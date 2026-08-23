#!/usr/bin/env python3
"""
fleet-ledger.py - history store and change detector for fleet scans.

PROTOTYPE, 2026-08-17. Built to answer a design question with real output
rather than argument: given that two runs 14h apart differed by one integer,
what should a human actually receive?

Design contract, matching the rest of cm-automation:
  - stdlib only, no pip, no services
  - runs identically on macOS and a Linux CI runner
  - append-only: it never rewrites or deletes a prior observation
  - unknown is a value, never folded into yes or no
  - diffs operate on OBSERVED FACTS, never on rendered strings

Subcommands
  ingest   reports/*.json -> history/observations.jsonl   (idempotent)
  diff     compare two runs, fact level, with change classification
  digest   the delta-first report a human should receive
  timeline per-site or per-fact history across all ingested runs

Usage
  ./scripts/fleet-ledger.py ingest  --reports ./reports --history ./history
  ./scripts/fleet-ledger.py diff    --history ./history
  ./scripts/fleet-ledger.py digest  --history ./history
  ./scripts/fleet-ledger.py timeline --history ./history --site hoffmanscheese
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys

# Severity lives in scripts/lib/severity.py and NOTHING computes it anywhere
# else. It is a pure function of observed facts plus the inventory's
# `production` flag, so history rescores consistently whenever a threshold
# moves. Loaded by path because this file is not on a package path.
_sev_spec = importlib.util.spec_from_file_location(
    "severity", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "severity.py"))
SEV = importlib.util.module_from_spec(_sev_spec)
_sev_spec.loader.exec_module(SEV)

# --------------------------------------------------------------------------
# Fact model
# --------------------------------------------------------------------------
# OBSERVED facts come from Pantheon. They are what we diff.
# DERIVED values are computed by the scanner from observed facts. We diff them
# too, but separately and labelled, because a derived change with no observed
# change means OUR RULES changed, not the fleet. That distinction is the whole
# reason this is split.

OBSERVED = (
    "framework",
    "plan",
    "env",
    "frozen",
    "php_version",
    "db_backup_age_days",
    "upstream_pending",
    "wp_checked",
    "wp_version",
    "wp_core_update",
    "plugin_updates",
    "theme_updates",
    # Did this run inventory the site's components at all? The LIST itself is
    # not a fact and is not stored here -- it goes to components.jsonl, one row
    # per component. This is the scalar the page needs so that "no vulnerable
    # plugin found" can be told apart from "we never listed the plugins".
    "components_checked",
)

DERIVED = ("status",)

# `notes` is a rendered sentence that embeds observed numbers. Diffing it
# double-reports every numeric change. Excluded on purpose. Do not add it back.
RENDERED = ("notes",)

# Facts whose absence is meaningful (site was not deep-scanned) rather than
# missing data. Absent -> the literal token "unknown".
UNKNOWN = "unknown"


# Facts that only exist if the site was deep-scanned over SSH. In api-only mode
# the scanner currently writes 0 / 0 / "n/a" for these on every site. A 0 there
# is a FABRICATED NEGATIVE: it renders as "no plugin updates pending" in the CSV
# and the digest when the truth is "nobody looked". The ledger refuses to store
# it. This is settled principle 5 (unknown is never folded into negative)
# applied to the data rather than only to the display.
# wp_version joined this list on 2026-08-18. It is the fact the whole project
# was built to establish: the workbook asserts 7.0.2 on all 78 sites and nothing
# had ever verified it on any of them. Until that date the scan recorded only
# wp_core_update, which reports the version AVAILABLE and reads "up-to-date"
# when none is, so a fleet on any version at all looked identical to a fleet on
# 7.0.2. Belongs here because reading it needs SSH, so on an api-only run it
# must be unknown and never a value.
DEEP_ONLY = ("wp_version", "wp_core_update", "plugin_updates", "theme_updates",
             "components_checked")


def fact(row, key):
    """Observed value, or UNKNOWN. Never None, never coerced to a falsy default."""
    if key in DEEP_ONLY and row.get("wp_checked") is not True:
        return UNKNOWN
    if key not in row or row[key] is None:
        return UNKNOWN
    return row[key]


# --------------------------------------------------------------------------
# PHP support calendar - php.net/supported-versions, verified 2026-08-17
# --------------------------------------------------------------------------
# Kept as data, not as an if-chain, so it is reviewable and updatable without
# touching logic. Dates are the END of security support.
# The PHP end-of-support table used to live here AND as a hardcoded floor in
# the severity rules, and the two disagreed on the page: "Still true" reported
# a site past PHP end-of-support while its severity row read fine. One table
# now, in the severity module, read from here.
PHP_SECURITY_EOL = SEV.PHP_SECURITY_EOL
php_support = SEV.php_support


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
# The whole point of this layer: three tools key on three different identifiers
# (Pantheon machine name, domain, sending domain) and none of them agreed. Every
# source is normalised onto the inventory's site_id (the domain) before anything
# is stored, so one site has ONE history no matter which tool observed it.
#
# Fact names must not collide across sources; ingest asserts it rather than
# trusting it, because a silent collision would merge two unrelated measurements
# into one timeline and the diff would report changes that never happened.

EMAIL_OBSERVED = (
    "spf_present", "spf_all_qualifier", "spf_checked_at",
    "dkim_present", "dkim_selector",
    "dmarc_at_sending_present", "dmarc_at_sending_policy",
    "dmarc_at_from_present", "dmarc_at_from_policy", "dmarc_via_org_fallback",
    "relaxed_aligned",
)

# Nexcess control-plane discovery. Every name is prefixed, and that is a
# decision rather than a style: the control plane and WP-CLI answer the same
# two questions (what PHP, what WordPress) by different means, and the
# control-plane answer is the weaker of the two. Storing them under one name
# means whichever ran last wins and the disagreement disappears. Storing them
# apart means the disagreement is a fact, and `wp_version_disagreement` in the
# severity module can report it.
#
# `nexcess_unix_username` is here because it is the join key for Phase 2: SSH
# identity on Nexcess Managed WordPress is per site, so the SSH scan cannot be
# built until this has been measured once.
NEXCESS_OBSERVED = (
    "nexcess_site_id",
    "nexcess_unix_username",
    "nexcess_ip",
    "nexcess_package",
    "nexcess_state",
    "nexcess_app",
    "nexcess_app_version",
    "nexcess_php_version",
    "nexcess_env",
    "nexcess_temp_domain",
)

# Cookie-consent coverage. A browser observation of the public homepage: what
# fired before any consent interaction, and which consent tooling is present.
#
# `consent_pre_tracker_names` is a sorted comma string, not a list. The ledger
# diffs values, and a list would report a reorder as a change. Sorting it makes
# "GA4 appeared" a real diff and "the same two in a different order" a no-op.
#
# NOTHING HERE IS A COMPLIANCE VERDICT. These are observations. The words
# "compliant" and "non-compliant" do not appear in this workflow and must not
# be added -- see docs/CONSENT.md for why that line is load-bearing rather than
# lawyerly.
CONSENT_OBSERVED = (
    "consent_scan_ok",
    "consent_banner_vendor",
    "consent_banner_detected",
    "consent_pre_trackers",
    "consent_pre_tracker_names",
    "consent_mode_denied",
    "consent_http_status",
    "consent_final_url",
)

# `cmpScripts` from the scan file is deliberately NOT a ledger fact. It is
# evidence for interpreting `consent_banner_vendor` -- it tells "no CMP" apart
# from "a CMP we do not recognise" -- and it lives in reports/ where a person
# reading a finding can consult it. Giving it a timeline would mean diffing a
# list of URLs that change on every cache-buster, and reporting that as a fleet
# change.

RUN_RE = re.compile(r"fleet-(health|plugin-scan|email-dns|[a-z0-9-]+)-(\d{4}-\d{2}-\d{2})_(\d{4})\.json$")


def parse_run_id(path):
    """Run identity comes from the filename stamp the scanners already write."""
    m = RUN_RE.search(os.path.basename(path))
    if not m:
        return None
    kind, day, hhmm = m.groups()
    return {
        "run_id": "%s-%s_%s" % (kind, day, hhmm),
        "kind": kind,
        "observed_at": "%sT%s:%s:00" % (day, hhmm[:2], hhmm[2:]),
    }


def load_inventory(path):
    """site_id lookups. Returns (by_host_site_name, by_domain, records).

    A MISSING inventory is an ERROR here, not an empty result. Accepting it
    silently is exactly how the ledger written on 2026-08-16 came to key its
    health rows on Pantheon machine names: the inventory did not exist yet,
    every lookup fell back to the raw key, nothing complained, and the damage
    was only visible a day later when the dashboard reported 130 sites for an
    84-site fleet. The store is append-only, so it could not be corrected in
    place; it had to be rebuilt from reports/ that happened to still exist.

    Pass path=None to mean "deliberately no inventory". That is now a decision
    the caller states out loud, rather than what a wrong path quietly gets you.
    """
    if path is None:
        return {}, {}, {}
    if not os.path.exists(path):
        raise SystemExit(
            "inventory not found: %s\n"
            "Ingesting without it keys every row on whatever identifier its own\n"
            "tool happens to use, and this ledger is append-only, so the result\n"
            "cannot be corrected afterwards. Point --inventory at the real file,\n"
            "or pass --no-inventory if you genuinely mean unnormalised keys."
            % path
        )
    inv = json.load(open(path))
    by_host, by_domain, recs = {}, {}, {}
    for s in inv["sites"]:
        recs[s["site_id"]] = s
        if s.get("host_site_name"):
            by_host[s["host_site_name"]] = s["site_id"]
        if s.get("domain"):
            by_domain[s["domain"].lower()] = s["site_id"]
    return by_host, by_domain, recs


def _health_rows(payload, by_host):
    """Pantheon health scan: a list of rows keyed on the machine name."""
    if not isinstance(payload, list):
        return None
    out = []
    for r in payload:
        name = r["site"]
        rec = {"site_id": by_host.get(name, name), "host_site_name": name,
               "source": "health"}
        for k in OBSERVED:
            rec[k] = fact(r, k)
        for k in DERIVED:
            rec["derived_" + k] = fact(r, k)
        out.append(rec)
    return out


def _component_rows(payload, by_host):
    """One row per site per installed component. A LIST, not a fact.

    Deliberately not in observations.jsonl. That ledger diffs scalar facts
    between runs; a 40-element list per site would either be diffed
    element-wise -- turning every routine plugin version bump into fleet news
    -- or stored as an opaque blob nothing could query. Components are the
    third layer the data model always implied: inventory (human), observations
    (scalar measurements), components (an inventory OF each site).

    A site with `components: null` produces NO ROWS. Zero rows for a site and
    "this site runs nothing" must not be the same state, which is why
    `components_checked` is carried on the observation row instead of being
    inferred from a row count here.
    """
    if not isinstance(payload, list):
        return None
    out = []
    for r in payload:
        comps = r.get("components")
        if not isinstance(comps, list):
            continue
        name = r["site"]
        site_id = by_host.get(name, name)
        # DE-DUPLICATE, keyed on (slug, is-a-theme), preferring the mu-plugin
        # typing. `wp plugin list` ALREADY returns must-use plugins, with
        # status "must-use", so the scanner's separate --status=must-use call
        # lists every one of them twice -- once typed `plugin`, once
        # `mu-plugin`. Measured on the first real run, 2026-08-23: 51
        # duplicate rows across the first 16 sites, ~165 fleet-wide.
        #
        # Deduping HERE rather than only in the scanner is deliberate. This
        # store is append-only, so a duplicated row cannot be corrected later;
        # the guard belongs at the point of writing, where it holds no matter
        # which version of the scanner produced the report.
        #
        # A theme is allowed to share a slug with a plugin, so themes are keyed
        # separately rather than collapsed into one namespace.
        best = {}
        for c in comps:
            slug = c.get("name")
            if not slug:
                continue
            key = (slug, c.get("type") == "theme")
            if key in best and best[key].get("type") == "mu-plugin":
                continue          # already have the authoritative typing
            best[key] = c
        for c in best.values():
            slug = c.get("name")
            out.append({
                "site_id": site_id,
                "host_site_name": name,
                "source": "health",
                # Match on slug + type + version, never the display name --
                # docs/VULN-INTEL-REVIEW.md section 3. WP-CLI's `name` IS the
                # directory slug, which is what advisory feeds key on.
                "slug": slug,
                "type": c.get("type") or "plugin",
                "version": c.get("version") or UNKNOWN,
                "status": c.get("status") or UNKNOWN,
                "update_available": c.get("update") == "available",
                "update_version": c.get("update_version") or None,
            })
    return out


def _email_rows(payload, by_domain):
    """Email DNS check: a dict with a `sites` list keyed on the domain."""
    if not isinstance(payload, dict) or payload.get("kind") != "email-dns":
        return None
    out = []
    for s in payload.get("sites", []):
        if "error" in s:
            continue
        d = s["domain"].lower()
        dk, spf = s.get("dkim", {}), s.get("spf", {})
        dm = s.get("dmarc", {})
        at_send, at_from = dm.get("at_sending_domain", {}), dm.get("at_from_domain", {})
        out.append({
            "site_id": by_domain.get(d, d), "host_site_name": None, "source": "email-dns",
            "spf_present": spf.get("present", UNKNOWN),
            "spf_all_qualifier": spf.get("all_qualifier") or UNKNOWN,
            "spf_checked_at": spf.get("checked_at") or UNKNOWN,
            "dkim_present": dk.get("present", UNKNOWN),
            "dkim_selector": dk.get("selector") or UNKNOWN,
            "dmarc_at_sending_present": at_send.get("present", UNKNOWN),
            "dmarc_at_sending_policy": at_send.get("policy") or UNKNOWN,
            "dmarc_at_from_present": at_from.get("present", UNKNOWN),
            "dmarc_at_from_policy": at_from.get("policy") or UNKNOWN,
            "dmarc_via_org_fallback": at_from.get("via_org_fallback", UNKNOWN),
            "relaxed_aligned": s.get("alignment", {}).get("relaxed_aligned", UNKNOWN),
        })
    return out


def _nexcess_rows(payload, by_domain):
    """Nexcess estate discovery: a dict with a `sites` list keyed on the domain.

    Sites the API could not be asked about are NOT written. A row that exists
    with every fact unknown is indistinguishable on the page from a row that
    was measured and came back empty, and this project has shipped that bug
    more than once. A site missing from the scan stays UNKNOWN, which is what
    it is.
    """
    if not isinstance(payload, dict) or payload.get("kind") != "nexcess-estate":
        return None
    out = []
    for s in payload.get("sites", []):
        if s.get("error"):
            continue
        d = (s.get("domain") or "").lower()
        if not d:
            continue
        out.append({
            "site_id": by_domain.get(d, d), "host_site_name": None,
            "source": "nexcess",
            "nexcess_site_id": s.get("nexcess_site_id", UNKNOWN) or UNKNOWN,
            "nexcess_unix_username": s.get("unix_username") or UNKNOWN,
            "nexcess_ip": s.get("ip") or UNKNOWN,
            "nexcess_package": s.get("package") or UNKNOWN,
            "nexcess_state": s.get("state") or UNKNOWN,
            "nexcess_app": s.get("app") or UNKNOWN,
            "nexcess_app_version": s.get("app_version") or UNKNOWN,
            "nexcess_php_version": s.get("php_version") or UNKNOWN,
            "nexcess_env": s.get("env") or UNKNOWN,
            "nexcess_temp_domain": s.get("temp_domain") or UNKNOWN,
        })
    return out


def _consent_rows(payload, by_domain):
    """Consent sweep: a dict with a `sites` list keyed on the domain.

    UNLIKE the Nexcess adapter, a FAILED scan IS written, carrying
    `consent_scan_ok: false` and unknown for everything else. The two cases are
    genuinely different. A Nexcess site the API would not describe was still
    listed by the API, so the listing was the measurement and an all-unknown row
    would have added nothing. Here the site itself would not load for a browser,
    and that is a fact about the site worth keeping a history of -- a domain
    that stops answering is a finding, and a row that quietly vanishes from the
    sweep is not one anybody sees.
    """
    if not isinstance(payload, dict) or payload.get("kind") != "consent-sweep":
        return None
    out = []
    for s in payload.get("sites", []):
        d = (s.get("domain") or "").lower()
        if not d:
            continue
        ok = bool(s.get("ok"))
        trackers = s.get("preConsentTrackers") or []
        rec = {
            "site_id": s.get("site_id") or by_domain.get(d, d),
            "host_site_name": None, "source": "consent",
            "consent_scan_ok": ok,
        }
        if ok:
            rec.update({
                "consent_banner_vendor": s.get("bannerVendor") or (
                    "generic" if s.get("genericBannerVisible") else "none"),
                "consent_banner_detected": bool(s.get("bannerDetected")),
                "consent_pre_trackers": len(trackers),
                "consent_pre_tracker_names": ", ".join(sorted(trackers)) or "none",
                "consent_mode_denied": bool(s.get("consentModeDenied")),
                "consent_final_url": s.get("finalUrl") or UNKNOWN,
            })
        else:
            # Nobody looked successfully. Every observation is unknown, and none
            # of them is zero: "0 trackers fired" on a page that never loaded
            # would render as an all-clear.
            for k in CONSENT_OBSERVED:
                rec.setdefault(k, UNKNOWN)
            rec["consent_scan_ok"] = False

        # The status is set from the payload whether or not the scan succeeded,
        # because on a failed row it is usually the REASON. 23 sites in the
        # first real sweep answered 403; recording that as unknown would hide
        # the one fact that explains the whole row.
        rec["consent_http_status"] = (
            s.get("status") if s.get("status") is not None else UNKNOWN)
        out.append(rec)
    return out


# Fact-name collision guard. If two sources ever claim the same fact name, the
# ledger would silently merge unrelated measurements onto one timeline.
#
# Checked pairwise across every family rather than as one hardcoded pair, so
# adding a fourth source (the cookie consent monitor is next) cannot get past
# it by nobody remembering to extend the assert.
FACT_FAMILIES = {
    "health": OBSERVED,
    "email-dns": EMAIL_OBSERVED,
    "nexcess": NEXCESS_OBSERVED,
    "consent": CONSENT_OBSERVED,
}
for _a in sorted(FACT_FAMILIES):
    for _b in sorted(FACT_FAMILIES):
        if _a >= _b:
            continue
        _overlap = set(FACT_FAMILIES[_a]) & set(FACT_FAMILIES[_b])
        assert not _overlap, ("fact name collision between sources %s and %s: %s"
                              % (_a, _b, sorted(_overlap)))


# ---------------------------------------------------------------------------
# COVERAGE: what "this run actually measured this site" means, per source.
# ---------------------------------------------------------------------------
# ONE definition, used by three callers that must never disagree:
#
#   1. ingest()                      -> stores `deep_scanned` on the run
#   2. previous_run_of_same_source() -> decides what is a comparable baseline
#   3. ingest()'s drop check         -> notices a run that saw less than the
#                                       run before it
#
# It cost a day to learn that this has to be in one place. Until 2026-08-20 it
# was in two: ingest computed `deep_scanned` from a per-source predicate, while
# the baseline guard tested whether the previous run's SITE SET was a strict
# subset. For health those agree, because a cohort run genuinely has fewer
# rows. For consent they do not -- the sweep writes a row for all 78 sites
# whether or not the page loaded, so a 38-site run and a 54-site run have
# IDENTICAL site sets. The guard saw two comparable full runs, two CI runs at
# 38 replaced a laptop run at 54 on the live dashboard, and nothing anywhere
# said so.
#
# A ROW EXISTS is not A SITE WAS MEASURED. Everything below keys on the second.
MEASURED = {
    # `wp_checked` IS the health coverage flag. An api-only run reaches every
    # site's control plane but reads no WordPress, so it measures nothing in
    # this family -- which is why the baseline rule below has to treat "this
    # run measured nothing" as a different MODE, not as a partial look.
    "health":    lambda r: r.get("wp_checked") is True,
    # The page actually loaded. An HTTP 403 block page is NOT a measurement.
    # That exact bug shipped once and made 23 sites look clean.
    "consent":   lambda r: r.get("consent_scan_ok") is True,
    # The control plane described the site, rather than merely listing it.
    "nexcess":   lambda r: r.get("nexcess_app_version") not in (None, UNKNOWN),
    # DKIM needs a selector to be known, so it is the email fact that
    # distinguishes "looked" from "could not look".
    "email-dns": lambda r: r.get("dkim_present") is True,
}

# The FACT each source's coverage turns on, as a name rather than a predicate.
# MEASURED above decides what a run measured; this decides how a MOVE in that
# fact is classified, and the two must name the same fact or the tool reports
# its own blindness as fleet news.
#
# `wp_checked` was here alone from the first full-mode run, when one event --
# deep-scan coverage arriving -- turned into 48 rows of "what changed".
# `consent_scan_ok` is the identical fact for the consent sweep and was left
# out, so when a WAF blocked four sites on 2026-08-20 the one event was
# reported three ways: six consent facts went to UNKNOWN and collapsed
# correctly, while this flag and the status explaining it each became a
# TRANSITION. 8 of the 14 headline "changes needing a decision" were the
# scanner losing sight of a site.
#
# `consent_http_status` rides along because it describes what the SCANNER got,
# not what the site is: a 200 becoming a 403 is the sweep being refused, and
# on its own it is never a statement about how the site is maintained.
#
# Adding a fifth source means adding its flag here in the same change as its
# MEASURED entry. test-ledger.py asserts every name in this tuple classifies
# as COVERAGE.
# `components_checked` is health's SECOND coverage flag, added 2026-08-23 with
# the component inventory. It is not a new source, but it answers the same
# question -- can the tool see this site -- and it moves False->True on every
# inventoried site the first time the new scanner runs. Without an entry here
# that single event lands as ~46 TRANSITION rows of fleet news, which is
# precisely what `wp_checked` did on the first full-mode run.
COVERAGE_FLAGS = ("wp_checked", "consent_scan_ok", "consent_http_status",
                  "components_checked")

# Which DIRECTION a move in one of those flags went. True means coverage was
# gained; False means it went dark.
#
# These facts carry a real value on BOTH sides -- True/False, 200/403 -- so
# they never touch the UNKNOWN token, and the gained/lost tally in
# collapse_coverage() below cannot infer direction from the values the way it
# does for every other fact. Without an entry here a flag reports "moved on 4
# sites" and an em dash in both columns, which reads as nothing having
# happened on the one line that explains all the others.
#
# `wp_checked` has needed this since the first full-mode run, when it rendered
# `wp_checked  -  48` in the LOST column on the run where coverage went from
# nothing to 48 sites. Adding a flag above without adding it here reintroduces
# that; test-ledger.py asserts no coverage line reports a move with no
# direction.
COVERAGE_DIRECTION = {
    "wp_checked":          lambda before, after: after is True,
    "consent_scan_ok":     lambda before, after: after is True,
    "components_checked":  lambda before, after: after is True,
    # The sweep saw the site only on a 2xx. Anything else is an error page,
    # which is the whole reason `ok` was redefined to require one.
    "consent_http_status": lambda before, after: (isinstance(after, int)
                                                  and 200 <= after < 300),
}


def measured_count(rows, source):
    """How many of `rows` this source actually measured. Never a row count."""
    pred = MEASURED.get(source)
    if pred is None:
        # A new source with no coverage predicate must NOT silently report full
        # coverage; that is the failure this whole module exists to prevent.
        # Failing loudly at ingest is the cheapest place to catch it.
        raise KeyError(
            "source %r has no entry in MEASURED in scripts/fleet-ledger.py. "
            "Add one before ingesting it: without a coverage definition every "
            "run of this source reports as fully covered and no coverage drop "
            "can ever be detected." % (source,))
    return sum(1 for r in rows if pred(r))


def measured_sites(obs, run_id, source):
    """The set of sites this run MEASURED. None if the source has no rule."""
    pred = MEASURED.get(source)
    if pred is None:
        return None
    return set(o["site"] for o in obs if o["run_id"] == run_id and pred(o))


# How a run of each source describes itself. `health` is the exception: it has
# two real modes and which one it was is a property of the coverage, not of the
# tool, so it is derived rather than looked up.
RUN_MODE = {"consent": "browser", "nexcess": "api-estate", "email-dns": "dns"}


def ingest(reports_dir, history_dir, inventory=None):
    obs_path = os.path.join(history_dir, "observations.jsonl")
    runs_path = os.path.join(history_dir, "runs.jsonl")
    if not os.path.isdir(history_dir):
        os.makedirs(history_dir)

    seen = set()
    # The newest already-ingested run of each source, so a run that measured
    # LESS than the one before it can be noticed at the moment it lands.
    # runs.jsonl is append-ordered, so the last record per source is the one to
    # compare against.
    last_by_source = {}
    if os.path.exists(runs_path):
        with open(runs_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                seen.add(rec["run_id"])
                if rec.get("source"):
                    last_by_source[rec["source"]] = rec

    by_host, by_domain, inv_recs = load_inventory(inventory)

    # reports/ is gitignored, so it legitimately does not exist on a fresh
    # clone, or on a CI runner whose scan died before writing anything. Nothing
    # to ingest is zero runs, not a traceback. This is the same absence that
    # broke CI run #1.
    if os.path.isdir(reports_dir):
        files = sorted(
            os.path.join(reports_dir, n)
            for n in os.listdir(reports_dir)
            if n.endswith(".json")
        )
    else:
        files = []

    added_runs, added_obs, skipped = 0, 0, 0
    # Runs that measured fewer sites than the previous run of the same source.
    coverage_drops = []
    # Rows whose identifier matched no inventory entry, accumulated across every
    # run in this ingest. Each run already records its own list, but a value
    # written into a file nobody reads is not a warning. The caller gets a count
    # back and the CLI prints it.
    unresolved_by_run = {}
    comp_path = os.path.join(history_dir, "components.jsonl")
    added_components = 0
    with open(obs_path, "a") as obs_fh, open(runs_path, "a") as runs_fh, \
            open(comp_path, "a") as comp_fh:
        for path in files:
            meta = parse_run_id(path)
            if meta is None:
                print("  skip (unrecognized name): %s" % os.path.basename(path), file=sys.stderr)
                continue
            if meta["run_id"] in seen:
                skipped += 1
                continue
            with open(path) as fh:
                payload = json.load(fh)

            rows = _health_rows(payload, by_host)
            if rows is None:
                rows = _email_rows(payload, by_domain)
            if rows is None:
                rows = _nexcess_rows(payload, by_domain)
            if rows is None:
                rows = _consent_rows(payload, by_domain)
            if rows is None:
                print("  skip (unrecognised shape): %s" % os.path.basename(path),
                      file=sys.stderr)
                continue

            if not rows:
                # An empty report is an absence, not a zero-coverage run.
                # Recording it would put a run in the ledger claiming it
                # measured nothing, which is a different statement.
                print("  skip (no rows): %s" % os.path.basename(path),
                      file=sys.stderr)
                continue

            source = rows[0]["source"]
            # Coverage is a property of the RUN and is what makes an OK
            # trustworthy or not. Computed from the ONE definition above, which
            # the baseline guard and the drop check also read, so the three can
            # never disagree about what "measured" means.
            #
            # Health used to count this off the raw `payload` rather than the
            # normalised rows. Verified identical across all seven health runs
            # in the ledger on 2026-08-20 before the two were merged.
            deep = measured_count(rows, source)
            # Written as a statement, not a chained conditional expression.
            # The one-liner `"full" if deep else "api-only" if source ==
            # "health" else RUN_MODE[source]` parses right-associatively and
            # labels every covered consent run "full". Caught before it ran.
            if source == "health":
                mode = "full" if deep else "api-only"
            else:
                mode = RUN_MODE[source]
            unresolved = [r for r in rows
                          if r.get("site_id") and r["site_id"] not in inv_recs]
            # `mode` is the coverage SHAPE (full / api-only / browser).
            # `method` is the INSTRUMENT that produced it, and it is a separate
            # field on purpose: the consent sweep moved from a headless browser
            # to a headed one on 2026-08-22, which changes what the numbers
            # MEAN without changing their shape. Folding the two together would
            # drag health's load-bearing api-only -> full baseline exception
            # into a rule that has nothing to do with it.
            #
            # Only sources that actually have more than one instrument declare
            # this. A run with no `method` compares to other runs with no
            # `method` exactly as it always did.
            method = payload.get("method") if isinstance(payload, dict) else None
            meta.update({
                "source_file": os.path.basename(path),
                "source": source,
                "site_count": len(rows),
                "deep_scanned": deep,
                "mode": mode,
                **({"method": method} if method else {}),
                # Rows that matched no inventory entry. Never silently dropped:
                # an unknown site is the highest-signal finding there is.
                "sites_not_in_inventory": sorted(r["site_id"] for r in unresolved),
            })
            if unresolved:
                unresolved_by_run[meta["run_id"]] = sorted(
                    r["site_id"] for r in unresolved)
            # A run that measured fewer sites than the previous run of the
            # same source. THE RUN IS STILL INGESTED -- the ledger is
            # append-only and a degraded measurement is still a measurement.
            # Refusing to record an observation because it is inconvenient is
            # the opposite of what this tool is for. What must not happen is
            # that it lands QUIETLY.
            #
            # 2026-08-19: two CI consent runs at 38 of 78 landed after a laptop
            # run at 54, and because the dashboard renders the latest run per
            # source, the live page silently lost 16 measured sites. All three
            # runs wrote 78 rows over 78 sites, so nothing about the shape of
            # the data told the good run from the bad one.
            prev = last_by_source.get(source)
            if (prev is not None
                    and isinstance(prev.get("deep_scanned"), int)
                    and deep < prev["deep_scanned"]):
                coverage_drops.append({
                    "run_id": meta["run_id"],
                    "source": source,
                    "deep_scanned": deep,
                    "site_count": len(rows),
                    "previous_run_id": prev["run_id"],
                    "previous_deep_scanned": prev["deep_scanned"],
                    "lost": prev["deep_scanned"] - deep,
                })
            last_by_source[source] = meta

            runs_fh.write(json.dumps(meta, sort_keys=True) + "\n")
            added_runs += 1

            for r in rows:
                rec = dict(r)
                rec["run_id"] = meta["run_id"]
                rec["observed_at"] = meta["observed_at"]
                # `site` kept as an alias of site_id so existing readers and the
                # 43 assertions written against the health-only ledger keep
                # working unchanged.
                rec["site"] = r["site_id"]
                obs_fh.write(json.dumps(rec, sort_keys=True) + "\n")
                added_obs += 1

            # Components ride the same run_id, so the inventory and the facts
            # measured alongside it can never drift apart. Guarded on source
            # rather than on payload shape: another source is free to use the
            # word "components" for something that is not a WordPress plugin.
            for c in ((_component_rows(payload, by_host) or [])
                      if source == "health" else []):
                crec = dict(c)
                crec["run_id"] = meta["run_id"]
                crec["observed_at"] = meta["observed_at"]
                crec["site"] = c["site_id"]
                comp_fh.write(json.dumps(crec, sort_keys=True) + "\n")
                added_components += 1

    return {
        "runs_added": added_runs,
        "runs_skipped": skipped,
        "observations_added": added_obs,
        "components_added": added_components,
        "ledger": obs_path,
        "components_ledger": comp_path,
        "unresolved_by_run": unresolved_by_run,
        "unresolved_count": sum(len(v) for v in unresolved_by_run.values()),
        "coverage_drops": coverage_drops,
    }


def load_components(history_dir, run_id=None):
    """Component rows, optionally narrowed to one run.

    An ABSENT file returns [] and that is not the same as "this fleet runs no
    plugins". components.jsonl does not exist until the first full scan after
    2026-08-23 has been ingested, so every caller must decide what it shows
    when there are no rows -- the renderer states coverage from the INVENTORY
    rather than from these rows, so an empty ledger reads "0 of 53" instead of
    silently rendering an empty catalogue as a complete one.
    """
    path = os.path.join(history_dir, "components.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if run_id is None or r.get("run_id") == run_id:
                rows.append(r)
    return rows


def load_ledger(history_dir):
    obs_path = os.path.join(history_dir, "observations.jsonl")
    runs_path = os.path.join(history_dir, "runs.jsonl")
    runs, obs = [], []
    if os.path.exists(runs_path):
        with open(runs_path) as fh:
            runs = [json.loads(l) for l in fh if l.strip()]
    if os.path.exists(obs_path):
        with open(obs_path) as fh:
            obs = [json.loads(l) for l in fh if l.strip()]
    runs.sort(key=lambda r: r["observed_at"])
    return runs, obs


def coverage_regressions(runs):
    """Sources whose LATEST run measured fewer sites than the run before it.

    THE PUBLISH SIDE of the coverage guard. `ingest` already refuses a drop,
    and in CI that is sufficient because the publish job is gated on the
    persist job succeeding. It is not sufficient anywhere else: ingest and
    publish can happen in different sessions, and `publish-dashboard.sh` run by
    hand renders the LATEST run per source with nothing on the page saying that
    run saw less than the one before it. That is exactly how two 38-of-78
    consent runs replaced a 54-of-78 run on the live dashboard for a day.

    Reads `deep_scanned` off the run record -- the SAME number ingest computed
    from MEASURED. A fourth opinion about what "measured" means is the specific
    defect this whole area exists to prevent, so this deliberately does not
    recompute it from observations.

    Only the latest run of each source is considered. A drop three runs ago
    that has since recovered is history, not a reason to hold up today's page.

    Returns [] when everything is fine, so a caller can treat truthiness as
    "something to say".
    """
    by_source = {}
    for r in sorted(runs, key=lambda x: x["observed_at"]):
        by_source.setdefault(r.get("source"), []).append(r)

    out = []
    for source, rs in sorted(by_source.items()):
        if source is None or len(rs) < 2:
            continue
        curr, prev = rs[-1], rs[-2]
        c, p = curr.get("deep_scanned"), prev.get("deep_scanned")
        if not isinstance(c, int) or not isinstance(p, int) or c >= p:
            continue
        # A health run going full -> api-only measures zero in the wp_checked
        # family while still being a complete look at every site's control
        # plane. That is a different MODE, not a worse look, and flagging it
        # would put a standing warning on the page for normal operation --
        # `upstream_pending` in another costume.
        if curr.get("mode") and prev.get("mode") and curr["mode"] != prev["mode"]:
            continue
        out.append({
            "source": source,
            "run_id": curr["run_id"],
            "deep_scanned": c,
            "site_count": curr.get("site_count"),
            "previous_run_id": prev["run_id"],
            "previous_deep_scanned": p,
            "lost": p - c,
        })
    return out


def previous_run_of_same_source(runs, idx=-1, obs=None):
    """The newest run, and the most recent earlier COMPARABLE run of the same tool.

    Without the same-source rule, ingesting an email scan after a health scan
    makes the diff compare a Pantheon snapshot against a DNS snapshot and
    report the entire fleet as changed. Comparing like with like is not a
    nicety here.

    The same argument applies to COVERAGE, and that half was missing until
    2026-08-19. Debugging a scanner leaves one- and three-site cohort runs in
    the ledger. Diffing a 3-site cohort against the 52-site fleet run that
    follows it reports the other 49 sites as `INVENTORY: absent -> present`,
    and the dashboard's headline number becomes "51 changes needing a
    decision" when the real answer is a handful. A cohort run is a partial
    look, not a statement that the rest of the fleet vanished.

    So a candidate baseline whose site set is a STRICT SUBSET of the current
    run's is skipped. Equal sets are kept -- two full runs of the same fleet
    are exactly what should be compared. If every earlier run is a subset,
    there is no honest baseline and this returns None rather than inventing
    one.

    `obs` is optional only for backwards compatibility; without it the
    coverage rule cannot be applied and the old behaviour stands.
    """
    if not runs:
        return None, None
    curr = runs[idx]
    src = curr.get("source")
    curr_sites = _sites_in(obs, curr["run_id"]) if obs is not None else None
    # None when the source has no coverage rule, in which case rule 2 below
    # cannot be applied and rule 1 stands on its own.
    curr_measured = measured_sites(obs, curr["run_id"], src) if obs is not None else None
    for r in reversed(runs[:idx if idx != -1 else len(runs) - 1]):
        if r.get("source") != src:
            continue
        if curr_sites is not None:
            # Rule 1, since 2026-08-19: a candidate whose ROW set is a strict
            # subset is a cohort run -- a partial look, not a statement that
            # the rest of the fleet vanished.
            if _sites_in(obs, r["run_id"]) < curr_sites:
                continue
            # Rule 2, added 2026-08-20: same rows, fewer MEASUREMENTS. Consent
            # writes a row for every site whether or not the page loaded, so a
            # 38-of-78 run and a 54-of-78 run are indistinguishable under rule
            # 1. Diffing the good run against the bad one is what produced 97
            # facts "crossing the unknown boundary" on 17 sites -- coverage
            # churn dressed up as fleet change.
            #
            # The empty-set exception is load-bearing. An api-only health run
            # measures ZERO sites in the wp_checked family while still being a
            # complete look at every site's control plane. That is a different
            # MODE, not a partial look, and excluding it as a baseline would
            # discard the only comparable run in seven of this ledger's runs.
            if curr_measured is not None:
                prev_measured = measured_sites(obs, r["run_id"], src)
                if prev_measured and prev_measured < curr_measured:
                    continue
        # Rule 3, added 2026-08-22: a run taken with a DIFFERENT INSTRUMENT is
        # not a baseline, whatever its coverage.
        #
        # The consent sweep moved from a headless browser to a headed one. That
        # was not a tuning change: headless cannot see Hotjar or Meta Pixel at
        # all, because both detect automation and decline to fire. On
        # blockclub.co headless reports 4 pre-consent trackers and headed
        # reports 6, reproducibly, and all six were always firing.
        #
        # Diffed against a headless run, the first headed run is a wave of
        # ONSET rows: new problems that are not new. COVERAGE does not catch it
        # because these values never touch the UNKNOWN token -- 4 became 6.
        #
        # Absent vs absent is comparable; absent vs present is NOT. So the
        # first headed run correctly finds no baseline and emits no diff, and
        # health / email-dns / nexcess -- which declare no method at all --
        # compare exactly as they did before.
        if r.get("method") != curr.get("method"):
            continue
        return r, curr
    return None, curr


def _sites_in(obs, run_id):
    return set(o["site"] for o in obs if o["run_id"] == run_id)


def rows_for(obs, run_id):
    return {o["site"]: o for o in obs if o["run_id"] == run_id}


# --------------------------------------------------------------------------
# Change classification - the actual design proposal
# --------------------------------------------------------------------------
# Five classes, in descending order of how much a human should care. The point
# is that "a field changed" is not one thing, and a digest that treats it as
# one thing is the noise problem.

#   INVENTORY  a site appeared or disappeared. Nothing else can be trusted
#              until this is explained. Currently invisible; this is the class
#              that would have surfaced the 52-vs-54 discrepancy on its own.
#   TRANSITION a site crossed a severity boundary. The classic alert.
#   ONSET      a condition became true that was false. New problem.
#   RESOLVED   a condition became false that was true. Somebody fixed it.
#   DRIFT      a counter on an ALREADY-OPEN finding moved. Not news. This is
#              hoffmanscheese 719 -> 720. Suppressed from push by default,
#              retained in the ledger, still visible in the timeline.

#   COVERAGE   a fact went from unknown to known, or back. The TOOL started
#              or stopped being able to see something. Not a fleet change at
#              all, and the reason this class exists: the first full-mode run
#              after api-only runs produced 325 "changes", because 48 sites
#              each gained six facts at once. That is one event -- deep-scan
#              coverage arrived -- and reporting it 300 times buries the
#              handful of real changes underneath it. Collapsed in the
#              display and excluded from the headline count, like DRIFT.
CLASS_ORDER = ["INVENTORY", "TRANSITION", "ONSET", "RESOLVED", "COVERAGE", "DRIFT"]

# Classes that are real but must not inflate "changes needing a decision".
QUIET_CLASSES = ("COVERAGE", "DRIFT")

# Facts where a monotonic increase on an already-bad row is drift, not onset.
COUNTERS = ("db_backup_age_days",)


def classify(site, key, before, after, prev_row, curr_row, today):
    # Crossing the unknown boundary in either direction is the TOOL's coverage
    # changing, never the fleet's state. Checked before every other rule so it
    # covers facts added later without anyone remembering to handle it.
    if UNKNOWN in (before, after) and before != after:
        return "COVERAGE"

    # These facts ARE their source's coverage flag: they say whether the tool
    # could see the site, never how the site is. A run going api-only -> full
    # flips `wp_checked` on every site at once, and a WAF flips
    # `consent_scan_ok` on everything it blocks; each is one event and belongs
    # in the coverage summary, not as a row per site in "what changed".
    if key in COVERAGE_FLAGS:
        return "COVERAGE"

    if key in COUNTERS:
        # Did it cross a threshold that changes the answer? Then it is real.
        # Otherwise it is a clock ticking on something already reported.
        prev_bad = _backup_bad(before)
        curr_bad = _backup_bad(after)
        if prev_bad != curr_bad:
            return "TRANSITION"
        if curr_bad and prev_bad:
            return "DRIFT"
        return "ONSET" if curr_bad else "RESOLVED"

    if key in ("upstream_pending", "plugin_updates", "theme_updates"):
        b = 0 if before == UNKNOWN else before
        a = 0 if after == UNKNOWN else after
        if before == UNKNOWN or after == UNKNOWN:
            return "COVERAGE"
        if b == 0 and a > 0:
            return "ONSET"
        if b > 0 and a == 0:
            return "RESOLVED"
        return "DRIFT"

    if key == "php_version":
        return "TRANSITION"
    if key in ("plan", "framework", "env", "frozen", "wp_checked", "wp_core_update"):
        return "TRANSITION"
    return "TRANSITION"


# There used to be a second, different backup threshold here (2 days) while the
# scanner used its own. One number now, owned by the severity module.
BACKUP_CRIT_DAYS = SEV.BACKUP_CRIT_DAYS


def _backup_bad(v):
    # None and the UNKNOWN token mean the same thing here: nobody established a
    # backup age. A row from a source that does not measure backups (the email
    # check) carries neither, and must not be read as "backup is fine" OR as
    # "backup is missing".
    if v is None or v == UNKNOWN or not isinstance(v, (int, float)):
        return False
    return v > BACKUP_CRIT_DAYS


FACTS_BY_SOURCE = FACT_FAMILIES


def facts_for(row):
    """Which fact names this row actually carries.

    Diffing a health fact against an email row would compare None to None
    forever, and worse, a source changing would look like every fact changing
    at once. So the fact list follows the row's own source.
    """
    return FACTS_BY_SOURCE.get(row.get("source"), OBSERVED)


def rows_for_source(obs, run_id, source=None):
    return {o["site_id"] if "site_id" in o else o["site"]: o
            for o in obs
            if o["run_id"] == run_id and (source is None or o.get("source") == source)}


# Sites scored against an inventory that does not contain them. Surfaced by the
# CLI and the renderer rather than swallowed -- see score().
MISSED_INVENTORY = set()


def score(row, inv=None, today=None):
    """Severity for one ledger row, with the inventory's decisions merged in.

    The ledger stores only what was OBSERVED. `production` and `in_workbook`
    are human decisions and live in the inventory, so they have to be joined on
    here rather than assumed absent -- absent `production` means "nobody has
    ruled", which scores AS production, and that is the safe direction.
    """
    # Look up on site_id, falling back to `site`. Ledger rows carry both, but a
    # caller holding a row keyed the other way must not silently miss: a failed
    # lookup yields production=None, which scores AS production, so a
    # `production: false` ruling would be quietly ignored rather than applied.
    # Failing safe is the right direction; failing safe INVISIBLY is how this
    # project got a 130-row ledger for an 84-site fleet.
    key = row.get("site_id") or row.get("site")
    inv = inv or {}
    rec = inv.get(key) or {}
    if key and inv and key not in inv:
        MISSED_INVENTORY.add(key)
    merged = dict(row)
    merged["site_id"] = key
    merged["production"] = rec.get("production")
    merged["in_workbook"] = rec.get("in_workbook")
    return SEV.evaluate(merged, today)


def diff_runs(prev_rows, curr_rows, today, inv=None):
    changes = []

    gone = sorted(set(prev_rows) - set(curr_rows))
    new = sorted(set(curr_rows) - set(prev_rows))
    for s in new:
        changes.append({"class": "INVENTORY", "site": s, "fact": "site", "before": "absent", "after": "present"})
    for s in gone:
        changes.append({"class": "INVENTORY", "site": s, "fact": "site", "before": "present", "after": "absent"})

    for s in sorted(set(prev_rows) & set(curr_rows)):
        p, c = prev_rows[s], curr_rows[s]
        if p.get("source") != c.get("source"):
            changes.append({"class": "TRANSITION", "site": s, "fact": "source",
                            "before": p.get("source"), "after": c.get("source")})
            continue
        # A fact ABSENT from a row is not None, it is unknown. Runs predating a
        # fact carry no key for it at all, and `p.get(k)` returning None meant
        # the unknown-boundary check below never fired: the first full-mode run
        # reported `wp_version` as 48 separate fleet changes on the day the
        # fact was introduced. This is the "meaning of a fact changed" problem
        # the handoff left open, and defaulting to UNKNOWN is the fix.
        site_changes = []
        for k in facts_for(c):
            before, after = p.get(k, UNKNOWN), c.get(k, UNKNOWN)
            if before != after:
                site_changes.append(
                    {
                        "class": classify(s, k, before, after, p, c, today),
                        "site": s,
                        "fact": k,
                        "before": before,
                        "after": after,
                    }
                )
        changes.extend(site_changes)
        # Severity is RE-DERIVED for both sides with the CURRENT rules rather
        # than read off the stored `derived_status` the scanner wrote at the
        # time. That is the whole point of moving scoring out of the scanner:
        # retuning a threshold moves both sides together and emits NOTHING,
        # instead of reporting all 52 sites as changed with no observed fact
        # behind it.
        #
        # RULE_CHANGE therefore now means something narrower and still real:
        # the score moved with no observed fact behind it, which happens when
        # the site's `production` flag is flipped in the inventory.
        pv = score(p, inv, today)["status"]
        cv = score(c, inv, today)["status"]
        if pv != cv:
            # Only facts the score actually READS can explain a score change.
            # Without this filter, a site whose `upstream_pending` ticked 1->2
            # in the same run looked like a real transition, when the status
            # move was entirely caused by core-update state becoming visible
            # for the first time. 31 of the 33 status moves on the first
            # full-mode run were exactly that.
            real = [x for x in site_changes
                    if x["class"] != "COVERAGE" and x["fact"] in SEV.SCORING_FACTS]
            if not real:
                # The score moved only because facts that were unknown became
                # known. The site did not get worse; we started being able to
                # see it. Reporting 33 of these as TRANSITION on the first
                # full-mode run is the single loudest false alarm this tool can
                # produce, and it fires exactly once per new fact -- on the run
                # where the new fact is most worth reading calmly.
                cls = "COVERAGE"
            else:
                cls = "TRANSITION"
            if not site_changes:
                # No observed movement at all: the RULES moved. Today that
                # means a human flipped `production` in the inventory.
                cls = "RULE_CHANGE"
            changes.append({"class": cls, "site": s, "fact": "status",
                            "before": pv, "after": cv})

    order = {c: i for i, c in enumerate(CLASS_ORDER + ["RULE_CHANGE"])}
    changes.sort(key=lambda c: (order.get(c["class"], 99), c["site"], c["fact"]))
    return changes


def collapse_coverage(changes):
    """Fold COVERAGE rows into one summary per fact.

    Returns (kept, summaries). `summaries` is a list of
    {"fact", "sites", "before", "after"} -- one line each, listing the sites,
    rather than one row per site per fact.
    """
    kept, cov = [], []
    for c in changes:
        (cov if c["class"] == "COVERAGE" else kept).append(c)
    by_fact = {}
    for c in cov:
        g = by_fact.setdefault(c["fact"], {"fact": c["fact"], "sites": [],
                                           "gained": 0, "lost": 0})
        g["sites"].append(c["site"])
        # Direction, by what the values actually are. The coverage FLAGS are
        # not unknown-to-value moves at all and must not be counted as if they
        # were, so each one states its own direction in COVERAGE_DIRECTION
        # above. `status` deliberately has no entry: it is a consequence of
        # other facts becoming visible, with a real value on both sides, and
        # calling it gained or lost would be inventing a direction for
        # something that only ever moved because its inputs did.
        _dir = COVERAGE_DIRECTION.get(c["fact"])
        if _dir is not None:
            g["gained" if _dir(c["before"], c["after"]) else "lost"] += 1
        elif c["before"] == UNKNOWN and c["after"] != UNKNOWN:
            g["gained"] += 1
        elif c["after"] == UNKNOWN and c["before"] != UNKNOWN:
            g["lost"] += 1
    for g in by_fact.values():
        g["sites"].sort()
    return kept, sorted(by_fact.values(), key=lambda g: -len(g["sites"]))


# --------------------------------------------------------------------------
# Standing conditions, grouped by cause
# --------------------------------------------------------------------------
# A digest needs two halves: what CHANGED (above) and what is still true. The
# second half is where 36 rows must collapse into 1 fact, because 36 rows of
# one cause reads as a crisis and is one merge.


def _standing_consent(rows):
    """Consent findings, grouped by cause like everything else on the page.

    Added 2026-08-19 after the first real sweep. Without this the two largest
    causes on the fleet -- 34 sites with no consent tooling and 28 firing
    trackers before consent -- appeared only as per-site WARN reasons, and the
    "grouped by cause, not by site" section that exists to stop 34 findings
    reading as 34 decisions did not mention them at all.
    """
    out = []
    if not rows:
        return out

    leaking = sorted(s for s, r in rows.items()
                     if isinstance(r.get("consent_pre_trackers"), int)
                     and r["consent_pre_trackers"] > 0)
    if leaking:
        # Split, because these are two different conversations. A site with
        # tooling that leaks anyway is a BUILD defect we own. A site with no
        # tooling at all is a scope question for the client.
        tooled = [s for s in leaking if rows[s].get("consent_banner_detected") is True]
        untooled = [s for s in leaking if s not in tooled]
        if tooled:
            out.append({
                "cause": "Consent tooling present, but trackers fire before consent",
                "axis": "RISK",
                # Outranks its neighbours regardless of size: it is the only
                # group on the page describing a defect in something WE built,
                # rather than a decision the client has not made. Three sites
                # beats thirty-four when the three are ours to fix.
                "priority": 10,
                "sites": tooled,
                "detail": dict((s, rows[s].get("consent_pre_tracker_names", ""))
                               for s in tooled),
                "action": "The highest-value rows here: the banner implies consent is "
                          "being collected and the tags are not waiting for it. This is "
                          "a correctness defect in a build, not a posture question.",
            })
        if untooled:
            out.append({
                "cause": "Trackers fire before consent, and no consent tooling is present",
                "axis": "RISK",
                "sites": untooled,
                "detail": dict((s, rows[s].get("consent_pre_tracker_names", ""))
                               for s in untooled),
                "action": "One scope decision covers all %d: whether these sites are "
                          "in scope for consent tooling at all. Technical observation, "
                          "not a legal conclusion." % len(untooled),
            })

    notool = sorted(s for s, r in rows.items()
                    if r.get("consent_banner_detected") is False)
    if notool:
        out.append({
            "cause": "No consent tooling detected on the homepage",
            "axis": "RISK",
            "sites": notool,
            "action": "One decision covers all %d, not %d separate findings: which "
                      "of these need consent tooling. Sites in this group that also "
                      "fire trackers are listed separately above." % (len(notool), len(notool)),
        })

    blocked = sorted(s for s, r in rows.items()
                     if r.get("consent_scan_ok") is False)
    if blocked:
        out.append({
            "cause": "The consent sweep could not see the site",
            "axis": "COVERAGE",
            "sites": blocked,
            "detail": dict((s, "HTTP %s" % rows[s].get("consent_http_status"))
                           for s in blocked),
            # NOT "one decision covering all N". Measured 2026-08-22: every
            # one of the 20 blocked Pantheon sites answers from
            # `server: cloudflare` with `cf-mitigated: challenge`, and none
            # reaches Pantheon at all. Their zones sit across at least four
            # different DNS providers, so there is no single account and no
            # single owner to ask. Saying "one decision" sent a request to the
            # wrong vendor for two days.
            "action": "NOT one decision. The 20 CM Pantheon sites here were "
                      "measured on 2026-08-22: every one is a Cloudflare bot "
                      "challenge on the client's own zone, reaching Pantheon "
                      "not at all, across at least four DNS providers. The "
                      "remaining %d have NOT been attributed. All of them are "
                      "UNMEASURED, not clean, and no consent rule scores on "
                      "them." % max(0, len(blocked) - 20),
        })
    return out


def standing(curr_rows, today):
    """Grouped by cause, not by site. Only ever reads facts a row actually has."""
    groups = []
    health = {s: r for s, r in curr_rows.items()
              if r.get("source", "health") == "health"}
    email = {s: r for s, r in curr_rows.items() if r.get("source") == "email-dns"}
    consent = {s: r for s, r in curr_rows.items() if r.get("source") == "consent"}

    groups.extend(_standing_email(email))
    groups.extend(_standing_consent(consent))
    curr_rows = health

    upstream = sorted(s for s, r in curr_rows.items() if r.get("upstream_pending") not in (UNKNOWN, 0, None))
    if upstream:
        groups.append(
            {
                "cause": "One pending Pantheon upstream commit, unmerged",
                "axis": "DRIFT",
                "sites": upstream,
                "action": "One merge decision covers all %d sites." % len(upstream),
            }
        )

    nobackup = sorted(
        (s, r["db_backup_age_days"])
        for s, r in curr_rows.items()
        if _backup_bad(r.get("db_backup_age_days"))
    )
    if nobackup:
        plans = sorted(set(curr_rows[s].get("plan") for s, _ in nobackup))
        groups.append(
            {
                "cause": "No recent DB backup",
                "axis": "RISK",
                "sites": [s for s, _ in nobackup],
                "detail": dict(("%s" % s, "%dd, %s" % (d, curr_rows[s].get("plan")))
                               for s, d in nobackup),
                "action": "All on plan(s) %s. Sandbox plans get no automatic nightly backup, so decide whether these are production before treating as an incident."
                % ", ".join(plans),
            }
        )

    eol, expiring = [], []
    for s, r in curr_rows.items():
        tier, days = php_support(r.get("php_version"), today)
        if tier == "eol":
            eol.append((s, r.get("php_version"), r.get("plan")))
        elif tier == "expiring":
            expiring.append((s, r.get("php_version"), days))
    if eol:
        groups.append(
            {
                "cause": "PHP version past end of security support",
                "axis": "RISK",
                "sites": [s for s, _, _ in sorted(eol)],
                "detail": dict((s, "PHP %s, %s" % (v, p)) for s, v, p in eol),
                "action": "Receiving no security patches. Upgrade path is a Pantheon setting plus a compatibility check.",
            }
        )
    if expiring:
        v = expiring[0][1]
        d = expiring[0][2]
        groups.append(
            {
                "cause": "PHP %s leaves security support in %d days (%s)" % (v, d, PHP_SECURITY_EOL[v]),
                "axis": "PLANNING",
                "sites": sorted(s for s, _, _ in expiring),
                "action": "Fleet-wide deadline, not a per-site alert. Schedule the upgrade wave now; it is the only finding here with a fixed date.",
            }
        )

    unknown_deep = sorted(s for s, r in curr_rows.items() if r.get("wp_checked") is False)
    if unknown_deep:
        groups.append(
            {
                "cause": "WordPress core, plugin and theme status not observed",
                "axis": "COVERAGE",
                "sites": unknown_deep,
                "action": "API-only mode cannot see these. Any OK on these sites means clean-on-what-we-looked-at, not clean.",
            }
        )

    order = {"RISK": 0, "COVERAGE": 1, "PLANNING": 2, "DRIFT": 3}
    groups.sort(key=lambda g: order.get(g["axis"], 9))
    return groups


def _standing_email(rows):
    """Email posture, same grouping discipline: cause first, sites second."""
    if not rows:
        return []
    out = []
    no_spf = sorted(s for s, r in rows.items() if r.get("spf_present") is False)
    if no_spf:
        out.append({"axis": "RISK", "cause": "No SPF record on the sending domain",
                    "sites": no_spf,
                    "action": "Authoritative answer, genuinely absent. Mail from these "
                              "domains cannot pass SPF."})
    undet = sorted(s for s, r in rows.items() if r.get("spf_present") == UNKNOWN)
    if undet:
        out.append({"axis": "COVERAGE", "cause": "SPF could not be determined",
                    "sites": undet,
                    "action": "A finding about the lookup, not the domain. Mostly "
                              "self-inflicted resolver saturation; the next run "
                              "usually resolves it."})
    no_dmarc = sorted(s for s, r in rows.items()
                      if r.get("dmarc_at_from_present") is False)
    if no_dmarc:
        out.append({"axis": "RISK",
                    "cause": "No DMARC on the domain recipients actually see",
                    "sites": no_dmarc,
                    "action": "Nothing protects the brand domain from spoofing. Note "
                              "this is a different question from whether the provider "
                              "setup is complete."})
    monitor = sorted(s for s, r in rows.items()
                     if r.get("dmarc_at_from_policy") == "none")
    if monitor:
        out.append({"axis": "DRIFT", "cause": "DMARC published but p=none",
                    "sites": monitor,
                    "action": "Monitoring only. One policy decision covers all %d."
                              % len(monitor)})
    unaligned = sorted(s for s, r in rows.items() if r.get("relaxed_aligned") is False)
    if unaligned:
        out.append({"axis": "RISK", "cause": "From domain not aligned with sending domain",
                    "sites": unaligned,
                    "action": "DMARC fails on unaligned mail even when SPF and DKIM pass."})
    return out


# --------------------------------------------------------------------------
# Digest
# --------------------------------------------------------------------------


def render_digest(runs, obs, today):
    if len(runs) < 1:
        return "No runs ingested.\n"
    curr = runs[-1]
    curr_rows = rows_for(obs, curr["run_id"])
    out = []
    out.append("# Fleet delta - %s" % curr["observed_at"].replace("T", " "))
    out.append("")

    prev, _ = previous_run_of_same_source(runs)
    if prev is not None:
        prev_rows = rows_for(obs, prev["run_id"])
        changes = diff_runs(prev_rows, curr_rows, today)
        pushable = [c for c in changes if c["class"] != "DRIFT"]
        drift = [c for c in changes if c["class"] == "DRIFT"]

        out.append(
            "Compared with `%s` (%s earlier). %d site(s) both runs."
            % (prev["run_id"], _gap(prev["observed_at"], curr["observed_at"]), len(curr_rows))
        )
        out.append("")
        out.append("## What changed")
        out.append("")
        if not pushable:
            out.append("**Nothing that needs a decision.**")
            if drift:
                out.append("")
                out.append(
                    "%d counter(s) moved on findings already open (suppressed):"
                    % len(drift)
                )
                for c in drift:
                    out.append(
                        "- `%s` %s %s -> %s" % (c["site"], c["fact"], c["before"], c["after"])
                    )
        else:
            out.append("| Class | Site | Fact | Before | After |")
            out.append("|---|---|---|---|---|")
            for c in pushable:
                out.append(
                    "| %s | `%s` | %s | %s | %s |"
                    % (c["class"], c["site"], c["fact"], c["before"], c["after"])
                )
            if drift:
                out.append("")
                out.append("%d counter(s) moved on already-open findings, suppressed." % len(drift))
    else:
        out.append("First ingested run. No delta available; this is the baseline.")

    out.append("")
    out.append("## Still true (grouped by cause, not by site)")
    out.append("")
    for g in standing(curr_rows, today):
        out.append("**%s - %s**" % (g["axis"], g["cause"]))
        out.append("")
        out.append("- Affects: %s" % ", ".join(g["sites"][:6]) + (" ..." if len(g["sites"]) > 6 else ""))
        out.append("- %s" % g["action"])
        out.append("")

    out.append("## Coverage of this run")
    out.append("")
    out.append(
        "Mode `%s`. %d of %d sites deep-scanned. %s"
        % (
            curr["mode"],
            curr["deep_scanned"],
            curr["site_count"],
            "Three of eight fact fields were not observed on any site."
            if curr["mode"] == "api-only"
            else "",
        )
    )
    out.append("")
    return "\n".join(out)


def _gap(a, b):
    da = datetime.datetime.fromisoformat(a)
    db = datetime.datetime.fromisoformat(b)
    h = (db - da).total_seconds() / 3600.0
    if h < 48:
        return "%.0fh" % h
    return "%.0fd" % (h / 24.0)


def render_timeline(runs, obs, site=None):
    out = []
    if site:
        recs = sorted((o for o in obs if o["site"] == site), key=lambda o: o["observed_at"])
        if not recs:
            return "No observations for site %r.\n" % site
        out.append("# Timeline: %s" % site)
        inv_rec = None
        out.append("")
        # One site, several tools, one history. Each source gets its own table
        # because the facts genuinely differ; forcing them into one grid is how
        # you end up with a row of None that reads like missing data.
        for source in sorted(set(r.get("source", "health") for r in recs)):
            block = [r for r in recs if r.get("source", "health") == source]
            out.append("## source: %s" % source)
            out.append("")
            if source == "email-dns":
                out.append("| Observed | SPF | DKIM sel | DMARC@sending | DMARC@from | Aligned |")
                out.append("|---|---|---|---|---|---|")
                for r in block:
                    out.append("| %s | %s | %s | %s | %s | %s |" % (
                        r["observed_at"].replace("T", " "),
                        r.get("spf_present"), r.get("dkim_selector"),
                        r.get("dmarc_at_sending_present"),
                        r.get("dmarc_at_from_present"), r.get("relaxed_aligned")))
            else:
                out.append("| Observed | Status | Plan | PHP | Backup age | Upstream | Deep scanned |")
                out.append("|---|---|---|---|---|---|---|")
                for r in block:
                    out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                        r["observed_at"].replace("T", " "),
                        r.get("derived_status"), r.get("plan"), r.get("php_version"),
                        r.get("db_backup_age_days"), r.get("upstream_pending"),
                        r.get("wp_checked")))
            out.append("")
    else:
        out.append("# Runs in the ledger")
        out.append("")
        out.append("| Run | Observed | Source | Sites | Mode | Deep scanned | Not in inventory |")
        out.append("|---|---|---|---|---|---|---|")
        for r in runs:
            missing = r.get("sites_not_in_inventory") or []
            out.append("| %s | %s | %s | %d | %s | %d | %s |" % (
                r["run_id"], r["observed_at"].replace("T", " "), r.get("source", "?"),
                r["site_count"], r["mode"], r["deep_scanned"],
                ("**%d**" % len(missing)) if missing else "0"))
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ingest", "diff", "digest", "timeline"])
    ap.add_argument("--reports", default="./reports")
    ap.add_argument("--history", default="./history")
    ap.add_argument("--inventory", default="./data/fleet-inventory.json",
                    help="the authoritative site list. Every source is normalised "
                         "onto its site_id before storage, so one site has one "
                         "history regardless of which tool observed it.")
    ap.add_argument("--no-inventory", action="store_true",
                    help="ingest WITHOUT normalising onto site_id. Stores "
                         "whatever key each tool uses, so a site observed by "
                         "two tools gets two histories. Escape hatch for "
                         "tests; not for real data.")
    ap.add_argument("--allow-coverage-drop", action="store_true",
                    help="ingest a run that measured FEWER sites than the "
                         "previous run of the same source without failing. "
                         "The run is stored either way; this only decides "
                         "whether the exit code says so.")
    ap.add_argument("--fail-on-unresolved", action="store_true",
                    help="exit non-zero if any ingested row matched no "
                         "inventory entry. For CI, where nobody is reading "
                         "stdout.")
    ap.add_argument("--site")
    ap.add_argument("--source",
                    help="restrict to one tool: health | email-dns | "
                         "nexcess | consent")
    ap.add_argument("--today", help="override today (YYYY-MM-DD) for deterministic tests")
    ap.add_argument("--out", help="write output to this file as well as stdout")
    a = ap.parse_args()

    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()

    if a.command == "ingest":
        res = ingest(a.reports, a.history,
                     inventory=None if a.no_inventory else a.inventory)
        print(
            "ingested %d run(s), %d observation(s); %d run(s) already present -> %s"
            % (res["runs_added"], res["observations_added"], res["runs_skipped"], res["ledger"])
        )
        # An unresolved row is not dropped, it is stored under its own tool's
        # identifier. That is the right call for data, and the wrong thing to
        # do quietly: it is a second history for a site that already has one.
        if res["unresolved_count"]:
            print("", file=sys.stderr)
            print("WARNING: %d row(s) matched no inventory entry and were "
                  "stored under the tool's own key:" % res["unresolved_count"],
                  file=sys.stderr)
            for run_id in sorted(res["unresolved_by_run"]):
                names = res["unresolved_by_run"][run_id]
                shown = ", ".join(names[:8])
                if len(names) > 8:
                    shown += ", ... (%d more)" % (len(names) - 8)
                print("  %s: %s" % (run_id, shown), file=sys.stderr)
            print("Either add them to %s, or map them via host_site_name."
                  % a.inventory, file=sys.stderr)
            if a.fail_on_unresolved:
                return 1

        # Coverage going DOWN is a defect in the run. Coverage going up is
        # routine and says nothing. Direction is the whole point: the tool
        # already classified both as "COVERAGE" and suppressed them as noise,
        # which is why a 16-site loss reached the live dashboard unremarked.
        if res["coverage_drops"]:
            print("", file=sys.stderr)
            print("COVERAGE DROPPED. A run measured fewer sites than the run "
                  "before it:", file=sys.stderr)
            for d in res["coverage_drops"]:
                print("  %s  %d of %d measured, was %d in %s  (-%d)"
                      % (d["run_id"], d["deep_scanned"], d["site_count"],
                         d["previous_deep_scanned"], d["previous_run_id"],
                         d["lost"]), file=sys.stderr)
            print("", file=sys.stderr)
            print("The run(s) WERE ingested; the ledger is append-only and a "
                  "degraded measurement is still a measurement.", file=sys.stderr)
            print("But the dashboard renders the LATEST run per source, so "
                  "publishing now would replace a better", file=sys.stderr)
            print("measurement with a worse one and nothing on the page would "
                  "say so.", file=sys.stderr)
            print("", file=sys.stderr)
            print("Re-run the scan from somewhere less likely to be blocked, "
                  "or pass --allow-coverage-drop", file=sys.stderr)
            print("if the drop is real and expected.", file=sys.stderr)
            if not a.allow_coverage_drop:
                return 1
        return 0

    runs, obs = load_ledger(a.history)
    if not runs:
        print("ledger is empty; run `ingest` first", file=sys.stderr)
        return 1

    if a.command == "diff":
        if a.source:
            runs = [r for r in runs if r.get("source") == a.source]
        prev, curr = previous_run_of_same_source(runs)
        if prev is None:
            print("only one run from this source; nothing to diff")
            return 0
        print("# %s vs %s  (source: %s)" % (prev["run_id"], curr["run_id"],
                                            curr.get("source")), file=sys.stderr)
        prev_rows = rows_for(obs, prev["run_id"])
        curr_rows = rows_for(obs, curr["run_id"])
        changes = diff_runs(prev_rows, curr_rows, today)
        print(json.dumps(changes, indent=2, sort_keys=True))
        return 0

    text = render_digest(runs, obs, today) if a.command == "digest" else render_timeline(runs, obs, a.site)
    print(text)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
