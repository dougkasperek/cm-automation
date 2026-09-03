#!/usr/bin/env python3
"""
Self-check for the concurrency contract in .github/workflows/.

WHY THIS EXISTS
---------------
2026-08-28: four scans were run in one afternoon to bring every source current.
That is the first time this repo had more than one workflow in flight, and it
exposed two defects that had been harmless only because nothing overlapped.

  1. The PERSIST jobs shared `concurrency: fleet-ledger-write`, so the
     append-only ledger was safe. The PUBLISH jobs shared nothing. Each publish
     checks out main FRESH -- correct, and correct only if publishes do not
     overlap, because two racing publishes are won by whichever finishes last,
     not by whichever holds the newest ledger. The result is a page behind the
     ledger that looks current.

  2. Worse, and the reason this file is a test rather than a comment: GitHub
     keeps only ONE run pending per concurrency group by default. A newly
     queued run CANCELS the one already waiting. `cancel-in-progress: false`
     does not help -- it governs the RUNNING job, not the pending one. So
     dispatching four workflows together would run one persist, hold a second,
     and silently cancel the third and fourth. No error, no failed run, two
     ingests simply gone.

`queue: max` raises the pending limit to 100 and is documented as incompatible
with `cancel-in-progress: true`, which is why that stays false everywhere.

THE POINT OF TESTING IT
-----------------------
`queue: max` is a control that does nothing visible when it works and fails
silently when it is removed -- exactly the shape of the `--known-hosts` pin
that enforced nothing for a day, and of `workers_dev = false` sitting under the
wrong TOML table. A control nobody re-tests is the one that quietly stops
working. So: parse the YAML and assert the resolved value, never grep the text
and assume the key landed where it looks like it landed.

Run: ./test/test-workflows.py
"""
import glob
import io
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:                                    # pragma: no cover
    print("FAIL  pyyaml is not installed; it is in requirements.txt")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WF = os.path.join(ROOT, ".github", "workflows")

# The two groups that serialise shared state. Anything using them must queue
# rather than cancel.
SHARED_GROUPS = ("fleet-ledger-write", "fleet-publish", "nexcess-ssh")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- %s" % detail) if not cond and detail else ""))


files = sorted(glob.glob(os.path.join(WF, "*.yml")))
check("there are workflow files to check at all", len(files) >= 5, str(len(files)))

loaded = {}
for f in files:
    name = os.path.basename(f)
    try:
        loaded[name] = yaml.safe_load(open(f))
    except Exception as e:                             # pragma: no cover
        check("%s parses as YAML" % name, False, str(e))
check("every workflow file parses as YAML", len(loaded) == len(files))


def concurrency_blocks():
    """(file, where, block) for every concurrency block in every workflow."""
    for name, doc in loaded.items():
        if not isinstance(doc, dict):
            continue
        top = doc.get("concurrency")
        if isinstance(top, dict):
            yield name, "(workflow-level)", top
        for jn, job in (doc.get("jobs") or {}).items():
            if isinstance(job, dict) and isinstance(job.get("concurrency"), dict):
                yield name, jn, job["concurrency"]


blocks = list(concurrency_blocks())
shared = [(f, w, b) for f, w, b in blocks if b.get("group") in SHARED_GROUPS]

check("the shared concurrency groups are actually in use",
      len(shared) >= 6, str(len(shared)))

# --- the contract ---------------------------------------------------------
for f, where, b in shared:
    g = b.get("group")
    check("%s / %s (%s) queues rather than cancelling the pending run"
          % (f, where, g),
          b.get("queue") == "max", repr(b.get("queue")))
    # queue: max and cancel-in-progress: true are mutually exclusive per the
    # GitHub docs, and cancelling a running publish mid-upload would leave R2
    # holding a new dashboard.html beside an old consent.html.
    check("%s / %s (%s) does not cancel a run already in progress"
          % (f, where, g),
          b.get("cancel-in-progress") is False, repr(b.get("cancel-in-progress")))

