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
_p, _c = L.previous_run_of_same_source(_runs, obs=_obs)
check("a strict-subset run is skipped as a baseline", _p["run_id"] == "r1", str(_p))
check("...and the current run is still the newest", _c["run_id"] == "r2")
_p2, _ = L.previous_run_of_same_source(_runs)
check("without obs the old positional behaviour is unchanged", _p2["run_id"] == "cohort")

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


print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)