#!/usr/bin/env python3
"""
Can the vulnerability matcher actually FIND a critical?

WHY THIS EXISTS
---------------
As of 2026-08-31 every fleet vulnerability run has topped out at CVSS 6.4.
Nothing critical, nothing high. That may well be true of this fleet. Nothing
proved the pipeline could say otherwise, because the critical path had never
executed against real data -- and when it was looked at, on 2026-08-31, THERE
WAS NO CRITICAL PATH. `evaluate()` bucketed affected / cannot say / not
affected / no advisory and read `cvss` in exactly one place: a print, inside
the no-fix branch, as `(rec.get("cvss") or {}).get("score") or 0`. A 9.8 and a
6.4 differed only in the digits printed, a record with no score printed as 0.0,
and a critical WITH a fix never reached any detail listing at all.

This is the `0 leaking` row in CLAUDE.md's bug table, on the security axis.
The gating sweep reported zero leaks on every run it had ever done; every test
asked whether a CLEAN site reads clean, none planted a leak and demanded it be
found, and "0 leaking" was UNFALSIFIED rather than verified. Same direction
here, and the same fix: plant a critical and require it to be found.

A design mock of the alarm state was rendered and checked in a browser. That
proved the PAGE draws a critical row. It proved nothing about this pipeline --
the row was hand-written into the page's data object and never passed through
fleet-vuln.py, evaluate(), or a version comparison.

WHAT IS PLANTED
---------------
test/fixtures/vuln-critical-synthetic.json, five SYNTHETIC records against
slugs the fleet really runs (measured from history/components.jsonl,
2026-08-31: divi is on 66 sites, 36 of them at 4.27.6). It is synthetic and
offline on purpose -- the real feed is 147 MB behind a rate limit measured at
somewhere between 22.5 and 36.5 minutes, so a test may never fetch it.

  c001  CRITICAL 9.8, unauthenticated RCE, range COVERS 4.27.6, fix at 4.28.0
        -> must be found, banded critical, ranked first, and read as an UPDATE
  c002  CRITICAL 9.8, same slug, range ends at 3.29.3
        -> must come back NOT AFFECTED. Without this the suite cannot tell
           detection from a rule that fires on everything.
  m001  MEDIUM 6.4 -- the real ceiling every run has hit
        -> the critical must rank ABOVE it
  c003  CRITICAL 9.1, patched=false
        -> must read as a DECISION, and fix_version must be None
  u001  no published score
        -> must band "unknown". Never "low", never "none", never 0.0

The band table is separately checked against the vendor's OWN `cvss.rating` on
all 17 REAL advisories in test/fixtures/wf-pods-production.json, so the
thresholds are not a belief about where the bands sit.

NEGATIVE CONTROLS ARE PART OF THE SUITE, NOT A ONE-OFF
------------------------------------------------------
Four regressions are applied here and each is required to be CAUGHT. CLAUDE.md:
a check written the same hour as the fix is the likeliest to be vacuous, and
this repo has shipped a check that matched nothing and could never fail, and
another whose title claimed more than its predicate. Running the breaks on
every push is what stops this file going quietly vacuous later.

    python3 test/test-vuln-critical.py

Offline. No network, no key, no feed fetch.
"""

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "fv", os.path.join(HERE, "..", "scripts", "fleet-vuln.py"))
fv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fv)

FIXTURE = os.path.join(HERE, "fixtures", "vuln-critical-synthetic.json")
PODS = os.path.join(HERE, "fixtures", "wf-pods-production.json")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- %s" % detail) if not cond and detail else ""))


