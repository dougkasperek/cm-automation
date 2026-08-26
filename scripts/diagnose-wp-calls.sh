#!/usr/bin/env bash
#
# diagnose-wp-calls.sh
# Settles item 22: are the WP-CLI calls in the health scan SUCCEEDING and
# returning "nothing pending", or FAILING and being recorded as clean?
#
# READ-ONLY. Every call is a WP-CLI read. Nothing is written to any site.
#
# WHY THIS EXISTS
#
# `pantheon-fleet-healthcheck.sh` sets `wp_checked="true"` before the WP-CLI
# calls, then records:
#
#   wp_core_update  -> "up-to-date"  if the call returns nothing
#   plugin_updates  -> 0             if the call returns nothing
#   theme_updates   -> 0             if the call returns nothing
#
# Three different events land in each of those `else` branches and are then
# indistinguishable in the ledger:
#
#   1. the call ran and genuinely returned `[]`   -> a real measurement
#   2. the call timed out or exited non-zero      -> nobody measured anything
#   3. the call printed something that is not JSON, so json_or_empty rejected
#      it                                          -> nobody measured anything
#
# Only (1) justifies the clean value. On `health-2026-08-23_0111` five sites
# report `plugin_updates: 0`, and four of them report `wp_core_update:
# up-to-date` while running a WordPress below 7.1 -- including cm-whitelabel at
# 6.9.4, below the wp2shell floor. Nothing recorded separates a failed call
# from a genuinely current site, so the handoff refuses to change the defaults
# until someone MEASURES which it is. That is what this script does.
#
# IT KEEPS STDERR ON PURPOSE. `run_with_timeout` in lib/common.sh sends stderr
# to /dev/null, which is right for parsing and useless for diagnosis: the
# reason a call failed is the thing it throws away. This script captures
# stdout, stderr and the exit code separately. That is the ONLY intended
# difference from the scanner -- see the drift guard below.
#
# DRIFT GUARD. The WP-CLI argument lists are declared once, in WP_CALLS,
# and `test/test-wp-calls.py` asserts they are exactly the set the scanner
# invokes. A diagnostic that runs slightly different commands than the thing it
# is diagnosing answers a different question and looks like it answered this
# one. This repo has deleted one mirror already; this one is checked by a test
# rather than by memory.
#
# Usage:
#   ./scripts/diagnose-wp-calls.sh [--env live] [--json OUT.json] SITE [SITE...]
#
# Suggested first run -- the four sites the handoff names, plus a control that
# is known to have pending updates, so a run where EVERYTHING reads clean is
# recognisable as a broken run rather than as good news:
#   ./scripts/diagnose-wp-calls.sh cm-whitelabel sgroilawley
#
# EXIT CODES
#   0  every call on every site was a real measurement
#   1  could not start (missing tool, no Pantheon session, no sites given)
#   2  at least one call FABRICATED a clean value -- item 22 is live
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

TARGET_ENV="live"
JSON_OUT=""
# The join key problem, found the hard way on 2026-08-23. This script takes
# PANTHEON SITE NAMES, because that is what `terminus remote:wp SITE.env`
# wants. The ledger, the dashboard and every conversation about the fleet use
# DOMAINS. They are not the same string and four of the five sites worth
# diagnosing prove it: sgroilawley.com is `sgroifinancial`, lifebreath.com is
# `life-breath`. Passing the domain gets "A site named sgroilawley was not
# found", which this script originally reported as FABRICATED -- a typo dressed
# up as a fleet finding. The inventory holds both, so resolve rather than
# expecting anyone to remember.
INVENTORY="${INVENTORY:-$SCRIPT_DIR/../data/fleet-inventory.json}"
# Must match scripts/pantheon-fleet-healthcheck.sh. The DEFAULT is asserted by
# test/test-wp-calls.py against the scanner's value.
#
# Overridable only so the offline suite can exercise the timeout path in
# seconds instead of a minute. A real diagnosis must use the scanner's timeout,
# or a call this script calls slow is one the scanner would have completed.
WP_CLI_TIMEOUT="${WP_CLI_TIMEOUT_OVERRIDE:-60}"

# The five calls, exactly as the scanner makes them, one per line.
#
# They went from four to five on 2026-08-23 when the scanner started keeping a
# full component inventory instead of only the update backlog: the `--update=
# available` filters came off, --fields was pinned so update_version is
# present, and a second plugin call was added for must-use plugins, which
# `plugin list` never shows. test-wp-calls.py asserts this list and the
# scanner's calls are identical, and it caught this file being left behind.
#
# `core version` is here even though the scanner already handles its empty case
# correctly (`[ -z "$wp_version" ] && wp_version="unknown"`). It is the CONTROL:
# it uses the same SSH session as the other three, so if `core version` returns
# a version and `core check-update` returns nothing on the same site, the
# session worked and the empty result is a real answer. If both come back
# empty, the session is what failed. Without the control this script could not
# tell those apart either, which is the bug it is diagnosing.
WP_CALLS='core version
core check-update --format=json
plugin list --fields=name,status,update,version,update_version --format=json
plugin list --status=must-use --fields=name,status,version --format=json
theme list --fields=name,status,update,version,update_version --format=json
option get postman_options --format=json'

