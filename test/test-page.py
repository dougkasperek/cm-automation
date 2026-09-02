#!/usr/bin/env python3
"""The fleet page, since 2026-08-27: what the file must and must not contain.

The page is built in the browser from a JSON model the renderer embeds
(docs/DASHBOARD-V3.md), so this file can check the MODEL and the page SOURCE.
What the DOM looks like once the script has run is test/test-page.mjs.

Offline. Renders the page from the committed ledger into a temp file; nothing
here reads reports/ or the network. Every assertion is a property, never a
count that was true the day it was written.
"""
import datetime
import importlib.util
import json
import os
import re
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.chdir(ROOT)

_spec = importlib.util.spec_from_file_location(
    "renderer", os.path.join(ROOT, "scripts", "render-dashboard.py"))
RD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RD)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok    " + name)
    else:
        FAIL += 1
        print("FAIL  " + name + (("  <- " + str(detail)[:200]) if detail else ""))


TODAY = datetime.date(2026, 8, 27)
m = RD.build_model("./history", "./data/fleet-inventory.json", TODAY)
html = RD.render_page(m)
feed = RD.emit_data(m)
pd = RD.page_data(m)

print("-- one file, no network --")
check("the page is a complete document", html.startswith("<!doctype html>") and html.rstrip().endswith("</html>"))
_urls = set(re.findall(r'(?:src|href)="(https?://[^"]+)"', html))
check("no script, stylesheet or font is fetched from anywhere",
      not _urls and "fonts.googleapis" not in html and "<link" not in html, repr(sorted(_urls))[:200])
check("the page CSS and JS are inlined from scripts/dashboard/",
      "<style>" in html and "<script>" in html and "id=\"fleet-data\"" in html)
check("the embedded JSON cannot close its own script tag",
      "</script>" not in html.split('id="fleet-data">', 1)[1].split("</script>", 1)[0])

print("\n-- the model the page renders from is the model the feed publishes --")
_pm = re.search(r'<script type="application/json" id="fleet-data">(.*?)</script>', html, re.S)
emb = json.loads(_pm.group(1).replace("<\\/", "</"))
check("the embedded model round-trips", emb == json.loads(json.dumps(pd)))

print("\n-- latest run selection --")
# `health` has TWO cohorts and their run_ids embed the cohort name, so
# 'health-nexcess-<any date>' sorts after 'health-<any date>' as a STRING on
# every date. Selecting a source's latest run by run_id therefore pins it to
# the Nexcess cohort forever: the published feed reported a day-old 22-site
# run as THE health run while the page, keyed per kind by observed_at, showed
# the newer 52-site one -- the exact disagreement emit_data's own docstring
# says the shared model prevents. Assert against the ledger's run records,
# never a pinned id.
_health_runs = [json.loads(l) for l in open("history/runs.jsonl")]
_health_runs = [r for r in _health_runs if r.get("source") == "health"]
_newest = max(_health_runs, key=lambda r: (r.get("observed_at") or "", r["run_id"]))
check("latest['health'] is the newest health run by observed_at, not by run_id string",
      m["latest"]["health"]["run_id"] == _newest["run_id"],
      "%s vs %s" % (m["latest"]["health"]["run_id"], _newest["run_id"]))
# The feed keys runs by SOURCE, the page keys latest by KIND, so the coherence
# property is: the feed's health run is the newer of the page's two health
# kinds -- whichever cohort genuinely ran last.
_page_health = max(
    (pd["latest"][k] for k in ("health", "health-nexcess") if k in pd["latest"]),
    key=lambda r: (r.get("observed_at") or "", r["run_id"]))
check("the feed's runs.health agrees with the page's newest health kind",
      feed["runs"]["health"]["run_id"] == _page_health["run_id"],
      "%s vs %s" % (feed["runs"]["health"]["run_id"], _page_health["run_id"]))
check("site count equals the inventory", len(emb["sites"]) == m["inventory_count"] == len(feed["sites"]))
_by = {s["id"]: s for s in emb["sites"]}
check("every site's health status on the page is the feed's",
      all(_by[s["site_id"]]["health"]["status"] == s["status"] for s in feed["sites"]))
check("every site's consent status on the page is the feed's",
      all(_by[s["site_id"]]["consent"]["status"] == s["axes"]["consent"]["status"]
          for s in feed["sites"] if "consent" in s["axes"]))
check("every reason on the page is the feed's, code for code",
      all([r["code"] for r in _by[s["site_id"]]["health"]["reasons"]] == [r["code"] for r in s["reasons"]]
          for s in feed["sites"]))
check("every fact the feed publishes is on the page record too",
      all(k in _by[s["site_id"]]["f"] for s in feed["sites"] for k in RD.EMIT_FACTS))
