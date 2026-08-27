#!/usr/bin/env python3
"""score-scan.py: the scan and the dashboard must not disagree about severity.

Offline. No network, no terminus, no scan.

WHAT THIS GUARDS
----------------
On 2026-08-27 the scanner and severity.py were measured against the same 52
rows and answered 33 CRIT / 0 OK against 3 CRIT / 11 OK. The scanner carried
the pre-2026-08-19 model in bash. These tests assert the property that had to
hold and did not: **the scan's status is severity.py's status, for every row**.

They deliberately do NOT assert a fleet count, or that a particular row is
CRIT. Both are things a legitimate threshold change is entitled to move, and
CLAUDE.md already has three tests broken that way. What must never change is
that the two agree.
"""

import datetime
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SS = load(os.path.join(ROOT, "scripts", "score-scan.py"), "score_scan")
SEV = load(os.path.join(ROOT, "scripts", "lib", "severity.py"), "severity")

TODAY = datetime.date(2026, 8, 27)
PASS, FAIL = [], []


def check(what, cond, got=None):
    if cond:
        PASS.append(what)
        print("ok    %s" % what)
    else:
        FAIL.append(what)
        print("FAIL  %s%s" % (what, "  <- %s" % (got,) if got is not None else ""))


def row(site, **kw):
    base = {
        "site": site, "framework": "wordpress", "plan": "Basic", "env": "live",
        "frozen": False, "php_version": "8.2", "db_backup_age_days": 0,
        "upstream_pending": 0, "wp_checked": True, "wp_version": "7.1",
        "wp_core_update": "up-to-date", "plugin_updates": 0, "theme_updates": 0,
        "status": "PLACEHOLDER", "notes": "written by the old bash model",
    }
    base.update(kw)
    return base


# ------------------------------------------------- 1. the agreement property
print("-- the scan's status IS severity.py's status --")

FLEET = [
    row("a"),                                                   # clean
    row("b", wp_core_update="7.0.4", wp_version="7.0.3"),       # core pending
    row("c", plugin_updates=19),                                # backlog
    row("d", db_backup_age_days=900),                           # stale backup
    row("e", wp_version="6.9.4", wp_core_update="up-to-date"),  # below floor
    row("f", upstream_pending=3),                               # the old WARN
    row("g", frozen=True),
    row("h", wp_checked=False, wp_version=None, wp_core_update=None,
        plugin_updates=None, theme_updates=None),
]

scored = SS.score_rows([dict(r) for r in FLEET], TODAY)
check("every row is returned", len(scored) == len(FLEET), len(scored))

mismatched = []
for src, out in zip(FLEET, scored):
    want = SEV.evaluate(dict(src), TODAY)["status"]
    if out["status"] != want:
        mismatched.append((src["site"], out["status"], want))
check("every scored status equals severity.evaluate()'s status",
      not mismatched, mismatched)

check("the bash placeholder never survives",
      all(r["status"] != "PLACEHOLDER" for r in scored),
      [r["status"] for r in scored])

# THE RULE THAT MADE OK UNREACHABLE. upstream_pending was a WARN in the bash
# model and every site carried one, so the scanner could not print an OK.
_up = [r for r in scored if r["site"] == "f"][0]
check("a pending upstream commit alone is not a WARN",
      _up["status"] == "OK", _up["status"])

# AND THE ONE THAT PRODUCED 32 OF 33 CRITS.
_core = [r for r in scored if r["site"] == "b"][0]
check("a pending core update is WARN, not CRIT",
      _core["status"] == "WARN", _core["status"])

# The inversion the version floor exists for: below the floor is still CRIT.
_floor = [r for r in scored if r["site"] == "e"][0]
check("a version below the security floor is still CRIT",
      _floor["status"] == "CRIT", _floor["status"])

# UNMEASURED IS NEVER OK.
_unmeas = [r for r in scored if r["site"] == "h"][0]
check("a site the deep scan did not reach does not score OK",
      _unmeas["status"] != "OK", _unmeas["status"])


# ----------------------------------------------------- 2. facts are untouched
print("\n-- scoring rewrites the verdict, never the evidence --")
FACTS = ("site", "framework", "plan", "env", "php_version",
         "db_backup_age_days", "upstream_pending", "wp_checked", "wp_version",
         "wp_core_update", "plugin_updates", "theme_updates", "frozen")
drifted = []
for src, out in zip(FLEET, scored):
    for k in FACTS:
        if src.get(k) != out.get(k):
            drifted.append((src["site"], k, src.get(k), out.get(k)))
check("no measured fact is altered by scoring", not drifted, drifted)