while [ $# -gt 0 ]; do
  case "$1" in
    --env)  TARGET_ENV="$2"; shift 2 ;;
    --json) JSON_OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
    -*) err "unknown option: $1"; exit 1 ;;
    *)  break ;;
  esac
done

[ $# -gt 0 ] || { err "no sites given. Usage: $0 [--env live] SITE [SITE...]"; exit 1; }

require_tools terminus jq || exit 1
pantheon_login || exit 1

# Domain or site_id -> Pantheon site name. Falls through unchanged when the
# inventory has no opinion, so a site that is not in it can still be diagnosed.
resolve_site() {
  local given="$1" hit
  [ -f "$INVENTORY" ] || { printf '%s' "$given"; return 0; }
  hit="$(jq -r --arg g "$given" \
    '.sites[]? | select(.host_site_name==$g) | .host_site_name' \
    "$INVENTORY" 2>/dev/null | head -1)"
  [ -n "$hit" ] && { printf '%s' "$hit"; return 0; }
  hit="$(jq -r --arg g "$given" \
    '.sites[]? | select(.domain==$g or .site_id==$g) | .host_site_name // empty' \
    "$INVENTORY" 2>/dev/null | head -1)"
  [ -n "$hit" ] && { printf '%s' "$hit"; return 0; }
  printf '%s' "$given"
}

# SSH PREFLIGHT. `terminus remote:wp` spawns ssh, and ssh reads a passphrase
# prompt from /dev/tty -- which the `< /dev/null` in run_capture does NOT
# suppress, because that only closes stdin. With no key in the agent, every one
# of the calls per site prompts, and any prompt left unanswered is killed
# by the timeout and reported as a failed call.
#
# That verdict would be true of the scanner as well, but it would be a finding
# about THIS LAPTOP'S ssh-agent, not about the fleet -- and this project has
# already sent someone to the wrong vendor that way once, when `probe` printed
# one word for a DNS failure, a TLS trust failure and a dead host alike and the
# fault turned out to be a missing CA bundle. A tool that reports absences has
# to classify its own failures too.
#
# A warning rather than a hard stop: a passphraseless key with no agent at all
# is the normal CI shape, and ssh-add -l fails there too.
AGENT_EMPTY=0
if ! ssh-add -l >/dev/null 2>&1; then
  AGENT_EMPTY=1
  warn "ssh-agent holds no identities."
  warn "  If your Pantheon key has a passphrase, EVERY call below will prompt,"
  warn "  and an unanswered prompt is killed after ${WP_CLI_TIMEOUT}s and reported"
  warn "  as a failed call -- which would be this laptop's fault, not a site's."
  warn "  Load it first, once:  ssh-add --apple-use-keychain ~/.ssh/id_rsa"
  warn "Continuing; timeouts in this run will be flagged as possibly local."
fi

# ---------------------------------------------------------------------------
# run_capture SECS OUT_FILE ERR_FILE CMD...
#
# run_with_timeout from lib/common.sh, with stderr kept instead of discarded.
# Returns the command's exit status, or 124 on timeout, exactly as it does.
#
# bash 3.2: no `timeout` binary, no `date -d`, no mapfile. Same contract as the
# rest of this repo.
# ---------------------------------------------------------------------------
run_capture() {
  local secs="$1" out="$2" errf="$3"; shift 3
  # stdin from /dev/null: `terminus remote:wp` spawns ssh, and ssh reads stdin.
  # The scanner solved this by reading its site list on FD 3 after a full-mode
  # scan of 52 sites silently scanned exactly one. This loop reads its sites
  # from "$@" so it is not exposed the same way, but a child that drains stdin
  # is a hazard worth closing off rather than reasoning about.
  "$@" > "$out" 2> "$errf" < /dev/null &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 1
    waited=$((waited+1))
    if [ "$waited" -ge "$secs" ]; then
      # Silence the shell's own "Terminated: 15" job-control line while the
      # killed job is reaped. `wait 2>/dev/null` does not suppress it -- the
      # message comes from THIS shell, not from the child -- and in a report
      # whose entire purpose is to be read carefully, a stray line that looks
      # like output from the command under test is worse than useless.
      # run_with_timeout in lib/common.sh has the same behaviour; there it
      # lands in a scan log nobody reads line by line.
      exec 3>&2 2>/dev/null
      kill -TERM "$pid" 2>/dev/null
      sleep 1
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      exec 2>&3 3>&-
      return 124
    fi
  done
  wait "$pid" 2>/dev/null
  return $?
}

# What the SCANNER would record for this call, given what came back.
# Mirrors the scanner's branches literally so the verdict is about the scanner,
# not about this script's opinion of it.
scanner_would_record() {
  local call="$1" parsed="$2"
  case "$call" in
    "core version")
      [ -n "$parsed" ] && printf 'wp_version=<the version>' \
                       || printf 'wp_version=unknown' ;;
    "core check-update"*)
      if [ -n "$parsed" ] && [ "$parsed" != "[]" ]; then
        printf 'wp_core_update=<the available version>'
      else
        printf 'wp_core_update=up-to-date'
      fi ;;
    "plugin list --status=must-use"*)
      if [ -n "$parsed" ] && [ "$parsed" != "[]" ]; then
        printf 'mu-plugins=<count> into the component inventory'
      else
        printf 'no mu-plugins recorded'
      fi ;;
    "plugin list"*)
      # The count is now DERIVED from the full list by selecting
      # update=="available", so a non-empty result no longer means updates are
      # pending -- it means the site was inventoried.
      if [ -n "$parsed" ] && [ "$parsed" != "[]" ]; then
        printf 'plugin_updates=<those with update=available>, inventory kept'
      else
        printf 'plugin_updates=unknown, no inventory'
      fi ;;
    "theme list"*)
      if [ -n "$parsed" ] && [ "$parsed" != "[]" ]; then
        printf 'theme_updates=<those with update=available>, inventory kept'
      else
        printf 'theme_updates=unknown, no inventory'
      fi ;;
  esac
}

