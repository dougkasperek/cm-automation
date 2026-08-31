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
# WHAT THIS DOES NOT DO: it does not scan Nexcess by default. Its workflow
# deliberately defaults persist_ledger to false, because the ledger is
# append-only and a bad row can't be corrected in place. Pass
# --with-nexcess to include it anyway (still won't touch the ledger unless
# you also edit that call below).
#
# This comment said Nexcess was "blocked upstream (Cloudflare challenges the
# portal API)" until 2026-08-31. That was resolved on 2026-08-25 and the
# challenge was OURS -- a hand-built SSL context missing post_handshake_auth.
# See the bug table in CLAUDE.md and docs/NEXCESS-SUPPORT.md. The default is
# still off, but for the ledger reason above, not because it cannot connect.
#
# WHAT THIS DOES NOT DO, PART 2: it does not turn any of this into a
# schedule. Every cron block in .github/workflows/ is commented out -- a
# scheduled run could publish a WORSE view of the fleet than what's already
# live, silently. The publish-side coverage-drop guard now exists (see
# CLAUDE.md and scripts/publish-dashboard.sh); turning the crons on is a
# deliberate decision nobody has taken yet. Run this by hand.
#
# Requires: gh CLI, authenticated (`gh auth login`), with access to the repo.

set -euo pipefail

# Derived, not hardcoded. This was `dougkasperek/cm-automation` until
# 2026-08-31, which would have silently pointed every dispatch at the old
# personal repo the moment ownership moved to the clevermethod org. See
# docs/HANDOVER.md. Override with REPO=owner/name to target another fork.
#
# The git call is the CONDITION of an `if`, not a bare assignment. Under
# `set -e` a failing command substitution in an assignment aborts the script
# before the error message below can print -- so the clone with no origin got
# a silent exit instead of the one line telling it what to do. An `if`
# condition is exempt. Both directions tested 2026-08-31.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${REPO:-}" ]]; then
  if _remote="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null)"; then
    REPO="$(printf '%s' "$_remote" | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##')"
  else
    REPO=""
  fi
fi

if [[ -z "$REPO" || "$REPO" != */* ]]; then
  echo "Could not work out the GitHub repo from 'git remote get-url origin'." >&2
  echo "Set it explicitly:  REPO=owner/name $0" >&2
  exit 1
fi

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

# run_mode=full, changed 2026-08-22. This said api-only, which meant the one
# command named "run all the fleet scans" was the only one that did NOT collect
# WordPress version, core-update status or plugin/theme counts -- the facts that
# answer wp2shell. It was written when full mode did not work; full has run
# since 2026-08-18, including in CI, so the flag had outlived its reason and
# nothing said so.
run pantheon-fleet-healthcheck.yml \
  -f run_mode=full \
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