# --- nothing writes shared state without joining the group ----------------
# A new workflow that ingests or publishes must join, or it reintroduces the
# race this file documents. Keyed on the JOB NAME because that is what a new
# workflow copies from an existing one.
for name, doc in loaded.items():
    for jn, job in ((doc or {}).get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if "persist" in jn and "ledger" in jn:
            c = job.get("concurrency") or {}
            check("%s / %s joins fleet-ledger-write" % (name, jn),
                  c.get("group") == "fleet-ledger-write", repr(c.get("group")))
        if "publish" in jn and name != "_publish-dashboard.yml":
            # EVERY scanner publishes through the shared workflow. Until
            # 2026-09-03 this accepted an inline copy that carried the
            # `fleet-publish` group itself, and Pantheon's copy drifted: the
            # alert step added to the shared workflow on 2026-09-02 never
            # reached it, so a Pantheon publish could not alert. A copy of the
            # thing that actually runs is a place for the two to disagree, and
            # the copy that loses is the one nobody is looking at.
            uses = str(job.get("uses") or "")
            check("%s / %s publishes through the shared workflow" % (name, jn),
                  uses.endswith("_publish-dashboard.yml"),
                  "uses=%r (an inline publish job cannot carry the alert step)" % uses)

# --- the coverage-drop override ------------------------------------------
# Added 2026-08-28. The guard's own error message said "pass
# --allow-coverage-drop if the drop is real and expected" and NO workflow
# exposed it, so from Actions there was no way to say "yes, expected" at all.
# A legitimately smaller run -- the consent sweep reaches 71 of 79 sites from a
# runner against 78 from a laptop, because 7 refuse the runner with HTTP 403 --
# blocked every publish from every workflow until somebody published by hand.
#
# It is an override on a safety guard, so the two things that must stay true
# are that it is OFF unless asked for, and that BOTH guards get told. There are
# two independent coverage checks: persist-ledger.sh looks at the run it just
# ingested, publish-dashboard.sh looks at the whole ledger's standing state.
# Telling only one leaves the publish refusing anyway.
def dispatch_inputs(doc):
    on = doc.get(True) or doc.get("on") or {}
    out = {}
    for key in ("workflow_dispatch", "workflow_call"):
        out.update(((on.get(key) or {}).get("inputs") or {}))
    return out


scanners = [n for n, d in loaded.items()
            if isinstance(d, dict) and "persist-ledger" in str(d.get("jobs", {}))]
check("the scanner workflows were found", len(scanners) >= 4, str(scanners))

for name in sorted(scanners) + ["_publish-dashboard.yml"]:
    ins = dispatch_inputs(loaded[name])
    got = ins.get("allow_coverage_drop")
    check("%s offers allow_coverage_drop" % name, got is not None)
    if got is not None:
        # DEFAULT FALSE IS THE WHOLE POINT. A guard whose override defaults on
        # is not a guard.
        check("%s defaults allow_coverage_drop to false" % name,
              got.get("default") is False, repr(got.get("default")))

# Both guards must be reachable: the env var for persist, the flag for publish.
for name in sorted(scanners):
    body = io.open(os.path.join(WF, name), encoding="utf-8").read()
    check("%s passes the drop decision to persist-ledger.sh" % name,
          "FLEET_ALLOW_COVERAGE_DROP" in body)
    check("%s passes the drop decision on to the publish side" % name,
          "allow_coverage_drop: ${{ inputs.allow_coverage_drop }}" in body
          or "--allow-coverage-drop" in body)

pub = io.open(os.path.join(WF, "_publish-dashboard.yml"), encoding="utf-8").read()
check("the shared publish workflow can actually pass the flag",
      "--allow-coverage-drop" in pub)

# The script side: an override that silences its own reason hides a worse page.
persist = io.open(os.path.join(ROOT, "scripts", "persist-ledger.sh"),
                  encoding="utf-8").read()
check("persist-ledger.sh still prints what dropped when overridden",
      persist.count('grep -A 3 "COVERAGE DROPPED"') >= 2, "only one branch prints")
check("persist-ledger.sh defaults the override to off",
      'FLEET_ALLOW_COVERAGE_DROP:-0' in persist)

# --- the push retry loop tells the truth about WHY it failed ---------------
# 2026-08-28: a consent run lost a 6-minute headed sweep of 79 sites to
# `remote: fatal error in commit_refs`, a GitHub server error. The scan and the
# ingest both succeeded; only the push failed, and the runner workspace is
# discarded, so the observations went with it. The log said "another run got
# there first, re-ingesting" -- printed for EVERY push failure -- and nothing
# had raced it: the remote was still on the commit from twenty minutes earlier.
# One message for every cause, which is the `probe` row in the bug table.
check("the race message is conditional, not printed for every failure",
      "non-fast-forward" in persist,
      "persist-ledger.sh still claims a race for any push failure")
check("...and a non-race failure prints the actual git error",
      "NOT because of a concurrent run" in persist)
check("...and the final error says the scan and ingest succeeded, so the loss "
      "is understood",
      "The scan and the ingest both SUCCEEDED" in persist)
# THE TRAP THIS AVOIDS. persist-ledger.sh runs under `set -e`. A bare
# `PUSH_ERR="$(git push ...)"` aborts the script on the first failed push --
# no retry, no message, worse than the bug it was fixing. As an `if` condition
# it is exempt. Asserted because the difference is one character of structure.
check("the push capture is the if-condition, so `set -e` cannot kill the loop",
      'if PUSH_ERR="$(git push' in persist,
      "a bare assignment under set -e would abort on the first failure")

# --- the consent gating job, added 2026-08-28 -----------------------------
# It had NO CI path at all: fleet-consent.yml ran only the cold sweep, so every
# gating measurement on the live page came from a laptop. Step 4 of the
# "adding a workflow" checklist in CLAUDE.md, never done for this source.
_c = loaded.get("fleet-consent.yml") or {}
_jobs = (_c.get("jobs") or {})
check("the consent workflow has a gating job at all", "gating" in _jobs,
      str(sorted(_jobs)))
if "gating" in _jobs:
    _g = _jobs["gating"]
    _steps = " ".join(str(st.get("run", "")) for st in (_g.get("steps") or []))
    # HEADED OR NOTHING. A headless gating run sees fewer tags, and fewer tags
    # reads as "nothing fires after rejection" -- a pass. The instrument would
    # be manufacturing the best possible answer, which is how the v1 and v2
    # measured windows went wrong.
    # MATCHED ON THE INVOCATION, not the word. The first cut checked for
    # "xvfb-run" anywhere in the job and passed after the sweep was un-wrapped,
    # because the INSTALL step also runs `xvfb-run --help` to prove it exists.
    # A guard that a correct-looking break slips past is the third one of these
    # today; match what has to be true, not a word that happens to be nearby.
    check("the gating sweep itself runs under a virtual display",
          "xvfb-run -a node scripts/consent/run-gating-sweep.mjs" in
          " ".join(_steps.split()),
          "run-gating-sweep.mjs is not wrapped in xvfb-run")
    check("...and takes its roster from THIS run's cold scan, not the repo",
          "--from-scan" in _steps, "gating does not use --from-scan")

    _p = _jobs.get("persist-ledger") or {}
    _needs = _p.get("needs") or []
    check("persist waits for gating, so both reports land in one ingest",
          "gating" in _needs, repr(_needs))
    # A GATING FAILURE MUST NOT COST THE COLD SWEEP. 79 cold rows are worth
    # persisting whether or not the Reject All pass worked, and gating is the
    # more fragile of the two.
    check("...but is NOT gated on gating succeeding",
          "needs.gating.result == 'success'" not in str(_p.get("if")),
          str(_p.get("if")))

# The tester must refuse a headless browser rather than report floors. Asserted
# on the source because no CI job can prove it without breaking the display.
_tg = io.open(os.path.join(ROOT, "scripts", "consent", "test-gating.mjs"),
              encoding="utf-8").read()
check("the gating tester checks it actually GOT a headed browser",
      "browserActual" in _tg and "process.exit(3)" in _tg,
      "test-gating.mjs does not verify the browser it was given")
_gs = io.open(os.path.join(ROOT, "scripts", "consent", "run-gating-sweep.mjs"),
              encoding="utf-8").read()
check("...and the sweep aborts on it, rather than one INCONCLUSIVE row per site",
      "err.code === 3" in _gs,
      "run-gating-sweep.mjs does not act on the tester's headed abort")

# ---------------------------------------------------------------------------
# EVERY COMMITTED PAGE MUST BE RE-RENDERED, DIFFED AND STAGED
# ---------------------------------------------------------------------------
# consent.html has been a tracked file since 2026-08-27 and persist-ledger.sh
# never re-rendered it, so the committed review copy went stale on every ledger
# write -- the exact failure the comment above that render block describes,
# reintroduced by the page added days after it was written. Found 2026-08-31
# while adding a fourth page, which would have been the third occurrence.
#
# The three lists must be identical. Rendering a page the diff does not check
# leaves it uncommitted; diffing one that is not staged means the run reports a
# change it then throws away.
_rend = (set(re.findall(r"--(?:components|consent|vuln)-out (\S+)", persist))
         | set(re.findall(r"--out (fleet\.html)", persist)))


def _paths(pat):
    m = re.search(pat, persist, re.S)
    return set(x for x in m.group(1).replace("\\\n", " ").split()
               if x not in ("\\", "history/"))


_diffed = _paths(r"git diff --quiet -- ([^;]+);")
_staged = _paths(r"git add ([^\n]+\n(?:\s+\S+\n)?)")
check("persist-ledger.sh renders more than one page", len(_rend) >= 2, str(_rend))
check("every page it renders is also diffed",
      _rend == _diffed, "rendered %s, diffed %s" % (sorted(_rend), sorted(_diffed)))
check("every page it diffs is also staged",
      _diffed == _staged, "diffed %s, staged %s" % (sorted(_diffed), sorted(_staged)))
# A tracked page nobody re-renders is a stale review copy by construction.
_tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                              text=True).stdout.split())
_html = {f for f in _tracked if f.endswith(".html") and "/" not in f}
# Two committed pages are DEAD, not stale, and are named rather than excluded
# by a pattern so a NEW unrendered page still fails this check:
#   health.html          nothing in the repo writes it at all
#   fleet-dashboard.html render-fleet-dashboard.py (v1)'s default --out. v1
#                        feeds the live LOCAL view that fills in while a scan
#                        runs; its output is not published and not refreshed.
# Both were committed by the initial import on 2026-08-18 and have not been
# touched since. They should be deleted; until they are, this list keeps the
# check sharp instead of the check being dropped.
_DEAD_PAGES = {"health.html", "fleet-dashboard.html"}
check("every committed top-level page is re-rendered by persist-ledger.sh",
      (_html - _DEAD_PAGES) <= _rend,
      "committed but never re-rendered: %s" % sorted(_html - _DEAD_PAGES - _rend))
