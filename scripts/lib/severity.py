#!/usr/bin/env python3
"""
Severity scoring: the single source of truth for CRIT / WARN / OK.

WHY THIS FILE EXISTS
--------------------
Until 2026-08-19 severity was computed inside `pantheon-fleet-healthcheck.sh`
at scan time and copied into the ledger as `derived_status`. Two consequences,
both bad:

1. Retuning a threshold did nothing to the observations already in history, so
   the first diff after a rules change reported every site as having changed
   with no observed fact behind it. The ledger already separates OBSERVED from
   DERIVED for exactly this reason; this file is what makes that separation
   pay off. Scoring is now a pure function of stored facts, so history rescores
   consistently and a threshold change is never mistaken for a fleet change.
2. The scanner's model was a flat OR of five conditions, and two of them broke
   against real fleet data. See below.

WHAT WAS WRONG WITH THE OLD MODEL
---------------------------------
Measured on the 2026-08-19 full-fleet run, 52 sites: **33 CRIT, 15 WARN, and
ZERO healthy.** A model where nothing is ever OK cannot rank anything.

  `upstream_pending > 0 -> WARN`
      Every single site carries 1 or 2 pending Pantheon upstream commits. Zero
      sites have none. One rule, on a fact that is never zero, put a floor of
      WARN under the entire fleet. Upstream commits are now INFORMATIONAL and
      are never a severity driver. They are still recorded and still shown.

  `core update available -> CRIT`
      32 sites are on 7.0.3 with 7.0.4 pending: one minor version behind, and
      above the wp2shell fix line. That single rule produced 32 of the 33
      CRITs. Being one behind is a maintenance backlog, not an emergency. Now
      WARN.

THE INVERSION THAT MOTIVATED THE VERSION FLOOR
----------------------------------------------
`cm-whitelabel` runs WordPress 6.9.4, BELOW the wp2shell fix, and its
`wp_core_update` reads `up-to-date`. So the core-update rule did not fire on
the one genuinely dangerous site in the fleet. It scored CRIT only because its
last backup was 2,147 days old. **Had it been backed up yesterday it would have
scored OK.**

`WP_SECURITY_FLOOR` is the rule that fixes this, and it is the only rule here
that reads the version the site is ACTUALLY ON rather than whether an update is
pending. Keep it that way.

(`cm-whitelabel` itself was ruled a temp non-public site by Doug on
2026-08-19 and carries `production: false`. The rule stays regardless: it is
the rule, not the site, that had to exist.)

UNKNOWN IS NEVER OK
-------------------
Every rule below tests for a known bad value. A fact that is absent, None, or
the literal token "unknown" fires NOTHING. That is deliberate and it is the
project's settled principle 5. A site nobody could measure must not be able to
reach OK by having no evidence against it; it reaches SKIP or UNKNOWN instead,
which say so out loud. Before adding a rule, ask what it does when the answer
is unknown, and whether a reader could take the result to mean the opposite.
"""

import datetime

# --- thresholds -------------------------------------------------------------
# All tunable policy lives here, in one block, as named constants. Changing a
# number here rescores all of history on the next render and does NOT emit a
# fleet-wide change, because the ledger classifies a derived-only move as
# RULE_CHANGE rather than TRANSITION.

# The wp2shell unauthenticated RCE fix. A site below this is exposed, full
# stop, regardless of what `core check-update` claims.
WP_SECURITY_FLOOR = (7, 0, 2)

# PHP security support, by version, as a DATE rather than a floor.
#
# This was a hardcoded `< 8.0` floor for about an hour, and rendering the page
# exposed it: "Still true" reported one site past PHP end-of-support while
# severity scored that same site fine, because 8.1 ended 31 Dec 2025 and a
# static floor could not know that. Two PHP rules in two files, disagreeing on
# the page. One table now, here, and fleet-ledger.py reads it from this module.
#
# A version absent from this table is UNKNOWN, never "supported". Adding a new
# PHP release means adding a row; forgetting to must not silently pass a site.
PHP_SECURITY_EOL = {
    "7.4": "2022-11-28",
    "8.0": "2023-11-26",
    "8.1": "2025-12-31",
    "8.2": "2026-12-31",
    "8.3": "2027-12-31",
    "8.4": "2028-12-31",
    "8.5": "2029-12-31",
}

