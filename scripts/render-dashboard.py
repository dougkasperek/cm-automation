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
    "SKIP": "muted", "FROZEN": "muted",
}
AXIS_TONE = {"RISK": "bad", "COVERAGE": "info", "PLANNING": "info", "DRIFT": "muted"}
CLASS_TONE = {"INVENTORY": "bad", "TRANSITION": "info", "ONSET": "bad",
              "RESOLVED": "good", "DRIFT": "muted", "RULE_CHANGE": "info"}


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
        prev, curr = L.previous_run_of_same_source(rs)
        latest[source] = curr
        rows = L.rows_for(obs, curr["run_id"])
        standing.extend(L.standing(rows, today))
        if prev is not None:
            for c in L.diff_runs(L.rows_for(obs, prev["run_id"]), rows, today):
                c["source"] = source
                c["against"] = prev["run_id"]
                changes.append(c)

    order = {c: i for i, c in enumerate(L.CLASS_ORDER + ["RULE_CHANGE"])}
    changes.sort(key=lambda c: (order.get(c["class"], 99), c["site"], c["fact"]))
    axis_order = {"RISK": 0, "COVERAGE": 1, "PLANNING": 2, "DRIFT": 3}
    standing.sort(key=lambda g: (axis_order.get(g["axis"], 9), -len(g["sites"])))

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
        m["in_inventory"] = True
    for m in merged.values():
        m.setdefault("in_inventory", False)
        m.setdefault("host", None)

    sites = sorted(merged.values(), key=lambda s: s["site_id"])

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

    unreconciled = [s for s in sites
                    if s.get("in_workbook") is False or s.get("reconciliation")]

    return {
        "runs": runs, "latest": latest, "changes": changes, "standing": standing,
        "sites": sites, "coverage": coverage, "inventory_count": len(inv),
        "unreconciled": unreconciled,
        "generated": today.isoformat(),
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
    pushable = [c for c in m["changes"] if c["class"] != "DRIFT"]
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
    A('<p class=sub style="margin:-4px 0 10px">Blank cells are not tidy, they are '
      'the point: <strong>not checked</strong> means no scan has looked, and '
      '<em>claimed</em> means the value comes from the manual workbook and has '
      'never been verified. WordPress core, plugin and theme status needs the '
      'SSH-based full scan, which is not wired up yet.</p>')
    A('<div class=filters>'
      '<input id=q placeholder="Filter by site name" autocomplete=off>'
      '<select id=host><option value="">All hosts</option></select>'
      '<select id=state><option value="">All states</option></select></div>')
    A('<div class=card style="overflow-x:auto"><table id=fleet>'
      "<tr><th>Site</th><th>Host</th><th>State</th><th>PHP</th>"
      "<th>Newest backup</th><th>Upstream</th>"
      "<th>WP core</th><th>Plugins</th><th>Themes</th>"
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

    def observed(v, claim=None):
        """An observed value, or an explicit gap. A workbook claim never fills
        the gap silently; it is shown as a claim, in muted ink."""
        if v not in (None, L.UNKNOWN):
            return e(v)
        if claim:
            return ('<span class=quiet title="From the manual workbook. '
                    'Not verified by any scan.">%s <em>claimed</em></span>' % e(claim))
        return '<span class=quiet>not checked</span>'

    for s in m["sites"]:
        st = s.get("derived_status")
        state = chip(st, STATE_TONE.get(st, "muted")) if st else '<span class=quiet>—</span>'
        claim = s.get("claimed") or {}
        A('<tr data-site="%s" data-host="%s" data-state="%s">'
          "<td><code>%s</code></td><td class=quiet>%s</td><td>%s</td>"
          "<td class=num>%s</td><td>%s</td><td class=num>%s</td>"
          "<td>%s</td><td>%s</td><td>%s</td>"
          "<td>%s</td><td class=quiet>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
          % (e(s["site_id"].lower()), e(s.get("host") or ""), e(st or ""),
             e(s["site_id"]), e(s.get("host") or "—"), state,
             observed(s.get("php_version"), claim.get("php_version")),
             backup(s.get("db_backup_age_days")),
             e(s.get("upstream_pending", "—")),
             observed(s.get("wp_core_update"), claim.get("wp_version")),
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
 function apply(){
   var q=document.getElementById('q').value.toLowerCase(),
       h=document.getElementById('host').value,
       s=document.getElementById('state').value;
   rows.forEach(function(r){
     r.style.display=(!q||r.dataset.site.indexOf(q)>-1)&&(!h||r.dataset.host===h)
       &&(!s||r.dataset.state===s)?'':'none';});
 }
 ['q','host','state'].forEach(function(id){
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
    ap.add_argument("--today", help="override today (YYYY-MM-DD) for deterministic output")
    a = ap.parse_args()
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    m = build_model(a.history, a.inventory, today)
    with open(a.out, "w") as fh:
        fh.write(render(m))
    print("%d sites, %d change(s), %d standing finding(s) -> %s"
          % (len(m["sites"]), len(m["changes"]), len(m["standing"]), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