# ...and the exclusions must still exist, or they are silently protecting
# nothing while looking like a considered decision.
check("the dead-page list names only files that are actually committed",
      _DEAD_PAGES <= _html, str(sorted(_DEAD_PAGES - _html)))


# ---------------------------------------------------------------------------
# EVERY SCAN JOB QUEUES BEHIND ITS OWN KIND (B9, 2026-09-03)
# ---------------------------------------------------------------------------
# On 2026-09-01 the Pantheon workflow was dispatched twice, two minutes apart.
# Both scans ran against the same 49 sites at once; lasershows.com measured
# cleanly in one and read ERROR in the other, and both measured fewer sites
# (45, 46) than a scan running alone (47). The ledger lock covered the WRITE
# and worked; nothing covered the scan. A schedule firing during a manual run
# produces exactly this.
#
# The contract: every job the persist job depends on carries a concurrency
# group. It must NOT be one of the shared groups (a scan queued on the ledger
# lock waits behind a 25-second ingest and blocks the next ingest for 45
# minutes), and it must not be shared with a DIFFERENT scanner, or a six-minute
# email check queues behind a 45-minute Pantheon scan for no reason. A
# workflow-level group (the Nexcess SSH scan) satisfies it, since that covers
# every job in the run.
def _scan_jobs(doc):
    """The jobs the persist job needs, i.e. the ones that produce the run."""
    jobs = (doc or {}).get("jobs") or {}
    out = set()
    for jn, job in jobs.items():
        if "persist" in jn and "ledger" in jn:
            needs = job.get("needs") or []
            out.update([needs] if isinstance(needs, str) else needs)
    return sorted(out)


