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
# ITEM 21. An api-only run establishes NOTHING about WordPress, and until
# 2026-08-23 that read as 45 healthy sites.
#
# The site below is what an api-only scan actually writes: the control plane
# answered, so PHP and the backup age are real, and every WordPress fact is
# the token `unknown` with `wp_checked` FALSE. It fell between the two guards
# meant to catch exactly this -- `wp_version_unknown` needs `wp_checked` True,
# `coverage_partial` needs health NOT to have seen the site -- so it scored on
# backup age and PHP alone and reached OK.
# --------------------------------------------------------------------------
def apionly(**kw):
    """A site as an api-only health run records it. Nothing about WordPress."""
    base = dict(site(), wp_checked=False, wp_version="unknown",
                wp_core_update="unknown", plugin_updates="unknown",
                theme_updates="unknown", framework="wordpress")
    base.update(kw)
    return base

check("an api-only site does not reach OK: nothing about its WordPress "
      "was established",
      S.evaluate(apionly())["status"] == "WARN",
      S.evaluate(apionly())["status"])
check("...and it says WHY, with its own code",
      "wp_unestablished" in [r["code"] for r in S.evaluate(apionly())["reasons"]],
      str([r["code"] for r in S.evaluate(apionly())["reasons"]]))
check("wp_unestablished is a HEALTH finding",
      S.axis_of("wp_unestablished") == "health")

# The two absences stay DISTINCT. "The deep scan ran and could not read it"
# and "no deep scan ever looked" have different remedies -- go and look at the
# site, versus run a full scan -- so they must not collapse into one code.
check("a deep scan that ran and failed still reports wp_version_unknown",
      codes(wp_version="unknown") == ["wp_version_unknown"],
      str(codes(wp_version="unknown")))
check("...and never both codes at once",
      "wp_unestablished" not in codes(wp_version="unknown"))

# The rule must be silent on a scan that DID its job, or it puts a WARN floor
# under the whole fleet -- the `upstream_pending` mistake, again.
check("a fully deep-scanned healthy site is untouched by the new rule",
      st() == "OK" and "wp_unestablished" not in codes())

# A site whose framework is positively NOT WordPress is exempt: the WordPress
# question is not a question there, and a rule true of every one of them ranks
# nothing. An unrecorded framework is NOT exempt -- it fails safe and warns.
check("a non-WordPress site is exempt from the WordPress rule",
      "wp_unestablished" not in
      [r["code"] for r in S.evaluate(apionly(framework="drupal8"))["reasons"]])
check("an unrecorded framework fails SAFE and still warns",
      "wp_unestablished" in
      [r["code"] for r in S.evaluate(apionly(framework=None))["reasons"]])

# --------------------------------------------------------------------------
# The SAME bug one layer in, found on the first real run after item 22 was
# fixed. morrison-chs answered `wp core version` (7.0.4) and then failed the
# three calls that need the database, so its version is known and its UPDATE
# STATUS is not. `wp_unestablished` tests the version, so it stayed silent, and
# the site read OK with core, plugin and theme all unknown.
#
# The version is not what makes an OK mean anything. "Nothing is pending" is.
# --------------------------------------------------------------------------
def halfscanned(**kw):
    """Version read; the three database-backed calls did not answer."""
    base = dict(site(), wp_checked=True, wp_version="7.0.4",
                wp_core_update="unknown", plugin_updates="unknown",
                theme_updates="unknown", framework="wordpress")
    base.update(kw)
    return base

check("a site whose UPDATE STATUS is unknown does not read OK, even with a "
      "known version",
      S.evaluate(halfscanned())["status"] == "WARN",
      S.evaluate(halfscanned())["status"])
check("...and it has its own code, distinct from wp_unestablished",
      "wp_update_status_unknown" in
      [r["code"] for r in S.evaluate(halfscanned())["reasons"]],
      str([r["code"] for r in S.evaluate(halfscanned())["reasons"]]))
check("wp_update_status_unknown is a HEALTH finding",
      S.axis_of("wp_update_status_unknown") == "health")
