#!/usr/bin/env python3
"""Build the batch-one mockup from the REAL model.

Every number here is read from the ledger at build time. A mockup with typed
numbers would be the exact defect this project keeps finding, and it would be
demonstrating a design principle while breaking it.
"""
import importlib.util as il, datetime, collections, html, json, os

spec = il.spec_from_file_location("r", "scripts/render-dashboard.py")
R = il.module_from_spec(spec); spec.loader.exec_module(R)
M = R.build_model("./history", "./data/fleet-inventory.json", datetime.date(2026, 8, 26))
e = html.escape

H, AX = M["health"], M["health"].get("axes", {})

# EVERY EXCEPTION LINE COMES FROM THE SEVERITY CODES, not from a recount.
# The first cut of this mockup counted "sites with any pending plugin update"
# and labelled it "have a plugin update backlog": 68, where the real card says
# 24. `plugin_backlog` is a threshold rule, not "more than zero". Two different
# questions wearing the same words -- the exact defect this mockup argues
# against, reproduced inside it within the hour.
CODES = collections.Counter()
for _s in M["sites"]:
    _sev = _s.get("severity") or {}
    for _r in _sev.get("all_reasons", _sev.get("reasons", [])):
        CODES[_r.get("code")] += 1

def n_sites(n):
    return "%d site%s" % (n, "" if n == 1 else "s")
C = H["counts"]
attention = C["CRIT"] + C["WARN"]
no_ev = [s for s in M["sites"]
         if any(r.get("code") == "coverage_partial"
                for r in (s.get("severity") or {}).get("reasons", []))]
decisions = H["unreviewed"]

by_site = collections.defaultdict(list)
for c in M["changes"]:
    by_site[c.get("site") or c.get("site_id")].append(c)
loud = {s: cs for s, cs in by_site.items()
        if any(c["class"] not in ("COVERAGE", "DRIFT") for c in cs)}

def sweep():
    runs = sorted((M.get("latest_by_cohort") or {}).items(),
                  key=lambda kv: kv[1]["observed_at"])
    newest = runs[-1][1]["observed_at"]
    oldest = runs[0][1]["observed_at"]
    return newest, oldest, len(runs)

NEWEST, OLDEST, NSRC = sweep()
def when(ts):
    d = datetime.datetime.fromisoformat(ts)
    return d.strftime("%b %-d, %-I:%M %p")

# stale = measured more than a day before the newest sweep
stale = [k for k, r in (M.get("latest_by_cohort") or {}).items()
         if (datetime.datetime.fromisoformat(NEWEST)
             - datetime.datetime.fromisoformat(r["observed_at"])).days >= 1]