_scan_groups = {}                                    # file -> set(group)
for name in sorted(scanners):
    doc = loaded[name]
    top = (doc.get("concurrency") or {}) if isinstance(doc.get("concurrency"), dict) else {}
    found = _scan_jobs(doc)
    check("%s: the scan job(s) could be identified from the persist job" % name,
          bool(found), "persist-ledger has no needs")
    for jn in found:
        job = (doc.get("jobs") or {}).get(jn) or {}
        c = job.get("concurrency") if isinstance(job.get("concurrency"), dict) else None
        c = c or top
        g = c.get("group")
        check("%s / %s carries a concurrency group" % (name, jn), bool(g),
              "no job-level or workflow-level concurrency")
        if not g:
            continue
        check("%s / %s does not queue on a shared-state lock" % (name, jn),
              g not in SHARED_GROUPS or g == "nexcess-ssh", repr(g))
        check("%s / %s queues rather than cancelling" % (name, jn),
              c.get("queue") == "max" and c.get("cancel-in-progress") is False,
              repr(c))
        _scan_groups.setdefault(name, set()).add(g)

# Distinct per WORKFLOW, not per job: the consent cold sweep and its gating job
# share one group on purpose, so a second consent run waits for both.
_owner = {}
for name, groups in _scan_groups.items():
    for g in groups:
        _owner.setdefault(g, set()).add(name)
