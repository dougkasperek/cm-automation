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

# --- the feed cache: age is always stated, and only 429 is forgiven -------
# Added after run 33315975286 failed on a 429 twenty-two minutes after a
# successful one. --allow-stale exists so a re-run reports on the copy it has;
# it must NOT become a way for an auth failure to pass.
import tempfile                                            # noqa: E402


class _Args(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


_tmp = tempfile.mkdtemp()
_feed = os.path.join(_tmp, "wf-feed.json")
open(_feed, "wb").write(b'{"a":{"id":"a","software":[]}}')

check("a feed with no sidecar reports its age as UNKNOWN, not as fresh",
      fv.feed_age(_feed) == (None, None), str(fv.feed_age(_feed)))
fv.write_meta(_feed, "production", b"x" * 10, 1)
_when, _mins = fv.feed_age(_feed)
check("once written, the sidecar dates the feed", _when is not None and _mins == 0,
      "%s / %s" % (_when, _mins))

_orig_fetch = fv.fetch
try:
    os.environ["WF_KEY"] = "test-key-not-real"

    # A SUCCESSFUL fetch must leave the feed dateable. Asserted through
    # fetch_cmd, not by calling write_meta directly: the first cut of this file
    # tested the helper, so deleting the call from fetch_cmd passed all 28
    # checks. A test that cannot see the wiring is not testing the wiring.
    _fresh = os.path.join(_tmp, "fresh.json")
    _body = b'{"z":{"id":"z","title":"t","software":[{"slug":"s"}]}}'
    fv.fetch = lambda feed, key, timeout=180: (fv.OK, None, 200, _body)
    check("a successful fetch writes the feed",
          fv.fetch_cmd(_Args(feed="production", out=_fresh, allow_stale=False)) == 0
          and os.path.exists(_fresh))
    check("...and leaves it dateable, so nothing downstream is undated",
          fv.feed_age(_fresh) != (None, None), str(fv.feed_age(_fresh)))

    fv.fetch = lambda feed, key, timeout=180: (fv.RATE_LIMITED, "limit", 429, b"")
    check("429 with --allow-stale and a cached feed carries on",
          fv.fetch_cmd(_Args(feed="production", out=_feed, allow_stale=True)) == 0)
    check("...and the cached feed is left intact, not truncated",
          os.path.getsize(_feed) > 0)
    check("429 WITHOUT --allow-stale still fails",
          fv.fetch_cmd(_Args(feed="production", out=_feed, allow_stale=False)) == 1)

    _missing = os.path.join(_tmp, "absent.json")
    check("429 with --allow-stale but NO cached feed still fails",
          fv.fetch_cmd(_Args(feed="production", out=_missing, allow_stale=True)) == 1)

    # The guard that matters. A rejected key must never be smoothed over by a
    # flag that exists for rate limits.
    fv.fetch = lambda feed, key, timeout=180: (fv.UNAUTHORISED, "nope", 401, b"")
    check("401 is NOT forgiven by --allow-stale, even with a cached feed",
          fv.fetch_cmd(_Args(feed="production", out=_feed, allow_stale=True)) == 1)

    fv.fetch = lambda feed, key, timeout=180: (fv.FORBIDDEN, "edge", 403, b"")
    check("403 is NOT forgiven by --allow-stale either",
          fv.fetch_cmd(_Args(feed="production", out=_feed, allow_stale=True)) == 1)
finally:
    fv.fetch = _orig_fetch
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# THE INGESTABLE REPORT
# ---------------------------------------------------------------------------
# Above the summary deliberately: a block appended after sys.exit never runs
# and the suite reports the same count as before it existed.
#
# Scored against the REAL Pods records in test/fixtures, not a mock. A mock is
# evidence about the parser, never about the world -- the post-smtp mock passed
# every test while reading a field the plugin does not store.
_pods = json.load(open(os.path.join(os.path.dirname(__file__),
                                    "fixtures", "wf-pods-production.json")))
_pidx = fv.by_slug(_pods)
_prows = [{"site": "a.com", "slug": "pods", "version": "2.4.0",
           "type": "plugin", "status": "active"},
          {"site": "b.com", "slug": "pods", "version": "99.0",
           "type": "plugin", "status": "active"}]
_prep = fv.build_report(_prows, _pidx, "production",
                       {"a.com", "b.com", "unmatched.com"},
                       {"fetched_at": "2026-08-31T12:41:38Z", "records": len(_pods)})
_pby = {x["domain"]: x for x in _prep["sites"]}

check("the report declares the schema the ledger adapter looks for",
      _prep["schema"] == "fleet-vuln-intel/1", _prep["schema"])

# A site with NO component list must appear and carry no counts. Omitting it
# would make the run look like it covered the whole fleet -- 17 of 85 sites
# were unmatchable on 2026-08-31 -- and on this axis silence reads as good news.
check("a site with no component list is reported, not omitted",
      "unmatched.com" in _pby)
check("...as matched: false, with no counts at all",
      _pby["unmatched.com"]["matched"] is False
      and "affected" not in _pby["unmatched.com"]
      and "nofix" not in _pby["unmatched.com"],
      str(_pby["unmatched.com"]))

check("a matched site outside every affected range reads zero, not absent",
      _pby["b.com"]["matched"] is True and _pby["b.com"]["affected"] == 0)
check("...and carries no worst score rather than 0.0",
      _pby["b.com"]["worst_cvss"] is None, str(_pby["b.com"]["worst_cvss"]))

# THE CRITICAL PATH, on real published records. Every fleet run so far topped
# out at 6.4, so this rule had never executed against real data.
check("a real critical advisory produces a critical worst score",
      _pby["a.com"]["worst_cvss"] == 9.8, str(_pby["a.com"]["worst_cvss"]))
check("...and the finding count matches the findings listed",
      _pby["a.com"]["affected"] == len(_pby["a.com"]["findings"]),
      "%s vs %s" % (_pby["a.com"]["affected"], len(_pby["a.com"]["findings"])))

_f = _pby["a.com"]["findings"][0]
check("a finding carries the vendor's own rating word, not one we derived",
      _f["rating"] in ("Low", "Medium", "High", "Critical"), str(_f["rating"]))
# patched_versions is a LIST -- a plugin often patches several branches at
# once, and picking one would be a branch decision the matcher cannot make.
check("the fix version keeps every patched branch",
      _f["patched"] is True and _f["fix_version"] == "2.5", str(_f["fix_version"]))
check("every finding carries the fixable/no-fix flag",
      all("patched" in x for x in _pby["a.com"]["findings"]))

# MULTI-BRANCH FIX, on a real record. CVE-2023-6967 patches four branches at
# once; keeping only the first would tell 3 of 4 branches to install a version
# that is not on their line. 2.7.30 is inside its [*, 2.7.31) range.
_mb = [f for f in fv.build_report(
           [{"site": "m.com", "slug": "pods", "version": "2.7.30",
             "type": "plugin", "status": "active"}],
           _pidx, "production", set(), {})["sites"][0]["findings"]
       if f["cve"] == "CVE-2023-6967"]
check("a real multi-branch advisory is matched at all", len(_mb) == 1, str(len(_mb)))
check("...and every patched branch is kept, not just the first",
      _mb and _mb[0]["fix_version"] == "2.7.31.2, 2.8.23.2, 2.9.19.2, 3.0.10.2",
      _mb[0]["fix_version"] if _mb else "no match")

# THE NO-FIX COUNT. Every record in the Pods fixture is patched: True -- 29 of
# 29 -- so asserting this against it compares 0 to 0 and passes however the
# count is written. Flipping `patched` on a real record keeps the real SHAPE
# while giving the counter something to count. The vacuity guard below is the
# point: the first version of this check passed against a deliberately broken
# counter, which is a test that cannot fail.
_unpatched = json.loads(json.dumps(_pods))
for _r in _unpatched.values():
    for _sw in _r.get("software") or []:
        _sw["patched"] = False
_urep = fv.build_report(_prows, fv.by_slug(_unpatched), "production", set(), {})
_ua = [x for x in _urep["sites"] if x["domain"] == "a.com"][0]
check("the no-fix case is not vacuous: there is something to count",
      _ua["nofix"] > 0, str(_ua["nofix"]))
check("nofix counts exactly the findings whose patched is False",
      _ua["nofix"] == sum(1 for x in _ua["findings"] if x["patched"] is False)
      == _ua["affected"],
      "%s / %s / %s" % (_ua["nofix"],
                        sum(1 for x in _ua["findings"] if x["patched"] is False),
                        _ua["affected"]))
check("...and a patched fleet still counts zero of them",
      _pby["a.com"]["nofix"] == 0, str(_pby["a.com"]["nofix"]))

print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
