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
run_with_timeout() {
  local secs="$1"; shift
  local tmp_out; tmp_out="$(mktemp)"
  "$@" > "$tmp_out" 2>/dev/null &
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
      cat "$tmp_out"
      rm -f "$tmp_out"
      return 124
    fi
  done
  wait "$pid" 2>/dev/null
  local status=$?
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
  if terminus auth:whoami >/dev/null 2>&1; then
    log "Terminus: already authenticated."
    return 0
  fi
  if [ -z "${PANTHEON_MACHINE_TOKEN:-}" ]; then
    err "not authenticated and PANTHEON_MACHINE_TOKEN is unset."
    return 1
  fi
  log "Terminus: authenticating with machine token..."
  if terminus auth:login --machine-token="$PANTHEON_MACHINE_TOKEN" >/dev/null 2>&1; then
    log "Terminus: authenticated."
    return 0
  fi
  err "terminus auth:login failed."
  return 1
}