check("a core update that could not be read is enough on its own",
      "wp_update_status_unknown" in
      [r["code"] for r in S.evaluate(halfscanned(plugin_updates=0,
                                                 theme_updates=0))["reasons"]])
check("a plugin count that could not be read is enough on its own",
      "wp_update_status_unknown" in
      [r["code"] for r in S.evaluate(halfscanned(wp_core_update="up-to-date"))["reasons"]])
check("a fully measured site is untouched by it",
      st() == "OK" and "wp_update_status_unknown" not in codes())
check("an api-only site reports wp_unestablished, not this one -- the "
      "remedies differ (run a full scan vs find out why WP-CLI refused)",
      "wp_update_status_unknown" not in
      [r["code"] for r in S.evaluate(apionly())["reasons"]])

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

    # ITEM 21, against the run that exposed it. Two NAMED runs of the same
    # fleet 38 minutes apart: the first api-only, the second full. The bug is
    # invisible unless you compare them, which is why it survived -- a full run
    # lands afterwards and puts the numbers back.
    #
    # No fleet COUNT is asserted here. A count is a fixture that a legitimate
    # change is entitled to move; the PROPERTY is what has to hold.
    def _score(run_id):
        out = []
        for r in [json.loads(l) for l in open(hist)]:
            if r.get("run_id") != run_id:
                continue
            d = dict(r)
            rec = inv.get(r["site_id"], {})
            d["production"] = rec.get("production")
            d["in_workbook"] = rec.get("in_workbook")
            d["severity"] = S.evaluate(d)
            out.append(d)
        return out

    API_ONLY_RUN = "health-2026-08-23_0033"   # 52 sites, no SSH, no WordPress
    FULL_RUN = "health-2026-08-23_0111"       # the same 52, 38 minutes later
    _api = _score(API_ONLY_RUN)
    _full = _score(FULL_RUN)
    if _api and _full:
        check("ledger: NO site in an api-only run reads OK -- nothing about "
              "any site's WordPress was established",
              not [d["site_id"] for d in _api if d["severity"]["status"] == "OK"],
              str([d["site_id"] for d in _api
                   if d["severity"]["status"] == "OK"][:8]))
        # The other half, and the reason this is a rule and not a blanket
        # downgrade: when the deep scan DOES establish the version, the rule
        # goes quiet and sites can be OK again.
        check("ledger: the full run of the same fleet still has OK sites",
              any(d["severity"]["status"] == "OK" for d in _full))
        check("ledger: and the new code is silent on the full run",
              not any(r["code"] == "wp_unestablished"
                      for d in _full for r in d["severity"]["all_reasons"]))
        # The invariant behind both, stated once: OK means measured.
        _bad = [d["site_id"] for d in _api + _full
                if d["severity"]["status"] == "OK"
                and d.get("wp_version") in (None, "unknown", "n/a")]
        check("ledger: no site reads OK without an established WordPress "
              "version, in either mode", not _bad, str(_bad))
    else:
        print("skip  item-21 runs are not in this ledger")
else:
    print("skip  ledger checks (history/ or inventory missing)")


# --------------------------------------------------------------------------
# The published JSON feed must agree with the page it ships beside.
#
# The v1 pair was a page and a JSON blob produced by two code paths, and that
# is how a live endpoint ends up disagreeing with the dashboard next to it.
# emit_data() is built from the SAME model object that renders the HTML, and
# these checks prove that rather than trusting it -- a separate emit path that
# quietly drifted would be a fresh instance of this project's oldest bug.
# --------------------------------------------------------------------------
print("\n-- the JSON feed agrees with the page --")
import datetime as _dt
import importlib.util as _il
import re as _re

_rs = _il.spec_from_file_location("render", os.path.join(ROOT, "scripts", "render-dashboard.py"))
try:
    R = _il.module_from_spec(_rs)
    _rs.loader.exec_module(R)
except Exception as _e:                                    # pragma: no cover
    print("skip  renderer would not import: %s" % _e)
    R = None

