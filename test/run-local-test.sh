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

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$REPO_ROOT/test/mock:$PATH"
export PANTHEON_MACHINE_TOKEN="mock-token-not-real"
export MOCK_LOGGED_IN=0

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
  check "site count"                            "10"     "$(jq 'length' "$J")"
fi

# The uninitialized-env hang is a 600s sleep in the mock. If the preflight ever
# regresses and remote:wp is attempted, this run cannot finish quickly.
if [ "$ELAPSED" -lt 180 ]; then
  printf '  PASS  %-58s %ss\n' "run finished fast (no hang on uninitialized env)" "$ELAPSED"; PASS=$((PASS+1))
else
  printf '  FAIL  %-58s %ss\n' "run took too long - hang protection may have regressed" "$ELAPSED"; FAIL=$((FAIL+1))
fi

echo ""
echo "=== Case 2: --api-only (the first-CI-run mode) ====================="
"$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" --api-only --no-fail-on-crit --out "$TMP/api" >"$TMP/api.log" 2>&1
RC2=$?
J2="$(ls "$TMP"/api/fleet-health-*.json 2>/dev/null | head -n1)"
check "exit 0 with --no-fail-on-crit" "0" "$RC2"
if [ -n "$J2" ]; then
  check "coredrift NOT crit in api-only"  "false" "$(jq -r '.[]|select(.site=="coredrift")|.status=="CRIT"' "$J2")"
  check "staleback still CRIT (backup age is API data)" "CRIT" "$(status_of "$J2" staleback)"
  check "no site was wp_checked"          "0"     "$(jq '[.[]|select(.wp_checked==true)]|length' "$J2")"
fi

echo ""
echo "=== Case 3: subset + limit flags ==================================="
"$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" --api-only --no-fail-on-crit \
  --sites normalsite,staleback --out "$TMP/subset" >"$TMP/subset.log" 2>&1
J3="$(ls "$TMP"/subset/fleet-health-*.json 2>/dev/null | head -n1)"
[ -n "$J3" ] && check "--sites limits to 2 sites" "2" "$(jq 'length' "$J3")"

echo ""
echo "=== Case 4: bad machine token fails fast ==========================="
PANTHEON_MACHINE_TOKEN=BAD "$REPO_ROOT/scripts/pantheon-fleet-healthcheck.sh" \
  --api-only --out "$TMP/bad" >"$TMP/bad.log" 2>&1
check "exit 1 on auth failure" "1" "$?"

echo ""
echo "-------------------------------------------------------------------"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
