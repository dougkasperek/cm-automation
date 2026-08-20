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
* **No chart is drawn here, deliberately.** The counts are a handful of named
  classes, which is a stat tile and a table, not a bar chart; and with four runs
  in the ledger a trend line would be two points pretending to be a trend. Charts
  arrive when there is history to justify them.
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
    "light": {"good": "#1baf7a", "bad": "#eb6834", "info": "#2a78d6", "muted": "#8d9199",
              "surface": "#faf7f2", "card": "#ffffff", "ink": "#232320",
              "ink2": "#5c5b55", "line": "#ece5da"},
    "dark": {"good": "#199e70", "bad": "#d95926", "info": "#3987e5", "muted": "#8d9199",
             "surface": "#1a1a19", "card": "#232320", "ink": "#f5f0e8",
             "ink2": "#a09e96", "line": "#383835"},
}

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
        # The workbook's last known values, carried but NEVER mixed in with
        # observations. A human typing 7.0.2 into a spreadsheet is a claim; a
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

    unreconciled = [s for s in sites
                    if s.get("in_workbook") is False or s.get("reconciliation")]

    return {
        "runs": runs, "latest": latest, "changes": changes, "standing": standing,
        "sites": sites, "coverage": coverage, "inventory_count": len(inv),
        "unreconciled": unreconciled, "health": health,
        "coverage_changes": coverage_changes,
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
               "workbook_claims": s.get("claimed") or {}}
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


def css():
    out = [":root{"]
    for k, v in PALETTE["light"].items():
        out.append("--%s:%s;" % (k, v))
    out.append("}@media(prefers-color-scheme:dark){:root{")
    for k, v in PALETTE["dark"].items():
        out.append("--%s:%s;" % (k, v))
    out.append("}}")
    out.append("""
*{box-sizing:border-box}
body{margin:0;padding:28px 20px 64px;background:var(--surface);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:20px;margin:0 0 2px;font-weight:650}
h2{font-size:15px;margin:34px 0 10px;font-weight:650;letter-spacing:.01em}
.sub{color:var(--ink2);font-size:13px;margin:0 0 26px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:14px}
/* Hero: one per view, >=48px, same sans, proportional figures (never tabular). */
.hero{font-size:52px;line-height:1.05;font-weight:650;letter-spacing:-.02em;margin:2px 0 4px}
.hero-sub{color:var(--ink2);font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .lab{color:var(--ink2);font-size:12px;margin-bottom:6px}
.kpi .val{font-size:26px;font-weight:650;letter-spacing:-.01em}
.kpi .note{color:var(--ink2);font-size:12px;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:600;color:var(--ink2);font-size:12px;text-transform:uppercase;
 letter-spacing:.04em;padding:0 10px 8px 0;border-bottom:1px solid var(--line)}
td{padding:9px 10px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num{font-variant-numeric:tabular-nums}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink)}
/* Chip: colour is never the only signal. The label is always present. */
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
 white-space:nowrap;padding:2px 9px 2px 7px;border-radius:999px;
 border:1px solid color-mix(in srgb,currentColor 34%,transparent);
 background:color-mix(in srgb,currentColor 11%,transparent)}
.chip .dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.good{color:var(--good)}.bad{color:var(--bad)}.info{color:var(--info)}.muted{color:var(--muted)}
/* Meter: fill carries state, track is a lighter step of the SAME colour so the
   whole bar reads, per the marks spec. */
.meter{height:7px;border-radius:999px;background:color-mix(in srgb,currentColor 18%,transparent);
 overflow:hidden;margin-top:7px}
.meter>i{display:block;height:100%;background:currentColor;border-radius:999px}
.cov{display:grid;grid-template-columns:1fr auto;gap:2px 14px;align-items:baseline;margin-bottom:14px}
.cov .n{font-variant-numeric:tabular-nums;color:var(--ink2);font-size:12.5px}
.cov .m{grid-column:1/-1}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
input,select{font:13px inherit;padding:7px 10px;border:1px solid var(--line);border-radius:7px;
 background:var(--card);color:var(--ink);min-width:150px}
.quiet{color:var(--ink2)}
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
.wfn{font-size:22px;font-weight:640;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.wfcov{margin-top:auto;padding-top:4px}
.wfbar{height:6px;border-radius:3px;background:var(--line);overflow:hidden}
.wfbar i{display:block;height:100%;border-radius:3px}
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
.wfminirow .wfbar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;display:block}
""")
    return "".join(out)