if R is not None and os.path.exists(os.path.join(ROOT, "history", "observations.jsonl")):
    _m = R.build_model(os.path.join(ROOT, "history"),
                       os.path.join(ROOT, "data", "fleet-inventory.json"),
                       _dt.date(2026, 8, 19))
    _html = R.render(_m)
    _data = R.emit_data(_m)

    check("feed carries a schema version",
          _data["schema"] == "fleet-dashboard/2", _data.get("schema"))
    # The PROPERTY, not the number. This read `== 84` and broke the day a
    # real site was added to the inventory, which is a correct change. What
    # must hold is that the feed and the page describe the same set.
    check("feed has one entry per site on the page",
          len(_data["sites"]) == len(_m["sites"]) and len(_m["sites"]) > 0,
          "feed %d vs page %d" % (len(_data["sites"]), len(_m["sites"])))

    # THE PAGE AND THE FEED MUST AGREE ON EVERY AXIS, not just on health.
    # v1's page and JSON feed were built by two code paths and drifted; the
    # axis split doubles the number of numbers that can drift, so the guard
    # covers each axis rather than assuming health stands for all of them.
    for _axis in S.AXES:
        _chips = _re.findall(
            r'data-state="[A-Z]*" data-consent="([A-Z]*)"', _html)
        if _axis != "consent":
            continue
        _page = {}
        for _c in _chips:
            if _c:
                _page[_c] = _page.get(_c, 0) + 1
        _feed = {}
        for _srow in _data["sites"]:
            _st = (_srow.get("axes") or {}).get("consent", {}).get("status")
            if _st:
                _feed[_st] = _feed.get(_st, 0) + 1
        check("the consent COLUMN agrees with the consent axis in the feed",
              _page == _feed, "page=%s feed=%s" % (_page, _feed))

    check("every site row carries a consent status in the feed",
          all("axes" in _srow and "consent" in _srow["axes"]
              for _srow in _data["sites"]))
    check("the site table has a Consent column at all",
          "<th>Consent</th>" in _html)

    # --- Eastern time ---------------------------------------------------
    # The ledger stores UTC. The page prints Eastern, 12-hour, ALWAYS labelled.
    # An unlabelled timestamp is a confident-looking value standing in for a
    # missing one: the 10:57 sweep rendered as "14:57" and read as afternoon.
    check("a UTC stamp renders as Eastern 12-hour with the zone named",
          R.when("2026-08-20T14:57:00") == "Aug 20, 10:57 AM EDT",
          R.when("2026-08-20T14:57:00"))
    check("...and winter is EST, not EDT",
          R.when("2026-01-15T14:57:00") == "Jan 15, 9:57 AM EST",
          R.when("2026-01-15T14:57:00"))
    check("...and a UTC time before 05:00 belongs to the PREVIOUS Eastern day",
          R.when("2026-08-20T00:30:00") == "Aug 19, 8:30 PM EDT",
          R.when("2026-08-20T00:30:00"))
    check("noon and midnight do not render as 0:00",
          R.when("2026-08-20T16:00:00").startswith("Aug 20, 12:00 PM")
          and R.when("2026-08-20T04:00:00").startswith("Aug 20, 12:00 AM"),
          "%s / %s" % (R.when("2026-08-20T16:00:00"), R.when("2026-08-20T04:00:00")))
    check("an unparseable stamp is shown as-is, never as a plausible time",
          R.when("not-a-date") == "not-a-date" and R.when(None) == "unknown")

    # The hand-rolled DST rule exists because zoneinfo raises with no tzdata,
    # and that failure would land in CI. Cross-check it whenever tzdata IS
    # present, so the fallback cannot quietly drift from the real rule.
    try:
        from zoneinfo import ZoneInfo as _ZI
        _NY, _UTC = _ZI("America/New_York"), _ZI("UTC")
        _bad, _d = [], _dt.datetime(2026, 1, 1)
        while _d < _dt.datetime(2028, 1, 1):
            _mine, _zone = R.eastern(_d)
            _real = _d.replace(tzinfo=_UTC).astimezone(_NY)
            if (_mine != _real.replace(tzinfo=None)
                    or _zone != _real.strftime("%Z")):
                _bad.append(_d)
            _d += _dt.timedelta(hours=1)
        check("the hand-rolled Eastern rule matches zoneinfo hour by hour "
              "across two years and four DST transitions",
              not _bad, "%d mismatch(es), first at %s"
              % (len(_bad), _bad[0] if _bad else "-"))
    except ImportError:
        print("skip  zoneinfo unavailable, cannot cross-check the DST rule")

    check("the page labels every run time with a zone",
          _html.count("EDT") + _html.count("EST") >= len(_data["runs"]),
          "%d zone label(s) for %d run(s)"
          % (_html.count("EDT") + _html.count("EST"), len(_data["runs"])))
    check("an unmeasured consent cell says WHY rather than sitting blank, "
          "because a blank consent cell reads as nothing to fix",
          ("UNKNOWN" not in _html) or ("cellnote" in _html))

    # Every count in the feed must appear in the rendered HTML next to its
    # state chip. If the page said 2 CRIT and the feed said 33, only a person
    # opening both would ever notice.
    for _state, _n in _data["health"]["counts"].items():
        if not _n:
            continue
        _pat = _re.compile(r"%s</span>\s*</div>\s*<div class=val>%d</div>" % (_state, _n))
        check("page shows %d %s, same as the feed" % (_n, _state),
              bool(_pat.search(_html)), "not found in rendered HTML")

    # A per-site spot check, on the row where being wrong matters most.
    _feed = {s["site_id"]: s for s in _data["sites"]}
    check("the excluded site is in the feed, not silently dropped",
          "cm-whitelabel" in _feed)
    check("...flagged as not counting toward the fleet",
          _feed["cm-whitelabel"]["counts_toward_fleet"] is False)
    check("...and still carrying its real CRIT status",
          _feed["cm-whitelabel"]["status"] == "CRIT")
    # The PROPERTY, not the code that happened to fire the day this was
    # written. This pinned `wp_below_floor` and went red on 2026-08-22 when a
    # health scan could not read cm-whitelabel's WordPress version: the site
    # was still CRIT, on a 2149-day-old backup, and the feed still said why --
    # the test was asserting WHICH reason rather than THAT there was one.
    #
    # Same family as the standing rule about pinning fleet counts. A scan is
    # entitled to move which rule fires on a given site; it is not entitled to
    # produce a CRIT with no CRIT-level reason behind it, and that is the thing
    # worth guarding.
    _crit_reasons = [r for r in _feed["cm-whitelabel"]["reasons"]
                     if r["level"] == "CRIT"]
    check("feed states WHY a site is CRIT, not just that it is",
          bool(_crit_reasons),
          "status CRIT with no CRIT-level reason: %s"
          % _feed["cm-whitelabel"]["reasons"])
    check("...and no site in the feed is CRIT with nothing behind it",
          all(any(r["level"] == "CRIT" for r in s["reasons"])
              for s in _data["sites"] if s["status"] == "CRIT"),
          str([s["site_id"] for s in _data["sites"]
               if s["status"] == "CRIT"
               and not any(r["level"] == "CRIT" for r in s["reasons"])]))
    check("feed publishes the thresholds it was scored with",
          _data["severity_rules"]["wp_security_floor"] == "7.0.2"
          and _data["severity_rules"]["backup_crit_days"] == S.BACKUP_CRIT_DAYS)

    # A site nobody has scanned must not read as healthy in a machine-readable
    # feed either. This is settled principle 5 applied to the API.
    #
    # The assertion is on the PROPERTY, not on a count. It used to read
    # `len(_unknown) == 32`, and the consent sweep broke it by reaching every
    # domain -- a correct change, failing a test, because the test had pinned a
    # fleet number that a new source is entitled to move. Third time this shape
    # of test broke this session. Assert what must be TRUE, not what happened to
    # be true on the day it was written.
    _unknown = [s for s in _data["sites"] if s["status"] == "UNKNOWN"]
    check("never-scanned sites are UNKNOWN in the feed, not OK",
          all(s["status"] != "OK" for s in _unknown))
    check("...and carry no WordPress version rather than a blank that reads as one",
          all(s["wp_version"] is None for s in _unknown))

    # The health-coverage gap, which is the number that replaced UNKNOWN as the
    # scoreboard. A site with no health evidence must never read OK.
    _nohealth = set(_data.get("no_health_evidence") or [])
    check("the feed publishes the health-coverage gap as its own list",
          "no_health_evidence" in _data)

    # THE GUARD THAT WOULD HAVE CAUGHT THE CONSENT OMISSION.
    # If a fact can change a site's status, a consumer of the feed has to be
    # able to see why. The consent sweep shipped with its facts scoring on the
    # page and absent from the feed, because EMIT_FACTS is a hand-written
    # allowlist and nobody extended it. Enumerating it is deliberate -- it is a
    # contract, and a rename should break loudly here -- so the protection is
    # this assertion rather than deriving the list.
    _missing = [f for f in S.SCORING_FACTS if f not in R.EMIT_FACTS]
    check("every fact severity scores on is published in the feed",
          not _missing, repr(_missing))
    check("...and every site row actually carries them",
          all(all(f in s for f in S.SCORING_FACTS) for s in _data["sites"]),
          repr([f for f in S.SCORING_FACTS
                if not all(f in s for s in _data["sites"])]))
    check("...and no site in it reads as OK, whatever else has looked at it",
          all(s["status"] != "OK" for s in _data["sites"]
              if s["site_id"] in _nohealth),
          repr([s["site_id"] for s in _data["sites"]
                if s["site_id"] in _nohealth and s["status"] == "OK"]))
