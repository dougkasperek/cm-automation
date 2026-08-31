#!/usr/bin/env python3
"""
render-dashboard.py - the fleet dashboard, read from the ledger.

Reads `history/observations.jsonl` + `history/runs.jsonl` + the inventory and
emits ONE self-contained HTML file. No build step, no CDN, no fonts fetched, no
JS framework. It opens from a file:// URL and it deploys to a Worker unchanged.

This is the ledger-backed view. `render-fleet-dashboard.py` is left alone: it
powers the live "watch a scan fill in" demo, which reads a single in-progress
scan file rather than history. Two readers, two jobs. Merge them only if the
live view is ever taught to read the ledger mid-scan.

Design decisions, and why (see docs/DATA-MODEL.md for the data side):

* **Read-only.** Attestations, SSO and an audit trail come after production.
* **The lead is what CHANGED**, not the snapshot. Two health runs 14h apart
  differed by one integer across 52 sites; a page that leads with 84 rows of
  mostly-unchanged state trains people to stop reading it.
* **Causes, not sites.** 38 sites sharing one unmerged upstream commit is one
  decision, not 38 rows.
* **No chart is drawn here, deliberately, and none is pending.** The counts are
  a handful of named classes, which is a stat tile and a table, not a bar chart.
  The blocker is CADENCE, not volume: the ledger held 27 runs on 2026-08-23 and
  every one was triggered by hand, so a trend line would show when somebody ran
  the scanner rather than how the fleet moved. This said "with four runs" until
  2026-08-23, and the footer promised charts would "appear once the ledger holds
  enough runs" -- a threshold nothing implemented. Charts are a decision to be
  made after the crons are on, not something waiting on a counter.
* **Colour never carries meaning alone.** Every state chip has its text label.
  The palette is the project's validated status set, re-checked 2026-08-18 with
  the dataviz validator: light and dark both pass lightness, chroma, CVD
  separation and normal-vision separation. Light mode warns on contrast vs the
  surface, which is dischargeable only by visible labels or a table view, and
  this page is both.
"""
import argparse
import collections
import datetime
import html
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ledger", os.path.join(HERE, "fleet-ledger.py"))
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

# Same module the ledger scores with. Two scorers would be two answers.
SEV = L.SEV

# Validated status palette. Do NOT swap these for brand colours without re-running
# scripts/validate_palette.js in the dataviz skill: the deck's own severity green
# and amber fail colourblind separation at protan delta-E 3.8.
PALETTE = {
    # Chrome from [removed] (src/form.html) so the company's apps read as one
    # product: its paper, ink, hairlines and strong ink, not approximated.
    #
    # THE SEVERITY COLOURS ARE OURS AND DO NOT COME FROM SOWGEN. good/bad/info
    # were validated for colourblind separation -- the obvious green+amber pair
    # was REJECTED at protan delta-E 3.8, which is why WARN is blue here.
    # [removed]'s --good #0E7A55 / --red #B4392F have not been through that, and
    # in [removed] colour is decorative while here it carries the finding. Do not
    # unify these two sets by eye.
    #
    # `strong` is [removed]'s --navy, named for its ROLE rather than its hue: it
    # is the structural dark, and in dark mode it has to become light. A token
    # called "navy" that renders pale is how a palette starts lying.
    "light": {"good": "#1baf7a", "bad": "#eb6834", "info": "#2a78d6", "muted": "#8d9199",
              "surface": "#efefea", "card": "#ffffff", "panel2": "#f6f6f1",
              "ink": "#241e31", "ink2": "#6e6879", "faint": "#9c98a5",
              "strong": "#1c122d", "line": "#d9d8d0", "line2": "#e7e6df"},
}

# LIGHT ONLY, from 2026-08-23. There was a dark counterpart and it is gone.
#
# [removed] ships light only, so a dark mode here was the one place the two apps
# could not look alike -- and it was a second palette to keep in step, with a
# second set of contrast ratios to re-measure every time a colour moved.
#
# The page therefore paints its own ground explicitly and does not consult
# prefers-color-scheme at all. That is deliberate rather than an omission: a
# page with no background of its own inherits whatever the host is painting,
# which on a dark browser theme means this page's ink on someone else's black.

STATE_TONE = {
    "CRIT": "bad", "WARN": "info", "OK": "good", "ERROR": "info",
    "UNKNOWN": "info", "SKIP": "muted", "FROZEN": "muted",
}

# What each state means, verbatim on the page. Written out because the whole
# reason severity was rebuilt on 2026-08-19 is that the old model scored 33 of
# 52 sites CRIT and nothing OK, and a reader had no way to tell that the word
# had stopped meaning anything. A legend is cheap insurance against that
# happening quietly a second time.
STATE_MEANING = {
    "CRIT": "act now",
    "WARN": "schedule it",
    "OK": "nothing pending that needs a person",
    "UNKNOWN": "no scan of any kind has reached these",
    "SKIP": "no environment to measure",
    "FROZEN": "site frozen by Pantheon",
}
AXIS_TONE = {"RISK": "bad", "COVERAGE": "info", "PLANNING": "info", "DRIFT": "muted"}

# EVERY host a component-inventorying transport reaches. MODULE-LEVEL since
# 2026-08-27, because it was a local and the components page could not see it.
#
# The Nexcess SSH scan landed 2026-08-25 and this tuple was widened to include
# it, which fixed the DENOMINATOR -- the coverage line went from "of 53" to
# "of 75". The components page's own sentence was not touched and went on
# reading "This page can see 68 of 75 Pantheon sites", over a fleet holding 53
# Pantheon sites and 22 Nexcess. The number was right and the noun was wrong.
#
# The same sentence then said "nothing here is a statement about the 32 sites
# on other hosts", computed as everything != "CM Pantheon" -- which includes
# the 22 Nexcess sites the page DOES speak for. It disclaimed its own data.
#
# Both halves now read this tuple, so widening the transports again cannot
# leave the prose describing the previous set.
COMPONENT_HOSTS = ("CM Pantheon", "CM Nexcess")


def component_host_phrase():
    """'Pantheon and Nexcess' -- the hosts named, never a hardcoded noun."""
    names = [h.replace("CM ", "") for h in COMPONENT_HOSTS]
    if len(names) == 1:
        return names[0]
    return "%s and %s" % (", ".join(names[:-1]), names[-1])
CLASS_TONE = {"INVENTORY": "bad", "TRANSITION": "info", "ONSET": "bad",
              "RESOLVED": "good", "COVERAGE": "info", "DRIFT": "muted",
              "RULE_CHANGE": "info"}


def e(v):
    return html.escape("" if v is None else str(v))


def build_model(history_dir, inventory_path, today):
    runs, obs = L.load_ledger(history_dir)
    if not runs:
        raise SystemExit("ledger is empty; run `fleet-ledger.py ingest` first")
    _, _, inv = L.load_inventory(inventory_path)

    # THE EMAIL WORKBOOK IS A SECOND RULINGS FILE, and the sending-domain
    # comparison needs it. Loaded here rather than threaded through a flag
    # because it sits beside fleet-inventory.json and is read the same way.
    #
    # Optional on purpose: this is the rulings layer, and a render must still
    # work from the ledger alone. Absent means no comparison is drawn, never a
    # comparison against nothing.
    email_rulings = {}
    _ep = os.path.join(os.path.dirname(inventory_path) or ".",
                       "fleet-email-inventory.json")
    if os.path.exists(_ep):
        try:
            for _s in (json.load(open(_ep)).get("sites") or []):
                if _s.get("domain"):
                    email_rulings[_s["domain"]] = _s
        except (ValueError, OSError):
            email_rulings = {}

    # Latest run per (source, COHORT), and the diff against the previous run of
    # the same cohort.
    #
    # THE COHORT IS LOAD-BEARING AS OF 2026-08-25. `health` now has two
    # transports over disjoint site sets: Pantheon terminus (52 sites) and
    # Nexcess SSH (22). They can never appear in one run, so "the latest run of
    # the health source" can never represent the fleet.
    #
    # Taking one latest run per SOURCE did exactly what that implies: the
    # 22-site Nexcess run became "the latest health run" and the 52 Pantheon
    # sites lost every fact they had. The rendered page went from 310 distinct
    # components to 128, and CRIT, SKIP and FROZEN vanished entirely. Caught by
    # looking at the render, one step before it was published.
    #
    # Diffing within a cohort is also the correct comparison. A Nexcess run is
    # not the Pantheon run having lost 26 sites, and the coverage-drop guard
    # would otherwise report it as one every time.
    by_cohort = {}
    for r in runs:
        key = (r.get("source", "health"), r.get("kind") or r.get("source", "health"))
        by_cohort.setdefault(key, []).append(r)

    latest_by_cohort, changes, standing = {}, [], []
    # HOW MANY SITES CARRIED EACH FINDING LAST TIME. A backlog with no
    # direction is not actionable: "32 sites behind on WordPress" is the same
    # sentence whether it was 26 last week or 38, and those are opposite
    # situations.
    #
    # NO GUARD IS NEEDED FOR AN INSTRUMENT CHANGE, and that is not luck.
    # previous_run_of_same_source() already refuses a baseline taken with a
    # different instrument -- rule 3, added the day the consent sweep went
    # headed -- so when the browser changes `prev` is None and there is simply
    # no trend to draw. A trend computed across instruments would report new
    # visibility as a regression, which is the defect that rule exists for.
    standing_was = {}
    # source -> {site_id: row}, accumulated across that source's cohorts and
    # scored once. See the comment at the assert below.
    standing_rows = {}
    standing_prev = {}
    latest = {}
    for (source, kind), rs in by_cohort.items():
        prev, curr = L.previous_run_of_same_source(rs, obs=obs)
        latest_by_cohort[(source, kind)] = curr
        # The BASELINE is accumulated per source for the same reason the current
        # rows are. Assigning per cohort meant the second cohort's count
        # overwrote the first under the same key, so a 24-site backlog whose
        # baseline was 24 would show "was 7" and draw an arrow claiming the
        # fleet had tripled. A trend is worse than no trend when it is wrong.
        if prev is not None:
            for site_id, prow in L.rows_for(obs, prev["run_id"]).items():
                standing_prev.setdefault(source, {})[site_id] = prow
        # `latest[source]` stays the most recent run of the source overall, for
        # the freshness line and the provenance block. Facts come from
        # latest_by_cohort below, never from this.
        #
        # MOST RECENT BY observed_at, NEVER BY run_id. run_ids embed the cohort
        # name, and 'health-nexcess-<any date>' sorts after 'health-<any date>'
        # as a string ('n' > '2'), so an id compare pinned this to the Nexcess
        # cohort on every date both cohorts exist: the published feed reported
        # a day-old 22-site run as THE health run while the page, which keys
        # per kind by observed_at, showed the newer 52-site one. run_id is only
        # the tiebreak. test/test-page.py asserts this against runs.jsonl.
        _recency = lambda r: (r.get("observed_at") or "", r["run_id"])
        if source not in latest or _recency(curr) > _recency(latest[source]):
            latest[source] = curr
        rows = L.rows_for(obs, curr["run_id"])
        # STANDING IS COMPUTED PER SOURCE, NOT PER COHORT -- collected here,
        # evaluated once below. Calling standing() per cohort emits one group
        # per cohort, so a cause that BOTH health cohorts can raise appears
        # twice on the page with the fleet split across the two rows. Found
        # 2026-08-27 the moment a group existed that both could raise: the
        # plugin backlog rendered as "17 sites" and "7 sites" instead of 24,
        # each with its own action line quoting its own half as the total.
        #
        # The existing groups did not collide, but only by luck -- upstream,
        # backup and PHP read facts only the Pantheon cohort carries. That is
        # not a property to rely on; it is the same near-miss as the cohort
        # split itself.
        #
        # UNION WITHIN A SOURCE ONLY. Rows are keyed on site, and across
        # sources those keys collide hard -- 46 sites carry both a health row
        # and an email row today -- so a flat union over every cohort would
        # silently drop one of each pair. Within a source the cohorts are
        # disjoint by construction, and the assert below refuses to guess if
        # that ever stops being true.
        for site_id, row in rows.items():
            if site_id in standing_rows.setdefault(source, {}):
                raise SystemExit(
                    "two cohorts of source %r both carry %s.\n"
                    "standing() would silently keep one row and drop the other.\n"
                    "Decide which cohort owns the site before rendering."
                    % (source, site_id))
            standing_rows[source][site_id] = row
        if prev is not None:
            for c in L.diff_runs(L.rows_for(obs, prev["run_id"]), rows, today, inv):
                c["source"] = source
                c["against"] = prev["run_id"]
                changes.append(c)

    # `inv` goes in because the consent groups need the human rulings to tell a
    # defect from configured behaviour, and ours from theirs. Passed to the
    # BASELINE too: a group scored with the rulings against a baseline scored
    # without them would report the difference as a fleet change.
    for source in sorted(standing_rows):
        standing.extend(L.standing(standing_rows[source], today, inv))
    for source in sorted(standing_prev):
        for g in L.standing(standing_prev[source], today, inv):
            standing_was[g["cause"]] = len(g["sites"])

    order = {c: i for i, c in enumerate(L.CLASS_ORDER + ["RULE_CHANGE"])}
    changes.sort(key=lambda c: (order.get(c["class"], 99), c["site"], c["fact"]))
    changes, coverage_changes = L.collapse_coverage(changes)
    axis_order = {"RISK": 0, "COVERAGE": 1, "PLANNING": 2, "DRIFT": 3}
    # Within an axis, sort by an explicit priority FIRST, then by size.
    #
    # Size alone put "consent tooling present, but trackers fire before
    # consent" -- 3 sites, and the only group on the page that is a defect in
    # something clevermethod built -- fifth, below three larger groups that are
    # client scope questions. Its own text said "the highest-value rows here"
    # while sitting halfway down. Size is a decent default for "how much does
    # this cost to fix"; it is a poor one for "who has to act and how bad is
    # it", and a group that knows it outranks its neighbours should be able to
    # say so rather than hoping it is big enough.
    standing.sort(key=lambda g: (axis_order.get(g["axis"], 9),
                                 -g.get("priority", 0),
                                 -len(g["sites"])))

    # One row per site, merged across every source that has seen it.
    merged = {}
    for (source, _kind), run in sorted(latest_by_cohort.items()):
        for site_id, row in L.rows_for(obs, run["run_id"]).items():
            m = merged.setdefault(site_id, {"site_id": site_id, "sources": []})
            m["sources"].append(source)
            for k, v in row.items():
                if k not in ("run_id", "observed_at", "site", "site_id", "source"):
                    m[k] = v
    for site_id, rec in inv.items():
        m = merged.setdefault(site_id, {"site_id": site_id, "sources": []})
        # The workbook's last known values. NO LONGER RENDERED as of
        # 2026-08-20 -- see observed() -- but still carried here because
        # `in_workbook` below feeds severity's review queue, and because
        # deleting inventory data to change a display is the wrong lever.
        # A human typing 7.0.2 into a spreadsheet is a claim; a
        # scan reading it off the site is a fact. The table shows both and says
        # which is which.
        m["claimed"] = rec.get("workbook_last_known") or {}
        m["host"] = rec.get("host")
        m["host_site_name"] = rec.get("host_site_name")
        m["in_workbook"] = rec.get("in_workbook", True)
        m["reconciliation"] = rec.get("reconciliation")
        m["production"] = rec.get("production")
        # The consent rulings, alongside `production` and for the same reason:
        # a human decided them and no scan can. `consent_model` is what stops
        # an opt-out site being reported as leaking when it is doing what it
        # was configured to do.
        m["consent_managed"] = rec.get("consent_managed")
        m["consent_model"] = rec.get("consent_model")
        m["consent_rule"] = rec.get("consent_rule")
        m["consent_note"] = rec.get("consent_note")
        m["notes"] = rec.get("notes")
        m["in_inventory"] = True
    for m in merged.values():
        m.setdefault("in_inventory", False)
        m.setdefault("host", None)
        m.setdefault("production", None)

    sites = sorted(merged.values(), key=lambda s: s["site_id"])

    # Severity is computed HERE, from the stored facts, every render. The row's
    # own `derived_status` -- what the scanner thought at scan time -- is
    # deliberately not used. It is a historical record of an older model, and
    # reading it would mean a threshold change never reaching the page.
    for s_ in sites:
        s_["severity"] = SEV.evaluate(s_, today)
        s_["status"] = s_["severity"]["status"]
    health = SEV.summarise(sites, today)

    # Coverage: what was actually observed, per fact family. This is the honesty
    # layer, and it is why an OK on this page can be trusted or not.
    def frac(rows, key, want_known=True):
        seen = [r for r in rows if key in r]
        if not seen:
            return (0, 0)
        known = sum(1 for r in seen if r[key] not in (L.UNKNOWN, None))
        return (known, len(seen))

    coverage = []
    if "health" in latest:
        # PER COHORT. One line per transport, because they cover disjoint site
        # sets and a combined fraction would hide which half is missing.
        # Pantheon reports platform facts that Nexcess has no equivalent for,
        # so the two lines are not the same question either.
        for (src, kind), run in sorted(latest_by_cohort.items()):
            if src != "health":
                continue
            hr = list(L.rows_for(obs, run["run_id"]).values())
            if kind == "health-nexcess":
                coverage.append(
                    ("WordPress core, plugins, themes on Nexcess (SSH)",
                     frac(hr, "plugin_updates")))
            else:
                coverage.append(
                    ("Pantheon platform facts (plan, PHP, backups, upstream)",
                     frac(hr, "php_version")))
                coverage.append(
                    ("WordPress core, plugins, themes on Pantheon (SSH)",
                     frac(hr, "plugin_updates")))
    if "email-dns" in latest:
        er = list(L.rows_for(obs, latest["email-dns"]["run_id"]).values())
        coverage.append(("SPF", frac(er, "spf_present")))
        coverage.append(("DKIM (selector must be known to verify)", frac(er, "dkim_selector")))
        coverage.append(("DMARC", frac(er, "dmarc_at_from_present")))

    if "consent" in latest:
        cr = list(L.rows_for(obs, latest["consent"]["run_id"]).values())
        # Coverage here is "the page actually loaded", which is exactly what
        # `consent_scan_ok` records. A site behind a WAF counts as not covered.
        seen = [x for x in cr if x.get("consent_scan_ok") is True]
        coverage.append(("Cookie consent (public homepage, needs a browser)",
                         (len(seen), len(cr))))

    # Nexcess estate discovery. Deliberately NOT gated on `"nexcess" in
    # latest` like the three blocks above -- as of 2026-08-20 no Nexcess run
    # has ever completed, and a run-gated line would simply never appear.
    # That is the exact bug this box exists to prevent: it would list three
    # sources and stay silent about a fourth one that has never run, and a
    # new viewer would have no way to tell "not covered" from "not built".
    # The denominator is drawn from the INVENTORY (which sites are hosted on
    # Nexcess), not from ledger rows, so this reads "0 of 21" honestly today
    # and moves the moment a real scan lands. See CLAUDE.md, "Adding a
    # workflow to the suite", step 5 -- every future source's coverage line
    # must follow this shape, not the `if source in latest` shape above.
    # Component inventory. Same shape as the Nexcess line below and for the
    # same reason: the denominator is the INVENTORY (which sites this scan is
    # expected to reach), never the component rows themselves. Counting rows
    # would make an empty ledger read as full coverage of nothing.
    _health_runs = [r["run_id"] for (src, _k), r in latest_by_cohort.items()
                    if src == "health"]
    comp_rows = (sum((L.load_components(history_dir, rid) or []
                      for rid in sorted(_health_runs)), [])
                 if "health" in latest else [])
    pantheon_sites = [s for s in sites if s.get("host") == "CM Pantheon"]
    # EVERY host a component-inventorying transport reaches, not just Pantheon.
    # The components page was built when Pantheon was the only one. After the
    # Nexcess SSH scan landed it held 2,344 installs while still claiming to
    # cover "47 of 53" -- the Pantheon denominator -- and offered no Nexcess
    # site in its picker. A page that holds data it says it does not have is
    # the same failure as one that lacks data it claims to have.
    component_sites = [s for s in sites if s.get("host") in COMPONENT_HOSTS]
    inventoried = set(r["site_id"] for r in comp_rows)
    if component_sites:
        coverage.append(("Component inventory (plugins, mu-plugins, themes)",
                         (len(inventoried & set(s["site_id"] for s in component_sites)),
                          len(component_sites))))

    # Wordfence matching. Denominator is the INVENTORY of sites a component
    # inventory exists for, never the finding rows: an empty vulnerabilities
    # ledger and a clean fleet produce the same zero, and only one is good
    # news. Present from the day the source was registered, so the line reads
    # "0 of N" honestly before the first run rather than not appearing -- the
    # Nexcess block three sections down is here for exactly that reason.
    _vuln_runs = [r["run_id"] for (src, _k), r in latest_by_cohort.items()
                  if src == "vuln-intel"]
    vuln_rows = sum((L.load_findings(history_dir, rid) or []
                     for rid in sorted(_vuln_runs)), [])
    # The run BEFORE the latest one, so "new since the last check" is measured
    # rather than assumed. On the first run there is no baseline and nothing
    # may be called new -- everything would qualify, which would put a red
    # "act today" over advisories the world has known about for two years.
    _vuln_all = sorted({r["run_id"] for r in L.load_findings(history_dir)})
    _vuln_prev = _vuln_all[-2] if len(_vuln_all) >= 2 else None
    vuln_prev_rows = (L.load_findings(history_dir, _vuln_prev) or []
                      if _vuln_prev else [])
    vuln_matched = set(s["site_id"] for s in sites
                       if s.get("vuln_checked") is True)
    if component_sites:
        coverage.append(("Known vulnerabilities (Wordfence, matched to installs)",
                         (len(vuln_matched & set(s["site_id"] for s in component_sites)),
                          len(component_sites))))

    # THE SENDING DOMAIN, MEASURED ON THE SITE. Added 2026-08-26.
    #
    # SPF, DKIM and DMARC are all queried at the sending domain, and that value
    # was a RULING nothing had ever checked -- a person typed it into the audit
    # workbook. post-smtp stores the site's own answer, and the deep scan is
    # already inside the site, so it is one more WP-CLI call.
    #
    # DENOMINATOR FROM THE INVENTORY, like every line above it: the sites a
    # deep scan can reach at all. Counting only the rows that answered would
    # make a scan that read one site look like full coverage. The ceiling is
    # not 85 and the line says so -- 17 sites are on hosts no deep scan
    # reaches, and post-smtp is the only mailer read, so this can never be
    # complete. A partial number that states its own denominator is the point.
    if component_sites:
        _sd_known = sum(1 for s in component_sites
                        if s.get("smtp_from_domain") not in
                        (None, L.UNKNOWN, "n/a"))
        coverage.append(("Sending domain, measured on the site (post-smtp only)",
                         (_sd_known, len(component_sites))))

    nexcess_sites = [s for s in sites if s.get("host") == "CM Nexcess"]
    if nexcess_sites:
        nx_known = sum(1 for s in nexcess_sites
                        if s.get("nexcess_app_version") not in (None, L.UNKNOWN))
        coverage.append(("Nexcess estate (PHP, WordPress version, via the portal API)",
                         (nx_known, len(nexcess_sites))))

    # The From: header domain a person recorded, next to the one the site
    # reports. Attached per site rather than compared here, so the comparison
    # lives with the copy that explains it.
    for _s in sites:
        _w = email_rulings.get(_s.get("site_id")) or {}
        _fa = str(_w.get("from_address") or "")
        _s["recorded_from_domain"] = (_fa.rsplit("@", 1)[-1].lower()
                                      if "@" in _fa else None)

    unreconciled = [s for s in sites
                    if s.get("in_workbook") is False or s.get("reconciliation")]

    return {
        "runs": runs, "latest": latest, "changes": changes, "standing": standing,
        # cause -> how many sites carried it in the previous comparable run.
        # A cause absent from this map has no baseline: either it is new, or
        # the run before it was taken with a different instrument.
        "standing_was": standing_was,
        "sites": sites, "coverage": coverage, "inventory_count": len(inv),
        "components": build_components(comp_rows, sites, inventoried,
                                       component_sites),
        "vulnerabilities": build_vulnerabilities(
            vuln_rows, sites, vuln_matched, today,
            vuln_prev_rows, _vuln_prev),
        "unreconciled": unreconciled, "health": health,
        "coverage_changes": coverage_changes,
        # The latest run of a source measured fewer sites than the run before
        # it. Stated on the page rather than used to refuse a render: a page
        # that quietly shows a worse view is the failure; a page that shows it
        # and SAYS SO is not. publish-dashboard.sh reads the same function to
        # decide its exit code.
        "coverage_regressions": L.coverage_regressions(runs),
        # Which instrument produced the consent numbers on this page, and
        # whether it just changed. Both drive a notice; see render().
        "latest_by_cohort": latest_by_cohort,
        "consent_method": (latest.get("consent") or {}).get("method"),
        "consent_method_changed": bool(
            "consent" in latest
            and (latest["consent"].get("method")
                 != next((r.get("method") for r in
                          reversed(by_cohort.get(("consent", "consent"), [])[:-1])),
                         None))
            and len(by_cohort.get(("consent", "consent"), [])) > 1),
        "generated": today.isoformat(),
        # The raw inventory records and the observation rows, for page_data().
        # The page needs attestations, DNS host and decommission flags (from the
        # inventory) and per-site history series (from the observations); both
        # are already in memory here, and reading them again from disk in a
        # second place is how two readers of one file come to disagree.
        "inventory": inv,
        "obs": obs,
        "today": today,
    }


