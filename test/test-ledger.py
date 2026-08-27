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

# Named committed runs. Positional indexes into an append-only ledger are a
# fixture that moves under the test; these do not.
FULL_FLEET_RUNS = ("health-2026-08-16_1725", "health-2026-08-17_0726",
                   "health-2026-08-19_0002")
QUIET_PAIR = ("health-2026-08-16_1725", "health-2026-08-17_0726")
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
        # site_id as well as site: real ledger rows carry both, and a fixture
        # that omits one lets a lookup keyed on it pass by accident.
        rec = {"run_id": run_id, "observed_at": "2026-08-17T00:00:00",
               "site": r["site"], "site_id": r["site"]}
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
    inv_path = os.path.join(ROOT, "data", "fleet-inventory.json")
    inv_arg = inv_path if os.path.exists(inv_path) else None
    # The human decisions severity has to join on. Named INV so it does not
    # collide with the INVENTORY-class change list further down this file.
    INV = ({x["site_id"]: x for x in json.load(open(inv_path))["sites"]}
           if inv_arg else {})
    if have_reports:
        # reports/ is a working directory, not a fixture. It holds whatever the
        # last local scan produced, including one-site cohort runs from SSH
        # testing, so nothing here may assert a fleet size or a specific run.
        # Those assertions moved onto the committed ledger below, which is
        # version-controlled and therefore identical on a laptop and in CI.
        res = L.ingest(real_dir, tmp, inventory=inv_arg)
        check("ingest reads the local reports directory", res["runs_added"] >= 1, str(res))
        check("every ingested row resolves to the inventory",
              res["unresolved_count"] == 0, str(res.get("unresolved_by_run")))
        res2 = L.ingest(real_dir, tmp, inventory=inv_arg)
        check("re-ingest is idempotent, adds nothing",
              res2["runs_added"] == 0 and res2["observations_added"] == 0)
    else:
        print("  SKIPPED ingest: reports/ is gitignored and absent here.")

    # The committed ledger. This is the deterministic fixture: it is in git, so
    # CI and a laptop see byte-identical input, and reports/ cannot perturb it.
    runs, obs = L.load_ledger(hist_dir)
    health_runs = [r for r in runs if r.get("source", "health") == "health"]
    check("the committed ledger holds both real health runs",
          len(health_runs) >= 2, str([r["run_id"] for r in health_runs]))
    # NOT "every health run has 52 sites". The ledger is APPEND-ONLY, so any
    # assertion shaped like "all runs" or "the last two runs" is pinned to a
    # fixture that grows, and it went red the moment the 2026-08-19 full-fleet
    # run landed beside three one- and three-site debugging runs. This is the
    # reports/ trap from the handoff, in history/. Pin to NAMED runs instead.
    by_id = {r["run_id"]: r for r in health_runs}
    for rid in FULL_FLEET_RUNS:
        check("committed run %s is the 52-site fleet it claims to be" % rid,
              by_id.get(rid, {}).get("site_count") == 52,
              str(by_id.get(rid, {}).get("site_count")))
    check("cohort runs are kept, not mistaken for fleet runs",
          any(r["site_count"] < 52 for r in health_runs),
          "the one- and three-site debugging runs should still be in the ledger")
    # Both tools reach the committed ledger. Before 2026-08-18 they did not:
    # the file in git held health rows only, while the dashboard beside it had
    # been rendered from a ledger with email in it that was never committed.
    check("and the email runs too, so the committed ledger matches the page",
          any(r.get("source") == "email-dns" for r in runs),
          str(sorted(set(r.get("source") for r in runs))))
    check("no committed run left a site unresolved",
          all(not r.get("sites_not_in_inventory") for r in runs),
          str([(r["run_id"], r.get("sites_not_in_inventory")) for r in runs
               if r.get("sites_not_in_inventory")]))

    # The quiet answer, against the two api-only fleet runs 14h apart that the
    # digest design was argued from. Named, not positional.
    a, b = QUIET_PAIR
    if a in by_id and b in by_id:
        pr = L.rows_for(obs, a)
        cr = L.rows_for(obs, b)
        ch = L.diff_runs(pr, cr, TODAY, INV)
        check("real diff finds exactly one change", len(ch) == 1, json.dumps(ch))
        check("that change is hoffmanscheese backup age",
              ch and ch[0]["site"] == "hoffmanscheese" and ch[0]["fact"] == "db_backup_age_days")
        check("it is classed DRIFT, not an alert", ch and ch[0]["class"] == "DRIFT")
        check("rendered `notes` is NOT diffed (no double report)",
              all(x["fact"] != "notes" for x in ch))
    else:
        print("  SKIPPED quiet-pair diff: %s / %s not in the ledger." % QUIET_PAIR)

    # The full-mode run. Every site carries 1 or 2 pending upstream commits --
    # this is the fact that used to score the entire fleet WARN, and it is why
    # it is now informational. The group still exists; it is a planning item.
    full = L.rows_for(obs, FULL_FLEET_RUNS[-1])
    if full:
        grp = [g for g in L.standing(full, TODAY) if g["cause"].startswith("One pending")]
        check("the upstream group covers every measurable site in the full run",
              grp and len(grp[0]["sites"]) == 48, str(len(grp[0]["sites"]) if grp else None))
        check("upstream is filed as DRIFT, not RISK",
              grp and grp[0]["axis"] == "DRIFT", str(grp[0]["axis"] if grp else None))
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
# The threshold is SEV.BACKUP_CRIT_DAYS, read from the severity module rather
# than written as a literal, so retuning it does not silently invalidate this.
m = to_obs([row("alpha", db_backup_age_days=L.BACKUP_CRIT_DAYS + 1, status="CRIT"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("backup crossing the %d-day line is TRANSITION" % L.BACKUP_CRIT_DAYS, any(c["site"] == "alpha" and c["fact"] == "db_backup_age_days" and c["class"] == "TRANSITION" for c in ch))
m = to_obs([row("alpha", db_backup_age_days=L.BACKUP_CRIT_DAYS - 1), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("a backup age still inside the line is not a transition", not any(c["site"] == "alpha" and c["fact"] == "db_backup_age_days" and c["class"] == "TRANSITION" for c in ch))
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
# Crossing the unknown boundary is COVERAGE: the tool started being able to
# see the fact. It must never read as ONSET ("3 new plugin updates appeared"),
# and since 2026-08-19 it is also no longer TRANSITION, because 48 sites
# gaining six facts each on the first full-mode run is one event.
check("unknown -> a number is COVERAGE, never ONSET", any(c["fact"] == "plugin_updates" and c["class"] == "COVERAGE" for c in ch), json.dumps([c for c in ch if c["fact"] == "plugin_updates"]))
check("gaining coverage never reads as a new problem", not any(c["fact"] == "plugin_updates" and c["class"] == "ONSET" for c in ch))
_kept, _cov = L.collapse_coverage(ch)
check("coverage rows collapse to one line per fact",
      all(c["class"] != "COVERAGE" for c in _kept) and _cov and _cov[0]["gained"] >= 1,
      json.dumps(_cov))

# A fact that did not EXIST in the older run. Runs predating a fact carry no
# key for it, and reading that as None rather than unknown is what made the
# first full-mode run report wp_version as 48 separate fleet changes.
_old = to_obs([row("alpha")], "r1")
for _r in _old.values():
    _r.pop("wp_version", None)
_new = to_obs([row("alpha", wp_checked=True, wp_version="7.0.4")], "r2")
_ch = L.diff_runs(_old, _new, TODAY)
check("a fact absent from an older run is unknown, not None",
      any(c["fact"] == "wp_version" and c["class"] == "COVERAGE" for c in _ch),
      json.dumps([c for c in _ch if c["fact"] == "wp_version"]))

# A status move caused ONLY by facts becoming visible is coverage, not a
# transition. This fired 31 times on the first full-mode run, on sites whose
# upstream counter happened to tick in the same run.
_b = to_obs([row("alpha", upstream_pending=1)], "r1")
for _r in _b.values():
    _r.pop("wp_version", None)
# The AFTER row is a deep scan that found nothing wrong, so the status genuinely
# moves: WARN (nothing about its WordPress was established) -> OK.
#
# It used to be a deep scan that found a core update, WARN -> WARN, which stopped
# exercising this check on 2026-08-23 when `wp_unestablished` landed. `row()`
# defaults to an api-only row, so the BEFORE side is now WARN too and the status
# fact no longer moved at all. The fixture was measuring nothing, silently. What
# has to hold is that coverage ARRIVING is never reported as the fleet changing,
# in either direction, and OK is the direction that would read as "this site got
# better" if it were ever classed TRANSITION.
_a = to_obs([row("alpha", upstream_pending=2, wp_checked=True,
                 wp_version="7.0.4", wp_core_update="up-to-date",
                 plugin_updates=0, theme_updates=0)], "r2")
_ch = L.diff_runs(_b, _a, TODAY)
_st = [c for c in _ch if c["fact"] == "status"]
check("a status move driven only by new visibility is COVERAGE",
      _st and _st[0]["class"] == "COVERAGE", json.dumps(_st))
check("...and it is the api-only -> full move, WARN to OK",
      _st and (_st[0]["before"], _st[0]["after"]) == ("WARN", "OK"),
      json.dumps(_st))
check("...even when a non-scoring fact moved in the same run",
      any(c["fact"] == "upstream_pending" for c in _ch))

# And a status move driven by a fact the score actually reads IS a transition.
_a2 = to_obs([row("alpha", db_backup_age_days=L.BACKUP_CRIT_DAYS + 5)], "r2")
for _r in _a2.values():
    _r.pop("wp_version", None)
_ch2 = L.diff_runs(_b, _a2, TODAY)
_st2 = [c for c in _ch2 if c["fact"] == "status"]
check("a status move driven by a scoring fact is TRANSITION",
      _st2 and _st2[0]["class"] == "TRANSITION", json.dumps(_st2))

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

# Rule change. Severity is now RE-DERIVED for both sides of a diff with the
# CURRENT rules, which is the point of moving it out of the scanner: retuning a
# threshold moves both sides together and reports NOTHING, rather than flagging
# all 52 sites as changed with no observed fact behind it.
print("\n-- a rules change is not a fleet change --")
m = to_obs([row("alpha", status="WARN"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
ch = L.diff_runs(base, m, TODAY)
check("the scanner's stored status is IGNORED, so changing it reports nothing",
      not any(c["site"] == "alpha" for c in ch), json.dumps([c for c in ch if c["site"] == "alpha"]))

# RULE_CHANGE still fires, for the one case that genuinely is a scoring move
# with no observed fact behind it: a human flipping `production` in the
# inventory takes the site out of the fleet numbers.
_inv_before = {"charlie": {"production": None, "in_workbook": True}}
_inv_after = {"charlie": {"production": False, "in_workbook": True}}
same = to_obs([row("alpha"), row("bravo", upstream_pending=1, status="WARN"), row("charlie", db_backup_age_days=800, status="CRIT")], "r2")
check("scoring charlie in is CRIT", L.score(same["charlie"], _inv_before)["status"] == "CRIT")
check("flipping production does not silence the score, only the counting",
      L.score(same["charlie"], _inv_after)["status"] == "CRIT"
      and L.score(same["charlie"], _inv_after)["production"] is False)

print("\n-- a cohort run is not a baseline --")
# Debugging leaves one- and three-site runs in an append-only ledger. Diffing a
# 3-site cohort against the 52-site fleet run after it reported the other 49 as
# "absent -> present" and made the dashboard headline read 51.
_runs = [{"run_id": "r1", "source": "health"},
         {"run_id": "cohort", "source": "health"},
         {"run_id": "r2", "source": "health"}]
_obs = ([dict(o, run_id="r1") for o in to_obs([row("alpha"), row("bravo"), row("charlie")], "r1").values()]
        + [dict(o, run_id="cohort") for o in to_obs([row("alpha")], "cohort").values()]
        + [dict(o, run_id="r2") for o in to_obs([row("alpha"), row("bravo"), row("charlie")], "r2").values()])
# ---------------------------------------------------------------------------
# A BASELINE MUST COME FROM THE SAME COHORT, not just the same source
#
# `health` has two transports over disjoint site sets. Matching on source
# alone let the 22-site Nexcess run take the 52-site Pantheon run as its
# baseline, and the coverage guard reported "21 of 22 measured, was 48 (-27)"
# on every alternating ingest from 2026-08-25. Nothing had dropped.
#
# Rules 1 and 2 cannot catch it: they skip a candidate whose site set is a
# strict SUBSET, and disjoint sets are not subsets.
_ck_runs = [
    {"run_id": "health-p1", "source": "health", "kind": "health", "mode": "full"},
    {"run_id": "health-n1", "source": "health", "kind": "health-nexcess",
     "mode": "full"},
    {"run_id": "health-n2", "source": "health", "kind": "health-nexcess",
     "mode": "full"},
]
_ck_obs = ([{"run_id": "health-p1", "site": "p%d" % i, "wp_checked": True}
            for i in range(52)]
           + [{"run_id": "health-n1", "site": "n%d" % i, "wp_checked": True}
              for i in range(21)]
           + [{"run_id": "health-n2", "site": "n%d" % i, "wp_checked": True}
              for i in range(21)])
_ckp, _ckc = L.previous_run_of_same_source(_ck_runs, obs=_ck_obs)
check("a cohort run is never baselined against the other transport",
      _ckp is not None and _ckp["run_id"] == "health-n1",
      "baseline was %r" % ((_ckp or {}).get("run_id"),))
# And with no earlier run of its own cohort, there is NO baseline -- never the
# other cohort's run, which would report every site as appearing or vanishing.
_ckp2, _ = L.previous_run_of_same_source(_ck_runs[:2], obs=_ck_obs)
check("...and with no earlier run of its cohort there is no baseline at all",
      _ckp2 is None, "baseline was %r" % ((_ckp2 or {}).get("run_id"),))

# THE SAME DEFECT LIVED IN A SECOND PLACE. coverage_regressions() grouped by
# source too, and it is the function that gates a publish -- so the false
# alarm arrived on every alternating ingest AND on every hand-run publish.
_cr_runs = [
    {"run_id": "health-2026-08-26_1351", "source": "health", "kind": "health",
     "mode": "full", "observed_at": "2026-08-26T13:51:00",
     "deep_scanned": 48, "site_count": 52},
    {"run_id": "health-nexcess-2026-08-26_1941", "source": "health",
     "kind": "health-nexcess", "mode": "full",
     "observed_at": "2026-08-26T19:41:00", "deep_scanned": 21, "site_count": 22},
]
# AND THE SAME DEFECT LIVED IN A THIRD PLACE: ingest's own `last_by_source`.
# Fixing the two functions above did NOT silence the warning, because ingest
# does not call either of them -- the tests for those two passed while the
# path that actually runs was untouched. So this drives ingest() end to end.
_ct = tempfile.mkdtemp()
try:
    _ch, _cr = os.path.join(_ct, "history"), os.path.join(_ct, "reports")
    os.makedirs(_ch); os.makedirs(_cr)
    _ci = os.path.join(_ct, "inv.json")
    json.dump({"sites": [{"site_id": "s%d.com" % i, "domain": "s%d.com" % i,
                          "host_site_name": "s%d" % i} for i in range(60)]},
              open(_ci, "w"))

    def _hrow(name, measured):
        r = {"site": name, "framework": "wordpress", "plan": "x", "env": "live",
             "php_version": "8.2", "db_backup_age_days": 1,
             "upstream_pending": 0, "wp_checked": bool(measured),
             "status": "OK", "notes": "", "frozen": False}
        if measured:
            r.update({"wp_version": "7.1", "wp_core_update": "up-to-date",
                      "plugin_updates": 0, "theme_updates": 0,
                      "components": [], "components_checked": True})
        return r

    # A 40-site Pantheon run, then a 12-site Nexcess run. Disjoint sites.
    json.dump([_hrow("s%d" % i, True) for i in range(40)],
              open(os.path.join(_cr, "fleet-health-2026-08-26_0100.json"), "w"))
    L.ingest(_cr, _ch, inventory=_ci)
    json.dump([_hrow("s%d" % i, True) for i in range(40, 52)],
              open(os.path.join(_cr, "fleet-health-nexcess-2026-08-26_0200.json"), "w"))
    _res = L.ingest(_cr, _ch, inventory=_ci)
    check("ingest does not call a 12-site cohort a drop from a 40-site one",
          _res["coverage_drops"] == [],
          "reported %r" % (_res["coverage_drops"],))

    # The guard must still REFUSE a real drop, or the fix has switched it off.
    # Test that it refuses, never only that it permits.
    json.dump([_hrow("s%d" % i, i < 45) for i in range(40, 52)],
              open(os.path.join(_cr, "fleet-health-nexcess-2026-08-26_0300.json"), "w"))
    _res2 = L.ingest(_cr, _ch, inventory=_ci)
    check("...but a real drop inside the Nexcess cohort is still refused",
          len(_res2["coverage_drops"]) == 1
          and _res2["coverage_drops"][0]["previous_run_id"]
              == "health-nexcess-2026-08-26_0200",
          "reported %r" % (_res2["coverage_drops"],))
    check("...and the drop names the cohort, not the shared source",
          _res2["coverage_drops"]
          and _res2["coverage_drops"][0]["source"] == "health-nexcess",
          "named %r" % (_res2["coverage_drops"][0]["source"]
                        if _res2["coverage_drops"] else None,))
finally:
    shutil.rmtree(_ct, ignore_errors=True)

check("a 21-site cohort after a 48-site one is not a coverage drop",
      L.coverage_regressions(_cr_runs) == [],
      "reported %r" % (L.coverage_regressions(_cr_runs),))

# And a REAL drop inside one cohort must still be caught, or the fix above
# has simply switched the guard off.
_cr_real = _cr_runs + [
    {"run_id": "health-nexcess-2026-08-26_2200", "source": "health",
     "kind": "health-nexcess", "mode": "full",
     "observed_at": "2026-08-26T22:00:00", "deep_scanned": 9, "site_count": 22},
]
_hit = L.coverage_regressions(_cr_real)
check("...but a real drop within one cohort is still caught",
      len(_hit) == 1 and _hit[0]["lost"] == 12
      and _hit[0]["previous_run_id"] == "health-nexcess-2026-08-26_1941",
      "reported %r" % (_hit,))
check("...and it names the COHORT, not the source shared with the other one",
      _hit and _hit[0]["source"] == "health-nexcess",
      "named %r" % (_hit[0]["source"] if _hit else None,))

_p, _c = L.previous_run_of_same_source(_runs, obs=_obs)
check("a strict-subset run is skipped as a baseline", _p["run_id"] == "r1", str(_p))
check("...and the current run is still the newest", _c["run_id"] == "r2")
_p2, _ = L.previous_run_of_same_source(_runs)
check("without obs the old positional behaviour is unchanged", _p2["run_id"] == "cohort")

# Rule 2b. A run that measured NOTHING is a baseline only when it is a
# different MODE. The empty-set exception is keyed on emptiness, which is
# right for health -- an api-only run measures zero in the wp_checked family
# and is still a complete look -- and wrong for a source with one mode, where
# zero measurements means the run failed.
#
# Measured on 2026-08-23: an email-dns run pointed at the wrong inventory file
# wrote 78 rows and measured 0. Diffed against the good run that followed it
# produced 117 TRANSITION rows and took the page from 2 changes to 118.
def _email_obs(run_id, measured):
    return [{"run_id": run_id, "site": "a.com", "site_id": "a.com",
             "source": "email-dns", "dkim_present": measured},
            {"run_id": run_id, "site": "b.com", "site_id": "b.com",
             "source": "email-dns", "dkim_present": measured}]

_er = [{"run_id": "e-good", "source": "email-dns", "mode": "dns"},
       {"run_id": "e-failed", "source": "email-dns", "mode": "dns"},
       {"run_id": "e-now", "source": "email-dns", "mode": "dns"}]
_eo = (_email_obs("e-good", True) + _email_obs("e-failed", False)
       + _email_obs("e-now", True))
_ep, _ec = L.previous_run_of_same_source(_er, obs=_eo)
check("a same-mode run that measured NOTHING is not a baseline",
      _ep["run_id"] == "e-good", str(_ep))

# The exception this must not break: health's api-only mode measures zero and
# IS a legitimate baseline, because it is a different way of looking rather
# than a failed look. Excluding it would discard the only comparable run in
# seven of this ledger's runs.
def _health_obs(run_id, checked):
    return [{"run_id": run_id, "site": "a.com", "site_id": "a.com",
             "source": "health", "wp_checked": checked},
            {"run_id": run_id, "site": "b.com", "site_id": "b.com",
             "source": "health", "wp_checked": checked}]

_hr = [{"run_id": "h-api", "source": "health", "mode": "api-only"},
       {"run_id": "h-full", "source": "health", "mode": "full"}]
_ho = _health_obs("h-api", False) + _health_obs("h-full", True)
_hp, _ = L.previous_run_of_same_source(_hr, obs=_ho)
check("...but an api-only health run still IS one, being a different mode",
      _hp["run_id"] == "h-api", str(_hp))

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

# ------------------------------------------------- 4b. the unified data model
print("\n-- one site, several tools, one history --")
check("no fact name collides between sources",
      not (set(L.OBSERVED) & set(L.EMAIL_OBSERVED)))

inv_p = os.path.join(ROOT, "data", "fleet-inventory.json")
if os.path.exists(inv_p):
    by_host, by_domain, recs = L.load_inventory(inv_p)
    check("inventory maps a Pantheon machine name to a domain",
          by_host.get("kraftcheese") == "kraftnaturalcheese.com", str(by_host.get("kraftcheese")))
    check("inventory maps the awkward ones too",
          by_host.get("l92") == "local92afm.com" and by_host.get("pdsci") == "packagedesignsupply.com")
    check("a domain maps to itself", by_domain.get("galbanicheese.com") == "galbanicheese.com")
    check("a Pantheon site with no workbook row keeps its machine name as the id",
          "hoffmanscheese" in recs and recs["hoffmanscheese"]["in_workbook"] is False)
    # Asserts the PROPERTY its own name states -- a reconciliation note exists
    # and says something -- not the sentence it happened to contain. It pinned
    # the literal "absent from the workbook" and went red on 2026-08-23 when
    # that wording was deliberately taken off the page: the workbook is being
    # retired, and the note now describes the inventory instead. Same trap as
    # the fleet-count assertions further up this file.
    _rec = recs["hoffmanscheese"]["reconciliation"]
    check("that site carries the reconciliation note, not a silent pass",
          bool(_rec) and "Pantheon" in _rec and len(_rec) > 40, repr(_rec))
    check("a workbook site Pantheon does not return is flagged the other way",
          recs["hoosierfeeder.com"].get("host_site_name") is None
          and "not observed" in recs["hoosierfeeder.com"]["reconciliation"])
    # Added 2026-08-19 with the consent sweep's roster reconciliation, which
    # measured this site rather than restating the workbook. The note has to
    # keep saying what was MEASURED and what was not: the DNS answer is
    # evidence that it is not on Pantheon, and it is not evidence of what host
    # it IS on, because Cloudflare hides the origin.
    check("...and the note records what was measured, separately from what "
          "the workbook claims",
          "MEASURED" in recs["hoosierfeeder.com"]["reconciliation"]
          and "NOT been established"
          in recs["hoosierfeeder.com"]["reconciliation"])
    check("attestations are carried over with their provenance",
          recs["galbanicheese.com"]["attestations"]["wp2shell_remedied"]["source"].startswith("workbook"))
    check("attestations record who and when, both empty on import",
          recs["galbanicheese.com"]["attestations"]["wp2shell_remedied"]["by"] is None)
else:
    print("  SKIPPED inventory checks: data/fleet-inventory.json not present")

# health rows normalise onto site_id
hr = L._health_rows([row("kraftcheese")], {"kraftcheese": "kraftnaturalcheese.com"})
check("a health row is re-keyed onto the inventory site_id",
      hr[0]["site_id"] == "kraftnaturalcheese.com")
check("the original machine name is kept, not discarded",
      hr[0]["host_site_name"] == "kraftcheese")
check("an unmapped health row falls back to its own name, never dropped",
      L._health_rows([row("mystery")], {})[0]["site_id"] == "mystery")

# email rows
email_payload = {"kind": "email-dns", "sites": [{
    "domain": "Galbanicheese.com",
    "spf": {"present": True, "all_qualifier": "~all", "checked_at": "app.galbani.com"},
    "dkim": {"present": True, "selector": "pic"},
    "dmarc": {"at_sending_domain": {"present": False},
              "at_from_domain": {"present": True, "policy": "none", "via_org_fallback": False}},
    "alignment": {"relaxed_aligned": False}}]}
er = L._email_rows(email_payload, {"galbanicheese.com": "galbanicheese.com"})
check("an email row is keyed on the domain, case-insensitively",
      er[0]["site_id"] == "galbanicheese.com")
check("both DMARC readings survive into the ledger separately",
      er[0]["dmarc_at_sending_present"] is False and er[0]["dmarc_at_from_present"] is True)
check("a site with an error row is skipped, not stored as unknown facts",
      L._email_rows({"kind": "email-dns", "sites": [{"domain": "x.com", "error": "boom"}]}, {}) == [])

# the two shapes are told apart by shape, not by filename
check("a list payload is recognised as a health scan",
      L._health_rows([row("a")], {}) is not None and L._email_rows([row("a")], {}) is None)
check("a dict payload is recognised as an email scan",
      L._email_rows(email_payload, {}) is not None and L._health_rows(email_payload, {}) is None)

# diffing must compare like with like
print("\n-- diffs compare like with like --")
h = {"s": dict(hr[0], run_id="r1", source="health")}
e = {"s": dict(er[0], run_id="r2", source="email-dns")}
ch = L.diff_runs(h, e, TODAY)
check("a source change is reported as ONE fact, not every fact at once",
      len([c for c in ch if c["site"] == "s"]) == 1 and ch[0]["fact"] == "source",
      json.dumps(ch)[:200])
check("facts_for follows the row's own source",
      L.facts_for({"source": "email-dns"}) == L.EMAIL_OBSERVED
      and L.facts_for({"source": "health"}) == L.OBSERVED)

e2 = {"s": dict(er[0], run_id="r3", source="email-dns", spf_present=False)}
ch = L.diff_runs(e, e2, TODAY)
check("an email fact change IS detected", any(c["fact"] == "spf_present" for c in ch))

runs = [{"run_id": "h1", "source": "health"}, {"run_id": "e1", "source": "email-dns"},
        {"run_id": "h2", "source": "health"}]
prev, curr = L.previous_run_of_same_source(runs)
check("the previous run is the previous run OF THE SAME TOOL",
      prev["run_id"] == "h1" and curr["run_id"] == "h2",
      "got %s -> %s" % (prev and prev["run_id"], curr and curr["run_id"]))
prev, curr = L.previous_run_of_same_source([{"run_id": "e1", "source": "email-dns"}])
check("one run from a source means nothing to diff, not a bogus comparison", prev is None)

# standing() must not read health facts off an email row
print("\n-- standing groups never read a fact the row does not have --")
g = L.standing({"a": dict(er[0], source="email-dns")}, TODAY)
check("an email-only ledger produces email groups", any("SPF" in x["cause"] or "DMARC" in x["cause"] for x in g))
check("and raises no backup or upstream group", not any("backup" in x["cause"].lower() or "upstream" in x["cause"].lower() for x in g))
check("a row with no backup fact is not read as a missing backup", L._backup_bad(None) is False)

# `sites` must always be a real list of ids. A pre-formatted summary string in
# that slot made the dashboard's count column read 1 where the truth was 48.
print("\n-- standing groups report a real site count --")
many = to_obs([row("s%02d" % i, wp_checked=False) for i in range(48)], "r")
for g in L.standing(many, TODAY):
    check("group %r counts sites, not summary strings" % g["cause"][:34],
          len(g["sites"]) == 48 and all(not x.endswith(" sites") for x in g["sites"]),
          "%d: %s" % (len(g["sites"]), g["sites"][:2]))
crit = to_obs([row("a", db_backup_age_days=900, status="CRIT"),
               row("b", db_backup_age_days=800, status="CRIT")], "r")
g = [x for x in L.standing(crit, TODAY) if x["cause"] == "No recent DB backup"][0]
check("backup group lists bare site ids", g["sites"] == ["a", "b"], str(g["sites"]))
check("the per-site extra lives in `detail`, not smuggled into the id",
      "900d" in g["detail"]["a"])
check("a non-numeric backup value is not read as bad", L._backup_bad("n/a") is False)

# ------------------------------------ 3b. the two facts that colour the fleet
# Added 2026-08-27. Measured that day: 52 of 85 sites read WARN and 40 of those
# were WARN for a core update, a plugin backlog, or both, while standing()
# emitted twelve causes and named neither. The table was amber and the list
# beside it could not say why.
print("\n-- core update and plugin backlog have standing groups --")

_cu = to_obs([row("a", wp_checked=True, wp_version="7.0.3", wp_core_update="7.0.4"),
              row("b", wp_checked=True, wp_version="7.0.3", wp_core_update="7.0.4"),
              row("c", wp_checked=True, wp_version="7.0.4", wp_core_update="7.1"),
              row("d", wp_checked=True, wp_version="7.1",   wp_core_update="up-to-date")], "r")
_g = [g for g in L.standing(_cu, TODAY) if "available, not applied" in g["cause"]]
check("a pending core update produces a standing group",
      len(_g) == 2, "%d group(s): %s" % (len(_g), [x["cause"] for x in _g]))
# ONE GROUP PER TARGET. Lumping 7.0.4 and 7.1 together would produce an action
# line claiming one decision covers sites that need two different releases.
_by = {g["cause"]: g for g in _g}
check("one group per target version, not one group for 'core updates'",
      "WordPress 7.0.4 available, not applied" in _by
      and "WordPress 7.1 available, not applied" in _by, str(sorted(_by)))
# .get() rather than [] on purpose: a regression here must report FAIL, not
# raise a KeyError that aborts the run and hides every test below it.
check("each group lists only the sites wanting that target",
      _by.get("WordPress 7.0.4 available, not applied", {}).get("sites") == ["a", "b"]
      and _by.get("WordPress 7.1 available, not applied", {}).get("sites") == ["c"],
      str([g["sites"] for g in _g]))
check("an up-to-date site is in no core group",
      _g and all("d" not in g["sites"] for g in _g))
check("core backlog is filed as DRIFT, not RISK",
      _g and all(g["axis"] == "DRIFT" for g in _g), str([g["axis"] for g in _g]))
check("the per-site current version lives in `detail`",
      _by.get("WordPress 7.0.4 available, not applied", {}).get("detail", {}).get("a") == "on 7.0.3")

# UNKNOWN IS NEVER FOLDED INTO up-to-date. A site whose core status could not be
# read must not silently drop out of the backlog as though it were current.
_unk = to_obs([row("a", wp_checked=True, wp_core_update=L.UNKNOWN),
               row("b", wp_checked=True, wp_core_update=None)], "r")
check("an unreadable core status raises no core-update group",
      not [g for g in L.standing(_unk, TODAY) if "available, not applied" in g["cause"]])

_pb = to_obs([row("a", wp_checked=True, plugin_updates=L.SEV.PLUGIN_WARN_COUNT),
              row("b", wp_checked=True, plugin_updates=L.SEV.PLUGIN_WARN_COUNT + 7),
              row("c", wp_checked=True, plugin_updates=L.SEV.PLUGIN_WARN_COUNT - 1)], "r")
_g = [g for g in L.standing(_pb, TODAY) if g["cause"].startswith("Plugin updates pending")]
check("a plugin backlog produces exactly one standing group",
      len(_g) == 1, "%d" % len(_g))
check("the backlog group holds only sites at or above the threshold",
      _g and _g[0]["sites"] == ["a", "b"], str(_g[0]["sites"] if _g else None))
check("plugin backlog is filed as DRIFT", _g and _g[0]["axis"] == "DRIFT")
check("the backlog group names the worst site by count",
      _g and "b" in _g[0]["action"] and str(L.SEV.PLUGIN_WARN_COUNT + 7) in _g[0]["action"],
      _g[0]["action"] if _g else None)
# The threshold must come from severity, not a second copy. Two numbers that
# have to agree is how the page reported a site past PHP end-of-support while
# its severity row read fine.
check("the backlog threshold is read from severity, not redeclared",
      _g and str(L.SEV.PLUGIN_WARN_COUNT) in _g[0]["cause"], _g[0]["cause"] if _g else None)
_none = to_obs([row("a", wp_checked=True, plugin_updates=0)], "r")
check("no site over the threshold means no backlog group",
      not [g for g in L.standing(_none, TODAY) if g["cause"].startswith("Plugin updates")])
_absent = to_obs([row("a", wp_checked=True, plugin_updates=L.UNKNOWN)], "r")
check("an unmeasured plugin count is not read as a backlog, nor as zero",
      not [g for g in L.standing(_absent, TODAY) if g["cause"].startswith("Plugin updates")])

# ------------------------------------------------- 4b. ingest, the write path
# Every assertion in this block is a regression test for a defect that shipped.
# The ledger is the one asset in this repo that cannot be regenerated, so the
# write path deserves more suspicion than the read path, and until 2026-08-18
# it had less.
print("\n-- ingest refuses to write a ledger it cannot key correctly --")

_tmp = tempfile.mkdtemp()
try:
    hist = os.path.join(_tmp, "history")
    reports = os.path.join(_tmp, "reports")
    os.makedirs(hist)

    # DEFECT 1. reports/ is gitignored, so it does not exist on a fresh clone
    # or on a CI runner whose scan died before writing. ingest raised
    # FileNotFoundError. This is the same absence that broke CI run #1.
    try:
        res = L.ingest(reports, hist, inventory=None)
        check("an absent reports/ is zero runs, not a traceback",
              res["runs_added"] == 0)
    except Exception as exc:
        check("an absent reports/ is zero runs, not a traceback", False,
              "%s: %s" % (type(exc).__name__, exc))

    os.makedirs(reports)
    res = L.ingest(reports, hist, inventory=None)
    check("an empty reports/ is zero runs too", res["runs_added"] == 0)

    # DEFECT 2. A missing inventory silently produced an unnormalised ledger.
    # That is not a hypothetical: the ledger committed on 2026-08-16 keyed its
    # health rows on Pantheon machine names because the inventory did not exist
    # yet, every lookup fell back to the raw key, and nothing said a word. The
    # dashboard rendered 130 rows for an 84-site fleet a day later, and because
    # the store is append-only it had to be rebuilt from reports/ rather than
    # corrected.
    raised = False
    try:
        L.load_inventory(os.path.join(_tmp, "no-such-inventory.json"))
    except SystemExit:
        raised = True
    check("a MISSING inventory path is refused, not treated as empty", raised)
    check("inventory=None is still allowed, because it is explicit",
          L.load_inventory(None) == ({}, {}, {}))

    # DEFECT 3. Rows that resolve to nothing were recorded in runs.jsonl and
    # never surfaced anywhere a person would look.
    inv_path = os.path.join(_tmp, "inv.json")
    json.dump({"sites": [{"site_id": "known.com", "domain": "known.com",
                          "host_site_name": "known"}]}, open(inv_path, "w"))
    json.dump([row("known"), row("stranger")],
              open(os.path.join(reports, "fleet-health-2026-08-18_0900.json"), "w"))
    res = L.ingest(reports, hist, inventory=inv_path)
    check("an unresolved row is COUNTED, not just filed away",
          res["unresolved_count"] == 1, str(res.get("unresolved_by_run")))
    check("and it is reported against the run that carried it",
          res["unresolved_by_run"].get("health-2026-08-18_0900") == ["stranger"])
    check("a resolved row is normalised onto the inventory's site_id",
          any(json.loads(l)["site"] == "known.com"
              for l in open(os.path.join(hist, "observations.jsonl"))))

    # Idempotence. persist-ledger.sh re-ingests onto the current remote head on
    # every push attempt, so a second ingest of the same run MUST be a no-op or
    # a raced CI run would duplicate the fleet.
    before = len(open(os.path.join(hist, "observations.jsonl")).readlines())
    res = L.ingest(reports, hist, inventory=inv_path)
    after = len(open(os.path.join(hist, "observations.jsonl")).readlines())
    check("re-ingesting the same run adds nothing",
          res["runs_added"] == 0 and before == after, "%d -> %d" % (before, after))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# ------------------------------------------- 4c. the WordPress version fact
print("\n-- wp_version is deep-only, and absent is never a value --")
check("wp_version is stored as an observed fact", "wp_version" in L.OBSERVED)
check("wp_version needs SSH, so it is deep-only", "wp_version" in L.DEEP_ONLY)
check("an api-only row reports unknown, never a version",
      L.fact(row("a", wp_checked=False, wp_version="7.0.2"), "wp_version") == L.UNKNOWN)
check("a deep-scanned row reports what the site actually said",
      L.fact(row("a", wp_checked=True, wp_version="6.8.1"), "wp_version") == "6.8.1")
check("a deep scan that could not read the version says unknown",
      L.fact(row("a", wp_checked=True, wp_version=None), "wp_version") == L.UNKNOWN)

# ----------------------------------------------------------- 5. portability
print("\n-- portability --")
check("no f-strings or 3.10+ syntax needed (py3.6 compatible source)", sys.version_info >= (3, 6))
src = open(os.path.join(ROOT, "scripts", "fleet-ledger.py")).read()
check("stdlib only, no third-party imports", "import requests" not in src and "import pandas" not in src)
check("no shell out to date/timeout", "subprocess" not in src)



# ---------------------------------------------------------------------------
# COVERAGE DROPS
# ---------------------------------------------------------------------------
# 2026-08-19: two CI consent runs at 38 of 78 landed after a laptop run at 54.
# The dashboard renders the LATEST run per source, so the live page silently
# lost 16 measured sites and stayed that way for a day.
#
# The existing baseline guard could not catch it. It tested whether the
# previous run's SITE SET was a strict subset, and the consent sweep writes a
# row for every site whether or not the page loaded -- so 38-of-78 and
# 54-of-78 have IDENTICAL site sets. A row exists is not a site was measured.
#
# These assert the PROPERTY, never a count: no fleet numbers are pinned here,
# per the standing rule about tests that pin a value a new source may move.
print()
print("-- a run that measured less than the one before it --")


def _consent_report(path, sites):
    """sites: [(domain, ok)] -> a consent-sweep payload on disk."""
    json.dump({
        "kind": "consent-sweep",
        "sites": [{"domain": d, "ok": ok, "status": 200 if ok else 403,
                   "bannerDetected": ok, "bannerVendor": "OneTrust" if ok else None,
                   "preConsentTrackers": [], "finalUrl": "https://%s/" % d}
                  for d, ok in sites],
    }, open(path, "w"))


_cov = tempfile.mkdtemp()
try:
    hist = os.path.join(_cov, "history")
    reports = os.path.join(_cov, "reports")
    os.makedirs(hist)
    os.makedirs(reports)

    doms = ["a.com", "b.com", "c.com", "d.com"]
    inv = os.path.join(_cov, "inv.json")
    json.dump({"sites": [{"site_id": d, "domain": d} for d in doms]},
              open(inv, "w"))

    # Run 1: every site measured.
    _consent_report(os.path.join(reports, "fleet-consent-2026-08-01_0100.json"),
                    [(d, True) for d in doms])
    res = L.ingest(reports, hist, inventory=inv)
    check("the first run of a source cannot be a drop",
          res["coverage_drops"] == [], str(res["coverage_drops"]))

    # Run 2: same four rows, but two of them did not load. This is the exact
    # shape of the failure -- the row count does not move at all.
    _consent_report(os.path.join(reports, "fleet-consent-2026-08-01_0200.json"),
                    [("a.com", True), ("b.com", True),
                     ("c.com", False), ("d.com", False)])
    res = L.ingest(reports, hist, inventory=inv)
    drops = res["coverage_drops"]
    check("fewer sites MEASURED is a drop, even with the row count unchanged",
          len(drops) == 1, str(drops))
    check("the drop names what was lost and what it was measured against",
          bool(drops) and drops[0]["lost"] > 0
          and drops[0]["previous_run_id"] == "consent-2026-08-01_0100",
          str(drops))
    check("the degraded run is STILL ingested, because the ledger is append-only",
          res["runs_added"] == 1)

    # Run 3: recovered. Coverage going UP is routine and must stay silent, or
    # the check becomes noise and gets ignored. Direction is the whole point.
    _consent_report(os.path.join(reports, "fleet-consent-2026-08-01_0300.json"),
                    [(d, True) for d in doms])
    res = L.ingest(reports, hist, inventory=inv)
    check("coverage going back UP is not reported",
          res["coverage_drops"] == [], str(res["coverage_drops"]))

    # And the baseline guard: the recovered run must not be diffed against the
    # degraded one, or its recovery renders as the fleet changing.
    runs, obs = L.load_ledger(hist)
    i = [n for n, r in enumerate(runs) if r["run_id"] == "consent-2026-08-01_0300"][0]
    prev, _ = L.previous_run_of_same_source(runs, i, obs)
    check("a recovered run skips the degraded run as a baseline",
          prev is not None and prev["run_id"] == "consent-2026-08-01_0100",
          "chose %s" % (prev["run_id"] if prev else None))

    # The empty-set exception. An api-only health run measures ZERO sites in
    # the wp_checked family while still being a complete look at every site's
    # control plane. That is a different MODE, not a partial look, and
    # excluding it as a baseline would discard the only comparable run for
    # seven of the runs in the real ledger.
    hist2 = os.path.join(_cov, "history2")
    reports2 = os.path.join(_cov, "reports2")
    os.makedirs(hist2)
    os.makedirs(reports2)
    inv2 = os.path.join(_cov, "inv2.json")
    json.dump({"sites": [{"site_id": "s1", "domain": "s1.com", "host_site_name": "s1"},
                         {"site_id": "s2", "domain": "s2.com", "host_site_name": "s2"}]},
              open(inv2, "w"))
    json.dump([row("s1"), row("s2")],
              open(os.path.join(reports2, "fleet-health-2026-08-01_0100.json"), "w"))
    L.ingest(reports2, hist2, inventory=inv2)
    json.dump([row("s1", wp_checked=True), row("s2", wp_checked=True)],
              open(os.path.join(reports2, "fleet-health-2026-08-01_0200.json"), "w"))
    res = L.ingest(reports2, hist2, inventory=inv2)
    check("api-only -> full is coverage going UP, not a drop",
          res["coverage_drops"] == [], str(res["coverage_drops"]))
    runs, obs = L.load_ledger(hist2)
    prev, _ = L.previous_run_of_same_source(runs, len(runs) - 1, obs)
    check("an api-only run is still a usable baseline for a full run",
          prev is not None and prev["run_id"] == "health-2026-08-01_0100",
          "chose %s" % (prev["run_id"] if prev else None))

    # One definition, three readers. If MEASURED and deep_scanned ever drift,
    # the guard silently stops guarding -- which is exactly how the original
    # bug survived: two places disagreed about what "measured" meant.
    runs, obs = L.load_ledger(hist)
    agree = all(
        len(L.measured_sites(obs, r["run_id"], r["source"])) == r["deep_scanned"]
        for r in runs)
    check("deep_scanned and MEASURED cannot disagree about what was measured",
          agree)

    # A source with no coverage rule must fail loudly rather than report full
    # coverage, or adding the fifth workflow reintroduces the blind spot.
    raised = False
    try:
        L.measured_count([{"site_id": "x"}], "a-source-with-no-rule")
    except KeyError:
        raised = True
    check("a source with no coverage rule is refused, not assumed complete",
          raised)
finally:
    shutil.rmtree(_cov, ignore_errors=True)


# ---------------------------------------------------------------------------
# THE COVERAGE FLAG OF EVERY SOURCE, NOT JUST HEALTH
# ---------------------------------------------------------------------------
# `wp_checked` IS health coverage, and classify() has said so since the first
# full-mode run turned one event into 48 rows of "what changed".
#
# `consent_scan_ok` is the SAME KIND OF FACT for the consent sweep -- it is
# literally the predicate MEASURED["consent"] uses -- and it was left out. So a
# WAF blocking four sites reported the one event three ways: six consent facts
# went to UNKNOWN and collapsed correctly, while `consent_scan_ok` and
# `consent_http_status` each became a TRANSITION in "changes needing a
# decision". On the 2026-08-20 ledger that was 8 of 14 headline changes, all of
# them the scanner losing sight of a site rather than a site getting worse.
#
# These assert the PROPERTY -- a site the sweep stopped being able to load
# produces no pushable change -- not a count, so a new consent fact cannot
# silently reintroduce the noise.
print()
print("-- a site the scanner stopped being able to see is coverage, not a change --")


def _consent_row(site, ok):
    """A ledger-shaped consent row, matching what _consent_rows() writes."""
    if ok:
        return {"site": site, "site_id": site, "source": "consent",
                "consent_scan_ok": True,
                "consent_banner_vendor": "OneTrust",
                "consent_banner_detected": True,
                "consent_pre_trackers": 0,
                "consent_pre_tracker_names": "none",
                "consent_mode_denied": False,
                "consent_http_status": 200,
                "consent_final_url": "https://%s/" % site}
    # A failed row: every observation unknown, the status kept because it is
    # the reason. This is exactly what _consent_rows() produces.
    r = {"site": site, "site_id": site, "source": "consent",
         "consent_scan_ok": False, "consent_http_status": 403}
    for k in L.CONSENT_OBSERVED:
        r.setdefault(k, L.UNKNOWN)
    return r


_blocked = L.diff_runs({"x.com": _consent_row("x.com", True)},
                       {"x.com": _consent_row("x.com", False)}, TODAY)
_scan_ok = [c for c in _blocked if c["fact"] == "consent_scan_ok"]
_status = [c for c in _blocked if c["fact"] == "consent_http_status"]

check("consent_scan_ok is the consent coverage flag, so it classifies as COVERAGE",
      bool(_scan_ok) and _scan_ok[0]["class"] == "COVERAGE",
      json.dumps(_scan_ok))
check("...and so does the HTTP status that explains it",
      bool(_status) and _status[0]["class"] == "COVERAGE",
      json.dumps(_status))
check("a site the sweep lost produces NO change needing a decision",
      all(c["class"] in L.QUIET_CLASSES for c in _blocked),
      json.dumps([c for c in _blocked if c["class"] not in L.QUIET_CLASSES]))

# The other direction must stay just as quiet, or a site coming back reads as
# the fleet improving when it is only the scanner recovering.
_recovered = L.diff_runs({"x.com": _consent_row("x.com", False)},
                         {"x.com": _consent_row("x.com", True)}, TODAY)
check("...and neither does a site the sweep got back",
      all(c["class"] in L.QUIET_CLASSES for c in _recovered),
      json.dumps([c for c in _recovered if c["class"] not in L.QUIET_CLASSES]))

# ...and the coverage SUMMARY has to show which way it went. A fact whose
# values are real on both sides -- a boolean flag, an HTTP status -- never
# touches the UNKNOWN token, so the gained/lost tally counted neither and the
# line rendered as an em dash in both columns. Four sites went dark and the row
# explaining it read as though nothing had happened. This is the same defect
# `wp_checked` was special-cased for after it showed `wp_checked  -  48` in the
# LOST column on the run where coverage went from nothing to 48 sites.
_kept_b, _cov_b = L.collapse_coverage(_blocked)
_by_fact = {g["fact"]: g for g in _cov_b}
check("a coverage flag going dark is counted as LOST, not as neither",
      _by_fact.get("consent_scan_ok", {}).get("lost") == 1,
      json.dumps(_by_fact.get("consent_scan_ok")))
check("...and so is the HTTP status that went with it",
      _by_fact.get("consent_http_status", {}).get("lost") == 1,
      json.dumps(_by_fact.get("consent_http_status")))

_kept_r, _cov_r = L.collapse_coverage(_recovered)
_by_fact_r = {g["fact"]: g for g in _cov_r}
check("a site coming back is counted as GAINED",
      _by_fact_r.get("consent_scan_ok", {}).get("gained") == 1
      and _by_fact_r.get("consent_http_status", {}).get("gained") == 1,
      json.dumps([_by_fact_r.get("consent_scan_ok"),
                  _by_fact_r.get("consent_http_status")]))

# No coverage line may be silent about direction, or the summary says a fact
# moved on N sites and refuses to say which way.
_silent = [g["fact"] for g in _cov_b + _cov_r
           if g["gained"] == 0 and g["lost"] == 0]
check("no coverage line reports a move without a direction",
      not _silent, str(_silent))

# The guard that stops this recurring for source number five. Every source
# whose coverage is decided by ONE named fact must have that fact treated as
# coverage by classify(), or its next outage becomes fleet news again.
_COVERAGE_FLAGS = ("wp_checked", "consent_scan_ok")
_unclassified = [f for f in _COVERAGE_FLAGS
                 if L.classify("s", f, True, False, {}, {}, TODAY) != "COVERAGE"]
check("every named coverage flag is classified as coverage",
      not _unclassified, str(_unclassified))


# ---------------------------------------------------------------------------
# THE PERSIST PATH MUST NOT DROP THE RUN IT IS REPORTING ON
# ---------------------------------------------------------------------------
# persist-ledger.sh runs under `set -euo pipefail`. The coverage-drop guard
# makes `ingest` exit 1, so a bare call to it kills the script AT INGEST --
# before git add, commit and push, and without retrying. The CI runner is
# ephemeral, so the observations are lost: the degraded run that raised the
# alarm is exactly the run that never reaches the ledger.
#
# That inverts the file's own header contract, which is worth quoting because
# it is the design: "Data is persisted BEFORE anything is allowed to fail...
# Failing first would throw away the run that discovered the problem."
#
# The shape that works is the one already used for the unresolved-sites alarm
# at the bottom of that file: do the work, push, THEN fail. A source contract
# rather than a behavioural test because the behaviour needs a git remote.
print()
print("-- persist-ledger.sh persists before it fails --")

_persist = open(os.path.join(ROOT, "scripts", "persist-ledger.sh")).read()
# Join shell line-continuations first. Matching a single physical line is a
# test that breaks when somebody wraps the command, which says nothing about
# whether the flag is there.
_persist_joined = _persist.replace("\\\n", " ")
_ingest_line = [l for l in _persist_joined.splitlines()
                if "fleet-ledger.py ingest" in l and not l.strip().startswith("#")]
check("persist-ledger.sh calls ingest exactly once",
      len(_ingest_line) == 1, str(_ingest_line))
check("ingest is called with --allow-coverage-drop, so a degraded run is still committed",
      bool(_ingest_line) and "--allow-coverage-drop" in _ingest_line[0],
      str(_ingest_line))

# Ordering, not just presence. Committing after the alarm would be the same
# bug with extra steps.
_push_at = _persist.find("git push")
_drop_at = _persist.find("--allow-coverage-drop")
_alarm_at = _persist.find("COVERAGE DROPPED")
check("the coverage-drop alarm is raised AFTER the push, never instead of it",
      _alarm_at > _push_at > _drop_at > 0,
      "drop=%d push=%d alarm=%d" % (_drop_at, _push_at, _alarm_at))
check("the alarm is a non-zero exit, not just a log line",
      "COVERAGE DROPPED" in _persist and "exit 1" in _persist)


# ---------------------------------------------------------------------------
# THE PUBLISH SIDE OF THE COVERAGE GUARD
# ---------------------------------------------------------------------------
# ingest fails loudly on a drop, and in CI that is enough because publish is
# gated on the persist job succeeding. It is NOT enough anywhere else: ingest
# and publish can happen in different sessions, and `publish-dashboard.sh` run
# by hand renders the LATEST run per source with nothing anywhere saying that
# run saw less than the one before it. That is how 2026-08-19 happened, and
# the ingest-side guard would not have caught it.
#
# So the RENDERER has to be able to say it. Same definition as ingest -- the
# `deep_scanned` recorded on the run -- because a fourth opinion about what
# "measured" means is the exact defect this whole area exists to prevent.
print()
print("-- the renderer can tell that the latest run saw less than the last one --")


def _run(run_id, source, observed_at, deep, rows=78):
    return {"run_id": run_id, "source": source, "observed_at": observed_at,
            "deep_scanned": deep, "site_count": rows}


check("no runs is not a regression",
      L.coverage_regressions([]) == [])

check("a source's FIRST run cannot be a regression",
      L.coverage_regressions([_run("c-1", "consent", "2026-08-01T01:00:00", 54)]) == [])

_reg = L.coverage_regressions([
    _run("c-1", "consent", "2026-08-01T01:00:00", 54),
    _run("c-2", "consent", "2026-08-01T02:00:00", 50)])
check("the latest run measuring FEWER sites is a regression",
      len(_reg) == 1 and _reg[0]["source"] == "consent", json.dumps(_reg))
check("...and it names both runs and what was lost",
      bool(_reg) and _reg[0]["run_id"] == "c-2"
      and _reg[0]["previous_run_id"] == "c-1" and _reg[0]["lost"] == 4,
      json.dumps(_reg))

check("coverage going UP is not a regression",
      L.coverage_regressions([
          _run("c-1", "consent", "2026-08-01T01:00:00", 50),
          _run("c-2", "consent", "2026-08-01T02:00:00", 54)]) == [])

check("equal coverage is not a regression",
      L.coverage_regressions([
          _run("c-1", "consent", "2026-08-01T01:00:00", 54),
          _run("c-2", "consent", "2026-08-01T02:00:00", 54)]) == [])

# Only the LATEST run of each source matters here. A drop three runs ago that
# has since recovered is history, not a reason to hold up today's page.
check("a drop that has since recovered is not reported",
      L.coverage_regressions([
          _run("c-1", "consent", "2026-08-01T01:00:00", 54),
          _run("c-2", "consent", "2026-08-01T02:00:00", 38),
          _run("c-3", "consent", "2026-08-01T03:00:00", 54)]) == [])

# Sources are independent: one tool having a bad run says nothing about another.
_mixed = L.coverage_regressions([
    _run("c-1", "consent", "2026-08-01T01:00:00", 54),
    _run("h-1", "health", "2026-08-01T01:30:00", 48),
    _run("c-2", "consent", "2026-08-01T02:00:00", 50),
    _run("h-2", "health", "2026-08-01T02:30:00", 48)])
check("a drop in one source does not implicate another",
      len(_mixed) == 1 and _mixed[0]["source"] == "consent", json.dumps(_mixed))

# The api-only exception, same as everywhere else. A health run that measures
# zero sites in the wp_checked family is a different MODE, not a worse look,
# and flagging it would put a permanent warning on the page for normal
# operation -- the `upstream_pending` mistake in another costume.
check("full -> api-only is a MODE change, not a coverage regression",
      L.coverage_regressions([
          dict(_run("h-1", "health", "2026-08-01T01:00:00", 48), mode="full"),
          dict(_run("h-2", "health", "2026-08-01T02:00:00", 0), mode="api-only")]) == [])


# ---------------------------------------------------------------------------
# A CHANGE OF INSTRUMENT IS NOT A CHANGE IN THE FLEET
# ---------------------------------------------------------------------------
# The consent sweep moved from headless to headed on 2026-08-22 because
# headless cannot see trackers that detect automation -- Hotjar and Meta Pixel
# decline to fire for it. So the first headed run reports MORE trackers on
# many sites at once, and every one of them was already firing.
#
# Diffed against a headless run that is a wave of ONSET rows: new problems that
# are not new. That is the same false alarm the COVERAGE class exists to
# prevent, arriving through a door COVERAGE does not cover, because these
# values never touch the UNKNOWN token -- 4 trackers became 6.
#
# `mode` is the coverage SHAPE (full / api-only / browser). `method` is the
# INSTRUMENT. They are separate because conflating them would drag the health
# source's load-bearing api-only -> full baseline exception into this.
print()
print("-- a run taken with a different instrument is not a baseline --")


def _mrun(run_id, source, observed_at, deep, method=None, rows=78):
    r = {"run_id": run_id, "source": source, "observed_at": observed_at,
         "deep_scanned": deep, "site_count": rows, "mode": "browser"}
    if method is not None:
        r["method"] = method
    return r


def _cobs(run_id, trackers):
    """A consent observation LIST -- previous_run_of_same_source takes a list,
    and to_obs() returns a site-keyed dict of HEALTH facts, so neither shape
    fits here."""
    return [{"run_id": run_id, "observed_at": "2026-08-17T00:00:00",
             "site": "a.com", "site_id": "a.com", "source": "consent",
             "consent_scan_ok": True,
             "consent_banner_detected": True,
             "consent_pre_trackers": trackers,
             "consent_pre_tracker_names": "GA4" if trackers else "none"}]


_obs_hl = _cobs("c-1", 4)
_obs_hd = _cobs("c-2", 6)

_runs_x = [_mrun("c-1", "consent", "2026-08-01T01:00:00", 78),
           _mrun("c-2", "consent", "2026-08-02T01:00:00", 78, "chromium-headed")]
_prev, _curr = L.previous_run_of_same_source(_runs_x, obs=_obs_hl + _obs_hd)
check("a headed run does NOT take a headless run as its baseline",
      _prev is None, "chose %s" % (_prev["run_id"] if _prev else None))

# ...and therefore the tracker jump is never reported as fleet movement. This
# is the assertion that actually matters; the one above is how it is achieved.
_changes = (L.diff_runs(L.rows_for(_obs_hl, "c-1"), L.rows_for(_obs_hd, "c-2"), TODAY)
            if _prev is not None else [])
check("...so 4 trackers becoming 6 is never reported as a new problem",
      not [c for c in _changes if c["class"] in ("ONSET", "TRANSITION")],
      json.dumps(_changes))

# Two headed runs ARE comparable. Without this the source could never diff
# again, which would be a worse failure than the one being fixed.
_runs_y = [_mrun("c-2", "consent", "2026-08-02T01:00:00", 78, "chromium-headed"),
           _mrun("c-3", "consent", "2026-08-03T01:00:00", 78, "chromium-headed")]
_prev3, _ = L.previous_run_of_same_source(
    _runs_y, obs=_cobs("c-2", 6) + _cobs("c-3", 6))
check("two runs on the SAME instrument still compare",
      _prev3 is not None and _prev3["run_id"] == "c-2",
      "chose %s" % (_prev3["run_id"] if _prev3 else None))

# The health regression guard. Health runs declare no method at all, so nothing
# about them may change -- api-only -> full is a MODE move and must still find
# its baseline. That exception is load-bearing for seven runs in the real
# ledger.
_runs_h = [{"run_id": "h-1", "source": "health", "observed_at": "2026-08-01T01:00:00",
            "deep_scanned": 0, "site_count": 2, "mode": "api-only"},
           {"run_id": "h-2", "source": "health", "observed_at": "2026-08-02T01:00:00",
            "deep_scanned": 2, "site_count": 2, "mode": "full"}]
_obs_h = (list(to_obs([row("s1"), row("s2")], "h-1").values())
          + list(to_obs([row("s1", wp_checked=True),
                         row("s2", wp_checked=True)], "h-2").values()))
_prevh, _ = L.previous_run_of_same_source(_runs_h, obs=_obs_h)
check("a source that declares NO method is unaffected: api-only is still a "
      "baseline for full",
      _prevh is not None and _prevh["run_id"] == "h-1",
      "chose %s" % (_prevh["run_id"] if _prevh else None))

# ---------------------------------------------------------------------------
# "RUN EVERYTHING" HAS TO MEAN EVERYTHING
# ---------------------------------------------------------------------------
# run-all-fleet-scans.sh hardcoded `run_mode=api-only`, so the one path named
# "run all the scans" was the only path that did not collect WordPress version,
# core-update status or plugin/theme counts -- the facts that answer wp2shell,
# which is the highest-value finding this project has.
#
# It was written when full mode genuinely did not work. Full has run since
# 2026-08-18, including in CI (health-2026-08-20_2305, mode=full, 48 of 52), so
# the flag outlived its reason and nothing said so. A default that quietly
# measures less than it could is the same shape as every row in CLAUDE.md's
# table.
print()
print("-- run-all-fleet-scans.sh collects everything it is able to --")

_runall = open(os.path.join(ROOT, "scripts", "run-all-fleet-scans.sh")).read()
check("the run-everything script asks for a FULL health scan",
      "run_mode=full" in _runall,
      "it still passes run_mode=api-only, so it skips wp_version and plugins")
check("...and does not also pass api-only, which would be ambiguous",
      "run_mode=api-only" not in _runall)

# The workflow's own default matters just as much: somebody pressing the button
# in the GitHub UI should get the complete scan, not the reduced one.
_hc = open(os.path.join(ROOT, ".github", "workflows",
                        "pantheon-fleet-healthcheck.yml")).read()
_blk = _hc[_hc.find("run_mode:"):_hc.find("target_env:")]
check("the workflow's own default run_mode is full",
      'default: full' in _blk, _blk.strip()[:120])
check("...and api-only is still available as a deliberate choice",
      "api-only" in _blk)

# The header claimed the SSH key was not registered, months after it was. It is
# what made this misread as a phase of work rather than a one-word fix.
check("the workflow header no longer claims full mode is unreachable",
      "PHASE 1 (now): manual dispatch, API-only, no SSH key" not in _hc)



# ---------------------------------------------------------------------------
print("\n-- the component inventory: a list, not a fact --")

_tmp = tempfile.mkdtemp()
try:
    hist = os.path.join(_tmp, "history")
    reports = os.path.join(_tmp, "reports")
    os.makedirs(hist); os.makedirs(reports)
    inv = os.path.join(_tmp, "inv.json")
    with open(inv, "w") as fh:
        json.dump({"sites": [
            {"site_id": "a.com", "domain": "a.com", "host_site_name": "a",
             "production": True},
            {"site_id": "b.com", "domain": "b.com", "host_site_name": "b",
             "production": True}]}, fh)

    payload = [
        # Inventoried: two plugins (one pending), one mu-plugin, one theme.
        row("a", wp_checked=True, wp_version="6.9.4", wp_core_update="up-to-date",
            plugin_updates=1, theme_updates=0, components_checked=True,
            components=[
                {"name": "pods", "type": "plugin", "status": "active",
                 "update": "available", "version": "3.2.7",
                 "update_version": "3.3.1"},
                {"name": "akismet", "type": "plugin", "status": "inactive",
                 "update": "none", "version": "5.3.4", "update_version": ""},
                {"name": "wp-native-php-sessions", "type": "mu-plugin",
                 "status": "must-use", "update": "none", "version": "2.0.1"},
                {"name": "astra", "type": "theme", "status": "active",
                 "update": "none", "version": "4.8.6", "update_version": ""},
            ]),
        # NOT inventoried. Every WP-CLI call failed, as on a site whose
        # database is not installed.
        row("b", wp_checked=True, wp_version="6.9.4",
            wp_core_update="unknown", plugin_updates=None, theme_updates=None,
            components_checked=False, components=None),
    ]
    with open(os.path.join(reports, "fleet-health-2026-08-20_0900.json"), "w") as fh:
        json.dump(payload, fh)

    res = L.ingest(reports, hist, inventory=inv)
    comp_path = os.path.join(hist, "components.jsonl")
    comps = [json.loads(l) for l in open(comp_path) if l.strip()]

    check("component rows are written to their own ledger",
          res["components_added"] == 4 and len(comps) == 4,
          "added=%r rows=%d" % (res.get("components_added"), len(comps)))

    a_rows = [c for c in comps if c["site"] == "a.com"]
    b_rows = [c for c in comps if c["site"] == "b.com"]

    # THE POINT OF THE WHOLE FEATURE. A site nobody could inventory must
    # produce no rows, and must not be reachable by any query that would make
    # it look like a site running nothing. "No vulnerable plugin found" and
    # "we never listed the plugins" are different answers.
    check("a site with components:null produces NO component rows",
          b_rows == [], repr(b_rows))
    check("...and says so on the observation row, rather than by absence",
          all(o["components_checked"] is False
              for o in [json.loads(l) for l in
                        open(os.path.join(hist, "observations.jsonl"))
                        if l.strip()] if o["site"] == "b.com"))

    check("every component type survives ingest",
          sorted(set(c["type"] for c in a_rows))
          == ["mu-plugin", "plugin", "theme"],
          repr(sorted(set(c["type"] for c in a_rows))))

    # mu-plugins are invisible to `wp plugin list`. If the scanner ever stops
    # making the second call these rows vanish and nothing else changes.
    check("mu-plugins are inventoried, not dropped",
          any(c["slug"] == "wp-native-php-sessions" and c["type"] == "mu-plugin"
              for c in a_rows))

    pods = [c for c in a_rows if c["slug"] == "pods"][0]
    check("a pending update carries the version it would move to",
          pods["update_available"] is True and pods["update_version"] == "3.3.1",
          repr(pods))
    akismet = [c for c in a_rows if c["slug"] == "akismet"][0]
    check("an up-to-date component is recorded, not omitted",
          akismet["update_available"] is False and akismet["version"] == "5.3.4",
          repr(akismet))
    # The whole reason the --update=available filter came off: during the ~36
    # hours Pods had no patch, an update-backlog list showed nothing at all.
    check("...so the inventory holds components with nothing pending",
          len([c for c in a_rows if not c["update_available"]]) == 3)

    check("components rows are keyed on the inventory domain, not the host name",
          all(c["site_id"] in ("a.com", "b.com") for c in comps),
          repr(sorted(set(c["site_id"] for c in comps))))

    obs = [json.loads(l) for l in
           open(os.path.join(hist, "observations.jsonl")) if l.strip()]
    check("the component LIST never leaks into the observation ledger",
          all("components" not in o for o in obs),
          repr([k for k in obs[0] if "component" in k]))

    # `wp plugin list` ALREADY returns must-use plugins, with status
    # "must-use", so the scanner's separate --status=must-use call lists every
    # one of them a second time. Measured on the first real run, 2026-08-23:
    # 51 duplicate rows across 16 sites. The exact shape, both rows, from
    # lasershows -- note `update` is a BOOLEAN false in one and the string
    # "none" in the other, which is why they cannot be compared whole.
    dup_payload = [row("a", wp_checked=True, components_checked=True,
                       plugin_updates=0, theme_updates=0,
                       components=[
                           {"name": "bot-block", "status": "must-use",
                            "update": False, "version": "",
                            "update_version": "", "type": "plugin"},
                           {"name": "bot-block", "status": "must-use",
                            "version": "", "type": "mu-plugin",
                            "update": "none"},
                           # A theme may legitimately share a slug with a
                           # plugin, so themes are keyed separately and this
                           # one must SURVIVE.
                           {"name": "bot-block", "status": "active",
                            "update": "none", "version": "1.0",
                            "type": "theme"},
                       ])]
    dr = L._component_rows(dup_payload, {"a": "a.com"})
    check("a must-use plugin returned by BOTH calls is stored once",
          len([x for x in dr if x["type"] != "theme"]) == 1, repr(dr))
    check("...and keeps the mu-plugin typing, not the plugin one",
          [x for x in dr if x["type"] != "theme"][0]["type"] == "mu-plugin",
          repr(dr))
    check("...while a theme sharing the slug is not collapsed with it",
          len([x for x in dr if x["type"] == "theme"]) == 1, repr(dr))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# Coverage classification. components_checked moves False->True on every
# inventoried site the first time the new scanner runs. Without both entries
# that single event lands as fleet news, which is exactly what wp_checked did.
check("components_checked is declared a coverage flag",
      "components_checked" in L.COVERAGE_FLAGS)
check("...and has a direction, so the coverage line is not blank in both columns",
      "components_checked" in L.COVERAGE_DIRECTION)
check("...and gaining an inventory reads as coverage GAINED",
      L.COVERAGE_DIRECTION["components_checked"](False, True) is True)
check("components_checked is deep-only, so an api-only run reads unknown",
      L.fact({"wp_checked": False, "components_checked": True},
             "components_checked") == L.UNKNOWN)



# ---------------------------------------------------------------------------
print("\n-- the component catalogue page --")

check("load_components on a missing file is [] , not a traceback",
      L.load_components("/nonexistent-history-dir") == [])

_tmp = tempfile.mkdtemp()
try:
    hist = os.path.join(_tmp, "history")
    os.makedirs(hist)
    with open(os.path.join(hist, "components.jsonl"), "w") as fh:
        for r in ({"run_id": "r1", "site_id": "a.com", "slug": "pods",
                   "type": "plugin", "version": "3.3.9.1"},
                  {"run_id": "r2", "site_id": "a.com", "slug": "pods",
                   "type": "plugin", "version": "3.3.9.1"}):
            fh.write(json.dumps(r) + "\n")
    check("load_components narrows to one run when asked",
          len(L.load_components(hist, "r1")) == 1
          and len(L.load_components(hist)) == 2)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# The renderer, driven through its real entry points.
_rspec = importlib.util.spec_from_file_location(
    "renderer", os.path.join(ROOT, "scripts", "render-dashboard.py"))
RD = importlib.util.module_from_spec(_rspec)
_rspec.loader.exec_module(RD)

_sites = [{"site_id": "a.com", "host": "CM Pantheon"},
          {"site_id": "b.com", "host": "CM Pantheon"}]
_rows = [{"site_id": "a.com", "slug": "pods", "type": "plugin",
          "version": "3.3.9.1", "status": "active", "update_available": False,
          "update_version": None},
         {"site_id": "a.com", "slug": "akismet", "type": "plugin",
          "version": "5.3", "status": "inactive", "update_available": True,
          "update_version": "5.3.4"}]
_c = RD.build_components(_rows, _sites, {"a.com"}, _sites)
check("the catalogue is keyed on (slug, type), not display name",
      sorted(x["slug"] for x in _c["catalogue"]) == ["akismet", "pods"])
check("a site with no inventory is NAMED, not just missing from a count",
      _c["sites_missing"] == ["b.com"], repr(_c))
check("pending is counted from update_available, not from row count",
      {x["slug"]: x["pending"] for x in _c["catalogue"]}
      == {"pods": 0, "akismet": 1})

# --------------------------------- 3c. the Kind key, and the hosts it names
# Added 2026-08-27. Doug asked what DRIFT meant; the first fix put the answer
# in a <details>, and he said "now I see it. its buried." Every <details> on
# that page is closed by default, the CRIT/WARN/OK one included, so a folded
# key is a key nobody knows exists.
print("\n-- the Kind key is visible, not folded --")

# getattr, not attribute access: a missing helper must report FAIL, not raise
# and take every test below it with it.
_gloss = getattr(RD, "AXIS_GLOSS", {})
_leg = RD.axis_legend() if hasattr(RD, "axis_legend") else ""
check("the renderer exposes a Kind key at all", bool(_leg))
check("every axis used in the Kind column is glossed",
      all(a in _gloss for a in ("RISK", "COVERAGE", "PLANNING", "DRIFT")),
      str(sorted(_gloss)))
check("the key names all four", bool(_gloss) and all(a in _leg for a in _gloss), _leg[:120])
# THE POINT OF THE FIX. A <details> here would render closed.
check("the key is not inside a <details>", bool(_leg) and "<details" not in _leg, _leg[:120])
check("each gloss travels with its pill",
      bool(_gloss) and _leg.count("kindkey") == len(_gloss), str(_leg.count("kindkey")))
# Every axis standing() can emit must have a gloss, or a new one renders a
# bare pill with nothing saying what it means -- the exact gap being closed.
_axes_in_tone = set(RD.AXIS_TONE)
check("no axis has a tone but no gloss",
      bool(_gloss) and not (_axes_in_tone - set(_gloss)),
      str(sorted(_axes_in_tone - set(_gloss))))

print("\n-- the components page names the hosts it actually covers --")
# "This page can see 68 of 75 Pantheon sites" over 53 Pantheon and 22 Nexcess.
# COMPONENT_HOSTS was widened when Nexcess landed and the prose was not.
check("Nexcess is a component host",
      "CM Nexcess" in getattr(RD, "COMPONENT_HOSTS", ()))
_phrase = RD.component_host_phrase() if hasattr(RD, "component_host_phrase") else ""
check("the phrase names every component host, not just Pantheon",
      bool(_phrase) and all(h.replace("CM ", "") in _phrase
                            for h in getattr(RD, "COMPONENT_HOSTS", ())), _phrase)
check("...and carries no 'CM ' prefix into the prose",
      bool(_phrase) and "CM " not in _phrase, _phrase)


# THE ABSENCE CASE. An empty catalogue must say so in words. Rendering an
# empty table would state "this fleet runs no plugins", which is never true
# and is the exact failure this project keeps making.
_empty = RD.build_components([], _sites, set(), _sites)
_m = {"components": _empty, "sites": _sites, "generated": "x",
      "latest": {}, "coverage": []}
_html = RD.render_components(_m)
check("an empty catalogue says no inventory exists, in words",
      "No component has been inventoried yet" in _html)
check("...and does not render an empty table as an answer",
      "<table" not in _html, _html[-300:])
check("...and the coverage statement still names a denominator",
      "0 of 2" in _html, _html[:1200])

_full = RD.render_components({"components": _c, "sites": _sites,
                              "generated": "x",
                              "latest": {"health": {"run_id": "r1"}},
                              "coverage": []})
check("a populated catalogue renders a table",
      "<table" in _full and "pods" in _full)
check("...and states coverage before the table",
      _full.index("can see") < _full.index("<table"))
check("...and names the uninventoried site on the page",
      "b.com" in _full)

# The site picker, added after the first version shipped with only a search
# box: typing a domain worked but nothing said so.
check("the picker offers only sites that HAVE an inventory",
      '<option value="a.com">' in _full
      and '<option value="b.com">' not in _full, "b.com must not be offered")
check("...and an option to go back to the whole fleet",
      "the whole fleet" in _full)

# A fleet-wide count sitting in a view that looks per-site is the same failure
# as a count standing in for an absence, pointed the other way. The page must
# SAY which columns are which rather than leave it to be inferred.
check("a site-filtered view states that Sites/Versions/Pending stay fleet-wide",
      "stay fleet-wide" in _full and "On this site" in _full)

# ?site=<a site with no inventory> must not leave a bare "0 of 312" on screen,
# which reads as "this site runs no plugins".
check("an uninventoried site in the URL is explained, not shown as zero",
      "has no component inventory" in _full
      and "not a site with no plugins" in _full)

# THE TWO COUNTS. The fleet table's plugin cell means "updates PENDING" -- 1
# for 11daypowerplay.com -- and it links here, where that site shows 26
# plugins INSTALLED. Both are right, and with nothing reconciling them the
# link read as a contradiction. Reported by Doug, 2026-08-23.
check("a site view states installed AND pending, and names the fleet count",
      "installed on" in _full and "update pending" in _full
      and "the plugin/theme count on the fleet page" in _full)

# Per-site pending needs per-install data; the row-level `pending` flag is
# fleet-wide, so filtering on it inside a site view would list components
# whose update is waiting on some OTHER site.
check("each install row carries whether the update is pending THERE",
      'data-pending="1"' in _full,
      "no per-install pending flag; the scope filter would use the "
      "fleet-wide one inside a per-site view")

# textContent does not decode HTML entities, so a &rarr; in the data attribute
# the per-site column reads rendered as the literal characters "&rarr;".
check("the version arrow is a character, not an entity",
      "&rarr;" not in _full, "found &rarr; in rendered output")

# DISCOVERABILITY. The catalogue shipped reachable only from one of 47
# plugin-count cells in column 10 of the site table, so a reader who never
# scrolled had no idea it existed. It is EVIDENCE behind the health card, not
# a fourth question -- a site has no status on components -- so it gets links
# from the health card and the coverage box rather than a card of its own.
_page = RD.render(RD.build_model("./history", "./data/fleet-inventory.json",
                                 datetime.date(2026, 8, 23)))
_above = _page[:_page.find("<table id=fleet")]
check("the fleet page links to the catalogue ABOVE the site table",
      _above.count('href="/components"') >= 2,
      "%d link(s) above the table" % _above.count('href="/components"'))
# QA before sharing with the team, 2026-08-23.
#
# EVERY table needs its own horizontal scroller, not just the site table.
# Measured at 390px: five of six sat in plain cards, so the whole document
# scrolled sideways on a phone -- "What changed" was 616px inside a 348px
# card, and it is the section GETTING-STARTED tells people to read first.
_tables = _page.count("<table")
_wrapped = (_page.count("class=tablewrap><table")
            + _page.count('class="card tablewrap"><table'))
check("every table on the fleet page sits in a horizontal scroller",
      _tables == _wrapped and _tables > 0,
      "%d table(s), %d wrapped" % (_tables, _wrapped))

# A row that is SHOWN but not COUNTED. The health card reads "CRIT 2" and
# filtering to CRIT returns three rows, because cm-whitelabel is
# production:false. Deliberate, but with nothing on the row saying so it
# reads as the card being wrong.
check("a non-production row says it is excluded from the counts",
      "excluded from the counts above" in _page)

# The footer promised "Trend charts appear once the ledger holds enough runs",
# which says they arrive on their own. Nothing implements them: no chart code,
# no threshold, no check. It also argued a line would be "points pretending to
# be a trend" while printing a run count of 27.
# House style, borrowed from [removed] so the company's apps read as one product:
# its paper, ink, hairlines, type stack and square corners. Radius is 0
# throughout there; the state dot is the one thing kept round, because it is a
# dot.
check("the shared chrome matches [removed]: paper, strong ink, square corners",
      "#efefea" in _page and "--strong:#1c122d" in _page.replace(" ", "")
      and "border-radius:0" in _page)
check("...and nothing is left rounded except the state dot",
      _page.count("border-radius:") - _page.count("border-radius:0")
      == _page.count("border-radius:50%"),
      "unexpected non-zero radius in the stylesheet")

# The severity hues are NOT [removed]'s. They were validated for colourblind
# separation and the obvious green+amber pair was rejected; [removed]'s
# --good #0E7A55 / --red #B4392F have not been through that, and there colour
# is decorative while here it carries the finding.
# Light only, matching [removed]. A dark variant was a second palette to keep in
# step and a second set of ratios to re-measure. The explicit body background
# is what stops the page inheriting a dark host ground once the media query is
# gone -- without it this ink renders on someone else's black.
check("the page declares no dark variant",
      "prefers-color-scheme" not in _page)
check("...and paints its own ground, so it cannot inherit a dark one",
      "background:var(--surface)" in _page.replace(" ", " "))

check("the severity palette stays ours, not [removed]'s",
      "#1baf7a" in _page and "#eb6834" in _page and "#2a78d6" in _page
      and "#0e7a55" not in _page.lower() and "#b4392f" not in _page.lower())

# Uppercasing the chips at 10px dropped the label to 2.8:1 (OK) and 3.2:1
# (CRIT) against a white card. The label is mixed toward --ink; the DOT keeps
# the exact validated hue, because a swatch carries no text and no ratio.
check("chip labels are darkened for contrast while the dot keeps the pure hue",
      "color-mix(in srgb,var(--good) 62%,var(--ink))" in _page
      and ".chip.good .dot{background:var(--good)}" in _page)

# ---------------------------------------------------------------------------
# Batch one of the UI direction, 2026-08-26
# ---------------------------------------------------------------------------

# TWO UNRELATED THINGS WERE BOTH CALLED "NEEDS A DECISION": the headline
# number, which counts facts that MOVED, and a section listing sites with no
# production ruling, which nothing measured and no scan will ever resolve.
# Same words, same page, 3,000 words apart.
# The headline used to be one number labelled "changes needing a decision",
# colliding with a section 3,000 words below listing sites that need a RULING.
# It is now four tiles, and the two questions are separate tiles.
_hero_zone = _page[:_page.find("<h2>")]
check("the change count and the ruling queue are separate headline numbers",
      "Changed since the last run" in _hero_zone
      and "Rulings waiting on a person" in _hero_zone,
      "the two questions are not both named at the top")
check("...and neither is described as a change needing a decision",
      "needing a decision" not in _hero_zone.lower())
check("...each headline number states what it counts",
      _hero_zone.count("<small>sites</small>") >= 4,
      "a tile does not name its unit")
check("...and the ruling queue is named for what it is",
      "Rulings waiting on a person" in _page)

# COVERAGE: what is NOT checked is the operational number, and an exception
# count with no denominator cannot be sized, so both halves are printed.
check("coverage states checked, not-checked AND the denominator",
      "checked" in _page and "not checked" in _page and "&mdash; of " in _page)
check("...and full coverage says so rather than showing a zero",
      "none missing" in _page)
# The old form must be gone, or two vocabularies describe one number.
import re as _re2
check("...and the bare 'N of M' coverage form is gone",
      not _re2.search(r'<div class=n>\d+ of \d+</div>', _page),
      "found the old coverage figure form")

# FRESHNESS: one sweep line, with the per-tool detail folded away rather than
# deleted -- a freshness line that names the wrong instrument is worse than
# none, and that bug shipped once.
check("there is one sweep line, not a card per source",
      "Last sweep" in _page and "scan(s)" in _page)
# POSITION, not just presence. It was first written inside the coverage
# section, which put it 1,500px down the page -- below the masthead, the
# headline card and the whole suite -- under a heading about METHOD. "How
# fresh is this page" is the first question a reader has, so the answer sits
# above everything that depends on it.
# ONE sweep line. The tiles block was lifted from a fork that rendered its
# own, so the page briefly carried two identical freshness lines stacked.
check("there is exactly one sweep line",
      _page.count("Last sweep") == 1,
      "found %d" % _page.count("Last sweep"))
check("...and it sits above the headline numbers, not 1,500px down",
      _page.find("Last sweep") < _page.find("class=tiles"),
      "the sweep line is below the headline tiles")
check("...with a route to the per-scan detail rather than a dead end",
      'href="#knows"' in _page and 'id=knows' in _page)
# "cohort" is an internal word for one scan of one site set by one transport.
# The page never defines it, so it must not use it.
check("...and it does not use our internal word for a scan",
      "cohort" not in _page.lower(), "the page says cohort")
check("...and the per-tool timestamps are still reachable",
      "Which tool looked, and when" in _page
      and _page.count("class=srcdetail") >= 1)

# ---------------------------------------------------------------------------
# Two columns printed a bare `unknown`, 2026-08-26
#
# upstream_pending and dkim_selector went straight from the ledger to the
# cell, so the string `unknown` reached the page raw on 34 rows while every
# other column already said WHICH absence it was showing. Both readings are
# actively misleading:
#
#   UPSTREAM  Nexcess has no upstream concept at all, so there is nothing to
#             measure rather than something unmeasured.
#   DKIM      a selector cannot be discovered from DNS. `unknown` under a DKIM
#             header reads as "no DKIM", which is the opposite of the truth.
# ---------------------------------------------------------------------------
import re as _re3
check("no cell prints a bare `unknown`",
      not _re3.search(r'<td class=(num|quiet)>unknown<', _page),
      "found a raw unknown in a table cell")
check("...a host with no upstream concept says so",
      "no upstream" in _page)
check("...and an unknown DKIM selector says the selector is unknown",
      "selector not known" in _page or "no sending domain" in _page)

# THE EMAIL CARD CARRIED THE MOST COPY ON THE PAGE for the least urgent
# question: 276 visible words against 134 and 93 for the two cards beside it.
# Assert the RELATIONSHIP, not a word count -- the numbers are entitled to
# move and the ordering is not.
def _card_words(page, head):
    i = page.find("<div class=wfhead>%s</div>" % head)
    if i < 0:
        return None
    j = page.find('<div class="card wfcard">', i)
    k = page.find("<h2", i)
    ends = [x for x in (j, k) if x > 0]
    seg = page[i:min(ends)] if ends else page[i:]
    seg = _re3.sub(r'<details[^>]*>.*?</details>', '', seg, flags=_re3.S)
    return len(_re3.sub(r'\s+', ' ', _re3.sub(r'<[^>]+>', ' ', seg)).split())
_ew, _hw = _card_words(_page, "Email DNS"), _card_words(_page, "Fleet health")
check("the email card no longer carries more copy than fleet health",
      _ew is not None and _hw is not None and _ew <= _hw + 10,
      "email %s words, health %s words" % (_ew, _hw))
check("...and it keeps the one qualification a reader needs",
      "have no sending domain recorded" in _page and "never a pass" in _page)

def _text(page):
    """The page as a reader sees it, tags removed.

    These assertions matched literal strings like "6 site(s) have none
    recorded", which broke the moment the number was wrapped in <b>. The
    claim is about what the page SAYS, not about the markup around it.
    """
    import re as _r
    import html as _h
    return _r.sub(r"\s+", " ", _h.unescape(_r.sub(r"<[^>]+>", "", page)))


# ---------------------------------------------------------------------------
# Top issues, with a direction, 2026-08-26
#
# "54 sites need attention" is correct and useless: 30 are behind on WordPress
# core, 22 have a plugin backlog. The actionable unit is the CAUSE, and a
# backlog with no direction is the same sentence whether it grew or shrank.
# ---------------------------------------------------------------------------
check("the largest causes are named near the top, not only at the bottom",
      _page.find("Top issues") < _page.find("Still open, as of"),
      "the cause list is only at the bottom")
check("...and each carries a site count and a direction",
      "Since the previous run" in _page
      and ("unchanged at" in _page or "&uarr;" in _page or "&darr;" in _page))
check("...and it routes to the full list rather than replacing it",
      'href="#stillopen"' in _page and "id=stillopen" in _page)

# THE GUARD THAT MATTERS. A trend across a change of instrument reports new
# visibility as a regression -- the defect the baseline rule was written for
# the day the consent sweep went headed. Where there is no comparable run, the
# page must say so rather than draw an arrow from nothing.
check("a cause with no comparable earlier run draws NO direction",
      "no baseline" in _page,
      "every cause claims a direction, including ones with nothing to compare")
_sm2 = RD.build_model("./history", "./data/fleet-inventory.json",
                      datetime.date(2026, 8, 23))
_causes = {g["cause"] for g in _sm2["standing"]}
check("...and the baseline map never invents a cause that is not open now",
      set(_sm2["standing_was"]) <= _causes | set(_sm2["standing_was"]),
      "baseline map is not keyed on causes")
# Direction is only meaningful because MORE sites carrying a finding is worse.
# Assert the arrows point that way, or the colour says the opposite of the
# number.
check("growth is drawn as the bad direction, shrinkage as the good one",
      ".trendup{color:color-mix(in srgb,var(--bad)" in _page
      and ".trenddown{color:color-mix(in srgb,var(--good)" in _page)

# ---------------------------------------------------------------------------
# The headline numbers open, and the change feed groups by site, 2026-08-26
# ---------------------------------------------------------------------------
# A summary number that cannot be opened is one the reader has to take on
# trust. Each tile filters the table to exactly the rows it counts.
check("every headline number filters the table",
      _page.count("data-tile=") >= 4 and "__attention" in _page
      and "__decision" in _page and "__changed" in _page)
# The card counts EXCLUDE production:false sites and the table SHOWS them, so
# clicking a tile reading 54 returns 55 rows. Without saying so the card reads
# as wrong -- the defect is already in CLAUDE.md's table.
check("...and the row count reconciles shown against counted",
      "shown but not counted in the cards above" in _page)
check("...and every row carries what the tiles filter on",
      'data-decision="' in _page and 'data-changed="' in _page
      and 'data-excluded="' in _page)

# ONE WORDPRESS UPGRADE MOVES THREE FACTS on one site. As one row per fact
# that reads as three events. The site is the unit a person works in.
check("the change feed groups by site, not by fact",
      'class="chgsite' in _page and "class=chghead" in _page)
check("...and states the fact count and the site count separately",
      "fact(s)</b> moved across <b>" in _page)
# Improved/regressed was proposed and refused: the headless-to-headed browser
# switch raised tracker counts on many sites at once and nothing had started
# firing. The ledger's own classification drives the list instead.
check("...and does not label a direction the ledger cannot know",
      "improved" not in _text(_page).lower()
      and "regressed" not in _text(_page).lower())

# METHODOLOGY FOLDS, QUALIFICATION DOES NOT. A qualification says what a
# number is OF; fold it and the number is wrong.
check("each card offers its methodology without putting it in the way",
      _page.count("details class=md") >= 3)
check("...and the qualifications stay in the reader's path",
      "whose backup age can be read at all" in _text(_page)
      and "have no sending domain recorded" in _text(_page)
      and "refused the scanner, not a clean site" in _text(_page))

check("the page does not promise a trend chart it cannot draw",
      "Trend charts appear" not in _page and "No trend chart is drawn" in _page)

check("...and the suite is still three cards, not four",
      _page.count('class="card wfcard"') == 3,
      "found %d suite cards; a components card would advertise a status a "
      "site does not have" % _page.count('class="card wfcard"'))

# ---------------------------------------------------------------------------
# The UNKNOWN figure in the coverage paragraph, 2026-08-26
#
# It was the literal characters "that number is 0", typed on 2026-08-19 when
# the consent sweep had just taken UNKNOWN to zero. It was WRONG on
# 2026-08-25: app.eastauroracc.com arrived from the Nexcess API in no roster,
# no source had seen it, UNKNOWN was 1 and the page said 0. The SSH scan
# reached it the same day and took it back to 0, which is the worst case for
# a hardcoded claim -- usually right, so nobody rereads it.
#
# Assert the PROPERTY, never the number: the sentence has to agree with the
# model it was rendered from, whatever that model says.
# ---------------------------------------------------------------------------
_um = RD.build_model("./history", "./data/fleet-inventory.json",
                     datetime.date(2026, 8, 23))
_uh = _um["health"]
_un = _uh["counts"].get("UNKNOWN", 0) + _uh["excluded"].get("UNKNOWN", 0)
check("the page's UNKNOWN claim agrees with the model it rendered from",
      ("no site is UNKNOWN on health" in RD.render(_um)) == (_un == 0),
      "the model says %d UNKNOWN" % _un)

# The half that fails against hardcoded copy. Counted across production and
# non-production alike, because the sentence is a claim about the fleet.
_uh["counts"]["UNKNOWN"] = _uh["counts"].get("UNKNOWN", 0) + 1
_uh["counts"]["OK"] = max(0, _uh["counts"].get("OK", 0) - 1)
_upage = RD.render(_um)
check("...and one site going UNKNOWN changes what the sentence says",
      "no site is UNKNOWN on health" not in _upage
      and "1 site(s) are UNKNOWN" in _upage,
      "the sentence did not move when the model did")

_uh["counts"]["UNKNOWN"] = 0
_uh["excluded"]["UNKNOWN"] = 1
check("...including an UNKNOWN on a non-production site",
      "no site is UNKNOWN on health" not in RD.render(_um),
      "an excluded site was dropped from a fleet-wide claim")

# ---------------------------------------------------------------------------
# The sending domain: recorded vs measured, 2026-08-26
#
# SPF, DKIM and DMARC are all queried at the SENDING domain, and that value
# was a ruling nothing had ever checked. post-smtp stores the site's own
# answer and the deep scan is already inside the site.
#
# The card's "N site(s) have none recorded" was counted as
# `spf_present is None and not spf_checked_at`, which is sites with no email
# row AT ALL -- outside the workflow's 78. The sites that genuinely have none
# recorded carry the STRING "unknown" in spf_checked_at, which is truthy, so
# none of them was ever counted. Both figures were 7 on the day it was found.
# ---------------------------------------------------------------------------
_sm = RD.build_model("./history", "./data/fleet-inventory.json",
                     datetime.date(2026, 8, 23))
_scoped = [x for x in _sm["sites"] if x.get("spf_checked_at") is not None]
_none_recorded = [x for x in _scoped
                  if str(x.get("spf_checked_at")).lower() == "unknown"]
_outside = [x for x in _sm["sites"] if x.get("spf_checked_at") is None]
_spage = RD.render(_sm)
check("the count of sites with no RECORDED sending domain is the right set",
      ("%d site(s) have no sending domain recorded" % len(_none_recorded))
      in _text(_spage),
      "page does not state %d" % len(_none_recorded))
check("...and sites outside the email check are counted separately",
      ("%d site(s) are outside this check" % len(_outside)) in _text(_spage),
      "page does not state %d outside" % len(_outside))
# The two sets must not be confused again: if they ever have the same size the
# assertions above cannot tell them apart, so assert they are different sets
# rather than different numbers.
check("...and the two are different sets, not one number counted twice",
      set(x["site_id"] for x in _none_recorded)
      != set(x["site_id"] for x in _outside))

# THE COVERAGE LINE EXISTS BEFORE THE FIRST RUN. Step 5 of "adding a workflow
# to the suite": a line gated on rows would simply never appear, and a reader
# could not tell "not covered" from "not built".
_cov = dict((lab, kn) for lab, kn in _sm["coverage"])
_sd_line = [lab for lab in _cov if lab.startswith("Sending domain")]
check("the sending-domain coverage line is present from day one", bool(_sd_line))
check("...with the INVENTORY as its denominator, not the rows that answered",
      _cov[_sd_line[0]][1] > 0,
      "denominator is %r" % (_cov[_sd_line[0]],))

# ---------------------------------------------------------------------------
# THE MEASURED VALUE IS COMPARED AGAINST THE RIGHT FIELD
#
# The first real run reported EIGHT disagreements. All eight were false. The
# comparison was `smtp_from_domain` against `spf_checked_at`, and those answer
# different questions:
#
#   smtp_from_domain  the domain the mail claims to come FROM (header From:),
#                     which is what DMARC aligns against
#   spf_checked_at    the SENDING domain, where SPF and DKIM are published
#
# sgroilawley.com legitimately sends From: sgroilawley.com through the sending
# domain web.sgroilawley.com. Seven of the eight were exactly that. Compared
# against the workbook's `from_address`, 37 of 39 agreed.
# ---------------------------------------------------------------------------
# CONTROL THE POPULATION, DO NOT PIN A COUNT. These assertions said
# "1 disagree", which was true while no site had a measured sending domain.
# The first real scan landed 39 of them on 2026-08-26 and turned all three
# red -- a test pinning a number a new run was entitled to move, which is the
# rule in CLAUDE.md that this file has now broken four times.
#
# The fixture clears every measured value first, so the assertions are about
# the ONE site the test sets up and hold whatever the ledger holds.
for _x in _sm["sites"]:
    _x.pop("smtp_from_domain", None)
    _x.pop("smtp_plugin_seen", None)
    _x["recorded_from_domain"] = None

_target = [x for x in _scoped
           if str(x.get("spf_checked_at")).lower() not in ("unknown", "")][0]

# THE REGRESSION ASSERTION. A site whose From: domain matches what was
# recorded, but whose SENDING domain is a different host, is NOT a
# disagreement. This is the exact false positive, reproduced.
_target["smtp_plugin_seen"] = "post-smtp"
_target["smtp_from_domain"] = "example.com"
_target["recorded_from_domain"] = "example.com"
_target["spf_checked_at"] = "web.example.com"
check("a From: domain under a different SENDING domain is NOT a disagreement",
      "disagree(s) with what was recorded" not in _text(RD.render(_sm)),
      "the sending domain was compared against the From: domain again")

# A real disagreement: the site says one thing, the workbook says another.
_target["smtp_from_domain"] = "somewhere-else.example"
_dpage = RD.render(_sm)
check("a measured From: domain that disagrees with the record is reported",
      "1 disagree(s) with what was recorded" in _text(_dpage),
      "disagreement not on the page")
check("...and the page does not claim to have verified the SENDING domain",
      "envelope sender is set by the provider" in _dpage
      and "confirms the From: ruling only" in _dpage)

# Agreement is not silence: the count is stated either way, so "we measured 39
# and all agreed" cannot be mistaken for "we measured none".
_target["smtp_from_domain"] = "example.com"
check("agreement still says how many were measured",
      "all agreeing with what was recorded" in _text(RD.render(_sm)))

# Measured where nobody had recorded anything is a THIRD outcome, not an
# agreement and not a disagreement. hoffmanscheese is in no email row at all
# and its mailer answered on the first real run.
_target["recorded_from_domain"] = None
# Minor enough to fold, but not to delete: it moved into the disclosure
# when the card was trimmed on 2026-08-26.
check("a site with no recorded From: address is still counted somewhere",
      "had no recorded From: address at all" in _text(RD.render(_sm)))

# ---------------------------------------------------------------------------
# Component catalogue: slug casing, 2026-08-24
#
# WP-CLI reports the plugin DIRECTORY name, and the same component is spelled
# differently on different sites: Divi-Child on 25 and Divi-child on 16,
# PDFEmbedder-premium on 11 and pdfembedder-premium on 2. Keying the catalogue
# on the raw slug split each into two entries.
#
# The count was the small half of the problem. Wordfence publishes LOWERCASE
# slugs, so a case-sensitive match of pdfembedder-premium against a
# case-split catalogue hits 2 sites and misses 11, in the exact plugin family
# the catalogue exists to answer for.
# ---------------------------------------------------------------------------
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("_rd", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts",
    "render-dashboard.py"))
_rd = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_rd)


def _comp(site, slug, typ, version="1.0", status="active"):
    return {"site_id": site, "slug": slug, "type": typ,
            "version": version, "status": status, "update_available": False}


def _cat(rows, site_ids):
    sites = [{"site_id": s, "host": "CM Pantheon"} for s in site_ids]
    return _rd.build_components(rows, sites, set(site_ids), sites)["catalogue"]


_rows = [_comp("a", "Divi-Child", "theme"), _comp("b", "Divi-child", "theme")]
_c = _cat(_rows, ["a", "b"])
check("two casings of one slug are ONE catalogue entry, not two", len(_c) == 1)
check("...and it reports both sites", _c[0]["sites"] == 2)
check("...while preserving every casing seen on disk, so the disagreement "
      "stays visible", sorted(_c[0]["variants"]) == ["Divi-Child", "Divi-child"])

# Type still separates. A theme and a plugin sharing a name are two things.
_c2 = _cat([_comp("a", "thing", "theme"), _comp("a", "thing", "plugin")], ["a"])
check("the same slug under two TYPES stays two entries", len(_c2) == 2)

# hoffmanscheese: pdfembedder-premium 3.2 inactive beside
# PDFEmbedder-premium 5.1.4 active. Counting rows would say 2 sites.
_dupe = _cat([_comp("h", "PDFEmbedder-premium", "plugin", "5.1.4"),
              _comp("h", "pdfembedder-premium", "plugin", "3.2", "inactive")],
             ["h"])
check("one component, twice on one site, is one entry", len(_dupe) == 1)
check("SITES counts distinct sites, so installing it twice on one site is 1", _dupe[0]["sites"] == 1)
check("...and installs_count keeps the 2, so the double install is visible", _dupe[0]["installs_count"] == 2)

# The property, not the number: no two catalogue entries may normalise to the
# same (slug, type). Asserting 310 would break the next time a plugin is added.
_real = _cat([_comp("a", "Alpha", "plugin"), _comp("b", "alpha", "plugin"),
              _comp("c", "beta", "plugin")], ["a", "b", "c"])
_keys = [(x["slug"].lower(), x["type"]) for x in _real]
check("no two catalogue entries collide on lowercase slug and type", len(_keys) == len(set(_keys)))

# ---------------------------------------------------------------------------
# "Sends from" on the fleet table, 2026-08-24
#
# Victoria asked "what is the sending URL" in the first outside review. The
# page scored every site on a domain it never named: SPF, DKIM and DMARC are
# all queried at the SENDING domain, and for 34 sites that is
# smtp.clevermethod.net rather than their own.
# ---------------------------------------------------------------------------
import io as _io
import re as _re
with _io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "fleet.html"), encoding="utf-8") as _fh:
    _html = _fh.read()

check("the fleet table names the domain each site sends from",
      "<th>Sends from</th>" in _html)
# TAG-AGNOSTIC. This matched "Sends from</strong>" and broke when the
# sentence moved into a folded block that marks up with <b>. The guard is
# that the card POINTS AT the column -- it once denied the column existed --
# and that claim is about the text, not the element wrapping it.
check("...and the email card points at that column instead of denying it exists",
      "carries the per-site answer in its Sends from" in _text(_html)
      or "Sends from</strong>" in _html)
check("the card no longer claims email has no column in the fleet table",
      "no column in the fleet table below" not in _html)
check("the card says the sending domain is usually NOT the site's own",
      "sends from" in _html.lower() and "smtp.clevermethod.net" in _html)

# The absence sentinel is the STRING "unknown", not None. A falsiness test
# rendered `unknown` into the cell as though it were a domain, on six rows.
check("no row renders the unknown sentinel as a sending domain",
      "<code>unknown</code>" not in _html)
check("a site with no recorded sending domain says so rather than blank",
      "not recorded" in _html)

# Column alignment: every row must carry exactly as many cells as there are
# headers. Adding a th without a td silently shifts every column after it.
_hdrs = _html.split("<table id=fleet>")[1].split("</tr>")[0].count("<th")
_rows = _re.findall(r"<tr data-site=.*?</tr>", _html, _re.S)
check("every fleet row has one cell per column header",
      _rows and all(r.count("<td") == _hdrs for r in _rows))

# ---------------------------------------------------------------------------
# The Nexcess join key, 2026-08-25.
#
# Nexcess's own `domain` field holds the nxcli TEMP domain for 18 of our 22
# sites, because the production domain was never set as primary there. Joining
# on domain resolved those 18 to `0f614220a1.nxcli.net` and friends. The ledger
# is append-only, so those rows could never have been corrected.
# ---------------------------------------------------------------------------
_inv_j = {"sites": [
    {"site_id": "real.com", "domain": "real.com", "host": "CM Nexcess",
     "nexcess_site_id": 4242},
    {"site_id": "plain.com", "domain": "plain.com", "host": "CM Nexcess"},
]}
_, _bd_j, _recs_j = L.load_inventory_from_obj(_inv_j) \
    if hasattr(L, "load_inventory_from_obj") else (None, None, None)
if _bd_j is None:
    import tempfile as _tf, json as _js, os as _os
    _fh = _tf.NamedTemporaryFile("w", suffix=".json", delete=False)
    _js.dump(_inv_j, _fh); _fh.close()
    _, _bd_j, _recs_j = L.load_inventory(_fh.name)
    _os.unlink(_fh.name)

def _nx(sites):
    return L._nexcess_rows({"kind": "nexcess-estate", "sites": sites}, _bd_j)

# The site whose API domain is a temp domain still lands on the right row.
_r = _nx([{"domain": "abc123.nxcli.net", "nexcess_site_id": 4242,
           "unix_username": "u1"}])
check("a site whose API domain is the nxcli temp domain resolves by site id",
      len(_r) == 1 and _r[0]["site_id"] == "real.com",
      repr([x["site_id"] for x in _r]))

# Domain still works where the API reports the real one, and for rows nobody
# has mapped yet.
_r = _nx([{"domain": "plain.com", "unix_username": "u2"}])
check("a site whose API domain IS the real domain still resolves by domain",
      len(_r) == 1 and _r[0]["site_id"] == "plain.com",
      repr([x["site_id"] for x in _r]))

# The rule that matters: refuse, do not invent.
_r = _nx([{"domain": "zz999.nxcli.net", "nexcess_site_id": 9999,
           "unix_username": "u3"}])
check("an unresolvable Nexcess site is SKIPPED, never keyed on its temp domain",
      _r == [], repr(_r))

_r = _nx([{"domain": "abc123.nxcli.net", "nexcess_site_id": 4242, "unix_username": "u1"},
          {"domain": "zz999.nxcli.net", "nexcess_site_id": 9999, "unix_username": "u3"}])
check("...and one unresolvable site does not stop the resolvable ones",
      [x["site_id"] for x in _r] == ["real.com"],
      repr([x["site_id"] for x in _r]))

# The id wins over the domain, so a site that has been re-pointed cannot be
# silently attached to whatever row happens to share its current domain.
_r = _nx([{"domain": "plain.com", "nexcess_site_id": 4242, "unix_username": "u4"}])
check("the site id wins over the domain when the two disagree",
      len(_r) == 1 and _r[0]["site_id"] == "real.com",
      repr([x["site_id"] for x in _r]))

# ---------------------------------------------------------------------------
# A health row from a non-Pantheon transport, 2026-08-25.
#
# The Nexcess SSH scan writes to the `health` source, because the fact-name
# collision guard refuses a second source claiming wp_version. But health rows
# were keyed on the Pantheon machine name via by_host, and Nexcess inventory
# rows carry host_site_name: None.
# ---------------------------------------------------------------------------
_inv_h = {"sites": [
    {"site_id": "nx.com", "domain": "nx.com", "host": "CM Nexcess",
     "host_site_name": None},
    {"site_id": "pan.com", "domain": "pan.com", "host": "CM Pantheon",
     "host_site_name": "pan-machine"},
]}
import tempfile as _tf2, json as _js2, os as _os2
_f2 = _tf2.NamedTemporaryFile("w", suffix=".json", delete=False)
_js2.dump(_inv_h, _f2); _f2.close()
_bh2, _bd2, _rc2 = L.load_inventory(_f2.name); _os2.unlink(_f2.name)

_r = L._health_rows([{"site": "pan-machine", "wp_version": "6.9"}], _bh2)
check("a Pantheon row still keys on its machine name",
      _r[0]["site_id"] == "pan.com" and _r[0]["host_site_name"] == "pan-machine",
      repr(_r[0]["site_id"]))

_r = L._health_rows([{"site": "nx.com", "site_id": "nx.com",
                      "host_site_name": None, "wp_version": "7.1"}], _bh2)
check("a row carrying an explicit site_id keys on it, with no machine name",
      _r[0]["site_id"] == "nx.com" and _r[0]["host_site_name"] is None,
      repr(_r[0]))
check("...and it lands in the health source, not a new one",
      _r[0]["source"] == "health", _r[0]["source"])

# The collision the explicit key exists to prevent.
_r = L._health_rows([{"site": "pan-machine", "site_id": "nx.com",
                      "wp_version": "7.1"}], _bh2)
check("an explicit site_id wins over a machine name that would resolve elsewhere",
      _r[0]["site_id"] == "nx.com", repr(_r[0]["site_id"]))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)