# Inside this many days of the EOL date, a version is a planning item (WARN),
# not yet an incident. 46 sites are on 8.2, which ends 2026-12-31.
PHP_EXPIRING_DAYS = 180

BACKUP_CRIT_DAYS = 30    # beyond this, restore is not a real option
BACKUP_WARN_DAYS = 7     # a weekly cadence is the working assumption

# Plugin backlog. The fleet spreads continuously from 0 to 29 with a median of
# ~6, so there is no natural break in the data and this is a judgement call:
# ten pending updates is where a backlog stops looking like normal ops.
PLUGIN_WARN_COUNT = 10

UNKNOWN = "unknown"

# The facts evaluate() actually reads to produce a status. Anything not in here
# can move freely without the score moving, and a caller reasoning about WHY a
# status changed should consult this rather than assume every observed fact is
# an input. `upstream_pending` and `theme_updates` are deliberately absent:
# they are recorded and displayed, and they score nothing.
SCORING_FACTS = ("frozen", "wp_checked", "wp_version", "php_version",
                 "db_backup_age_days", "wp_core_update", "plugin_updates",
                 "nexcess_app_version", "nexcess_php_version",
                 "consent_scan_ok", "consent_banner_detected",
                 "consent_pre_trackers")

# The fact names a Pantheon health observation always carries, whatever their
# values. Presence of ANY of these means the health scanner saw this site.
HEALTH_FACTS = ("php_version", "wp_checked", "db_backup_age_days",
                "upstream_pending", "plan")

# The same idea for the Nexcess control-plane adapter. A Nexcess row is a
# DIFFERENT kind of look than a health scan: it is what the hosting control
# plane reports about a site, not what WP-CLI read off the filesystem. The
# names are prefixed so the two can never be confused for each other on one
# timeline, and so that when SSH lands in Phase 2 a disagreement between
# `nexcess_app_version` and `wp_version` shows up as a finding instead of
# overwriting one with the other.
NEXCESS_FACTS = ("nexcess_site_id", "nexcess_php_version",
                 "nexcess_app_version", "nexcess_state", "nexcess_package")

# Cookie-consent coverage, from a browser observation of the public homepage.
# `consent_scan_ok` is listed first and is present on EVERY consent row,
# including rows where the page would not load, so its presence means "the
# sweep reached this site" and its VALUE says whether the look succeeded.
CONSENT_FACTS = ("consent_scan_ok", "consent_banner_detected",
                 "consent_pre_trackers")

# Any scan of any kind reached this site. Used ONLY to decide UNKNOWN. Adding
# a provider means adding its fact tuple here, or 21 measured sites keep
# rendering as "nobody looked".
#
# The email/DNS facts are deliberately NOT here. That check answers a different
# question -- can this domain send mail that authenticates -- and a site with
# only email facts genuinely has had no scan reach the SITE. Adding it would
# move 78 sites out of UNKNOWN without anyone having looked at one of them.
COVERAGE_FACTS = HEALTH_FACTS + NEXCESS_FACTS + CONSENT_FACTS

# States, worst first. Callers that need to sort or pick a worst-of should use
# this rather than hardcoding an order.
ORDER = ["CRIT", "WARN", "OK", "UNKNOWN", "SKIP", "FROZEN"]


