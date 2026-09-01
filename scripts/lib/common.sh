#!/usr/bin/env bash
#
# scripts/lib/common.sh
# CleverMethod automation - shared helpers for every runtime script.
#
# PORTABILITY CONTRACT (read this before editing):
#   Everything here must run on BOTH:
#     - macOS /bin/bash 3.2  (Doug's Mac, frozen at 3.2 for GPLv3 reasons)
#     - Linux bash 5.x       (GitHub Actions ubuntu-latest, Azure DevOps ubuntu agents)
#   That means: NO mapfile/readarray, NO associative arrays, NO `date -d`,
#   NO `timeout` binary, NO ${var,,} case conversion, NO `declare -n`.
#   If you need any of those, write a portable helper here instead.
#
# PLATFORM CONTRACT:
#   Nothing in this file may reference GitHub Actions or Azure DevOps.
#   Platform glue (artifact upload, job summaries, secret injection) belongs
#   in the CI YAML wrapper, not here. That is what keeps the same script
#   runnable on a laptop, on GitHub, and on Azure without modification.

# ---------------------------------------------------------------------------
# Logging. Everything goes to stderr so stdout stays clean for JSON pipelines.
# ---------------------------------------------------------------------------
log()  { printf '%s\n' "$*" >&2; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
err()  { printf 'ERROR: %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# run_with_timeout SECONDS CMD [ARGS...]
#
# Runs a command with a hard wall-clock ceiling. Prints whatever stdout the
# command produced (even if killed partway), returns the command's exit status,
# or 124 if it was killed for timing out.
#
# WHY THIS EXISTS: macOS has no `timeout` binary (GNU coreutils only). A first
# implementation using bash job control / process-group kill was tested against
# a real hung process and did NOT reliably kill it, leaving orphans. This
# poll-and-kill version was verified against a mock hung process and does work.
#
# KNOWN LIMIT: it kills the immediate child (terminus/php) but cannot guarantee
# a grandchild ssh process is reaped in every case. A stray one is harmless.
# The guarantee that matters is that the SCRIPT never blocks past SECONDS+1.
# ---------------------------------------------------------------------------
# STDERR IS KEPT WHEN THE CALLER ASKS FOR IT, since 2026-09-01. It went to
# /dev/null, so a timeout, a rate-limited reply, an auth failure and a
# malformed response all produced the same empty string and the same message.
# On 2026-09-01, 22 of 49 Pantheon sites failed their environment preflight and
# nothing in the log or the ledger could say why, because the only evidence had
# been thrown away at this line.
#
# It writes to a FILE rather than a variable on purpose. Every caller uses
# `$(run_with_timeout ...)`, which runs in a subshell, so a global set in here
# never reaches the caller. Set RWT_ERR_FILE once in the calling script and
# read it, and RWT_ERR_FILE.status, immediately after the call.
_rwt_status_to_file() {
  [ -n "${RWT_ERR_FILE:-}" ] || return 0
  printf '%s' "$1" > "${RWT_ERR_FILE}.status" 2>/dev/null || true
}

run_with_timeout() {
  local secs="$1"; shift
  local tmp_out; tmp_out="$(mktemp)"
  local err_to="${RWT_ERR_FILE:-}"
  if [ -n "$err_to" ]; then
    : > "$err_to" 2>/dev/null || err_to=""
  fi
  if [ -n "$err_to" ]; then
    "$@" > "$tmp_out" 2>"$err_to" &
  else
    "$@" > "$tmp_out" 2>/dev/null &
  fi
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 1
    waited=$((waited+1))
    if [ "$waited" -ge "$secs" ]; then
      kill -TERM "$pid" 2>/dev/null
      sleep 1
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      [ -n "$err_to" ] && printf 'killed after %ss (timeout)\n' "$secs" >> "$err_to" 2>/dev/null
      _rwt_status_to_file 124
      cat "$tmp_out"
      rm -f "$tmp_out"
      return 124
    fi
  done
  wait "$pid" 2>/dev/null
  local status=$?
  _rwt_status_to_file "$status"
  cat "$tmp_out"
  rm -f "$tmp_out"
  return "$status"
}

# ---------------------------------------------------------------------------
# strip_noise
#
# Filters known non-JSON noise lines out of a Terminus/SSH stdout stream so the
# remainder can be trusted as JSON.
#
# THE PHP NOTICE PATTERNS, added 2026-08-23, cost four sites their real data.
# Pantheon's own `wp-native-php-sessions` mu-plugin emits ~40 lines of
# "PHP Deprecated: Return type of Pantheon_Sessions\Session_Handler::open(...)"
# on PHP 8.2, on stdout, BEFORE WP-CLI's JSON. `wp plugin list` exited 0 and
# the JSON was intact at the end of it, but json_or_empty saw the notice wall,
# refused the whole thing, and the scanner wrote its clean default. So four
# sites recorded `plugin_updates: 0, theme_updates: 0, wp_core_update:
# up-to-date` while galbanicheese actually had 15 plugin updates, 3 theme
# updates and WordPress 7.1 waiting.
#
# The RUNBOOK has predicted this exact failure since it was written -- "jq parse
# failures | new noise line not covered by strip_noise | add the pattern here".
# It was never acted on because there was no symptom to see: the scanner's
# defaults turned the parse failure into a clean measurement. A missing filter
# here is only visible once a failed call records `unknown`, which is why that
# fix and this one shipped together.
#
# `Fatal error` is deliberately NOT filtered. A fatal means the call produced
# nothing usable, and the result SHOULD stay unparseable so it records as
# unknown. Filtering it would leave an empty string that looks the same as a
# call that returned nothing -- which is the bug, one layer down.
#
# WHY THIS EXISTS: the first live fleet run broke jq because SSH host-key
# warnings ("Warning: Permanently added ... to the list of known hosts") and
# Terminus's own notice/timing lines leaked into stdout. This is WORSE on
# ephemeral CI runners than on a laptop, because a fresh runner has no cached
# known_hosts and therefore emits the host-key warning for EVERY site.
# ---------------------------------------------------------------------------
strip_noise() {
  grep -v -E \
    -e '^Warning: Permanently added' \
    -e '^Warning: the ECDSA host key' \
    -e "^Warning: Identity file" \
    -e '^\[notice\]' \
    -e '^\[warning\]' \
    -e '^\[info\]' \
    -e '^ *\[[0-9]+\.[0-9]+ *(ms|s)\]' \
    -e '^Your Terminus version' \
    -e '^You are running an outdated' \
    -e '^PHP Deprecated:' \
    -e '^Deprecated:' \
    -e '^PHP Notice:' \
    -e '^Notice:' \
    -e '^PHP Warning:' \
    -e '^Warning: Constant .* already defined' \
    -e '^PHP Stack trace:' \
    -e '^PHP +[0-9]+\. ' \
    || true
}

# ---------------------------------------------------------------------------
# json_or_empty
#
# Reads stdin, strips noise, and echoes it back ONLY if it is non-empty AND
# parses as JSON. Otherwise echoes nothing and returns 1.
#
# WHY THIS EXISTS: `jq empty` on a truly EMPTY string returns exit 0, because
# jq treats empty input as trivially valid. That caused a real false result on
# 2026-08-09 - a timed-out env:list returned "" and the code read that as
# "check succeeded, environment is absent" instead of "check failed, status
# unknown", mislabeling galbanicheese (a known-good site) as nonexistent.
# The non-empty guard is the fix. Never remove it.
# ---------------------------------------------------------------------------
json_or_empty() {
  local raw cleaned
  raw="$(cat)"
  cleaned="$(printf '%s' "$raw" | strip_noise)"
  if [ -z "$cleaned" ]; then
    return 1
  fi
  if printf '%s' "$cleaned" | jq empty >/dev/null 2>&1; then
    printf '%s' "$cleaned"
    return 0
  fi
  # LAST RESORT: take everything from the first line that STARTS a JSON value.
  #
  # Enumerating noise patterns has now failed twice in one day. The PHP
  # deprecation wall cost four sites their plugin counts, and the fix for it
  # missed `Warning: Constant DISALLOW_FILE_MODS already defined in phar://...`
  # on morrison-chs, which cost a fifth. Every miss is a real measurement
  # thrown away, and the list of things WP-CLI and PHP can print before their
  # output is not knowable in advance.
  #
  # So: if the cleaned text does not parse whole, find the first line beginning
  # with [ or { and try from there to the END of the input. Anchored on a line
  # start and required to parse all the way to the end, so a stray brace inside
  # an error message cannot produce a partial object -- it has to be the real
  # payload or nothing.
  #
  # This does NOT make strip_noise redundant: `core version` returns bare text,
  # not JSON, and is matched by grep rather than parsed here.
  local from_json
  from_json="$(printf '%s' "$cleaned" | sed -n '/^[[{]/,$p')"
  if [ -n "$from_json" ] && printf '%s' "$from_json" | jq empty >/dev/null 2>&1; then
    printf '%s' "$from_json"
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# require_tools TOOL [TOOL...]
# ---------------------------------------------------------------------------
require_tools() {
  local missing=0 t
  for t in "$@"; do
    if ! command -v "$t" >/dev/null 2>&1; then
      err "required tool not found on PATH: $t"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || return 1
}

# ---------------------------------------------------------------------------
# pantheon_login
#
# Authenticates Terminus non-interactively if not already authenticated.
# Reads PANTHEON_MACHINE_TOKEN from the environment - it is never passed as an
# argument, so it cannot leak into `ps` output or a CI command echo.
# ---------------------------------------------------------------------------
pantheon_login() {
  # Read the IDENTITY, not the exit code.
  #
  # This check used to be `terminus auth:whoami >/dev/null 2>&1`, which trusts
  # the exit status alone. On a machine with no session at all, auth:whoami
  # still exits 0, so this function returned early, auth:login was NEVER
  # called, and the very next command came back empty with no explanation.
  # It looked correct on a laptop, where the cached session makes the early
  # return genuinely right, and failed on every fresh CI runner - the Pantheon
  # job had never once authenticated in CI before 2026-08-18.
  #
  # Same bug as json_or_empty forty lines up: an exit code standing in for an
  # answer. The fix is the same too - require actual output.
  local who
  who="$(terminus auth:whoami 2>/dev/null | strip_noise | tr -d '[:space:]')"
  if [ -n "$who" ]; then
    log "Terminus: already authenticated as ${who}."
    return 0
  fi
  if [ -z "${PANTHEON_MACHINE_TOKEN:-}" ]; then
    err "not authenticated and PANTHEON_MACHINE_TOKEN is unset."
    return 1
  fi
  log "Terminus: authenticating with machine token..."
  local out
  if out="$(terminus auth:login --machine-token="$PANTHEON_MACHINE_TOKEN" 2>&1)"; then
    # Confirm the login actually produced a session rather than trusting its
    # exit code in turn, which would reintroduce the bug above one line lower.
    who="$(terminus auth:whoami 2>/dev/null | strip_noise | tr -d '[:space:]')"
    if [ -z "$who" ]; then
      err "terminus auth:login reported success but there is still no session."
      return 1
    fi
    log "Terminus: authenticated as ${who}."
    return 0
  fi
  # Terminus's own message, minus the noise. Never echo the token itself.
  err "terminus auth:login failed: $(printf '%s' "$out" | strip_noise | tail -3 | tr '\n' ' ')"
  return 1
}
