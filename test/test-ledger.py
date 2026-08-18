#!/usr/bin/env python3
"""
Self-check for fleet-ledger.py.

A change detector that reports "nothing changed" is worthless unless it is
proven to catch changes. Half these assertions exist to prove the quiet answer
on the real data was real and not a broken comparison.

Run: ./test/test-ledger.py
"""
import datetime
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

spec = importlib.util.spec_from_file_location("ledger", os.path.join(ROOT, "scripts", "fleet-ledger.py"))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

TODAY = datetime.date(2026, 8, 17)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name, ("  <- " + detail) if (detail and not cond) else ""))


def row(site, **kw):
    base = {
        "site": site,
        "framework": "wordpress",
        "plan": "Basic",
        "env": "live",
        "frozen": False,
        "php_version": "8.2",
        "db_backup_age_days": 0,
        "upstream_pending": 0,
        "wp_checked": False,
        "wp_core_update": "n/a",
        "plugin_updates": 0,
        "theme_updates": 0,
        "status": "OK",
        "notes": "API-only run: WP core/plugin/theme not checked",
    }
    base.update(kw)
    return base


def to_obs(rows, run_id="r"):
    out = {}
    for r in rows:
        rec = {"run_id": run_id, "observed_at": "2026-08-17T00:00:00", "site": r["site"]}
        for k in L.OBSERVED:
            rec[k] = L.fact(r, k)
        for k in L.DERIVED:
            rec["derived_" + k] = L.fact(r, k)
        out[r["site"]] = rec
    return out


def classes(changes):
    return sorted(set(c["class"] for c in changes))


# ---------------------------------------------------------------- 1. real data
# Two sources, on purpose:
#   reports/  raw scan output. GITIGNORED, so absent on a fresh clone and on
#             every CI runner. Ingest is only exercised when it is present.
#   history/  the committed ledger. This is the asset that survives a clone,
#             so the diff assertions read from here and always run.
print("\n-- against the two real runs --")
real_dir = os.path.join(ROOT, "reports")
hist_dir = os.path.join(ROOT, "history")
have_reports = os.path.isdir(real_dir) and any(
    f.startswith("fleet-health-") and f.endswith(".json") for f in os.listdir(real_dir))
tmp = tempfile.mkdtemp()
try:
    if have_reports:
        res = L.ingest(real_dir, tmp)
        runs, obs = L.load_ledger(tmp)
        check("ingest picks up both real runs", res["runs_added"] >= 2, str(res))
        check("104 observations from 2 x 52 sites", res["observations_added"] == 104,
              str(res["observations_added"]))
        res2 = L.ingest(real_dir, tmp)
        check("re-ingest is idempotent, adds nothing",
              res2["runs_added"] == 0 and res2["observations_added"] == 0)
    else:
        print("  SKIPPED ingest: reports/ is gitignored and absent here.")
        runs, obs = L.load_ledger(hist_dir)

    if len(runs) < 2:
        print("  SKIPPED diff: fewer than two runs available in either source.")
    else:
        p = L.rows_for(obs, runs[-2]["run_id"])
        c = L.rows_for(obs, runs[-1]["run_id"])
        ch = L.diff_runs(p, c, TODAY)
        check("real diff finds exactly one change", len(ch) == 1, json.dumps(ch))
        check("that change is hoffmanscheese backup age",
              ch and ch[0]["site"] == "hoffmanscheese" and ch[0]["fact"] == "db_backup_age_days")
        check("it is classed DRIFT, not an alert", ch and ch[0]["class"] == "DRIFT")
        check("rendered `notes` is NOT diffed (no double report)",
              all(x["fact"] != "notes" for x in ch))
        check("upstream group counts 38, incl. the 2 CRIT rows the old model hid",
              any(g["cause"].startswith("One pending") and len(g["sites"]) == 38
                  for g in L.standing(c, TODAY)))
finally:
    shutil.rmtree(tmp)

