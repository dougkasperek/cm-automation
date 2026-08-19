#!/usr/bin/env bash
#
# publish-dashboard.sh
# Render the LEDGER-backed dashboard and push it to the hosted Worker.
#
#   FLEET_PUBLISH_URL=https://fleet.thudstaff.com \
#   FLEET_PUBLISH_TOKEN=xxxx \
#   ./scripts/publish-dashboard.sh
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

while [ $# -gt 0 ]; do
  case "$1" in
    --history)   HISTORY="$2"; shift 2 ;;
    --inventory) INVENTORY="$2"; shift 2 ;;
    # Render both artifacts and print where they landed, without publishing.
    # Use this to LOOK at the page before it goes live. Six of the nine bugs
    # this project has found were caught by a person reading a rendered page.
    --dry-run)   DRY_RUN=1; shift ;;
    -h|--help)   sed -n '2,40p' "$0"; exit 0 ;;
    *) err "unknown argument: $1"; err "this script takes no scan file; it renders from the ledger"; exit 1 ;;
  esac
done

require_tools python3 curl || exit 1

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

if [ "$DRY_RUN" -eq 0 ]; then
  : "${FLEET_PUBLISH_URL:?FLEET_PUBLISH_URL is not set (e.g. https://fleet.thudstaff.com)}"
  : "${FLEET_PUBLISH_TOKEN:?FLEET_PUBLISH_TOKEN is not set}"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  WORK="$REPO_ROOT/reports/publish-preview"
  mkdir -p "$WORK"
else
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
fi

log "Rendering from the ledger at $HISTORY ..."
# --strict: exit non-zero if the ledger holds a site the inventory does not.
# Publishing a page with an unresolvable row means putting a site with two
# histories in front of people, which is the 130-row failure going live.
python3 "$SCRIPT_DIR/render-dashboard.py" \
  --history "$HISTORY" \
  --inventory "$INVENTORY" \
  --out "$WORK/dashboard.html" \
  --emit-data "$WORK/latest.json" \
  --strict || { err "render failed; nothing published"; exit 1; }

if [ "$DRY_RUN" -eq 1 ]; then
  log ""
  log "Dry run. Nothing was published."
  log "  page: $WORK/dashboard.html"
  log "  data: $WORK/latest.json"
  log ""
  log "Open the page and read it before publishing for real."
  exit 0
fi

BASE="${FLEET_PUBLISH_URL%/}"
rc=0
for pair in "dashboard.html:text/html" "latest.json:application/json"; do
  name="${pair%%:*}"
  ctype="${pair##*:}"
  log "Publishing $name ..."
  code="$(curl -sS -o "$WORK/resp.txt" -w '%{http_code}' \
    -X PUT "$BASE/api/publish/$name" \
    -H "Authorization: Bearer $FLEET_PUBLISH_TOKEN" \
    -H "Content-Type: $ctype" \
    --data-binary "@$WORK/$name")" || code="000"
  if [ "$code" != "200" ]; then
    err "publish of $name failed with HTTP $code"
    sed -n '1,5p' "$WORK/resp.txt" >&2 2>/dev/null || true
    rc=1
  else
    log "  ok"
  fi
done

# Both objects or neither. The page and the feed are one render; shipping the
# page while the feed 500s leaves the API serving the PREVIOUS run's numbers
# beside a current page, and nothing on either would say so.
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
  python3 - "$WORK/latest.json" "$BASE" >> "$FLEET_PUBLISH_SUMMARY" <<'PY' || true
import json, sys
d = json.load(open(sys.argv[1]))
base = sys.argv[2]
h = d["health"]
print("## Dashboard published
")
print("<%s/>
" % base)
print("| state | sites |")
print("|---|---|")
for k, v in h["counts"].items():
    if v:
        print("| %s | %d |" % (k, v))
if h["excluded_sites"]:
    print("
Excluded from these counts (`production: false`): %s"
          % ", ".join("`%s`" % s for s in h["excluded_sites"]))
if h["unreviewed"]:
    print("
**%d site(s) still need a production ruling:** %s"
          % (len(h["unreviewed"]), ", ".join("`%s`" % s for s in h["unreviewed"])))
runs = d.get("runs", {})
if runs:
    print("
Rendered from: %s"
          % ", ".join("%s `%s`" % (k, v["run_id"]) for k, v in sorted(runs.items())))
PY
fi

log ""
log "Published. Dashboard is live at: $BASE/"
log "JSON feed:                       $BASE/api/fleet-scan"
exit 0