# Facts published in the JSON feed. Enumerated ON PURPOSE rather than dumping
# the internal model: this is a contract other things read, and an internal
# rename should break the emit loudly here rather than silently change an API
# somebody built against.
EMIT_FACTS = ("host", "plan", "framework", "env", "php_version", "wp_version",
              "wp_core_update", "wp_checked", "plugin_updates", "theme_updates",
              "upstream_pending", "db_backup_age_days", "frozen",
              "in_workbook", "production",
              # Control-plane facts, under their own names. A consumer that
              # wants "the WordPress version" has to choose between
              # `wp_version` and `nexcess_app_version` and therefore has to
              # know which is which, which is the point.
              "nexcess_site_id", "nexcess_unix_username", "nexcess_state",
              "nexcess_php_version", "nexcess_app_version",
              # Wordfence matching. Added here and not only to PAGE_FACTS, so
              # the JSON feed carries what the page shows -- the comment below
              # about consent is this same omission, and it shipped once.
              # `vuln_checked` is load-bearing: without it the column cannot
              # tell a site with no findings from one nothing looked at, and
              # renders both as clean.
              "vuln_checked", "vuln_affected", "vuln_nofix", "vuln_worst_cvss",
              # Consent facts. Omitted on the day the sweep landed, which meant
              # the PAGE showed 34 no-tooling and 28 leaking sites while the
              # feed next to it carried no consent data at all. The docstring
              # below says the two cannot disagree because they come from one
              # model -- true for facts that are emitted, and no protection at
              # all against a whole family being left out of this tuple.
              # test-severity.py now asserts SCORING_FACTS is a subset of this,
              # so a fact that can change a site's status cannot be invisible
              # to a consumer asking why.
              "consent_scan_ok", "consent_banner_vendor",
              "consent_banner_detected", "consent_pre_trackers",
              "consent_pre_tracker_names", "consent_mode_denied",
              "consent_http_status", "consent_final_url",
              # INVENTORY RULINGS, added 2026-08-27. Not measurements -- these
              # come from data/fleet-inventory.json, and they are here because
              # `consent_model` CHANGES THE SCORE. The same four trackers on a
              # cold load are a defect on an opt-in site and the configured
              # behaviour on an opt-out one, so a consumer reading a consent
              # finding cannot interpret it without this.
              "consent_model", "consent_managed",
              # THE GATING SWEEP, added 2026-08-28 when it was finally scored.
              # `consent_gating_leak` reads `gating_still_firing`, so by the
              # rule stated above these cannot be omitted: a fact that changes
              # a site's status must not be invisible to a consumer asking why.
              # The names matter as much as the count -- the remedy for a leak
              # is per-tag, and "2 tags" tells nobody which two.
              "gating_tested", "gating_still_firing",
              "gating_still_firing_names", "gating_stopped_names",
              "gating_cookieless_names", "gating_cold_count")


def _age_days(published, today):
    """Days since an advisory was published. None if either date is missing.

    None is reported as "age unknown", never as 0 -- a zero would sort as the
    newest finding on the page and read as disclosed today.
    """
    if not published or not today:
        return None
    try:
        d = datetime.date(*[int(x) for x in str(published)[:10].split("-")])
    except Exception:                                          # noqa: BLE001
        return None
    return (today - d).days


def build_vulnerabilities(rows, sites, matched, today=None,
                          prev_rows=None, prev_run=None):
    """Findings grouped by COMPONENT, plus the fleet counts the page leads on.

    Component-major for the same reason build_components is: the fleet table
    already answers "how many findings on this site" with a count. The question
    a count cannot answer is which component, at what version, on which sites,
    and whether an update closes it -- eight components over eleven sites on
    2026-08-31, which is eight conversations rather than fourteen.

    `unmatched` is carried explicitly. A site with no component inventory
    cannot be matched at all, and on this axis "no findings" is the best
    possible result, so a site missing from these rows must never render as
    clean. It is the same absence the hatched tokens exist for.
    """
    host = {s["site_id"]: (s.get("host") or "") for s in sites}
    by = {}
    for r in rows:
        slug = (r.get("slug") or "").lower()
        if not slug:
            continue
        cve = r.get("cve")
        g = by.setdefault((slug, cve), {
            "slug": slug, "cve": cve, "cvss": r.get("cvss"),
            "rating": r.get("rating"), "patched": r.get("patched"),
            "fix_version": r.get("fix_version"), "title": r.get("title"),
            "published": r.get("published"), "sites": [], "versions": set(),
        })
        g["sites"].append({"site_id": r["site_id"], "host": host.get(r["site_id"], ""),
                           "version": r.get("version")})
        if r.get("version"):
            g["versions"].add(str(r.get("version")))
    # (slug, cve, site) seen in the PREVIOUS run. A finding absent from this
    # set is new to us; with no previous run the set is None and NOTHING is
    # called new, because on a first run everything would be -- which would put
    # an "act today" over advisories published two years ago.
    seen_before = (None if prev_run is None else
                   {((r.get("slug") or "").lower(), r.get("cve"), r["site_id"])
                    for r in (prev_rows or [])})

    out = []
    for g in by.values():
        g["sites"].sort(key=lambda x: x["site_id"])
        g["versions"] = sorted(g["versions"])
        g["site_count"] = len({x["site_id"] for x in g["sites"]})
        # HOW LONG THE WORLD HAS KNOWN. "Critical, open 857 days" is a
        # different and more useful sentence than "critical": it names a
        # patching backlog rather than an emergency, and a page that says
        # "act today" every day for two years is not an alert.
        g["age_days"] = _age_days(g.get("published"), today)
        g["new_since_last"] = (
            False if seen_before is None else
            any((g["slug"], g["cve"], x["site_id"]) not in seen_before
                for x in g["sites"]))
        out.append(g)
    # No fix first, then by blast radius, then by score. A component nobody can
    # update out of is the only thing on this page that is not a scheduling
    # question.
    out.sort(key=lambda g: (g["patched"] is not False, -g["site_count"],
                            -(g["cvss"] or 0), g["slug"]))

    nofix = [g for g in out if g["patched"] is False]
    fixable = [g for g in out if g["patched"] is not False]
    scores = [g["cvss"] for g in out if isinstance(g["cvss"], (int, float))]
    return {
        "findings": out,
        "nofix": nofix,
        "fixable": fixable,
        # Findings, not components: one component on four sites is four.
        "n_findings": sum(g["site_count"] for g in out),
        "n_nofix": sum(g["site_count"] for g in nofix),
        "n_fixable": sum(g["site_count"] for g in fixable),
        "nofix_sites": sorted({x["site_id"] for g in nofix for x in g["sites"]}),
        "affected_sites": sorted({x["site_id"] for g in out for x in g["sites"]}),
        # UNKNOWN, never 0.0 -- a zero here would render as a measured severity.
        "worst_cvss": max(scores) if scores else None,
        "critical": [g for g in out if isinstance(g["cvss"], (int, float))
                     and g["cvss"] >= 9.0],
        # Whether a comparison was possible at all. None means no earlier run,
        # and the page must say it cannot tell rather than imply nothing is new.
        "has_baseline": prev_run is not None,
        "prev_run": prev_run,
        "matched_sites": sorted(matched),
        # Sites this source could not look at. NOT clean, and named so the page
        # can say which.
        "unmatched_sites": sorted(s["site_id"] for s in sites
                                  if s.get("host") in COMPONENT_HOSTS
                                  and s["site_id"] not in matched),
    }


def build_components(rows, sites, inventoried, expected_sites):
    """Component catalogue, keyed on (slug, type) -- never on display name.

    Plugin-major on purpose. A per-site view answers "what is pending here",
    which the fleet table already answers with a count. The question a count
    cannot answer is the one that mattered when Pods CVE-2026-19598 landed on
    2026-08-20: WHICH sites run this component, at what versions. That is a
    pivot of the same rows, and it is why this is a page rather than a popout
    hanging off a table cell.
    """
    host = {s["site_id"]: (s.get("host") or "") for s in sites}
    by = {}
    for r in rows:
        # KEYED ON LOWERCASE SLUG, since 2026-08-24. The ledger stores the slug
        # exactly as WP-CLI reported it, because that is the measurement and it
        # is the directory name on disk. But the SAME component appears under
        # different casing on different sites: `Divi-Child` on 25 sites and
        # `Divi-child` on 16, `PDFEmbedder-premium` on 11 and
        # `pdfembedder-premium` on 2. Keying on the raw slug split each into two
        # catalogue entries and inflated the distinct count from 310 to 312.
        #
        # This is not a cosmetic count problem. Wordfence publishes LOWERCASE
        # slugs, so a case-sensitive match of `pdfembedder-premium` against this
        # catalogue would hit 2 sites and miss 11, in the exact plugin family
        # this catalogue was built to answer for.
        #
        # Normalising here rather than at ingest keeps the rule this repo runs
        # on: the ledger holds what was measured, interpretation happens at
        # render time. The observed casings are preserved below in `variants`
        # so a real disagreement on disk stays visible instead of being tidied
        # away.
        k = (r["slug"].lower(), r["type"])
        g = by.setdefault(k, {"slug": r["slug"], "type": r["type"], "installs": []})
        g["installs"].append(r)
    cat = []
    for g in by.values():
        inst = sorted(g["installs"], key=lambda x: x["site_id"])
        versions = sorted(set(x.get("version") or L.UNKNOWN for x in inst))
        # Display the casing that appears on the most sites, not whichever row
        # happened to be read first. `Divi-Child` (25) beats `Divi-child` (16).
        counts = {}
        for x in inst:
            counts[x["slug"]] = counts.get(x["slug"], 0) + 1
        display_slug = max(sorted(counts), key=lambda v: counts[v])
        variants = sorted(counts)
        # SITES, not installs. A site can carry the same component twice under
        # different casing -- hoffmanscheese has pdfembedder-premium 3.2
        # inactive beside PDFEmbedder-premium 5.1.4 active -- so counting rows
        # would report 13 sites for a component that is on 12.
        site_ids = {x["site_id"] for x in inst}
        cat.append({
            "slug": display_slug,
            "type": g["type"],
            # Every casing seen on disk. One entry is the normal case.
            "variants": variants,
            "sites": len(site_ids),
            "installs_count": len(inst),
            "versions": versions,
            "pending": sum(1 for x in inst if x.get("update_available")),
            "inactive": sum(1 for x in inst if x.get("status") == "inactive"),
            "installs": [{"site_id": x["site_id"],
                          "host": host.get(x["site_id"], ""),
                          "version": x.get("version") or L.UNKNOWN,
                          "status": x.get("status") or L.UNKNOWN,
                          "update_available": bool(x.get("update_available")),
                          "update_version": x.get("update_version")}
                         for x in inst],
        })
    # Most-installed first: a component on 45 sites is the one a CVE would
    # cost most to answer for.
    cat.sort(key=lambda c: (-c["sites"], c["slug"].lower()))

    expected = set(s["site_id"] for s in expected_sites)
    return {
        "catalogue": cat,
        "rows": len(rows),
        "sites_inventoried": sorted(inventoried & expected),
        # Named, not counted. "5 sites are missing" is a number nobody can act
        # on; the list is the work.
        "sites_missing": sorted(expected - inventoried),
        "expected": sorted(expected),
        "pending_total": sum(1 for r in rows if r.get("update_available")),
    }


def emit_data(m):
    """The JSON feed, built from the SAME model object that renders the page.

    That shared origin is the whole design. The v1 pair was a page and a JSON
    blob produced by two code paths, which is how a live endpoint ends up
    disagreeing with the page next to it. Here, if the numbers below are wrong
    the page is wrong in exactly the same way, and looking at the page catches
    both.
    """
    sites = []
    for s in m["sites"]:
        sev = s.get("severity") or {}
        row = {"site_id": s["site_id"],
               "status": sev.get("status"),
               "counts_toward_fleet": sev.get("production", True),
               "reasons": sev.get("reasons", []),
               # Per-axis statuses, added 2026-08-20. `status` and `reasons`
               # above are the HEALTH axis, so a consumer that wants the
               # consent answer for a site must be able to read it here rather
               # than re-deriving it from the fact columns -- re-deriving is
               # how the page and the feed came to disagree in v1.
               "axes": sev.get("axes", {}),
               "info": sev.get("info", []),
               "sources": sorted(s.get("sources") or []),
               # `workbook_claims` was dropped from the feed 2026-08-20 with
               # the workbook columns. The inventory still holds the values and
               # `in_workbook` still feeds severity's review queue; they are
               # simply no longer published as though they were evidence.
               }
        for k in EMIT_FACTS:
            row[k] = s.get(k)
        sites.append(row)

    no_health = sorted(s["site_id"] for s in m["sites"]
                       if any(r.get("code") == "coverage_partial"
                              for r in (s.get("severity") or {}).get("reasons", [])))
    return {
        "schema": "fleet-dashboard/2",
        # The health-coverage gap, as a first-class number rather than
        # something a consumer has to re-derive from reasons. See the comment
        # on the same block in render().
        "no_health_evidence": no_health,
        # Bumped from the v1 {stamp, kind, rows} shape. A consumer written
        # against v1 must fail on the version rather than silently read fields
        # that no longer mean what they meant.
        "generated": m["generated"],
        "severity_rules": {
            "wp_security_floor": ".".join(map(str, SEV.WP_SECURITY_FLOOR)),
            "backup_crit_days": SEV.BACKUP_CRIT_DAYS,
            "backup_warn_days": SEV.BACKUP_WARN_DAYS,
            "plugin_warn_count": SEV.PLUGIN_WARN_COUNT,
            "php_security_eol": SEV.PHP_SECURITY_EOL,
        },
        "runs": {src: {"run_id": r["run_id"], "observed_at": r.get("observed_at"),
                       "site_count": r.get("site_count"),
                       "mode": r.get("mode"), "deep_scanned": r.get("deep_scanned")}
                 for src, r in m["latest"].items()},
        "health": m["health"],
        "sites": sites,
        "standing": m["standing"],
        "changes": m["changes"],
        "coverage_changes": m["coverage_changes"],
        "coverage": [{"what": w, "known": k, "of": n} for w, (k, n) in m["coverage"]],
        "inventory_count": m["inventory_count"],
    }



# ---------------------------------------------------------------------------
# EASTERN TIME
# ---------------------------------------------------------------------------
# The ledger stores `observed_at` in UTC, because a stamp is made with
# `date -u` and a run can happen on a laptop in Buffalo or a GitHub runner in
# Virginia. The PAGE is read by people in one timezone, and until 2026-08-20 it
# printed the raw UTC value with no marker at all -- so a sweep Doug ran at
# 10:57 in the morning rendered as "14:57" and looked like an afternoon run.
# A timestamp with no zone is a confident-looking value standing in for a
# missing one, same as everything else in CLAUDE.md's table.
#
# The rule is hand-rolled rather than delegated to zoneinfo because zoneinfo
# raises when the system has no tzdata, which slim containers routinely do not
# have -- and that failure would land in CI, not here. The test cross-checks it
# against zoneinfo hour by hour whenever zoneinfo IS available, so the fallback
# cannot quietly drift from the real rule.
def _second_sunday_march(y):
    d = datetime.date(y, 3, 8)
    return d + datetime.timedelta(days=(6 - d.weekday()) % 7)


def _first_sunday_november(y):
    d = datetime.date(y, 11, 1)
    return d + datetime.timedelta(days=(6 - d.weekday()) % 7)


def eastern(utc_dt):
    """UTC datetime -> (local datetime, 'EDT'|'EST').

    EDT (UTC-4) from 02:00 local on the second Sunday in March to 02:00 local
    on the first Sunday in November; EST (UTC-5) otherwise. The boundaries are
    evaluated in UTC (07:00Z and 06:00Z), which is what the rule actually says
    and avoids needing the offset to decide the offset.
    """
    y = utc_dt.year
    start = datetime.datetime.combine(_second_sunday_march(y),
                                      datetime.time(7, 0))
    end = datetime.datetime.combine(_first_sunday_november(y),
                                    datetime.time(6, 0))
    if start <= utc_dt < end:
        return utc_dt - datetime.timedelta(hours=4), "EDT"
    return utc_dt - datetime.timedelta(hours=5), "EST"