# The fleet as it really is, in miniature. Versions and slugs measured from
# history/components.jsonl on 2026-08-31.
# ORDER MATTERS, and it is deliberate. The MEDIUM is listed first so that an
# unranked pipeline returns it first: `sorted()` is stable, so with the
# ranking removed the output falls back to this order. The first cut of this
# file listed the critical first, and the "ranking dropped" negative control
# PASSED while ranking was broken -- the critical came out on top by accident
# of the fixture. A check that passes for the wrong reason is the thing this
# file exists to prevent.
INSTALLS = [
    {"site": "a.com", "slug": "wps-hide-login", "version": "1.9.16",
     "type": "plugin", "status": "active"},
    {"site": "a.com", "slug": "divi-dash", "version": "1.5.0",
     "type": "plugin", "status": "active"},
    {"site": "a.com", "slug": "divi", "version": "4.27.6",
     "type": "theme", "status": "active"},
    {"site": "b.com", "slug": "divi", "version": "4.27.6",
     "type": "theme", "status": "active"},
    # Outside c001's range AND outside c002's. Not affected by either.
    {"site": "c.com", "slug": "divi", "version": "5.11.1",
     "type": "theme", "status": "active"},
    {"site": "a.com", "slug": "divi-booster", "version": "4.0.0",
     "type": "plugin", "status": "active"},
]


def pipeline():
    """Fixture bytes -> parse -> by_slug -> evaluate.

    Deliberately through the REAL entry points rather than a hand-built index.
    The design mock proved the page renders a critical row and nothing about
    the pipeline, because the row never went through any of this.
    """
    raw = open(FIXTURE, "rb").read()
    feed, why = fv.parse(raw)
    if feed is None:
        raise AssertionError("fixture is not feed-shaped: %s" % why)
    return fv.evaluate(INSTALLS, fv.by_slug(feed))


def one(findings, slug, site=None, vid=None):
    for f in findings:
        if f["slug"] != slug:
            continue
        if site and f["site"] != site:
            continue
        if vid and not str(f["vuln_id"]).endswith(vid):
            continue
        return f
    return None


def assertions():
    """Every claim about the critical path, as (name, bool, detail).

    A function so the negative controls can re-run it under a break and
    require named checks to go red.
    """
    m = pipeline()
    fs = m["findings"]
    out = []

    def a(name, cond, detail=""):
        out.append((name, bool(cond), str(detail)))

    crit = one(fs, "divi", site="a.com", vid="c001")
    med = one(fs, "wps-hide-login")
    nofix = one(fs, "divi-booster")
    unscored = one(fs, "divi-dash")

    # --- it is found at all ------------------------------------------------
    a("the planted critical is surfaced as a finding", crit is not None,
      "slugs found: %s" % sorted({f["slug"] for f in fs}))
    a("it is found on every site running the affected version",
      len([f for f in fs if f["slug"] == "divi"
           and str(f["vuln_id"]).endswith("c001")]) == 2,
      [f["site"] for f in fs if f["slug"] == "divi"])

    # --- it is classified critical, by the WORD ---------------------------
    a("its CVSS 9.8 bands as critical",
      crit and crit["band"] == "critical", crit and crit["band"])
    a("the run's worst band is reported as critical",
      m["worst_band"] == "critical", m["worst_band"])
    a("the band is a word, not a bare number a reader must decode",
      crit and isinstance(crit["band"], str)
      and crit["band"] not in ("", "9.8"), crit and crit["band"])
    a("the score is carried through beside the band",
      crit and crit["score"] == 9.8, crit and crit["score"])

    # --- it ranks above the mediums the fleet already reports -------------
    a("the medium (6.4) is also found, so the comparison is real",
      med is not None and med["band"] == "medium", med and med["band"])
    a("the critical ranks ABOVE the 6.4 medium",
      crit and med and fs.index(crit) < fs.index(med),
      "critical at %s, medium at %s" % (
          crit and fs.index(crit), med and fs.index(med)))
    a("the worst finding is first in the list, not buried",
      fs and fs[0]["band"] == "critical", fs and fs[0]["band"])

    # --- a fix exists, so it reads as an UPDATE ---------------------------
    a("the fix version is carried through",
      crit and crit["fix_version"] == "4.28.0", crit and crit["fix_version"])
    a("...so it reads as an update, not a decision",
      crit and crit["action"] == "update", crit and crit["action"])
    a("the NEAREST fix is named, not the newest release the vendor shipped",
      crit and crit["fix_version"] != "5.12.0", crit and crit["fix_version"])

    # --- the critical WITHOUT a fix is a decision, and says so ------------
    a("an unpatched critical carries no fix version",
      nofix and nofix["fix_version"] is None, nofix and nofix["fix_version"])
    a("...and reads as a decision rather than an update",
      nofix and nofix["action"] == "decide", nofix and nofix["action"])
    a("...and is still banded critical",
      nofix and nofix["band"] == "critical", nofix and nofix["band"])

    # --- THE OTHER HALF: detection is not a rule that fires on everything --
    # c002 is CRITICAL 9.8 on the same slug and must NOT fire on 4.27.6.
    a("a critical whose range excludes our version is NOT reported",
      one(fs, "divi", vid="c002") is None,
      [f["vuln_id"] for f in fs if f["slug"] == "divi"])
    a("...and the site outside every range is not reported at all",
      one(fs, "divi", site="c.com") is None,
      [f["site"] for f in fs if f["slug"] == "divi"])
    a("...it is counted as not affected, not as unmeasured",
      m["n_clean"] >= 1, "n_clean=%s unsure=%s" % (m["n_clean"], len(m["unsure"])))
    a("nothing lands in CANNOT SAY: every version here is readable",
      len(m["unsure"]) == 0, m["unsure"])

    # --- an unscored advisory is UNKNOWN, never the reassuring end --------
    a("an advisory with no published score bands as unknown",
      unscored and unscored["band"] == "unknown", unscored and unscored["band"])
    a("...never as low or none, which would bury it",
      unscored and unscored["band"] not in ("low", "none"),
      unscored and unscored["band"])
    a("...and its score stays None, never 0.0",
      unscored and unscored["score"] is None, unscored and unscored["score"])
    a("an unknown-scored finding ranks above the mediums, not below",
      unscored and med and fs.index(unscored) < fs.index(med),
      "unknown at %s, medium at %s" % (
          unscored and fs.index(unscored), med and fs.index(med)))

    # --- the counts a headline would be built from ------------------------
    a("critical findings are counted under their own band",
      m["n_by_band"].get("critical") == 3, m["n_by_band"])
    a("the medium is not summed into the critical count",
      m["n_by_band"].get("medium") == 1, m["n_by_band"])
    return out


