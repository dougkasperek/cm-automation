#!/usr/bin/env python3
"""
Offline tests for the matcher in scripts/fleet-vuln.py. No network, no key.

WHAT THIS GUARDS
----------------
The version comparison itself is tested in test-vercmp.py against real PHP.
This file tests the COUNTING, which is where this repo has gone wrong before:

  - `13 sites run PDFEmbedder-premium` was 12. The catalogue counted ROWS as
    sites, and one site carries the plugin twice.
  - `312 distinct components` was 310, because WP-CLI reports the on-disk
    directory name and its casing differs per site. Wordfence publishes
    LOWERCASE slugs, so a case-sensitive match would have hit 2 of 12 sites
    and called the other 10 clean.
  - Every row in CLAUDE.md's table is an absence rendered as a value, so
    "no advisory exists" and "not affected" are kept apart here and asserted
    to stay apart.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "fv", os.path.join(HERE, "..", "scripts", "fleet-vuln.py"))
fv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fv)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- %s" % detail) if not cond and detail else ""))


def rec(vid, slug, lo, hi, patched=True, cve=None):
    return (vid,
            {"id": vid, "cve": cve, "published": "2026-01-01 00:00:00",
             "title": "t", "cvss": {"score": 9.0}},
            {"slug": slug, "type": "plugin", "patched": patched,
             "patched_versions": ["9.9"] if patched else [],
             "affected_versions": {"%s - %s" % (lo, hi): {
                 "from_version": lo, "from_inclusive": True,
                 "to_version": hi, "to_inclusive": True}}})


def install(site, slug, version, status="active"):
    return {"site": site, "slug": slug, "version": version,
            "type": "plugin", "status": status}


# --- a site carrying the same component twice is ONE site -----------------
idx = {"dup": [rec("v1", "dup", "1.0", "3.0")]}
rows = [install("a.com", "dup", "2.0"), install("a.com", "dup", "2.5"),
        install("b.com", "dup", "2.0")]
m = fv.evaluate(rows, idx)
check("two vulnerable copies on one site are 3 findings over 2 sites",
      len(m["hits"]) == 3 and len(m["hit_sites"]) == 2,
      "%d hits, %d sites" % (len(m["hits"]), len(m["hit_sites"])))

# --- the casing bug, in the exact shape it took ---------------------------
# WP-CLI reports the directory name; the feed is lowercase. `installs()`
# lowercases, so the index must match on the lowered slug.
idx = {"pdfembedder-premium": [rec("v2", "pdfembedder-premium", "1.0", "4.0")]}
rows = [install("a.com", "pdfembedder-premium", "3.2"),
        install("b.com", "pdfembedder-premium", "3.2")]
m = fv.evaluate(rows, idx)
check("a lowercase slug matches both casings once installs() has lowered them",
      len(m["hit_sites"]) == 2, str(m["hit_sites"]))

# --- no advisory is NOT "not affected" ------------------------------------
idx = {"known": [rec("v3", "known", "1.0", "2.0")]}
rows = [install("a.com", "known", "5.0"),        # advisory exists, outside it
        install("a.com", "bespoke-thing", "1.0")]  # nothing published, ever
m = fv.evaluate(rows, idx)
check("a component with an advisory it is outside counts as not affected",
      m["n_clean"] == 1, str(m["n_clean"]))
check("a component with NO advisory is counted separately, not as clean",
      m["n_no_advisory"] == 1, str(m["n_no_advisory"]))
check("...and the two are never summed into one number",
      m["n_clean"] != m["n_clean"] + m["n_no_advisory"])

# --- an unreadable version is CANNOT SAY, never clean ---------------------
for bad in (None, "", "unknown", "n/a"):
    idx = {"known": [rec("v4", "known", "1.0", "2.0")]}
    m = fv.evaluate([install("a.com", "known", bad)], idx)
    check("version %r on a component with advisories is CANNOT SAY" % bad,
          len(m["unsure"]) == 1 and m["n_clean"] == 0,
          "unsure=%d clean=%d" % (len(m["unsure"]), m["n_clean"]))

# --- an unevaluable range does not clear a site ---------------------------
broken = ("v5", {"id": "v5", "published": "2026-01-01 00:00:00", "cvss": {}},
          {"slug": "known", "patched": True,
           "affected_versions": {"x": {"from_version": "unknown",
                                       "to_version": "2.0"}}})
idx = {"known": [rec("v6", "known", "1.0", "2.0"), broken]}
m = fv.evaluate([install("a.com", "known", "9.0")], idx)
check("a range that will not parse leaves the install CANNOT SAY, not clean",
      len(m["unsure"]) == 1 and m["n_clean"] == 0,
      "unsure=%d clean=%d" % (len(m["unsure"]), m["n_clean"]))

# --- with a fix vs without ------------------------------------------------
idx = {"a": [rec("v7", "a", "1.0", "3.0", patched=True)],
       "b": [rec("v8", "b", "1.0", "3.0", patched=False)]}
rows = [install("s1.com", "a", "2.0"), install("s2.com", "b", "2.0"),
        install("s3.com", "b", "2.0")]
m = fv.evaluate(rows, idx)
check("findings with a fix are separated from findings without",
      len(m["fixed"]) == 1 and len(m["nofix"]) == 2,
      "fixed=%d nofix=%d" % (len(m["fixed"]), len(m["nofix"])))
check("the no-fix group counts sites, not findings",
      len({h[0]["site"] for h in m["nofix"]}) == 2)

# --- boundaries -----------------------------------------------------------
idx = {"c": [rec("v9", "c", "2.0", "3.0")]}
check("the bottom of an affected range IS affected",
      len(fv.evaluate([install("x", "c", "2.0")], idx)["hits"]) == 1)
check("the top of an affected range IS affected",
      len(fv.evaluate([install("x", "c", "3.0")], idx)["hits"]) == 1)
check("just above the top is NOT affected",
      fv.evaluate([install("x", "c", "3.0.1")], idx)["n_clean"] == 1)
check("just below the bottom is NOT affected",
      fv.evaluate([install("x", "c", "1.9.9")], idx)["n_clean"] == 1)

# --- nothing is silently dropped -----------------------------------------
idx = {"a": [rec("va", "a", "1.0", "3.0")], "b": [rec("vb", "b", "1.0", "3.0")]}
rows = [install("s1", "a", "2.0"), install("s1", "b", "9.0"),
        install("s1", "z", "1.0"), install("s2", "a", "unknown")]
m = fv.evaluate(rows, idx)
accounted = (len({h[0]["site"] + h[0]["slug"] + str(h[0]["version"])
                  for h in m["hits"]})
             + len(m["unsure"]) + m["n_clean"] + m["n_no_advisory"])
check("every install lands in exactly one bucket", accounted == len(rows),
      "%d accounted for, %d rows" % (accounted, len(rows)))

# --- the real catalogue and the real Pods record --------------------------
import json                                                # noqa: E402
CAT = os.path.join(HERE, "..", "history", "components.jsonl")
PODS = os.path.join(HERE, "fixtures", "wf-pods-production.json")
if os.path.exists(CAT) and os.path.exists(PODS):
    rows = fv.installs(CAT)
    idx = fv.by_slug(json.load(open(PODS, encoding="utf-8")))
    m = fv.evaluate(rows, idx)
    check("the real catalogue loads as installs", len(rows) > 2000, str(len(rows)))
    check("no site is affected by any Pods advisory (all 31 run 3.3.9.1)",
          len(m["hits"]) == 0, str(m["hits"][:2]))
    check("the 31 Pods installs were actually CHECKED, not skipped",
          m["n_clean"] == 31, str(m["n_clean"]))
else:
    check("the real catalogue and Pods fixture are present", False,
          "%s / %s" % (CAT, PODS))

print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