check("the page carries the email DNS facts the feed does not",
      all(k in _by[s["site_id"]]["f"] for s in feed["sites"]
          for k in ("spf_present", "dkim_present", "dmarc_at_from_present", "relaxed_aligned")))
check("headline counts are the feed's", emb["counts"] == feed["health"]["counts"] and emb["axes"] == feed["health"]["axes"])
check("the no-health-evidence list is the feed's", emb["no_health_evidence"] == feed["no_health_evidence"])
check("coverage lines are the feed's", emb["coverage"] == feed["coverage"])
check("standing findings and their baselines travel with the page",
      emb["standing"] == m["standing"] and emb["standing_was"] == m["standing_was"])
check("coverage regressions travel with the page (the banner reads them)",
      "coverage_regressions" in emb and emb["coverage_regressions"] == m["coverage_regressions"])

print("\n-- absence is preserved, never coerced --")
_absent = {None, RD.L.UNKNOWN, "n/a"}
check("absence shapes survive into the page record unchanged",
      any(s["f"].get("db_backup_age_days") in _absent for s in emb["sites"])
      and any(s["f"].get("db_backup_age_days") == RD.L.UNKNOWN for s in emb["sites"]))
check("a site nothing inventoried has NO pending list, not an empty 'runs nothing'",
      all(s["pending"] == [] for s in emb["sites"] if s["f"].get("components_checked") is not True)
      and any(s["pending"] for s in emb["sites"] if s["f"].get("components_checked") is True))
check("pending lists sum to the catalogue's pending total",
      sum(len(s["pending"]) for s in emb["sites"]) == emb["components"]["pending_total"])

print("\n-- attestations are claims, four answers kept four --")
_ev = {a["evidence"] for s in emb["sites"] for a in s["att"]}
check("the evidence vocabulary is closed",
      _ev <= {"evidence", "no-evidence", "unclaimed-evidence", "consistent-no", "platform", "not-inventoried", "n/a"}, repr(_ev))
check("a claim of No with no plugin is consistent, not a contradiction",
      all(a["evidence"] != "no-evidence" for s in emb["sites"] for a in s["att"]
          if not (isinstance(a["value"], str) and a["value"].startswith("Yes"))))
check("no attestation is reported as confirmed by a person (none has been)",
      all(not a["by"] for s in emb["sites"] for a in s["att"]))
check("a platform control is not checkable, never 'no evidence'",
      all(a["evidence"] == "platform" for s in emb["sites"] for a in s["att"]
          if isinstance(a["value"], str) and ("Pantheon" in a["value"] or "WAF" in a["value"])))

print("\n-- the page decides how to group, never what is true --")
js = html.split("<script>", 1)[1].split("</script>", 1)[0]
check("no severity threshold is written into the page script",
      "7.0.2" not in js and "BACKUP_CRIT_DAYS" not in js and "PLUGIN_WARN_COUNT" not in js
      and "D.severity_rules" in js)
check("the page never assigns a status", not re.search(r"\.status\s*=\s*['\"]", js))
# The bar for green must be stated beside the banner. Asserted on the phrase
# rather than on "Green requires:" with its colon -- the sentence was cut from
# 45 words to one clause on 2026-08-31 and the colon went with it, which is a
# test pinned to punctuation rather than to the guarantee.
check("the banner's green predicate is printed beside the banner",
      "Green requires" in js)
check("a coverage regression makes the banner 'can't say', not green",
      "coverage_regressions" in js and "Can't say" in js)
check("the page never says 'all good'", "all good" not in html.lower())
# A typed count in the page's prose is the bug in CLAUDE.md's table. Every
# number the page prints must be computed from the model; a number word or a
# digit inside a quoted sentence in page.js is a count that was true the day
# it was written. Allowed: CSS-like sizes and the four tracker vendors' names.
_typed = re.findall(r"'[^']*\b(?:two|three|four|five|six|seven|eight|nine|ten|\d{2,})\s+(?:sites?|domains?|components?|homepages?|decisions?|items?)\b[^']*'", js)
check("no count is typed into the page's prose", not _typed, "; ".join(_typed)[:200])
check("times carry an Eastern offset the RENDERER decided", emb["tz_offset_minutes"] in (-240, -300) and "tz_offset_minutes" in js)
check("the lane rule lives in the page, not in severity",
      "function lane(" in js and not hasattr(RD.SEV, "lane"))

print("\n-- the legacy page still renders, for one cycle --")
_legacy = RD.render(m)
check("render() still produces the previous page", "<table id=fleet>" in _legacy)
check("...and it is not what --out writes", "<table id=fleet>" not in html)


