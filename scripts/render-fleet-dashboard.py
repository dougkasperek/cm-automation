#!/usr/bin/env python3
"""
render-fleet-dashboard.py
CleverMethod - turn a fleet scan JSON into a self-contained HTML dashboard.

    ./scripts/render-fleet-dashboard.py <scan.json> -o dashboard.html [--live-url /api/fleet-scan]

DESIGN RULE (same as everything else in this repo): this script knows nothing
about GitHub Actions, Azure DevOps, or Cloudflare. It reads a JSON file and
writes an HTML file. Where that HTML gets served is the wrapper's problem.

It handles BOTH scan schemas and detects which one it was given:
  * wpstatistics-fleet-scan.sh  -> site / framework / frozen / has_analytics_plugin
                                   / matched_plugins / notes
  * pantheon-fleet-healthcheck.sh -> site / status (CRIT|WARN|OK|FROZEN|SKIP|ERROR)
                                   / php_version / db_backup_age_days / ...

--live-url makes the page try to fetch fresher JSON from that URL on load and
re-render if it succeeds, falling back to the data embedded at build time. That
is what makes the hosted version live without making the file useless offline.

COLOR NOTE, so nobody "improves" this later:
The three chromatic state colors are the first three slots of a categorical
palette validated with the dataviz validator against THIS page's surfaces:
  light #faf7f2 -> CVD dE 9.2, normal-vision dE 27.6, all checks pass
  dark  #1a1a19 -> CVD dE 9.4, normal-vision dE 26.5, all checks pass
The deck's own severity colors (#1a7f37 green / #9a6700 amber) were tried first
and FAILED: protan dE 3.8, i.e. a red-green colorblind reader cannot separate
them. Do not swap these back for brand greens without re-running the validator.
The fourth state ("none") is a deliberate neutral gray, not a categorical slot.
It reads gray on purpose, because it means "nothing installed", and it is always
direct-labeled so hue never carries it alone.
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# State model. Order here is the order segments appear in the composition bar,
# chosen so no two adjacent segments are a failing color pair.
# --------------------------------------------------------------------------
PLUGIN_STATES = [
    ("ready",    "Drop-in ready",     "aqua",    "Same 9-plugin WP Statistics bundle as Galbani. The existing pull script should work with a --site swap."),
    ("partial",  "Needs schema work", "orange",  "Has an analytics plugin, but not the Galbani bundle. Needs a schema check or new pull logic."),
    ("unknown",  "Not determined",    "blue",    "The scan could not establish an answer for this site. Not the same as 'no'."),
    ("none",     "No analytics plugin", "neutral", "Confirmed: no matching analytics plugin installed."),
]

HEALTH_STATES = [
    ("CRIT",   "Critical",       "orange",  "Missing or stale DB backup, or a WordPress core update is pending."),
    ("WARN",   "Warning",        "blue",    "Plugin, theme, or pending platform updates."),
    ("OK",     "Healthy",        "aqua",    "All checks passed."),
    ("ERROR",  "Not determined", "blue",    "Checks could not complete. Status genuinely unknown."),
    ("SKIP",   "Skipped",        "neutral", "Environment confirmed absent or never initialized."),
    ("FROZEN", "Frozen",         "neutral", "Dormant Pantheon site, not deep-scanned by design."),
]

GALBANI_BUNDLE_MARKER = "wp-statistics-data-plus"

# Sites where a SPECIFIC known bug produced a SPECIFIC wrong answer. Surfacing
# this beats quietly shipping a number a developer can disprove in ten seconds.
#
# Each entry is (symptom, explanation). The flag is raised ONLY when the row
# actually exhibits the symptom.
#
# WHY THE SYMPTOM CHECK EXISTS: the first version keyed on site name alone. The
# 2026-08-16 health scan then ran post-fix, galbanicheese came back correctly as
# WARN with a fresh backup, and the dashboard still stamped a red
# "this result is WRONG" banner on a perfectly good row. Flagging a correct row
# as broken is worse than not flagging at all, because it teaches people to
# ignore the banner. A known-bad marker must describe a symptom, not a site.
KNOWN_BAD = {
    "galbanicheese": (
        "does not exist",
        "This result is WRONG and we know why. galbanicheese has a working live "
        "environment that the Galbani reporting pipeline uses every week. The scan "
        "hit a timeout, got an empty response, and jq treats empty input as valid, "
        "so 'check failed' was misread as 'environment absent'. Fixed in the script "
        "on 2026-08-09; this scan predates the fix and was never re-run."
    )
}


def known_bad_note(site, notes):
    """Return the explanation only if this row shows the known symptom."""
    entry = KNOWN_BAD.get(site)
    if not entry:
        return None
    symptom, explanation = entry
    return explanation if symptom.lower() in (notes or "").lower() else None


# The scan writes one long boilerplate sentence per failure mode, which is right
# for a text report and wrong for a table: fourteen identical paragraphs bury the
# signal. Shorten for display, keep the full text on hover so nothing is lost.
NOTE_SHORTHAND = [
    ("non-json",         "SSH or output failure. Rerun this site by hand."),
    ("returned nothing", "SSH or output failure. Rerun this site by hand."),
    ("not initialized",  "live env exists but was never initialized. Skipped before SSH."),
    ("does not exist",   "Scan reported live env absent."),
    ("frozen",           "Frozen site."),
]


def shorten_note(note):
    low = (note or "").lower()
    for needle, short in NOTE_SHORTHAND:
        if needle in low:
            return short
    return note or ""


def classify_plugin_row(row):
    site = row.get("site", "")
    notes = (row.get("notes") or "").lower()
    matched = row.get("matched_plugins") or []

    if known_bad_note(site, notes):
        return "unknown", "known-bad result, see banner"
    if row.get("frozen"):
        return "unknown", "frozen site, not scanned"
    if "non-json" in notes or "returned nothing" in notes or "failed" in notes:
        return "unknown", "SSH or output failure, status unknown"
    if "not initialized" in notes or "does not exist" in notes:
        return "unknown", "environment not initialized"
    if matched:
        if any(GALBANI_BUNDLE_MARKER in p for p in matched):
            return "ready", ""
        return "partial", ""
    return "none", ""


def build_plugin_model(rows):
    states = {k: [] for k, _, _, _ in PLUGIN_STATES}
    table = []
    for row in rows:
        key, reason = classify_plugin_row(row)
        site = row.get("site", "")
        matched = row.get("matched_plugins") or []
        rec = {
            "site": site,
            "state": key,
            "framework": row.get("framework") or "unknown",
            "detail": ", ".join(matched) if matched else "-",
            "count": len(matched),
            "notes": shorten_note(row.get("notes") or reason or ""),
            "notes_full": row.get("notes") or reason or "",
            "flagged": bool(known_bad_note(site, row.get("notes") or reason or "")),
        }
        states[key].append(site)
        table.append(rec)
    return states, table, PLUGIN_STATES


def build_health_model(rows):
    states = {k: [] for k, _, _, _ in HEALTH_STATES}
    table = []
    for row in rows:
        key = row.get("status") or "ERROR"
        if key not in states:
            states[key] = []
        site = row.get("site", "")
        bits = []
        if row.get("php_version"):
            bits.append("PHP " + str(row["php_version"]))
        age = row.get("db_backup_age_days")
        if age is not None:
            bits.append("backup " + ("none" if age == 9999 else f"{age}d"))
        if row.get("plugin_updates"):
            bits.append(f"{row['plugin_updates']} plugin upd")
        if row.get("theme_updates"):
            bits.append(f"{row['theme_updates']} theme upd")
        rec = {
            "site": site,
            "state": key,
            "framework": row.get("framework") or "unknown",
            "detail": " · ".join(bits) if bits else "-",
            "count": 0,
            "notes": shorten_note(row.get("notes") or ""),
            "notes_full": row.get("notes") or "",
            "flagged": bool(known_bad_note(site, row.get("notes") or "")),
        }
        states[key].append(site)
        table.append(rec)
    return states, table, HEALTH_STATES


def detect(rows):
    if not rows:
        raise SystemExit("ERROR: scan JSON is empty.")
    keys = set(rows[0].keys())
    if "has_analytics_plugin" in keys or "matched_plugins" in keys:
        return "plugin"
    if "status" in keys:
        return "health"
    raise SystemExit(
        "ERROR: unrecognised scan schema. Expected either 'matched_plugins' "
        "(wpstatistics-fleet-scan) or 'status' (pantheon-fleet-healthcheck). "
        f"Got: {sorted(keys)}"
    )


def stamp_from_filename(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})[_-](\d{2})(\d{2})", os.path.basename(path))
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}"
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except OSError:
        return "unknown"


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__ | clevermethod</title>
<style>
/* Brand tokens carried over from the deck companion pages so this reads as
   part of the same system. Data-state colors are NOT brand colors: see the
   COLOR NOTE in render-fleet-dashboard.py before changing any of them. */
.viz-root{
  color-scheme: light;
  --navy:#17212b; --ink:#2a3540; --coral-dark:#8a3d2e; --teal-dark:#1d5351;
  --surface:#faf7f2; --plane:#f5f0e8; --card:#ffffff;
  --text-primary:#17212b; --text-secondary:#46525d; --muted:#68737e;
  --line:#ddd7ce; --grid:#ece5da;
  --st-aqua:#1baf7a; --st-orange:#eb6834; --st-blue:#2a78d6; --st-neutral:#8d9199;
  --ring:rgba(11,11,11,0.10);
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])) .viz-root{
    color-scheme: dark;
    --surface:#1a1a19; --plane:#0d0d0d; --card:#232320;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#a09e96;
    --line:#383835; --grid:#2c2c2a;
    --st-aqua:#199e70; --st-orange:#d95926; --st-blue:#3987e5; --st-neutral:#898781;
    --ring:rgba(255,255,255,0.12);
  }
}
:root[data-theme="dark"] .viz-root{
  color-scheme: dark;
  --surface:#1a1a19; --plane:#0d0d0d; --card:#232320;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#a09e96;
  --line:#383835; --grid:#2c2c2a;
  --st-aqua:#199e70; --st-orange:#d95926; --st-blue:#3987e5; --st-neutral:#898781;
  --ring:rgba(255,255,255,0.12);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--plane)}
.viz-root{
  background:var(--plane); color:var(--text-primary); min-height:100vh;
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55;
}
.wrap{max-width:1120px;margin:0 auto;padding:34px 24px 72px}
header.top{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;justify-content:space-between;margin-bottom:6px}
.eyebrow{font:700 11px/1 Consolas,ui-monospace,monospace;letter-spacing:.14em;color:var(--coral-dark);text-transform:uppercase;margin:0 0 10px}
h1{font-family:Georgia,'Times New Roman',serif;font-size:31px;line-height:1.15;margin:0 0 8px;color:var(--text-primary)}
.sub{color:var(--text-secondary);margin:0;font-size:14.5px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button,select,input[type=search]{
  font:inherit;font-size:13px;color:var(--text-primary);background:var(--card);
  border:1px solid var(--line);border-radius:9px;padding:7px 11px;cursor:pointer;
}
input[type=search]{cursor:text;min-width:190px}
button:hover,select:hover{border-color:var(--muted)}
button[aria-pressed=true]{background:var(--navy);color:#fff;border-color:var(--navy)}

.banner{
  background:var(--card);border:1px solid var(--line);border-left:4px solid var(--st-orange);
  border-radius:12px;padding:14px 18px;margin:22px 0 6px;font-size:13.5px;color:var(--text-secondary)
}
.banner b{color:var(--text-primary)}
.freshness{font:12px/1.5 Consolas,ui-monospace,monospace;color:var(--muted);margin:14px 0 0}
.freshness .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--st-neutral);margin-right:6px;vertical-align:baseline}
.freshness.live .dot{background:var(--st-aqua)}
.freshness.scanning{color:var(--text-primary);font-weight:600}
.freshness.scanning .dot{background:var(--st-orange);animation:pulse 1.1s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(1.35)}}
@media (prefers-reduced-motion:reduce){.freshness.scanning .dot{animation:none}}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:26px 0 6px}
.tile{background:var(--card);border:1px solid var(--ring);border-radius:14px;padding:16px 18px}
.tile .v{font-size:34px;line-height:1.05;font-weight:650;letter-spacing:-.01em}
.tile .k{font-size:12.5px;color:var(--text-secondary);margin-top:5px;display:flex;align-items:center;gap:7px}
.swatch{width:11px;height:11px;border-radius:3px;flex:0 0 auto;box-shadow:0 0 0 1px var(--ring)}
.tile .h{font-size:11.5px;color:var(--muted);margin-top:7px;line-height:1.45}

section{margin-top:34px}
h2{font-family:Georgia,serif;font-size:19px;margin:0 0 4px;color:var(--text-primary)}
.cap{font-size:13px;color:var(--text-secondary);margin:0 0 16px}

/* Composition bar. 2px surface gaps between segments per the mark spec,
   4px rounded ends on the outermost segments only. */
.bar{display:flex;width:100%;height:46px;gap:2px;margin:6px 0 12px}
.seg{position:relative;min-width:3px;transition:filter .12s}
.seg:first-child{border-radius:5px 0 0 5px}
.seg:last-child{border-radius:0 5px 5px 0}
.seg:hover{filter:brightness(1.08)}
.seg:focus-visible{outline:2px solid var(--text-primary);outline-offset:2px}
.seg .lab{
  position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font:650 13px/1 Inter,sans-serif;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.35);pointer-events:none
}
.legend{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:12.5px;color:var(--text-secondary);margin-top:12px}
.legend .li{display:flex;align-items:center;gap:7px}

#tip{
  position:fixed;z-index:50;pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--navy);color:#fff;border-radius:9px;padding:9px 12px;font-size:12.5px;
  max-width:320px;line-height:1.45;box-shadow:0 6px 20px rgba(0,0,0,.22)
}
#tip b{display:block;margin-bottom:3px}

table{width:100%;border-collapse:separate;border-spacing:0;font-size:13.5px;
  background:var(--card);border-radius:12px;overflow:hidden;box-shadow:0 0 0 1px var(--ring)}
th{background:var(--navy);color:#fff;text-align:left;padding:9px 12px;font-size:11.5px;
  letter-spacing:.04em;text-transform:uppercase;cursor:pointer;white-space:nowrap;user-select:none}
th:hover{background:#22303d}
th[aria-sort]:after{content:'';margin-left:6px}
th[aria-sort=ascending]:after{content:'\25B2';font-size:9px}
th[aria-sort=descending]:after{content:'\25BC';font-size:9px}
td{padding:9px 12px;border-top:1px solid var(--grid);color:var(--text-secondary);vertical-align:top}
td.site{font-weight:650;color:var(--text-primary);white-space:nowrap;font-variant-numeric:tabular-nums}
td.detail{font:12.5px/1.5 Consolas,ui-monospace,monospace;word-break:break-word}
tr.flag td{background:color-mix(in srgb, var(--st-orange) 9%, var(--card))}
.pill{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-size:12.5px;font-weight:600;color:var(--text-primary)}
.empty{padding:26px;text-align:center;color:var(--muted);font-size:13.5px}
.count{font-size:12.5px;color:var(--muted);margin:10px 0 0}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
@media(max-width:720px){
  h1{font-size:25px} .wrap{padding:24px 16px 56px}
  td.detail{max-width:none} .bar{height:38px}
}
@media print{ .controls{display:none} body{background:#fff} }
</style>
</head>
<body>
<div class="viz-root">
<div class="wrap">

  <header class="top">
    <div>
      <p class="eyebrow">clevermethod &middot; Pantheon fleet</p>
      <h1>__H1__</h1>
      <p class="sub">__SUB__</p>
    </div>
    <div class="controls">
      <input type="search" id="q" placeholder="Filter sites..." aria-label="Filter sites by name"/>
      <select id="stateFilter" aria-label="Filter by state"><option value="">All states</option></select>
      <button id="themeBtn" type="button" aria-pressed="false">Dark</button>
    </div>
  </header>

  <p class="freshness" id="freshness"><span class="dot"></span><span id="freshText">Scan of __STAMP__ &middot; embedded snapshot</span></p>

  __BANNER__

  <section>
    <h2>Fleet composition</h2>
    <p class="cap">__NSITES__ sites, one segment per state. Segment width is site count.</p>
    <div class="bar" id="bar" role="img" aria-label="Fleet composition by state"></div>
    <div class="legend" id="legend"></div>
  </section>

  <section>
    <div class="tiles" id="tiles"></div>
  </section>

  <section>
    <h2>Every site</h2>
    <p class="cap">Click a column heading to sort. This table is the accessible equivalent of the bar above, and the thing to hand someone who wants the raw answer.</p>
    <table>
      <thead><tr>
        <th data-k="site">Site</th>
        <th data-k="state">State</th>
        <th data-k="framework">Framework</th>
        <th data-k="detail">__DETAILCOL__</th>
        <th data-k="notes">Notes</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    <p class="count" id="count"></p>
  </section>

  <footer>
    Read-only scan. Nothing was changed on any site. &middot; clevermethod, Inc.
    &middot; Generated by <code>render-fleet-dashboard.py</code> from <code>__SRCNAME__</code>
  </footer>
</div>
</div>
<div id="tip" role="tooltip"></div>

<script>
const STATES = __STATES__;
const COLORVAR = {aqua:'--st-aqua', orange:'--st-orange', blue:'--st-blue', neutral:'--st-neutral'};
let ROWS = __ROWS__;
const LIVE_URL = __LIVEURL__;

const $ = s => document.querySelector(s);
const cssVar = n => getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(n).trim();
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function counts(){
  const c = {};
  STATES.forEach(s => c[s.key] = 0);
  ROWS.forEach(r => { if (c[r.state] === undefined) c[r.state] = 0; c[r.state]++; });
  return c;
}

function renderBar(){
  const c = counts(), total = ROWS.length || 1;
  const bar = $('#bar'), legend = $('#legend');
  bar.innerHTML = ''; legend.innerHTML = '';
  STATES.forEach(s => {
    const n = c[s.key] || 0;
    if (!n) return;
    const pct = n / total * 100;
    const seg = document.createElement('div');
    seg.className = 'seg';
    seg.style.flex = pct + ' 0 0';
    seg.style.background = cssVar(COLORVAR[s.color]);
    seg.tabIndex = 0;
    seg.setAttribute('role', 'button');
    seg.setAttribute('aria-label', s.label + ': ' + n + ' sites. ' + s.help);
    // Direct label only where the segment is wide enough to hold it legibly.
    if (pct >= 9) seg.innerHTML = '<span class="lab">' + n + '</span>';
    const show = e => {
      const t = $('#tip');
      t.innerHTML = '<b>' + esc(s.label) + ' &middot; ' + n + ' sites (' + pct.toFixed(0) + '%)</b>' + esc(s.help);
      t.style.opacity = 1;
      const r = seg.getBoundingClientRect();
      const x = Math.min(Math.max(12, (e.clientX || r.left + r.width / 2) - 140), innerWidth - 332);
      t.style.left = x + 'px';
      t.style.top = (r.bottom + 10) + 'px';
    };
    seg.addEventListener('mousemove', show);
    seg.addEventListener('focus', show);
    seg.addEventListener('mouseleave', () => $('#tip').style.opacity = 0);
    seg.addEventListener('blur', () => $('#tip').style.opacity = 0);
    seg.addEventListener('click', () => { $('#stateFilter').value = s.key; renderTable(); });
    bar.appendChild(seg);

    const li = document.createElement('div');
    li.className = 'li';
    li.innerHTML = '<span class="swatch" style="background:' + cssVar(COLORVAR[s.color]) + '"></span>' +
                   esc(s.label) + ' <strong style="color:var(--text-primary)">' + n + '</strong>';
    legend.appendChild(li);
  });
}

function renderTiles(){
  const c = counts(), t = $('#tiles');
  t.innerHTML = '';
  const total = document.createElement('div');
  total.className = 'tile';
  total.innerHTML = '<div class="v">' + ROWS.length + '</div><div class="k">Sites scanned</div>' +
                    '<div class="h">Every site the machine token can see.</div>';
  t.appendChild(total);
  STATES.forEach(s => {
    const n = c[s.key] || 0;
    if (!n) return;
    const d = document.createElement('div');
    d.className = 'tile';
    d.innerHTML = '<div class="v">' + n + '</div>' +
      '<div class="k"><span class="swatch" style="background:' + cssVar(COLORVAR[s.color]) + '"></span>' + esc(s.label) + '</div>' +
      '<div class="h">' + esc(s.help) + '</div>';
    t.appendChild(d);
  });
}

let sortKey = 'state', sortDir = 1;
function renderTable(){
  const q = $('#q').value.trim().toLowerCase();
  const sf = $('#stateFilter').value;
  const order = {}; STATES.forEach((s, i) => order[s.key] = i);
  let rows = ROWS.filter(r =>
    (!q || r.site.toLowerCase().includes(q) || (r.detail || '').toLowerCase().includes(q)) &&
    (!sf || r.state === sf));
  rows.sort((a, b) => {
    let x, y;
    if (sortKey === 'state') { x = order[a.state] ?? 99; y = order[b.state] ?? 99; }
    else { x = (a[sortKey] || '').toString().toLowerCase(); y = (b[sortKey] || '').toString().toLowerCase(); }
    return x < y ? -sortDir : x > y ? sortDir : (a.site < b.site ? -1 : 1);
  });
  const meta = {}; STATES.forEach(s => meta[s.key] = s);
  const tb = $('#tbody');
  tb.innerHTML = rows.length ? rows.map(r => {
    const m = meta[r.state] || {label: r.state, color: 'neutral'};
    return '<tr' + (r.flagged ? ' class="flag"' : '') + '>' +
      '<td class="site">' + esc(r.site) + (r.flagged ? ' &#9888;' : '') + '</td>' +
      '<td><span class="pill"><span class="swatch" style="background:var(' + COLORVAR[m.color] + ')"></span>' + esc(m.label) + '</span></td>' +
      '<td>' + esc(r.framework) + '</td>' +
      '<td class="detail">' + esc(r.detail) + '</td>' +
      '<td' + (r.notes_full && r.notes_full !== r.notes ? ' title="' + esc(r.notes_full) + '"' : '') + '>' +
        esc(r.notes) + '</td></tr>';
  }).join('') : '<tr><td colspan="5" class="empty">No sites match this filter.</td></tr>';
  $('#count').textContent = 'Showing ' + rows.length + ' of ' + ROWS.length + ' sites.';
  document.querySelectorAll('th').forEach(th => {
    if (th.dataset.k === sortKey) th.setAttribute('aria-sort', sortDir === 1 ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
  });
}

function renderAll(){ renderBar(); renderTiles(); renderTable(); }

// ---- wiring ----
STATES.forEach(s => {
  const o = document.createElement('option');
  o.value = s.key; o.textContent = s.label;
  $('#stateFilter').appendChild(o);
});
$('#q').addEventListener('input', renderTable);
$('#stateFilter').addEventListener('change', renderTable);
document.querySelectorAll('th').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
  if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
  renderTable();
}));
$('#themeBtn').addEventListener('click', () => {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
  $('#themeBtn').textContent = dark ? 'Dark' : 'Light';
  $('#themeBtn').setAttribute('aria-pressed', dark ? 'false' : 'true');
  renderAll();
});
renderAll();

// ---- live refresh ----
// The embedded snapshot always renders first, so the page is never blank and
// never depends on the network. Polling then replaces it and says so. This is
// what makes a running scan visible: the scan scripts rewrite their JSON after
// EVERY site, so the row count climbs while you watch.
let lastSig = '';
let failures = 0;

function applyLive(d){
  const rows = d.rows;
  if (!Array.isArray(rows)) throw new Error('expected {rows:[...]}, got raw scan JSON');
  const sig = rows.length + '|' + (d.stamp || '') + '|' + (d.scanning ? 'run' : 'done');
  if (sig === lastSig) return false;
  lastSig = sig;
  ROWS = rows;

  const f = $('#freshness');
  f.classList.add('live');
  f.classList.toggle('scanning', !!d.scanning);
  const when = new Date().toLocaleTimeString();
  $('#freshText').textContent = d.scanning
    ? 'SCAN RUNNING · ' + rows.length + ' sites so far · updated ' + when
    : 'Live · ' + rows.length + ' sites · scan of ' + (d.stamp || 'unknown') + ' · updated ' + when;
  renderAll();
  return true;
}

function poll(){
  if (!LIVE_URL) return;
  fetch(LIVE_URL, {cache: 'no-store'})
    .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
    .then(d => { failures = 0; applyLive(d); })
    .catch(e => {
      failures++;
      // Say it once, then stop nagging. The embedded snapshot is still on screen
      // and is still correct as of its own timestamp, which is the honest state.
      if (failures === 1) {
        $('#freshText').textContent += ' · live updates unavailable (' + e.message + ')';
      }
    });
}

if (LIVE_URL) { poll(); setInterval(poll, 3000); }
</script>
</body>
</html>
"""