# NO row keeps the incoming note, whatever its status. The first cut fell back
# to it "when severity has nothing to say", which is exactly the FROZEN and OK
# rows -- so the old model's verdict survived in the only place nothing
# overwrites it.
check("no row keeps the note the old model wrote",
      all("old bash model" not in (r.get("notes") or "") for r in scored),
      [(r["site"], r.get("notes")) for r in scored
       if "old bash model" in (r.get("notes") or "")])
check("a row with a finding gets a non-empty note",
      all(r.get("notes") for r in scored if r["status"] in ("CRIT", "WARN")),
      [(r["site"], r.get("notes")) for r in scored if r["status"] in ("CRIT", "WARN")])


# ERROR IS A SCAN OUTCOME, NOT A SEVERITY, and severity has no word for it.
# Scoring a row with no facts turned "we could not reach this site" into SKIP,
# which means "we looked and there is no live environment" -- a different and
# more reassuring statement. Caught by the mock suite on `timeoutsite`.
print("\n-- a row the scan could not read is not scored at all --")
_err = {"site": "timeoutsite", "status": "ERROR", "frozen": False,
        "wp_checked": None, "wp_version": None, "php_version": None,
        "db_backup_age_days": None, "plugin_updates": None,
        "notes": "Environment preflight failed (timeout or unparseable "
                 "response). Status unknown, NOT confirmed absent."}
_scored_err = SS.score_rows([dict(_err)], TODAY)[0]
check("an ERROR row keeps ERROR, and is not downgraded to SKIP",
      _scored_err["status"] == "ERROR", _scored_err["status"])
check("...and keeps the diagnostic saying WHY it is empty",
      "preflight failed" in (_scored_err.get("notes") or ""),
      repr(_scored_err.get("notes")))
check("...while a row that CAN be scored still is",
      SS.score_rows([row("q", plugin_updates=19)], TODAY)[0]["status"] == "WARN")


# ------------------------------------------------------ 3. the failure branch
# A scorer that eats bad input and emits [] reads downstream as "the scan found
# nothing" -- this project's oldest bug, pointed at its own tooling.
print("\n-- bad input is refused, never emitted as an empty scan --")


def run_cli(stdin_text):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "score-scan.py")],
                       input=stdin_text, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


rc, out, errtxt = run_cli("not json at all")
check("unparseable input exits non-zero", rc != 0, rc)
check("...and writes nothing to stdout", out.strip() == "", repr(out[:60]))
check("...and says what went wrong", "could not parse" in errtxt, errtxt[:80])

rc, out, errtxt = run_cli('{"sites": []}')
check("a JSON object rather than an array is refused", rc != 0, rc)
check("...and writes nothing to stdout", out.strip() == "", repr(out[:60]))

rc, out, errtxt = run_cli("[]")
check("an empty array is valid and scores to an empty array", rc == 0, rc)
check("...emitting []", json.loads(out) == [], out[:40])

rc, out, errtxt = run_cli(json.dumps([row("z", plugin_updates=19)]))
check("a real row round-trips through the CLI", rc == 0, rc)
_cli = json.loads(out)
check("...and the CLI agrees with the library",
      _cli[0]["status"] == SS.score_rows([row("z", plugin_updates=19)])[0]["status"],
      _cli[0]["status"])
check("the count line goes to stderr, not stdout",
      "score-scan:" in errtxt and "score-scan:" not in out)


# ----------------------------------------- 4. the shell calls it, and says so
print("\n-- the scanner wires it in, and is loud when it cannot --")
sh = open(os.path.join(ROOT, "scripts", "pantheon-fleet-healthcheck.sh")).read()
check("the scanner invokes score-scan.py", "score-scan.py" in sh)
check("...before it writes any output",
      sh.index("score-scan.py") < sh.index('jq -r \'\n  (["site"'),
      "scoring must precede the CSV/JSON/MD writes")
# A SILENT FALLBACK TO THE WRONG MODEL is exactly how this went three weeks
# unnoticed. Every branch that keeps the bash status must say the summary is
# not the dashboard's model.
# Assert the PROPERTY, not a count: every branch that keeps the bash status
# must also say the summary is not the dashboard's model. Pinning the number
# would break on a legitimate refactor of the branches, which is the mistake
# CLAUDE.md records three tests making.
_keeps = sh.count("keeping the scanner's own status")
_warns = sh.count("NOT the model the dashboard uses")
check("at least one fallback branch exists to test",
      _keeps >= 1, "%d" % _keeps)
check("every branch that keeps the bash status warns it is not the real model",
      _keeps == _warns, "%d keep vs %d warn" % (_keeps, _warns))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