def when(observed_at):
    """Ledger timestamp -> 'Aug 20, 10:57 AM EDT'. Never silently unlabelled."""
    if not observed_at:
        return "unknown"
    try:
        utc = datetime.datetime.strptime(observed_at[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return str(observed_at)
    local, zone = eastern(utc)
    hh = local.strftime("%I").lstrip("0") or "12"
    return "%s %s, %s:%s %s %s" % (local.strftime("%b"), local.day, hh,
                                   local.strftime("%M"),
                                   local.strftime("%p"), zone)


def css():
    out = [":root{"]
    for k, v in PALETTE["light"].items():
        out.append("--%s:%s;" % (k, v))
    out.append("}")
    out.append("""
*{box-sizing:border-box}
/* Type stack, sizes and the square-cornered, uppercase-label treatment are
   [removed]'s, so the two apps read as one product. Radius is 0 throughout
   there; the only thing kept round here is the state dot, which is a dot. */
/* `background` here is load-bearing, not decoration: this page declares no
   dark variant, so without an explicit ground it would inherit the host's and
   render this ink on someone else's black. */
body{margin:0;padding:28px 20px 64px;background:var(--surface);color:var(--ink);
 font:14px/1.5 "Helvetica Neue",Helvetica,Inter,-apple-system,BlinkMacSystemFont,
 "Segoe UI",Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:25px;margin:0 0 2px;font-weight:800;letter-spacing:-.022em;
 line-height:1.08;color:var(--strong)}
h2{font-size:12.5px;margin:34px 0 10px;font-weight:800;letter-spacing:.09em;
 text-transform:uppercase;color:var(--strong)}
.sub{color:var(--ink2);font-size:13px;margin:0 0 26px}
.card{background:var(--card);border:1px solid var(--line);border-radius:0;padding:18px 20px;margin-bottom:14px}
/* Hero: one per view, >=48px, same sans, proportional figures (never tabular). */
.hero{font-size:52px;line-height:1.05;font-weight:800;letter-spacing:-.028em;margin:2px 0 4px;
 color:var(--strong)}
.hero-sub{color:var(--ink2);font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:0;padding:14px 16px}
.kpi .lab{color:var(--ink2);font-size:10.5px;margin-bottom:6px;font-weight:700;
 letter-spacing:.07em;text-transform:uppercase}
.kpi .val{font-size:26px;font-weight:800;letter-spacing:-.02em;color:var(--strong)}
.kpi .note{color:var(--ink2);font-size:12px;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:800;color:var(--ink2);font-size:10.5px;text-transform:uppercase;
 letter-spacing:.06em;padding:0 10px 8px 0;border-bottom:1px solid var(--line)}
td{padding:9px 10px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num{font-variant-numeric:tabular-nums}
code{font:11.5px/1.55 ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;color:var(--ink)}
/* Chip: colour is never the only signal. The label is always present. */
/* THE INFO DISCLOSURE. Methodology folds; qualification never does.
   A qualification says what a number is OF -- "of the 48 whose backup age can
   be read at all" -- and without it the number is wrong. Methodology says how
   the number was computed, and a reader can act on the page without it. */
details.md{margin-top:9px;border-top:1px solid var(--line2);padding-top:8px}
details.md summary{cursor:pointer;font-size:11px;font-weight:700;color:var(--ink2);
 list-style:none;display:inline-flex;align-items:center;gap:6px}
details.md summary::-webkit-details-marker{display:none}
details.md summary .ic{display:inline-flex;align-items:center;justify-content:center;
 width:15px;height:15px;border:1px solid var(--line);font-size:10px;font-weight:800;
 font-style:italic;color:var(--ink2)}
details.md summary:hover{color:var(--strong)}
details.md[open] summary{margin-bottom:7px}
details.md p{margin:0 0 7px;font-size:12px;line-height:1.55;color:var(--ink2)}
details.md p:last-child{margin-bottom:0}
.sweepline{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;
 margin:6px 0 12px;font-size:13px;padding-bottom:10px;
 border-bottom:1px solid var(--line)}
.sweeplink{color:var(--info);text-decoration:none;
 border-bottom:1px solid color-mix(in srgb,var(--info) 40%,transparent)}
.sweepline b{color:var(--strong)}
.srcdetail{margin-bottom:10px}
.srcdetail summary{cursor:pointer;font-size:11px;font-weight:800;
 letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);
 list-style:none;display:inline-block;padding:2px 0;
 border-bottom:1px solid var(--line)}
.srcdetail summary::-webkit-details-marker{display:none}
.srcdetail summary::before{content:"+ ";font-weight:800}
.srcdetail[open] summary::before{content:"\2212 "}
.srcdetail[open] summary{margin-bottom:8px}
.chgsite{border-bottom:1px solid var(--line2);padding:10px 0}
.chgsite:last-child{border-bottom:0}
.chgsite.quietonly{opacity:.72}
.chghead{font-size:13.5px;font-weight:600;color:var(--strong)}
.chglist{margin:6px 0 0;padding-left:16px;font-size:12.5px;color:var(--ink2)}
.chglist li{margin-bottom:3px}
.trendup{color:color-mix(in srgb,var(--bad) 70%,var(--ink))}
.trenddown{color:color-mix(in srgb,var(--good) 70%,var(--ink))}
.rowcount{margin-left:auto;font-size:12px;color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--line);
 padding:14px 16px;text-align:left;font:inherit;color:inherit;cursor:pointer}
.tile:hover{border-color:var(--ink2);border-left-color:var(--strong)}
.tile.bad{border-left-color:var(--bad)}
.tile.info{border-left-color:var(--info)}
.tile.on{background:var(--panel2);border-left-color:var(--strong)}
.tlab{font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
 color:var(--ink2);margin-bottom:6px}
.tnum{font-size:30px;font-weight:700;color:var(--strong);letter-spacing:-.02em;line-height:1.1}
.tnum small{font-size:13px;font-weight:600;color:var(--ink2);letter-spacing:0;margin-left:5px}
.twhy{font-size:12px;color:var(--ink2);margin-top:5px;line-height:1.45}
.covof{color:var(--faint);font-weight:400}
.covnone{color:var(--muted);font-weight:400}
.covgap{color:var(--bad)}
/* THE THREE LAYERS. A rule, a label and a sentence -- no boxes, no tint.
   The page already uses cards for content, so a tinted band around cards
   would read as a bigger card rather than as a boundary. A full-bleed rule
   with a label sitting on it is the cheapest thing that unambiguously says
   "a different kind of material starts here". */
.layer{margin:34px 0 0;padding:0}
.layer:first-of-type{margin-top:22px}
.layerhead{border-top:2px solid var(--ink);padding:10px 0 0;margin:0 0 16px}
.layerlab{font-size:11px;font-weight:800;letter-spacing:.14em;
 text-transform:uppercase;color:var(--ink)}
.layerwhy{font-size:13px;color:var(--ink2);margin-top:3px;max-width:62ch}
/* The reference layer is where a reader stops reading and starts looking
   things up. Saying so with weight rather than colour keeps it legible on
   paper and in both themes. */
.layer-reference .layerhead{border-top-width:4px}

/* JUMP LINKS. Inline under the masthead, wrapping, no sticky rail: the
   tallest section here is a 102KB table and a bar pinned to every screen
   costs more than it returns. */
.jumpnav{display:flex;flex-wrap:wrap;gap:4px 14px;margin:10px 0 0;
 font-size:12px}
.jumpnav a{color:color-mix(in srgb,var(--info) 85%,var(--ink));text-decoration:none;
 border-bottom:1px solid color-mix(in srgb,currentColor 30%,transparent)}
.jumpnav a:hover{border-bottom-color:currentColor}
.backtop{margin:18px 0 0;font-size:12px}
.backtop a{color:var(--ink2);text-decoration:none}
.backtop a:hover{color:color-mix(in srgb,var(--info) 85%,var(--ink))}
/* An anchor jump must not tuck the heading under anything, and must leave the
   heading visibly ABOVE its own content rather than flush to the top edge. */
[id]{scroll-margin-top:14px}

/* THE KEY, GROUPED. The label carries the distinction -- verdict versus no
   verdict -- so the groups need separating but not boxing. */
.keygroup + .keygroup{margin-top:16px;padding-top:14px;
 border-top:1px solid var(--line)}
.keylab{font-size:12px;font-weight:700;margin:0 0 8px}

/* ROUTINE CHANGES, FOLDED. Closed by default and it says what is inside it,
   because a fold whose summary is a bare "22 sites" is the buried-key
   mistake again. */
.quietfold{margin-top:4px}
.quietfold > summary{cursor:pointer;font-size:13px;color:var(--ink2);
 padding:8px 0}
.quietfold > summary:hover{color:var(--ink)}
.quietfold > div{padding-top:6px}

/* THE KIND KEY. Wraps to as many lines as it needs rather than scrolling: it
   is four short items and it must be readable at any width, on the phone
   included. Each item keeps its pill and gloss together, so a wrap never
   orphans a definition from the word it defines. */
.kindlegend{display:flex;flex-wrap:wrap;align-items:center;gap:6px 16px;
 margin:8px 0 0;font-size:12px;line-height:1.5}
.kindkey{display:inline-flex;align-items:baseline;gap:7px}
.kindkey .chip{position:relative;top:1px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-weight:800;
 letter-spacing:.08em;text-transform:uppercase;
 white-space:nowrap;padding:3px 8px 3px 7px;border-radius:0;
 border:1px solid color-mix(in srgb,currentColor 34%,transparent);
 background:color-mix(in srgb,currentColor 11%,transparent)}
/* THE LABEL IS DARKENED, THE DOT IS NOT. The severity hues are validated for
   colourblind SEPARATION, which is a different test from contrast against a
   white card: as drawn they measure 2.8:1 (OK) and 3.2:1 (CRIT) as text, and
   uppercasing them at 10px made that worse. Mixing the text toward --ink
   lifts both above 4.5 while the dot keeps the exact validated colour -- a
   swatch carries no text and has no ratio to meet. --ink flips in dark mode,
   so the same rule darkens on paper and lightens on the dark ground. */
/* Per-tone, not `.chip{...currentColor...}`. That first attempt lost to the
   `.good{color:var(--good)}` rule below it: equal specificity, later wins, so
   the ratios did not move at all. Measured before believing it. */
.chip.good{color:color-mix(in srgb,var(--good) 62%,var(--ink))}
.chip.bad{color:color-mix(in srgb,var(--bad) 62%,var(--ink))}
.chip.info{color:color-mix(in srgb,var(--info) 62%,var(--ink))}
.chip.muted{color:color-mix(in srgb,var(--muted) 62%,var(--ink))}
.chip .dot{width:7px;height:7px;border-radius:50%;flex:none}
.chip.good .dot{background:var(--good)}
.chip.bad .dot{background:var(--bad)}
.chip.info .dot{background:var(--info)}
.chip.muted .dot{background:var(--muted)}
.good{color:var(--good)}.bad{color:var(--bad)}.info{color:var(--info)}.muted{color:var(--muted)}
/* Meter: fill carries state, track is a lighter step of the SAME colour so the
   whole bar reads, per the marks spec. */
.meter{height:7px;border-radius:0;background:color-mix(in srgb,currentColor 18%,transparent);
 overflow:hidden;margin-top:7px}
.meter>i{display:block;height:100%;background:currentColor;border-radius:0}
.cov{display:grid;grid-template-columns:1fr auto;gap:2px 14px;align-items:baseline;margin-bottom:14px}
.cov .n{font-variant-numeric:tabular-nums;color:var(--ink2);font-size:12.5px}
.cov .m{grid-column:1/-1}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
input,select{font:inherit;font-size:12px;padding:8px 10px;border:1px solid var(--line);
 border-radius:0;background:var(--card);color:var(--ink);min-width:150px}
/* EVERY table gets its own horizontal scroller, not just the site table.
   Measured at 390px on 2026-08-23: five of the six tables sat in plain cards
   with overflow-x:visible, so the whole document scrolled sideways on a
   phone. "What changed" was 616px inside a 348px card -- and it is the
   section GETTING-STARTED tells people to read if they read only one. */
.tablewrap{overflow-x:auto}
.quiet{color:var(--ink2)}
/* input and select had no focus rule at all; only links and the state chips
   did, so keyboard users lost the outline on the filters. */
input:focus-visible,select:focus-visible{outline:2px solid var(--info);
 outline-offset:1px}
/* There was no `a` rule at all until 2026-08-23, because until then the page
   had no links. The component catalogue added 48 of them -- one per
   inventoried site in the plugin column, plus the back link -- and they all
   rendered as the browser default rgb(0,0,238) on the dark ground, about 2:1.
   Mixed toward --ink rather than using --info raw: that darkens the link in
   light mode and lightens it in dark, so both land above 4.5:1 instead of
   light mode sitting at 4.1. */
a{color:color-mix(in srgb,var(--info) 85%,var(--ink));
 text-decoration-color:color-mix(in srgb,currentColor 45%,transparent);
 text-underline-offset:2px}
a:hover{text-decoration-color:currentColor}
a:focus-visible{outline:2px solid var(--info);outline-offset:2px;border-radius:0}
.big-quiet{padding:6px 0 2px;color:var(--ink2);font-size:14px}
details{margin-top:8px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
.foot{color:var(--ink2);font-size:12px;margin-top:34px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:700px){.hero{font-size:40px}td,th{font-size:12.5px}}

/* --- the suite scoreboard, 2026-08-20 -------------------------------- */
.suite{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));margin-bottom:26px}
.wfcard{display:flex;flex-direction:column;gap:10px}
.wfhead{font-size:17px;font-weight:650;letter-spacing:-.01em}
.wfblurb{font-size:13px;line-height:1.45;color:var(--ink2)}
.wfstates{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;margin-top:2px}
.wfstate{display:flex;align-items:baseline;gap:6px}
button.wfjump{background:none;border:0;padding:2px 4px;margin:-2px -4px;font:inherit;
  cursor:pointer;border-radius:0}
button.wfjump:hover{background:rgba(0,0,0,.05)}
button.wfjump:focus-visible{outline:2px solid var(--info);outline-offset:1px}
.wfn{font-size:22px;font-weight:640;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.wfcov{margin-top:auto;padding-top:4px}
.wfbar{height:6px;border-radius:0;background:var(--line);overflow:hidden}
.wfbar i{display:block;height:100%;border-radius:0}
.wfbar i.good{background:var(--good)}
.wfbar i.info{background:var(--info)}
.wfbar i.bad{background:var(--bad)}
.wfcovlab{font-size:12.5px;color:var(--ink2);margin-top:5px}
.wfnote{font-size:12.5px;line-height:1.5;color:var(--ink2);border-top:1px solid var(--line);padding-top:9px}
.wfdetail{display:flex;flex-direction:column;gap:5px;font-size:12.5px;line-height:1.45;color:var(--ink2)}
.wfrow b{color:var(--ink);font-size:14px;font-variant-numeric:tabular-nums}
.wfmini{display:flex;flex-direction:column;gap:9px;margin:2px 0 4px}
.wfminirow{display:grid;grid-template-columns:46px 1fr 48px;align-items:center;gap:9px;font-size:12.5px;color:var(--ink2)}
.wfminilab{font-weight:600;color:var(--ink)}
.wfmininum{text-align:right;font-variant-numeric:tabular-nums}
.cellnote{font-size:11px;line-height:1.35;color:var(--ink2);margin-top:3px;max-width:150px}
/* --- compressed masthead, 2026-08-20 --------------------------------- */
.masthead{margin-bottom:12px}
.topband{display:grid;grid-template-columns:minmax(190px,0.8fr) minmax(300px,1.5fr);
 gap:26px;align-items:center;padding:16px 20px;margin-bottom:10px}
.topband .hero{font-size:46px;margin:0}
.topband .hero-sub{font-size:13px;line-height:1.45;margin-top:2px}
.topside{display:grid;gap:0}
.toprow{display:grid;grid-template-columns:34px 1fr;gap:12px;align-items:baseline;
 font-size:12.5px;line-height:1.45;color:var(--ink2);
 padding:7px 0;border-bottom:1px solid var(--line)}
.toprow:last-child{border-bottom:0;padding-bottom:0}
.toprow:first-child{padding-top:0}
.toprow b{color:var(--ink);font-size:16px;font-weight:640;text-align:right;
 font-variant-numeric:tabular-nums}
.runline{font-size:12.5px;color:var(--ink2);margin:0 0 26px}
.runline b{color:var(--ink);font-weight:600}
@media(max-width:720px){.topband{grid-template-columns:1fr;gap:16px}}
.wfminirow .wfbar{height:6px;border-radius:0;background:var(--line);overflow:hidden;display:block}
""")
    return "".join(out)


# THREE LAYERS, MARKED. Added 2026-08-27.
#
# The page is eleven sections and 168KB, of which "Every site" alone is 102KB.
# It reads as one undifferentiated scroll, so a reader has no way to tell when
# they have left the executive summary and entered supporting evidence, or when
# the evidence has given way to reference data they were never meant to read
# top to bottom.
#
# The layers are not new sections. They are boundaries around sections that
# already existed, in the order they already appeared. Nothing moved.
LAYERS = [
    ("summary", "Summary",
     "What needs a decision, and which way the fleet is moving."),
    ("detail", "Detail",
     "The evidence behind the summary: what is unresolved, what moved, and "
     "what is still open."),
    ("reference", "Complete inventory",
     "Every site and every recorded fact. Reference data, not a reading "
     "order."),
]


def layer_open(key):
    """Open a layer band. Emits the rule, the label and the anchor."""
    title = dict((k, (t, d)) for k, t, d in LAYERS)[key]
    return ('<section class="layer layer-%s" id="layer-%s">'
            '<div class=layerhead>'
            '<div class=layerlab>%s</div>'
            '<div class=layerwhy>%s</div>'
            '</div>' % (key, key, e(title[0]), e(title[1])))


def layer_close():
    return "</section>"


def jumpnav():
    """Jump links for a page nobody can scroll usefully.

    Anchors only -- no scroll-spy, no sticky rail. A sticky bar on a page whose
    tallest section is a 102KB table costs vertical space on every screen to
    solve a problem that occurs a handful of times per read.
    """
    items = [
        ("layer-summary", "Summary"),
        ("topissues-h", "Top issues"),
        ("suite", "The suite"),
        ("thekey", "The key"),
        ("rulings", "Rulings"),
        ("changed", "What changed"),
        ("stillopen", "Still open"),
        ("everysite", "Every site"),
    ]
    return ('<nav class=jumpnav aria-label="Jump to a section">%s</nav>'
            % "".join('<a href="#%s">%s</a>' % (i, e(t)) for i, t in items))


def backtotop():
    """One per layer, at its foot. The reader is 40 screens down by then."""
    return ('<p class=backtop><a href="#layer-summary">'
            '&uarr; Back to the summary</a></p>')


def chip(text, tone, title=None):
    return '<span class="chip %s"%s><span class="dot"></span>%s</span>' % (
        tone, ' title="%s"' % e(title) if title else "", e(text))


# ONE SHORT SENTENCE PER KIND. These have to read on their own beside a
# coloured pill; the folded block under the table carries the long form.
AXIS_GLOSS = {
    "RISK":     "a client is exposed now — act",
    "COVERAGE": "a scan could not see it — an absence, not a verdict",
    "PLANNING": "a fixed, fleet-wide deadline — the date is the finding",
    "DRIFT":    "a maintenance backlog — no incident, but it grows on its own",
}


def axis_legend(counts=True):
    """The always-visible key for the Kind column. See the caller for why.

    `counts=True` renders the inline strip under Top issues, prefixed "Kind" so
    it reads as a key rather than as more findings. `counts=False` renders the
    same four items inside the consolidated key, where the surrounding group
    label already says what they are.
    """
    bits = []
    for axis in ("RISK", "COVERAGE", "PLANNING", "DRIFT"):
        bits.append('<span class=kindkey>%s<span class=quiet>%s</span></span>'
                    % (chip(axis, AXIS_TONE.get(axis, "info")),
                       e(AXIS_GLOSS[axis])))
    return ('<div class=kindlegend>%s%s</div>'
            % ('<span class=quiet><b>Kind</b></span>' if counts else "",
               "".join(bits)))


# One line per source, for the provenance block. Keyed on the ledger's source
# name so a source that has never run still has an answer waiting for it.
SOURCE_ANSWERS = {
    "health":    "Pantheon platform + WP-CLI, per site",
    "consent":   "public homepage in a real browser",
    "email-dns": "public DNS, per domain",
    "nexcess":   "Nexcess control plane",
}


def md(A, title, paras):
    """A folded methodology block.

    THE SPLIT THIS IMPLEMENTS. Two kinds of text share this page and they were
    being treated as one category by anyone proposing to "reduce the prose":

      QUALIFICATION says what a number is OF. "2 sites have no recent backup,
      of the 48 whose backup age can be read at all." Fold it and the number
      becomes false. It stays inline, in the reader's path, in body type.

      METHODOLOGY says how the number was computed, which threshold applied,
      and what the tool cannot see. A reader can act on the page without it
      and needs it when they doubt a number. It folds.

    The test for which is which: if hiding the sentence would let a reader
    draw a conclusion the evidence does not support, it is qualification.
    """
    A('<details class=md><summary><span class=ic>i</span>%s</summary>' % title)
    for para in paras:
        A('<p>%s</p>' % para)
    A('</details>')


def sweep_line(A, m, e):
    """One line: how fresh is this page, and is anything lagging."""
    cohorts = m.get("latest_by_cohort") or {}
    stamps = sorted((r.get("observed_at") or "") for r in cohorts.values())
    never = [src for src in sorted(L.FACT_FAMILIES)
             if not any(k[0] == src for k in cohorts)]
    if not stamps:
        return
    newest = stamps[-1]
    lagging = [t for t in stamps
               if (datetime.datetime.fromisoformat(newest)
                   - datetime.datetime.fromisoformat(t)).days >= 1]
    A('<div class=sweepline>')
    A('<span><b>Last sweep</b> %s</span>' % e(when(newest)))
    # "cohort" is our word, not the reader's. It means one scan of one site
    # set by one transport, and nothing on the page defines it. The count is
    # of SCANS, so the line says scans. Renamed 2026-08-26.
    A('<span class=quiet>%d scan(s) &middot; %d current &middot; '
      '%d older than a day%s</span>'
      % (len(stamps), len(stamps) - len(lagging), len(lagging),
         " &middot; %d source(s) never run" % len(never) if never else ""))
    A('<a class=sweeplink href="#knows">Which tool looked, and when</a>')
    A('</div>')


def coverage_section(A, m, e):
    """The one place that says who looked, when, and at how much.

    Moved here 2026-08-23 and merged with the run line. It renders high on
    the page now -- directly under the scoreboard -- because a coverage
    caveat three sections below the number it qualifies is a caveat nobody
    reads. The per-number warnings stay inline with their numbers; only the
    general provenance moved.
    """
    # --- coverage ---------------------------------------------------------
    A('<h2 id=knows>What this page knows, and what it does not</h2>')
    # NO NAMED ARTIFACT, and no em dash. Both 2026-08-24.
    #
    # This used to say a ruling was "recorded in the inventory file". That named
    # something the reader cannot see, cannot identify and has no route to: to a
    # viewer of this page, "the inventory file" is a JSON file in a private git
    # repo. It told them a mutable thing exists and left "so where do I change
    # one" hanging, and the predictable question was "where is the inventory
    # file editing page". `Nobody edits this page` did not cover it, because it
    # denies editing HERE while the sentence before it says a person edits
    # SOMETHING.
    #
    # The distinction itself stays. Measurement vs ruling is the point of this
    # section and of the data model: the ledger holds what was measured, the
    # inventory holds what a person decided, and this page shows both and says
    # which is which. Dropping `ruling` to dodge the question would cost the
    # page its ability to say "nobody measured this, somebody decided it".
    # So: keep the two categories, describe the ruling by WHO MADE IT rather
    # than by WHERE IT LIVES, and close the question with "nothing here is
    # editable" instead of the narrower "nobody edits this page".
    # ONE SENTENCE INLINE, THE REST FOLDED. The measurement/ruling distinction
    # is how a reader interprets every number on the page, so it stays in the
    # path. Where the data lives, what is editable and why coverage sits on
    # the same screen are all methodology: useful, and not needed to read a
    # row correctly.
    A('<p class=sub style="margin:-4px 0 10px">Every value here is either a '
      '<strong>measurement</strong> or a <strong>ruling</strong>, and they are '
      'labelled. Unknown is shown as unknown, never as a pass.</p>')
    md(A, "What that distinction means, and why coverage sits here", [
        "A <b>measurement</b> was read off a site, a DNS record or a hosting "
        "API by one of the tools below, and stored in an append-only ledger. "
        "A <b>ruling</b> is a decision someone on the team has already made: "
        "which sites exist, who hosts them, and whether a site counts as "
        "production.",
        "Nothing on this page is editable. It is generated, and both the "
        "measurements and the rulings come from source data kept outside it.",
        "A green row is worth exactly as much as the coverage behind it, which "
        "is why the coverage numbers are on this screen rather than in an "
        "appendix. A page that reports 80 healthy sites without saying how "
        "many it could actually see is the failure this section exists to "
        "prevent.",
    ])

    # WHO LOOKED, AND WHEN. This used to be a bare line of timestamps under the
    # masthead, three sections above the coverage bars it explains. Provenance
    # was spread over five places on this page -- masthead, run line, suite
    # intro, this box, and the table preamble -- so a new reader had to
    # assemble it. One block, 2026-08-23.
    # EVERY REGISTERED SOURCE, not just the ones that have run. The masthead
    # used to print a tool count from `m["latest"]` and said "3 tools" while the
    # coverage bars below listed four -- Nexcess has a source in the ledger and
    # has never once run. A source that is simply absent from this block reads
    # as "not covered" when the truth is "not built yet", and the coverage line
    # for Nexcess exists precisely so nobody makes that mistake.
    # ONE ENTRY PER COHORT, not per source. `health` has two transports over
    # disjoint site sets, and this block showed a single `health` row carrying
    # the NEWER of the two timestamps against the description of the OTHER one:
    # "Aug 25 ... Pantheon platform + WP-CLI" while the Pantheon scan was two
    # days old. A freshness line that reports the wrong instrument is worse
    # than none, because a stale page nobody can tell is stale is this project
    # oldest failure.
    # ONE SWEEP LINE, then the per-source detail folded away. Five timestamp
    # cards is four more than the question deserves: the question is "how
    # fresh is this page", and the answer is one date plus whether anything is
    # lagging. The per-source detail is still here, one click away, because a
    # freshness line that reports the wrong instrument is worse than none --
    # that bug shipped once, when a single `health` row carried the Nexcess
    # timestamp against the Pantheon description. 2026-08-26.
    _cohorts = m.get("latest_by_cohort") or {}
    A('<details class=srcdetail><summary>Which tool looked, and when</summary>')
    A('<div class=card style="margin-bottom:10px"><div class=kpis>')
    _seen = set()
    for src in sorted(L.FACT_FAMILIES):
        runs = sorted((k, v) for k, v in _cohorts.items() if k[0] == src)
        if not runs:
            A('<div class=kpi><div class=lab>%s</div>'
              '<div class=val style="font-size:15px"><span class=quiet>never run'
              '</span></div><div class=note>%s</div></div>'
              % (e(src), e(SOURCE_ANSWERS.get(src, ""))))
            continue
        for (_src, kind), meta in runs:
            label = src if len(runs) == 1 else "%s (%s)" % (
                src, "nexcess" if "nexcess" in kind else "pantheon")
            note = SOURCE_ANSWERS.get(src, "")
            if len(runs) > 1:
                note = ("Nexcess SSH + WP-CLI, per site"
                        if "nexcess" in kind
                        else "Pantheon platform + WP-CLI, per site")
            A('<div class=kpi><div class=lab>%s</div>'
              '<div class=val style="font-size:15px"><span>%s</span></div>'
              '<div class=note>%s</div></div>'
              % (e(label), e(when(meta.get("observed_at"))), e(note)))
    A("</div></div></details>")

    # A coverage number that went DOWN. Directly above the coverage box,
    # because without it that box states a smaller number in the same
    # confident type as a larger one and nothing distinguishes "this is what
    # we can see" from "this is less than we could see yesterday". Two CI
    # consent runs at 38 of 78 replaced a laptop run at 54 on 2026-08-19 and
    # sat there for a day with every number on the page internally consistent.
    # The instrument, stated when it is not the one that sees everything.
    #
    # A headless browser cannot load a site behind a bot challenge, and cannot
    # see Hotjar or Meta Pixel on ANY site, because both detect automation and
    # decline to fire. Measured 2026-08-22 on blockclub.co: 4 trackers headless,
    # 6 headed, reproducibly. So a headless number is a FLOOR, and a floor
    # printed in the same confident type as a total reads as a total.
    #
    # Retires itself the moment a headed run lands.
    if m["consent_method"] != "chromium-headed":
        A('<div class="card" style="border-left:3px solid var(--bad);'
          'margin-bottom:10px">'
          '<div><b>These consent numbers are a floor, not a total.</b> They were '
          'taken with a headless browser, which cannot load a site behind a bot '
          'challenge and cannot see trackers that detect automation. '
          'Hotjar and Meta Pixel are among them.</div>'
          '<div class=quiet style="margin-top:6px">Measured on one site that '
          'headless could already read: 4 trackers headless, 6 headed. Every '
          'count below may be low, and none of them is high. Re-run the sweep '
          'to replace this.</div></div>')
    elif m["consent_method_changed"]:
        # The other half. The first headed run reports MORE trackers on many
        # sites at once, and every one was already firing. The ledger refuses
        # to diff across instruments so it produces no false ONSET rows, but a
        # person comparing this page to yesterday's still needs telling.
        A('<div class="card" style="border-left:3px solid var(--info);'
          'margin-bottom:10px">'
          '<div><b>The instrument changed: these consent numbers are not '
          'comparable to the previous run.</b> The sweep now uses a headed '
          'browser, which sees trackers a headless one cannot.</div>'
          '<div class=quiet style="margin-top:6px">A higher tracker count here '
          'is new visibility, not a fleet regression. Nothing started firing. '
          'We started being able to see it. The previous run is '
          'deliberately not used as a baseline, so no change below is derived '
          'from comparing the two.</div></div>')

    for g in m["coverage_regressions"]:
        A('<div class="card" style="border-left:3px solid var(--bad);'
          'margin-bottom:10px">'
          '<div><b>Coverage went DOWN for %s.</b> This run measured %d of %d '
          'sites; the run before it measured %d. %d site(s) that were visible '
          'are not visible now.</div>'
          '<div class=quiet style="margin-top:6px">The page below reflects the '
          'newer, smaller measurement, because it is the most recent one. That '
          'is not the same as the fleet getting worse. It is this tool '
          'seeing less. Re-run the scan before reading anything into a number '
          'that moved. (%s, against %s)</div></div>'
          % (e(g["source"]), g["deep_scanned"], g["site_count"] or 0,
             g["previous_deep_scanned"], g["lost"],
             e(g["run_id"]), e(g["previous_run_id"])))

    # WHAT IS NOT CHECKED IS THE OPERATIONAL NUMBER. "68 of 74" makes the
    # reader subtract to find the six sites nobody has looked at, and the six
    # are the reason this box exists. Both halves are printed now, with the
    # denominator kept: an exception count with no total cannot be sized.
    # 2026-08-26.
    A("<div class=card>")
    for label, (known, total) in m["coverage"]:
        pct = (100.0 * known / total) if total else 0
        tone = "good" if pct >= 99 else ("info" if pct >= 50 else "bad")
        gap = total - known
        # The component line is the only coverage row with a page behind it.
        # Linked HERE because this box is where a reader is already asking
        # "what does this page know" -- until now the only route into the
        # catalogue was one of 47 plugin-count cells in column 10 of the table
        # at the bottom, so a reader who never scrolled had no idea it existed.
        # The others stay plain: a link that goes nowhere is worse than none.
        text = e(label)
        if label.startswith("Component inventory"):
            text = ('<a href="/components">%s</a>' % text)
        A('<div class="cov %s"><div style="color:var(--ink)">%s</div>'
          '<div class=n><b>%d</b> checked &middot; %s '
          '<span class=covof>&mdash; of %d</span></div>'
          '<div class="m meter"><i style="width:%.1f%%"></i></div></div>'
          % (tone, text, known,
             ('<span class=covnone>none missing</span>' if not gap
              else '<b class=covgap>%d not checked</b>' % gap),
             total, pct))
    A("</div>")



def render(m):
    o = []
    A = o.append
    A("<!doctype html><html lang=en><meta charset=utf-8>")
    A('<meta name=viewport content="width=device-width,initial-scale=1">')
    A("<title>clevermethod fleet</title><style>%s</style>" % css())
    A('<div class=wrap>')
    # --- masthead ----------------------------------------------------------
    # COMPRESSED 2026-08-20. The hero card and a four-tile KPI row together ate
    # roughly 490px before the first workflow card, so on a laptop the suite
    # scoreboard -- the thing the page is now organised around -- started below
    # the fold. Context that never changes (how many sites, how many hosts, how
    # many tools) belongs in a line of text, not in tiles the size of the
    # numbers that DO change.
    risk = [g for g in m["standing"] if g["axis"] == "RISK"]
    pushable = [c for c in m["changes"] if c["class"] not in L.QUIET_CLASSES]
    drift = [c for c in m["changes"] if c["class"] == "DRIFT"]
    nhosts = len({s.get("host") for s in m["sites"] if s.get("host")})

    A('<div class=masthead>')
    A("<h1>clevermethod fleet</h1>")
    # NO TOOL COUNT HERE. It read `len(m["latest"])`, which counts sources that
    # have RUN, and printed "3 tools" while the coverage block listed four --
    # Nexcess has a registered source and no runs, and was given a coverage line
    # precisely so nobody could confuse "not covered" with "not built". The
    # provenance block below names them and says when each last ran.
    A('<p class=sub style="margin:2px 0 0">%d sites across %d hosts &middot; '
      'one ledger &middot; read-only</p>' % (m["inventory_count"], nhosts))
    A(jumpnav())
    A('</div>')
    A(layer_open("summary"))

    # HOW FRESH IS THIS PAGE is the first question a reader has, so the answer
    # sits directly under the masthead. It was first written inside the
    # coverage section, which put it 1,500px down, below the whole suite --
    # under the heading "What this page knows, and what it does not", which is
    # where the METHOD belongs and not where the DATE does.
    #
    # The per-scan breakdown stays down there, folded. This line is the
    # answer; that block is the evidence for it.
    sweep_line(A, m, e)

    # FOUR EXCEPTION TILES, replacing one hero and three sub-rows.
    #
    # The hero answered "what moved". The three rows beside it answered four
    # other questions in small type. A reader arriving cold needs the same
    # four answers at the same weight: is anything wrong, what is waiting on
    # ME, what moved, and what do we still not know.
    #
    # Each tile states its UNIT and is clickable: it filters the table below
    # to exactly the rows it counts. A summary number that cannot be opened is
    # a number the reader has to take on trust.
    _chg_sites = sorted({c.get("site") or c.get("site_id") for c in pushable})
    h = m["health"]
    _attention = h["counts"]["CRIT"] + h["counts"]["WARN"]
    _no_ev = [x for x in m["sites"]
              if any(r.get("code") == "coverage_partial"
                     for r in (x.get("severity") or {}).get("reasons", []))]
    A('<div class=tiles>')
    A('<button class="tile bad" data-tile="attention">'
      '<div class=tlab>Needs attention</div>'
      '<div class=tnum>%d<small>sites</small></div>'
      '<div class=twhy>%d critical, %d warning. %d excluded as '
      'non-production.</div></button>'
      % (_attention, h["counts"]["CRIT"], h["counts"]["WARN"],
         sum(h["excluded"].values())))
    A('<button class="tile info" data-tile="decisions">'
      '<div class=tlab>Rulings waiting on a person</div>'
      '<div class=tnum>%d<small>sites</small></div>'
      '<div class=twhy>No owner, no ruling. No scan can clear these.</div>'
      '</button>' % len(h["unreviewed"]))
    A('<button class="tile info" data-tile="changed">'
      '<div class=tlab>Changed since the last run</div>'
      '<div class=tnum>%d<small>sites</small></div>'
      '<div class=twhy>%d fact(s) moved. %d routine, %d coverage-only, both '
      'reported below.</div></button>'
      % (len(_chg_sites), len(pushable), len(drift),
         sum(len(g["sites"]) for g in m["coverage_changes"])))
    A('<button class="tile" data-tile="nohealth">'
      '<div class=tlab>No health evidence</div>'
      '<div class=tnum>%d<small>sites</small></div>'
      '<div class=twhy>Looked at, but no backup age and no plugin count. '
      'Not the same as healthy.</div></button>' % len(_no_ev))
    A('</div>')

    # The two counts that are not about sites keep a line of their own rather
    # than a tile, because they count CAUSES and ROWS, not sites, and putting
    # them in the same grid would invite reading them as sites.
    A('<p class=sub style="margin:10px 0 0">'
      '<b>%d</b> open risk cause(s) &middot; <b>%d</b> site(s) in one source '
      'and not the other.</p>' % (len(risk), len(m["unreconciled"])))

    # --- the suite ---------------------------------------------------------
    # ONE TILE GROUP PER QUESTION, added 2026-08-20.
    #
    # Until today the page led with a single status row that mixed two
    # unrelated questions. 38 of 70 WARN sites carried a consent finding and 7
    # were WARN for consent alone, so "fleet health" moved when the consent
    # sweep ran and nothing about maintenance had changed -- while consent
    # itself had no headline anywhere and survived as three rows inside
    # "Still true". Both problems are the same problem.
    #
    # ONLY THE ANSWER STATES ARE SHOWN PER CARD. SKIP and FROZEN are terminal
    # states of the SITE, not of a question, so repeating them on every card
    # says "3 sites are SKIP for consent", which is not a thing. They are
    # stated once, in the footer of the health card. Caught by looking at the
    # rendered page, not by a test.
    h = m["health"]
    ax = h.get("axes") or {}
    ANSWERS = ["CRIT", "WARN", "OK", "UNKNOWN"]

    def _cov(prefix):
        for w, (k, n) in m["coverage"]:
            if w.startswith(prefix):
                return k, n
        return None, None

    def _bar(known, of, label):
        if not of:
            return ""
        pct = int(round(100.0 * known / of))
        tone = "good" if pct >= 90 else ("info" if pct >= 60 else "bad")
        return ('<div class=wfbar><i class="%s" style="width:%d%%"></i></div>'
                '<div class=wfcovlab><strong>%d of %d</strong> %s</div>'
                % (tone, pct, known, of, e(label)))

    # TOP ISSUES, WITH A DIRECTION. Added 2026-08-26.
    #
    # The headline tile reads "54 sites need attention" and is correct and
    # useless: 30 of them are behind on WordPress core and 22 have a plugin
    # backlog. That is a maintenance backlog, not an exception list, and no
    # layout makes 54 amber rows actionable. What IS actionable is the cause
    # and its direction -- "45 sites have no consent tooling, up 6" names a
    # job and says whether it is being won.
    #
    # These are the same groups rendered under "Still open" further down, cut
    # to the largest few. The full list stays where it is; this is the way in.
    _top = sorted(m["standing"], key=lambda g: -len(g["sites"]))[:6]
    if _top:
        A('<h2 id=topissues-h>Top issues</h2>')
        A('<p class=sub style="margin:-4px 0 10px">Grouped by cause rather '
          'than by site, because one decision usually covers the whole group. '
          '<b>Since the previous run</b> compares against the last run of the '
          'same tool taken with the same instrument &mdash; where there is no '
          'such run, no direction is drawn rather than one being guessed.</p>')
        A('<div class="card tablewrap"><table id=topissues>'
          "<tr><th>Issue</th><th>Kind</th><th class=num>Sites</th>"
          "<th>Since the previous run</th></tr>")
        for g in _top:
            n = len(g["sites"])
            was = m["standing_was"].get(g["cause"])
            if was is None:
                trend = ('<span class=quiet title="No comparable earlier run: '
                         'the cause is new, or the run before it was taken '
                         'with a different instrument.">no baseline</span>')
            elif n > was:
                trend = ('<b class=trendup>&uarr; %d</b> '
                         '<span class=quiet>was %d</span>' % (n - was, was))
            elif n < was:
                trend = ('<b class=trenddown>&darr; %d</b> '
                         '<span class=quiet>was %d</span>' % (was - n, was))
            else:
                trend = '<span class=quiet>unchanged at %d</span>' % was
            A("<tr><td>%s</td><td>%s</td><td class=num><b>%d</b></td>"
              "<td>%s</td></tr>"
              % (e(g["cause"]),
                 chip(g["axis"], AXIS_TONE.get(g["axis"], "info"),
                      AXIS_GLOSS.get(g["axis"])),
                 n, trend))
        A("</table></div>")
        # THE KEY, UNFOLDED, DIRECTLY UNDER THE WORDS IT DEFINES.
        #
        # The first cut of this was a <details> above the table, matching every
        # other explanatory block on the page. Doug had asked what DRIFT meant;
        # shown the folded version he said "now I see it. its buried." Every
        # <details> here is closed by default -- including the one explaining
        # CRIT, WARN and OK -- so the page has no visible key anywhere and a
        # reader has no way to know a definition exists to be opened.
        #
        # A key you have to discover is not a key.
        A(axis_legend())
        # The long form stays folded, because it is depth rather than the
        # definition: the four short glosses above are the definition. What
        # earns the fold is the COLLISION -- DRIFT and COVERAGE mean something
        # else in the change feed below, on this same page.
        A('<details class=method style="margin:8px 0 0">'
          "<summary>More on the kinds, and two words that mean something else "
          "further down this page</summary><div>")
        A("<p><b>RISK</b> &mdash; a client is exposed now, and it is not "
          "waiting on anything. This is the column to act on.</p>")
        A("<p><b>COVERAGE</b> &mdash; a scan could not see the site. It says "
          "nothing about the site itself, only about what this tool "
          "established. An absence, reported as one.</p>")
        A("<p><b>PLANNING</b> &mdash; a fixed, fleet-wide deadline. Nothing is "
          "wrong today; the date is the finding.</p>")
        A("<p><b>DRIFT</b> &mdash; a maintenance backlog. Real work, no "
          "incident, and it gets worse on its own if nobody schedules it. "
          "Pending updates and unmerged upstream commits live here.</p>")
        A('<p class=quiet><b>Two of these words are reused further down the '
          "page and do not mean the same thing there.</b> In the change feed, "
          "DRIFT means a counter moved on a finding that was already open "
          "&mdash; routine, not news &mdash; and COVERAGE means the scanner "
          "started or stopped seeing a site between runs. Here they describe "
          "what KIND of problem a finding is; there they describe what KIND of "
          "change happened.</p>")
        A("</div></details>")
        A('<p class=quiet style="margin:6px 0 0">'
          '<a href="#stillopen">All %d open findings, with the sites in '
          'each</a>.</p>' % len(m["standing"]))

    A('<h2 id=suite>The suite</h2>')
    A('<p class=sub style="margin:-4px 0 10px">One card per question. A site has '
      'a status on <em>each</em> axis independently: a site can be well '
      'maintained and still leak trackers. Scored from the ledger at render '
      'time, so changing a '
      'threshold rescores all of history rather than reporting as a fleet '
      'change.</p>')
    A('<div class=suite>')

    def card(title, blurb, counts_map, cov, detail=None, note=None,
             axis=None, method=None):
        A('<div class="card wfcard">')
        A('<div class=wfhead>%s</div>' % e(title))
        A('<div class=wfblurb>%s</div>' % blurb)
        if counts_map:
            A('<div class=wfstates>')
            for st in ANSWERS:
                n = counts_map.get(st, 0)
                if not n and st in ("CRIT", "UNKNOWN"):
                    continue
                # CLICKABLE, 2026-08-23. "Every site" is 47% of the page and
                # starts 53% of the way down it -- about seven screens of
                # scrolling. Reordering the page was the obvious fix and the
                # wrong one: a reader who opens on a table where 73 of 84 rows
                # say WARN asks "is everything broken?", and the answer is in
                # the sections they just skipped. A chip that jumps to the
                # table already filtered puts the data one click from the top
                # and keeps the reading order for people who want it.
                if axis:
                    # The tooltip deliberately does NOT promise this count.
                    # Card counts exclude `production: false` sites; the table
                    # still shows them, by design. Clicking "UNKNOWN 10" on the
                    # consent card lists 11 rows, the extra being cm-whitelabel.
                    # Naming a state is honest; naming a number would not be.
                    A('<button class="wfstate wfjump" data-axis="%s" '
                      'data-state="%s" title="Filter the table below to %s '
                      '%s">%s<span class=wfn>%s</span></button>'
                      % (e(axis), e(st), e(st), e(axis),
                         chip(st, STATE_TONE.get(st, "muted")), e(n)))
                else:
                    A('<div class=wfstate>%s<span class=wfn>%s</span></div>'
                      % (chip(st, STATE_TONE.get(st, "muted")), e(n)))
            A('</div>')
        if detail:
            A('<div class=wfdetail>%s</div>' % detail)
        A('<div class=wfcov>%s</div>' % cov)
        if note:
            A('<div class=wfnote>%s</div>' % note)
        if method:
            md(A, method[0], method[1])
        A('</div>')

    # HEALTH ----------------------------------------------------------------
    nh = len([x for x in m["sites"]
              if any(r.get("code") == "coverage_partial"
                     for r in (x.get("severity") or {}).get("reasons", []))])
    # THE CARD IS FLEET-WIDE, SO ITS BAR MUST BE TOO. This read
    # `_cov("Pantheon platform facts")` and showed "48 of 52" under a card
    # whose CRIT/WARN/OK counts span all 85 sites. After the Nexcess SSH scan
    # landed, that bar described one of two transports while the numbers above
    # it described both, which reads as the card being 4 sites short of
    # complete when it is 22 sites wider than the bar.
    #
    # Sum the WordPress-inventory lines instead: they are the per-transport
    # coverage of the question this card actually asks. The individual lines
    # stay in the coverage box below, so nothing is hidden by adding them up.
    _wp_cov = [(kk, nn) for lab, (kk, nn) in m["coverage"]
               if lab.startswith("WordPress core, plugins, themes")]
    if _wp_cov:
        k, n = sum(x[0] for x in _wp_cov), sum(x[1] for x in _wp_cov)
        _bar_label = "WordPress core, plugins and themes, both transports"
    else:
        k, n = _cov("Pantheon platform facts")
        _bar_label = "Pantheon platform facts"
    terminal = []
    for st in ("SKIP", "FROZEN"):
        c = h["counts"].get(st, 0)
        if c:
            terminal.append("%d %s" % (c, st.lower()))
    if h["excluded_sites"]:
        terminal.append("%d excluded as non-production" % len(h["excluded_sites"]))
    hcodes = {}
    for x in m["sites"]:
        for r in ((x.get("severity") or {}).get("axes", {})
                  .get("health", {}).get("reasons", [])):
            hcodes[r["code"]] = hcodes.get(r["code"], 0) + 1
    # THE DENOMINATOR FOR BACKUP AGE IS NOT THE FLEET, and saying "2 have no
    # recent database backup" without saying so invites the reading that the
    # other 83 are fine. Backup age comes from `terminus backup:list`, a
    # Pantheon API call. Nexcess exposes no equivalent, so for all 22 Nexcess
    # sites it is not merely unmeasured, it is UNMEASURABLE by this tool.
    #
    # This got worse the day the Nexcess SSH scan landed: those sites moved out
    # of an honest UNKNOWN into WARN with real WordPress and plugin data, so
    # they now look well-measured while their backup status is invisible.
    _bk_known = len([x for x in m["sites"]
                     if x.get("db_backup_age_days") not in (None, L.UNKNOWN)])
    _bk_total = len(m["sites"])
    hbits = []
    for codes, label in (
            (("backup_missing", "backup_stale", "backup_aging"),
             "have no recent database backup"),
            (("core_update",), "are behind on WordPress core"),
            (("plugin_backlog",), "have a plugin backlog"),
            (("php_eol",), "run PHP past end of security support")):
        c = sum(hcodes.get(x, 0) for x in codes)
        if c:
            suffix = ""
            if "database backup" in label and _bk_known < _bk_total:
                suffix = (', of the <b>%d of %d</b> whose backup age can be '
                          'read at all' % (_bk_known, _bk_total))
            hbits.append('<span class=wfrow><b>%d</b> %s%s</span>'
                         % (c, e(label), suffix))
    card("Fleet health",
         "Is this site being maintained: backups, PHP, WordPress, plugins.",
         ax.get("health") or h["counts"], _bar(k, n, _bar_label),
         method=("How a health state is decided", [
             "Scored from the ledger at <b>render time</b>, not at scan time. "
             "Changing a threshold therefore rescores every run in history "
             "rather than reporting as a fleet change. The thresholds are "
             "named constants in one module; there is no second scorer.",
             "<b>CRIT</b> means act now: no database backup inside the "
             "threshold, a WordPress version below the security floor, or a "
             "core update waiting. <b>WARN</b> means schedule it. <b>OK</b> "
             "means nothing is pending that needs a person &mdash; it is not "
             "a statement that the site is healthy, because a site can reach "
             "OK on evidence this tool cannot gather.",
             "A rule never fires on an unknown value. That is deliberate: a "
             "site nobody measured must not fall out the bottom into OK, and "
             "it must not be scored CRIT on an absence either. It is reported "
             "as an absence, which is what the coverage line beside these "
             "counts is for.",
             "A site with no production ruling is scored <b>as production</b>. "
             "Nobody has decided, and failing safe is the point: the fleet's "
             "worst-maintained site sits on a Sandbox plan, so inferring "
             "non-production from the hosting plan would have excluded exactly "
             "the site that most needed looking at.",
         ]),
         detail="".join(hbits) or None,
         note=("<strong>%d site(s) have been looked at but have NO health "
               "evidence</strong>: no backup age, no plugin or theme count. "
               "They score WARN for that reason alone, and this is the coverage "
               "number to watch.%s"
               # The catalogue is EVIDENCE behind this card, not a fourth
               # question. "plugin backlog" above is a count; which plugins,
               # at which versions, on which sites is the same rows pivoted.
               # It gets a line here rather than a card of its own because a
               # site has no status on components -- a fourth card would
               # advertise one that does not exist. See
               # docs/VULN-INTEL-REVIEW.md section 3: vulnerabilities land on
               # THIS axis too, when they land.
               "<br><a href=\"/components\">See which plugins, themes and "
               "mu-plugins are installed, and on which sites</a>. "
               "%d component(s) across %d site(s)."
               % (nh, ("<br>Plus " + ", ".join(terminal) + ".") if terminal else "",
                  len(m["components"]["catalogue"]),
                  len(m["components"]["sites_inventoried"]))),
         axis="health")

    # CONSENT ---------------------------------------------------------------
    # The status split alone does not say what to DO. 38 WARN is two different
    # conversations: a site with no tooling at all, and a site whose tooling is
    # installed and not working. The second is worse and is invisible in a
    # single count.
    def _n_standing(frag):
        for g in m["standing"]:
            if frag in g["cause"]:
                return len(g.get("sites") or [])
        return 0
    leaks_with = _n_standing("tooling present, but trackers fire")
    leaks_without = _n_standing("Trackers fire before consent, and no consent")
    notool = _n_standing("No consent tooling detected")
    k, n = _cov("Cookie consent")
    card("Cookie consent",
         "Does the homepage fire trackers before anyone consents.",
         ax.get("consent"), _bar(k, n, "homepages the sweep could load"),
         method=("How the consent sweep works, and what it cannot see", [
             "A real browser loads the public homepage and records which "
             "third-party trackers fired <b>before any consent interaction</b>. "
             "Nothing is clicked and no cookie banner is dismissed.",
             "The counts are a <b>floor</b> whenever the sweep runs headless: "
             "some trackers detect automation and decline to fire. Measured on "
             "one site the sweep could already read: 4 trackers headless, 6 "
             "headed, reproducibly. The latest run was headed. A headless "
             "number is never high and may be low.",
             "A site behind a bot challenge returns a block page rather than "
             "the homepage. That is recorded as UNKNOWN, never as a clean "
             "result &mdash; 23 sites once read &ldquo;no banner, no "
             "trackers&rdquo; when what they had returned was HTTP 403.",
             "These are <b>observations, not compliance verdicts</b>. The "
             "words compliant and non-compliant do not appear in this "
             "workflow, and should not be added: whether a given tracker "
             "needs consent depends on jurisdiction, purpose and the "
             "controller's own basis, none of which a browser can see.",
         ]),
         detail=(
             '<span class=wfrow><b>%d</b> fire trackers before consent</span>'
             '<span class=wfrow><b>%d</b> of those have consent tooling '
             'installed that is not stopping them</span>'
             '<span class=wfrow><b>%d</b> have no consent tooling at all</span>'
             % (leaks_with + leaks_without, leaks_with, notool)),
         note="Never CRIT by design: CRIT stays a security tier so it remains a "
              "list somebody works through. <strong>UNKNOWN is a site that "
              "refused the scanner, not a clean site.</strong> Technical "
              "observations, not legal conclusions.",
         axis="consent")

    # EMAIL / DNS -----------------------------------------------------------
    # No per-site status: this answers a question about a DOMAIN. It still gets
    # a card, because leaving a live workflow off the strip reads as "we do not
    # do that" -- and it shows its three coverage fractions where the other
    # cards show states, so the card is comparable rather than half empty.
    # Sites where no sending domain was recorded, so SPF/DKIM/DMARC were never
    # queried anywhere. `spf_checked_at` names the domain actually looked up,
    # so its absence IS the absence of a recorded sending domain.
    #
    # THESE FOUR NUMBERS ARE COUNTED, AND THREE OF THEM USED TO BE WRONG OR
    # TYPED. 2026-08-26.
    #
    # `_no_sending` read `spf_present is None and not spf_checked_at`, and the
    # card printed it as "N site(s) have none recorded". That counted sites
    # with no email row AT ALL -- app.eastauroracc.com, cm-whitelabel,
    # moorseville-nc and four more that are outside the email workflow's 78
    # entirely. The sites that genuinely have no recorded sending domain carry
    # the STRING "unknown" in `spf_checked_at`, which is truthy, so not one of
    # them was counted. Both figures happened to be 7 on the day it was
    # noticed, which is why nobody noticed. Two different questions, two
    # numbers, both stated.
    _in_scope = [x for x in m["sites"] if x.get("spf_checked_at") is not None]
    _no_sending = len([x for x in _in_scope
                       if str(x.get("spf_checked_at")).lower() == L.UNKNOWN])
    _out_of_scope = len(m["sites"]) - len(_in_scope)
    # The shared sending domain was the literal number 34 in the blurb below.
    # It is right today and was never going to stay right on its own.
    _shared = collections.Counter(
        str(x["spf_checked_at"]).lower() for x in _in_scope
        if str(x.get("spf_checked_at")).lower() != L.UNKNOWN)
    _top_domain, _top_n = (_shared.most_common(1) or [("", 0)])[0]
    # MEASURED vs RECORDED, AND AGAINST THE RIGHT FIELD.
    #
    # This compared `smtp_from_domain` to `spf_checked_at` and would have
    # reported EIGHT disagreements on the first real run. All eight were false.
    # The two are different questions:
    #
    #   smtp_from_domain  the domain the mail claims to come FROM, the header
    #                     From:. It is what DMARC aligns against.
    #   spf_checked_at    the SENDING domain, where SPF and DKIM are published.
    #
    # A site can legitimately send From: sgroilawley.com through the sending
    # domain web.sgroilawley.com, and 7 of the 8 were exactly that shape.
    # The workbook records both, so the comparable field is `from_address`.
    # Against that, 37 of 39 agreed on 2026-08-26.
    #
    # AND THE MEASUREMENT CANNOT CHECK THE SENDING DOMAIN AT ALL on most
    # sites. 35 of 52 use `transport_type: mailgun_api`, where the envelope
    # sender is set by Mailgun rather than stored in the WordPress option.
    # This confirms the From: ruling; the sending-domain ruling stays a ruling.
    _measured = [x for x in m["sites"]
                 if x.get("smtp_from_domain") not in (None, L.UNKNOWN, "n/a")]
    _comparable = [x for x in _measured if x.get("recorded_from_domain")]
    _disagree = [x for x in _comparable
                 if str(x["smtp_from_domain"]).lower()
                 != str(x["recorded_from_domain"]).lower()]
    # Measured, and nobody had recorded a From: address to compare it with.
    _newly_known = [x for x in _measured if not x.get("recorded_from_domain")]
    email_causes = [g for g in m["standing"]
                    if g["axis"] == "RISK"
                    and ("DMARC" in g["cause"] or "SPF" in g["cause"]
                         or "aligned" in g["cause"])]
    # The site's OWN answer, where a deep scan could read it. Stated only once
    # a scan has actually read one: before the first run this whole block is
    # silent rather than printing "0 measured", which reads as a finding about
    # the fleet instead of a tool that has not run yet.
    _measured_note = ""
    if _measured:
        _measured_note = (
            '<div style="margin-top:6px">On <strong>%d site(s)</strong> the '
            'address the mail claims to come <em>from</em> is now '
            '<strong>measured</strong>, read out of post-smtp, and kept beside '
            'the recorded value rather than over it. Checked against the '
            '%d that have a recorded From: address: %s</div>'
            '<div class=quiet style="margin-top:4px">This does <strong>not</strong> '
            'verify the sending domain above. Most of these sites send through '
            'the Mailgun API, where the envelope sender is set by Mailgun and '
            'is not stored on the site, so the sending domain stays a ruling. '
            'The two are different: a site can legitimately send From: '
            '<code>example.com</code> through the sending domain '
            '<code>web.example.com</code>.%s</div>'
            % (len(_measured), len(_comparable),
               ('<strong>all agree</strong>.' if not _disagree
                else '<strong>%d disagree</strong> and are worth a look: %s.'
                     % (len(_disagree),
                        ", ".join("<code>%s</code>" % e(x["site_id"])
                                  for x in _disagree[:6])
                        + (" and more" if len(_disagree) > 6 else ""))),
               ('' if not _newly_known
                else ' <strong>%d site(s)</strong> had no recorded From: '
                     'address at all and now have a measured one.'
                     % len(_newly_known)))
        )
    A('<div class="card wfcard">')
    A('<div class=wfhead>Email DNS</div>')
    # WHICH DOMAIN. Victoria asked this in the 2026-08-24 review, which is the
    # question the old blurb invited: it said "can this domain send mail" over
    # a card whose three bars are measured at THREE different places. SPF and
    # DKIM are checked at the sending domain; DMARC is checked at
    # `_dmarc.<sending_domain>`, not at the site's own domain, and that rule was
    # recovered by scoring candidates against a year of the workbook's verdicts.
    # A site at example.com sending through smtp.clevermethod.net is scored on
    # smtp.clevermethod.net, and nothing on the page said so.
    A('<div class=wfblurb>Can the domain each site <em>sends from</em> '
      'authenticate its mail. Usually not the site\'s own domain: %d sites '
      'send through <code>%s</code>, so they are scored on '
      'that.</div>' % (_top_n, e(_top_domain)))
    A('<div class=wfmini>')
    for label, prefix in (("SPF", "SPF"), ("DKIM", "DKIM"), ("DMARC", "DMARC")):
        k, n = _cov(prefix)
        if n:
            pct = int(round(100.0 * k / n))
            tone = "good" if pct >= 90 else ("info" if pct >= 60 else "bad")
            A('<div class=wfminirow><span class=wfminilab>%s</span>'
              '<span class=wfbar><i class="%s" style="width:%d%%"></i></span>'
              '<span class=wfmininum>%d/%d</span></div>'
              % (e(label), tone, pct, k, n))
    A('</div>')
    # TRIMMED TO MATCH THE OTHER TWO CARDS. This carried 276 visible words
    # against 134 for fleet health and 93 for consent -- the most copy on the
    # page, for the card that answers the least urgent question.
    #
    # What stayed is the same shape the other cards use: exception lines, and
    # the one qualification a reader cannot do without. "6 have none recorded"
    # must stay in the path, because those six read UNKNOWN in every column
    # and a reader who does not know why will read the blanks as passes.
    # Everything about HOW the lookups work moved into the disclosure.
    A('<div class=wfdetail>'
      '<span class=wfrow><b>%d</b> open cause(s), listed under Still open</span>'
      '<span class=wfrow><b>%d</b> site(s) have no sending domain recorded, so '
      'every column reads UNKNOWN &mdash; never a pass</span>'
      '<span class=wfrow><b>%d</b> site(s) are outside this check and have no '
      'row in it</span>%s</div>'
      % (len(email_causes), _no_sending, _out_of_scope,
         ('<span class=wfrow><b>%d</b> site(s) now have their From: address '
          'measured off the site%s</span>'
          % (len(_measured),
             (', and <b>%d</b> disagree(s) with what was recorded' % len(_disagree))
             if _disagree else ', all agreeing with what was recorded')
          if _measured else "")))
    A('<div class=wfnote>Scored per <strong>sending domain</strong>, not per '
      'site, so it has no status chip of its own.</div>')
    # EVERY NUMBER IN HERE IS COMPUTED. The fork this was lifted from had
    # "59 of 75" and "37 of 38" typed into the prose, which is the defect this
    # project keeps finding -- and folding a number behind a disclosure makes
    # it MORE likely to go stale unnoticed, not less.
    _sd_cov = [(kk, nn) for lab, (kk, nn) in m["coverage"]
               if lab.startswith("Sending domain")]
    md(A, "Where each record is looked up, and what is not verified", [
        "SPF and DKIM are queried at the <b>sending domain</b>. DMARC is "
        "queried at <code>_dmarc.&lt;sending domain&gt;</code> and again at "
        "the domain recipients actually see, because a site sending as "
        "<code>example.com</code> through <code>web.example.com</code> has "
        "two answers and only one of them is what a recipient's mail server "
        "checks.",
        "<b>DKIM cannot be discovered.</b> A selector has to be known before "
        "it can be verified, so an unverified DKIM row means the selector is "
        "unknown &mdash; not that DKIM is absent. The two readings are "
        "opposite, and the column says which one it is showing.",
        ("The sending domain is a <b>ruling</b>. On %s the From: address is "
         "now measured off the site itself, from post-smtp's own "
         "configuration, and stored beside the ruling rather than over it, so "
         "a disagreement shows instead of resolving silently. %d of %d "
         "comparable sites agree."
         % (("%d of %d sites" % _sd_cov[0]) if _sd_cov else "some sites",
            len(_comparable) - len(_disagree), len(_comparable))),
        "That measurement does <b>not</b> verify the sending domain. Most of "
        "these sites send through the Mailgun API, where the envelope sender "
        "is set by the provider and is not stored on the site at all. It "
        "confirms the From: ruling only.",
        ("<b>%d site(s)</b> had no recorded From: address at all and now have "
         "a measured one." % len(_newly_known)) if _newly_known else
        "Every measured site had a recorded From: address to compare against.",
        "A DNS lookup that times out is recorded as unknown, never as a "
        "missing record. &ldquo;No SPF record&rdquo; once meant the resolver "
        "had not answered.",
        "Several sites share one sending domain and therefore one result, "
        "which is why this card has no per-site status. The fleet table below "
        "carries the per-site answer in its <b>Sends from</b>, SPF, DKIM and "
        "DMARC columns.",
    ])

    A('</div>')

    A('</div>')

    # --- fleet health -----------------------------------------------------
    counts, excl = h["counts"], h["excluded"]
    coverage_section(A, m, e)

    # ONE KEY, THREE GROUPS. Consolidated 2026-08-27.
    #
    # There were two keys on this page and they were nowhere near each other:
    # the site states here, and the finding kinds under Top issues 18KB up. A
    # reader hitting a DRIFT pill in the Still-open table had one key above and
    # one below, and no reason to think either existed.
    #
    # THE GROUPING IS THE POINT, and it is not cosmetic. CRIT/WARN/OK are a
    # VERDICT ON THE SITE. SKIP/FROZEN/UNKNOWN are the absence of one -- we
    # could not measure, so we are not saying. Flattening those into one row of
    # six pills is what makes a reader treat SKIP as a mild WARN, and that
    # reading is the exact failure this project keeps writing down: an absence
    # displayed as though it were a value.
    A(backtotop())
    A(layer_close())
    A(layer_open("detail"))
    A('<h2 id=thekey>The key</h2>')
    A('<p class=sub style="margin:-4px 0 10px">Every state and kind used on '
      'this page. Scored from the ledger at render time, not at scan time. '
      'Thresholds are named constants in <code>scripts/lib/severity.py</code>; '
      'changing one rescores every run in history and does not report as a '
      'fleet change.</p>')
    A("<div class=card>")

    _verdict = [st for st in SEV.ORDER if st in ("CRIT", "WARN", "OK")]
    _nomeasure = [st for st in SEV.ORDER
                  if st in ("SKIP", "FROZEN", "UNKNOWN") and counts.get(st, 0)]

    A('<div class=keygroup><div class=keylab>Site health'
      '<span class=quiet> &mdash; a verdict on the site</span></div>'
      '<div class=kpis>')
    for st in _verdict:
        A('<div class=kpi><div class=lab>%s</div><div class=val>%s</div>'
          '<div class=note>%s</div></div>'
          % (chip(st, STATE_TONE.get(st, "muted")), e(counts.get(st, 0)),
             e(STATE_MEANING.get(st, ""))))
    A("</div></div>")

    if _nomeasure:
        A('<div class=keygroup><div class=keylab>Not measurable'
          '<span class=quiet> &mdash; no verdict was reached, and that is not '
          'a mild one</span></div><div class=kpis>')
        for st in _nomeasure:
            A('<div class=kpi><div class=lab>%s</div><div class=val>%s</div>'
              '<div class=note>%s</div></div>'
              % (chip(st, STATE_TONE.get(st, "muted")), e(counts.get(st, 0)),
                 e(STATE_MEANING.get(st, ""))))
        A("</div></div>")

    A('<div class=keygroup><div class=keylab>Finding kind'
      '<span class=quiet> &mdash; what sort of problem, in the tables above'
      '</span></div>')
    A(axis_legend(counts=False))
    A("</div></div>")

    # HEALTH COVERAGE, stated separately from the status counts.
    #
    # Added 2026-08-19 with the consent sweep, because rendering the page with
    # consent facts in the ledger took UNKNOWN from 32 to ZERO. Nothing had
    # improved: the sweep reached every domain, so no site was left in "nobody
    # looked", and the number Doug named as the scoreboard silently became 0.
    #
    # UNKNOWN answers "has any scan reached this site". It never answered "do
    # we know this site's health", and the two were only ever the same number
    # by accident, while health was the only scan there was. Every source added
    # to the suite breaks that coincidence again, so the health-coverage
    # question gets its own line rather than riding on a status count.
    no_health = [s for s in m["sites"]
                 if any(r.get("code") == "coverage_partial"
                        for r in (s.get("severity") or {}).get("reasons", []))]
    #
    # THE UNKNOWN FIGURE IN THIS SENTENCE IS MEASURED, NOT TYPED. It read
    # "that number is 0" as literal copy from 2026-08-19 until 2026-08-26, and
    # it was WRONG for a day: `app.eastauroracc.com` arrived from the Nexcess
    # API on 2026-08-25 in no roster, no source had seen it, and UNKNOWN was 1
    # while the page said 0. The SSH scan reached it and took it back to 0,
    # which is the worst case -- a hardcoded claim that is usually right.
    # Counted across ALL sites, production and not, because the sentence is a
    # statement about the fleet and `counts` alone drops the excluded ones.
    unknown_n = counts.get("UNKNOWN", 0) + excl.get("UNKNOWN", 0)
    if no_health:
        A('<p class=sub style="margin:10px 0 0">The <strong>%d site(s) with no '
          'health evidence</strong> named on the health card above are NOT the '
          'same question as UNKNOWN. UNKNOWN asks whether any scan reached a '
          'site at all; %s. Coverage asks whether we '
          'know how a site is <em>maintained</em>, which is the number to '
          'watch.</p>'
          % (len(no_health),
             ('the consent sweep reaches every domain, so <strong>no site is '
              'UNKNOWN on health</strong> right now' if not unknown_n else
              '<strong>%d site(s) are UNKNOWN</strong>, reached by no scan of '
              'any kind' % unknown_n)))
        # The 32 domains used to be printed here. Measured 2026-08-23: 233px
        # of a 879px section, in a block headed "What the states mean", which
        # is not what a site list is. The same sentence already appears on the
        # health card one screen above, and the table below now has a filter
        # that reproduces the list exactly. Naming a set is not the same as
        # listing it.
        A('<p class=quiet style="margin:4px 0 0">Filter the table below by '
          '<b>No health evidence</b> to see them.</p>')

    if h["excluded_sites"]:
        A('<p class=quiet style="margin:10px 0 0">Excluded from these counts: '
          '%s. Marked <code>production: false</code> in the inventory by a '
          'person. Still scanned, still shown in the table below, and scoring '
          '%s on its own row.</p>'
          % (", ".join("<code>%s</code>" % e(x) for x in h["excluded_sites"]),
             ", ".join("%s %s" % (v, k) for k, v in excl.items() if v)))
    A("</div>")

    # --- review queue -----------------------------------------------------
    # Sites with no `production` ruling AND no workbook row: nobody has ever
    # looked at them. Deliberately NOT every site whose `production` is null,
    # which is all 84 and would be ignored.
    if h["unreviewed"]:
        # "Needs a decision" collided with the headline number, which counts
        # facts that moved. This one is a RULING waiting on a person, and no
        # scan can ever clear it. Renamed 2026-08-26.
        A('<h2 id=rulings>Rulings waiting on a person</h2>')
        A('<p class=sub style="margin:-4px 0 10px"><b>%d site(s)</b> that no '
          'scan can resolve. Each needs a person to decide something this tool '
          'cannot read off a server. Until someone does, they are counted as '
          'production, because failing safe is the point: on this fleet that '
          'set has included the two worst-maintained sites.</p>'
          % len(h["unreviewed"]))
        # THREE COLUMNS, THREE QUESTIONS, added 2026-08-27: what is unresolved,
        # why no scan can settle it, and what a person has to decide.
        #
        # THE OLD "Why it is here" COLUMN ANSWERED A DIFFERENT QUESTION on any
        # row that had health findings. It read
        # `reasons or "<the ruling text>"` -- severity reasons FIRST -- so
        # hoffmanscheese, whose ruling is missing for exactly the same reason
        # as the other four, displayed "No database backup in 730 days; 27
        # plugin updates pending" instead. Those are true, they are on the
        # site's own row two sections down, and they are not why a ruling is
        # outstanding. A reader comparing the rows would conclude the four
        # blanks were bureaucratic and this one was urgent, when the decision
        # required is identical.
        #
        # AND THE REASON IS READ FROM THE INVENTORY, not hardcoded here. The
        # fallback string was a second copy of `reconciliation` that could not
        # be corrected by editing the record it described.
        #
        # NO ACTION CONTROLS. Nothing on this page changes a site or a record,
        # and a button implying otherwise would be the first thing here that
        # lied about what the tool does.
        A("<div class=card><div class=tablewrap><table>"
          "<tr><th>Site</th><th>Unresolved</th>"
          "<th>Why no scan can settle it</th>"
          "<th>The decision</th></tr>")
        by_id = {x["site_id"]: x for x in m["sites"]}
        for sid in h["unreviewed"]:
            s_ = by_id.get(sid, {})
            st = s_.get("status")
            missing = [lab for lab, key in
                       (("owner", "owner"), ("client", "client"))
                       if not s_.get(key)]
            if s_.get("production") is None:
                missing.append("production ruling")
            # An empty list would render as a blank cell asserting nothing is
            # missing, on a row that is in this table BECAUSE something is.
            unresolved = ", ".join(missing) or "ownership record"
            # `reconciliation` is the inventory's own sentence about this site.
            # It is split on the last "Decide" because the record states the
            # situation and the decision in one string; if it does not, the
            # whole sentence is the situation and the decision column says so
            # rather than inventing one.
            rec = (s_.get("reconciliation") or "").strip()
            if "Decide" in rec:
                why, _, decision = rec.partition("Decide")
                decision = "Decide" + decision
            else:
                why, decision = rec, ""
            why = why.strip().rstrip(".") or (
                "The host account returns this site; the inventory carries no "
                "record of who owns it")
            A("<tr><td><code>%s</code> %s<div class=quiet>%s</div></td>"
              "<td>%s</td><td class=quiet>%s</td><td><b>%s</b></td></tr>"
              % (e(sid),
                 chip(st, STATE_TONE.get(st, "muted")) if st else "",
                 e(s_.get("plan") or ""),
                 e(unresolved), e(why + "."),
                 e(decision or "A person has to rule on this site; the "
                               "inventory does not record what the question "
                               "is.")))
        A("</table></div></div>")

    # --- what changed -----------------------------------------------------
    # GROUPED BY SITE. One WordPress upgrade moves three facts -- the version,
    # the update status, and the site's own status -- and as one row per fact
    # that reads as three events on three lines. The site is the unit a person
    # works in, so it is the unit the feed groups on.
    #
    # DIRECTION IS DELIBERATELY NOT LABELLED. "Improved" and "regressed" were
    # proposed and are refused: when the consent sweep changed from a headless
    # to a headed browser, tracker counts rose on many sites at once and
    # nothing had started firing -- we had started being able to see it. The
    # ledger already separates the fleet changing from the instrument
    # changing, and that classification is what drives this list. A second
    # vocabulary on top of it would be a second answer.
    A('<h2 id=changed>What changed</h2>')
    if not m["changes"]:
        A('<div class=card><p class=big-quiet>Nothing, in either source.</p></div>')
    else:
        _grouped = {}
        for c in m["changes"]:
            _grouped.setdefault(c["site"], []).append(c)
        _loud = sum(1 for cs in _grouped.values()
                    if any(x["class"] not in L.QUIET_CLASSES for x in cs))
        A('<p class=sub style="margin:-4px 0 10px"><b>%d fact(s)</b> moved '
          'across <b>%d site(s)</b> since the previous run of each tool. '
          '%d site(s) moved only on a routine counter.</p>'
          % (len(m["changes"]), len(_grouped), len(_grouped) - _loud))
        # THE ROUTINE ONES ARE FOLDED, added 2026-08-27. Today 22 of 23
        # changed sites moved only a plugin counter by one or two, and each
        # got a heading, a bullet and a pill -- 7KB of page in which the ONE
        # real transition was the first of twenty-three identical-looking
        # blocks. Sorting it to the top was not enough; it still read as one
        # item in a long list of items.
        #
        # Folded, NOT dropped. "22 sites moved only on a routine counter" with
        # no way to see which 22 is a summary standing in for the evidence,
        # and the whole point of DRIFT is that it is real and recorded. The
        # fold is open-able and names every site inside it.
        _loud_sites = [k for k in _grouped
                       if any(x["class"] not in L.QUIET_CLASSES
                              for x in _grouped[k])]
        _quiet_sites = [k for k in _grouped if k not in _loud_sites]

        def _render_site(site):
            cs = _grouped[site]
            quiet_only = site in _quiet_sites
            A('<div class="chgsite%s">' % (" quietonly" if quiet_only else ""))
            A('<div class=chghead><code>%s</code> <span class=quiet>&mdash; '
              '%d fact(s)%s</span></div>'
              % (e(site), len(cs),
                 ", all routine counter movement" if quiet_only else ""))
            A("<ul class=chglist>")
            for c in cs:
                A('<li>%s <code>%s</code> &rarr; <code>%s</code> %s</li>'
                  % (e(c["fact"]), e(c["before"]), e(c["after"]),
                     chip(c["class"], CLASS_TONE.get(c["class"], "info"))))
            A("</ul></div>")

        A("<div class=card>")
        if _loud_sites:
            for site in sorted(_loud_sites,
                               key=lambda k: (-len([x for x in _grouped[k]
                                                    if x["class"]
                                                    not in L.QUIET_CLASSES]),
                                              -len(_grouped[k]), k)):
                _render_site(site)
        else:
            A('<p class=big-quiet>No site crossed a threshold or gained a '
              'finding. Everything below is counter movement.</p>')
        if _quiet_sites:
            _qf = sum(len(_grouped[k]) for k in _quiet_sites)
            A('<details class=quietfold><summary>%d site(s), %d fact(s) '
              '&mdash; routine counter movement only, no threshold crossed'
              '</summary><div>' % (len(_quiet_sites), _qf))
            for site in sorted(_quiet_sites):
                _render_site(site)
            A("</div></details>")
        A("</div>")

    if m["coverage_changes"]:
        # RENAMED 2026-08-23. It was "What this tool can now see", which a
        # first-time reader takes as "new tooling was added". It is not that:
        # it fires on any coverage change in EITHER direction since the
        # previous run -- an SSH key landing, a WAF blocking four sites, an
        # api-only run reading no WordPress. The direction is the point, so
        # the title has to carry both.
        A("<h2>What the scanner started, or stopped, being able to see</h2>")
        A('<p class=sub style="margin:-4px 0 10px">Since the previous run of '
          'each tool. These are facts that crossed the line between unknown and '
          'known, in either direction: <strong>our visibility changing, '
          'not the fleet</strong>. A fact going dark is a defect in the run, not '
          'good news. One line per fact rather than one row per site: the first '
          'full-mode run gave 48 sites six new facts each, which is one event, '
          'not 288 of them.</p>')
        A("<div class=card><div class=tablewrap><table>"
          "<tr><th>Fact</th><th>Became visible</th>"
          "<th>Went dark</th><th>Sites</th></tr>")
        for g in m["coverage_changes"]:
            A("<tr><td><code>%s</code></td><td class=num>%s</td>"
              "<td class=num>%s</td><td><details><summary>%d site(s)</summary>"
              '<div class=quiet style="margin-top:6px">%s</div></details></td></tr>'
              % (e(g["fact"]), e(g["gained"]) if g["gained"] else "—",
                 e(g["lost"]) if g["lost"] else "—",
                 len(g["sites"]), e(", ".join(g["sites"]))))
        A("</table></div></div>")

    # --- still true, grouped by cause ------------------------------------
    # RENAMED 2026-08-23. "Still true" left the obvious question unanswered --
    # true since when? These are findings that are open as of the most recent
    # run of each tool, and the section above it is what CHANGED in that run.
    # The pairing only reads if both say what they are relative to.
    A('<h2 id=stillopen>Still open, as of the latest run of each tool</h2>')
    A('<p class=sub style="margin:-4px 0 10px">Findings that were already true '
      'and still are. Nothing here is new in this run. New movement is '
      'under <em>What changed</em>. Grouped by cause rather than by site: one '
      'unmerged upstream commit across 38 sites is one decision, not 38 '
      'findings.</p>')
    A("<div class=card>")
    if not m["standing"]:
        A('<p class=big-quiet>No standing findings.</p>')
    else:
        A("<div class=tablewrap><table>"
          "<tr><th>Axis</th><th>Cause</th><th>Sites</th><th>What it means</th></tr>")
        for g in m["standing"]:
            sites, detail = g["sites"], g.get("detail") or {}
            listing = ", ".join(
                ("%s (%s)" % (s, detail[s])) if s in detail else s for s in sites)
            A("<tr><td>%s</td><td><strong>%s</strong></td><td class=num>%d</td>"
              "<td>%s<details><summary>affected sites</summary>"
              '<div class=quiet style="margin-top:6px">%s</div></details></td></tr>'
              % (chip(g["axis"], AXIS_TONE.get(g["axis"], "info")), e(g["cause"]),
                 len(sites), e(g["action"]), e(listing)))
        A("</table></div>")
    A("</div>")

    # --- reconciliation ---------------------------------------------------
    if m["unreconciled"]:
        A("<h2>Sites that do not reconcile</h2>")
        A('<p class=sub style="margin:-4px 0 10px">Present in one source and absent '
          'from the other. This is the highest-signal finding on the page: until it '
          'is explained, nothing else about these sites can be trusted.</p>')
        A("<div class=card><div class=tablewrap><table>"
          "<tr><th>Site</th><th>Host</th><th>Why</th></tr>")
        for s in m["unreconciled"]:
            A("<tr><td><code>%s</code></td><td>%s</td><td>%s</td></tr>"
              % (e(s["site_id"]), e(s.get("host")), e(s.get("reconciliation"))))
        A("</table></div></div>")

    # --- the fleet --------------------------------------------------------
    A(backtotop())
    A(layer_close())
    A(layer_open("reference"))
    A('<h2 id=everysite>Every site</h2>')
    A('<p class=sub style="margin:-4px 0 10px"><strong>Health and Consent are '
      'independent</strong>. A site can be well maintained and still leak '
      'trackers, and the two filters combine, so "OK health, WARN consent" is a '
      'query you can run. A consent cell reading UNKNOWN is a site that refused '
      'the scanner, not a clean one. '
      'Blank cells are not tidy, they are '
      'the point: <strong>not checked</strong> means no scan has looked, and '
      '<em>per host</em> means the hosting control plane reported it rather '
      'than a scan reading it off the site. Every value here was measured.</p>')
    A('<div class=filters>'
      '<input id=q placeholder="Filter by site name" autocomplete=off>'
      '<select id=host><option value="">All hosts</option></select>'
      '<select id=state><option value="">All health states</option>'
      '<option value="__attention">Needs attention</option>'
      '<option value="__changed">Changed since the last run</option>'
      '<option value="__decision">Ruling waiting on a person</option>'
      '<option value="__nohealth">No health evidence</option></select>'
      '<select id=consent><option value="">All consent states</option></select>'
      '<span id=rowcount class=rowcount></span></div>')
    A('<div class="card tablewrap"><table id=fleet>'
      "<tr><th>Site</th><th>Host</th><th>Health</th><th>Consent</th><th>PHP</th>"
      "<th>Newest backup</th><th>Upstream</th>"
      "<th>WP version</th><th>WP core</th><th>Plugins</th><th>Themes</th>"
      "<th>Sends from</th>"
      "<th>SPF</th><th>DKIM</th><th>DMARC sending</th><th>DMARC from</th>"
      "<th>Aligned</th></tr>")

    def yn(v):
        if v is True:
            return chip("yes", "good")
        if v is False:
            return chip("no", "bad")
        return chip("unknown", "muted")

    def backup(v):
        """Render the meaning, not the integer.

        This column previously printed a bare `0` under a header reading
        BACKUP, which reads as "zero backups" when it means the opposite: the
        newest backup is 0 days old. Same family of defect as the fabricated
        zeros and the DNS timeout, and it was misread on first contact.
        """
        if v in (None, L.UNKNOWN):
            return '<span class=quiet>not checked</span>'
        try:
            d = int(v)
        except (TypeError, ValueError):
            return e(v)
        if d == 0:
            return chip("today", "good")
        if d == 1:
            return chip("1 day ago", "good")
        if d <= 2:
            return chip("%d days ago" % d, "good")
        return chip("%d days ago" % d, "bad")

    # TWO tiers of evidence, strongest first, and the cell says which tier it is
    # showing. There were three until 2026-08-20; the workbook's typed claim was
    # the third and is gone. See observed() for why.
    #
    #   read off the site by WP-CLI     plain text, no qualifier
    #   reported by the hosting API     "per host", muted qualifier
    #   none of the above               "not checked"
    #
    # The tiers exist because of 2026-08-19: rendering the page with
    # control-plane facts in the ledger showed 21 sites whose PHP and WordPress
    # versions had just been MEASURED while the cell still displayed something
    # else. The measurement was in the ledger, scoring correctly, and invisible
    # on the page. Labelling which tier a cell is showing is what fixed it, and
    # that is the part worth keeping.
    def observed(v, plane=None):
        """A measured value, or an explicit absence. Never a claim.

        THE WORKBOOK COLUMN WAS REMOVED 2026-08-20. Doug: "we don't need to
        compete with the old way." Every cell used to carry a second, muted
        value from the manual audit spreadsheet, and a mismatch drew a red
        "workbook says 7.0.2" chip. That comparison was the point while the
        workbook was still the system of record and the open question was
        whether this tool could be trusted. It has been, so the comparison is
        now two numbers competing for a reader's attention in one cell, and the
        older one is not evidence.

        What survives is the distinction that is still real: a value read off
        the SITE versus a value the hosting CONTROL PLANE reports. Both are
        measurements, of different strengths, and a reader needs to know which
        one they are looking at.

        `in_workbook` is untouched and still feeds severity's review queue --
        "nobody ever wrote this site down" remains the strongest signal in the
        production-ruling backlog. This change is display only.
        """
        if v in (None, L.UNKNOWN):
            if plane not in (None, L.UNKNOWN):
                return ('<span title="Reported by the hosting control plane, '
                        'not read off the site itself.">%s <em>per host</em>'
                        '</span>' % e(plane))
            return '<span class=quiet>not checked</span>'
        return e(v)

    inventoried = set(m["components"]["sites_inventoried"])

    def plugin_cell(s):
        """The pending-update count, linked to the component catalogue.

        LINKED ONLY WHERE AN INVENTORY EXISTS. A site can carry a count from a
        run made before component capture was switched on, and a link from
        that count would land on a page with nothing to show for it -- a count
        promising names that were never recorded. Those cells stay plain text.
        """
        cell = observed(s.get("plugin_updates"))
        if s["site_id"] not in inventoried:
            return cell
        return ('<a href="/components?site=%s" title="Which plugins, and at '
                'what versions">%s</a>' % (e(s["site_id"]), cell))

    def upstream_cell(s):
        """Pending upstream commits, or the reason there is no number.

        This printed `e(s.get("upstream_pending", "—"))` -- the raw ledger
        value -- so the string `unknown` reached the page bare, on 26 rows.
        Every other cell in this table already says WHICH absence it is
        showing. Upstream is a PANTHEON fact: it comes from
        `terminus upstream:updates:list` and Nexcess exposes no equivalent, so
        for those sites there is nothing to measure rather than something
        unmeasured. Those are different answers and the cell now says which.
        """
        v = s.get("upstream_pending")
        if v in (None, L.UNKNOWN, ""):
            if (s.get("host") or "") != "CM Pantheon":
                return ('<span class=quiet title="Upstream tracking is a '
                        'Pantheon feature. This host exposes no equivalent, so '
                        'there is nothing to measure.">no upstream</span>')
            return '<span class=quiet>not checked</span>'
        return e(v)

    def selector_cell(s):
        """The DKIM selector, or why there is none to show.

        Same defect as upstream: the raw value went straight to the cell, so
        `unknown` printed bare. A DKIM selector cannot be discovered from DNS
        -- you can only verify one you already know -- so an absent selector
        means the check could not run, not that DKIM is missing. Printing the
        word `unknown` under a DKIM header invites the opposite reading.
        """
        v = s.get("dkim_selector")
        if v in (None, L.UNKNOWN, "", "—"):
            if s.get("spf_checked_at") in (None, L.UNKNOWN):
                return ('<span class=quiet title="No sending domain is '
                        'recorded for this site, so nothing was queried.">'
                        'no sending domain</span>')
            return ('<span class=quiet title="A DKIM selector cannot be '
                    'discovered from DNS. Without one, DKIM can be neither '
                    'confirmed nor ruled out.">selector not known</span>')
        return e(v)

    def wp_version_cell(v, plane=None):
        """The WordPress version, and where it was read from.

        Two evidence tiers, strongest first: read off the site by WP-CLI, or
        reported by the hosting control plane. The third tier -- the workbook's
        typed claim -- was removed 2026-08-20.

        A control-plane version is still qualified rather than shown bare. It
        is weaker evidence than `wp core version`, and the severity model
        scores CRIT on it deliberately, so a reader deciding whether to go and
        look at a site needs to know which kind of answer they have.
        """
        if v in (None, L.UNKNOWN):
            if plane not in (None, L.UNKNOWN):
                return ('<span title="Reported by the hosting control plane, '
                        'not read off the site by WP-CLI.">%s <em>per host</em>'
                        '</span>' % e(plane))
            return '<span class=quiet>not checked</span>'
        return e(v)

    def consent_cell(s):
        """The consent axis for one site, with the vendor when there is one.

        UNKNOWN here means the sweep was refused or could not load the page. It
        is rendered as UNKNOWN and captioned, never left blank: a blank cell in
        a consent column reads as "nothing to fix", which is the exact bug the
        sweep shipped with -- 23 HTTP 403 block pages scored as clean.
        """
        ax = (s.get("severity") or {}).get("axes", {}).get("consent") or {}
        st = ax.get("status")
        if not st:
            return '<span class=quiet>&mdash;</span>'
        cell = chip(st, STATE_TONE.get(st, "muted"))
        if st == "UNKNOWN":
            code = s.get("consent_http_status")
            why = ("HTTP %s" % code) if isinstance(code, int) else "not reached"
            return cell + '<div class=cellnote>%s</div>' % e(why)
        vendor = s.get("consent_banner_vendor")
        pre = s.get("consent_pre_trackers")
        bits = []
        if vendor and vendor not in (None, "none", L.UNKNOWN):
            bits.append(e(vendor))
        elif st != "OK":
            bits.append("no tooling")
        try:
            if int(pre) > 0:
                # "OK" beside "4 before consent" reads as a contradiction, and
                # on an opt-out site it is not one: the tags are supposed to
                # fire on load outside the restricted region. The cell has to
                # carry the reason or the status looks wrong next to its own
                # evidence. Caught by looking at the rendered row, 2026-08-27.
                if s.get("consent_model") == "opt-out":
                    bits.append('<span title="This site is opt-out outside its '
                                'restricted region, so tags firing on load is '
                                'the configured behaviour. Whether they stop on '
                                'a rejection is not tested by this sweep."'
                                '>%d on load, as configured</span>' % int(pre))
                else:
                    bits.append("%d before consent" % int(pre))
        except (TypeError, ValueError):
            pass
        if bits:
            cell += '<div class=cellnote>%s</div>' % " &middot; ".join(bits)
        return cell

    def sends_from(s):
        """The domain SPF/DKIM/DMARC were actually queried at.

        Added 2026-08-24 because Victoria asked "what is the sending URL" in
        the first outside review. The page scored every site on a domain it
        never named. `spf_checked_at` is that domain, recorded by the check
        itself rather than re-derived here, so the column cannot drift from
        what was measured.

        It is a RULING, not a measurement: a person records it in the audit
        workbook and nothing in DNS reveals it. When it is missing the cell
        says so, because a blank would read as "nothing to send from".
        """
        d = s.get("spf_checked_at")
        # The ledger's absence sentinel is the STRING "unknown", not None, so
        # a plain falsiness test rendered `unknown` as if it were a domain.
        # Caught by looking at the page: six rows showed <code>unknown</code>.
        if not d or str(d).strip().lower() == L.UNKNOWN:
            return '<span class=quiet>not recorded</span>'
        return "<code>%s</code>" % e(d)

    for s in m["sites"]:
        st = s.get("status")
        state = chip(st, STATE_TONE.get(st, "muted")) if st else '<span class=quiet>—</span>'
        cst = ((s.get("severity") or {}).get("axes", {})
               .get("consent") or {}).get("status") or ""
        nohealth = "1" if any(
            r.get("code") == "coverage_partial"
            for r in (s.get("severity") or {}).get("reasons", [])) else ""
        # A row that is SHOWN but not COUNTED. cm-whitelabel is
        # production:false, so the health card reads "CRIT 2" while filtering
        # to CRIT returns three rows. Deliberate -- the site is still scanned
        # and still shown -- but with nothing on the row saying so it reads as
        # the card being wrong. It now says so on the row itself, rather than
        # only in a sentence two sections away.
        excluded = s.get("production") is False
        A('<tr data-site="%s" data-host="%s" data-state="%s" data-consent="%s"'
          ' data-nohealth="%s" data-decision="%s" data-changed="%s"'
          ' data-excluded="%s">'
          "<td><code>%s</code>%s</td><td class=quiet>%s</td><td>%s</td><td>%s</td>"
          "<td class=num>%s</td><td>%s</td><td class=num>%s</td>"
          "<td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
          "<td class=quiet>%s</td>"
          "<td>%s</td><td class=quiet>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
          % (e(s["site_id"].lower()), e(s.get("host") or ""), e(st or ""), e(cst),
             nohealth,
             "1" if s["site_id"] in set(h["unreviewed"]) else "",
             "1" if s["site_id"] in set(_chg_sites) else "",
             "1" if excluded else "",
             e(s["site_id"]),
             ('<br><span class=quiet style="font-size:11.5px">not production, '
              'excluded from the counts above</span>' if excluded else ""),
             e(s.get("host") or "—"), state, consent_cell(s),
             observed(s.get("php_version"), s.get("nexcess_php_version")),
             backup(s.get("db_backup_age_days")),
             upstream_cell(s),
             wp_version_cell(s.get("wp_version"), s.get("nexcess_app_version")),
             observed(s.get("wp_core_update")),
             plugin_cell(s),
             observed(s.get("theme_updates")),
             sends_from(s),
             yn(s.get("spf_present")), selector_cell(s),
             yn(s.get("dmarc_at_sending_present")), yn(s.get("dmarc_at_from_present")),
             yn(s.get("relaxed_aligned"))))
    A("</table></div>")

    # THE TREND-CHART PROMISE WAS REMOVED 2026-08-23. It read "Trend charts
    # appear once the ledger holds enough runs to justify one", which says
    # they arrive on their own. Nothing implements them -- no chart code, no
    # threshold, no check. The page promised behaviour that did not exist.
    #
    # Its own justification had also expired: the sentence rendered the live
    # run count, so it argued a line would be "points pretending to be a
    # trend" while printing 27. The count is no longer the reason.
    #
    # The real reason is cadence, not volume, and it is stated instead: those
    # runs were triggered by hand at irregular intervals, so a line over them
    # would draw the shape of when somebody ran the scanner rather than
    # anything the fleet did. That is a worse answer than no chart.
    A('<p class=foot>Generated %s from the ledger at <code>history/</code>, '
      "which holds %d run(s). Read-only: this page reports, it never changes a "
      "site. <strong>No trend chart is drawn.</strong> Nothing here is "
      "scheduled yet, so runs happen at irregular intervals when somebody "
      "starts one, and a line through them would show when the scanner was "
      "run rather than how the fleet moved.</p>"
      % (e(m["generated"]), len(m["runs"])))
    A(backtotop())
    A(layer_close())
    A("</div>")

    A("""<script>
(function(){
 var rows=[].slice.call(document.querySelectorAll('#fleet tr[data-site]'));
 function opts(sel,vals){
   var have={};[].slice.call(sel.options).forEach(function(o){have[o.value]=1;});
   vals.filter(Boolean).sort().forEach(function(v){
     if(have[v])return;
     var o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o);});}
 opts(document.getElementById('host'),
      rows.map(function(r){return r.dataset.host}).filter(function(v,i,a){return a.indexOf(v)===i}));
 opts(document.getElementById('state'),
      rows.map(function(r){return r.dataset.state}).filter(function(v,i,a){return a.indexOf(v)===i}));
 opts(document.getElementById('consent'),
      rows.map(function(r){return r.dataset.consent}).filter(function(v,i,a){return a.indexOf(v)===i}));
 function apply(){
   var q=document.getElementById('q').value.toLowerCase(),
       h=document.getElementById('host').value,
       s=document.getElementById('state').value,
       c=document.getElementById('consent').value;
   rows.forEach(function(r){
     var okState = !s || (
       s==='__nohealth'  ? r.dataset.nohealth==='1'  :
       s==='__attention' ? (r.dataset.state==='CRIT'||r.dataset.state==='WARN') :
       s==='__decision'  ? r.dataset.decision==='1'  :
       s==='__changed'   ? r.dataset.changed==='1'   :
                           r.dataset.state===s);
     r.style.display=(!q||r.dataset.site.indexOf(q)>-1)&&(!h||r.dataset.host===h)
       &&okState&&(!c||r.dataset.consent===c)?'':'none';});
   // THE CARD COUNT AND THE ROW COUNT MUST RECONCILE. Clicking a tile that
   // says 54 returns 55 rows, because a production:false site is shown and
   // not counted. Without saying so, the card reads as wrong.
   var shown=rows.filter(function(r){return r.style.display!=='none';});
   var ex=shown.filter(function(r){return r.dataset.excluded==='1';}).length;
   var out=document.getElementById('rowcount');
   if(out) out.textContent = shown.length+' of '+rows.length+' sites shown'
     +(ex? ' \u00b7 '+ex+' shown but not counted in the cards above':'');
 }
 [].slice.call(document.querySelectorAll('[data-tile]')).forEach(function(b){
   b.addEventListener('click',function(){
     var map={attention:'__attention',decisions:'__decision',
              changed:'__changed',nohealth:'__nohealth'};
     document.querySelectorAll('[data-tile]').forEach(function(x){
       x.classList.toggle('on', x===b);});
     document.getElementById('state').value = map[b.dataset.tile]||'';
     document.getElementById('consent').value='';
     apply();
     var t=document.getElementById('fleet');
     if(t) t.scrollIntoView({behavior:'smooth',block:'start'});
   });});
 [].slice.call(document.querySelectorAll('.wfjump')).forEach(function(b){
   b.addEventListener('click',function(){
     var ax=b.dataset.axis, st=b.dataset.state;
     document.getElementById('state').value   = (ax==='health')  ? st : '';
     document.getElementById('consent').value = (ax==='consent') ? st : '';
     apply();
     var t=document.getElementById('fleet');
     if(t) t.scrollIntoView({behavior:'smooth',block:'start'});
   });});
 ['q','host','state','consent'].forEach(function(id){
   var el=document.getElementById(id);
   el.addEventListener('input',apply);el.addEventListener('change',apply);});
 apply();
})();
</script></html>""")
    return "".join(o)


COMPONENT_CSS = """
.tablewrap{overflow-x:auto}
#cat th[data-sort]{cursor:pointer;user-select:none;white-space:nowrap}
#cat th[data-sort]:hover{color:var(--ink)}
#cat th[data-sort]::after{content:"";opacity:.35;margin-left:5px}
#cat th.asc::after{content:"\\2191";opacity:1}
#cat th.desc::after{content:"\\2193";opacity:1}
#cat td{vertical-align:top}
#cat summary{cursor:pointer;color:var(--ink2);font-size:12.5px}
.installs{margin-top:6px;display:flex;flex-direction:column;gap:3px;
 max-height:230px;overflow-y:auto;padding-right:4px}
.install{display:flex;gap:8px;align-items:baseline;font-size:12.5px}
.install .v{font-variant-numeric:tabular-nums;color:var(--ink2)}
tr.hide{display:none}
"""

# No framework, no build step, and it degrades to a plain readable table with
# scripting off -- the filters simply do nothing. Same choice as the fleet
# page's own filter script.
COMPONENT_JS = """<script>
(function(){
 var rows=[].slice.call(document.querySelectorAll('#cat tr[data-slug]'));
 var q=document.getElementById('q'), ty=document.getElementById('type'),
     sc=document.getElementById('scope'), site=document.getElementById('site'),
     cnt=document.getElementById('count'),
     banner=document.getElementById('sitebanner'),
     sname=document.getElementById('sitename'),
     scount=document.getElementById('sitecount'),
     clear=document.getElementById('clearsite'),
     spending=document.getElementById('sitepending'),
     persite=[].slice.call(document.querySelectorAll('.persite'));

 // Deep link. The fleet table's plugin count arrives as
 // /components?site=galbanicheese.com, so that cell still answers the
 // per-site question in one click.
 var pre=new URLSearchParams(location.search).get('site');
 var notice=document.getElementById('nositenotice');
 if(pre){
   var opt=[].slice.call(site.options).find(function(o){
     return o.value.toLowerCase()===pre.toLowerCase(); });
   if(opt){
     site.value=opt.value;
   } else {
     // Named but not inventoried. Say which, in words. A bare "0 of 312"
     // reads as "this site runs no plugins"; it means nobody listed them.
     q.value=pre;
     document.getElementById('nositename').textContent=pre;
     notice.style.display='';
   }
 }

 function apply(){
   var t=(q.value||'').trim().toLowerCase(), ty_=ty.value, sc_=sc.value,
       si=(site.value||'').toLowerCase(), n=0, npend=0, ninst=0;
   rows.forEach(function(r){
     var ok=true;
     if(si && (' '+r.dataset.sitesList+' ').indexOf(' '+si+' ')<0) ok=false;
     if(ok && t && r.dataset.slug.indexOf(t)<0 &&
        (' '+r.dataset.sitesList+' ').indexOf(t)<0) ok=false;
     if(ok && ty_ && r.dataset.type!==ty_) ok=false;
     var ins = si ? r.querySelector('.install[data-site="'+si+'"]') : null;
     // With a site selected, "updates pending" must mean pending ON THIS
     // SITE. The `pending` flag on the row is fleet-wide, so filtering on it
     // inside a per-site view would list components whose update is waiting
     // somewhere else entirely -- the same confusion as the count that sent
     // us here.
     if(ok && sc_==='pending' && si){
       if(!ins || !ins.dataset.pending) ok=false;
     } else if(ok && sc_ && (' '+r.dataset.flags+' ').indexOf(sc_)<0) ok=false;
     r.classList.toggle('hide', !ok);
     if(ok) n++;
     // Site totals are counted from the site's OWN install rows, independent
     // of the type/scope/text filters. Counting visible rows instead made the
     // banner read "1 component installed" as soon as the pending filter was
     // on, when 31 were installed and 1 was merely shown.
     if(ins){ ninst++; if(ins.dataset.pending) npend++; }

     // Fill the per-site cell from the install row for the selected site.
     // Read off the same rendered data the table already shows, so the two
     // cannot disagree.
     var cell=r.querySelector('td.persite');
     if(cell){
       if(ok && si){
         var ins=r.querySelector('.install[data-site="'+si+'"]');
         cell.textContent = ins ? ins.dataset.v : '';
       } else { cell.textContent=''; }
     }
   });
   cnt.textContent = n+' of '+rows.length+' components';

   persite.forEach(function(el){ el.hidden = !si; });
   banner.style.display = si ? '' : 'none';
   if(si){
     sname.textContent=site.value;
     scount.textContent=ninst;
     spending.textContent = npend===0
       ? 'none have an update pending'
       : (npend===1 ? '1 has an update pending'
                    : npend+' have an update pending');
   }

   // Keep the URL shareable, without adding a history entry per keystroke.
   var u=new URL(location.href);
   if(site.value){ u.searchParams.set('site', site.value); }
   else { u.searchParams.delete('site'); }
   history.replaceState(null,'',u);
 }
 [q,ty,sc,site].forEach(function(el){
   el.addEventListener('input', apply); el.addEventListener('change', apply); });
 // The notice describes one arrival, not a standing state: as soon as the
 // search that produced it is edited, it stops being true.
 q.addEventListener('input', function(){ notice.style.display='none'; });
 clear.addEventListener('click', function(ev){
   ev.preventDefault(); site.value=''; apply(); });
 apply();

 var tbl=document.getElementById('cat'), dir={};
 [].slice.call(tbl.querySelectorAll('th[data-sort]')).forEach(function(th){
   th.addEventListener('click', function(){
     var k=th.dataset.sort, d=dir[k]=(dir[k]==='asc'?'desc':'asc');
     [].slice.call(tbl.querySelectorAll('th')).forEach(function(o){
       o.classList.remove('asc','desc'); });
     th.classList.add(d);
     var num={sites:'nSites',vers:'nVers',pending:'nPending'}[k];
     rows.sort(function(a,b){
       var va,vb;
       if(num){ va=+a.dataset[num]; vb=+b.dataset[num]; }
       else { va=a.dataset[k]||''; vb=b.dataset[k]||''; }
       if(va<vb) return d==='asc'?-1:1;
       if(va>vb) return d==='asc'?1:-1;
       // Stable tiebreak on slug, so equal counts do not shuffle between
       // clicks and look like the data moved.
       return a.dataset.slug<b.dataset.slug?-1:1;
     });
     rows.forEach(function(r){ tbl.appendChild(r); });
   });
 });
})();
</script>"""


VULN_CSS = """
/* The vulnerability page. Tokens and classes come from page.css; this adds
   only what that stylesheet has no shape for. Two stylesheets is two answers
   about what a warning looks like. */
.vd { border-left: 4px solid var(--good); padding: 2px 0 2px 15px; margin: 0 0 14px; }
.vd.crit { border-left-color: var(--crit); }
.vd h2 { margin: 0; font-size: 19px; font-weight: 600; letter-spacing: -0.01em;
  text-wrap: balance; max-width: 40ch; color: var(--good-ink); }
.vd.crit h2 { color: var(--crit); }
.vd p { margin: 7px 0 0; font-size: 13.5px; color: var(--ink2); max-width: 72ch; }
.vd p b { color: var(--ink); font-family: var(--font-mono); font-weight: 600; }
.vstrip { display: flex; flex-wrap: wrap; gap: 4px 26px; font-size: 12.5px;
  color: var(--ink2); padding: 10px 0 0 19px; margin: 0 0 26px;
  border-top: 1px solid var(--line); }
.vstrip div { white-space: nowrap; }
.vstrip b { font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: 16px; font-weight: 500; color: var(--ink); margin-right: 5px; }
.vstrip .ok b { color: var(--good-ink); }
.vstrip .look b { color: var(--warn-ink); }
.vstrip .bad b { color: var(--crit); }
.vt { overflow-x: auto; border: 1px solid var(--line); border-radius: 3px;
  background: var(--surface); }
.vt table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
.vt th { padding: 0; border-bottom: 1px solid var(--line);
  background: var(--surface2); white-space: nowrap; }
.vt th button { width: 100%; display: flex; align-items: center; gap: 5px;
  border: 0; background: none; padding: 7px 11px; font: inherit; font-size: 10.5px;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink2);
  font-weight: 600; cursor: pointer; text-align: left; }
.vt th button:hover { color: var(--ink); }
.vt th[aria-sort] button { color: var(--accent); }
.vt th button .ar { font-size: 9px; opacity: 0; }
.vt th[aria-sort] button .ar { opacity: 1; }
.vt td { padding: 10px 11px; border-bottom: 1px solid var(--line); vertical-align: top; }
.vt tr:last-child td { border-bottom: 0; }
.vt tr.isc td { background: color-mix(in srgb, var(--crit) 7%, transparent); }
.vt tr.isc td:first-child { box-shadow: inset 3px 0 0 var(--crit); }
.vslug { font-family: var(--font-mono); font-weight: 500; word-break: break-all; }
.vwhat { display: block; color: var(--ink2); font-size: 11.5px; margin-top: 2px;
  max-width: 46ch; }
.vfix { display: inline-block; margin-top: 6px; font-size: 11.5px; font-weight: 600;
  color: var(--crit); border: 1px solid var(--crit); border-radius: 2px;
  padding: 1px 7px; background: color-mix(in srgb,var(--crit) 10%,transparent); }
.vsites { margin-top: 7px; display: flex; flex-wrap: wrap; gap: 4px; align-items: baseline; }
.vsites span { font-family: var(--font-mono); font-size: 11px; color: var(--ink);
  background: var(--surface2); border: 1px solid var(--line); border-radius: 2px;
  padding: 1px 6px; white-space: nowrap; }
.vsites button { border: 0; background: none; padding: 0; font: inherit;
  font-size: 11px; color: var(--accent); cursor: pointer; text-decoration: underline;
  text-underline-offset: 2px; white-space: nowrap; }
.vcve { display: block; font-family: var(--font-mono); font-size: 10.5px;
  color: var(--ink2); margin-top: 6px; }
.vver { font-family: var(--font-mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
.vsev { white-space: nowrap; }
.vsev .lbl { font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--ink2); }
.vsev .num { font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  color: var(--ink2); font-size: 11.5px; margin-left: 5px; }
.vsev.Medium .lbl, .vsev.High .lbl { color: var(--warn-ink); }
.vsev.Critical .lbl { color: var(--crit); }
.vwho { font-size: 11.5px; color: var(--ink2); }
.vsince { font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  white-space: nowrap; font-size: 11.5px; }
.vnote { border-top: 1px solid var(--line); padding-top: 13px; margin-top: 26px; }
.vnote h3 { font-size: 12px; color: var(--ink2); text-transform: uppercase;
  letter-spacing: 0.07em; margin: 0 0 8px; }
.vnote ul { margin: 0; padding-left: 17px; font-size: 12.5px; color: var(--ink2); }
.vnote li { margin: 6px 0; max-width: 78ch; }
.vnote b { font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-weight: 500; color: var(--ink); }
"""


VULN_JS = r"""
/* Sorting only. This file decides no severity and holds no threshold -- it
   renders what severity.py and fleet-vuln.py already decided, the same
   contract page.js has. */
(function () {
  var DATA = JSON.parse(document.getElementById('vuln-data').textContent);
  var tb = document.querySelector('.vt tbody');
  var hr = document.querySelector('.vt thead tr');
  /* DEFAULT IS SEVERITY, with age as the tiebreak. Sorting the whole table by
     age put a 9.5-year-old MEDIUM above a 4-day-old CRITICAL, which is the
     opposite of the reader's question. Age was added to separate findings that
     SHARE a score, so it belongs in the tiebreak and in its own sortable
     column, not as the primary key. Caught by reading the rendered table. */
  var key = 'cvss', dir = -1, open = {};
  var GET = {
    slug: function (g) { return g.slug; },
    ver: function (g) { return (g.versions || []).join(','); },
    cvss: function (g) { return typeof g.cvss === 'number' ? g.cvss : -1; },
    fix: function (g) { return g.patched === false ? 0 : 1; },
    /* -1 for an unknown age, so it sorts to the BOTTOM of a longest-first
       list rather than to the top where it would read as disclosed today. */
    age: function (g) { return typeof g.age_days === 'number' ? g.age_days : -1; }
  };
  function ageText(g) {
    if (typeof g.age_days !== 'number') { return 'unknown'; }
    var d = g.age_days;
    if (d < 60) { return d + ' days'; }
    if (d < 730) { return Math.round(d / 30) + ' months'; }
    return (d / 365).toFixed(1) + ' years';
  }
  function esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function sites(g, i) {
    /* 66 chips is not a table row. Collapse past six and SAY how many are
       hidden -- a silent truncation reads as "only these six". */
    var LIM = 6, all = g.sites || [], shown = open[i] ? all : all.slice(0, LIM);
    var h = shown.map(function (x) { return '<span>' + esc(x.site_id) + '</span>'; }).join('');
    if (all.length > LIM) {
      h += '<button type="button" data-x="' + i + '">'
        + (open[i] ? 'show fewer' : 'and ' + (all.length - LIM) + ' more') + '</button>';
    }
    return '<div class="vsites">' + h + '</div>';
  }
  function render() {
    var rows = DATA.slice().sort(function (a, b) {
      /* A finding NEW since the last check never sorts out of the top. It was
         the criticals that were pinned here until 2026-08-31, and that was
         wrong for the same reason the old headline was: six of the eight
         criticals had been outstanding for months, so pinning them pinned the
         backlog and buried the two that had just appeared. What changed is
         what a reader cannot already know. */
      var an = a.new_since_last ? 0 : 1;
      var bn = b.new_since_last ? 0 : 1;
      if (an !== bn) { return an - bn; }
      var x = GET[key](a), y = GET[key](b);
      var n = (typeof x === 'number') ? x - y : String(x).localeCompare(String(y));
      /* Oldest first among equals: eight findings at 9.8 are indistinguishable
         by score, and how long we have carried one is the thing that ranks it. */
      var tie = (GET.age(b) - GET.age(a)) || (b.site_count - a.site_count);
      return (n * dir) || tie;
    });
    tb.innerHTML = rows.map(function (g, i) {
      /* The stripe marks what is NEW, not what scores highest. A page that
         paints every 9.8 red says the same thing every render for years. */
      var isc = !!g.new_since_last;
      return '<tr' + (isc ? ' class="isc"' : '') + '>'
        + '<td><span class="vslug">' + esc(g.slug) + '</span>'
        + '<span class="vwhat">' + esc(g.title) + '</span>'
        + (g.patched === false ? ''
           : '<span class="vfix">Update to ' + esc(g.fix_version) + '</span>')
        + sites(g, i)
        + '<span class="vcve">' + esc(g.cve) + '</span></td>'
        + '<td class="vver">' + esc((g.versions || []).join(', ')) + '</td>'
        + '<td><span class="vsev ' + esc(g.rating || '') + '">'
        + '<span class="lbl">' + esc(g.rating || 'unrated') + '</span>'
        + '<span class="num">' + (typeof g.cvss === 'number' ? g.cvss.toFixed(1) : '') + '</span></span></td>'
        + '<td class="vwho">' + (g.patched === false ? 'none available' : 'update') + '</td>'
        + '<td class="vsince">' + ageText(g)
        + '<em>' + (g.new_since_last ? 'new this run' : esc(g.published)) + '</em></td>'
        + '</tr>';
    }).join('');
    Array.prototype.forEach.call(hr.children, function (th) {
      var b = th.querySelector('button');
      if (b.dataset.k === key) { th.setAttribute('aria-sort', dir < 0 ? 'descending' : 'ascending'); }
      else { th.removeAttribute('aria-sort'); }
      b.querySelector('.ar').innerHTML = (b.dataset.k === key && dir > 0) ? '&#9650;' : '&#9660;';
    });
  }
  hr.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-k]'); if (!b) { return; }
    if (b.dataset.k === key) { dir = -dir; }
    else { key = b.dataset.k; dir = (key === 'cvss' || key === 'since') ? -1 : 1; }
    open = {}; render();
  });
  tb.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-x]'); if (!b) { return; }
    open[b.dataset.x] = !open[b.dataset.x]; render();
  });
  render();
})();
"""


def render_vulnerabilities(m):
    """The vulnerability page: which components have a known hole, and who runs them.

    A SEPARATE PAGE, agreed 2026-08-31, for the reason the consent and
    component pages are: the fleet matrix is one row per SITE and findings are
    per component per site. The matrix carries a count and links here.

    THE PAGE LEADS WITH THE VERDICT, not the worst number. The first draft
    opened on `14` in red under "no fix exists" and Doug's word for it was
    "induced panic" -- measured, every one of those fourteen was MEDIUM or
    below. Opening on the scariest true number is this repo's cardinal bug with
    the sign flipped, and both directions are defects. The verdict is also
    SCOPED: it speaks for vulnerabilities and says nothing about maintenance,
    where this fleet is not fine.
    """
    with open(os.path.join(PAGE_DIR, "page.css"), encoding="utf-8") as fh:
        css_text = fh.read()

    v = m["vulnerabilities"]
    n_matched = len(v["matched_sites"])
    n_unmatched = len(v["unmatched_sites"])
    worst = v["worst_cvss"]
    crits = v["critical"]
    crit_sites = {x["site_id"] for g in crits for x in g["sites"]}
    fresh = [g for g in crits if g["new_since_last"]]
    ages = [g["age_days"] for g in crits if g["age_days"] is not None]
    oldest = max(ages) if ages else None
    installs = len(m["components"]["catalogue"]) if m.get("components") else 0

    o = []
    A = o.append
    A("<!doctype html>")
    A('<html lang="en">')
    A("<head>")
    A('<meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<meta name="color-scheme" content="light dark">')
    A("<title>clevermethod fleet: vulnerabilities</title>")
    A("<style>%s%s</style>" % (css_text, VULN_CSS))
    A("</head><body>")
    A('<div class="wrap">')
    A('<header class="top"><div><h1>Plugin vulnerabilities'
      '<small>%d site(s) matched &middot; %d distinct component(s) &middot; '
      'Wordfence, read-only</small></h1>'
      '<p class="thesis">Every plugin, mu-plugin and theme we can see, checked '
      'against Wordfence’s published advisories. '
      '<a href="/">Back to the fleet page</a>.</p></div></header>'
      % (n_matched, installs))

    # --- THE VERDICT ------------------------------------------------------
    if not v["matched_sites"]:
        A('<div class="vd"><h2 style="color:var(--ink)">Nothing has been '
          'matched yet.</h2><p>The Wordfence source is registered and has not '
          'produced a run. This is an absence, not a clean result.</p></div>')
    elif fresh:
        # NEW since the last check. This is the only state that earns "today":
        # something changed, and a reader who acted yesterday would not know.
        A('<div class="vd crit"><h2>Act today. %d critical finding(s) are new '
          'since the last check.</h2>'
          '<p>%s. A patch exists for each, so this is an update rather than a '
          'decision. %d further critical finding(s) were already '
          'outstanding.</p></div>'
          % (len(fresh),
             "; ".join("<b>%s</b> (%s)" % (html.escape(g["slug"]), g["cve"])
                       for g in fresh[:4]),
             len(crits) - len(fresh)))
    elif crits:
        # STANDING, and nothing new. Saying "act today" here would have said it
        # every day for %d days, which is not an alert but the page's permanent
        # state -- and the reason the first draft of this page was rewritten.
        # Duration is the finding: it names a patching backlog, not an
        # emergency, and that is both true and more likely to move someone.
        A('<div class="vd crit"><h2>%d critical finding(s) have gone '
          'unpatched%s.</h2>'
          '<p>None is new since the last check. Every one has a patch '
          'available and has had for %s. %d finding(s) in total close with a '
          'normal plugin update; %d have no update available and need a '
          'decision.</p></div>'
          % (len(crits),
             "" if oldest is None else ", the oldest for <b>%d days</b>" % oldest,
             "some time" if oldest is None else "as long as %d days" % oldest,
             v["n_fixable"], v["n_nofix"]))
    elif v["n_nofix"]:
        A('<div class="vd"><h2>Nothing here needs urgent attention.</h2>'
          '<p><b>%d</b> component(s) on <b>%d</b> site(s) have a known problem '
          'with no update available. The most serious rates <b>%s out of 10</b> '
          '— nothing is critical. Everything else Wordfence flagged, '
          '<b>%d</b> finding(s), is closed by a normal plugin update.</p></div>'
          % (len(v["nofix"]), len(v["nofix_sites"]),
             ("%.1f" % worst) if isinstance(worst, (int, float)) else "unknown",
             v["n_fixable"]))
    else:
        A('<div class="vd"><h2>No component has an unfixable vulnerability.</h2>'
          '<p>Everything Wordfence flagged — <b>%d</b> finding(s) — is '
          'closed by a normal plugin update. This is a statement about known '
          'advisories only.</p></div>' % v["n_fixable"])

    A('<div class="vstrip">')
    A('<div class="ok"><b>%d</b>closed by updating</div>' % v["n_fixable"])
    A('<div class="look"><b>%d</b>need a decision</div>' % len(v["nofix"]))
    A('<div><b>%d</b>site(s) affected</div>' % len(v["affected_sites"]))
    # NEVER omitted, and never phrased as a pass. On this axis "no findings" is
    # the best possible result, so a site nothing looked at must not be silent.
    A('<div class="bad" title="No component inventory exists, so these could '
      'not be matched at all."><b>%d</b>not checked</div>' % n_unmatched)
    if v["has_baseline"]:
        A('<div class="%s"><b>%d</b>new since the last check</div>'
          % ("bad" if fresh else "", len(fresh)))
    else:
        # No earlier run to compare against. Saying "0 new" would be a claim
        # this page cannot support, and on a first run everything is new to us
        # while none of it is new to the world.
        A('<div>no baseline yet &mdash; first run of this source</div>')
    A("</div>")

    # --- THE TABLE --------------------------------------------------------
    if v["findings"]:
        A('<h3 style="font-size:14.5px;margin:0 0 3px">Findings, worst first</h3>')
        A('<p class="quiet" style="margin:0 0 11px;font-size:12.5px;max-width:72ch">'
          'Sorted worst first, and among findings that share a score, by how '
          'long the advisory has been public. '
          'Findings that share a score are indistinguishable by it; age is what '
          'separates one disclosed last week from one carried for years. New '
          'findings are marked. Anything with no update available is a choice '
          'rather than a task — replace it, restrict who can reach it, or '
          'accept it.</p>')
        A('<div class="vt"><table><thead><tr>')
        for key, label in (("slug", "Component and sites"), ("ver", "Version"),
                           ("cvss", "Severity"), ("fix", "Fix"),
                           ("age", "Open for")):
            A('<th%s><button type="button" data-k="%s">%s'
              '<span class="ar">&#9660;</span></button></th>'
              % (' aria-sort="descending"' if key == "cvss" else "", key, label))
        A("</tr></thead><tbody>")
        A("</tbody></table></div>")
        A('<script id="vuln-data" type="application/json">%s</script>'
          % json.dumps([{k: (sorted(x) if isinstance(x, set) else x)
                         for k, x in g.items()} for g in v["findings"]]))
        A("<script>%s</script>" % VULN_JS)
    else:
        A('<p class="quiet">No finding to list.</p>')

    # --- WHAT THIS DOES NOT SAY -------------------------------------------
    A('<div class="vnote"><h3>Worth knowing</h3><ul>')
    if n_unmatched:
        A('<li><b>%d</b> site(s) could not be checked: no plugin list exists '
          'for them, so they are in no number on this page. Unchecked, not '
          'clear. %s</li>'
          % (n_unmatched, ", ".join("<code>%s</code>" % x
                                    for x in v["unmatched_sites"][:12])))
    A('<li>Wordfence never having published an advisory for a component is not '
      'evidence the component is sound. For a widely used plugin it is '
      'meaningful; for code written for one client, it mostly means no outside '
      'researcher has looked at it.</li>')
    A('<li>Versions come from the component inventory the health scan wrote, '
      'so anything installed or updated since that scan is not reflected '
      'here.</li>')
    A("</ul></div>")
    A('<p class="foot">Read-only. Wordfence Intelligence V3, matched against '
      '<a href="/components">the component catalogue</a>.</p>')
    A("</div></body></html>")
    return "\n".join(o)


def render_consent(m):
    """The consent page: one question, all the evidence for it.

    A SEPARATE PAGE for the same reason the component catalogue is one: the
    fleet table is one row per site, and consent has data that does not fit
    that grain. The gating results are per TRACKER per PASS -- which tags
    survived a rejection, at what consent state -- and alongside them sit the
    model, the OneTrust rule, who manages the site, and the vendor. Three
    columns in the matrix is all that shape can carry, and it was already at
    three.

    SAME CHROME AS THE FLEET PAGE, deliberately. It inlines `page.css` and uses
    that stylesheet's tokens and classes -- `.wrap`, `.top`, `.tools`, `.chip`
    with `st-*`, `.quiet`, `.foot`. The first cut shipped with the OLD css()
    and its own token set (`--bad`, `--info`, `--card`), which rendered a page
    that was recognisably a different product one click from the dashboard.
    Two stylesheets is two answers about what a warning looks like.
    """
    with open(os.path.join(PAGE_DIR, "page.css"), encoding="utf-8") as fh:
        css_text = fh.read()

    sites = m["sites"]
    swept = [x for x in sites if "consent_scan_ok" in x]
    seen = [x for x in swept if x.get("consent_scan_ok") is True]
    tooled = [x for x in seen if x.get("consent_banner_detected") is True]
    gated = [x for x in sites if x.get("gating_tested") is True]
    untested = [x for x in sites
                if "gating_tested" in x and x.get("gating_tested") is not True]

    def _ours_broken(x):
        return (x.get("consent_managed") is True
                and x.get("gating_tested") is True
                and (x.get("gating_still_firing") or 0) > 0)

    ours_broken = sorted((x for x in sites if _ours_broken(x)),
                         key=lambda x: x["site_id"])
    ours_ok = sorted((x for x in sites
                      if x.get("consent_managed") is True
                      and x.get("gating_tested") is True
                      and not (x.get("gating_still_firing") or 0)),
                     key=lambda x: x["site_id"])
    theirs = sorted((x for x in sites
                     if x.get("consent_managed") is not True
                     and isinstance(x.get("consent_pre_trackers"), int)
                     and x["consent_pre_trackers"] > 0),
                    key=lambda x: x["site_id"])

    o = []
    A = o.append
    A("<!doctype html>")
    A('<html lang="en">')
    A("<head>")
    A('<meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<meta name="color-scheme" content="light dark">')
    A("<title>clevermethod fleet: consent</title>")
    A("<style>%s%s</style>" % (css_text, CONSENT_CSS))
    A("</head><body>")
    A('<div class="wrap">')

    A('<header class="top"><div><h1>Cookie consent'
      '<small>%d domains &middot; %d with tooling &middot; read-only</small></h1>'
      '<p class="thesis">Two questions, not one. What fires for a visitor who '
      'has done nothing, and what still fires after that visitor clicks Reject '
      'All. Only the second discriminates. '
      '<a href="/">Back to the fleet page</a>.</p></div></header>'
      % (len(swept), len(tooled)))

    # COVERAGE FIRST, as three separate denominators. The two sweeps ask
    # different populations -- the cold one reaches every domain, the gating
    # test only sites with a button to click -- so one number would be wrong
    # for one of them.
    A('<ul class="lanes">')
    for label, k, n in (("homepage loaded", len(seen), len(swept)),
                        ("tooling detected", len(tooled), len(seen)),
                        ("rejection tested", len(gated), len(tooled))):
        A('<li><span class="n">%d</span><span class="quiet">of %d %s</span></li>'
          % (k, n, e(label)))
    A("</ul>")

    # THE THREE STATES. Doug, 2026-08-27: act on what we manage, and still be
    # able to tell clients about what we do not, without the page implying we
    # broke theirs.
    A('<div class="states">')
    for cls, title, rows_, why in (
        ("crit", "Ours, and a tag ignores the rejection", ours_broken,
         "We manage consent here and something still fires after Reject All. "
         "The only group that is a defect in something we built."),
        ("good", "Ours, and gated", ours_ok,
         "Everything that fired on load stopped when consent was refused."),
        ("plan", "Not ours", theirs,
         "Trackers fire before consent and clevermethod does not manage this "
         "site. Worth telling the client; not our queue."),
    ):
        A('<section class="state state-%s"><h2>%s</h2>'
          '<p class="n">%d<span>sites</span></p><p class="why">%s</p>'
          % (cls, e(title), len(rows_), e(why)))
        # NAMED WHERE NAMING IS ACTIONABLE, COUNTED WHERE IT IS NOT. The two
        # small groups are a work list. "Not ours" is 39, and rendering all of
        # them turned a summary into a wall that buried the two cards somebody
        # can act on.
        if rows_ and len(rows_) <= 14:
            A('<p class="mono sl">%s</p>'
              % ", ".join(e(x["site_id"]) for x in rows_))
        elif rows_:
            A('<p class="mono sl">%s <span class="quiet">and %d more &mdash; '
              'all of them in the table below</span></p>'
              % (", ".join(e(x["site_id"]) for x in rows_[:6]), len(rows_) - 6))
        A("</section>")
    A("</div>")

    # UNTESTED IS ITS OWN ROW, never folded into "gated". "Nothing still fires
    # after rejection" is the best possible result, so a site the test could
    # not complete would otherwise read as the cleanest on the fleet.
    if untested:
        # THE REASON IS COMPUTED, NEVER TYPED. This sentence was the literal
        # "Two of these run a generic banner..." while the list beside it grew
        # from 3 to 9 (five WAF challenges on the reject pass, 2026-08-28), so
        # the page confidently explained a different list than the one it
        # printed. The generic-banner reason is the only one the ledger can
        # support -- the cold sweep's own vendor fact -- so that one is
        # computed and no other reason is guessed at; the rest live in the
        # run log.
        generic = [x for x in untested
                   if x.get("consent_banner_vendor") == "generic"]
        why = ((" %d of these run a generic banner with no Reject control "
                "the test knows how to find." % len(generic)) if generic else "")
        A('<p class="notice"><b>%d site(s) could not be tested for gating.</b> '
          'Not clean &mdash; unread.%s <span class="mono">%s'
          '</span></p>' % (len(untested), why,
                           ", ".join(e(x["site_id"]) for x in untested)))

    A('<h2 class="sec">Every site the sweep reached</h2>')
    # THE OURS TOGGLE. Consent work is done by whoever configures it, and the
    # first question they ask is "which of these are mine". Plain checkbox in
    # the same .tools bar the fleet page uses, and it rewrites the count so the
    # number always describes what is on screen -- the fleet page learned that
    # one the hard way, printing a fact about the view as a fact about the site.
    A('<div class="tools">')
    A('<label><input type="checkbox" id="oursonly"> Only sites we manage</label>')
    A('<span class="count" id="rowcount"></span>')
    A("</div>")
    A('<div class="mwrap"><table class="ctbl" id="ctbl"><thead>'
      "<tr><th>Site</th><th>Managed</th><th>Model</th><th>Tooling</th>"
      '<th class="num">On load</th><th>After reject</th><th>Cookieless</th>'
      "</tr></thead><tbody>")
    for x in sorted(seen, key=lambda y: y["site_id"]):
        managed = x.get("consent_managed") is True
        mchip = ('<span class="chip st-OK">ours</span>' if managed
                 else '<span class="quiet">client</span>')
        model = x.get("consent_model")
        mo = e(model) if model else '<span class="quiet">not ruled</span>'
        vendor = x.get("consent_banner_vendor")
        ven = (e(vendor) if vendor not in (None, "none", L.UNKNOWN)
               else '<span class="quiet">none</span>')
        pre = x.get("consent_pre_trackers")
        pre_s = str(pre) if isinstance(pre, int) else '<span class="quiet">?</span>'
        if x.get("gating_tested") is True:
            still = x.get("gating_still_firing") or 0
            after = ('<span class="chip st-OK">gated</span>' if not still
                     else '<span class="chip st-CRIT">%s</span>'
                          % e(x.get("gating_still_firing_names") or "?"))
        elif "gating_tested" in x:
            # UNMEASURED GETS THE HATCH, the same treatment the fleet page uses
            # for an absence. It must not read as a quiet pass.
            after = '<span class="chip st-UNKNOWN">not tested</span>'
        else:
            after = '<span class="quiet">&mdash;</span>'
        ck = x.get("gating_cookieless_names")
        ck_s = (e(ck) if ck not in (None, "none", L.UNKNOWN)
                else '<span class="quiet">&mdash;</span>')
        A('<tr data-ours="%s"><td class="mono">%s</td><td>%s</td><td>%s</td>'
          '<td>%s</td><td class="num mono">%s</td><td>%s</td>'
          '<td class="quiet">%s</td></tr>'
          % ("1" if managed else "0", e(x["site_id"]), mchip, mo, ven,
             pre_s, after, ck_s))
    A("</tbody></table></div>")

    A('<h2 class="sec">What this page does not establish</h2>')
    A('<ul class="caveats">')
    A("<li><b>Location.</b> The sweep records what fired from wherever it ran, "
      "and does not record where that was. A site with a geolocation rule "
      "behaves differently elsewhere.</li>")
    A("<li><b>One page.</b> The homepage only. A tag that fires on a form page "
      "and not the homepage is invisible here.</li>")
    A("<li><b>A floor, not a total.</b> Some vendors decline to fire under "
      "automation, so a tracker count is the least that fired, never the "
      "most.</li>")
    A("<li><b>Not a compliance verdict.</b> These are observations about tag "
      "behaviour. Whether a configuration meets a given law is a question for "
      "someone qualified to answer it.</li>")
    A("<li><b>Cookieless Google pings are not leaks.</b> A GA or Ads request "
      "carrying <code>gcs=G100</code> after a rejection is what a correctly "
      "configured site does; it has its own column rather than a finding.</li>")
    A("</ul>")

    A('<footer class="foot">Generated %s from the ledger at '
      "<code>history/</code>. Read-only: this page reports, it never changes a "
      "site.</footer>" % e(m["generated"]))
    A("</div>")
    A("""<script>
(function () {
  var box = document.getElementById('oursonly');
  var rows = [].slice.call(document.querySelectorAll('#ctbl tbody tr'));
  var out = document.getElementById('rowcount');
  function draw() {
    var only = box.checked, shown = 0;
    rows.forEach(function (r) {
      var keep = !only || r.getAttribute('data-ours') === '1';
      r.hidden = !keep;
      if (keep) shown++;
    });
    // THE COUNT DESCRIBES WHAT IS ON SCREEN, and says so against the total.
    // A bare number here would be a fact about the view wearing the clothes of
    // a fact about the fleet -- the exact mistake the components page made
    // when a filter rewrote "the 1 component installed on <site>".
    out.textContent = shown + ' of ' + rows.length + ' rows shown';
  }
  box.addEventListener('change', function () {
    draw();
    // Survives a reload and a shared link. Someone sending "look at ours"
    // should be able to send the URL.
    var u = new URL(location.href);
    if (box.checked) u.searchParams.set('ours', '1');
    else u.searchParams.delete('ours');
    history.replaceState(null, '', u);
  });
  if (new URLSearchParams(location.search).get('ours') === '1') box.checked = true;
  draw();
})();
</script>""")
    A("</body></html>")
    A("")
    return "\n".join(o)


CONSENT_CSS = """
.states { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); margin: 0 0 12px; }
.state { border: 1px solid var(--line); background: var(--surface); padding: 12px 14px; }
/* Tone on a left bar, not a fill. Three filled cards in three colours reads as
   a traffic light, and these are not three severities -- they are three
   OWNERS. */
.state-crit { border-left: 3px solid var(--crit); }
.state-good { border-left: 3px solid var(--good); }
.state-plan { border-left: 3px solid var(--plan); }
.state h2 { margin: 0; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink2); }
.state .n { font-family: var(--font-mono); font-size: 30px; font-weight: 500; margin: 2px 0 4px; }
.state .n span { font-family: var(--font-body); font-size: 12px; color: var(--ink2); margin-left: 6px; }
.state .why { font-size: 12.5px; color: var(--ink2); margin: 0; line-height: 1.5; }
.state .sl { font-size: 12px; margin: 8px 0 0; line-height: 1.7; }
.notice { border: 1px solid var(--line); border-left: 3px solid var(--plan); background: var(--surface); padding: 10px 14px; font-size: 12.5px; margin: 0 0 14px; }
h2.sec { font-size: 15px; margin: 22px 0 8px; }
.ctbl { border-collapse: collapse; width: 100%; font-size: 13px; }
.ctbl th, .ctbl td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); vertical-align: top; white-space: nowrap; }
.ctbl thead th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink2); font-weight: 600; }
.ctbl .num { text-align: right; }
.caveats { margin: 0; padding-left: 20px; line-height: 1.6; font-size: 13px; max-width: 78ch; }
.caveats li { margin-bottom: 7px; }
"""


def render_components(m):
    """The component catalogue, plugin-major.

    A SEPARATE PAGE rather than a popout on the fleet table. A popout lives in
    a site row, so it can only ever answer "what is pending on this site" --
    which the count in that row already answers. The question a count cannot
    answer is "which of our sites run this component, at what versions", and
    that is the one that mattered when Pods CVE-2026-19598 landed with no
    patch for ~36 hours. Same rows, pivoted.
    """
    c = m["components"]
    cat = c["catalogue"]
    o = []
    A = o.append
    A("<!doctype html><html lang=en><meta charset=utf-8>")
    A('<meta name=viewport content="width=device-width,initial-scale=1">')
    A("<title>clevermethod fleet: components</title><style>%s%s</style>"
      % (css(), COMPONENT_CSS))
    A('<div class=wrap>')

    A('<div class=masthead>')
    A("<h1>Components</h1>")
    A('<p class=sub>Every plugin, mu-plugin and theme installed across the '
      'fleet, and which sites run it. <a href="/">Back to the fleet '
      'page</a>.</p>')
    A("</div>")

    # COVERAGE FIRST, and named rather than counted. A search for `pods` that
    # returns three sites reads as "three sites run pods" unless the page has
    # already said how much of the fleet it can see. The sites it cannot see
    # are listed, because "6 sites are missing" is a number nobody can act on.
    inv_n, exp_n = len(c["sites_inventoried"]), len(c["expected"])
    tone = "good" if inv_n >= exp_n else "info"
    A('<div class="card" style="margin-bottom:14px">')
    # The out-of-scope count is every host NO component transport reaches, not
    # every host that is not Pantheon. Computed the second way it came to 32,
    # which silently included the 22 Nexcess sites this page inventories -- the
    # page disclaiming data it was displaying two screens below.
    out_of_scope = len([x for x in m["sites"]
                        if (x.get("host") or "") not in COMPONENT_HOSTS])
    A('<div><b>This page can see %d of %d sites on %s.</b> '
      'Nothing here is a statement about the other %d, or about the %d site(s) '
      'on hosts no component scan reaches. No component has ever been listed '
      'for those.</div>'
      % (inv_n, exp_n, component_host_phrase(), exp_n - inv_n, out_of_scope))
    if c["sites_missing"]:
        A('<div class=quiet style="margin-top:6px">Not inventoried: %s</div>'
          % ", ".join("<code>%s</code>" % e(x) for x in c["sites_missing"]))
    A('<div class="cov %s" style="margin-top:10px"><div style="color:var(--ink)">'
      'Component inventory</div><div class=n>%d of %d</div>'
      '<div class="m meter"><i style="width:%.1f%%"></i></div></div>'
      % (tone, inv_n, exp_n, (100.0 * inv_n / exp_n) if exp_n else 0))
    A("</div>")

    if not cat:
        # An empty catalogue is an ABSENCE, never an empty list rendered as a
        # complete answer.
        A('<div class="card"><b>No component has been inventoried yet.</b> '
          '<span class=quiet>The scanner keeps this from the full (SSH) run '
          'only, and no such run has been ingested since the inventory was '
          'switched on. This is not a fleet that runs no plugins.</span></div>')
        A("</div>")
        return "\n".join(o)

    A('<div class=kpis style="margin-bottom:14px">')
    for lab, val, note in (
            ("distinct components", len(cat),
             "%d installs across %d sites" % (c["rows"], inv_n)),
            ("updates pending", c["pending_total"],
             "%d component(s) have one waiting"
             % len([x for x in cat if x["pending"]])),
            ("on more than one site", len([x for x in cat if x["sites"] > 1]),
             "shared components; a CVE in one is a fleet question"),
            ("version spread", len([x for x in cat if len(x["versions"]) > 1]),
             "run at more than one version across the fleet")):
        A('<div class=kpi><div class=lab>%s</div><div class=val>%d</div>'
          '<div class=note>%s</div></div>' % (e(lab), val, e(note)))
    A("</div>")

    A('<div class=filters>')
    A('<input id=q type=search placeholder="Search component or site&hellip;" '
      'autocomplete=off>')
    A('<select id=type><option value="">every type</option>'
      '<option value=plugin>plugin</option>'
      '<option value=mu-plugin>mu-plugin</option>'
      '<option value=theme>theme</option></select>')
    # The site picker. Populated from the sites that HAVE an inventory, not
    # from the fleet: offering a site whose components were never listed would
    # produce an empty result that reads as "this site runs nothing".
    A('<select id=site><option value="">the whole fleet</option>')
    for sid in c["sites_inventoried"]:
        A('<option value="%s">%s</option>' % (e(sid), e(sid)))
    A("</select>")
    A('<select id=scope><option value="">every component</option>'
      '<option value=pending>updates pending</option>'
      '<option value=spread>more than one version</option>'
      '<option value=shared>on more than one site</option></select>')
    A('<span class=quiet id=count style="align-self:center"></span>')
    A("</div>")

    # Stated, not implied. When one site is selected the Sites, Versions and
    # Pending columns still describe the WHOLE FLEET -- `wordpress-seo` reads
    # "45 sites, 40 pending" whether or not you have filtered to one of them.
    # A fleet-wide count sitting in a view that looks per-site is the same
    # failure as a count standing in for an absence, pointed the other way, so
    # the page says which is which rather than leaving it to be inferred.
    # A site named in the URL that has NO inventory. Falling back to a text
    # search leaves "0 of 312 components" on screen, which reads as "this site
    # runs no plugins" when the truth is that nobody ever listed them. Same
    # distinction as everywhere else on this page: unknown is not a no.
    A('<div id=nositenotice class=card style="display:none;margin-bottom:10px;'
      'border-left:3px solid var(--bad)">'
      '<div><b><code id=nositename></code> has no component inventory.</b> '
      'This is not a site with no plugins. It is a site whose plugins '
      'have never been listed. Nothing below describes it.</div>'
      '<div class=quiet style="margin-top:6px">Every DB-backed WP-CLI call '
      'fails on a site whose database is not installed, and a site outside the '
      'Pantheon deep scan is never reached at all. See the coverage line '
      'above.</div></div>')

    # THE COUNT THIS PAGE IS REACHED BY IS A DIFFERENT COUNT. The fleet
    # table's plugin cell means "updates PENDING" -- 1 for 11daypowerplay.com
    # -- and it links here, where the same site shows 26 plugins INSTALLED.
    # Both are right and the page said nothing to reconcile them, so the link
    # read as a contradiction. It now states installed AND pending, and names
    # the fleet page's number explicitly.
    A('<div id=sitebanner class=card style="display:none;margin-bottom:10px">'
      '<div><b>Showing the <span id=sitecount></span> component(s) installed '
      'on <code id=sitename></code></b>, of which '
      '<b><span id=sitepending></span></b>. That second number is the '
      'plugin/theme count on the fleet page.</div>'
      '<div class=quiet style="margin-top:6px">The <em>On this site</em> '
      'column is this site\'s own version. <b>Sites</b>, <b>Versions</b> and '
      '<b>Pending</b> stay fleet-wide: they describe the component across all '
      '%d inventoried sites, not this one.</div>'
      '<div style="margin-top:6px"><a href="#" id=clearsite>Show the whole '
      'fleet again</a></div></div>' % len(c["sites_inventoried"]))

    A('<div class=tablewrap><table id=cat>')
    A("<tr><th data-sort=slug>Component</th><th data-sort=type>Type</th>"
      "<th class=persite hidden>On this site</th>"
      "<th data-sort=sites class=num>Sites</th>"
      "<th data-sort=vers class=num>Versions</th>"
      "<th data-sort=pending class=num>Pending</th>"
      "<th>Where it runs</th></tr>")
    for x in cat:
        sites_attr = " ".join(i["site_id"].lower() for i in x["installs"])
        flags = []
        if x["pending"]:
            flags.append("pending")
        if len(x["versions"]) > 1:
            flags.append("spread")
        if x["sites"] > 1:
            flags.append("shared")
        A('<tr data-slug="%s" data-type="%s" data-sites-list="%s" '
          'data-flags="%s" data-n-sites="%d" data-n-vers="%d" '
          'data-n-pending="%d">'
          % (e(x["slug"].lower()), e(x["type"]), e(sites_attr),
             " ".join(flags), x["sites"], len(x["versions"]), x["pending"]))
        # The casing note is not cosmetic. A component whose directory name
        # differs across sites is one a case-sensitive CVE match would split,
        # and Wordfence publishes lowercase slugs. Say it on the row rather
        # than merging quietly.
        variants = x.get("variants") or []
        casing = ""
        if len(variants) > 1:
            casing = ('<div class=quiet style="font-size:11px">also on disk as '
                      '%s</div>'
                      % e(", ".join(v for v in variants if v != x["slug"])))
        # Same component twice on ONE site. hoffmanscheese carries
        # pdfembedder-premium 3.2 inactive beside PDFEmbedder-premium 5.1.4
        # active. Inactive still means files on disk.
        dupe = ""
        if x.get("installs_count", x["sites"]) > x["sites"]:
            dupe = ('<div class=quiet style="font-size:11px;color:var(--bad)">'
                    '%d install(s) across %d site(s): installed twice somewhere'
                    '</div>' % (x["installs_count"], x["sites"]))
        A("<td><code>%s</code>%s%s</td>" % (e(x["slug"]), casing, dupe))
        A("<td class=quiet>%s</td>" % e(x["type"]))
        A('<td class=persite hidden></td>')
        A("<td class=num>%d</td>" % x["sites"])
        # The VERSION SPREAD is the column a count cannot give you: one
        # component at five versions across the fleet is five different
        # answers to "are we affected".
        A('<td class=num>%s</td>'
          % (("<b>%d</b>" % len(x["versions"])) if len(x["versions"]) > 1
             else str(len(x["versions"]))))
        A("<td class=num>%s</td>"
          % (('<span class="chip info"><span class=dot></span>%d</span>'
              % x["pending"]) if x["pending"] else '<span class=quiet>0</span>'))
        A("<td>")
        A("<details><summary>%d site%s</summary><div class=installs>"
          % (x["sites"], "" if x["sites"] == 1 else "s"))
        for i in x["installs"]:
            # A literal arrow, not &rarr;. The same string goes into the
            # data-v attribute that the per-site column reads with
            # textContent, which does not decode entities -- so the entity
            # rendered as the characters "&rarr;" in that column. The page is
            # UTF-8; the character is fine in both places.
            bits = [e(i["version"])]
            if i["update_available"] and i["update_version"]:
                bits.append("\u2192 %s" % e(i["update_version"]))
            elif i["update_available"]:
                bits.append("\u2192 update available")
            st = ""
            if i["status"] in ("inactive", "must-use", "parent"):
                st = ' <span class=quiet>%s</span>' % e(i["status"])
            A('<div class=install data-site="%s" data-v="%s" data-pending="%s">'
              '<code>%s</code><span class=v>%s</span>%s</div>'
              % (e(i["site_id"].lower()), e(" ".join(bits)),
                 "1" if i["update_available"] else "",
                 e(i["site_id"]), " ".join(bits), st))
        A("</div></details>")
        A("</td></tr>")
    A("</table></div>")

    A('<p class=foot>Generated %s from <code>history/components.jsonl</code>, '
      'run <code>%s</code>. Read-only. An <span class=quiet>inactive</span> '
      'plugin is still on disk and is still listed; it is not evidence of '
      'safety.</p>'
      % (e(m["generated"]),
         e((m["latest"].get("health") or {}).get("run_id", "unknown"))))
    A("</div>")
    A(COMPONENT_JS)
    return "\n".join(o)


# ---------------------------------------------------------------------------
# THE PAGE, since 2026-08-27: the evidence matrix with a schedule tab.
# ---------------------------------------------------------------------------
# Chosen from three rendered concepts (see _scratch/redesign/ and
# docs/DASHBOARD-V3.md). The markup is built in the browser from a JSON model
# this function embeds; the Python side decides WHAT is true, the page decides
# only how to group and count it. Nothing in scripts/dashboard/page.js computes
# a status: every status and reason is severity.py's, read from the JSON.
#
# Why the model is embedded rather than fetched: the page must open from
# file:// and from behind Access with no second request, and a page whose data
# arrives separately can disagree with the page around it. One file, one model.
#
# render() below it is the previous page, kept for ONE cycle behind
# --legacy-out as the fallback if this one is wrong in production. Retire it,
# and the tests that pin its markup, once the new page has been published and
# read for a week.

PAGE_DIR = os.path.join(HERE, "dashboard")

# Facts the page carries per site. A superset of EMIT_FACTS: the feed is a
# contract for other consumers; the page is the one consumer that wants every
# family, email DNS included. Absence is preserved as-is -- None means the
# source never wrote the site, "unknown" means it asked and got no answer,
# "n/a" means the scan does not ask there -- and page.js renders each of the
# three as an absence token, never as a value.
PAGE_FACTS = EMIT_FACTS + (
    "components_checked",
    "smtp_plugin_seen", "smtp_from_domain", "smtp_relay_host", "smtp_transport",
    "nexcess_app", "nexcess_env", "nexcess_package", "nexcess_temp_domain",
    "spf_present", "spf_all_qualifier", "spf_checked_at", "dkim_present",
    "dkim_selector", "dmarc_at_from_present", "dmarc_at_from_policy",
    "dmarc_at_sending_present", "dmarc_at_sending_policy",
    "dmarc_via_org_fallback", "relaxed_aligned", "recorded_from_domain",
    "consent_rule", "consent_note")

# Workbook attestations the component inventory can check, and the plugin
# families that count as evidence. "Yes - Pantheon" / "Yes - CF WAF" name a
# platform control, which no plugin list can confirm or deny, so those are
# reported as not checkable rather than as absent.
ATTESTATION_SLUGS = {
    "hide_login": {"wps-hide-login"},
    "wp_2fa": {"wp-2fa", "wp-defender", "wordfence", "two-factor"},
    "activity_log": {"wp-security-audit-log"},
    "xmlrpc_disabled": {"disable-xml-rpc", "disable-xml-rpc-api", "disable-xmlrpc"},
}
ATTESTATION_LABEL = {
    "hide_login": "Login URL hidden", "wp_2fa": "2FA",
    "activity_log": "Activity log", "xmlrpc_disabled": "XML-RPC disabled",
    "single_cm_user": "Single CM user", "keeper_password": "Password in Keeper",
    "wp2shell_remedied": "wp2shell remedied",
}


def _attestations(site_id, rec, inventoried, active_slugs):
    out = []
    for k, v in (rec.get("attestations") or {}).items():
        val = v.get("value")
        ev = "n/a"
        if k in ATTESTATION_SLUGS:
            if isinstance(val, str) and ("Pantheon" in val or "WAF" in val):
                ev = "platform"
            elif site_id not in inventoried:
                ev = "not-inventoried"
            else:
                seen = bool(active_slugs.get(site_id, set()) & ATTESTATION_SLUGS[k])
                yes = isinstance(val, str) and val.startswith("Yes")
                # Yes + plugin -> evidence; Yes + none -> no-evidence;
                # No/blank + plugin -> unclaimed-evidence; No/blank + none ->
                # consistent-no. Four answers, kept four: a "No" with no plugin
                # is not a contradiction and must not count as one.
                ev = ("evidence" if (yes and seen) else "no-evidence" if yes
                      else "unclaimed-evidence" if seen else "consistent-no")
        out.append({"key": k, "label": ATTESTATION_LABEL.get(k, k), "value": val,
                    "evidence": ev, "source": v.get("source"),
                    "by": v.get("by"), "at": v.get("at")})
    return out


def _history_series(m):
    """Per-site series over the FULL health runs: plugin backlog, WordPress
    version, backup age. Full runs only, and only fleet-sized ones: api-only
    runs store unknown for the deep facts and one- or three-site debugging runs
    are not the fleet. Ten points is movement, not a trend, and the page
    labels it that way."""
    full = {r["run_id"] for r in m["runs"]
            if r.get("source") == "health" and r.get("mode") == "full"
            and (r.get("site_count") or 0) > 3}
    hist = collections.defaultdict(lambda: {"plugins": [], "wp": [], "backup": []})
    for o in sorted(m["obs"], key=lambda o: o.get("observed_at") or ""):
        if o.get("source") != "health" or o.get("run_id") not in full:
            continue
        h = hist[o["site_id"]]
        d = (o.get("observed_at") or "")[:10]
        if isinstance(o.get("plugin_updates"), int):
            h["plugins"].append([d, o["plugin_updates"]])
        if o.get("wp_version") not in (None, L.UNKNOWN):
            h["wp"].append([d, o["wp_version"]])
        if isinstance(o.get("db_backup_age_days"), int):
            h["backup"].append([d, o["db_backup_age_days"]])
    return hist


def page_data(m):
    """The model the page renders from. Built from the same `m` as render(),
    render_components() and emit_data(), so the four cannot disagree."""
    inv = m.get("inventory") or {}
    comp = m["components"]
    inventoried = set(comp["sites_inventoried"])
    # per site: active plugin slugs (for attestation evidence) and the pending list
    active = collections.defaultdict(set)
    pending = collections.defaultdict(list)
    for c in comp["catalogue"]:
        for i in c["installs"]:
            if i["status"] == "active":
                active[i["site_id"]].add(c["slug"].lower())
            if i["update_available"]:
                pending[i["site_id"]].append([c["slug"], c["type"], i["version"],
                                              i["update_version"]])
    hist = _history_series(m)
    sites = []
    for s in m["sites"]:
        sev = s.get("severity") or {}
        rec = inv.get(s["site_id"]) or {}
        axes = sev.get("axes") or {}
        sites.append({
            "id": s["site_id"],
            "host": s.get("host"),
            "hsn": s.get("host_site_name"),
            "production": s.get("production"),
            "counts": bool(sev.get("production", True)),
            "in_workbook": s.get("in_workbook"),
            "in_inventory": s.get("in_inventory", True),
            "reconciliation": s.get("reconciliation"),
            "notes": s.get("notes"),
            "sources": sorted(s.get("sources") or []),
            "health": axes.get("health", {"status": sev.get("status"),
                                          "reasons": sev.get("reasons", [])}),
            "consent": axes.get("consent", {"status": "UNKNOWN", "reasons": []}),
            "info": sev.get("info", []),
            "f": {k: s.get(k) for k in PAGE_FACTS},
            "claimed": s.get("claimed"),
            "att": _attestations(s["site_id"], rec, inventoried, active),
            "dns": rec.get("dns"),
            "email_provider": (rec.get("email") or {}).get("provider"),
            "decommission_candidate": bool(rec.get("decommission_candidate")),
            "pending": sorted(pending.get(s["site_id"], [])),
            "hist": hist.get(s["site_id"], {"plugins": [], "wp": [], "backup": []}),
        })
    runs_sorted = sorted(m["runs"], key=lambda r: r.get("observed_at") or "")
    latest = {}
    for r in runs_sorted:
        latest[r.get("kind") or r.get("source")] = {
            "run_id": r["run_id"], "observed_at": r.get("observed_at"),
            "mode": r.get("mode"), "site_count": r.get("site_count"),
            "deep_scanned": r.get("deep_scanned"), "method": r.get("method")}
    today = m.get("today") or datetime.date.fromisoformat(m["generated"])
    noon = datetime.datetime.combine(today, datetime.time(16, 0))  # ~noon Eastern, in UTC
    _local, zone = eastern(noon)
    feed = emit_data(m)
    return {
        "generated": m["generated"],
        "tz_offset_minutes": -240 if zone == "EDT" else -300,
        "tz_note": "UTC−4, EDT" if zone == "EDT" else "UTC−5, EST",
        "inventory_count": m["inventory_count"],
        "counts": m["health"]["counts"], "axes": m["health"]["axes"],
        "excluded": m["health"]["excluded"],
        "excluded_sites": m["health"]["excluded_sites"],
        "unreviewed": m["health"]["unreviewed"],
        "no_health_evidence": feed["no_health_evidence"],
        "severity_rules": feed["severity_rules"],
        "latest": latest,
        "all_runs": [{"run_id": r["run_id"], "source": r.get("source"),
                      "kind": r.get("kind") or r.get("source"), "mode": r.get("mode"),
                      "observed_at": r.get("observed_at"),
                      "site_count": r.get("site_count"),
                      "deep_scanned": r.get("deep_scanned")} for r in runs_sorted],
        "coverage": feed["coverage"],
        "coverage_changes": m["coverage_changes"],
        "coverage_regressions": m["coverage_regressions"],
        "changes": m["changes"],
        "standing": m["standing"],
        "standing_was": m["standing_was"],
        "unreconciled": [{"id": u["site_id"], "host": u.get("host"),
                          "why": u.get("reconciliation") or u.get("notes") or ""}
                         for u in m["unreconciled"]],
        "sites": sites,
        "components": {
            "catalogue": [{"slug": c["slug"], "type": c["type"],
                           "variants": c.get("variants", []), "sites": c["sites"],
                           "installs_count": c["installs_count"],
                           "versions": c["versions"], "pending": c["pending"],
                           "inactive": c["inactive"],
                           "target": [v for v, _n in collections.Counter(
                               i["update_version"] for i in c["installs"]
                               if i["update_available"]).most_common()],
                           "installs": [[i["site_id"], i["version"],
                                         i["status"] == "active",
                                         bool(i["update_available"]),
                                         i["update_version"]] for i in c["installs"]]}
                          for c in comp["catalogue"]],
            "rows": comp["rows"], "sites_inventoried": comp["sites_inventoried"],
            "sites_missing": comp["sites_missing"], "expected": comp["expected"],
            "pending_total": comp["pending_total"]},
    }


def render_page(m):
    """One self-contained file: the page CSS and JS from scripts/dashboard/
    inlined, the model embedded as JSON. No request leaves the page."""
    with open(os.path.join(PAGE_DIR, "page.css"), encoding="utf-8") as fh:
        css_text = fh.read()
    with open(os.path.join(PAGE_DIR, "page.js"), encoding="utf-8") as fh:
        js_text = fh.read()
    # `</` inside a JSON string would end the <script> early; escaping the
    # slash is a no-op for JSON and keeps the HTML parser out of the data.
    data = json.dumps(page_data(m), separators=(",", ":"),
                      ensure_ascii=False).replace("</", "<\\/")
    for label, blob in (("page.css", css_text), ("page.js", js_text)):
        if "</script" in blob.lower() or "</style" in blob.lower():
            raise SystemExit("%s contains a closing tag that would end its block" % label)
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        "<title>clevermethod fleet</title>",
        "<style>", css_text, "</style>",
        "</head>",
        "<body>",
        '<div id="app"></div>',
        '<script type="application/json" id="fleet-data">' + data + "</script>",
        "<script>", js_text, "</script>",
        "</body>",
        "</html>",
        "",
    ])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", default="./history")
    ap.add_argument("--inventory", default="./data/fleet-inventory.json")
    ap.add_argument("--out", default="./fleet.html",
                    help="the page: evidence matrix plus schedule tab, one "
                         "self-contained file (render_page).")
    ap.add_argument("--legacy-out", metavar="PATH",
                    help="also write the previous eleven-section page "
                         "(render). Kept for one cycle as the fallback if the "
                         "new page is wrong in production; see docs/DASHBOARD-V3.md.")
    ap.add_argument("--consent-out", metavar="PATH",
                    help="write the consent page here. Its own page because "
                         "the gating results are per tracker per pass, which "
                         "does not fit one row per site.")
    ap.add_argument("--vuln-out", metavar="PATH",
                    help="write the vulnerability page here. Its route must "
                         "exist in the Worker or it is uploaded and "
                         "unreachable, which looks exactly like never having "
                         "been rendered.")
    ap.add_argument("--components-out", metavar="PATH",
                    help="also render the component catalogue to PATH. The "
                         "fleet table's plugin count links to it, so publishing "
                         "one without the other leaves a dead link.")
    ap.add_argument("--emit-data", metavar="PATH",
                    help="also write the same model as JSON, for the Worker's "
                         "/api/fleet-scan route. Built from the model that "
                         "renders the page, so the two cannot disagree.")
    ap.add_argument("--today", help="override today (YYYY-MM-DD) for deterministic output")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if the ledger holds a site the "
                         "inventory does not. For CI, where nobody reads the "
                         "site count on stdout.")
    a = ap.parse_args()
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    m = build_model(a.history, a.inventory, today)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(render_page(m))
    if a.legacy_out:
        with open(a.legacy_out, "w", encoding="utf-8") as fh:
            fh.write(render(m))
        print("legacy page -> %s" % a.legacy_out)
    if a.components_out:
        with open(a.components_out, "w") as fh:
            fh.write(render_components(m))
        c = m["components"]
        print("components -> %s  (%d distinct, %d installs, %d of %d sites)"
              % (a.components_out, len(c["catalogue"]), c["rows"],
                 len(c["sites_inventoried"]), len(c["expected"])))
    if a.consent_out:
        with open(a.consent_out, "w") as fh:
            fh.write(render_consent(m))
        _g = [x for x in m["sites"] if x.get("gating_tested") is True]
        _bad = [x for x in _g if (x.get("gating_still_firing") or 0) > 0]
        print("consent -> %s  (%d gating-tested, %d still firing after reject)"
              % (a.consent_out, len(_g), len(_bad)))
    if a.emit_data:
        with open(a.emit_data, "w") as fh:
            json.dump(emit_data(m), fh, indent=1, sort_keys=False)
            fh.write("\n")
        print("data -> %s" % a.emit_data)
    c = m["health"]["counts"]
    print("%d sites, %d change(s), %d standing finding(s) -> %s"
          % (len(m["sites"]), len(m["changes"]), len(m["standing"]), a.out))
    print("  health: %s%s"
          % (" / ".join("%d %s" % (c[k], k) for k in SEV.ORDER if c.get(k)),
             ("   (%d excluded: %s)"
              % (sum(m["health"]["excluded"].values()),
                 ", ".join(m["health"]["excluded_sites"])))
             if m["health"]["excluded_sites"] else ""))
    # A NARROW SET DESCRIBED IN BROAD WORDS -- the signature shape in
    # CLAUDE.md's table. `unreviewed` is sites with no ownership record AND no
    # ruling, which is five. The number of sites needing a production ruling is
    # every site whose `production` is null, which is most of the fleet. The
    # on-page copy was always accurate; this line said the wrong thing in
    # fewer words. Logged in docs/DO-THIS-NEXT.md, fixed 2026-08-26.
    _unruled = len([x for x in m["sites"] if x.get("production") is None])
    if m["health"]["unreviewed"]:
        print("  %d site(s) have no owner AND no production ruling: %s"
              % (len(m["health"]["unreviewed"]),
                 ", ".join(m["health"]["unreviewed"])))
    if _unruled:
        print("  %d of %d site(s) have no production ruling at all"
              % (_unruled, len(m["sites"])))

    if a.vuln_out:
        with open(a.vuln_out, "w") as fh:
            fh.write(render_vulnerabilities(m))
        _v = m["vulnerabilities"]
        print("  vulnerabilities -> %s (%d finding(s) over %d site(s); "
              "%d site(s) NOT checked)"
              % (a.vuln_out, _v["n_findings"], len(_v["affected_sites"]),
                 len(_v["unmatched_sites"])))

    # Severity looked up an inventory record and did not find one. That means a
    # `production: false` ruling would have been silently ignored, which is the
    # quiet-mis-key failure this project has now hit twice.
    if L.MISSED_INVENTORY:
        print("\nWARNING: %d site(s) scored against no inventory record: %s"
              % (len(L.MISSED_INVENTORY), ", ".join(sorted(L.MISSED_INVENTORY))),
              file=sys.stderr)
        print("Any production ruling on those sites was NOT applied.",
              file=sys.stderr)
        if a.strict:
            sys.exit(1)

    # A site in the ledger but not in the inventory means some tool keyed a row
    # on an identifier nothing else uses, so that site now has two histories and
    # the page renders both as separate rows. It is exactly how a 84-site fleet
    # rendered as 130 rows on 2026-08-18, and the only reason anyone noticed was
    # that a person read the number. --strict is that person, for CI.
    orphans = sorted(s["site_id"] for s in m["sites"] if not s.get("in_inventory"))
    if orphans:
        print("", file=sys.stderr)
        print("%d site(s) in the ledger are not in the inventory:"
              % len(orphans), file=sys.stderr)
        shown = orphans[:12]
        print("  " + ", ".join(shown)
              + (", ... (%d more)" % (len(orphans) - 12) if len(orphans) > 12 else ""),
              file=sys.stderr)
        print("Expected %d sites, rendered %d."
              % (m["inventory_count"], len(m["sites"])), file=sys.stderr)
        if a.strict:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