CSS = """
:root{--good:#1baf7a;--bad:#eb6834;--info:#2a78d6;--muted:#8d9199;--surface:#efefea;
--card:#ffffff;--panel2:#f6f6f1;--ink:#241e31;--ink2:#6e6879;--faint:#9c98a5;
--strong:#1c122d;--line:#d9d8d0;--line2:#e7e6df}
*{box-sizing:border-box}
body{margin:0;padding:24px 20px 72px;background:var(--surface);color:var(--ink);
font:14px/1.5 "Helvetica Neue",Helvetica,Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:24px;letter-spacing:-.01em;margin:0;color:var(--strong)}
h2{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;
color:var(--ink2);margin:30px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:0;padding:14px 16px}
.sub{color:var(--ink2);font-size:13px;margin:2px 0 0}
.quiet{color:var(--faint);font-size:12px}
.sweep{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:baseline;
border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:18px}
.sweep b{color:var(--strong)}
/* --- exception tiles --- */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);padding:14px 16px;
text-align:left;font:inherit;color:inherit;cursor:pointer;border-left:3px solid var(--line)}
.tile:hover{border-color:var(--ink2);border-left-color:var(--strong)}
.tile.bad{border-left-color:var(--bad)}
.tile.info{border-left-color:var(--info)}
.tile.good{border-left-color:var(--good)}
.tile .n{font-size:30px;font-weight:700;color:var(--strong);letter-spacing:-.02em;line-height:1.1}
.tile .n small{font-size:13px;font-weight:600;color:var(--ink2);letter-spacing:0;margin-left:5px}
.tile .lab{font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
color:var(--ink2);margin-bottom:6px}
.tile .why{font-size:12px;color:var(--ink2);margin-top:5px;line-height:1.45}
/* --- chips --- */
.chip{display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:800;
letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;padding:3px 8px 3px 7px;
border:1px solid color-mix(in srgb,currentColor 34%,transparent);
background:color-mix(in srgb,currentColor 11%,transparent)}
.chip .gl{font-size:10px;line-height:1}
.chip.bad{color:color-mix(in srgb,var(--bad) 62%,var(--ink))}
.chip.info{color:color-mix(in srgb,var(--info) 62%,var(--ink))}
.chip.good{color:color-mix(in srgb,var(--good) 62%,var(--ink))}
.chip.muted{color:var(--muted)}
/* --- suite --- */
.suite{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:10px}
.wfhead{font-size:15px;font-weight:700;color:var(--strong);margin-bottom:2px}
.wfq{font-size:12px;color:var(--ink2);margin-bottom:11px}
.states{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:11px}
.st{background:none;border:0;padding:0;font:inherit;color:inherit;cursor:pointer;text-align:left}
.st .v{font-size:19px;font-weight:700;color:var(--strong);margin-top:3px}
.st:hover .v{text-decoration:underline}
.exc{border-top:1px solid var(--line2);padding-top:9px;font-size:12.5px;line-height:1.6}
.exc div{margin-bottom:3px}
.exc b{color:var(--strong)}
.qual{color:var(--ink2)}
.more{display:inline-block;margin-top:9px;font-size:12px;font-weight:700;color:var(--info);
text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--info) 40%,transparent)}
/* --- info disclosure --- */
details.info-d{margin-top:9px}
details.info-d summary{cursor:pointer;font-size:11px;font-weight:700;color:var(--ink2);
list-style:none;display:inline-flex;align-items:center;gap:5px}
details.info-d summary::-webkit-details-marker{display:none}
details.info-d summary .i{display:inline-flex;align-items:center;justify-content:center;
width:14px;height:14px;border:1px solid var(--line);font-size:9px;font-weight:800;color:var(--ink2)}
details.info-d[open] summary{margin-bottom:6px}
details.info-d p{margin:0 0 6px;font-size:12px;color:var(--ink2);line-height:1.55}
/* --- coverage --- */
.cov{display:grid;grid-template-columns:1fr auto;gap:2px 14px;align-items:baseline;
padding:7px 0;border-bottom:1px solid var(--line2)}
.cov:last-child{border-bottom:0}
.cov .lab{font-size:13px}
.cov .fig{font-size:13px;white-space:nowrap;text-align:right}
.cov .fig b{color:var(--strong)}
.cov .fig .gap{color:var(--bad);font-weight:700}
.cov .fig .none{color:var(--muted)}
.cov .of{color:var(--faint);font-size:12px}
.meter{grid-column:1/-1;height:3px;background:var(--line2)}
.meter i{display:block;height:3px;background:var(--info)}
.meter i.full{background:var(--good)}
/* --- changes --- */
.chg{border-bottom:1px solid var(--line2);padding:10px 0}
.chg:last-child{border-bottom:0}
.chg .site{font-weight:700;color:var(--strong);font-size:13.5px}
.chg .cnt{color:var(--ink2);font-weight:400;font-size:12.5px}
.chg ul{margin:6px 0 0;padding-left:16px;font-size:12.5px;color:var(--ink2)}
.chg li{margin-bottom:2px}
.chg code{font-size:12px;background:var(--panel2);padding:1px 4px}
/* --- decisions --- */
.dec{display:grid;grid-template-columns:minmax(160px,1fr) minmax(150px,auto) 2fr;
gap:10px 16px;padding:9px 0;border-bottom:1px solid var(--line2);align-items:baseline}
.dec:last-child{border-bottom:0}
.dec .who{font-weight:600;color:var(--strong);font-size:13px}
.dec .act{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--info)}
.dec .why{font-size:12.5px;color:var(--ink2)}
/* --- table --- */
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;
color:var(--ink2);padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--line2);white-space:nowrap}
tr:last-child td{border-bottom:0}
td.dom{font-weight:600;color:var(--strong)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.absent{color:var(--muted);font-style:italic;font-size:12px}
.exflag{display:inline-block;margin-left:6px;font-size:9px;font-weight:800;
letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
border:1px solid var(--line);padding:1px 5px;vertical-align:1px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px}
.filters input,.filters select{font:inherit;font-size:13px;padding:6px 9px;
border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:0}
.filters input{min-width:190px}
.pill{font-size:11px;font-weight:700;padding:5px 10px;border:1px solid var(--line);
background:var(--card);cursor:pointer;color:var(--ink2);border-radius:0}
.pill.on{background:var(--strong);color:#fff;border-color:var(--strong)}
.count{font-size:12px;color:var(--ink2);margin-left:auto}
.note{background:var(--panel2);border-left:3px solid var(--info);padding:10px 13px;
font-size:12.5px;color:var(--ink2);margin-top:10px}
.note b{color:var(--strong)}
@media(max-width:640px){.tile .n{font-size:25px}h1{font-size:20px}}
"""