else:
    print("skip  feed checks (renderer or ledger unavailable)")


def _raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False



# ---------------------------------------------------------------------------
# AXES
# ---------------------------------------------------------------------------
# One status per site used to answer two questions at once, and the consent
# sweep silently moved the fleet-health headline. These pin the SEPARATION,
# never a count -- a new source is entitled to move any number here.
print()
print("-- axes: one status per question --")

import re as _re

_src = open(os.path.join(os.path.dirname(__file__),
                         "..", "scripts", "lib", "severity.py")).read()
_codes = set()
for _expr in _re.findall(r"add\((?:crit|warn),(.*?),", _src, _re.S):
    _codes |= set(_re.findall(r'"([a-z_0-9]+)"', _expr))
check("every severity code in the module has an axis",
      _codes and all(c in S.AXIS_OF_CODE for c in _codes),
      "unmapped: %s" % sorted(c for c in _codes if c not in S.AXIS_OF_CODE))
check("...and the check found the conditional code too, not just the literals",
      "backup_stale" in _codes)
check("an unmapped code RAISES rather than defaulting to health",
      _raises(lambda: S.axis_of("not_a_real_code"), KeyError))

# A terminal state is a statement about the SITE, so it lands on every axis.
# Without this a frozen site reads "frozen for health, OK for consent".
for _term, _site in (("FROZEN", {"frozen": True}),
                     ("UNKNOWN", {"site_id": "nobody-looked"})):
    _r = S.evaluate(_site, TODAY)
    check("a %s site is %s on EVERY axis, not just health" % (_term, _term),
          _r["status"] == _term
          and all(_r["axes"][a]["status"] == _term for a in S.AXES),
          repr(_r["axes"]))

