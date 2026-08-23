#!/usr/bin/env bash
#
# publish-dashboard.sh
# Render the LEDGER-backed dashboard and upload it to R2.
#
#   CLOUDFLARE_API_TOKEN=xxxx \
#   CLOUDFLARE_ACCOUNT_ID=xxxx \
#   ./scripts/publish-dashboard.sh
#
#   ./scripts/publish-dashboard.sh --dry-run    # render only, look at it first
#
# It takes NO scan file. That is the change made 2026-08-19 and the reason this
# script existed in a broken state for a month.
#
# WHAT WAS WRONG
# --------------
# This used to run `render-fleet-dashboard.py <scan.json>`: the v1 renderer,
# which draws ONE scan and knows nothing about history. Both it and the
# Worker's /api/fleet-scan route predate the ledger. Running this script as it
# stood would have published the wrong dashboard - a single-run snapshot, with
# no change detection, no email/DNS data, and 52 sites instead of 84 - to a
# hostname people were about to be pointed at.
#
# It now renders from the ledger in history/, which is the same input the local
# `fleet.html` is built from, so what is published is what you reviewed.
#
# `render-fleet-dashboard.py` is NOT dead and must not be deleted:
# `serve-dashboard.py` imports it for the live local view that fills in site by
# site WHILE a scan runs. Two renderers, on purpose. See docs/DASHBOARD-V2.md.
#
# THE TWO ARTIFACTS COME FROM ONE RENDER
# --------------------------------------
# `--emit-data` writes the JSON feed from the same model object that produced
# the HTML. The v1 pair was built by two code paths, which is how a live JSON
# endpoint ends up disagreeing with the page sitting next to it. Here they
# cannot: if the feed is wrong, the page is wrong identically, and looking at
# the page catches both.
#
# IT UPLOADS STRAIGHT TO R2, NOT THROUGH THE WORKER
# -------------------------------------------------
# Changed 2026-08-19. It used to PUT to the Worker's /api/publish route with a
# bearer token. That route sits behind the hostname, and the hostname is behind
# Cloudflare Access, so a machine publishing had to cross TWO auth layers and
# needed an Access service token with a correctly ordered Service Auth policy
# just to reach a token check it would then also have to pass.
#
# Writing to the bucket directly removes the whole problem:
#   - no Access interaction, so no service token and no policy ordering
#   - no PUBLISH_TOKEN
#   - and no write endpoint on a public hostname at all, which is the real
#     win: the Worker is now strictly read-only.
#
# Access still fronts the hostname for PEOPLE. That part was never the problem
# and it stays.
#
# Portability: bash 3.2 compatible. See scripts/lib/common.sh for the contract.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

HISTORY="${FLEET_HISTORY_DIR:-$REPO_ROOT/history}"
INVENTORY="${FLEET_INVENTORY:-$REPO_ROOT/data/fleet-inventory.json}"
DRY_RUN=0
ALLOW_DROP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --history)   HISTORY="$2"; shift 2 ;;
    --inventory) INVENTORY="$2"; shift 2 ;;
    # Render both artifacts and print where they landed, without publishing.
    # Use this to LOOK at the page before it goes live. Six of the nine bugs
    # this project has found were caught by a person reading a rendered page.
    --dry-run)   DRY_RUN=1; shift ;;
    # Publish even though the latest run of a source measured fewer sites
    # than the run before it. Deliberately a flag and not a prompt: the
    # answer should be recorded in whatever ran this, not typed once and
    # forgotten.
    --allow-coverage-drop) ALLOW_DROP=1; shift ;;
    -h|--help)   sed -n '2,40p' "$0"; exit 0 ;;
    *) err "unknown argument: $1"; err "this script takes no scan file; it renders from the ledger"; exit 1 ;;
  esac
done

require_tools python3 || exit 1