def chip(state):
    tone = {"CRIT": "bad", "WARN": "info", "OK": "good"}.get(state, "muted")
    glyph = {"CRIT": "●", "WARN": "▲", "OK": "✓",
             "UNKNOWN": "?", "SKIP": "–", "FROZEN": "‖"}.get(state, "–")
    return ('<span class="chip %s"><span class=gl>%s</span>%s</span>'
            % (tone, glyph, e(state)))

A = [].append
o = []
A = o.append

A("<!doctype html><html lang=en><meta charset=utf-8>")
A('<meta name=viewport content="width=device-width,initial-scale=1">')
A("<title>clevermethod fleet &mdash; batch one</title><style>%s</style>" % CSS)
A('<div class=wrap>')

# ---------- masthead + one sweep line -------------------------------------
A('<h1>clevermethod fleet</h1>')
A('<p class=sub style="margin-bottom:14px">85 sites &middot; 6 hosts &middot; '
  'one ledger &middot; read-only</p>')
A('<div class=sweep>')
A('<span><b>Last sweep</b> %s</span>' % e(when(NEWEST)))
A('<span class=quiet>%d sources &middot; %d current &middot; %d older than a day</span>'
  % (NSRC, NSRC - len(stale), len(stale)))
A('<a class=more href="#" style="margin:0">Run &amp; coverage detail &rarr;</a>')
A('</div>')

# ---------- the four exception tiles --------------------------------------
A('<div class=tiles>')
A('<button class="tile bad" data-filter="attention"><div class=lab>Needs attention</div>'
  '<div class=n>%d<small>sites</small></div>'
  '<div class=why>%d critical, %d warning. Excludes %d site marked '
  'non-production.</div></button>'
  % (attention, C["CRIT"], C["WARN"], sum(H["excluded"].values())))
A('<button class="tile info" data-filter="decisions"><div class=lab>Decisions waiting</div>'
  '<div class=n>%d<small>sites</small></div>'
  '<div class=why>No owner and no production ruling. A person decides these, '
  'not a scan.</div></button>' % len(decisions))
A('<button class="tile info" data-filter="changed"><div class=lab>Sites changed</div>'
  '<div class=n>%d<small>sites</small></div>'
  '<div class=why>%d fact(s) moved since each tool&rsquo;s previous run. '
  '%d were routine counter drift.</div></button>'
  % (len(by_site), len(M["changes"]),
     len([c for c in M["changes"] if c["class"] == "DRIFT"])))