def chip(text, tone):
    return '<span class="chip %s"><span class="dot"></span>%s</span>' % (tone, e(text))


def render(m):
    o = []
    A = o.append
    A("<!doctype html><html lang=en><meta charset=utf-8>")
    A('<meta name=viewport content="width=device-width,initial-scale=1">')
    A("<title>clevermethod fleet</title><style>%s</style>" % css())
    A('<div class=wrap>')
    A("<h1>clevermethod fleet</h1>")
    srcs = ", ".join("%s %s" % (s, r["observed_at"].replace("T", " "))
                     for s, r in sorted(m["latest"].items()))
    A('<p class=sub>%d sites in the inventory. Latest runs: %s. Read-only.</p>'
      % (m["inventory_count"], e(srcs)))

    # --- hero: the one number the page leads with -------------------------
    pushable = [c for c in m["changes"] if c["class"] not in L.QUIET_CLASSES]
    drift = [c for c in m["changes"] if c["class"] == "DRIFT"]
    A('<div class=card>')
    A('<div class=hero>%d</div>' % len(pushable))
    if pushable:
        A('<div class=hero-sub>change(s) needing a decision since the previous run '
          'of each tool.</div>')
    else:
        A('<div class=hero-sub>changes needing a decision since the previous run of '
          'each tool. The fleet is stable; the standing findings below are unchanged.</div>')
    if drift:
        A('<div class=hero-sub style="margin-top:6px">%d counter(s) moved on findings '
          'already open, suppressed as noise.</div>' % len(drift))
    if m["coverage_changes"]:
        n = sum(len(g["sites"]) for g in m["coverage_changes"])
        A('<div class=hero-sub style="margin-top:6px">%d fact(s) crossed the '
          'unknown boundary on %d site(s). That is this tool\'s coverage '
          'changing, not the fleet\'s. Summarised below, not counted '
          'here.</div>'
          % (n, len(set(x for g in m["coverage_changes"] for x in g["sites"]))))
    A('</div>')

    # --- kpi row ----------------------------------------------------------
    risk = [g for g in m["standing"] if g["axis"] == "RISK"]
    A('<div class=kpis>')
    for lab, val, note in [
        ("Sites tracked", len(m["sites"]), "across %d host(s)" %
         len({s.get("host") for s in m["sites"] if s.get("host")})),
        ("Open risk causes", len(risk), "grouped by cause, not by site"),
        ("Needs reconciling", len(m["unreconciled"]),
         "in one source but not the other"),
        ("Tools feeding the ledger", len(m["latest"]),
         "one history per site regardless"),
    ]:
        A('<div class=kpi><div class=lab>%s</div><div class=val>%s</div>'
          '<div class=note>%s</div></div>' % (e(lab), e(val), e(note)))
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
      'maintained and still leak trackers, and until 2026-08-20 this page could '
      'not say that. Scored from the ledger at render time, so changing a '
      'threshold rescores all of history rather than reporting as a fleet '
      'change.</p>')
    A('<div class=suite>')

    def card(title, blurb, counts_map, cov, detail=None, note=None):
        A('<div class="card wfcard">')
        A('<div class=wfhead>%s</div>' % e(title))
        A('<div class=wfblurb>%s</div>' % blurb)
        if counts_map:
            A('<div class=wfstates>')
            for st in ANSWERS:
                n = counts_map.get(st, 0)
                if not n and st in ("CRIT", "UNKNOWN"):
                    continue
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
               "evidence</strong> — no backup age, no plugin or theme count. "
               "They score WARN for that reason alone, and this is the coverage "
               "number to watch.%s"
               % (nh, ("<br>Plus " + ", ".join(terminal) + ".") if terminal else "")))

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
              "observations, not legal conclusions.")

    # EMAIL / DNS -----------------------------------------------------------
    # No per-site status: this answers a question about a DOMAIN. It still gets
    # a card, because leaving a live workflow off the strip reads as "we do not
    # do that" -- and it shows its three coverage fractions where the other
    # cards show states, so the card is comparable rather than half empty.
    email_causes = [g for g in m["standing"]
                    if g["axis"] == "RISK"
                    and ("DMARC" in g["cause"] or "SPF" in g["cause"]
                         or "aligned" in g["cause"])]
    A('<div class="card wfcard">')
    A('<div class=wfhead>Email DNS</div>')
    A('<div class=wfblurb>Can this domain send mail that authenticates.</div>')
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
    A('<div class=wfnote>Scored per DOMAIN, not per site, so it has no column '
      'in the fleet table below and no status of its own. <strong>%d open '
      'cause(s)</strong>, listed under Still true.</div>' % len(email_causes))
    A('</div>')

    A('</div>')

    # --- fleet health -----------------------------------------------------
    counts, excl = h["counts"], h["excluded"]
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
        A('<p class=sub style="margin:10px 0 0"><strong>%d site(s) have been '
          'looked at but have NO health evidence</strong> — no backup age, no '
          'plugin or theme count. They score WARN rather than OK for that '
          'reason alone. This is the coverage number to watch; it is not the '
          'same question as UNKNOWN, which asks whether any scan reached a '
          'site at all.</p>' % len(no_health))
        A('<p class=quiet style="margin:4px 0 0">%s</p>'
          % ", ".join("<code>%s</code>" % e(x["site_id"])
                      for x in sorted(no_health, key=lambda r: r["site_id"])[:40]))

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
        A('<p class=sub style="margin:-4px 0 10px">%d site(s) with no audit '
          'record and no production ruling. Nobody has decided whether these '
          'matter, so they are counted as production until someone does. On '
          'this fleet that set has included the two worst-maintained sites, so '
          'it is worth clearing once.</p>' % len(h["unreviewed"]))
        A("<div class=card><table><tr><th>Site</th><th>State</th><th>Plan</th>"
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
                 e(reasons or "In the Pantheon account, absent from the workbook.")))
        A("</table></div>")

    # --- what changed -----------------------------------------------------
    A("<h2>What changed</h2><div class=card>")
    if not m["changes"]:
        A('<p class=big-quiet>Nothing, in either source.</p>')
    else:
        A("<table><tr><th>Class</th><th>Site</th><th>Fact</th><th>Before</th>"
          "<th>After</th><th>Source</th></tr>")
        for c in m["changes"]:
            A("<tr><td>%s</td><td><code>%s</code></td><td>%s</td><td class=num>%s</td>"
              "<td class=num>%s</td><td class=quiet>%s</td></tr>"
              % (chip(c["class"], CLASS_TONE.get(c["class"], "info")), e(c["site"]),
                 e(c["fact"]), e(c["before"]), e(c["after"]), e(c.get("source"))))
        A("</table>")
    A("</div>")

    # --- coverage ---------------------------------------------------------
    if m["coverage_changes"]:
        A("<h2>What this tool can now see</h2>")
        A('<p class=sub style="margin:-4px 0 10px">Facts that went from unknown '
          'to known, or back. One line per fact rather than one row per site: '
          'the first full-mode run gave 48 sites six new facts each, which is '
          'one event, not 288 of them.</p>')
        A("<div class=card><table><tr><th>Fact</th><th>Became visible</th>"
          "<th>Went dark</th><th>Sites</th></tr>")
        for g in m["coverage_changes"]:
            A("<tr><td><code>%s</code></td><td class=num>%s</td>"
              "<td class=num>%s</td><td><details><summary>%d site(s)</summary>"
              '<div class=quiet style="margin-top:6px">%s</div></details></td></tr>'
              % (e(g["fact"]), e(g["gained"]) if g["gained"] else "—",
                 e(g["lost"]) if g["lost"] else "—",
                 len(g["sites"]), e(", ".join(g["sites"]))))
        A("</table></div>")

    # --- still true, grouped by cause ------------------------------------
    A("<h2>Still true</h2>")
    A('<p class=sub style="margin:-4px 0 10px">Grouped by cause. One unmerged '
      'upstream commit across 38 sites is one decision, not 38 findings.</p>')
    A("<div class=card>")
    if not m["standing"]:
        A('<p class=big-quiet>No standing findings.</p>')
    else:
        A("<table><tr><th>Axis</th><th>Cause</th><th>Sites</th><th>What it means</th></tr>")
        for g in m["standing"]:
            sites, detail = g["sites"], g.get("detail") or {}
            listing = ", ".join(
                ("%s (%s)" % (s, detail[s])) if s in detail else s for s in sites)
            A("<tr><td>%s</td><td><strong>%s</strong></td><td class=num>%d</td>"
              "<td>%s<details><summary>affected sites</summary>"
              '<div class=quiet style="margin-top:6px">%s</div></details></td></tr>'
              % (chip(g["axis"], AXIS_TONE.get(g["axis"], "info")), e(g["cause"]),
                 len(sites), e(g["action"]), e(listing)))
        A("</table>")
    A("</div>")

    # --- coverage ---------------------------------------------------------
    A("<h2>How much of this is actually known</h2>")
    A('<p class=sub style="margin:-4px 0 10px">A green row is only worth as much '
      'as the coverage behind it. Unknown is shown as unknown, never as a pass.</p>')
    A("<div class=card>")
    for label, (known, total) in m["coverage"]:
        pct = (100.0 * known / total) if total else 0
        tone = "good" if pct >= 99 else ("info" if pct >= 50 else "bad")
        A('<div class="cov %s"><div style="color:var(--ink)">%s</div>'
          '<div class=n>%d of %d</div>'
          '<div class="m meter"><i style="width:%.1f%%"></i></div></div>'
          % (tone, e(label), known, total, pct))
    A("</div>")

    # --- reconciliation ---------------------------------------------------
    if m["unreconciled"]:
        A("<h2>Sites that do not reconcile</h2>")
        A('<p class=sub style="margin:-4px 0 10px">Present in one source and absent '
          'from the other. This is the highest-signal finding on the page: until it '
          'is explained, nothing else about these sites can be trusted.</p>')
        A("<div class=card><table><tr><th>Site</th><th>Host</th><th>Why</th></tr>")
        for s in m["unreconciled"]:
            A("<tr><td><code>%s</code></td><td>%s</td><td>%s</td></tr>"
              % (e(s["site_id"]), e(s.get("host")), e(s.get("reconciliation"))))
        A("</table></div>")

    # --- the fleet --------------------------------------------------------
    A("<h2>Every site</h2>")
    A('<p class=sub style="margin:-4px 0 10px"><strong>Health and Consent are '
      'independent</strong> — a site can be well maintained and still leak '
      'trackers, and the two filters combine, so "OK health, WARN consent" is a '
      'query you can run. A consent cell reading UNKNOWN is a site that refused '
      'the scanner, not a clean one. '
      'Blank cells are not tidy, they are '
      'the point: <strong>not checked</strong> means no scan has looked, and '
      '<em>per host</em> means the hosting control plane reported it rather '
      'than a scan reading it off the site, and '
      '<em>claimed</em> means the value comes from the manual workbook and has '
      'never been verified. WordPress core, plugin and theme status needs the '
      'SSH-based full scan, which is not wired up yet.</p>')
    A('<div class=filters>'
      '<input id=q placeholder="Filter by site name" autocomplete=off>'
      '<select id=host><option value="">All hosts</option></select>'
      '<select id=state><option value="">All health states</option></select>'
      '<select id=consent><option value="">All consent states</option></select></div>')
    A('<div class=card style="overflow-x:auto"><table id=fleet>'
      "<tr><th>Site</th><th>Host</th><th>Health</th><th>Consent</th><th>PHP</th>"
      "<th>Newest backup</th><th>Upstream</th>"
      "<th>WP version</th><th>WP core</th><th>Plugins</th><th>Themes</th>"
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

    # Three tiers of evidence, strongest first, and the cell says which tier it
    # is showing. Added 2026-08-19 with the Nexcess source, because rendering
    # the page with control-plane facts in the ledger showed 21 sites whose PHP
    # and WordPress versions had just been MEASURED still displaying the
    # workbook's unverified claim -- the measurement was in the ledger, scoring
    # correctly, and invisible on the page. Same family as every other entry in
    # CLAUDE.md's table, pointed the other way: an absence standing in for a
    # value this time.
    #
    #   read off the site by WP-CLI     plain text, no qualifier
    #   reported by the hosting API     "per host", muted qualifier
    #   typed into the audit workbook   "claimed", muted, whole cell quiet
    #   none of the above               "not checked"
    def observed(v, claim=None, plane=None):
        """An observed value, or an explicit gap. Neither a control-plane
        reading nor a workbook claim ever fills the gap silently."""
        if v not in (None, L.UNKNOWN):
            return e(v)
        if plane not in (None, L.UNKNOWN, ""):
            return ('<span title="Reported by the hosting control plane, not '
                    'read off the site itself. Stronger than the workbook, '
                    'weaker than a WP-CLI reading.">%s <em class=quiet>per '
                    'host</em></span>' % e(plane))
        if claim:
            return ('<span class=quiet title="From the manual workbook. '
                    'Not verified by any scan.">%s <em>claimed</em></span>' % e(claim))
        return '<span class=quiet>not checked</span>'

    def wp_version_cell(v, claim, plane=None):
        """Observed WordPress version against the workbook's claim.

        This is the comparison the project exists to make. The workbook asserts
        7.0.2 fleet-wide and, until 2026-08-18, nothing had ever read the actual
        version off a single site. One month after wp2shell - an RCE whose only
        fix was that upgrade - a site not on 7.0.2 is the most important thing
        this page can show, so a disagreement is called out rather than left for
        a reader to spot by comparing two columns.
        """
        if v in (None, L.UNKNOWN) and plane not in (None, L.UNKNOWN, ""):
            # The control plane answered where WP-CLI has not run. This is the
            # only evidence that exists for the 21 Nexcess sites, and it is the
            # evidence that answers the wp2shell question for them, so it is
            # shown -- qualified, and still compared against the workbook.
            cell = ('%s <em class=quiet title="Reported by the hosting control '
                    'plane, not read off the site itself.">per host</em>'
                    % e(plane))
            if claim and str(plane) != str(claim):
                cell += " " + chip("workbook says %s" % claim, "bad")
            return cell
        if v in (None, L.UNKNOWN):
            if claim:
                return ('<span class=quiet title="From the manual workbook. '
                        'Not verified by any scan.">%s <em>claimed</em></span>'
                        % e(claim))
            return '<span class=quiet>not checked</span>'
        if claim and str(v) != str(claim):
            # chip(), not a bare span: there is no chip-bad class, and the
            # palette is only legal in light mode because every chip carries a
            # visible text label. "workbook says X" is that label.
            return ('%s <span title="The manual workbook records %s for this '
                    'site. The scan read %s off the site itself.">%s</span>'
                    % (e(v), e(claim), e(v),
                       chip("workbook says %s" % claim, "bad")))
        return e(v)

    def consent_cell(s):
        """The consent axis for one site, with the vendor when there is one.

        UNKNOWN here means the sweep was refused or could not load the page.
        It is rendered as UNKNOWN and captioned, never left blank: a blank cell
        in a consent column reads as "nothing to fix", which is the exact bug
        the sweep shipped with -- 23 HTTP 403 block pages scored as clean.
        """
        ax = (s.get("severity") or {}).get("axes", {}).get("consent") or {}
        st = ax.get("status")
        if not st:
            return '<span class=quiet>—</span>'
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
            cell += '<div class=cellnote>%s</div>' % " · ".join(bits)
        return cell

    for s in m["sites"]:
        st = s.get("status")
        state = chip(st, STATE_TONE.get(st, "muted")) if st else '<span class=quiet>—</span>'
        cst = ((s.get("severity") or {}).get("axes", {})
               .get("consent") or {}).get("status") or ""
        claim = s.get("claimed") or {}
        A('<tr data-site="%s" data-host="%s" data-state="%s" data-consent="%s">'
          "<td><code>%s</code></td><td class=quiet>%s</td><td>%s</td><td>%s</td>"
          "<td class=num>%s</td><td>%s</td><td class=num>%s</td>"
          "<td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
          "<td>%s</td><td class=quiet>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
          % (e(s["site_id"].lower()), e(s.get("host") or ""), e(st or ""), e(cst),
             e(s["site_id"]), e(s.get("host") or "—"), state, consent_cell(s),
             observed(s.get("php_version"), claim.get("php_version"),
                      s.get("nexcess_php_version")),
             backup(s.get("db_backup_age_days")),
             e(s.get("upstream_pending", "—")),
             wp_version_cell(s.get("wp_version"), claim.get("wp_version"),
                             s.get("nexcess_app_version")),
             # No workbook claim is passed here on purpose. The workbook
             # records a VERSION; this column answers whether an update is
             # PENDING. Showing "7.0.2 claimed" in an update-pending column
             # answered a question nobody asked, in the one place a reader
             # most needs a straight answer.
             observed(s.get("wp_core_update")),
             observed(s.get("plugin_updates"), claim.get("plugins_utd")),
             observed(s.get("theme_updates"), claim.get("themes_utd")),
             yn(s.get("spf_present")), e(s.get("dkim_selector") or "—"),
             yn(s.get("dmarc_at_sending_present")), yn(s.get("dmarc_at_from_present")),
             yn(s.get("relaxed_aligned"))))
    A("</table></div>")

    A('<p class=foot>Generated %s from the ledger at <code>history/</code>. '
      "Read-only: this page reports, it never changes a site. Trend charts appear "
      "once the ledger holds enough runs to justify one; with %d run(s) a line "
      "would be points pretending to be a trend.</p>"
      % (e(m["generated"]), len(m["runs"])))
    A("</div>")

    A("""<script>
(function(){
 var rows=[].slice.call(document.querySelectorAll('#fleet tr[data-site]'));
 function opts(sel,vals){vals.filter(Boolean).sort().forEach(function(v){
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
     r.style.display=(!q||r.dataset.site.indexOf(q)>-1)&&(!h||r.dataset.host===h)
       &&(!s||r.dataset.state===s)&&(!c||r.dataset.consent===c)?'':'none';});
 }
 ['q','host','state','consent'].forEach(function(id){
   var el=document.getElementById(id);
   el.addEventListener('input',apply);el.addEventListener('change',apply);});
})();
</script></html>""")
    return "".join(o)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", default="./history")
    ap.add_argument("--inventory", default="./data/fleet-inventory.json")
    ap.add_argument("--out", default="./fleet.html")
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