# ---------------------------------------------------------------------------
# THE VULNERABILITY VERDICT IS KEYED ON CHANGE, NOT ON THE WORST SCORE
# ---------------------------------------------------------------------------
# Measured 2026-08-31: eight critical findings, median age 86 days and the
# oldest 857. The page said "Act today" over all of them, which it would have
# said every day for over two years. That is not an alert, it is the page's
# permanent state -- the same defect as the first draft of this page, pointed
# the other way. Both directions are wrong.
_V = m["vulnerabilities"]

# A first run has no earlier run to compare against, and on it EVERYTHING is
# new to us while none of it is new to the world. Calling that "act today"
# would put a red banner over advisories published years ago.
_no_base = RD.build_vulnerabilities([], [], set(), TODAY, [], None)
check("with no baseline, the page knows it cannot compare",
      _no_base["has_baseline"] is False)
_rows = [{"site_id": "a.com", "slug": "x", "cve": "CVE-1", "cvss": 9.8,
          "rating": "Critical", "patched": True, "fix_version": "2",
          "title": "t", "published": "2024-01-01", "version": "1"}]
_first = RD.build_vulnerabilities(_rows, [], set(), TODAY, [], None)
check("...so nothing is marked new on a first run",
      not any(g["new_since_last"] for g in _first["findings"]),
      str([g["new_since_last"] for g in _first["findings"]]))
_seen = RD.build_vulnerabilities(_rows, [], set(), TODAY, _rows, "prev-run")
check("a finding present in the previous run is not new",
      not any(g["new_since_last"] for g in _seen["findings"]))
_fresh = RD.build_vulnerabilities(_rows, [], set(), TODAY, [], "prev-run")
check("a finding absent from the previous run IS new",
      all(g["new_since_last"] for g in _fresh["findings"]))

# Age is the thing that separates findings sharing a score. An unknown age must
# not become 0, which would sort as the newest row and read as disclosed today.
check("age is measured in days from the published date",
      _first["findings"][0]["age_days"] == (TODAY - datetime.date(2024, 1, 1)).days,
      str(_first["findings"][0]["age_days"]))
_undated = RD.build_vulnerabilities(
    [dict(_rows[0], published=None)], [], set(), TODAY, [], None)
check("an unknown age is None, never 0",
      _undated["findings"][0]["age_days"] is None,
      str(_undated["findings"][0]["age_days"]))

# The rendered verdict. "Act today" is reserved for something that CHANGED.
_html_standing = RD.render_vulnerabilities(
    dict(m, vulnerabilities=RD.build_vulnerabilities(
        _rows, [], {"a.com"}, TODAY, _rows, "prev-run")))
check("a standing critical does NOT say act today",
      "Act today" not in _html_standing, "said act today over nothing new")
check("...it names how long it has gone unpatched instead",
      "gone unpatched" in _html_standing and "days" in _html_standing)
_html_new = RD.render_vulnerabilities(
    dict(m, vulnerabilities=RD.build_vulnerabilities(
        _rows, [], {"a.com"}, TODAY, [], "prev-run")))
check("a NEW critical does say act today", "Act today" in _html_new)

# ---------------------------------------------------------------------------
# The version cell carries its sites, 2026-09-01
# ---------------------------------------------------------------------------
# Until this date the page had a "Component and sites" column listing site
# names and a "Version" column listing "3.14, 4.23.4, 4.24.1, ..." beside it.
# 60 of 163 findings span more than one version -- divi is 62 sites over 12 --
# so for those the reader could not tell which site ran which. Reported by the
# dev team.
_multi = [
    {"site_id": "a.com", "slug": "x", "cve": "CVE-9", "cvss": 6.4,
     "rating": "Medium", "patched": True, "fix_version": "5",
     "title": "t", "published": "2024-01-01", "version": "4.1"},
    {"site_id": "b.com", "slug": "x", "cve": "CVE-9", "cvss": 6.4,
     "rating": "Medium", "patched": True, "fix_version": "5",
     "title": "t", "published": "2024-01-01", "version": "4.2"},
    # No version recorded. It must stay a distinct group and say so in words:
    # a blank beside two real numbers reads as "same as above".
    {"site_id": "c.com", "slug": "x", "cve": "CVE-9", "cvss": 6.4,
     "rating": "Medium", "patched": True, "fix_version": "5",
     "title": "t", "published": "2024-01-01", "version": None},
]
_mv = RD.build_vulnerabilities(_multi, [], set(), TODAY, [], None)
_g = _mv["findings"][0]
# The cell is built in the browser from this, so the per-site version is the
# whole contract. A group carrying only a de-duplicated version LIST cannot be
# rendered against sites at all.
check("every affected site carries the version it runs",
      all("version" in x for x in _g["sites"]),
      str(_g["sites"]))
check("...and the versions are the ones each site actually runs",
      {x["site_id"]: x["version"] for x in _g["sites"]}
      == {"a.com": "4.1", "b.com": "4.2", "c.com": None},
      str(_g["sites"]))