_shared_scan = {g: sorted(o) for g, o in _owner.items() if len(o) > 1}
check("no two scanner workflows share a scan group",
      not _shared_scan, str(_shared_scan))


# ---------------------------------------------------------------------------
# THE TEST ALERT IS SENT BY HAND, AND A FAILURE TO SEND IS A FAILURE
# ---------------------------------------------------------------------------
# fleet-alert-test.yml exists to put one labelled message in the channel. Two
# things must stay true. It runs on dispatch only: a test message on a timer
# trains the channel to ignore the real one. And it FAILS when it cannot send,
# unlike the publish step, which warns, because there a webhook must not fail
# a publish that already succeeded and here sending is the whole job.
_t = loaded.get("fleet-alert-test.yml")
check("the test-alert workflow exists", isinstance(_t, dict))
if isinstance(_t, dict):
    _on = _t.get(True) or _t.get("on") or {}
    check("the test alert runs on dispatch only", set(_on) == {"workflow_dispatch"},
          str(sorted(_on)))
    _jobs_t = _t.get("jobs") or {}
    check("...and has no persist or publish job",
          not any(("persist" in j) or ("publish" in j) for j in _jobs_t), str(sorted(_jobs_t)))
    _steps_t = [st for j in _jobs_t.values() for st in (j.get("steps") or [])]
    _send = [st for st in _steps_t if "fleet-alert.py --test" in str(st.get("run", ""))]
    check("...one step sends the test message", len(_send) == 1, str(len(_send)))
    if _send:
        _run = str(_send[0].get("run"))
        check("a missing webhook is an ERROR here, not a warning",
              "::error::TEAMS_WEBHOOK_URL" in _run and "::warning::" not in _run)
        check("...and the step is not continue-on-error",
              not _send[0].get("continue-on-error"))
        check("a refused post shows the webhook's answer", "--fail-with-body" in _run)
        # The shell must not parse the payload. A one-liner reading d["summary"]
        # outlived the payload shape it was written for and killed the step one
        # line before the post, on the first run with a whole webhook URL.
        check("the send step does not parse the payload in shell",
              "json.load" not in _run and '["summary"]' not in _run)
        # The first paste of the URL lost its query string and the endpoint
        # said `ApiVersionInvalid`, which names nothing a person can act on.
        check("a truncated webhook URL is named as such, before the post",
              '*"?"*"sig="*' in _run and "no query string" in _run)
    _perm = _t.get("permissions") or {}
    check("the test alert cannot write to the repo",
          _perm.get("contents") == "read", str(_perm))

# The publish-side step keeps the opposite policy, on purpose.
_pub_doc = loaded.get("_publish-dashboard.yml") or {}
_pub_steps = [st for j in (_pub_doc.get("jobs") or {}).values() for st in (j.get("steps") or [])]
_alert = [st for st in _pub_steps if "fleet-alert.py" in str(st.get("run", ""))]
check("the publish alert step still exists", len(_alert) == 1, str(len(_alert)))
if _alert:
    check("...and cannot fail a publish that succeeded",
          _alert[0].get("continue-on-error") is True)
    check("...and never sends the TEST message", "--test" not in str(_alert[0].get("run")))
    check("...and also names a truncated URL, as a warning",
          '*"?"*"sig="*' in str(_alert[0].get("run"))
          and "::warning::TEAMS_WEBHOOK_URL has no query string" in str(_alert[0].get("run")))


print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
