#!/usr/bin/env python3
"""
Self-check for scripts/lib/severity.py.

Every case below is either a rule, or a REGRESSION this module was written to
prevent. The regressions are the point: the old model scored 33 of 52 sites
CRIT and nothing OK, and it did that while missing the one genuinely dangerous
site in the fleet. Both failures are asserted against here by name.

Run: ./test/test-severity.py
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_s = importlib.util.spec_from_file_location(
    "severity", os.path.join(ROOT, "scripts", "lib", "severity.py"))
S = importlib.util.module_from_spec(_s)
_s.loader.exec_module(S)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- " + detail) if (detail and not cond) else ""))


def site(**kw):
    """A healthy deep-scanned site. Each test breaks exactly one thing."""
    base = {
        "site_id": "example.com",
        "frozen": False,
        "wp_checked": True,
        "php_version": "8.2",
        "wp_version": "7.0.4",
        "wp_core_update": "up-to-date",
        "db_backup_age_days": 0,
        "plugin_updates": 0,
        "theme_updates": 0,
        "upstream_pending": 0,
        "in_workbook": True,
    }
    base.update(kw)
    return base


def st(**kw):
    return S.evaluate(site(**kw))["status"]


def codes(**kw):
    return [r["code"] for r in S.evaluate(site(**kw))["reasons"]]


# --------------------------------------------------------------------------
# The baseline the old model could not produce
# --------------------------------------------------------------------------
check("a fully current site is OK", st() == "OK", st())

# --------------------------------------------------------------------------
# REGRESSION 1: the WARN floor. Every site in the fleet carries 1 or 2 pending
# Pantheon upstream commits, always. The old model made that a WARN, so no site
# could ever score OK and the page had 0 healthy out of 52.
# --------------------------------------------------------------------------
check("upstream commits alone do NOT score", st(upstream_pending=2) == "OK",
      st(upstream_pending=2))
check("upstream commits are still reported as info",
      "2 Pantheon upstream commit(s) pending" in S.evaluate(site(upstream_pending=2))["info"])

# --------------------------------------------------------------------------
# REGRESSION 2: the inversion. cm-whitelabel runs 6.9.4 -- below the wp2shell
# fix -- and its `wp_core_update` reads "up-to-date", so the old core-update
# rule did not fire on the one genuinely exposed site in the fleet. It scored
# CRIT only by accident of a stale backup. This is the case that must never
# regress: up-to-date must not be able to mask a below-floor version.
# --------------------------------------------------------------------------
check("6.9.4 is CRIT even when core says up-to-date",
      st(wp_version="6.9.4", wp_core_update="up-to-date") == "CRIT")
check("...and it is the version rule that fires, not something incidental",
      codes(wp_version="6.9.4", wp_core_update="up-to-date") == ["wp_below_floor"],
      str(codes(wp_version="6.9.4", wp_core_update="up-to-date")))
check("7.0.2 exactly, the floor itself, is not below it",
      st(wp_version="7.0.2") == "OK")

# --------------------------------------------------------------------------
# REGRESSION 3: one minor version behind is not an emergency. 32 of 52 sites
# are on 7.0.3 with 7.0.4 pending, both above the wp2shell fix. The old model
# made all 32 CRIT, which is 97% of its CRIT count.
# --------------------------------------------------------------------------
check("a pending core update is WARN, not CRIT",
      st(wp_version="7.0.3", wp_core_update="7.0.4") == "WARN")

# --------------------------------------------------------------------------
# Backups
# --------------------------------------------------------------------------
check("backup today is OK", st(db_backup_age_days=0) == "OK")
check("backup 8 days ago is WARN", st(db_backup_age_days=8) == "WARN")
check("backup 31 days ago is CRIT", st(db_backup_age_days=31) == "CRIT")
check("backup 721 days is CRIT", st(db_backup_age_days=721) == "CRIT")
check("the 9999 sentinel reads as 'none found', not as 9999 days",
      codes(db_backup_age_days=9999) == ["backup_missing"]
      and "9999" not in S.evaluate(site(db_backup_age_days=9999))["reasons"][0]["text"])

# --------------------------------------------------------------------------
# PHP
# --------------------------------------------------------------------------
import datetime
TODAY = datetime.date(2026, 8, 19)


def stp(**kw):
    return S.evaluate(site(**kw), TODAY)["status"]


check("PHP 7.4 is CRIT (EOL 2022-11-28)", stp(php_version="7.4") == "CRIT")
check("PHP 8.1 is CRIT (EOL 2025-12-31, and a `< 8.0` floor missed it)",
      stp(php_version="8.1") == "CRIT")
check("PHP 8.3 is fine", stp(php_version="8.3") == "OK")
# 46 of 52 sites are on 8.2. Scoring a shared fleet-wide deadline per-site is
# how upstream_pending put a WARN floor under the whole fleet.
check("PHP 8.2, expiring 2026-12-31, is NOT a per-site WARN",
      stp(php_version="8.2") == "OK")
check("...but the deadline is still stated on the row",
      any("leaves security support" in x
          for x in S.evaluate(site(php_version="8.2"), TODAY)["info"]))
check("an unrecognised PHP version is not assumed supported",
      S.php_support("9.9", TODAY)[0] == "unknown")
check("php_support does not fail open when today is omitted",
      S.php_support("7.4")[0] == "eol")

# --------------------------------------------------------------------------
# Plugins: a graduated threshold, because a single >0 test was half the old
# model's WARNs and the fleet spreads continuously from 0 to 29.
# --------------------------------------------------------------------------
check("5 plugin updates is not a severity signal", st(plugin_updates=5) == "OK")
check("5 plugin updates is still shown as info",
      "5 plugin update(s) pending" in S.evaluate(site(plugin_updates=5))["info"])
check("10 plugin updates is WARN", st(plugin_updates=10) == "WARN")
check("29 plugin updates is WARN", st(plugin_updates=29) == "WARN")

# --------------------------------------------------------------------------
# UNKNOWN IS NEVER OK. This is settled principle 5 and the single most
# repeated bug in this project: a confident value standing in for an absence.
# --------------------------------------------------------------------------
check("a site that was never deep-scanned is SKIP, not OK",
      st(wp_checked=False, php_version="unknown", wp_version=None,
         wp_core_update=None, db_backup_age_days=None,
         plugin_updates=None, upstream_pending=None) == "SKIP")
check("a deep scan that could not read the version does not reach OK",
      st(wp_version="unknown") == "WARN", st(wp_version="unknown"))
check("wp_core_update 'unknown' does not fire the core rule",
      "core_update" not in codes(wp_core_update="unknown"))
check("wp_core_update 'n/a' (api-only, nobody looked) does not fire either",
      "core_update" not in codes(wp_core_update="n/a"))
check("a null backup age is not read as a fresh backup",
      "backup_stale" not in codes(db_backup_age_days=None)
      and "backup_missing" not in codes(db_backup_age_days=None))
check("frozen short-circuits everything", st(frozen=True, wp_version="6.0") == "FROZEN")

# A site the health scanner has NEVER reached -- e.g. one seen only by the
# email/DNS check, which is all 32 Nexcess and outlier-host sites today. It
# carries no health fact keys at all. Before this branch existed these fell
# through to SKIP and the first render read "35 SKIP" for a fleet with three
# real skips, turning the project's largest evidence gap into a shrug.
check("a site with no health observation at all is UNKNOWN, not SKIP",
      S.evaluate({"site_id": "nexcess-only.com", "in_workbook": True})["status"] == "UNKNOWN")
check("UNKNOWN and SKIP are not the same state",
      S.evaluate({"site_id": "x"})["status"]
      != S.evaluate(site(wp_checked=False, php_version="unknown"))["status"])
check("an email-only row is still UNKNOWN even carrying email facts",
      S.evaluate({"site_id": "x", "spf_present": True,
                  "dmarc_at_from_present": True})["status"] == "UNKNOWN")
check("presence of a health fact is what counts, not its value",
      S.evaluate({"site_id": "x", "php_version": "unknown",
                  "wp_checked": False})["status"] == "SKIP")

# --------------------------------------------------------------------------
# The production flag. Tri-state on purpose, and null must fail SAFE.
# --------------------------------------------------------------------------
check("production null counts as production",
      S.evaluate(site(production=None))["production"] is True)
check("production absent counts as production",
      S.evaluate(site())["production"] is True)
check("production false is excluded",
      S.evaluate(site(production=False))["production"] is False)
check("an excluded site still gets a real score, it is not silenced",
      S.evaluate(site(production=False, wp_version="6.9.4"))["status"] == "CRIT")

# --------------------------------------------------------------------------
# The review queue. NOT "production is null" -- that is all 84 sites.
# --------------------------------------------------------------------------
check("a workbook site with no ruling does not need review",
      S.needs_review(site(in_workbook=True)) is False)
check("a site absent from the workbook with no ruling DOES need review",
      S.needs_review(site(in_workbook=False)) is True)
check("a site already ruled on does not need review",
      S.needs_review(site(in_workbook=False, production=False)) is False)

# --------------------------------------------------------------------------
# summarise(): excluded sites are counted separately, never dropped.
# --------------------------------------------------------------------------
_sum = S.summarise([site(site_id="a"), site(site_id="b", wp_version="6.9.4"),
                    site(site_id="c", wp_version="6.9.4", production=False)])
check("summarise counts production sites", _sum["counts"]["OK"] == 1
      and _sum["counts"]["CRIT"] == 1, json.dumps(_sum["counts"]))
check("summarise counts excluded separately rather than dropping them",
      _sum["excluded"]["CRIT"] == 1 and _sum["excluded_sites"] == ["c"],
      json.dumps(_sum))

# --------------------------------------------------------------------------
# Against the COMMITTED LEDGER, never against reports/. reports/ is gitignored,
# holds whatever the last local scan produced, and does not exist on a CI
# runner or a fresh clone.
# --------------------------------------------------------------------------
hist = os.path.join(ROOT, "history", "observations.jsonl")
inv_path = os.path.join(ROOT, "data", "fleet-inventory.json")
if os.path.exists(hist) and os.path.exists(inv_path):
    RUN = "health-2026-08-19_0002"   # the first full-fleet full-mode scan
    inv = {x["site_id"]: x for x in json.load(open(inv_path))["sites"]}
    rows = [json.loads(l) for l in open(hist)]
    rows = [r for r in rows if r.get("run_id") == RUN]
    merged = []
    for r in rows:
        rec = inv.get(r["site_id"], {})
        d = dict(r)
        d["production"] = rec.get("production")
        d["in_workbook"] = rec.get("in_workbook")
        d["severity"] = S.evaluate(d)
        merged.append(d)
    res = S.summarise(merged)
    c = res["counts"]

    check("ledger: the run is the 52 sites it claims to be", len(rows) == 52, str(len(rows)))
    check("ledger: at least one site scores OK (the old model had zero)",
          c["OK"] > 0, json.dumps(c))
    check("ledger: CRIT is a short list a person can act on, not most of the fleet",
          c["CRIT"] <= 5, json.dumps(c))
    check("ledger: every measurable site lands in a state",
          sum(c.values()) + sum(res["excluded"].values()) == 52, json.dumps(c))
    check("ledger: no site in a scanned run reads UNKNOWN",
          c.get("UNKNOWN", 0) == 0,
          "UNKNOWN is for sites the health scan never reached, not scanned ones")
    crit = sorted(d["site_id"] for d in merged
                  if d["severity"]["status"] == "CRIT" and d["severity"]["production"])
    # Two, and the second one is the argument for having ONE PHP table rather
    # than a hardcoded floor: runtalnorthamerica.com runs PHP 8.1, which
    # stopped receiving security patches on 2025-12-31. The old severity model
    # never looked at PHP at all, and a `< 8.0` floor would have passed it.
    check("ledger: the CRIT list is hoffmanscheese and the PHP 8.1 site",
          crit == ["hoffmanscheese", "runtalnorthamerica.com"], str(crit))
    _byid = {d["site_id"]: d for d in merged}
    check("ledger: hoffmanscheese is CRIT for its 721-day backup gap",
          any(r["code"] == "backup_stale"
              for r in _byid["hoffmanscheese"]["severity"]["reasons"]))
    check("ledger: runtalnorthamerica is CRIT for PHP 8.1 being past EOL",
          any(r["code"] == "php_eol"
              for r in _byid["runtalnorthamerica.com"]["severity"]["reasons"]))
    check("ledger: cm-whitelabel is excluded but still scores CRIT",
          res["excluded_sites"] == ["cm-whitelabel"] and res["excluded"]["CRIT"] == 1,
          json.dumps(res))
    # Six Pantheon sites are absent from the workbook. cm-whitelabel has since
    # been ruled on, so five remain unreviewed -- which is the queue draining
    # as designed, not a count that happens to be five.
    check("ledger: the review queue is the unaudited sites, not all 84",
          res["unreviewed"] == ["clevermethod-forward", "hoffmanscheese",
                                "moorseville-nc", "nc-moorseville",
                                "pfannenbergsales"], str(res["unreviewed"]))
    check("ledger: a site with a production ruling has left the queue",
          "cm-whitelabel" not in res["unreviewed"])
else:
    print("skip  ledger checks (history/ or inventory missing)")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