def build_html(table, states, kind, title, sub, detail_col, stamp, src_name, live_url):
    """Fill the template. Kept separate from main() so serve-dashboard.py can
    re-render in process on every file change without shelling out."""
    present = {r["state"] for r in table}
    states = [s for s in states if s[0] in present]

    flagged = [r for r in table if r["flagged"]]
    banner = ""
    if flagged:
        items = "".join(
            f"<br><br><b>{html.escape(r['site'])}</b>: "
            f"{html.escape(known_bad_note(r['site'], r.get('notes_full') or '') or '')}"
            for r in flagged
        )
        banner = (
            '<div class="banner"><b>Known bad data in this scan, shown deliberately.</b> '
            f'{len(flagged)} row{"" if len(flagged)==1 else "s"} below '
            f'{"is" if len(flagged)==1 else "are"} flagged because we already know the scan got it wrong. '
            "It is left in rather than quietly corrected, because a dashboard that hides its own "
            "known errors is worth less than one that names them." + items + "</div>"
        )

    state_js = json.dumps([
        {"key": k, "label": lab, "color": col, "help": helptext}
        for k, lab, col, helptext in states
    ])

    out = TEMPLATE
    for needle, value in [
        ("__TITLE__", html.escape(title)),
        ("__H1__", html.escape(title)),
        ("__SUB__", html.escape(sub)),
        ("__STAMP__", html.escape(stamp)),
        ("__NSITES__", str(len(table))),
        ("__BANNER__", banner),
        ("__DETAILCOL__", html.escape(detail_col)),
        ("__SRCNAME__", html.escape(src_name)),
        ("__STATES__", state_js),
        ("__ROWS__", json.dumps(table)),
        ("__LIVEURL__", json.dumps(live_url or None)),
    ]:
        out = out.replace(needle, value)
    return out