if [ ! -d "$HISTORY" ]; then
  err "no ledger at $HISTORY"
  err "run: ./scripts/fleet-ledger.py ingest --reports ./reports --history ./history"
  exit 1
fi

if [ ! -f "$INVENTORY" ]; then
  # Rendering without the inventory is what produced a 130-row page for an
  # 84-site fleet on 2026-08-18. It is a hard error, not a warning.
  err "no inventory at $INVENTORY"
  exit 1
fi

# CREDENTIALS: a token if there is one, otherwise your wrangler login.
#
# CI must use a token -- there is no browser on a runner to log in with. A
# LAPTOP already has a wrangler OAuth session (it is what `wrangler deploy`
# uses), and requiring a token there meant re-pasting a 53-character secret
# into every new shell. That is friction that ends with the token in a dotfile.
# Added 2026-08-20 after exactly that happened twice in one session.
#
# Precedence is wrangler's, not ours: wrangler prefers CLOUDFLARE_API_TOKEN
# over the OAuth session whenever the variable is set, so all this block does
# is decide whether to REQUIRE it. A junk token still fails, and fails with a
# 401 rather than falling back -- which is correct. A publish that silently
# used a different identity than the one you named would be worse than one
# that stops.
if [ "$DRY_RUN" -eq 0 ]; then
  require_tools wrangler || exit 1
  WHO="${TMPDIR:-/tmp}/cm-whoami.$$"

  if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
    AUTH_AS="CLOUDFLARE_API_TOKEN"
    : "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is not set (see: wrangler whoami)}"
  else
    # No token. Fall back to the logged-in session, but PROVE it exists first
    # rather than letting the upload fail later with a 401 that reads like a
    # permissions problem when it is really "you are not logged in".
    if ! wrangler whoami >"$WHO" 2>&1; then
      err "no CLOUDFLARE_API_TOKEN, and wrangler is not logged in either."
      err ""
      err "  Either:  wrangler login                     (laptop, opens a browser)"
      err "  or:      export CLOUDFLARE_API_TOKEN=...    (CI, or a headless box)"
      err ""
      awk 'NR<=6 {print "        " $0}' "$WHO" >&2 2>/dev/null || true
      rm -f "$WHO"
      exit 1
    fi
    AUTH_AS="your wrangler login"

    if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
      # wrangler whoami prints account ids in a table; pull one out so the
      # caller does not have to know it. If the login can reach more than one
      # account, wrangler cannot guess and neither can this script. Picking the
      # first would be a confident value standing in for a decision, and it
      # would publish to the wrong account without saying so.
      n_acct="$(grep -o -E '[0-9a-f]{32}' "$WHO" | sort -u | wc -l | tr -d ' ')"
      if [ "$n_acct" = "1" ]; then
        CLOUDFLARE_ACCOUNT_ID="$(grep -o -E '[0-9a-f]{32}' "$WHO" | head -n1)"
        export CLOUDFLARE_ACCOUNT_ID
        log "Using account $CLOUDFLARE_ACCOUNT_ID from your wrangler login."
      else
        err "your wrangler login can reach $n_acct accounts, so this script"
        err "will not pick one. Set CLOUDFLARE_ACCOUNT_ID explicitly."
        err "Candidates:"
        grep -o -E '[0-9a-f]{32}' "$WHO" | sort -u | awk '{print "        " $0}' >&2
        rm -f "$WHO"
        exit 1
      fi
    fi
    rm -f "$WHO"
  fi
  log "Authenticating with $AUTH_AS."
fi

# Where the objects land. The Worker reads exactly these two keys, so changing
# either here without changing ci/cloudflare/cm-fleet-worker.js publishes into
# a void that returns the "nothing published yet" page.
R2_BUCKET="${FLEET_R2_BUCKET:-dash-data}"
R2_PREFIX="fleet/"

if [ "$DRY_RUN" -eq 1 ]; then
  WORK="$REPO_ROOT/reports/publish-preview"
  mkdir -p "$WORK"