# ---------------------------------------------------------------------------
# the positive run
# ---------------------------------------------------------------------------

print("--- the planted critical must be FOUND ---")
BASE = assertions()
for name, cond, detail in BASE:
    check(name, cond, detail)

# ---------------------------------------------------------------------------
# the band table, against REAL vendor data
# ---------------------------------------------------------------------------
print()
print("--- the band thresholds, against the vendor's own rating ---")
pods = json.load(open(PODS, encoding="utf-8"))
disagree = []
for vid, r in pods.items():
    c = r.get("cvss") or {}
    if c.get("rating") is None or c.get("score") is None:
        continue
    ours = fv.band(c["score"])
    theirs = str(c["rating"]).lower()
    if ours != theirs:
        disagree.append((vid, c["score"], theirs, ours))
check("our band agrees with Wordfence on all %d real scored advisories"
      % len([1 for r in pods.values() if (r.get("cvss") or {}).get("score") is not None]),
      not disagree, disagree)
check("the real Pods record does contain criticals, so that check is not vacuous",
      any(fv.band((r.get("cvss") or {}).get("score")) == "critical"
          for r in pods.values()),
      sorted({fv.band((r.get("cvss") or {}).get("score")) for r in pods.values()}))

# The boundaries, which is where a band table is wrong if it is wrong at all.
print()
print("--- band boundaries ---")
for score, want in ((10, "critical"), (9.0, "critical"), (8.9, "high"),
                    (7.0, "high"), (6.9, "medium"), (6.4, "medium"),
                    (4.0, "medium"), (3.9, "low"), (0.1, "low"),
                    (0, "none")):
    check("CVSS %s bands as %s" % (score, want), fv.band(score) == want,
          fv.band(score))
