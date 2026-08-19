#!/usr/bin/env bash
#
# test/run-local-test.sh
# Runs the healthcheck against the mock terminus and asserts the results.
# No network, no Pantheon account, no SSH key required.
#
#   ./test/run-local-test.sh
#
# This is the gate to run before pushing a script change. It is also what the
# CI workflow runs on pull requests, so a broken script fails in seconds
# instead of failing halfway through a 54-site production scan.
#
set -uo pipefail

# STDIN MUST NOT BE A TERMINAL. The mock's `remote:wp` drains stdin on purpose,
# because the real `terminus remote:wp` spawns ssh and ssh reads stdin -- that
# is the 2026-08-18 bug where a scan of ten sites silently scanned one. When
# this script is run from an interactive shell, that `cat` blocks on the
# keyboard and every WP-CLI call sits there until the 60s timeout kills it:
# 20 calls, ~21 minutes, and four failures that all read as "the version could
# not be determined" rather than as a hang.
#
# Redirecting from /dev/null makes the drain return at EOF immediately. It does
# NOT weaken the regression check: the here-doc the site loop reads is created
# inside the healthcheck script, so if that loop ever goes back to stdin the
# mock still eats it and the test still catches it.
exec </dev/null

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$REPO_ROOT/test/mock:$PATH"
export PANTHEON_MACHINE_TOKEN="mock-token-not-real"
export MOCK_LOGGED_IN=0
# Each case gets its own empty session file, so a login in one case cannot make
# the next case look authenticated. Case 4 in particular must start with none.
new_session() { export MOCK_SESSION_FILE="$TMP/session-$1"; : > "$MOCK_SESSION_FILE"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf '  PASS  %-58s %s\n' "$label" "$actual"; PASS=$((PASS+1))
  else
    printf '  FAIL  %-58s expected=%s actual=%s\n' "$label" "$expected" "$actual"; FAIL=$((FAIL+1))
  fi
}

status_of() { jq -r --arg s "$2" '.[]|select(.site==$s)|.status' "$1"; }

echo "=== Case 1: full scan, fail-on-crit ON (default) ==================="
echo "    (1-3 min, silent: two mock sites hang on purpose to prove the timeout"
echo "     guard works. Output goes to a temp log, not here.)"
new_session 1
START="$(date +%s)"
"$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" --out "$TMP/full" >"$TMP/full.log" 2>&1
RC=$?
ELAPSED=$(( $(date +%s) - START ))
J="$(ls "$TMP"/full/fleet-health-*.json 2>/dev/null | head -n1)"

check "exit code is 2 (CRIT present)" "2" "$RC"
if [ -z "$J" ]; then
  echo "  FAIL  no JSON output produced"; FAIL=$((FAIL+1))
else
  check "normalsite healthy"                    "OK"     "$(status_of "$J" normalsite)"
  check "staleback CRIT (10d old backup)"       "CRIT"   "$(status_of "$J" staleback)"
  check "coredrift CRIT (WP core update)"       "CRIT"   "$(status_of "$J" coredrift)"
  check "plugindrift WARN (plugins+upstream)"   "WARN"   "$(status_of "$J" plugindrift)"
  check "frozensite FROZEN"                     "FROZEN" "$(status_of "$J" frozensite)"
  check "pfannenbergpartners SKIP (uninit env)" "SKIP"   "$(status_of "$J" pfannenbergpartners)"
  check "ghostenv SKIP (no live env)"           "SKIP"   "$(status_of "$J" ghostenv)"
  check "timeoutsite ERROR not SKIP"            "ERROR"  "$(status_of "$J" timeoutsite)"
  check "noisysite parsed despite stdout noise" "OK"     "$(status_of "$J" noisysite)"
  check "drupalsite scanned, WP checks n/a"     "n/a"    "$(jq -r '.[]|select(.site=="drupalsite")|.wp_core_update' "$J")"

  # The observed WordPress version, added 2026-08-18. check-update alone only
  # ever says whether something is PENDING, so a fleet claimed to be on 7.0.2
  # read as "up-to-date" everywhere and the claim stayed unverified.
  ver_of() { jq -r --arg s "$1" '.[]|select(.site==$s)|.wp_version' "$J"; }
  check "normalsite reports its installed version" "7.0.2"   "$(ver_of normalsite)"
  check "coredrift is BEHIND what it can update to" "6.8.1"  "$(ver_of coredrift)"
  check "noisysite version survives stdout noise"  "7.0.2"   "$(ver_of noisysite)"
  check "staleback silent -> unknown, not a value" "unknown" "$(ver_of staleback)"
  check "drupalsite not asked -> n/a, not unknown" "n/a"     "$(ver_of drupalsite)"

  # A row that exited before the WP stage carries NO wp_version key at all.
  # Absent means the row never reached the question; "n/a" means it reached it
  # and did not ask; "unknown" means it asked and got nothing. Three different
  # states, and collapsing any two of them is how this project has produced
  # every wrong number it has produced.
  check "frozensite has no wp_version key"      "null"   "$(jq -r '.[]|select(.site=="frozensite")|.wp_version' "$J")"
  check "site count"                            "10"     "$(jq 'length' "$J")"

  # THE REGRESSION TEST FOR THE 2026-08-18 STDIN BUG.
  # terminus remote:wp spawns ssh, ssh reads stdin, and the per-site loop used
  # to read its site list FROM stdin - so ssh ate the remaining sites on the
  # first one and every full-mode scan ever run stopped after one site while
  # reporting the requested count. The loop now reads on fd 3. The mock drains
  # stdin the way ssh does, so this fails if the descriptor is ever taken away.
  M="${J%.json}.md"
  check "the digest counts rows scanned, not rows requested" "10" \
        "$(grep -oE 'Scanned \*\*[0-9]+\*\*' "$M" | grep -oE '[0-9]+')"
  check "and claims no incompleteness when there is none" "0" \
        "$(grep -c 'produced no row at all' "$M")"