# ---------------------------------------------------------------------------
# AXES
# ---------------------------------------------------------------------------
# Added 2026-08-20. Until today one status per site answered TWO unrelated
# questions -- is this site maintained, and does it leak trackers before
# consent -- and the second silently drove the first. 38 of 70 WARN sites had a
# consent reason and 7 were WARN for consent ALONE, so the fleet-health
# headline moved when the consent sweep ran and nothing about maintenance had
# changed. That is the same shape as `upstream_pending`: a rule from one
# question ranking sites on another.
#
# An axis is a QUESTION, not a workflow. `coverage_partial` comes from the
# consent sweep -- it fires when the sweep is the only thing that ever saw a
# site -- but it answers "do we know this site's health", so it is a HEALTH
# reason. Map by what the finding is about, never by which tool found it.
#
# Same vocabulary on every axis, per CLAUDE.md: an axis with no measurement
# reads UNKNOWN, never OK. A second set of state names would be a second
# answer.
AXES = ("health", "consent")

AXIS_OF_CODE = {
    "wp_below_floor":              "health",
    "php_eol":                     "health",
    "backup_missing":              "health",
    # A conditional code -- `add(crit, "backup_missing" if ... else
    # "backup_stale", ...)`. A grep for add(bucket, "literal") misses it, which
    # is exactly why axis_of() raises instead of defaulting.
    "backup_stale":                "health",
    "backup_aging":                "health",
    "core_update":                 "health",
    "plugin_backlog":              "health",
    "wp_version_unknown":          "health",
    "wp_version_disagreement":     "health",
    "nexcess_app_version_unknown": "health",
    # Fires on the consent sweep, ANSWERS a health question. See above.
    "coverage_partial":            "health",
    "consent_pre_consent_trackers": "consent",
    "consent_no_tooling":           "consent",
}


def axis_of(code):
    """Which question does this finding answer?

    Raises for an unmapped code rather than defaulting to health. A new rule
    that silently lands on the health axis would re-create exactly the bug
    this split was built to fix, and it would do it quietly.
    """
    try:
        return AXIS_OF_CODE[code]
    except KeyError:
        raise KeyError(
            "severity code %r has no axis. Add it to AXIS_OF_CODE -- a rule "
            "with no axis cannot be scored, and defaulting it to health is "
            "how consent came to drive the health headline." % (code,))


def _version(v):
    """Parse a dotted version to a tuple, or None if it is not one.

    Returns None for None, "unknown", "n/a", "up-to-date", and anything else
    that is not a version. Every caller below treats None as "no rule fires",
    which is what keeps an unmeasured site out of OK rather than in it.
    """
    if v is None:
        return None
    parts = str(v).strip().split(".")
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, TypeError):
        return None