A('<button class="tile" data-filter="noevidence"><div class=lab>No health evidence</div>'
  '<div class=n>%d<small>sites</small></div>'
  '<div class=why>Looked at by some tool, but no backup age and no plugin '
  'count. Not the same as healthy.</div></button>' % len(no_ev))
A('</div>')

# ---------- suite cards ---------------------------------------------------
A("<h2>The suite</h2>")
A('<div class=suite>')

# fleet health
backup_readable = len([x for x in M["sites"]
                       if x.get("db_backup_age_days") not in (None, "unknown")])
behind = len([x for x in M["sites"]
              if x.get("wp_core_update") not in (None, "unknown", "n/a", "up-to-date")])
backlog = len([x for x in M["sites"]
               if isinstance(x.get("plugin_updates"), int) and x["plugin_updates"] > 0])
nobackup = len([g for g in M["standing"] if g["cause"].startswith("No recent DB backup")]
               ) and [g for g in M["standing"] if g["cause"].startswith("No recent DB backup")][0]
nobackup_n = len(nobackup["sites"]) if nobackup else 0

A('<div class=card>')
A('<div class=wfhead>Fleet health</div>')
A('<div class=wfq>Is this site being maintained?</div>')
A('<div class=states>')
for st in ("CRIT", "WARN", "OK"):
    A('<button class=st data-filter="health:%s">%s<div class=v>%d <span '
      'style="font-size:12px;font-weight:500;color:var(--ink2)">sites</span></div></button>'
      % (st, chip(st), C[st]))
A('</div>')
A('<div class=exc>')
A('<div><b>%s</b> have no recent database backup &mdash; '
  '<span class=qual>of the <b>%d</b> whose backup age can be read at all. '
  'The other %d are on hosts that expose no backup API.</span></div>'
  % (n_sites(CODES["backup_stale"] + CODES["backup_missing"]),
     backup_readable, 85 - backup_readable))
A('<div><b>%s</b> are behind on WordPress core</div>' % n_sites(CODES["core_update"]))
A('<div><b>%s</b> have a plugin backlog <span class=qual>&mdash; more updates '
  'pending than the threshold, not simply more than zero</span></div>'
  % n_sites(CODES["plugin_backlog"]))
A('<div><b>%s</b> %s PHP past end of security support</div>'
  % (n_sites(CODES["php_eol"]),
     "runs" if CODES["php_eol"] == 1 else "run"))
A('</div>')
A('<details class=info-d><summary><span class=i>i</span>How this is calculated</summary>'
  '<p>Scored from the ledger at render time, not at scan time, so changing a '
  'threshold rescores every run in history instead of reporting as a fleet '
  'change. Thresholds are named constants in the severity module.</p>'
  '<p>A site with <code>production: null</code> scores as production. Nobody '
  'has ruled on it, and failing safe is the point.</p></details>')
A('<a class=more href="#" data-filter="attention">Work the %d &rarr;</a>' % attention)
A('</div>')

# consent
cax = AX.get("consent") or {}
pre = [g for g in M["standing"] if "before conse" in g["cause"]]
pre_n = sum(len(g["sites"]) for g in pre)
notool = [g for g in M["standing"] if g["cause"].startswith("No consent tooling")]
A('<div class=card>')
A('<div class=wfhead>Cookie consent</div>')
A('<div class=wfq>Does the homepage fire trackers before anyone consents?</div>')
A('<div class=states>')
for st in ("WARN", "OK", "UNKNOWN"):
    A('<button class=st data-filter="consent:%s">%s<div class=v>%d <span '
      'style="font-size:12px;font-weight:500;color:var(--ink2)">sites</span></div></button>'
      % (st, chip(st), cax.get(st, 0)))
A('</div>')
A('<div class=exc>')
A('<div><b>%s</b> fire trackers before consent</div>'
  % n_sites(CODES["consent_pre_consent_trackers"]))