fi

# The uninitialized-env hang is a 600s sleep in the mock. If the preflight ever
# regresses and remote:wp is attempted, this run cannot finish quickly.
if [ "$ELAPSED" -lt 180 ]; then
  printf '  PASS  %-58s %ss\n' "run finished fast (no hang on uninitialized env)" "$ELAPSED"; PASS=$((PASS+1))
else
  printf '  FAIL  %-58s %ss\n' "run took too long - hang protection may have regressed" "$ELAPSED"
  # ~1300s with every wp_version reading "unknown" is the signature of stdin
  # being a terminal, not of the timeout guard regressing. See `exec </dev/null`
  # at the top of this file.
  printf '        %s\n' "~1300s + unknown versions => stdin was a TTY, not a guard failure"
  FAIL=$((FAIL+1))
fi

echo ""
echo "=== Case 2: --api-only (the first-CI-run mode) ====================="
new_session 2
"$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" --api-only --no-fail-on-crit --out "$TMP/api" >"$TMP/api.log" 2>&1
RC2=$?
J2="$(ls "$TMP"/api/fleet-health-*.json 2>/dev/null | head -n1)"
check "exit 0 with --no-fail-on-crit" "0" "$RC2"
if [ -n "$J2" ]; then
  check "coredrift NOT crit in api-only"  "false" "$(jq -r '.[]|select(.site=="coredrift")|.status=="CRIT"' "$J2")"
  check "staleback still CRIT (backup age is API data)" "CRIT" "$(status_of "$J2" staleback)"
  check "no site was wp_checked"          "0"     "$(jq '[.[]|select(.wp_checked==true)]|length' "$J2")"
  # api-only never opens an SSH connection, so no row may carry a version and
  # none may say "unknown" either - "unknown" would claim the scan tried and
  # could not tell. The only permitted values are "n/a" on a scanned row and
  # the field being absent on a row that exited early (FROZEN / SKIP / ERROR),
  # which is why this counts violations rather than counting "n/a".
  check "api-only never reports a version or unknown" "0" \
        "$(jq '[.[]|select(.wp_version!=null and .wp_version!="n/a")]|length' "$J2")"
  check "scanned rows in api-only all say n/a" "0" \
        "$(jq '[.[]|select(.wp_checked!=null and .wp_version!="n/a")]|length' "$J2")"
fi

echo ""
echo "=== Case 3: subset + limit flags ==================================="
new_session 3
"$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" --api-only --no-fail-on-crit \
  --sites normalsite,staleback --out "$TMP/subset" >"$TMP/subset.log" 2>&1
J3="$(ls "$TMP"/subset/fleet-health-*.json 2>/dev/null | head -n1)"
[ -n "$J3" ] && check "--sites limits to 2 sites" "2" "$(jq 'length' "$J3")"

echo ""
echo "=== Case 4: bad machine token fails fast ==========================="
new_session 4
PANTHEON_MACHINE_TOKEN=BAD "$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" \
  --api-only --out "$TMP/bad" >"$TMP/bad.log" 2>&1
check "exit 1 on auth failure" "1" "$?"

echo ""
echo "=== Case 5: auth:whoami exits 0 but reports nobody ================="
# THE REGRESSION TEST FOR THE 2026-08-18 CI FAILURE.
#
# On a GitHub runner `terminus auth:whoami` exits 0 with no output when there
# is no session at all. pantheon_login used to read only the exit code, so it
# logged "already authenticated", never called auth:login, and site:list came
# back empty. The job failed in seconds with "no sites returned" and three
# guesses as to why. It works on a laptop because the cached session makes the
# early return genuinely correct there, which is why nothing caught it for
# weeks.
#
# The check must read the IDENTITY, not the status. With a valid token this
# run has to authenticate and complete normally.
new_session 5
MOCK_WHOAMI_SILENT_OK=1 "$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" \
  --api-only --no-fail-on-crit --sites normalsite --out "$TMP/silent" \
  >"$TMP/silent.log" 2>&1
RC5=$?
J5="$(ls "$TMP"/silent/fleet-health-*.json 2>/dev/null | head -n1)"
check "a silent whoami does not pass for a session" "0" "$RC5"
check "the token is used, so the fleet is not empty" "1" "$(jq 'length' "$J5" 2>/dev/null || echo 0)"
check "and the log says who it authenticated AS" "1" \
      "$(grep -c 'authenticated as ci@clevermethod.com' "$TMP/silent.log")"

echo ""
echo "-------------------------------------------------------------------"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
