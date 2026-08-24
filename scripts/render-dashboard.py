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

    # Latest run per source, and the diff against the previous run of that source.
    by_source = {}
    for r in runs:
        by_source.setdefault(r.get("source", "health"), []).append(r)

    latest, changes, standing = {}, [], []
    for source, rs in by_source.items():
        prev, curr = L.previous_run_of_same_source(rs, obs=obs)
        latest[source] = curr
        rows = L.rows_for(obs, curr["run_id"])
        standing.extend(L.standing(rows, today))
        if prev is not None:
            for c in L.diff_runs(L.rows_for(obs, prev["run_id"]), rows, today, inv):
                c["source"] = source
                c["against"] = prev["run_id"]
                changes.append(c)

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
    for source, run in latest.items():
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
        hr = list(L.rows_for(obs, latest["health"]["run_id"]).values())
        coverage.append(("Pantheon platform facts (plan, PHP, backups, upstream)",
                         frac(hr, "php_version")))
        coverage.append(("WordPress core, plugins, themes (needs SSH)",
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
    comp_rows = (L.load_components(history_dir, latest["health"]["run_id"])
                 if "health" in latest else [])
    pantheon_sites = [s for s in sites if s.get("host") == "CM Pantheon"]
    inventoried = set(r["site_id"] for r in comp_rows)
    if pantheon_sites:
        coverage.append(("Component inventory (plugins, mu-plugins, themes)",
                         (len(inventoried & set(s["site_id"] for s in pantheon_sites)),
                          len(pantheon_sites))))

    nexcess_sites = [s for s in sites if s.get("host") == "CM Nexcess"]
    if nexcess_sites:
        nx_known = sum(1 for s in nexcess_sites
                        if s.get("nexcess_app_version") not in (None, L.UNKNOWN))
        coverage.append(("Nexcess estate (PHP, WordPress version, via the portal API)",
                         (nx_known, len(nexcess_sites))))

    unreconciled = [s for s in sites
                    if s.get("in_workbook") is False or s.get("reconciliation")]

    return {
        "runs": runs, "latest": latest, "changes": changes, "standing": standing,
        "sites": sites, "coverage": coverage, "inventory_count": len(inv),
        "components": build_components(comp_rows, sites, inventoried,
                                       pantheon_sites),
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
        "consent_method": (latest.get("consent") or {}).get("method"),
        "consent_method_changed": bool(
            "consent" in latest
            and (latest["consent"].get("method")
                 != next((r.get("method") for r in reversed(by_source.get("consent", [])[:-1])),
                         None))
            and len(by_source.get("consent", [])) > 1),
        "generated": today.isoformat(),
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
              "consent_http_status", "consent_final_url")


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


def chip(text, tone):
    return '<span class="chip %s"><span class="dot"></span>%s</span>' % (tone, e(text))


# One line per source, for the provenance block. Keyed on the ledger's source
# name so a source that has never run still has an answer waiting for it.
SOURCE_ANSWERS = {
    "health":    "Pantheon platform + WP-CLI, per site",
    "consent":   "public homepage in a real browser",
    "email-dns": "public DNS, per domain",
    "nexcess":   "Nexcess control plane",
}


def coverage_section(A, m, e):
    """The one place that says who looked, when, and at how much.

    Moved here 2026-08-23 and merged with the run line. It renders high on
    the page now -- directly under the scoreboard -- because a coverage
    caveat three sections below the number it qualifies is a caveat nobody
    reads. The per-number warnings stay inline with their numbers; only the
    general provenance moved.
    """
    # --- coverage ---------------------------------------------------------
    A("<h2>What this page knows, and what it does not</h2>")
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
    A('<p class=sub style="margin:-4px 0 10px">Every value on this page is one '
      'of two things, and they are labelled. A <strong>measurement</strong> was '
      'read off a site, a DNS record or a hosting API by one of the tools below '
      'and stored in an append-only ledger. A <strong>ruling</strong> is a '
      'decision someone on the team has already made: which sites exist, who '
      'hosts them, and whether a site counts as production. Nothing on this '
      'page is editable. It is generated, and both the measurements and the '
      'rulings come from source data kept outside it. A green row is worth '
      'exactly as much as the coverage behind it, so the coverage is on the '
      'same screen. Unknown is shown as unknown, never as a pass.</p>')

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
    A('<div class=card style="margin-bottom:10px"><div class=kpis>')
    for src in sorted(L.FACT_FAMILIES):
        meta = m["latest"].get(src)
        if meta:
            stamp, tone = when(meta.get("observed_at")), ""
        else:
            stamp, tone = "never run", ' class=quiet'
        A('<div class=kpi><div class=lab>%s</div>'
          '<div class=val style="font-size:15px"><span%s>%s</span></div>'
          '<div class=note>%s</div></div>'
          % (e(src), tone, e(stamp), e(SOURCE_ANSWERS.get(src, ""))))
    A("</div></div>")

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

    A("<div class=card>")
    for label, (known, total) in m["coverage"]:
        pct = (100.0 * known / total) if total else 0
        tone = "good" if pct >= 99 else ("info" if pct >= 50 else "bad")
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
          '<div class=n>%d of %d</div>'
          '<div class="m meter"><i style="width:%.1f%%"></i></div></div>'
          % (tone, text, known, total, pct))
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
    A('</div>')

    A('<div class="card topband">')
    A('<div class=topmain>')
    A('<div class=hero>%d</div>' % len(pushable))
    A('<div class=hero-sub>%s</div>'
      % ("change(s) needing a decision since the previous run of each tool."
         if pushable else
         "changes needing a decision. The fleet is stable; the standing "
         "findings below are unchanged."))
    A('</div>')

    A('<div class=topside>')
    cov_n = sum(len(g["sites"]) for g in m["coverage_changes"])
    cov_sites = len(set(x for g in m["coverage_changes"] for x in g["sites"]))
    for val, label in [
        (len(risk), "open risk causes, grouped by cause not by site"),
        (len(m["unreconciled"]), "sites in one source but not the other"),
        (len(drift), "counters moved on findings already open, suppressed"),
        (cov_n, "facts crossed the unknown boundary on %d site(s): this "
                "tool&rsquo;s coverage changing, not the fleet&rsquo;s" % cov_sites),
    ]:
        if not val:
            continue
        A('<div class=toprow><b>%s</b><span>%s</span></div>' % (e(val), label))
    A('</div>')
    A('</div>')

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

    A("<h2>The suite</h2>")
    A('<p class=sub style="margin:-4px 0 10px">One card per question. A site has '
      'a status on <em>each</em> axis independently: a site can be well '
      'maintained and still leak trackers. Scored from the ledger at render '
      'time, so changing a '
      'threshold rescores all of history rather than reporting as a fleet '
      'change.</p>')
    A('<div class=suite>')

    def card(title, blurb, counts_map, cov, detail=None, note=None, axis=None):
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
        A('</div>')

    # HEALTH ----------------------------------------------------------------
    nh = len([x for x in m["sites"]
              if any(r.get("code") == "coverage_partial"
                     for r in (x.get("severity") or {}).get("reasons", []))])
    k, n = _cov("Pantheon platform facts")
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
    hbits = []
    for codes, label in (
            (("backup_missing", "backup_stale", "backup_aging"),
             "have no recent database backup"),
            (("core_update",), "are behind on WordPress core"),
            (("plugin_backlog",), "have a plugin backlog"),
            (("php_eol",), "run PHP past end of security support")):
        c = sum(hcodes.get(x, 0) for x in codes)
        if c:
            hbits.append('<span class=wfrow><b>%d</b> %s</span>' % (c, e(label)))
    card("Fleet health",
         "Is this site being maintained: backups, PHP, WordPress, plugins.",
         ax.get("health") or h["counts"], _bar(k, n, "Pantheon platform facts"),
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
    _no_sending = len([x for x in m["sites"]
                       if x.get("spf_present") is None
                       and not x.get("spf_checked_at")])
    email_causes = [g for g in m["standing"]
                    if g["axis"] == "RISK"
                    and ("DMARC" in g["cause"] or "SPF" in g["cause"]
                         or "aligned" in g["cause"])]
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
      'authenticate its mail. Usually not the site\'s own domain: 34 sites '
      'send through <code>smtp.clevermethod.net</code>, so they are scored on '
      'that.</div>')
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
    A('<div class=wfnote>Scored per SENDING DOMAIN, not per site, so it has no '
      'status chip of its own. Several sites '
      'share one sending domain and therefore one result. The fleet table '
      'below carries the per-site result in its <strong>Sends from</strong>, '
      'SPF, DKIM and DMARC columns. <strong>%d open '
      'cause(s)</strong>, listed under Still open.'
      '<div style="margin-top:6px">The sending domain is <strong>recorded by a '
      'person</strong> in the audit workbook, not measured. Nothing in DNS '
      'reveals where a WordPress site was configured to send from. '
      '<strong>%d site(s) have none recorded</strong> and are UNKNOWN here, '
      'never a pass.</div></div>' % (len(email_causes), _no_sending))
    A('</div>')

    A('</div>')

    # --- fleet health -----------------------------------------------------
    counts, excl = h["counts"], h["excluded"]
    coverage_section(A, m, e)

    A("<h2>What the states mean</h2>")
    A('<p class=sub style="margin:-4px 0 10px">Scored from the ledger at render '
      'time, not at scan time. Thresholds are named constants in '
      '<code>scripts/lib/severity.py</code>; changing one rescores every run in '
      'history and does not report as a fleet change.</p>')
    A("<div class=card><div class=kpis>")
    for st in SEV.ORDER:
        n = counts.get(st, 0)
        if not n and st in ("UNKNOWN", "FROZEN", "SKIP"):
            continue
        A('<div class=kpi><div class=lab>%s</div><div class=val>%s</div>'
          '<div class=note>%s</div></div>'
          % (chip(st, STATE_TONE.get(st, "muted")), e(n),
             e(STATE_MEANING.get(st, ""))))
    A("</div>")

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
    if no_health:
        A('<p class=sub style="margin:10px 0 0">The <strong>%d site(s) with no '
          'health evidence</strong> named on the health card above are NOT the '
          'same question as UNKNOWN. UNKNOWN asks whether any scan reached a '
          'site at all; the consent sweep reaches every domain, so no site is '
          'UNKNOWN on health and that number is 0. Coverage asks whether we '
          'know how a site is <em>maintained</em>, which is the number to '
          'watch.</p>' % len(no_health))
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
        A("<h2>Needs a decision</h2>")
        A('<p class=sub style="margin:-4px 0 10px">%d site(s) with no ownership '
          'record and no production ruling. Nobody has decided whether these '
          'matter, so they are counted as production until someone does. On '
          'this fleet that set has included the two worst-maintained sites, so '
          'it is worth clearing once.</p>' % len(h["unreviewed"]))
        A("<div class=card><div class=tablewrap><table>"
          "<tr><th>Site</th><th>State</th><th>Plan</th>"
          "<th>Why it is here</th></tr>")
        by_id = {x["site_id"]: x for x in m["sites"]}
        for sid in h["unreviewed"]:
            s_ = by_id.get(sid, {})
            st = s_.get("status")
            reasons = "; ".join(r["text"] for r in
                                (s_.get("severity") or {}).get("reasons", []))
            A("<tr><td><code>%s</code></td><td>%s</td><td class=quiet>%s</td>"
              "<td>%s</td></tr>"
              % (e(sid), chip(st, STATE_TONE.get(st, "muted")) if st else "—",
                 e(s_.get("plan") or "—"),
                 e(reasons or "In the Pantheon account, with no client, owner "
                              "or production ruling in the inventory.")))
        A("</table></div></div>")

    # --- what changed -----------------------------------------------------
    A("<h2>What changed</h2><div class=card>")
    if not m["changes"]:
        A('<p class=big-quiet>Nothing, in either source.</p>')
    else:
        A("<div class=tablewrap><table>"
          "<tr><th>Class</th><th>Site</th><th>Fact</th><th>Before</th>"
          "<th>After</th><th>Source</th></tr>")
        for c in m["changes"]:
            A("<tr><td>%s</td><td><code>%s</code></td><td>%s</td><td class=num>%s</td>"
              "<td class=num>%s</td><td class=quiet>%s</td></tr>"
              % (chip(c["class"], CLASS_TONE.get(c["class"], "info")), e(c["site"]),
                 e(c["fact"]), e(c["before"]), e(c["after"]), e(c.get("source"))))
        A("</table></div>")
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
    A("<h2>Still open, as of the latest run of each tool</h2>")
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
    A("<h2>Every site</h2>")
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
      '<option value="__nohealth">No health evidence</option></select>'
      '<select id=consent><option value="">All consent states</option></select></div>')
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
          ' data-nohealth="%s">'
          "<td><code>%s</code>%s</td><td class=quiet>%s</td><td>%s</td><td>%s</td>"
          "<td class=num>%s</td><td>%s</td><td class=num>%s</td>"
          "<td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
          "<td class=quiet>%s</td>"
          "<td>%s</td><td class=quiet>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
          % (e(s["site_id"].lower()), e(s.get("host") or ""), e(st or ""), e(cst),
             nohealth,
             e(s["site_id"]),
             ('<br><span class=quiet style="font-size:11.5px">not production, '
              'excluded from the counts above</span>' if excluded else ""),
             e(s.get("host") or "—"), state, consent_cell(s),
             observed(s.get("php_version"), s.get("nexcess_php_version")),
             backup(s.get("db_backup_age_days")),
             e(s.get("upstream_pending", "—")),
             wp_version_cell(s.get("wp_version"), s.get("nexcess_app_version")),
             observed(s.get("wp_core_update")),
             plugin_cell(s),
             observed(s.get("theme_updates")),
             sends_from(s),
             yn(s.get("spf_present")), e(s.get("dkim_selector") or "—"),
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
     var okState = !s || (s==='__nohealth' ? r.dataset.nohealth==='1'
                                           : r.dataset.state===s);
     r.style.display=(!q||r.dataset.site.indexOf(q)>-1)&&(!h||r.dataset.host===h)
       &&okState&&(!c||r.dataset.consent===c)?'':'none';});
 }
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
    A('<div><b>This page can see %d of %d Pantheon sites.</b> '
      'Nothing here is a statement about the other %d, or about the %d sites '
      'on other hosts. No component has ever been listed for them.</div>'
      % (inv_n, exp_n, exp_n - inv_n,
         len([x for x in m["sites"] if (x.get("host") or "") != "CM Pantheon"])))
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", default="./history")
    ap.add_argument("--inventory", default="./data/fleet-inventory.json")
    ap.add_argument("--out", default="./fleet.html")
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
    with open(a.out, "w") as fh:
        fh.write(render(m))
    if a.components_out:
        with open(a.components_out, "w") as fh:
            fh.write(render_components(m))
        c = m["components"]
        print("components -> %s  (%d distinct, %d installs, %d of %d sites)"
              % (a.components_out, len(c["catalogue"]), c["rows"],
                 len(c["sites_inventoried"]), len(c["expected"])))
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
    if m["health"]["unreviewed"]:
        print("  %d site(s) need a production ruling: %s"
              % (len(m["health"]["unreviewed"]),
                 ", ".join(m["health"]["unreviewed"])))

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