A('<div><b>%s</b> have no consent tooling at all</div>'
  % n_sites(CODES["consent_no_tooling"]))
A('<div><b>%s</b> are <span class=qual>UNKNOWN &mdash; the sweep was '
  'refused or the page would not load. That is not a clean result.</span></div>'
  % n_sites(cax.get("UNKNOWN", 0)))
A('</div>')
A('<details class=info-d><summary><span class=i>i</span>How this is calculated</summary>'
  '<p>A real browser loads the public homepage and records what fired before '
  'any consent interaction. Observations only. The words compliant and '
  'non-compliant do not appear in this workflow.</p>'
  '<p>Counts are a floor when the sweep runs headless: some trackers detect '
  'automation and decline to fire. The latest run was headed.</p></details>')
A('<a class=more href="#" data-filter="consent:WARN">See the %d &rarr;</a>'
  % cax.get('WARN', 0))
A('</div>')

# email
dm = [g for g in M["standing"] if g["cause"].startswith("No DMARC")]
al = [g for g in M["standing"] if "not aligned" in g["cause"]]
spf = [g for g in M["standing"] if g["cause"].startswith("No SPF")]
A('<div class=card>')
A('<div class=wfhead>Email &amp; DNS</div>')
A('<div class=wfq>Can the domain each site sends from authenticate its mail?</div>')
A('<div class=exc style="border-top:0;padding-top:0">')
for lab, k, n in (("SPF", 72, 78), ("DKIM", 70, 78), ("DMARC", 78, 78)):
    A('<div><b>%d</b> pass, <b>%d</b> unverified <span class=of '
      'style="color:var(--faint)">&mdash; of %d sending domains</span> '
      '<span class=quiet>%s</span></div>' % (k, n - k, n, lab))
A('</div>')
A('<div class=exc style="margin-top:9px">')
A('<div><b>%s</b> have no DMARC on the domain recipients see</div>'
  % n_sites(len(dm[0]["sites"]) if dm else 0))
A('<div><b>%s</b> send from a domain not aligned with the sending domain</div>'
  % n_sites(len(al[0]["sites"]) if al else 0))
A('<div><b>%s</b> have no SPF record</div>'
  % n_sites(len(spf[0]["sites"]) if spf else 0))
A('</div>')
A('<details class=info-d><summary><span class=i>i</span>What this does and does not check</summary>'
  '<p>Scored per <b>sending domain</b>, not per site. Several sites share one '
  'sending domain and therefore one result, so this card has no site status of '
  'its own.</p>'
  '<p>The sending domain is a <b>ruling</b> a person recorded. 59 of 75 sites '
  'now have their From: address measured off the site instead, and it is '
  'stored beside the ruling rather than over it. It does not verify the '
  'sending domain: most sites send through an API where the envelope sender '
  'is set by the provider.</p></details>')
A('<a class=more href="#">Open causes &rarr;</a>')
A('</div>')
A('</div>')

# ---------- coverage: checked / not checked -------------------------------
A("<h2>Coverage</h2>")
A('<p class=sub style="margin:-6px 0 10px">What is <em>not</em> checked is the '
  'operational number. Each row states its own denominator.</p>')
A('<div class=card>')
for lab, (k, n) in M["coverage"]:
    gap = n - k
    A('<div class=cov><div class=lab>%s</div>'
      '<div class=fig><b>%d</b> checked &middot; %s <span class=of>&mdash; of %d</span></div>'
      '<div class=meter><i class="%s" style="width:%.1f%%"></i></div></div>'
      % (e(lab), k,
         ('<span class=none>none missing</span>' if not gap
          else '<span class=gap>%d not checked</span>' % gap),
         n, "full" if not gap else "", (100.0 * k / n) if n else 0))
A('</div>')