trunc() { cut -c1-400 | head -6; }

any_fabricated=0
any_timeout=0
any_notasite=0
json_rows=""

for given in "$@"; do
  site="$(resolve_site "$given")"
  se="$site.$TARGET_ENV"
  if [ "$site" != "$given" ]; then
    printf '\n===== %s  (you said %s; the inventory calls it %s on Pantheon) =====\n' \
           "$se" "$given" "$site"
  else
    printf '\n===== %s =====\n' "$se"
  fi

  while IFS= read -r call; do
    [ -z "$call" ] && continue
    out_f="$(mktemp)"; err_f="$(mktemp)"

    started=$SECONDS
    # shellcheck disable=SC2086
    run_capture "$WP_CLI_TIMEOUT" "$out_f" "$err_f" \
      terminus remote:wp "$se" -- $call
    rc=$?
    elapsed=$((SECONDS - started))

    raw="$(cat "$out_f")"
    errtxt="$(cat "$err_f")"
    cleaned="$(printf '%s' "$raw" | strip_noise)"

    # json_or_empty's two conditions, evaluated separately so the report can
    # say WHICH one rejected the output. The scanner only sees "empty".
    if [ -z "$cleaned" ]; then
      parsed=""; why="nothing left after strip_noise"
    elif printf '%s' "$cleaned" | jq empty >/dev/null 2>&1; then
      parsed="$cleaned"; why="valid JSON"
    else
      parsed=""; why="NOT JSON -- json_or_empty would reject this"
    fi

    # `core version` is plain text, not JSON, and the scanner greps it for a
    # version rather than parsing it. Judge it the way the scanner does.
    if [ "$call" = "core version" ]; then
      parsed="$(printf '%s' "$cleaned" | tr -d '\r' | grep -Eom1 '[0-9]+(\.[0-9]+)+')" || parsed=""
      [ -n "$parsed" ] && why="version matched: $parsed" || why="no version in the output"
    fi

    # THE VERDICT. A clean value is only a measurement when the call actually
    # succeeded and returned a parseable answer -- including an empty one.
    # NOT A FINDING ABOUT THE FLEET. Terminus could not find a site by this
    # name, so nothing was measured and nothing was fabricated -- the input was
    # wrong. Calling this FABRICATED, as this script did on its first real run,
    # puts a typo in the same column as a site whose plugin count is a lie.
    if printf '%s' "$errtxt" | grep -qE 'was not found|Could not locate a site'; then
      verdict="NOT-A-SITE"; cause="no Pantheon site by this name"
      any_notasite=1
    elif [ "$rc" -eq 124 ]; then
      verdict="FABRICATED"; cause="TIMED OUT after ${WP_CLI_TIMEOUT}s"
      any_timeout=1
    elif [ "$rc" -ne 0 ]; then
      verdict="FABRICATED"; cause="exit $rc"
    elif [ "$call" != "core version" ] && [ -z "$parsed" ]; then
      verdict="FABRICATED"; cause="$why"
    elif [ "$call" = "core version" ] && [ -z "$parsed" ]; then
      verdict="FABRICATED"; cause="$why"
    elif [ "$parsed" = "[]" ]; then
      verdict="MEASURED"; cause="genuinely nothing pending"
    else
      verdict="MEASURED"; cause="returned data"
    fi
    [ "$verdict" = "FABRICATED" ] && any_fabricated=1

    printf -- '--- wp %s\n' "$call"
    printf '    exit=%s  elapsed=%ss  stdout=%s bytes  stderr=%s bytes\n' \
           "$rc" "$elapsed" "${#raw}" "${#errtxt}"
    printf '    after strip_noise: %s\n' "$why"
    if [ -n "$raw" ]; then
      printf '    stdout: '; printf '%s' "$raw" | trunc | sed '2,$s/^/            /'
      printf '\n'
    fi
    if [ -n "$errtxt" ]; then
      # The line the scanner throws away, and usually the whole answer.
      printf '    stderr: '; printf '%s' "$errtxt" | trunc | sed '2,$s/^/            /'
      printf '\n'
    fi
    printf '    => %s (%s)\n' "$verdict" "$cause"
    # Deliberately silent for NOT-A-SITE. The scanner iterates Pantheon's own
    # site:list, so it never asks about a name that does not exist -- saying
    # "the scanner records: theme_updates=0" would invent a consequence.
    if [ "$verdict" != "NOT-A-SITE" ]; then
      printf '       the scanner records: %s\n' "$(scanner_would_record "$call" "$parsed")"
    fi

    json_rows="$json_rows$(jq -nc \
      --arg site "$site" --arg env "$TARGET_ENV" --arg call "$call" \
      --argjson rc "$rc" --argjson elapsed "$elapsed" \
      --arg verdict "$verdict" --arg cause "$cause" \
      --arg stdout "$raw" --arg stderr "$errtxt" \
      --arg records "$(scanner_would_record "$call" "$parsed")" \
      '{site:$site,env:$env,call:$call,exit_code:$rc,elapsed_s:$elapsed,
        verdict:$verdict,cause:$cause,scanner_records:$records,
        stdout:$stdout,stderr:$stderr}')
