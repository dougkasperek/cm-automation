#!/usr/bin/env bash
#
# publish-dashboard.sh
# Render a scan JSON into the dashboard and push it to the hosted Worker.
#
#   FLEET_PUBLISH_URL=https://fleet.example.com \
#   FLEET_PUBLISH_TOKEN=xxxx \
#   ./scripts/publish-dashboard.sh reports/wpstatistics-fleet-scan-2026-08-09_0954.json
#
# This is the whole "make it live" step. CI calls exactly this, with the two
# values coming from platform secrets (later, from Keeper). Nothing about it is
# GitHub-specific or Azure-specific, which is the point.
#
# Portability: bash 3.2 compatible. See scripts/lib/common.sh for the contract.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

SCAN_JSON="${1:-}"
if [ -z "$SCAN_JSON" ] || [ ! -f "$SCAN_JSON" ]; then
  err "usage: $0 <scan.json>"
  exit 1
fi

require_tools python3 curl || exit 1

: "${FLEET_PUBLISH_URL:?FLEET_PUBLISH_URL is not set (e.g. https://fleet.thudstaff.com)}"
: "${FLEET_PUBLISH_TOKEN:?FLEET_PUBLISH_TOKEN is not set}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log "Rendering dashboard from $SCAN_JSON ..."
python3 "$SCRIPT_DIR/render-fleet-dashboard.py" "$SCAN_JSON" \
  -o "$WORK/dashboard.html" \
  --emit-data "$WORK/latest.json" \
  --live-url /api/fleet-scan || { err "render failed"; exit 1; }

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

if [ "$rc" -eq 0 ]; then
  log ""
  log "Published. Dashboard is live at: $BASE/"
fi
exit "$rc"