check("a site with no recorded version is kept, not dropped",
      len(_g["sites"]) == 3 and any(x["version"] is None for x in _g["sites"]),
      str(_g["sites"]))

# The renderer emits the grouping function and no longer flattens the versions
# into one comma string. Asserted against the source because the cell itself is
# built client-side; the DOM behaviour was checked by hand on the rendered page.
check("the version cell is grouped, not a flat joined list",
      "function versions(g, i)" in RD.VULN_JS
      and "(g.versions || []).join(', ')" not in RD.VULN_JS,
      "VULN_JS still joins versions into one string")
check("...and an absent version renders as words, never a blank",
      "version not recorded" in RD.VULN_JS)
# The fleet page has accepted #site=<id> on load and on hashchange since it was
# built, so this is a link to the one drawer that already exists rather than a
# second one to keep in step.
# --- the findings table sorts by severity, not by what is new ---------------
# Until 2026-09-02 the comparator compared new_since_last BEFORE the sort key,
# unconditionally, so clicking "Severity" did not put the worst finding first
# and the page could open on a 6.4 with a 9.8 below the fold. Measured that
# morning: four new findings at 7.5, 7.2, 6.4 and 6.4 sat above five criticals.
#
# The pin was added on 2026-08-31 for a good reason, since pinning CRITICALS
# instead pinned a months-old backlog. It overcorrected: a new 6.4 is not more
# urgent than a standing 9.8.
#
# Asserted on ORDER IN THE SOURCE, because the comparator is inline JS with no
# seam to call. The sort key must be read before new_since_last is looked at.
_js = RD.VULN_JS
_sort = _js[_js.index("DATA.slice().sort"):_js.index("tb.innerHTML")]
# .find() and not .index(): a missing string returns -1 rather than raising, so
# a broken comparator fails this check instead of crashing the suite. The same
# slip cost a negative control earlier the same day.
_i_key = _sort.find("GET[key](a)")
_i_new = _sort.find("new_since_last ? 0 : 1")
check("the sort reads the chosen key before anything else",
      _i_key >= 0 and _i_new >= 0 and _i_key < _i_new,
      "key at %d, new_since_last at %d" % (_i_key, _i_new))
# It must still BREAK TIES, or eight findings at 9.8 have nothing to rank them
# and what just appeared is indistinguishable from what has sat for two years.
check("...and what is new still breaks ties among equal scores",
      "new_since_last ? 0 : 1" in _sort and "var tie" in _sort)
# No separate tier survives. A first cut kept one behind a flag initialised
# false, so the branch could never run and the handler clearing it did nothing.
check("...and no unconditional new-first tier survives",
      "if (an !== bn)" not in _sort,
      "the new-first tier is still there")

check("each site links to its drawer on the fleet page",
      "#site=" in RD.VULN_JS and "encodeURIComponent" in RD.VULN_JS,
      "site chips are not links into the fleet drawer")

# ---------------------------------------------------------------------------
# A site ruled out of scope is not this page's work, 2026-09-01
# ---------------------------------------------------------------------------
# hoffmanscheese was deleted from Pantheon and ruled production:false while
# carrying 70 of the page's 391 findings -- 18% of a page headed "what needs
# updating" was work on a site that no longer exists.
_scoped = [
    dict(_rows[0], site_id="live.com"),
    dict(_rows[0], site_id="gone.com", cve="CVE-2"),
]
_sites = [{"site_id": "live.com", "host": "h", "production": None},
          {"site_id": "gone.com", "host": "h", "production": False}]
_sc = RD.build_vulnerabilities(_scoped, _sites, set(), TODAY, [], None)
check("an excluded site's findings leave the counts",
      [x["site_id"] for g in _sc["findings"] for x in g["sites"]] == ["live.com"],
      str([x["site_id"] for g in _sc["findings"] for x in g["sites"]]))
check("...and are counted separately rather than vanishing",
      _sc["excluded_findings"] == 1 and _sc["excluded_sites"] == ["gone.com"],
      "%s %s" % (_sc["excluded_findings"], _sc["excluded_sites"]))
# Fail safe, the same way is_production does. Nobody having ruled must never
# mean nobody is watching.
_unruled = RD.build_vulnerabilities(
    _scoped, [{"site_id": "live.com", "host": "h"},
              {"site_id": "gone.com", "host": "h"}], set(), TODAY, [], None)
check("a site with NO ruling is still counted",
      _unruled["excluded_findings"] == 0
      and len([x for g in _unruled["findings"] for x in g["sites"]]) == 2)
_html_sc = RD.render_vulnerabilities(dict(m, vulnerabilities=_sc))
check("the page says how many findings it set aside, and where",
      "ruled out of scope" in _html_sc and "gone.com" in _html_sc,
      "the exclusion is silent")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