"
    rm -f "$out_f" "$err_f"
  done <<EOF
$WP_CALLS
EOF
done

if [ -n "$JSON_OUT" ]; then
  printf '%s' "$json_rows" | jq -s '.' > "$JSON_OUT"
  log "wrote $JSON_OUT"
fi

printf '\n=====================================================\n'
if [ "$any_notasite" -eq 1 ]; then
  printf 'ONE OR MORE NAMES WERE NOT PANTHEON SITES. That is an input error,\n'
  printf 'not a finding: nothing was measured for them, so nothing about them\n'
  printf 'was fabricated either. This script takes PANTHEON SITE NAMES, which\n'
  printf 'are not the domains the ledger and the dashboard use -- sgroilawley.com\n'
  printf 'is `sgroifinancial`, lifebreath.com is `life-breath`. Pass the domain\n'
  printf 'and it will be translated; pass a name in neither column and it will\n'
  printf 'reach Pantheon as typed.\n\n'
fi
if [ "$any_fabricated" -eq 1 ]; then
  printf 'ITEM 22 IS LIVE: at least one call failed and the scanner would have\n'
  printf 'recorded a clean value for it. The defaults need to become "unknown".\n'
  if [ "$any_timeout" -eq 1 ] && [ "$AGENT_EMPTY" -eq 1 ]; then
    printf '\nBUT READ THIS FIRST. Calls timed out AND ssh-agent held no identities\n'
    printf 'when this run started. If your Pantheon key has a passphrase, those\n'
    printf 'timeouts are ssh waiting on a prompt on THIS MACHINE, not a site\n'
    printf 'failing to answer. That is a local fault wearing a fleet finding\x27s\n'
    printf 'clothes. Run:  ssh-add --apple-use-keychain ~/.ssh/id_rsa\n'
    printf 'then run this again before recording anything about item 22.\n'
  fi
  exit 2
fi
if [ "$any_notasite" -eq 1 ]; then
  exit 1
fi
printf 'Every call was a real measurement. The clean values in the ledger are\n'
printf 'answers, not silence -- item 22 is theoretical on these sites.\n'
printf 'This is evidence about THESE sites on THIS run, not a proof about the\n'
printf 'fleet: run it again on a site that is behaving differently before\n'
printf 'concluding the defaults are safe.\n'
exit 0
