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
    inv_path = os.path.join(ROOT, "data", "fleet-inventory.json")
    inv_arg = inv_path if os.path.exists(inv_path) else None
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
    check("52 observations per committed health run",
          all(r["site_count"] == 52 for r in health_runs),
          str([r["site_count"] for r in health_runs]))
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

    if len(health_runs) < 2:
        print("  SKIPPED diff: fewer than two health runs available.")
    else:
        p = L.rows_for(obs, health_runs[-2]["run_id"])
        c = L.rows_for(obs, health_runs[-1]["run_id"])
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
    check("that site carries the reconciliation note, not a silent pass",
          "absent from the workbook" in recs["hoffmanscheese"]["reconciliation"])
    check("a workbook site Pantheon does not return is flagged the other way",
          recs["hoosierfeeder.com"].get("host_site_name") is None
          and "not observed" in recs["hoosierfeeder.com"]["reconciliation"])
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

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