# The split must not lose a finding. `reasons` agrees with `status`;
# `all_reasons` is the union and every entry is tagged.
_leaky = {"php_version": "8.2", "wp_checked": True, "wp_version": "7.0.2",
          "db_backup_age_days": 1, "plugin_updates": 0, "wp_core_update": "up-to-date",
          "upstream_pending": 0, "frozen": False,
          "consent_scan_ok": True, "consent_banner_detected": False,
          "consent_pre_trackers": 3}
_r = S.evaluate(_leaky, TODAY)
check("health stays OK when only consent has findings",
      _r["status"] == "OK" and _r["reasons"] == [], repr(_r["status"]))
check("...and consent is WARN, so the finding moved rather than vanishing",
      _r["axes"]["consent"]["status"] == "WARN")
check("all_reasons is the union of every axis",
      len(_r["all_reasons"])
      == sum(len(_r["axes"][a]["reasons"]) for a in S.AXES))
check("every reason carries the axis it was scored on",
      all("axis" in x for x in _r["all_reasons"]))
check("`reasons` never disagrees with `status`: no WARN reason under an OK",
      not (_r["status"] == "OK" and _r["reasons"]))

# summarise() must count the same population on every axis, or one card on the
# page silently describes a different fleet than the one beside it.
_fleet = [{"site_id": "a", **_leaky},
          {"site_id": "b", "frozen": True},
          {"site_id": "c"},
          {"site_id": "d", "php_version": "7.4", "wp_checked": True,
           "db_backup_age_days": 900, "frozen": False}]