for bad, why in ((None, "null score"), ("", "empty string"),
                 ("n/a", "a sentinel"), (True, "a boolean"),
                 ({}, "an object")):
    check("%s bands as unknown, not as a value" % why,
          fv.band(bad) == fv.UNKNOWN_BAND, fv.band(bad))


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS
# ---------------------------------------------------------------------------
# Break the pipeline four ways and require each break to be CAUGHT. A check
# written the same hour as the fix is the likeliest to be vacuous, and this
# repo has shipped one that matched nothing and could never fail.

def break_band():
    """Drop the band derivation: every finding bands the same."""
    orig = fv.band
    fv.band = lambda score: "medium"
    return lambda: setattr(fv, "band", orig)


def break_score():
    """Drop the score parsing: no finding carries a CVSS score at all.

    Separate from break_band on purpose. The first cut had one control for
    both and listed the ranking checks under it -- but with the score intact,
    ranking still put the 9.8 first, correctly, and the control was demanding
    a failure that should not happen.
    """
    orig = fv.score_of
    fv.score_of = lambda rec: None
    return lambda: setattr(fv, "score_of", orig)


def break_version_range():
    """Drop the version comparison: every advisory matches every install."""
    orig = fv.vercmp.is_affected
    fv.vercmp.is_affected = lambda version, av: True
    return lambda: setattr(fv.vercmp, "is_affected", orig)


def break_ranking():
    """Drop the ranking: findings come back in whatever order they were built."""
    orig = fv.rank_key
    fv.rank_key = lambda f: 0
    return lambda: setattr(fv, "rank_key", orig)


def break_fix_version():
    """Drop the fix-version passthrough: a fixable critical looks unfixable."""
    orig = fv.fix_version
    fv.fix_version = lambda installed, sw: None
    return lambda: setattr(fv, "fix_version", orig)


# Each break, and the checks it MUST take down. Naming them is the point: a
# break that merely fails "something" could be failing for an unrelated reason.
BREAKS = [
    ("band derivation dropped", break_band, [
        "its CVSS 9.8 bands as critical",
        "the run's worst band is reported as critical",
        "an advisory with no published score bands as unknown",
        "critical findings are counted under their own band",
    ]),
    ("CVSS score parsing dropped", break_score, [
        "the score is carried through beside the band",
        "its CVSS 9.8 bands as critical",
        "the run's worst band is reported as critical",
    ]),
    ("version-range comparison dropped", break_version_range, [
        "a critical whose range excludes our version is NOT reported",
        "...and the site outside every range is not reported at all",
        "...it is counted as not affected, not as unmeasured",
    ]),
    ("ranking dropped", break_ranking, [
        "the critical ranks ABOVE the 6.4 medium",
        "the worst finding is first in the list, not buried",
    ]),
    ("fix-version passthrough dropped", break_fix_version, [
        "the fix version is carried through",
        "...so it reads as an update, not a decision",
    ]),
]

print()
print("--- negative controls: each break must be CAUGHT ---")
for label, make, must_fail in BREAKS:
    restore = make()
    try:
        broken = dict((n, c) for n, c, _ in assertions())
    except Exception as e:                                 # noqa: BLE001
        # A break that makes the pipeline raise is still caught, but say so
        # rather than counting it as the assertion doing the work.
        broken = None
        err = "%s: %s" % (type(e).__name__, e)
    finally:
        restore()

    if broken is None:
        check("%s -> caught (pipeline raised: %s)" % (label, err), True)
        continue
    missed = [n for n in must_fail if broken.get(n) is not False]
    check("%s -> caught by every check named for it" % label, not missed,
          "these still passed while broken: %s" % missed)
    # And it must not be catching by accident everywhere: the suite must
    # still be measuring something specific.
    check("...%s does not simply fail everything" % label,
          any(v for v in broken.values()),
          "every single check failed, so the break is too blunt to be evidence")

# The restore actually restored. A negative control that leaks its monkeypatch
# would make every later run meaningless.
print()
after = dict((n, c) for n, c, _ in assertions())
check("the suite is green again after every break was restored",
      all(after.values()),
      [n for n, v in after.items() if not v])

print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