def _num(v):
    """A count or age, or None if the value is not a real measurement."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def is_production(site):
    """Does this site count toward the fleet's health numbers?

    `production` is an explicit human decision recorded in the inventory. It is
    tri-state on purpose:

        True   reviewed, counts
        None   NOBODY HAS LOOKED. Counts. Fail safe.
        False  reviewed and ruled out of scope. Reported, not counted.

    None must score as production. The alternative -- defaulting unreviewed
    sites out of the numbers -- means a site silently stops being watched
    because nobody got round to classifying it, which is the exact failure this
    project keeps finding.

    Do NOT infer this from the Pantheon plan. On the 2026-08-19 fleet, keying
    off `plan == "Sandbox"` would have excluded `hoffmanscheese` -- 721 days
    without a backup and the only real CRIT left. Plan is a billing attribute.
    """
    return site.get("production") is not False


def php_support(version, today=None):
    """(tier, days_left); tier is eol | expiring | supported | unknown.

    `today` defaults to the real current date rather than to None. The first
    version of this returned "supported" when no date was passed, which meant a
    caller that forgot the argument scored a PHP 7.4 site as fine -- a rule
    failing OPEN, in the one module whose stated contract is that an absence
    never reads as an all-clear. Callers that need deterministic output (tests,
    --today) pass the date explicitly; the default only stops a forgotten
    argument from being dangerous.
    """
    v = str(version)
    if v not in PHP_SECURITY_EOL:
        return (UNKNOWN, None)
    if today is None:
        today = datetime.date.today()
    eol = datetime.date.fromisoformat(PHP_SECURITY_EOL[v])
    days = (eol - today).days
    if days < 0:
        return ("eol", days)
    if days <= PHP_EXPIRING_DAYS:
        return ("expiring", days)
    return ("supported", days)


def evaluate(site, today=None):
    """Score one merged site record. Pure function of the facts passed in.

    Expects observed facts under their ledger names (`wp_version`,
    `db_backup_age_days`, `php_version`, `wp_core_update`, `plugin_updates`,
    `upstream_pending`, `wp_checked`, `frozen`) and optionally the inventory's
    `production` flag.

    Returns a dict:
        status      one of ORDER
        reasons     [{level, code, text}] -- what actually fired, in the order
                    the rules are written. Never empty for CRIT or WARN.
        info        [str] -- true but not severity-bearing. Shown, not scored.
        production  bool -- whether this row counts toward fleet totals
    """
    crit, warn, info = [], [], []

    def add(bucket, code, text):
        bucket.append({"code": code, "text": text})

    # --- terminal states, before any rule runs -----------------------------
    if site.get("frozen") is True:
        return _result("FROZEN", [], [], site)

    # NO HEALTH SCAN HAS EVER REACHED THIS SITE. Tested on the PRESENCE of the
    # fact keys, not their values: a site seen only by the email/DNS check
    # carries no health facts at all, while a site the health scan reached
    # carries them even when their value is the token "unknown".
    #
    # This branch exists because without it those sites fell through to SKIP,
    # and the first render said 35 SKIP for a fleet with 3 real skips. SKIP
    # reads as "nothing there to check". These are the 32 Nexcess and
    # outlier-host sites nobody has ever scanned -- the project's largest
    # evidence gap rendering as a shrug. Same bug as every other entry in the
    # handoff's table: a value that looks like an answer standing in for an
    # absence.
    if not any(k in site for k in COVERAGE_FACTS):
        return _result("UNKNOWN", [], [], site)

    # The health scan reached it, but there is no environment to measure: a
    # live env that was never initialized. Distinct from UNKNOWN above. SKIP
    # means there is nothing there; UNKNOWN means nobody looked.
    nexcess_seen = any(k in site for k in NEXCESS_FACTS)
    consent_seen = any(k in site for k in CONSENT_FACTS)
    health_seen = any(k in site for k in HEALTH_FACTS)
    if (not nexcess_seen and not consent_seen
            and site.get("wp_checked") is not True
            and _version(site.get("php_version")) is None):
        return _result("SKIP", [], [], site)

    # --- CRIT ---------------------------------------------------------------
    wp = _version(site.get("wp_version"))
    if wp is not None and wp < WP_SECURITY_FLOOR:
        add(crit, "wp_below_floor",
            "WordPress %s is below the %s security floor (wp2shell)"
            % (site.get("wp_version"), ".".join(map(str, WP_SECURITY_FLOOR))))

    # The same question, answered by the Nexcess control plane instead of by
    # WP-CLI. It fires only when no WP-CLI reading exists, so a site with both
    # is scored on the one that was read off the filesystem.
    #
    # A control-plane version is weaker evidence than `wp core version`, and
    # scoring CRIT on it is deliberate: below the wp2shell floor is the single
    # highest-value finding this project has, the remediation column is blank
    # for all 21 Nexcess sites, and being wrong in this direction produces a
    # site to go and check. Being wrong in the other direction produces a green
    # row over an unauthenticated RCE.
    nx_wp = _version(site.get("nexcess_app_version"))
    if wp is None and nx_wp is not None and nx_wp < WP_SECURITY_FLOOR:
        add(crit, "wp_below_floor",
            "WordPress %s is below the %s security floor (wp2shell), per the "
            "Nexcess control plane" % (site.get("nexcess_app_version"),
                                       ".".join(map(str, WP_SECURITY_FLOOR))))

    tier, days = php_support(site.get("php_version"), today)
    # Fall back to the control plane's PHP version only when the health scan
    # has none. Never merge the two into one value: keeping them separate is
    # what makes a disagreement visible below instead of silent.
    if tier == UNKNOWN and site.get("nexcess_php_version") not in (None, UNKNOWN):
        tier, days = php_support(site.get("nexcess_php_version"), today)
        php_shown = site.get("nexcess_php_version")
    else:
        php_shown = site.get("php_version")
    if tier == "eol":
        add(crit, "php_eol",
            "PHP %s stopped receiving security patches on %s"
            % (php_shown, PHP_SECURITY_EOL[str(php_shown)]))

    backup = _num(site.get("db_backup_age_days"))
    if backup is not None and backup > BACKUP_CRIT_DAYS:
        # 9999 is the scanner's sentinel for "no backup found at all". Saying
        # "no backup in 9999 days" would read as a measurement.
        add(crit, "backup_missing" if backup >= 9999 else "backup_stale",
            "No database backup found at all" if backup >= 9999
            else "No database backup in %d days" % backup)

    # --- WARN ---------------------------------------------------------------
    core = site.get("wp_core_update")
    if core not in (None, "up-to-date", "n/a", UNKNOWN):
        add(warn, "core_update", "WordPress core update available: %s" % core)

    if backup is not None and BACKUP_WARN_DAYS < backup <= BACKUP_CRIT_DAYS:
        add(warn, "backup_aging", "Last database backup was %d days ago" % backup)

    plugins = _num(site.get("plugin_updates"))
    if plugins is not None and plugins >= PLUGIN_WARN_COUNT:
        add(warn, "plugin_backlog", "%d plugin updates pending" % plugins)



    # A site that was deep-scanned but whose version could not be read is not
    # OK and is not CRIT. It is unmeasured, and it says so.
    if site.get("wp_checked") is True and wp is None:
        add(warn, "wp_version_unknown",
            "Deep scan ran but the WordPress version could not be read")

    # --- Nexcess control-plane rules ---------------------------------------
    # The API answered for this site but told us nothing about the application
    # version. Without this rule such a site scores on PHP alone and can reach
    # OK, which prints a green row over a site whose wp2shell status is still
    # exactly as unknown as it was before the scan ran. That is the shape of
    # every row in CLAUDE.md's table.
    if nexcess_seen and wp is None and nx_wp is None:
        add(warn, "nexcess_app_version_unknown",
            "The Nexcess control plane returned no application version, so the "
            "wp2shell question is still unanswered for this site")

    # The two readings disagree. Neither is overwritten and neither is picked:
    # the disagreement is the finding, and it is the reason the control-plane
    # facts are stored under their own names.
    if wp is not None and nx_wp is not None and wp != nx_wp:
        add(warn, "wp_version_disagreement",
            "WP-CLI reports WordPress %s, the Nexcess control plane reports %s"
            % (site.get("wp_version"), site.get("nexcess_app_version")))

    # --- cookie-consent rules -----------------------------------------------
    # WARN, not CRIT. Doug's ruling, 2026-08-19: CRIT stays a security tier --
    # act now, unpatched RCE, no backup, PHP past end of support -- so that the
    # CRIT count remains a short list somebody actually works through. A
    # consent gap is real and it is a client conversation, which is what WARN
    # means here.
    #
    # NEITHER RULE IS A COMPLIANCE VERDICT, and the wording is the guardrail:
    # they report what was observed on the sampled page. Do not reword these
    # into "non-compliant" -- see docs/CONSENT.md.
    pre = _num(site.get("consent_pre_trackers"))
    if pre:
        add(warn, "consent_pre_consent_trackers",
            "%d tracker(s) fired on the homepage before any consent "
            "interaction: %s" % (pre, site.get("consent_pre_tracker_names")
                                 if site.get("consent_pre_tracker_names")
                                 not in (None, UNKNOWN) else "see the scan"))

    if site.get("consent_banner_detected") is False:
        add(warn, "consent_no_tooling",
            "No consent tooling was detected on the homepage")

    # A page that would not load for the browser scores NOTHING. Plenty of
    # sites refuse headless clients, and a rule that fires on all of them would
    # put a WARN floor under the fleet for a reason that is identical
    # everywhere -- the exact mistake `upstream_pending` was making. It is
    # recorded, shown, and left to a person.
    if site.get("consent_scan_ok") is False:
        st = site.get("consent_http_status")
        if isinstance(st, int) and st >= 400:
            # The most common case by a distance: a WAF refusing the headless
            # client. 23 of 78 sites on the first real sweep. Naming the status
            # matters because it is the difference between "this site is down"
            # and "this site will not talk to our scanner".
            info.append("The consent sweep got HTTP %d, so it saw an error page "
                        "rather than the site. Its consent posture is "
                        "unmeasured, not clean." % st)
        else:
            info.append("The consent sweep could not load this site; its consent "
                        "posture is unmeasured, not clean")

    # Partial coverage. There is no backup age, no plugin count and no theme
    # count for this site, and those are the facts that make a Pantheon OK mean
    # anything. So a site seen ONLY by a provider adapter or the consent sweep
    # cannot reach OK; it reaches WARN and says what is missing. The rule
    # retires itself for a site the moment a health scan supplies those facts.
    #
    # Generalised 2026-08-19 when the consent sweep arrived: it was written for
    # Nexcess, but the condition was never about Nexcess. It is about a site
    # having been LOOKED AT without its health being ESTABLISHED, and every new
    # source that is not a health scan creates more of those.
    if (nexcess_seen or consent_seen) and not health_seen:
        missing = "Nexcess control-plane discovery" if nexcess_seen else "the consent sweep"
        add(warn, "coverage_partial",
            "Seen only by %s: no backup age, plugin or theme evidence exists "
            "for this site" % missing)

    # --- informational ------------------------------------------------------
    # Pending upstream commits used to be a WARN. Every site has 1 or 2, always,
    # so it scored the whole fleet as WARN and made OK unreachable. It is a real
    # fact and it stays on the page; it is not a severity signal.
    # NOT a WARN. 46 of 52 sites are on 8.2, which ends 2026-12-31, so scoring
    # it per-site would put a WARN floor under the fleet for a reason that is
    # identical everywhere -- the exact mistake `upstream_pending` was making.
    # It is one fleet-wide deadline and it belongs in the standing findings as
    # a PLANNING item, which is where the ledger already puts it.
    if tier == "expiring":
        info.append("PHP %s leaves security support in %d days (%s)"
                    % (php_shown, days, PHP_SECURITY_EOL[str(php_shown)]))

    app = site.get("nexcess_app")
    if app not in (None, UNKNOWN, "wordpress"):
        info.append("Nexcess reports the application as %r, not WordPress" % app)

    # `nexcess_state` is recorded and deliberately scores NOTHING. Its value
    # set has never been observed from this codebase -- "stable" is the only
    # value the vendor docs show -- and a rule written against a guessed enum
    # either never fires or fires on everything. Add the rule after a live run
    # shows what the field actually contains.

    up = _num(site.get("upstream_pending"))
    if up:
        info.append("%d Pantheon upstream commit(s) pending" % up)

    themes = _num(site.get("theme_updates"))
    if themes:
        info.append("%d theme update(s) pending" % themes)

    if plugins is not None and 0 < plugins < PLUGIN_WARN_COUNT:
        info.append("%d plugin update(s) pending" % plugins)

    return _result(None, crit, warn, site, info)


def _result(status, crit, warn, site, info=None):
    """Build the result, splitting findings across axes.

    `status=None` means "derive it": each axis is scored from its OWN reasons,
    and the top-level `status` is the HEALTH axis. Callers wanting the consent
    answer read `axes["consent"]`.

    A non-None `status` is a TERMINAL state -- FROZEN, UNKNOWN, SKIP -- which
    is a statement about the whole site rather than about one question, so it
    is stamped onto every axis. A frozen site is not "frozen for health and
    unknown for consent".

    `reasons` carries the HEALTH reasons only, so it always agrees with
    `status`. The union is `all_reasons`, every entry tagged with its axis. Two
    fields rather than one because a caller reading `reasons` and `status`
    together must never see an OK status sitting next to a WARN reason.
    """
    reasons = ([dict(r, level="CRIT", axis=axis_of(r["code"])) for r in crit]
               + [dict(r, level="WARN", axis=axis_of(r["code"])) for r in warn])

    if status is not None:
        axes = dict((a, {"status": status, "reasons": []}) for a in AXES)
        return {"status": status, "reasons": [], "all_reasons": [],
                "axes": axes, "info": info or [],
                "production": is_production(site)}

    axes = {}
    for a in AXES:
        mine = [r for r in reasons if r["axis"] == a]
        if any(r["level"] == "CRIT" for r in mine):
            st = "CRIT"
        elif mine:
            st = "WARN"
        else:
            st = "OK"
        axes[a] = {"status": st, "reasons": mine}

    # The consent axis is UNKNOWN unless the sweep actually loaded the page.
    # `consent_scan_ok` is present on every consent row INCLUDING rows the
    # sweep could not read, so its presence means "the sweep tried" and its
    # value says whether the look succeeded. Without this, a site the sweep was
    # refused by scores OK on consent -- 23 sites reading "no banner, no
    # trackers" off an HTTP 403 block page, which is the bug the sweep itself
    # shipped with on 2026-08-19. Unmeasured is not clean.
    if site.get("consent_scan_ok") is not True and not axes["consent"]["reasons"]:
        axes["consent"]["status"] = "UNKNOWN"

    health = axes["health"]
    return {"status": health["status"],
            "reasons": health["reasons"],
            "all_reasons": reasons,
            "axes": axes,
            "info": info or [],
            "production": is_production(site)}


def needs_review(site):
    """Should a human classify this site as production or not?

    NOT simply `production is None`. That is None on all 84 sites today, so it
    would put the entire fleet in the review queue and the queue would be
    ignored, which is worse than not having one.

    A site recorded in the manual audit workbook has already been through a
    human pass -- somebody typed its row. Absent an explicit ruling, that
    counts as reviewed and it scores as production.

    The queue is therefore the sites nobody has EVER looked at: no explicit
    `production` value AND no workbook row. On the 2026-08-19 fleet that is
    exactly six, all on the Sandbox plan, and it includes the two
    worst-maintained sites in the fleet. That correlation is the argument for
    surfacing the queue at all: on Pantheon, "nobody wrote this down" and
    "nobody is maintaining it" turned out to be the same set.
    """
    return site.get("production") is None and site.get("in_workbook") is False


def summarise(sites, today=None):
    """Fleet totals. Non-production sites are counted SEPARATELY, never folded
    into the headline numbers and never dropped.

    Returns {"counts": {...}, "excluded": {...}, "excluded_sites": [...],
             "unreviewed": [...]}.

    `unreviewed` is the review queue -- see needs_review().
    """
    counts = {k: 0 for k in ORDER}
    excluded = {k: 0 for k in ORDER}
    # Per-axis totals, added 2026-08-20 with the axis split. `counts` is the
    # HEALTH axis and stays the fleet headline; `axes` carries every axis
    # including health, so a caller can render one tile group per question
    # without re-deriving anything. Non-production sites are excluded from
    # every axis on the same rule, not just from health.
    axis_counts = dict((a, {k: 0 for k in ORDER}) for a in AXES)
    excluded_sites, unreviewed = [], []
    for s in sites:
        r = s.get("severity") or evaluate(s, today)
        if r["production"]:
            counts[r["status"]] += 1
            for a in AXES:
                axis_counts[a][r["axes"][a]["status"]] += 1
        else:
            excluded[r["status"]] += 1
            excluded_sites.append(s.get("site_id"))
        if needs_review(s):
            unreviewed.append(s.get("site_id"))
    return {"counts": counts, "excluded": excluded, "axes": axis_counts,
            "excluded_sites": sorted(x for x in excluded_sites if x),
            "unreviewed": sorted(x for x in unreviewed if x)}
