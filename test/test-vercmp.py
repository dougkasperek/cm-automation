#!/usr/bin/env python3
"""
Offline tests for scripts/lib/vercmp.py. No network, no key, no feed, no PHP.

WHY THIS SUITE EXISTS
---------------------
Every vulnerability finding rests on "is this installed version inside that
affected range". The catalogue's own numbers say a naive comparison gets the
fleet's most common shape wrong: 96 installs carry four-part versions, so a
string compare puts `4.9.97.43` BELOW `4.9.97.5`.

THE ORACLE IS PHP ITSELF
------------------------
WordPress uses PHP's `version_compare`, so that is what a plugin author means
by "3.3.9.1 is newer than 3.3.9". Rather than reason about the semantics, this
suite replays 2,602 answers taken from real PHP 8.5.9 on 2026-08-30 --
every pair of 25 edge cases plus 2,000 random pairs from the 534 distinct
versions actually installed on the fleet.

That mattered immediately: the first cut of this file asserted
`42.1.1c > 42.1.1` and `1.* is not treated as a glob` by reasoning, and PHP
disagreed with the first one. The code was right and the test was wrong. A
hand-reasoned expectation is evidence about the reasoner.

THE PODS RANGES ARE STILL TRANSCRIBED BY HAND, AND THAT IS TEMPORARY.
They come from docs/VULN-INTEL-REVIEW.md section 1, typed by a person from
NVD. `fleet-vuln.py fixture` pulls the real record; when that fixture is
committed this suite should read it and these literals should go.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
import vercmp                                              # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- %s" % detail) if not cond and detail else ""))


# --- the PHP oracle -------------------------------------------------------
FIX = os.path.join(HERE, "fixtures", "php-version-compare.json")
if not os.path.exists(FIX):
    check("the PHP oracle fixture is present", False, FIX)
else:
    doc = json.load(open(FIX, encoding="utf-8"))
    cases = doc["cases"]
    bad = []
    for a, b, want in cases:
        got = vercmp.compare(a, b)
        if got != want:
            bad.append((a, b, want, got))
    check("compare() agrees with PHP %s on all %d recorded pairs"
          % (doc["php_version"], len(cases)),
          not bad, "; ".join("%r vs %r php=%s ours=%s" % t for t in bad[:5]))
    # A fixture that shrank to nothing would pass vacuously.
    check("the oracle fixture is substantial, not an empty list",
          len(cases) > 2000, str(len(cases)))
    # And it must actually contain the shapes it claims to cover, or it is
    # 2,602 comparisons of trivially similar strings.
    flat = {a for a, _, _ in cases} | {b for _, b, _ in cases}
    check("the oracle covers four-part versions",
          any(len(v.split(".")) == 4 for v in flat))
    check("the oracle covers a non-numeric suffix",
          any(any(c.isalpha() for c in v) for v in flat))

# --- the shapes this fleet actually has -----------------------------------
def cmp_is(a, b, want):
    got = vercmp.compare(a, b)
    check("compare(%r, %r) == %s" % (a, b, want), got == want, "got %s" % got)


cmp_is("4.9.97.43", "4.9.97.5", 1)      # the four-part case, 96 installs
cmp_is("3.3.9.1", "3.3.9", 1)           # the Pods fix vs the last affected
cmp_is("2.8.23.3", "2.8.23.4", -1)
cmp_is("1.0", "1.0", 0)
cmp_is("1.0", "1.0.0", -1)              # a shorter version loses to a number...
cmp_is("1.0", "1.0-dev", 1)             # ...but beats a pre-release form
cmp_is("42.1.1c", "42.1.1", -1)         # PHP: an unknown suffix sorts BELOW

# --- absence is not a comparison ------------------------------------------
def refuses(v):
    try:
        vercmp.compare(v, "1.0")
    except ValueError:
        return True
    return False


for bad_v in (None, "", "unknown", "n/a", "UNKNOWN"):
    check("compare refuses the absent version %r rather than guessing" % bad_v,
          refuses(bad_v))
    check("is_absent(%r)" % bad_v, vercmp.is_absent(bad_v))
check("is_absent('3.3.9.1') is False", not vercmp.is_absent("3.3.9.1"))

# --- the Pods record, CVE-2026-19598 --------------------------------------
PODS = {
    "2.8 - 2.8.23.3": {"from_version": "2.8", "from_inclusive": True,
                       "to_version": "2.8.23.3", "to_inclusive": True},
    "2.9 - 2.9.19.3": {"from_version": "2.9", "from_inclusive": True,
                       "to_version": "2.9.19.3", "to_inclusive": True},
    "3.0 - 3.0.10.3": {"from_version": "3.0", "from_inclusive": True,
                       "to_version": "3.0.10.3", "to_inclusive": True},
    "3.1 - 3.1.4.1":  {"from_version": "3.1", "from_inclusive": True,
                       "to_version": "3.1.4.1", "to_inclusive": True},
    "3.2 - 3.2.8.2":  {"from_version": "3.2", "from_inclusive": True,
                       "to_version": "3.2.8.2", "to_inclusive": True},
    "3.3 - 3.3.9":    {"from_version": "3.3", "from_inclusive": True,
                       "to_version": "3.3.9", "to_inclusive": True},
}

check("the fleet's Pods version 3.3.9.1 is NOT affected",
      vercmp.is_affected("3.3.9.1", PODS) is False)
check("3.3.9, one patch below, IS affected",
      vercmp.is_affected("3.3.9", PODS) is True)
check("2.8.23.3, top of the oldest affected branch, IS affected",
      vercmp.is_affected("2.8.23.3", PODS) is True)
check("2.8.23.4, its fix, is NOT affected",
      vercmp.is_affected("2.8.23.4", PODS) is False)
check("3.1.4.2, a fix in a middle branch, is NOT affected",
      vercmp.is_affected("3.1.4.2", PODS) is False)
check("2.7.9, below every affected branch, is NOT affected",
      vercmp.is_affected("2.7.9", PODS) is False)
check("a version between branches (3.0.11) is NOT affected",
      vercmp.is_affected("3.0.11", PODS) is False)
check("all six affected branches are matched, not just the first",
      sum(1 for r in PODS.values()
          if vercmp.in_range(r["to_version"], r) is True) == 6)

# --- the unbounded marker -------------------------------------------------
check("* as from_version means unbounded below",
      vercmp.in_range("0.0.1", {"from_version": "*", "to_version": "1.0",
                                "to_inclusive": True}) is True)
check("* as to_version means unbounded above",
      vercmp.in_range("99.0", {"from_version": "1.0", "from_inclusive": True,
                               "to_version": "*"}) is True)
check("* at both ends matches everything",
      vercmp.in_range("1.2.3", {"from_version": "*", "to_version": "*"}) is True)
# The vendor states `1.*` matches an asterisk LITERALLY rather than globbing.
# So a version outside 1.x must still fall in this range -- if it did not, we
# would be expanding a glob the feed does not intend.
check("`1.*` is compared literally, not expanded as a glob",
      vercmp.in_range("7.2", {"from_version": "1.*", "from_inclusive": True,
                              "to_version": "*"}) is True)

# --- exclusive bounds -----------------------------------------------------
check("from_inclusive=false excludes the boundary",
      vercmp.in_range("1.0", {"from_version": "1.0", "from_inclusive": False,
                              "to_version": "2.0", "to_inclusive": True}) is False)
check("to_inclusive=false excludes the boundary",
      vercmp.in_range("2.0", {"from_version": "1.0", "from_inclusive": True,
                              "to_version": "2.0", "to_inclusive": False}) is False)

# --- three-valued: "cannot say" never reads as clean ----------------------
check("an unreadable version answers None, not False",
      vercmp.is_affected("unknown", PODS) is None)
check("a missing version answers None, not False",
      vercmp.is_affected(None, PODS) is None)
check("no ranges at all answers None, not False",
      vercmp.is_affected("1.0", {}) is None)
check("a malformed range answers None, not False",
      vercmp.in_range("1.0", {"from_version": "unknown",
                              "to_version": "2.0"}) is None)
check("one unevaluable range among clean ones answers None, not False",
      vercmp.is_affected("9.9", {
          "a": {"from_version": "1.0", "from_inclusive": True,
                "to_version": "2.0", "to_inclusive": True},
          "b": {"from_version": "unknown", "to_version": "3.0"},
      }) is None)
check("but a real match still wins over an unevaluable range",
      vercmp.is_affected("1.5", {
          "a": {"from_version": "1.0", "from_inclusive": True,
                "to_version": "2.0", "to_inclusive": True},
          "b": {"from_version": "unknown", "to_version": "3.0"},
      }) is True)

# --- every real version in the catalogue is comparable --------------------
CAT = os.path.join(HERE, "..", "history", "components.jsonl")
if os.path.exists(CAT):
    seen, broke = set(), []
    for line in open(CAT, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        v = json.loads(line).get("version")
        if vercmp.is_absent(v) or v in seen:
            continue
        seen.add(v)
        try:
            vercmp.compare(v, "1.0")
        except Exception as e:                            # noqa: BLE001
            broke.append((v, str(e)))
    check("every readable version in the real catalogue compares (%d distinct)"
          % len(seen), not broke, str(broke[:5]))
else:
    # history/ is NOT gitignored, unlike reports/. If it is ever missing, say
    # so rather than passing quietly.
    check("history/components.jsonl is present to test against", False, CAT)

print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