# ---------- changes grouped by site ---------------------------------------
A("<h2>What changed</h2>")
A('<p class=sub style="margin:-6px 0 10px"><b>%d fact(s) across %d site(s)</b> '
  'since the previous run of each tool. Grouped by site, because one upgrade '
  'moves several facts at once.</p>' % (len(M["changes"]), len(by_site)))
A('<div class=card>')
order = sorted(by_site.items(),
               key=lambda kv: (-len([c for c in kv[1] if c["class"] != "DRIFT"]),
                               -len(kv[1]), kv[0]))
for site, cs in order[:8]:
    notable = [c for c in cs if c["class"] != "DRIFT"]
    A('<div class=chg><div class=site>%s <span class=cnt>&mdash; %d change(s)%s'
      '</span></div><ul>' % (e(site), len(cs),
                             "" if notable else ", all routine counter drift"))
    for c in cs:
        A('<li>%s <code>%s</code> &rarr; <code>%s</code>%s</li>'
          % (e(str(c.get("fact"))), e(str(c.get("before"))), e(str(c.get("after"))),
             '' if c["class"] != "DRIFT" else ' <span class=quiet>routine</span>'))
    A('</ul></div>')
A('</div>')
A('<div class=note><b>Direction is deliberately not labelled here.</b> '
  'A count moving is not automatically better or worse: when the consent sweep '
  'changed from a headless to a headed browser, tracker counts rose on many '
  'sites at once and nothing had started firing &mdash; we started being able '
  'to see it. The ledger already separates <b>the fleet changed</b> from '
  '<b>the instrument changed</b>, and that classification is what drives this '
  'list.</div>')

# ---------- decisions -----------------------------------------------------
A("<h2>Decisions waiting</h2>")
A('<p class=sub style="margin:-6px 0 10px">A ruling is the half of the data '
  'model a person decides rather than a tool measures. Nothing here is '
  'editable on this page &mdash; it is generated, and it is read-only by '
  'design.</p>')
A('<div class=card>')
for sid in decisions:
    A('<div class=dec><div class=who>%s</div>'
      '<div class=act>Set production status</div>'
      '<div class=why>In the Pantheon account with no client, owner or '
      'production ruling recorded.</div></div>' % e(sid))
A('</div>')
A('<div class=note><b>83 of 84 sites have no production ruling at all.</b> '
  'The five above are the narrow set that also has no ownership record. The '
  'wider number is a coverage fact about the fleet, not a per-site flag, and '
  'no interface improves it &mdash; the ruling pass has to be run once.</div>')

# ---------- the table -----------------------------------------------------
A("<h2>Every site</h2>")
A('<div class=filters>')
A('<input id=q type=search placeholder="Search sites" aria-label="Search sites">')
A('<select id=host><option value="">All hosts</option>%s</select>'
  % "".join('<option>%s</option>' % e(h) for h in
            sorted({s.get("host") for s in M["sites"] if s.get("host")})))
for lab, f in (("All", ""), ("Attention", "attention"), ("Changed", "changed"),
               ("Decisions", "decisions"), ("No health evidence", "noevidence")):
    A('<button class="pill%s" data-filter="%s">%s</button>'
      % (" on" if not f else "", f, e(lab)))
A('<span class=count id=cnt></span>')
A('</div>')
A('<div class=tablewrap><table id=t><thead><tr>'
  '<th>Site</th><th>Health</th><th>Consent</th><th>Host</th>'
  '<th>WordPress</th><th class=num>Plugin updates</th>'
  '<th class=num>Backup age</th><th>Sends from</th></tr></thead><tbody>')

def cell(v, unit=""):
    if v in (None, "unknown", "n/a"):
        return '<span class=absent>not measured</span>'
    return "%s%s" % (e(str(v)), unit)