else
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
fi

# Coverage going DOWN, checked BEFORE anything is uploaded.
#
# ingest already refuses a drop, and in CI that is enough because the publish
# job is gated on the persist job succeeding. It is not enough here: ingest and
# publish can happen in different sessions, and this script renders the LATEST
# run per source. That is how two 38-of-78 consent runs replaced a 54-of-78 run
# on the live page for a day.
#
# The rendered page SAYS SO too -- see render-dashboard.py -- because a page
# that shows a worse view honestly is fine and a page that shows it silently is
# not. This check is the second line: it stops the replacement happening at all
# unless somebody said to.
DROPS="$(python3 - "$HISTORY" "$SCRIPT_DIR" <<'PYEOF'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location(
    "ledger", os.path.join(sys.argv[2], "fleet-ledger.py"))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
runs, _ = L.load_ledger(sys.argv[1])
for g in L.coverage_regressions(runs):
    print("%s: %d of %d measured, was %d in %s (-%d)"
          % (g["source"], g["deep_scanned"], g["site_count"] or 0,
             g["previous_deep_scanned"], g["previous_run_id"], g["lost"]))
PYEOF
)" || { err "could not check coverage; nothing published"; exit 1; }

if [ -n "$DROPS" ]; then
  err ""
  err "COVERAGE DROPPED. The latest run of a source measured fewer sites than the run before it:"
  printf '%s\n' "$DROPS" | sed 's/^/  /' >&2
  err ""
  err "Publishing now would replace a better measurement with a worse one on the live page."
  err "The rendered page does say so, but the number people read would still go backwards."
  err ""
  if [ "$ALLOW_DROP" -eq 1 ]; then
    err "--allow-coverage-drop was passed; publishing anyway."
    err ""
  else
    err "Re-run the scan, or pass --allow-coverage-drop if the drop is real and expected."
    exit 1
  fi
fi

log "Rendering from the ledger at $HISTORY ..."
# --strict: exit non-zero if the ledger holds a site the inventory does not.
# Publishing a page with an unresolvable row means putting a site with two
# histories in front of people, which is the 130-row failure going live.
python3 "$SCRIPT_DIR/render-dashboard.py" \
  --history "$HISTORY" \
  --inventory "$INVENTORY" \
  --out "$WORK/dashboard.html" \
  --components-out "$WORK/components.html" \
  --emit-data "$WORK/latest.json" \
  --strict || { err "render failed; nothing published"; exit 1; }

if [ "$DRY_RUN" -eq 1 ]; then
  log ""
  log "Dry run. Nothing was published."
  log "  page: $WORK/dashboard.html"
  log "  components: $WORK/components.html"
  log "  data: $WORK/latest.json"
  log ""
  log "Open the page and read it before publishing for real."
  exit 0
fi

rc=0
# components.html ships in the SAME loop as the page that links to it. If it
# were published separately, or conditionally, the fleet table's plugin count
# would point at a 404 for however long the two were out of step -- the same
# shape as the ledger moving while the dashboard did not.
for pair in "dashboard.html:text/html" "components.html:text/html" \
            "latest.json:application/json"; do
  name="${pair%%:*}"
  ctype="${pair##*:}"
  key="${R2_PREFIX}${name}"
  log "Uploading $key ..."

  # --remote is load-bearing. Without it wrangler writes to the LOCAL
  # miniflare simulation in .wrangler/ and reports success, so the command
  # looks like it published and nothing reaches Cloudflare. A confident
  # success message standing in for no action is this project's oldest bug;
  # the read-back below is what proves it did not happen here.
  if wrangler r2 object put "${R2_BUCKET}/${key}" \
       --file "$WORK/$name" \
       --content-type "$ctype" \
       --remote >"$WORK/put.log" 2>&1; then
    log "  uploaded"
  else
    err "upload of $key failed"
    awk 'NR<=12 {print "        " $0}' "$WORK/put.log" >&2 2>/dev/null || true
    err "        Check that CLOUDFLARE_API_TOKEN has R2 read AND write on"
    err "        account $CLOUDFLARE_ACCOUNT_ID, and that the bucket"
    err "        '$R2_BUCKET' exists."
    rc=1
    continue
  fi

  # Read it back and compare sizes. Verifying after deploy is a standing rule
  # in this account after a Worker shipped a wrong number and nobody checked.
  if wrangler r2 object get "${R2_BUCKET}/${key}" \
       --file "$WORK/verify-$name" --remote >"$WORK/get.log" 2>&1; then
    want="$(wc -c < "$WORK/$name" | tr -d ' ')"
    got="$(wc -c < "$WORK/verify-$name" | tr -d ' ')"
    if [ "$want" = "$got" ]; then
      log "  verified ${got} bytes"
    else
      err "$key read back as $got bytes, expected $want"
      rc=1
    fi
  else
    err "$key uploaded but could not be read back; treat it as unpublished"
    rc=1
  fi
