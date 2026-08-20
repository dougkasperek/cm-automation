#!/usr/bin/env python3
"""
Self-check for the cookie-consent sweep: its ledger source and its severity
rules.

NOTHING HERE TOUCHES THE NETWORK OR LAUNCHES A BROWSER. The scan fixtures are
hand-written in the shape `run-sweep.mjs` writes.

Two things this suite exists to protect, both of which are the whole point of
the workflow rather than incidental correctness:

1. **A site the sweep could not load must never read as clean.** "0 trackers
   fired" on a page that never loaded is an all-clear produced by an absence,
   which is the failure this repo keeps a table of.
2. **No output anywhere says "compliant" or "non-compliant".** clevermethod
   guarantees CORRECTNESS -- did the tooling do what it was configured to do --
   and the client owns POSTURE. A tool that quietly upgrades a technical
   observation into a legal conclusion destroys that distinction, and the
   distinction is the product.

Run: ./test/test-consent.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load("fleet_ledger", os.path.join(ROOT, "scripts", "fleet-ledger.py"))
S = _load("severity", os.path.join(ROOT, "scripts", "lib", "severity.py"))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- " + detail) if (detail and not cond) else ""))


INV_PATH = os.path.join(ROOT, "data", "fleet-inventory.json")
_inv = json.load(open(INV_PATH))
_invrecs = {s["site_id"]: s for s in _inv["sites"]}
_domains = [s["domain"] for s in _inv["sites"]
            if s.get("domain") and "." in s["domain"]]

import datetime
TODAY = datetime.date(2026, 8, 19)


# ---------------------------------------------------------------------------
# 1. The roster is the inventory, and only the inventory
# ---------------------------------------------------------------------------
print("\n--- roster ---")

check("the inventory holds 78 scannable domains, which is the roster",
      len(_domains) == 78, str(len(_domains)))

_no_domain = [s["site_id"] for s in _inv["sites"]
              if not (s.get("domain") and "." in s["domain"])]
check("six inventory entries have no scannable domain and are known by name, "
      "so a coverage gap cannot hide as a silent omission",
      len(_no_domain) == 6, repr(_no_domain))

_sweep_src = open(os.path.join(ROOT, "scripts", "consent",
                               "run-sweep.mjs")).read()


def _js_code(src):
    """Source minus // comments.

    Needed because the comments deliberately NAME the things the code must not
    do -- the deleted sites.yaml, the forbidden verdict words. A grep that
    cannot tell prose from code would either fail on the sentence that forbids
    a thing, or force that sentence out of the file. The sentence is worth more
    than the grep, so the grep learns to read.
    """
    return "\n".join(l.split("//")[0] for l in src.splitlines())


_sweep_code = _js_code(_sweep_src)
check("the sweep reads the inventory and carries no site list of its own",
      "fleet-inventory.json" in _sweep_code and "sites.yaml" not in _sweep_code)
check("...and the deleted pilot roster is still NAMED in the comments, so "
      "nobody recreates it",
      "sites.yaml" in _sweep_src)
check("...and the two roster errors the reconciliation found are written down "
      "where the next person will see them",
      "morrisoncontainerhandlingsolutions.com" in _sweep_src
      and "hoosierfeedercompany.com" in _sweep_src)


# ---------------------------------------------------------------------------
# 2. It never says compliant
# ---------------------------------------------------------------------------
print("\n--- the language rule ---")

_sev_src = open(os.path.join(ROOT, "scripts", "lib", "severity.py")).read()
_led_src = open(os.path.join(ROOT, "scripts", "fleet-ledger.py")).read()


def _emitted_strings(src):
    """Everything that could reach a reader: strings, minus comments."""
    return "\n".join(l.split("#")[0] for l in src.splitlines())


for label, src in (("the sweep", _sweep_code),
                   ("severity", _emitted_strings(_sev_src)),
                   ("the ledger", _emitted_strings(_led_src))):
    low = src.lower()
    # "non-compliant" is the dangerous one; "compliance" appears in prose that
    # explains why we do not use it, so the check is on the verdict words.
    bad = [w for w in ("non-compliant", "noncompliant", "is compliant",
                       "certifies", "certified compliant") if w in low]
    check("%s emits no compliance verdict" % label, not bad, repr(bad))

# ...and the rule itself is written down in all three, so the next person knows
# it is a rule rather than an accident of phrasing.
check("the language rule is stated in the source, not just obeyed by luck",
      "non-compliant" in _sweep_src.lower()
      and "compliance verdict" in _sev_src.lower())


# ---------------------------------------------------------------------------
# 3. Ledger ingest
# ---------------------------------------------------------------------------
print("\n--- ledger ingest ---")

check("consent is a declared fact family",
      "consent" in L.FACT_FAMILIES)
check("no consent fact name collides with any other source",
      all(not (set(L.CONSENT_OBSERVED) & set(v))
          for k, v in L.FACT_FAMILIES.items() if k != "consent"))

RUN_ID = "consent-2026-08-19_2100"
_meta = L.parse_run_id("reports/fleet-consent-2026-08-19_2100.json")
check("a consent scan filename parses to its own run kind",
      _meta and _meta["run_id"] == RUN_ID, repr(_meta))

_tmp = tempfile.mkdtemp(prefix="consent-test-")
try:
    _reports = os.path.join(_tmp, "reports")
    _history = os.path.join(_tmp, "history")
    os.makedirs(_reports)

    (d_clean, d_leak, d_notool, d_dead, d_cm, d_blocked,
     d_notool_leak) = _domains[:7]
    scan = {
        "kind": "consent-sweep", "schema": "consent-sweep/1",
        "roster_source": "data/fleet-inventory.json",
        "eligible": 7, "scanned_ok": 5, "skipped_no_domain": [],
        "sites": [
            # banner, nothing fires
            {"domain": d_clean, "site_id": d_clean, "ok": True, "error": None,
             "status": 200, "finalUrl": "https://" + d_clean + "/",
             "bannerVendor": "CookieYes", "bannerVisible": True,
             "genericBannerVisible": False, "bannerDetected": True,
             "preConsentTrackers": [], "consentModeDenied": False},
            # banner, but trackers fire anyway -- the Zehnder shape
            {"domain": d_leak, "site_id": d_leak, "ok": True, "error": None,
             "status": 200, "finalUrl": "https://" + d_leak + "/",
             "bannerVendor": "OneTrust", "bannerVisible": True,
             "genericBannerVisible": False, "bannerDetected": True,
             "preConsentTrackers": ["MS Clarity", "GA4 collect"],
             "consentModeDenied": False},
            # no tooling AND trackers firing. The commonest real shape: 25 of
            # 54 on the first real sweep. A different conversation from a site
            # whose banner is present and leaking anyway.
            {"domain": d_notool_leak, "site_id": d_notool_leak, "ok": True,
             "error": None, "status": 200,
             "finalUrl": "https://" + d_notool_leak + "/",
             "bannerVendor": None, "bannerVisible": False,
             "genericBannerVisible": False, "bannerDetected": False,
             "preConsentTrackers": ["GA4 collect"], "consentModeDenied": False,
             "cmpScripts": []},
            # no tooling at all, nothing firing
            {"domain": d_notool, "site_id": d_notool, "ok": True, "error": None,
             "status": 200, "finalUrl": "https://" + d_notool + "/",
             "bannerVendor": None, "bannerVisible": False,
             "genericBannerVisible": False, "bannerDetected": False,
             "preConsentTrackers": [], "consentModeDenied": False},
            # would not load
            {"domain": d_dead, "site_id": d_dead, "ok": False,
             "error": "page.goto: net::ERR_CONNECTION_TIMED_OUT",
             "retried": True, "status": None, "finalUrl": None,
             "bannerVendor": None, "bannerVisible": False,
             "genericBannerVisible": False, "bannerDetected": False,
             "preConsentTrackers": [], "consentModeDenied": False,
             "cmpScripts": []},
            # THE 403 CASE. The sweep navigated fine and got a block page, so
            # it observed no banner and no trackers -- which is what an error
            # page contains, not what the site contains. 23 of 78 sites did
            # exactly this on the first real run and all 23 read as clean.
            {"domain": d_blocked, "site_id": d_blocked, "ok": False,
             "error": "HTTP 403: the server refused the request, so the scanner "
                      "saw an error page rather than the site",
             "httpBlocked": True, "retried": False, "status": 403,
             "finalUrl": "https://" + d_blocked + "/",
             "bannerVendor": None, "bannerVisible": False,
             "genericBannerVisible": False, "bannerDetected": False,
             "preConsentTrackers": [], "consentModeDenied": False,
             "cmpScripts": []},
            # consent-mode denied pings only: correctly configured, not a leak
            {"domain": d_cm, "site_id": d_cm, "ok": True, "error": None,
             "status": 200, "finalUrl": "https://" + d_cm + "/",
             "bannerVendor": "OneTrust", "bannerVisible": True,
             "genericBannerVisible": False, "bannerDetected": True,
             "preConsentTrackers": [], "consentModeDenied": True},
        ],
    }
    with open(os.path.join(_reports,
                           "fleet-consent-2026-08-19_2100.json"), "w") as fh:
        json.dump(scan, fh)

    res = L.ingest(_reports, _history, inventory=INV_PATH)
    check("the consent scan is recognised and ingested",
          res["runs_added"] == 1 and res["observations_added"] == 7,
          json.dumps(res))

    runs, obs = L.load_ledger(_history)
    run = [r for r in runs if r["run_id"] == RUN_ID][0]
    check("the run is stored under the consent source",
          run["source"] == "consent", repr(run["source"]))
    check("the run's mode says a browser did the looking",
          run["mode"] == "browser", repr(run["mode"]))
    check("coverage counts only the pages that actually loaded",
          run["deep_scanned"] == 5, str(run["deep_scanned"]))
    check("every row resolved to an inventory site_id",
          run["sites_not_in_inventory"] == [],
          repr(run["sites_not_in_inventory"]))

    rows = L.rows_for_source(obs, RUN_ID, "consent")
    check("the diff uses the consent fact list for a consent row",
          L.facts_for(rows[d_clean]) is L.CONSENT_OBSERVED)
    check("tracker names are stored SORTED, so a reorder is not a change",
          rows[d_leak]["consent_pre_tracker_names"] == "GA4 collect, MS Clarity",
          repr(rows[d_leak]["consent_pre_tracker_names"]))
    check("a site with no trackers records 'none', a value, not an empty string",
          rows[d_clean]["consent_pre_tracker_names"] == "none")

    # The one that matters most.
    dead = rows[d_dead]
    check("a page that would not load is STILL recorded, so a site dropping out "
          "of the sweep is visible rather than silent",
          d_dead in rows)
    check("...with scan_ok false",
          dead["consent_scan_ok"] is False)
    check("...and every other consent fact unknown, never 0 and never false",
          dead["consent_pre_trackers"] == "unknown"
          and dead["consent_banner_detected"] == "unknown"
          and dead["consent_banner_vendor"] == "unknown",
          json.dumps({k: dead[k] for k in L.CONSENT_OBSERVED}))

    # THE REGRESSION THIS SUITE EXISTS FOR, SECOND EDITION.
    # A 403 is a page that loaded. It contains no banner and fires no trackers,
    # because it is a block page. The first real sweep had 23 of these and
    # every one was classified clean.
    blocked = rows[d_blocked]
    check("a site that answered HTTP 403 is NOT counted as scanned",
          blocked["consent_scan_ok"] is False, repr(blocked["consent_scan_ok"]))
    check("...and does not record zero trackers, which is what the block page "
          "actually contained",
          blocked["consent_pre_trackers"] == "unknown"
          and blocked["consent_banner_detected"] == "unknown")
    check("...but DOES keep the status, because on a failed row it is the reason",
          blocked["consent_http_status"] == 403,
          repr(blocked["consent_http_status"]))
    check("coverage counts exclude it, so the sweep never overstates what it saw",
          run["deep_scanned"] == 5, str(run["deep_scanned"]))

    # ------------------------------------------------------------------
    # 4. Severity
    # ------------------------------------------------------------------
    print("\n--- severity ---")

    def score(domain, extra=None):
        row = dict(rows[domain])
        if extra:
            row.update(extra)
        return L.score(row, _invrecs, TODAY)

    s_clean, s_leak, s_notool, s_dead, s_cm, s_blocked = (
        score(d) for d in (d_clean, d_leak, d_notool, d_dead, d_cm, d_blocked))

    check("a site the sweep saw is no longer UNKNOWN",
          all(x["status"] != "UNKNOWN"
              for x in (s_clean, s_leak, s_notool, s_cm)),
          repr([x["status"] for x in (s_clean, s_leak, s_notool, s_cm)]))

    # AXES, 2026-08-20. A consent finding now scores the CONSENT axis and
    # leaves health alone. It has to be read off `axes["consent"]`, because
    # `reasons` deliberately carries only what agrees with the top-level
    # status. Asserting against `all_reasons` here would pass even if the axis
    # split were wired up backwards.
    check("trackers firing before consent is a WARN, not a CRIT",
          s_leak["axes"]["consent"]["status"] == "WARN"
          and any(r["code"] == "consent_pre_consent_trackers"
                  for r in s_leak["axes"]["consent"]["reasons"]), repr(s_leak))
    check("...and the reason names the trackers, so nobody has to open the scan",
          any("MS Clarity" in r["text"]
              for r in s_leak["axes"]["consent"]["reasons"]))
    check("...and describes what was observed rather than reaching a verdict",
          all("compliant" not in r["text"].lower()
              for r in s_leak["all_reasons"]))

    check("no consent tooling detected is a WARN",
          any(r["code"] == "consent_no_tooling"
              for r in s_notool["axes"]["consent"]["reasons"]),
          repr(s_notool))

    check("consent-mode denied pings alone are NOT reported as a leak, or every "
          "correctly configured site would fail",
          not any(r["code"] == "consent_pre_consent_trackers"
                  for r in s_cm["all_reasons"]), repr(s_cm))

    # A page that would not load scores nothing, but says so.
    check("a page the sweep could not load raises no consent WARN, because a "
          "rule that fires on every bot-blocking site is a floor, not a signal",
          not any(r["code"].startswith("consent_") for r in s_dead["reasons"]),
          repr(s_dead))
    check("...and says out loud that its posture is unmeasured rather than clean",
          any("unmeasured, not clean" in i for i in s_dead["info"]),
          repr(s_dead["info"]))

    check("a 403 site raises no consent WARN either, and cannot reach OK on a "
          "block page",
          not any(r["code"].startswith("consent_") for r in s_blocked["reasons"]),
          repr(s_blocked))
    check("...and the info line NAMES the status, so 'the site is down' and "
          "'the site will not talk to our scanner' are distinguishable",
          any("HTTP 403" in i for i in s_blocked["info"]),
          repr(s_blocked["info"]))

    # Coverage. A consent-only site has no backup age and no plugin count.
    check("a site seen ONLY by the consent sweep cannot reach OK",
          s_clean["status"] == "WARN"
          and any(r["code"] == "coverage_partial" for r in s_clean["reasons"]),
          repr(s_clean))
    check("...and the reason names WHICH look it had",
          any("consent sweep" in r["text"] for r in s_clean["reasons"]))

    # ...and retires itself when a health scan supplies the missing facts.
    healthy = {"wp_checked": True, "wp_version": "7.0.4", "php_version": "8.2",
               "db_backup_age_days": 1, "plugin_updates": 0, "theme_updates": 0,
               "upstream_pending": 0, "wp_core_update": "up-to-date",
               "frozen": False}
    s_both = score(d_clean, healthy)
    check("...and a site with BOTH a clean consent scan and a clean health scan "
          "reaches OK",
          s_both["status"] == "OK", repr(s_both))

    # And the leak still scores once health facts exist.
    #
    # CHANGED 2026-08-20 and this is the whole point of the axis split: a
    # consent leak no longer drags the HEALTH status down. It used to, which is
    # why the fleet-health headline moved when the consent sweep ran and
    # nothing about maintenance had changed.
    #
    # The risk in making this change is that the finding quietly disappears
    # instead of moving, so both halves are asserted together: health is OK AND
    # consent is WARN AND the finding is still there to be read.
    s_leak_both = score(d_leak, healthy)
    check("a consent leak leaves the HEALTH status alone",
          s_leak_both["status"] == "OK"
          and s_leak_both["axes"]["health"]["status"] == "OK",
          repr(s_leak_both["status"]))
    check("...but is NOT lost: it scores WARN on the consent axis",
          s_leak_both["axes"]["consent"]["status"] == "WARN"
          and any(r["code"] == "consent_pre_consent_trackers"
                  for r in s_leak_both["axes"]["consent"]["reasons"]),
          repr(s_leak_both["axes"]["consent"]))
    check("...and still appears in all_reasons, tagged with its axis",
          any(r["code"] == "consent_pre_consent_trackers"
              and r["axis"] == "consent" for r in s_leak_both["all_reasons"]))
    check("a health finding never lands on the consent axis",
          all(r["axis"] == "health"
              for r in score(d_blocked, dict(healthy, db_backup_age_days=900)
                             )["axes"]["health"]["reasons"]))
    check("an unmeasured site is UNKNOWN on the consent axis, never OK",
          s_blocked["axes"]["consent"]["status"] == "UNKNOWN",
          repr(s_blocked["axes"]["consent"]))
    check("a clean measured site IS OK on the consent axis",
          s_clean["axes"]["consent"]["status"] == "OK",
          repr(s_clean["axes"]["consent"]))

    # Security still outranks consent.
    s_leak_crit = score(d_leak, dict(healthy, php_version="7.4"))
    check("a security CRIT still outranks a consent WARN, so the CRIT list "
          "stays a security list",
          s_leak_crit["status"] == "CRIT", repr(s_leak_crit["status"]))
    check("...and the consent axis is unaffected by the security CRIT, "
          "because they answer different questions",
          s_leak_crit["axes"]["consent"]["status"] == "WARN",
          repr(s_leak_crit["axes"]["consent"]["status"]))

    # ------------------------------------------------------------------
    # Standing findings: grouped by cause, like everything else on the page.
    # ------------------------------------------------------------------
    print("\n--- standing findings ---")
    _st = L._standing_consent(rows)
    _causes = {g["cause"]: g for g in _st}
    check("a consent sweep produces grouped standing findings at all",
          len(_st) >= 3, repr(sorted(_causes)))
    check("tooling-present-but-leaking is its OWN group, because it is a build "
          "defect we own rather than a scope question for the client",
          any("tooling present" in c.lower() and "fire before consent" in c.lower()
              for c in _causes), repr(sorted(_causes)))
    check("...and the no-tooling leak is a separate group",
          any("no consent tooling is present" in c.lower() for c in _causes))
    check("the leaking groups name the trackers per site",
          any(g.get("detail") and any("MS Clarity" in v for v in g["detail"].values())
              for g in _st))
    check("sites the sweep could not see are their own COVERAGE group, never "
          "folded in with sites that were seen and found clean",
          any(g["axis"] == "COVERAGE" and "could not see" in g["cause"] for g in _st))
    check("...and that group names the HTTP status per site",
          any(g["axis"] == "COVERAGE" and g.get("detail")
              and any("403" in v for v in g["detail"].values()) for g in _st))
    check("no standing finding states a compliance verdict",
          all("compliant" not in json.dumps(g).lower() for g in _st))
    # Sort order is a finding in its own right. The tooling-present-but-leaking
    # group is 3 sites next to a 34-site group, and sorting RISK by size alone
    # buried the one group describing a defect in something we built.
    _tooled = [g for g in _st if "tooling present" in g["cause"].lower()][0]
    check("the tooling-present-but-leaking group carries an explicit priority, "
          "so a 3-site defect we own outranks a 34-site client scope question",
          _tooled.get("priority", 0) > 0, repr(_tooled.get("priority")))
    check("...and no other consent group claims priority, so the key stays "
          "meaningful rather than becoming decoration",
          sum(1 for g in _st if g.get("priority", 0) > 0) == 1)

    res2 = L.ingest(_reports, _history, inventory=INV_PATH)
    check("re-ingesting the same run adds nothing",
          res2["runs_added"] == 0 and res2["observations_added"] == 0)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. The scanner's own contract
# ---------------------------------------------------------------------------
print("\n--- scanner contract ---")

_check_src = open(os.path.join(ROOT, "scripts", "consent",
                               "check-site.mjs")).read()
check("read-only: the scanner never clicks, types or submits",
      not any(w in _check_src for w in (".click(", ".fill(", ".type(",
                                        ".press(", "selectOption")))
check("no credentials of any kind are read",
      "process.env" not in _check_src.replace("process.env.PLAYWRIGHT_CHROMIUM_PATH", ""))
check("the browser path is not hardcoded to one machine",
      "PLAYWRIGHT_CHROMIUM_PATH" in _check_src)
check("the sweep requires an explicit UTC stamp, since run identity comes from "
      "the filename",
      "--stamp is required" in _sweep_src)
check("a failed scan is retried once, and the retry is recorded rather than "
      "hidden",
      "retried" in _sweep_src)
check("a navigation that did not throw is not treated as a site that was seen: "
      "the sweep requires a 2xx",
      "twoXX" in _sweep_code and "httpBlocked" in _sweep_code)
check("the consent-related script srcs are kept, so 'no CMP' and 'a CMP we do "
      "not recognise' stay distinguishable",
      "cmpScripts" in _sweep_code)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