def model_for(rows):
    """Classify rows and return (kind, table, states, title, sub, detail_col)."""
    kind = detect(rows)
    if kind == "plugin":
        _, table, states = build_plugin_model(rows)
        return (kind, table, states, "Analytics Plugin Coverage",
                "Which sites in the Pantheon fleet carry a WP Statistics style analytics "
                "plugin, and which could reuse the Galbani reporting pull as-is.",
                "Matched plugins")
    _, table, states = build_health_model(rows)
    return (kind, table, states, "Fleet Health",
            "WordPress core, plugin and theme drift, PHP version, backup age and "
            "pending platform commits across the Pantheon fleet.",
            "Detail")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_json")
    ap.add_argument("-o", "--out", default="fleet-dashboard.html")
    ap.add_argument("--live-url", default="", help="URL the page polls for fresher data, e.g. /api/fleet-scan")
    ap.add_argument("--emit-data", default="", help="also write the rendered row model as {stamp,rows} JSON, for the hosted live endpoint")
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    with open(args.scan_json, encoding="utf-8") as fh:
        rows = json.load(fh)
    if isinstance(rows, dict):
        rows = rows.get("rows") or list(rows.values())

    kind, table, states, h1, sub, detail_col = model_for(rows)
    if args.title:
        h1 = args.title

    out = build_html(
        table=table, states=states, kind=kind, title=h1, sub=sub,
        detail_col=detail_col, stamp=stamp_from_filename(args.scan_json),
        src_name=os.path.basename(args.scan_json), live_url=args.live_url,
    )

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)

    flagged = [r for r in table if r["flagged"]]
    states = [s for s in states if s[0] in {r["state"] for r in table}]

    if args.emit_data:
        with open(args.emit_data, "w", encoding="utf-8") as fh:
            json.dump({"stamp": stamp_from_filename(args.scan_json),
                       "kind": kind,
                       "rows": table}, fh)
        print(f"Wrote {args.emit_data}  (live data endpoint payload)")

    counts = {}
    for r in table:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print(f"Wrote {args.out}  ({kind} scan, {len(table)} sites)")
    for k, lab, _, _ in states:
        print(f"  {lab:<22} {counts.get(k, 0)}")
    if flagged:
        print(f"  FLAGGED known-bad rows: {', '.join(r['site'] for r in flagged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
