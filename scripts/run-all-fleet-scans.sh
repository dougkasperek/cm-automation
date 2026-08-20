#!/usr/bin/env bash
# Trigger every fleet-scan GitHub Actions workflow with one command.
#
# WHY THIS IS SAFE TO FIRE TOGETHER: each workflow (Pantheon health, email
# DNS, consent) ingests into history/ and then publishes fleet.thudstaff.com
# on its own -- see .github/workflows/_publish-dashboard.yml and the
# `persist-ledger` job in each workflow file. All of them share one
# concurrency group, `fleet-ledger-write`, with cancel-in-progress: false.
# GitHub queues their ledger writes instead of racing them, so running this
# script does not require any new coordination on the CI side.
#
# WHAT THIS DOES NOT DO: it does not scan Nexcess by default. That workflow
# is blocked upstream (Cloudflare challenges the portal API -- see project
# memory fleet_nexcess.md / docs/NEXCESS-SUPPORT.md) and its own workflow
# deliberately defaults persist_ledger to false, because the ledger is
# append-only and a bad row can't be corrected in place. Pass
# --with-nexcess to include it anyway (still won't touch the ledger unless
# you also edit that call below).
#
# WHAT THIS DOES NOT DO, PART 2: it does not turn any of this into a
# schedule. The consent workflow's cron block is deliberately commented out
# until the publish-side coverage-drop guard exists (see CLAUDE.md /
# fleet_coverage_guard.md) -- a scheduled run today could publish a WORSE
# view of the fleet than what's already live, silently. Run this by hand.
#
# Requires: gh CLI, authenticated (`gh auth login`), with access to the repo.

set -euo pipefail

REPO="dougkasperek/cm-automation"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install it (e.g. 'brew install gh') and run 'gh auth login' first." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run 'gh auth login' first." >&2
  exit 1
fi

run() {
  local workflow="$1"; shift
  echo "==> triggering $workflow"
  gh workflow run "$workflow" --repo "$REPO" "$@"
}

run pantheon-fleet-healthcheck.yml \
  -f run_mode=api-only \
  -f target_env=live \
  -f fail_on_crit=false \
  -f persist_ledger=true \
  -f publish_dashboard=true

run fleet-email-dns.yml \
  -f compare_to_workbook=true \
  -f fail_on_regression=false \
  -f persist_ledger=true \
  -f publish_dashboard=true

run fleet-consent.yml \
  -f concurrency=4 \
  -f only="" \
  -f persist_ledger=true \
  -f publish_dashboard=true

if [[ "${1:-}" == "--with-nexcess" ]]; then
  run fleet-nexcess.yml \
    -f probe_only=false \
    -f with_detail=true \
    -f persist_ledger=false \
    -f publish_dashboard=true
fi

echo
echo "All requested workflows queued (GitHub Actions has a short delay before"
echo "a triggered run shows up in 'gh run list')."
echo
echo "Watch them:"
echo "  gh run list --repo $REPO --limit 10"
echo "Or open:"
echo "  https://github.com/$REPO/actions"