# ------------------------------------------------------- 2. it catches changes
print("\n-- it catches real changes (proving the quiet answer above) --")
base = to_obs([row("alpha"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r1")

# new / gone site
m = to_obs([row("alpha"), row("bravo", upstream_pending=1, status="WARN"), row("delta")], "r2")
ch = L.diff_runs(base, m, TODAY)
inv = [c for c in ch if c["class"] == "INVENTORY"]
check("a new site is INVENTORY", any(c["site"] == "delta" and c["after"] == "present" for c in inv))
check("a vanished site is INVENTORY", any(c["site"] == "charlie" and c["after"] == "absent" for c in inv))
check("INVENTORY sorts first", ch[0]["class"] == "INVENTORY")

# resolved upstream
m = to_obs([row("alpha"), row("bravo", upstream_pending=0, status="OK"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("merging the upstream reads RESOLVED", any(c["fact"] == "upstream_pending" and c["class"] == "RESOLVED" for c in ch))

# onset upstream
m = to_obs([row("alpha", upstream_pending=2, status="WARN"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("a new pending commit reads ONSET", any(c["site"] == "alpha" and c["class"] == "ONSET" for c in ch))

# backup threshold crossing both ways
m = to_obs([row("alpha", db_backup_age_days=9, status="CRIT"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("backup crossing the 2-day line is TRANSITION", any(c["site"] == "alpha" and c["fact"] == "db_backup_age_days" and c["class"] == "TRANSITION" for c in ch))
m = to_obs([row("alpha"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=0, status="WARN")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("a backup finally taken is TRANSITION, not DRIFT", any(c["site"] == "charlie" and c["fact"] == "db_backup_age_days" and c["class"] == "TRANSITION" for c in ch))

# drift stays drift
m = to_obs([row("alpha"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=801, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("800 -> 801 on an open finding is DRIFT", any(c["site"] == "charlie" and c["class"] == "DRIFT" for c in ch))
check("DRIFT sorts last", ch[-1]["class"] == "DRIFT")

# php change
m = to_obs([row("alpha", php_version="8.4"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("a PHP version change is always reported", any(c["fact"] == "php_version" for c in ch))

# coverage change. base is api-only, so its plugin_updates is stored as unknown
# regardless of the fabricated 0 in the source row; going unknown -> 3 must be
# reported, and must NOT read as "3 new plugin updates appeared".
m = to_obs([row("alpha", wp_checked=True, plugin_updates=3, status="WARN"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("gaining deep-scan coverage is reported", any(c["fact"] == "wp_checked" for c in ch))
check("unknown -> a number is TRANSITION, not ONSET", any(c["fact"] == "plugin_updates" and c["class"] == "TRANSITION" for c in ch), json.dumps([c for c in ch if c["fact"] == "plugin_updates"]))

# the fabricated-zero fix itself
print("\n-- the scanner's fabricated zeros are refused at ingest --")
apionly = row("zulu", wp_checked=False, plugin_updates=0, theme_updates=0, wp_core_update="n/a")
check("api-only plugin_updates stored as unknown, not 0", L.fact(apionly, "plugin_updates") == "unknown")
check("api-only theme_updates stored as unknown, not 0", L.fact(apionly, "theme_updates") == "unknown")
check("api-only wp_core_update stored as unknown, not 'n/a'", L.fact(apionly, "wp_core_update") == "unknown")
deep = row("zulu", wp_checked=True, plugin_updates=0, theme_updates=0, wp_core_update="none")
check("a deep-scanned genuine 0 IS preserved", L.fact(deep, "plugin_updates") == 0)
check("upstream_pending is NOT coerced (it is an API fact, always observed)", L.fact(apionly, "upstream_pending") == 0)
check("db_backup_age_days is NOT coerced (also an API fact)", L.fact(row("z", db_backup_age_days=5), "db_backup_age_days") == 5)

# rule change: derived status moves with no observed change
m = to_obs([row("alpha", status="WARN"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("status moving with no observed change is RULE_CHANGE", any(c["site"] == "alpha" and c["class"] == "RULE_CHANGE" for c in ch))

# ------------------------------------------------------------- 3. unknown rules
print("\n-- unknown is never folded into yes or no --")
check("absent field becomes the token 'unknown'", L.fact({"site": "x"}, "php_version") == "unknown")
check("explicit null becomes 'unknown' too", L.fact({"site": "x", "plan": None}, "plan") == "unknown")
check("unknown backup age is NOT treated as bad", L._backup_bad("unknown") is False)
check("unknown backup age is NOT treated as good either (no CRIT, no OK claim)", L._backup_bad("unknown") is False)
skipped = to_obs([{"site": "sk", "framework": "wordpress", "plan": "Sandbox", "env": "live", "frozen": False, "status": "SKIP", "notes": "never initialized"}], "r1")
check("a SKIP row carries unknown facts, not zeros", skipped["sk"]["db_backup_age_days"] == "unknown")
check("a SKIP row raises no standing RISK group", not any(g["axis"] == "RISK" for g in L.standing(skipped, TODAY)))

# ------------------------------------------------------------ 4. php calendar
print("\n-- php support calendar --")
check("8.1 is EOL on 2026-08-17", L.php_support("8.1", TODAY)[0] == "eol")
check("8.2 is expiring (<=180d)", L.php_support("8.2", TODAY)[0] == "expiring")
check("8.2 has 136 days left", L.php_support("8.2", TODAY)[1] == 136, str(L.php_support("8.2", TODAY)))
check("8.3 is supported", L.php_support("8.3", TODAY)[0] == "supported")
check("an unseen version is unknown, not assumed bad", L.php_support("9.9", TODAY)[0] == "unknown")
check("unknown php raises no EOL claim", L.php_support("unknown", TODAY)[0] == "unknown")
# and the calendar must not silently rot
check("8.2 expiry is the real php.net date", L.PHP_SECURITY_EOL["8.2"] == "2026-12-31")

# ----------------------------------------------------------- 5. portability
print("\n-- portability --")
check("no f-strings or 3.10+ syntax needed (py3.6 compatible source)", sys.version_info >= (3, 6))
src = open(os.path.join(ROOT, "scripts", "fleet-ledger.py")).read()
check("stdlib only, no third-party imports", "import requests" not in src and "import pandas" not in src)
check("no shell out to date/timeout", "subprocess" not in src)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
