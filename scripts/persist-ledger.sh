#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# persist-ledger.sh - ingest a CI run's scan output into the append-only
# ledger and push the result back to the default branch.
#
# WHY THIS EXISTS. Until 2026-08-18 no CI run ever reached the ledger. reports/
# is gitignored, ingest was a manual step on Doug's laptop, and the workflows
# had contents:read, so every scan CI produced was a 90-day artifact and then
# nothing. The ledger is the one asset in this repo that cannot be regenerated,
# and it was the only one CI could not write to.
#
# THE ORDER OF OPERATIONS IS THE DESIGN. Data is persisted BEFORE anything is
# allowed to fail. An unrecognised site is a real finding and it does raise the
# alarm, but it raises it after the observations are safely committed, never
# instead of committing them. Failing first would throw away the run that
# discovered the problem.
#
# Conflicts are avoided rather than resolved. Two appends to one JSONL rebase
# badly, so on every attempt this resets to the current remote head and
# re-ingests onto it. ingest is idempotent on run_id, so that is always safe and
# never produces a duplicate.
#
# Usage:  scripts/persist-ledger.sh <reports-dir> <label>
# ---------------------------------------------------------------------------
set -euo pipefail

REPORTS="${1:?usage: persist-ledger.sh <reports-dir> <label>}"
LABEL="${2:-CI run}"
BRANCH="${LEDGER_BRANCH:-main}"
ATTEMPTS="${LEDGER_PUSH_ATTEMPTS:-3}"

if [ ! -d "$REPORTS" ]; then
  echo "no reports directory at ${REPORTS}; nothing to ingest"
  exit 0
fi
if [ -z "$(find "$REPORTS" -maxdepth 1 -name '*.json' -print -quit)" ]; then
  echo "no scan JSON in ${REPORTS}; the run produced nothing to ingest"
  exit 0
fi

git config user.name  "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

pushed=""
for attempt in $(seq 1 "$ATTEMPTS"); do
  # Start from the current remote head every time. Anything this loop built on
  # a previous attempt is discarded deliberately, so a run that raced with
  # another workflow re-ingests onto the winner rather than merging into it.
  git fetch --quiet origin "$BRANCH"
  git reset --quiet --hard "origin/${BRANCH}"

  # Invoked through python3 rather than ./scripts/... on purpose: the mode
  # bit on these two files was lost once already, and a CI job is a bad place
  # to discover it.
  python3 scripts/fleet-ledger.py ingest --reports "$REPORTS"
  python3 scripts/render-dashboard.py --out fleet.html

  if git diff --quiet -- history/ fleet.html; then
    echo "ledger already current at origin/${BRANCH}; nothing to push"
    pushed="skipped"
    break
  fi

  git add history/ fleet.html
  git commit --quiet -m "Ledger: ${LABEL}" \
    -m "Ingested by ${GITHUB_WORKFLOW:-local} run ${GITHUB_RUN_NUMBER:-0}." \
    -m "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-.}/actions/runs/${GITHUB_RUN_ID:-0}"

  if git push --quiet origin "HEAD:${BRANCH}"; then
    echo "ledger pushed to ${BRANCH} (attempt ${attempt})"
    pushed="yes"
    break
  fi
  echo "push rejected on attempt ${attempt}; another run got there first, re-ingesting"
  sleep $(( attempt * 5 ))
done

if [ -z "$pushed" ]; then
  echo "::error::could not push the ledger after ${ATTEMPTS} attempts."
  exit 1
fi

# The alarm, deliberately last. By this point the observations are committed, so
# a site the inventory has never heard of gets reported without costing the run
# that found it. --strict is a non-zero exit, not a missing row.
echo "verifying every ledger site resolves to the inventory"
if ! python3 scripts/render-dashboard.py --out /tmp/ledger-verify.html --strict; then
  echo "::error::the ledger holds sites the inventory does not. The observations were committed; add the sites to data/fleet-inventory.json or map them via host_site_name."
  exit 1
fi
echo "ledger verified"
