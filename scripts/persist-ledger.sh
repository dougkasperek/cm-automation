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
# THAT APPLIES TO THE COVERAGE-DROP GUARD TOO, and for a day it did not. The
# guard added on 2026-08-20 makes `ingest` exit 1 when a run measured fewer
# sites than the run before it. This script runs under `set -e`, so a bare call
# to ingest died right there -- before git add, commit and push, and without
# retrying. The runner is ephemeral, so the degraded run that raised the alarm
# was the one run guaranteed never to reach the ledger, and the ledger is the
# one asset here that cannot be regenerated.
#
# So ingest is called with --allow-coverage-drop, which stores the run and
# exits 0, and the drop is reported at the bottom with the other post-push
# alarms. The publish job is gated on this job succeeding, so a drop still
# stops fleet.thudstaff.com being replaced by a worse view -- it just no
# longer costs the observations to do it.
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

# Ingest's own output, kept so the coverage-drop verdict survives the push.
# Outside the worktree on purpose: the loop below does `git reset --hard` on
# every attempt.
INGEST_LOG="$(mktemp)"
trap 'rm -f "$INGEST_LOG"' EXIT

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
  # --allow-coverage-drop: STORE the run, exit 0, and let the check at the
  # bottom of this file decide the exit code. Without it, `set -e` kills the
  # script here and the run is lost. The drop is not being ignored; it is
  # being reported after the data is safe.
  python3 scripts/fleet-ledger.py ingest --reports "$REPORTS" \
    --allow-coverage-drop 2>&1 | tee "$INGEST_LOG"
  # BOTH pages, not just fleet.html. Until 2026-08-26 this rendered only
  # fleet.html, so the committed components.html was whatever a person last
  # ran by hand -- one health run behind after 2026-08-25, showing a component
  # catalogue that no longer matched the ledger beside it, with nothing on it
  # saying so. publish-dashboard.sh re-renders both, so the LIVE page was
  # right and only the review copy in the repo was stale, which is the
  # familiar shape: the copy that loses is the one nobody is looking at.
  #
  # ALL FOUR, and it was two until 2026-08-31. consent.html has been a TRACKED
  # file since 2026-08-27 and was never re-rendered here, so the committed
  # review copy went stale on every ledger write -- precisely the failure the
  # paragraph above describes, still live for the page added right after it
  # was written. vulnerabilities.html would have been the third occurrence.
  # test-workflows.py now asserts the rendered, diffed and staged lists are
  # identical, and that every committed page appears in them.
  python3 scripts/render-dashboard.py --out fleet.html \
    --components-out components.html \
    --consent-out consent.html \
    --vuln-out vulnerabilities.html

  if git diff --quiet -- history/ fleet.html components.html consent.html \
      vulnerabilities.html; then
    echo "ledger already current at origin/${BRANCH}; nothing to push"
    pushed="skipped"
    break
  fi

  git add history/ fleet.html components.html consent.html \
    vulnerabilities.html
  git commit --quiet -m "Ledger: ${LABEL}" \
    -m "Ingested by ${GITHUB_WORKFLOW:-local} run ${GITHUB_RUN_NUMBER:-0}." \
    -m "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-.}/actions/runs/${GITHUB_RUN_ID:-0}"

  # SAY WHICH FAILURE THIS IS. Until 2026-08-28 every push failure printed
  # "another run got there first, re-ingesting" -- one cause for every cause,
  # the same defect as `probe` reporting a DNS failure, a TLS trust failure and
  # a dead host with one word.
  #
  # On 2026-08-28 a consent run lost a 6-minute headed sweep of 79 sites to
  # `remote: fatal error in commit_refs`, a GitHub SERVER error. Nothing had
  # raced it -- the remote was still on the commit from twenty minutes earlier
  # and no other ledger-writing workflow had run -- and the log sent a reader
  # looking for a concurrent run that did not exist.
  #
  # A non-fast-forward IS a race, and re-ingesting onto the winner is the right
  # answer. Anything else is not, and saying so costs nothing.
  # The assignment is the `if` CONDITION on purpose. This file runs under
  # `set -e`, so a bare `PUSH_ERR="$(git push ...)"` on its own line would kill
  # the script on the first failed push -- no retry, no message, worse than the
  # bug above. As a condition it is exempt.
  if PUSH_ERR="$(git push origin "HEAD:${BRANCH}" 2>&1)"; then
    echo "ledger pushed to ${BRANCH} (attempt ${attempt})"
    pushed="yes"
    break
  fi
  if printf '%s' "$PUSH_ERR" | grep -qiE "non-fast-forward|fetch first|stale info|behind its remote"; then
    echo "push rejected on attempt ${attempt}: another run got there first, re-ingesting onto it"
  else
    # Retried anyway -- a server-side error often clears -- but never described
    # as a race, and the actual text is printed so the next reader sees it.
    echo "push FAILED on attempt ${attempt}, and NOT because of a concurrent run:"
    printf '%s\n' "$PUSH_ERR" | sed 's/^/    /'
  fi
  sleep $(( attempt * 5 ))
done

if [ -z "$pushed" ]; then
  echo "::error::could not push the ledger after ${ATTEMPTS} attempts. The scan and the ingest both SUCCEEDED; what was lost is the push, and with it this run's observations, because the runner workspace is discarded. Last error follows."
  printf '%s\n' "${PUSH_ERR:-（no output captured）}" | sed 's/^/    /'
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

# Coverage going DOWN is a defect in the run. Reported here, last, for the same
# reason the unresolved-site alarm is: the observations are committed by this
# point, so saying so costs nothing. The publish job needs this job to succeed,
# so exiting non-zero is what stops a worse measurement replacing a better one
# on the live page.
if grep -q "COVERAGE DROPPED" "$INGEST_LOG"; then
  # FLEET_ALLOW_COVERAGE_DROP: the caller has looked at the drop and says it is
  # expected. Added 2026-08-28, because until then the guard's own advice --
  # "pass --allow-coverage-drop if the drop is real and expected" -- named a
  # flag NO workflow exposed. There was no way to say "yes, expected" from
  # Actions at all, so a legitimately smaller run blocked every publish from
  # every workflow until somebody ran the publish by hand.
  #
  # The case that forced it: the consent sweep reaches 78 of 79 sites from a
  # laptop and 71 of 79 from a GitHub runner, because 7 sites refuse the
  # runner with HTTP 403. Neither number is wrong -- they are different
  # vantage points -- and the page already names each blocked site and says
  # its consent posture is unmeasured rather than clean. The drop is real,
  # expected, and explained, and there was still no way to publish it.
  #
  # Deliberately NOT a default and deliberately still loud. The drop is
  # printed either way; this only decides the exit code. An override that
  # silences its own reason is how a worse page becomes invisible.
  if [ "${FLEET_ALLOW_COVERAGE_DROP:-0}" = "1" ]; then
    echo "::warning::coverage dropped, and the run was dispatched with allow_coverage_drop. Publishing anyway. What dropped:"
    grep -A 3 "COVERAGE DROPPED" "$INGEST_LOG" || true
    echo "::notice::If this was not expected, the page now shows fewer measured sites than before. Re-run the scan."
  else
    echo "::error::coverage dropped: this run measured fewer sites than the run before it. The observations WERE committed; the dashboard was not published, because publishing would replace a better measurement with a worse one. Re-run the scan from somewhere less likely to be blocked, or re-dispatch with allow_coverage_drop if the drop is real and expected."
    grep -A 3 "COVERAGE DROPPED" "$INGEST_LOG" || true
    exit 1
  fi
fi
