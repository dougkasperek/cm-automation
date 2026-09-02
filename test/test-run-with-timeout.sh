#!/usr/bin/env bash
# Does run_with_timeout tell the caller WHY a call failed?
#
# Offline, no network, under a second. Split out from run-local-test.sh, which
# covers the same code path end to end but takes nearly two minutes because two
# mock sites hang on purpose.
#
# WHY THIS EXISTS. Until 2026-09-01 this function sent the child's stderr to
# /dev/null, so a timeout, a rate-limited reply, an auth failure and a malformed
# response all produced one empty string and one message. That day 22 of 49
# Pantheon sites failed their environment preflight and neither the log nor the
# ledger could say why, because the only evidence had been discarded here.
#
# It writes to a FILE and not a variable because every caller uses
# `$(run_with_timeout ...)`, which runs in a subshell, so a global set inside
# the function never reaches the caller.
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/common.sh

PASS=0; FAIL=0
check() { # check NAME EXPECTED ACTUAL
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf 'ok    %-58s %s\n' "$1" "$3"
  else FAIL=$((FAIL+1)); printf 'FAIL  %-58s expected [%s] got [%s]\n' "$1" "$2" "$3"; fi
}

RWT_ERR_FILE="$(mktemp)"; export RWT_ERR_FILE
trap 'rm -f "$RWT_ERR_FILE" "$RWT_ERR_FILE.status"' EXIT

echo "-- a call that times out --"
run_with_timeout 2 sleep 30 >/dev/null 2>&1; rc=$?
check "the return code is 124" "124" "$rc"
# 124 and "terminus exited 1" are different findings and the caller branches on
# this, so the status must survive the pipe into json_or_empty.
check "...and the status file says 124, not the pipe's status" "124" "$(cat "${RWT_ERR_FILE}.status" 2>/dev/null)"
case "$(cat "$RWT_ERR_FILE" 2>/dev/null)" in
  *"timeout"*) t=yes ;; *) t=no ;;
esac
check "...and stderr says it was killed on a timeout" "yes" "$t"

echo
echo "-- a call that fails with a real error --"
run_with_timeout 10 sh -c 'echo rate limited >&2; exit 7' >/dev/null 2>&1; rc=$?
check "the return code is the command's" "7" "$rc"
check "...and so is the status file" "7" "$(cat "${RWT_ERR_FILE}.status" 2>/dev/null)"
check "...and the message is kept, not discarded" "rate limited" "$(tr -d '\n' < "$RWT_ERR_FILE")"

echo
echo "-- a call that succeeds --"
out="$(run_with_timeout 10 sh -c 'echo hello')"; rc=$?
check "the return code is 0" "0" "$rc"
check "...stdout still reaches the caller" "hello" "$out"
check "...and the status file says 0" "0" "$(cat "${RWT_ERR_FILE}.status" 2>/dev/null)"
# THE ONE THAT MATTERS. The file is reused for every call in a 49-site run, so
# a stale message left by an earlier site would be reported against a later one.
check "...and stderr is TRUNCATED, so no stale error is inherited" "" "$(tr -d '\n' < "$RWT_ERR_FILE")"

echo
echo "-- with no RWT_ERR_FILE set, nothing breaks --"
( unset RWT_ERR_FILE
  o="$(run_with_timeout 10 sh -c 'echo quiet; echo noise >&2')"; r=$?
  [ "$r" = "0" ] && [ "$o" = "quiet" ] && echo "ok    a caller that does not ask for stderr still works       $o" \
    || echo "FAIL  a caller that does not ask for stderr still works" )

echo
echo "-- the preflight ceiling is not tighter than the other API calls --"
# THE MISTAKE THIS CATCHES. ENV_CHECK_TIMEOUT was 20 with the comment "API
# call, should be fast", while the other Pantheon API calls in the same script
# had 45. `terminus env:list` is the same kind of request and is not cheaper:
# measured on run health-2026-09-02_1147 across 49 sites, the median was 8s and
# 12 calls took 10s or more. Four runs that week each lost a different site to
# that ceiling.
#
# NOT an assertion that it equals 45. That is a number someone may have good
# reason to move. The property is that the env check never gets less headroom
# than the calls beside it.
_env=$(grep -E '^ENV_CHECK_TIMEOUT=' scripts/pantheon-fleet-healthcheck.sh | head -1 | sed 's/[^0-9]*\([0-9]*\).*/\1/')
_api=$(grep -E '^API_CALL_TIMEOUT=' scripts/pantheon-fleet-healthcheck.sh | head -1 | sed 's/[^0-9]*\([0-9]*\).*/\1/')
if [ -n "$_env" ] && [ -n "$_api" ] && [ "$_env" -ge "$_api" ]; then
  PASS=$((PASS+1)); printf 'ok    %-58s %s\n' "the env preflight gets at least the other API calls' ceiling" "${_env}s vs ${_api}s"
else
  FAIL=$((FAIL+1)); printf 'FAIL  %-58s env %ss is tighter than api %ss\n' "the env preflight gets at least the other API calls' ceiling" "$_env" "$_api"
fi

echo
echo "-------------------------------------------------------------------"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
