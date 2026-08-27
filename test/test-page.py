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
check("the banner's green predicate is printed beside the banner", "Green requires:" in js)
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

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
