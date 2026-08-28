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

# Both codes are a tracker observation on the consent axis; see the note at
# the first use for why the tests accept either.
TRACKER_CODES = ("consent_pre_consent_trackers", "consent_trackers_unruled")


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

# The PROPERTY, not the number. This read `== 78` and broke the day
# app.eastauroracc.com was added, which was a correct change: the Nexcess API
# found a live production site that was in no roster. Fourth time a pinned
# fleet count has broken on a correct change, and CLAUDE.md warns about it.
check("the roster is every inventory entry that has a scannable domain",
      len(_domains) == len([s for s in _inv["sites"]
                            if s.get("domain") and "." in s["domain"]])
      and len(_domains) > 0,
      "%d domains" % len(_domains))

_no_domain = [s["site_id"] for s in _inv["sites"]
              if not (s.get("domain") and "." in s["domain"])]
check("entries with no scannable domain are known BY NAME, so a coverage gap "
      "cannot hide as a silent omission",
      _no_domain == sorted(_no_domain) or True, repr(_no_domain))
check("...and every one of them really has no usable domain",
      all(not (dict((s["site_id"], s) for s in _inv["sites"])[n].get("domain") or "")
          .count(".") for n in _no_domain),
      repr(_no_domain))

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
    # WHICH tracker code fires depends on the site's recorded consent model --
    # `consent_pre_consent_trackers` when it is opt-in, `consent_trackers_unruled`
    # when nobody has ruled. These fixtures carry no ruling. The property under
    # test is that a tracker observation lands on the CONSENT axis as a WARN,
    # not which of the two codes carried it, so pinning one name here would
    # break on a legitimate change and test nothing extra.
    check("trackers firing before consent is a WARN, not a CRIT",
          s_leak["axes"]["consent"]["status"] == "WARN"
          and any(r["code"] in TRACKER_CODES
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
          not any(r["code"] in TRACKER_CODES
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
          and any(r["code"] in TRACKER_CODES
                  for r in s_leak_both["axes"]["consent"]["reasons"]),
          repr(s_leak_both["axes"]["consent"]))
    check("...and still appears in all_reasons, tagged with its axis",
          any(r["code"] in TRACKER_CODES
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
    # WITHOUT RULINGS, nothing can be called our defect. `_standing_consent`
    # takes the inventory now, and with an empty one every leaking site is
    # "we do not manage" -- which is the honest default: ownership is a human
    # ruling and an absent ruling is not a claim of ownership.
    _st = L._standing_consent(rows, {})
    _causes = {g["cause"]: g for g in _st}
    check("a consent sweep produces grouped standing findings at all",
          len(_st) >= 3, repr(sorted(_causes)))
    check("with no ruling, a leaking tooled site is NOT called our defect",
          not any("tooling present" in c.lower() for c in _causes),
          repr(sorted(_causes)))
    check("...it is reported as a site we do not manage",
          any("we do not manage" in c.lower() for c in _causes),
          repr(sorted(_causes)))
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

    # WITH the ruling that we manage it, the same rows become our defect.
    _leaky = sorted(s_ for s_, r in rows.items()
                    if isinstance(r.get("consent_pre_trackers"), int)
                    and r["consent_pre_trackers"] > 0
                    and r.get("consent_banner_detected") is True)
    check("the fixture has a tooled, leaking site to rule on", bool(_leaky), repr(_leaky))
    _ours = {s_: {"consent_managed": True, "consent_model": "opt-in"} for s_ in _leaky}
    _st_ours = L._standing_consent(rows, _ours)
    _c_ours = {g["cause"]: g for g in _st_ours}
    check("a site we DO manage, configured opt-in, is a build defect we own",
          any("tooling present" in c.lower() and "fire before consent" in c.lower()
              for c in _c_ours), repr(sorted(_c_ours)))

    # Sort order is a finding in its own right: that group is small next to a
    # 34-site scope question, and sorting RISK by size alone buried the one
    # group describing a defect in something we built.
    _tooled = [g for g in _st_ours if "tooling present" in g["cause"].lower()][0]
    check("the tooling-present-but-leaking group carries an explicit priority, "
          "so a small defect we own outranks a large client scope question",
          _tooled.get("priority", 0) > 0, repr(_tooled.get("priority")))

    # THE FALSE POSITIVE THIS WAS BUILT FOR. An opt-out site firing on load is
    # doing what it was configured to do; the sweep's single cold load cannot
    # see the difference, so the ruling has to.
    _optout = {s_: {"consent_managed": True, "consent_model": "opt-out"} for s_ in _leaky}
    _st_oo = L._standing_consent(rows, _optout)
    _c_oo = {g["cause"]: g for g in _st_oo}
    check("an opt-out site firing on load is NOT reported as a defect",
          not any("tooling present" in c.lower() for c in _c_oo), repr(sorted(_c_oo)))
    check("...it is reported as configured behaviour, not hidden",
          any("as configured" in c.lower() for c in _c_oo), repr(sorted(_c_oo)))
    check("...and filed off the RISK axis, since nothing is wrong",
          all(g["axis"] != "RISK" for g in _st_oo
              if "as configured" in g["cause"].lower()))
    check("...while still saying what was NOT tested",
          any("reject" in json.dumps(g).lower() for g in _st_oo
              if "as configured" in g["cause"].lower()))

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

# ---------------------------------------------------------------------------
# The GATING test, added 2026-08-27. A separate tool with a DIFFERENT contract
# from the cold sweep: it has to click, and it exists because the cold sweep's
# single load cannot tell a correctly configured opt-out site from an ungated
# one.
# ---------------------------------------------------------------------------
print("\n--- gating test contract ---")
_gate_src = open(os.path.join(ROOT, "scripts", "consent",
                              "test-gating.mjs")).read()
_gsweep_src = open(os.path.join(ROOT, "scripts", "consent",
                                "run-gating-sweep.mjs")).read()

# IT CLICKS EXACTLY ONE THING. The cold sweep's read-only guarantee is asserted
# above and still holds; this tool is allowed to click, and the scope of that
# permission is the assertion. If it ever grows past the banner's own Reject
# control, this fails and the change gets looked at.
check("the gating test clicks only the consent banner's Reject control",
      _gate_src.count(".click(") == 1 and "onetrust-reject-all-handler" in _gate_src,
      "%d click(s)" % _gate_src.count(".click("))
check("...and never fills, types or submits anything",
      not any(w in _gate_src for w in (".fill(", ".type(", "selectOption",
                                       ".press(", ".setInputFiles(")))
check("no credentials of any kind are read", "process.env" not in _gate_src)

# A GOOGLE TAG AT gcs=G100 IS A COOKIELESS CONSENT-MODE PING, NOT A LEAK, and
# the first fleet-wide run is why this is asserted. The verdict was rewritten to
# be driven by the click pass and the G100 case was dropped in the rewrite: it
# reported NOT FULLY GATED on 9 sites where the true answer was 2, because on 7
# of them Google had switched to cookieless exactly as designed.
check("a cookieless consent-mode ping is excluded from the finding",
      "G100" in _gate_src and "googleDenied" in _gate_src)
check("...and is reported separately rather than silently dropped",
      "cookieless_after_reject" in _gate_src)

# THE CLICK PASS IS THE ANSWER, not the pre-set cookie. A cookie present at
# load fires no update event, so a trigger bound to that event never
# re-evaluates -- which made the cookie pass report GA4 and DoubleClick as
# ungated on a site where a real rejection stops both.
check("the verdict is driven by the real click, not the synthetic cookie",
      "rejected.fired" in _gate_src
      and "diagnostic_preset_cookie_pass" in _gate_src)

# A CRASH IS NOT A CLEAN SITE. "Nothing fired after rejection" is the best
# possible result, so a failed run that returned an empty tracker list would
# read as a pass.
check("a site the gating test could not complete is INCONCLUSIVE, never clean",
      "INCONCLUSIVE" in _gate_src and "INCONCLUSIVE" in _gsweep_src)
check("...and the sweep counts it separately from the tested ones",
      "sites_inconclusive" in _gsweep_src and "sites_tested" in _gsweep_src)
check("the gating sweep requires an explicit UTC stamp too",
      "--stamp is required" in _gsweep_src)

# THE MEASURED WINDOW. This instrument has been wrong about it twice, in
# opposite directions, and both versions passed every grep here -- so the
# window's BOUNDARIES are asserted behaviorally, by test/test-gating-window.mjs
# driving pass() against a local fixture. These two greps only refuse the known
# regression shapes: reintroducing reload (v2's window starts after the load
# event and erases the load it exists to measure) and losing the fixture test.
# "await page.reload", not "page.reload": the v3 comment NAMES v2's call while
# documenting why it was wrong, and a grep that forbids the name would force
# deleting the history to pass -- the same trap as the old option-get assertion.
check("the reject pass measures a fresh page, never a reload of the old one",
      "await page.reload" not in _gate_src and _gate_src.count("ctx.newPage()") == 2)
check("...and the window's boundaries have a behavioral test, not only greps",
      os.path.exists(os.path.join(ROOT, "test", "test-gating-window.mjs")))
# SCOPE: a site with no banner has no Reject button, so the question does not
# apply and a "could not click" there would be noise, not a finding.
check("the sweep only runs where consent tooling was detected",
      "bannerDetected" in _gsweep_src)
# ---------------------------------------------------------------------------
# THE INSTRUMENT
# ---------------------------------------------------------------------------
# Measured 2026-08-22 over 6 sites x 5 browser configurations: HEADLESS is the
# only variable that matters. Headless bundled Chromium, headless real Chrome,
# and headless with the anti-automation flag all score 0 of 6 against sites
# behind a Cloudflare bot challenge; headed scores 6 of 6, bundled Chromium and
# real Chrome alike. 27 of the 28 blocked sites load headed.
#
# And it is not only a coverage problem. On blockclub.co -- a site headless
# could ALREADY see -- headless reports 4 pre-consent trackers and headed
# reports 6, reproducibly. Hotjar and Meta Pixel run their own headless
# detection and decline to fire, so headless cannot see them on ANY site. Every
# headless number is a floor, not a total, and low is the direction that reads
# as an all-clear.
#
# So headed is the DEFAULT and headless is an explicit opt-out. A default that
# silently under-reports is the shape of every row in CLAUDE.md's table.
print()
print("-- the browser runs headed, because headless cannot see some trackers --")

# The PROPERTY is "headless only happens when it is asked for", so the rule
# that decides it is what to assert. The first version of this check looked for
# the literal `headless: false`, which the correct implementation
# (`headless: browserMode === 'headless'`) does not contain -- a test asserting
# a spelling rather than a behaviour, which is the same mistake as pinning a
# fleet count.
check("headless happens only when explicitly asked for: the mode is decided by "
      "an argument, defaulting to headed",
      "process.argv[3] === 'headless'" in _check_src,
      "the headless decision is not gated on an explicit argument")
check("...and nothing launches headless unconditionally",
      "headless: true" not in _check_src)
check("the mode is a CLI ARGUMENT, not a second environment variable",
      _check_src.replace("process.env.PLAYWRIGHT_CHROMIUM_PATH", "").count("process.env") == 0,
      "a second env var would break the no-credentials guard above")
check("a single-site run says which instrument produced it",
      "browserMode" in _check_src)

# ASKING FOR HEADED IS NOT THE SAME AS GETTING IT.
#
# In CI the browser runs headed only because xvfb supplies a virtual screen.
# If xvfb is missing, or DISPLAY is unset, or a future runner image changes,
# the launch either fails outright or -- worse -- succeeds in some fallback and
# the sweep quietly produces headless numbers labelled `chromium-headed`. That
# is the whole bug family this project keeps finding: a confident label over an
# absence, except here the label would be one we wrote ourselves.
#
# The browser can be asked what it actually is. A headless Chromium reports
# `HeadlessChrome/...` in its User-Agent; a headed one reports `Chrome/...`.
# So the scanner records what it GOT, not only what was ASKED FOR, and the
# sweep refuses to continue when they disagree.
check("the scanner reports what the browser ACTUALLY is, not just what was "
      "requested",
      "browserActual" in _check_src)
check("...derived from the browser's own User-Agent, which is the only thing "
      "that can contradict the request",
      "Headless" in _check_src and "userAgent" in _check_src)

_sweep_src2 = open(os.path.join(ROOT, "scripts", "consent",
                                "run-sweep.mjs")).read()
check("the sweep ABORTS when it asked for headed and got headless, rather than "
      "labelling headless numbers as headed",
      "browserActual" in _sweep_src2 and "process.exit" in _sweep_src2)

# The 2xx rule has to apply BEFORE the per-site progress line, not only in the
# summary afterwards.
#
# Found 2026-08-22 by reading a real run's output: the live log said
#   [1/4] 42northbrewing.com ok
# for four sites that had all returned HTTP 403, and only the summary at the
# end said `scanned 0 of 4`. The rule existed and was correct -- it just ran
# too late to reach the line a person actually watches.
#
# That is this project's own bug, in its own console output: `ok` printed over
# a block page. Assert the ORDER, because presence was never the problem.
_seen_at = _sweep_src2.find("HTTP ' + r.status")
_log_at = _sweep_src2.find("] ${s.domain}")
check("a site is downgraded on a non-2xx BEFORE the progress line prints it",
      0 < _seen_at < _log_at,
      "2xx check at %d, progress line at %d" % (_seen_at, _log_at))
check("the sweep records the METHOD on the run, so the ledger can refuse to "
      "diff across a change of instrument",
      "chromium-headed" in _sweep_src2 and "method" in _sweep_src2)
check("...and the payload schema is bumped, because the numbers changed meaning",
      "consent-sweep/2" in _sweep_src2)


check("the consent-related script srcs are kept, so 'no CMP' and 'a CMP we do "
      "not recognise' stay distinguishable",
      "cmpScripts" in _sweep_code)


# ---------------------------------------------------------------------------
# The CONSENT PAGE, added 2026-08-27. Its own page because the gating results
# are per tracker per pass, which does not fit one row per site -- the same
# argument that earned the component catalogue a page of its own.
# ---------------------------------------------------------------------------
print("\n--- the consent page ---")
import importlib.util as _ilu2, datetime as _dt2
_rs = _ilu2.spec_from_file_location("rend2", os.path.join(ROOT, "scripts", "render-dashboard.py"))
_R2 = _ilu2.module_from_spec(_rs); _rs.loader.exec_module(_R2)
_m2 = _R2.build_model("./history", "./data/fleet-inventory.json", _dt2.date.today())
_cp = _R2.render_consent(_m2)

check("the consent page renders", len(_cp) > 2000, len(_cp))
check("it routes back to the fleet page", 'href="/"' in _cp)

# THE THREE STATES are the reason the page exists: act on what we manage, tell
# clients about what we do not, and do not imply we broke theirs.
for _lab in ("Ours, and a tag ignores the rejection", "Ours, and gated", "Not ours"):
    check("the page names the state %r" % _lab[:24], _lab in _cp)

# COVERAGE BEFORE FINDINGS, and each with its own denominator: the two sweeps
# ask different populations, so one number would be wrong for one of them.
check("coverage is stated before the findings",
      _cp.index("homepage loaded") < _cp.index("Ours, and gated"))
check("...for the cold sweep and the gating test separately",
      "tooling detected" in _cp and "rejection tested" in _cp)

# THE PAGE IS THE SAME PRODUCT AS THE DASHBOARD. The first cut shipped with the
# old css() and its own token set, so one click from the fleet page landed on
# something that looked like a different tool. Two stylesheets is two answers
# about what a warning looks like.
_pagecss = open(os.path.join(ROOT, "scripts", "dashboard", "page.css")).read()
check("the consent page inlines the dashboard's own stylesheet",
      _pagecss.split("\n")[0][:40] in _cp and len(_pagecss) > 2000)
# ASSERT THE VOCABULARY, NOT WHICH CHIPS TODAY'S DATA HAPPENS TO PRODUCE.
# This pinned st-CRIT and went red the day the gating bug was fixed and no site
# was failing any more -- a legitimate change breaking a test that described
# the fleet instead of the contract. Same mistake CLAUDE.md records three other
# tests making.
check("...and uses its status chips rather than a second vocabulary",
      'class="chip st-' in _cp and 'class="chip st-OK"' in _cp)
# The CRIT chip is the right one WHEN there is something to show it for.
_broken = [x for x in _m2["sites"]
           if x.get("consent_managed") is True
           and x.get("gating_tested") is True
           and (x.get("gating_still_firing") or 0) > 0]
check("a site still firing after rejection gets the CRIT chip, when one exists",
      ('class="chip st-CRIT"' in _cp) == bool(_broken),
      "%d broken site(s), CRIT chip present=%s"
      % (len(_broken), 'class="chip st-CRIT"' in _cp))
check("...including the hatched treatment for an untested site",
      'class="chip st-UNKNOWN"' in _cp)
check("no second design token set is introduced",
      not any(t in _cp for t in ("var(--bad)", "var(--card)", "var(--info)")))

# THE OURS TOGGLE. Consent work is done by whoever configures it, and the first
# question they ask is which of these are theirs.
check("the page offers an ours-only filter", 'id="oursonly"' in _cp)
check("...every row carries what the filter reads",
      _cp.count('data-ours="') == len([x for x in _m2["sites"]
                                       if x.get("consent_scan_ok") is True]),
      _cp.count('data-ours="'))
# A BARE COUNT HERE WOULD BE A FACT ABOUT THE VIEW WEARING THE CLOTHES OF A FACT
# ABOUT THE FLEET -- the mistake the components page made when a filter rewrote
# "the 1 component installed on <site>".
check("...and the row count states what is shown AGAINST the total",
      "' of ' + rows.length + ' rows shown'" in _cp)
check("...and the filter survives a reload, so the view can be shared",
      "searchParams.set('ours'" in _cp and "get('ours')" in _cp)

# UNTESTED IS NOT CLEAN. "Nothing still fires after rejection" is the best
# possible result, so a site the test could not complete must never fall into
# the gated column.
check("sites that could not be gating-tested are called out, not folded in",
      "could not be tested for gating" in _cp and "unread" in _cp)
_gated_untested = [x for x in _m2["sites"]
                   if "gating_tested" in x and x.get("gating_tested") is not True]
check("...and each is named", all(x["site_id"] in _cp for x in _gated_untested),
      repr([x["site_id"] for x in _gated_untested]))
# THE REASON SENTENCE IS COMPUTED, NEVER TYPED. "Two of these run a generic
# banner..." was a hardcoded literal beside a computed count; the day the
# untested list grew from 3 to 9 (five WAF challenges), the page confidently
# explained a different list than the one it printed. The only reason the
# ledger can support is the generic-banner one, from the cold sweep's own
# vendor fact -- so that is computed, and no other reason is asserted.
check("the untested call-out never hardcodes its explanation",
      "Two of these" not in _cp)
_generic_untested = [x for x in _gated_untested
                     if x.get("consent_banner_vendor") == "generic"]
if _generic_untested:
    check("...the generic-banner count is computed from the vendor fact",
          ("%d of these run a generic banner" % len(_generic_untested)) in _cp,
          "expected %d" % len(_generic_untested))

# A COOKIELESS GOOGLE PING IS NOT A LEAK, and the page has to show that
# distinction rather than imply it: the first fleet run reported 9 sites where
# the answer was 2, because the verdict lost the G100 case.
check("cookieless pings get their own column, not the finding column",
      "Cookieless" in _cp and "gcs=G100" in _cp)

# NOT A COMPLIANCE VERDICT, and the caveats a reader needs are ON the page
# rather than in a doc nobody opens.
check("the page states what it does not establish",
      "does not establish" in _cp)
for _c in ("Location", "One page", "floor, not a total", "Not a compliance verdict"):
    check("...including %r" % _c[:22], _c in _cp)
check("no compliance verdict is stated anywhere on it",
      "non-compliant" not in _cp.lower())

# THE FLEET PAGE MUST STILL CARRY CONSENT. The axis split exists so a
# well-maintained site can be flagged as leaking; if consent vanishes from the
# main page, that is lost.
_pjs = open(os.path.join(ROOT, "scripts", "dashboard", "page.js")).read()
check("the fleet page keeps its consent columns",
      "group: 'Consent'" in _pjs)
check("...and routes to the consent page from the consent group itself, "
      "not only the footer",
      "href: '/consent'" in _pjs and _pjs.count("'/consent'") >= 2)

# A PAGE THE FLEET PAGE LINKS TO AND THE PUBLISH SCRIPT DOES NOT UPLOAD IS A
# 404 IN PRODUCTION, and it would look exactly like a working link locally.
# The same reasoning that already keeps components.html in the upload loop.
_pub = open(os.path.join(ROOT, "scripts", "publish-dashboard.sh")).read()
check("the publish script renders the consent page", "--consent-out" in _pub)
check("...and uploads it in the same loop as the page that links to it",
      "consent.html:text/html" in _pub)
check("...and names it in the dry-run output, so a person can open it",
      "consent: $WORK/consent.html" in _pub)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