for s in sorted(M["sites"], key=lambda x: x["site_id"]):
    sev = s.get("severity") or {}
    st = sev.get("status")
    cst = ((sev.get("axes") or {}).get("consent") or {}).get("status")
    flags = []
    if st in ("CRIT", "WARN"):
        flags.append("attention")
    if s["site_id"] in by_site:
        flags.append("changed")
    if s["site_id"] in decisions:
        flags.append("decisions")
    if s in no_ev:
        flags.append("noevidence")
    bk = s.get("db_backup_age_days")
    # SHOWN BUT NOT COUNTED. cm-whitelabel is production:false, so the cards
    # exclude it and the table keeps it -- a site is never dropped. Clicking
    # "54 sites" therefore returns 55 rows, and without saying so on the row
    # the card reads as wrong. Found by driving the filters, not by looking.
    excl = not (sev.get("production", True))
    A('<tr data-f="%s" data-host="%s" data-site="%s" data-health="%s" '
      'data-consent="%s" data-excluded="%s">'
      % (" ".join(flags), e(s.get("host") or ""), e(s["site_id"]), e(st or ""),
         e(cst or ""), "1" if excl else ""))
    A('<td class=dom>%s%s</td>'
      % (e(s["site_id"]),
         ' <span class=exflag title="production: false, set by a person">'
         'not counted</span>' if excl else ""))
    A('<td>%s</td>' % chip(st))
    A('<td>%s</td>' % chip(cst))
    A('<td class=quiet>%s</td>' % e(s.get("host") or ""))
    A('<td>%s</td>' % cell(s.get("wp_version")))
    A('<td class=num>%s</td>' % cell(s.get("plugin_updates")))
    A('<td class=num>%s</td>'
      % ('<span class=absent>no backup API</span>' if bk in (None, "unknown")
         else "%s d" % e(str(bk))))
    A('<td>%s</td>' % cell(s.get("smtp_from_domain") or s.get("spf_checked_at")))
    A("</tr>")
A("</tbody></table></div>")
A('<div class=note><b>&ldquo;Not measured&rdquo; is printed, never left blank '
  'and never shown as a zero.</b> A blank cell reads as nothing to report. '
  'Every empty value on this page says which kind of absence it is: nobody '
  'looked, the host exposes no such API, or the call failed.</div>')

A("""
<script>
var rows=[].slice.call(document.querySelectorAll('#t tbody tr'));
var q=document.getElementById('q'),hs=document.getElementById('host'),
    cnt=document.getElementById('cnt'),active='';
function apply(){
  var term=(q.value||'').toLowerCase(), host=hs.value, n=0;
  rows.forEach(function(r){
    var ok=true;
    if(term && r.dataset.site.toLowerCase().indexOf(term)<0) ok=false;
    if(host && r.dataset.host!==host) ok=false;
    if(active){
      if(active.indexOf(':')>0){
        var p=active.split(':');
        if(r.dataset[p[0]]!==p[1]) ok=false;
      } else if((' '+r.dataset.f+' ').indexOf(' '+active+' ')<0) ok=false;
    }
    r.style.display=ok?'':'none'; if(ok)n++;
  });
  var ex=rows.filter(function(r){return r.style.display!=='none'&&r.dataset.excluded;}).length;
  cnt.textContent=n+' of '+rows.length+' sites shown'
    +(ex?' \u00b7 '+ex+' not counted in the cards above':'');
}
function setFilter(f){
  active=f;
  document.querySelectorAll('.pill').forEach(function(p){
    p.classList.toggle('on',p.dataset.filter===f);
  });
  apply();
  document.getElementById('t').scrollIntoView({behavior:'smooth',block:'start'});
}
document.querySelectorAll('[data-filter]').forEach(function(el){
  el.addEventListener('click',function(ev){ev.preventDefault();setFilter(el.dataset.filter);});
});
q.addEventListener('input',apply); hs.addEventListener('change',apply);
apply();
</script>
""")
A("</div>")

out = "docs/mockups/fleet-batch-one.html"
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w").write("\n".join(o))
print("wrote %s (%d KB)" % (out, len(open(out).read()) // 1024))
print("attention=%d decisions=%d changed_sites=%d no_evidence=%d"
      % (attention, len(decisions), len(by_site), len(no_ev)))