done

if [ "$rc" -ne 0 ]; then
  err ""
  err "PARTIAL PUBLISH. The page and the JSON feed may now disagree."
  err "Fix the cause and re-run; this script is idempotent."
  exit "$rc"
fi

# Optional markdown summary of what went live. CI points this at
# $GITHUB_STEP_SUMMARY so the run record states the numbers, rather than
# requiring someone to open the page to find out what was published. Kept here
# rather than in the workflow because the workflow is platform glue only.
if [ -n "${FLEET_PUBLISH_SUMMARY:-}" ]; then
  summary_rc=0
  python3 - "$WORK/latest.json" "${FLEET_PUBLIC_URL:-https://fleet.thudstaff.com}" \
      >> "$FLEET_PUBLISH_SUMMARY" <<'PY' || summary_rc=$?
import json, sys

d = json.load(open(sys.argv[1]))
base = sys.argv[2].rstrip("/")
h = d["health"]

# Bare print() for blank lines rather than a trailing escape inside a string.
# The first version used "\n" inside these literals and the generator that
# wrote this file turned them into real newlines, producing an unterminated
# string literal. The publish had already succeeded, so the job went green with
# no summary at all.
print("## Dashboard published")
print()
print("<%s/>" % base)
print()
print("| state | sites |")
print("|---|---|")
for k, v in h["counts"].items():
    if v:
        print("| %s | %d |" % (k, v))

if h["excluded_sites"]:
    print()
    print("Excluded from these counts (`production: false`): %s"
          % ", ".join("`%s`" % s for s in h["excluded_sites"]))

if h["unreviewed"]:
    print()
    print("**%d site(s) still need a production ruling:** %s"
          % (len(h["unreviewed"]), ", ".join("`%s`" % s for s in h["unreviewed"])))

runs = d.get("runs", {})
if runs:
    print()
    print("Rendered from: %s"
          % ", ".join("%s `%s`" % (k, v["run_id"]) for k, v in sorted(runs.items())))
PY

  # A summary that fails must SAY so. The first version ended in `|| true`, so
  # a SyntaxError in the block above printed a traceback into the log and the
  # step still reported success with the summary silently missing. The publish
  # itself has already succeeded by this point, so this is a warning and not a
  # failure, but it is not nothing.
  if [ "$summary_rc" -ne 0 ]; then
    err "the run summary could not be generated (exit $summary_rc)."
    err "The publish itself SUCCEEDED; only the summary is missing."
  fi
fi

PUBLIC="${FLEET_PUBLIC_URL:-https://fleet.thudstaff.com}"
log ""
log "Published. Dashboard is live at: ${PUBLIC%/}/"
log "JSON feed:                       ${PUBLIC%/}/api/fleet-scan"
log "(both behind Cloudflare Access, so open them in a browser, not curl)"
exit 0