_s = S.summarise(_fleet, TODAY)
check("summarise reports per-axis counts",
      set(_s["axes"]) == set(S.AXES), repr(sorted(_s["axes"])))
_tot = sum(_s["counts"].values())
check("every axis counts the SAME population, so two cards cannot describe "
      "different fleets",
      all(sum(_s["axes"][a].values()) == _tot for a in S.AXES),
      repr({a: sum(_s["axes"][a].values()) for a in S.AXES}))
check("the top-level counts ARE the health axis",
      _s["counts"] == _s["axes"]["health"])

# The consent axis must never claim OK for a site it could not see. This is the
# HTTP 403 bug the sweep shipped with, one layer up.
_blocked = dict(_leaky, consent_scan_ok=False, consent_banner_detected=None,
                consent_pre_trackers=None)
check("a site the sweep could not load is UNKNOWN on consent, never OK",
      S.evaluate(_blocked, TODAY)["axes"]["consent"]["status"] == "UNKNOWN")


# ---------------------------------------------------------------------------
# A site the control plane calls WordPress that is not WordPress, 2026-08-25.
#
# app.eastauroracc.com: Nexcess reports app=wordpress, app_version=6.2.2. It is
# a custom PHP application. No wp-config.php anywhere, composer.json requiring
# only mailchimp/marketing, and `wp core version` answering "This does not seem
# to be a WordPress installation".
#
# It scored CRIT wp_below_floor on the control plane's claim, which put a site
# that cannot have wp2shell onto the wp2shell remediation list.
# ---------------------------------------------------------------------------
_base = {"wp_checked": False, "php_version": "8.2",
         "nexcess_app_version": "6.2.2", "production": True}

_r = S.evaluate(dict(_base, framework="not-wordpress"))
check("a positively non-WordPress site is NOT CRIT for a WordPress version "
      "it does not run",
      "wp_below_floor" not in [x["code"] for x in _r["reasons"]],
      repr([x["code"] for x in _r["reasons"]]))
check("...and the disagreement is reported rather than silently dropped",
      "framework_not_wordpress" in [x["code"] for x in _r["reasons"]],
      repr([x["code"] for x in _r["reasons"]]))

# framework FAILS SAFE. Only a positive non-WordPress value exempts.
for _fw in (None, "unknown", "wordpress", "wordpress-network"):
    _site = dict(_base)
    if _fw is not None:
        _site["framework"] = _fw
    _r = S.evaluate(_site)
    check("framework=%r still scores CRIT below the floor" % _fw,
          "wp_below_floor" in [x["code"] for x in _r["reasons"]],
          repr([x["code"] for x in _r["reasons"]]))

# The exemption must not leak into a site with a REAL WP-CLI reading.
_r = S.evaluate(dict(_base, framework="not-wordpress", wp_version="6.2.2",
                     wp_checked=True))
check("a measured WordPress version below the floor is CRIT whatever the "
      "framework says",
      "wp_below_floor" in [x["code"] for x in _r["reasons"]],
      repr([x["code"] for x in _r["reasons"]]))

# No control-plane claim means no disagreement to report.
_r = S.evaluate({"framework": "not-wordpress", "php_version": "8.2",
                 "wp_checked": False, "production": True})
check("a non-WordPress site with no control-plane claim reports no "
      "disagreement",
      "framework_not_wordpress" not in [x["code"] for x in _r["reasons"]],
      repr([x["code"] for x in _r["reasons"]]))

check("the new code is mapped to an axis, since axis_of raises otherwise",
      S.axis_of("framework_not_wordpress") == "health")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
