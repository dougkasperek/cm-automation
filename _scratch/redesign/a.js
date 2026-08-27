/* Concept A — The Queue. The primary object is a decision, not a site. */
const standingBy = cause => D.standing.find(g => g.cause === cause);
const standingStarts = prefix => D.standing.filter(g => g.cause.startsWith(prefix));
const was = g => D.standing_was[g.cause];

function delta(g) {
  const w = was(g); if (w === undefined) return h('span', { class: 'it-delta' }, 'no baseline');
  const d = g.sites.length - w;
  if (d === 0) return h('span', { class: 'it-delta' }, 'unchanged at ' + w);
  return h('span', { class: 'it-delta ' + (d > 0 ? 'up' : 'down') }, (d > 0 ? '↑' : '↓') + Math.abs(d) + ' was ' + w);
}
function siteButtons(ids, detail) {
  return h('ul', { class: 'sitelist' }, ...ids.map(id => h('li', {}, h('button', { onclick: () => openSite(id) }, id, detail && detail[id] ? h('small', {}, detail[id]) : null))));
}
function item({ title, n, of, ofLabel, kind, action, body, sites, detail, cls, delta: dl }) {
  const det = h('details', { class: 'item ' + (cls || '') },
    h('summary', {},
      h('div', { class: 'it-title' }, title),
      h('div', { class: 'it-num' }, n, h('small', {}, of != null ? 'of ' + of + ' ' + ofLabel : ofLabel || '')),
      h('div', { class: 'it-meta' }, kind ? kindChip(kind) : null, dl || null)),
    h('div', { class: 'it-body' }, action ? h('p', {}, action) : null, body || null, sites ? siteButtons(sites, detail) : null));
  return det;
}

/* denominators, each a named set counted from the model */
const N = {
  sites: SITES.length,
  counted: COUNTED.length,
  coreMeasured: SITES.filter(s => isMeasured(s.f.wp_core_update)).length,
  inventoried: D.components.sites_inventoried.length,
  phpMeasured: SITES.filter(s => isMeasured(s.f.php_version) || isMeasured(s.f.nexcess_php_version)).length,
  upstreamMeasured: SITES.filter(s => isMeasured(s.f.upstream_pending)).length,
  backupMeasured: SITES.filter(s => isMeasured(s.f.db_backup_age_days)).length,
  consentLoaded: SITES.filter(s => s.f.consent_scan_ok === true).length,
  consentRows: SITES.filter(s => s.f.consent_scan_ok !== null && s.f.consent_scan_ok !== undefined).length,
  emailRows: SITES.filter(s => s.f.spf_present !== null && s.f.spf_present !== undefined).length,
  spfMeasured: SITES.filter(s => typeof s.f.spf_present === 'boolean').length,
  dmarcFromMeasured: SITES.filter(s => typeof s.f.dmarc_at_from_present === 'boolean').length,
  alignMeasured: SITES.filter(s => typeof s.f.relaxed_aligned === 'boolean').length,
};

/* ---- column 1: needs a person ------------------------------------------- */
const crit = COUNTED.filter(s => s.health.status === 'CRIT');
const excludedCrit = SITES.filter(s => !s.counts && s.health.status === 'CRIT');
const col1 = [];
for (const s of crit) col1.push(item({
  title: s.id, n: 1, ofLabel: 'site', kind: 'RISK', cls: 'crit-item',
  action: s.health.reasons.filter(r => r.level === 'CRIT').map(r => r.text).join('; ') + '.',
  body: h('p', { class: 'quiet' }, (s.f.plan === 'Sandbox' ? 'Sandbox plan: no automatic nightly backup. ' : '') + (D.unreviewed.includes(s.id) ? 'No owner and no production ruling: nobody has said whether this is a client site.' : (s.health.reasons.filter(r => r.level !== 'CRIT').map(r => r.text).join('; ') || ''))),
  sites: [s.id],
}));
const gLeak = standingBy('Consent tooling present, but trackers fire before consent');
if (gLeak) col1.push(item({ title: 'Consent banner present, trackers fire first', n: gLeak.sites.length, of: N.consentLoaded, ofLabel: 'homepages loaded', kind: 'RISK', cls: 'crit-item', action: gLeak.action, sites: gLeak.sites, detail: gLeak.detail, delta: delta(gLeak) }));
const gSpf = standingBy('No SPF record on the sending domain');
if (gSpf) col1.push(item({ title: 'No SPF record on the sending domain', n: gSpf.sites.length, of: N.spfMeasured, ofLabel: 'domains resolved', kind: 'RISK', cls: 'crit-item', action: gSpf.action, sites: gSpf.sites, delta: delta(gSpf) }));

/* ---- column 2: schedule (batchable maintenance) --------------------------- */
const col2 = [];
for (const g of standingStarts('WordPress ').filter(g => g.cause.includes('available'))) {
  const target = g.cause.match(/WordPress ([\d.]+)/)[1];
  const from = {}; for (const id of g.sites) { const v = BY_ID[id]?.f.wp_version; from[v] = (from[v] || 0) + 1; }
  col2.push(item({ title: 'Apply WordPress ' + target, n: g.sites.length, of: N.coreMeasured, ofLabel: 'sites with a core reading', kind: 'DRIFT', delta: delta(g),
    action: 'One release, one decision. Installed today: ' + Object.entries(from).sort((a, b) => b[1] - a[1]).map(([v, n]) => v + ' ×' + n).join(', ') + '.',
    body: h('p', { class: 'quiet' }, 'Open since ' + fmtDay(D.all_runs.find(r => r.source === 'health' && r.mode === 'full' && r.site_count > 3).observed_at.slice(0, 10)) + ' on most of these sites, the first full scan in the ledger; nothing older exists to compare against.'),
    sites: g.sites, detail: Object.fromEntries(g.sites.map(id => [id, BY_ID[id]?.f.wp_version + ' → ' + target])) }));
}
// plugin updates, by component: the same update on many sites is one decision
const pend = D.components.catalogue.filter(c => c.pending > 0).sort((a, b) => b.pending - a.pending);
const pendTotal = pend.reduce((n, c) => n + c.pending, 0);
const topComps = pend.slice(0, 12);
let cum = 0; const cumAt = {};
pend.forEach((c, i) => { cum += c.pending; if ([4, 9, 19].includes(i)) cumAt[i + 1] = cum; });
const compList = h('ul', { class: 'comp' }, ...topComps.map(c => h('li', {},
  h('span', { class: 'slug' }, c.slug, h('small', {}, ' → ' + (c.target[0] || '?') + (c.type !== 'plugin' ? ' · ' + c.type : ''))),
  h('span', { class: 'n' }, c.pending),
  h('span', { class: 'bar', title: c.pending + ' of ' + c.sites + ' installs pending' }, h('i', { style: 'width:' + Math.round(100 * c.pending / Math.max(1, c.sites)) + '%' })))));
const sitesWithPending = AGG.pendingSites.length;
col2.push(item({ title: 'Plugin and theme updates, batched by component', n: pend.length, ofLabel: 'components, ' + pendTotal + ' installs', kind: 'DRIFT',
  action: `${pendTotal} pending installs across ${sitesWithPending} of ${N.inventoried} inventoried sites. The top 5 components cover ${cumAt[5]}, the top 10 cover ${cumAt[10]}, the top 20 cover ${cumAt[20]}. Every component wants a single target version, so each row is one decision. Bars show the share of that component's installs that are behind.`,
  body: h('div', {}, compList, h('p', { class: 'cum' }, 'Showing 12 of ' + pend.length + ' components with something pending. The per-site backlog list is in each site\'s drawer.')),
  sites: null }));
const gBacklog = standingBy('Plugin updates pending, 10 or more');
if (gBacklog) col2.push(item({ title: 'Sites over the 10-update line', n: gBacklog.sites.length, of: N.inventoried, ofLabel: 'inventoried sites', kind: 'DRIFT', delta: delta(gBacklog),
  action: 'The per-site view of the same backlog: these are the sites that score WARN for it. Largest is ' + gBacklog.sites.map(id => [id, BY_ID[id].f.plugin_updates]).sort((a, b) => b[1] - a[1])[0].join(' at ') + '.',
  sites: gBacklog.sites, detail: Object.fromEntries(gBacklog.sites.map(id => [id, BY_ID[id].f.plugin_updates + ' pending'])) }));
const gPhp = D.standing.find(g => g.axis === 'PLANNING');
if (gPhp) col2.push(item({ title: gPhp.cause, n: gPhp.sites.length, of: N.phpMeasured, ofLabel: 'sites with a PHP reading', kind: 'PLANNING', delta: delta(gPhp), action: gPhp.action, sites: gPhp.sites }));
const gUp = standingBy('One pending Pantheon upstream commit, unmerged');
if (gUp) col2.push(item({ title: 'Merge the pending Pantheon upstream', n: gUp.sites.length, of: N.upstreamMeasured, ofLabel: 'Pantheon sites read', kind: 'DRIFT', delta: delta(gUp), action: gUp.action, sites: gUp.sites }));

/* ---- column 3: needs a ruling ------------------------------------------- */
const col3 = [];
col3.push(item({ title: 'Sites with no owner and no production ruling', n: D.unreviewed.length, of: N.sites, ofLabel: 'sites', kind: 'RISK',
  action: 'Nobody has said whether these are client sites or scratch. Until someone does, each counts as production and no scan can clear it. This set has held the two worst-maintained sites in the fleet.',
  sites: D.unreviewed, detail: Object.fromEntries(D.unreviewed.map(id => [id, (BY_ID[id].f.plan || '') + ' · ' + WORD[BY_ID[id].health.status]])) }));
const gNoTool = standingBy('No consent tooling detected on the homepage');
const gNoToolLeak = standingBy('Trackers fire before consent, and no consent tooling is present');
if (gNoTool) col3.push(item({ title: 'Consent tooling: in scope or not?', n: gNoTool.sites.length, of: N.consentLoaded, ofLabel: 'homepages loaded', kind: 'RISK', delta: delta(gNoTool),
  action: gNoTool.action + (gNoToolLeak ? ` ${gNoToolLeak.sites.length} of them already fire a tracker on load.` : ''),
  sites: gNoTool.sites, detail: gNoToolLeak ? Object.fromEntries(gNoTool.sites.map(id => [id, gNoToolLeak.detail?.[id] ? 'fires: ' + gNoToolLeak.detail[id] : 'no tracker seen'])) : null }));
const gPnone = standingBy('DMARC published but p=none');
if (gPnone) col3.push(item({ title: 'DMARC policy is p=none', n: gPnone.sites.length, of: N.dmarcFromMeasured, ofLabel: 'domains with DMARC read', kind: 'DRIFT', delta: delta(gPnone), action: gPnone.action, sites: gPnone.sites }));
const gNoDmarc = standingBy('No DMARC on the domain recipients actually see');
if (gNoDmarc) col3.push(item({ title: 'No DMARC at the From domain', n: gNoDmarc.sites.length, of: N.dmarcFromMeasured, ofLabel: 'domains with DMARC read', kind: 'RISK', delta: delta(gNoDmarc), action: gNoDmarc.action, sites: gNoDmarc.sites }));
const gAlign = standingBy('From domain not aligned with sending domain');
if (gAlign) col3.push(item({ title: 'From domain not aligned with sending domain', n: gAlign.sites.length, of: N.alignMeasured, ofLabel: 'domains measured', kind: 'RISK', delta: delta(gAlign), action: gAlign.action, sites: gAlign.sites }));
const decom = SITES.filter(s => s.decommission_candidate);
if (decom.length) col3.push(item({ title: 'Marked as decommission candidates in the inventory', n: decom.length, of: N.sites, ofLabel: 'sites', action: 'A person flagged these. Nothing on this page changes until the flag is resolved.', sites: decom.map(s => s.id), detail: Object.fromEntries(decom.map(s => [s.id, s.notes || ''])) }));
const unrec = D.unreconciled.filter(u => !D.unreviewed.includes(u.id));
if (unrec.length) col3.push(item({ title: 'Other sites that do not reconcile', n: unrec.length, of: N.sites, ofLabel: 'sites', action: 'In one source and not the other, with a ruling recorded or a measured explanation. Listed so the disagreement stays visible.', sites: unrec.map(u => u.id), detail: Object.fromEntries(unrec.map(u => [u.id, (u.why || '').slice(0, 90) + ((u.why || '').length > 90 ? '…' : '')])) }));

/* ---- column 4: can't see -------------------------------------------------- */
const col4 = [];
const nhe = D.no_health_evidence;
const byHost = {}; for (const id of nhe) { const hst = BY_ID[id]?.host || '?'; byHost[hst] = (byHost[hst] || 0) + 1; }
col4.push(item({ title: 'No health evidence at all', n: nhe.length, of: N.sites, ofLabel: 'sites', kind: 'COVERAGE', cls: 'abs-item',
  action: 'Looked at by another scan, never by a health scan: no backup age, no plugin count, no WordPress version. They score WARN so they cannot read as healthy, and they are not the same as the 41 sites with a real backlog. By host: ' + Object.entries(byHost).sort((a, b) => b[1] - a[1]).map(([k, v]) => k + ' ' + v).join(', ') + '. No single scanner build clears more than four of them.',
  sites: nhe, detail: Object.fromEntries(nhe.map(id => [id, BY_ID[id].host])) }));
const gBlocked = standingBy('The consent sweep could not see the site');
if (gBlocked) col4.push(item({ title: 'Homepages the consent sweep could not load', n: gBlocked.sites.length, of: N.consentRows, ofLabel: 'domains in the sweep', kind: 'COVERAGE', cls: 'abs-item', delta: delta(gBlocked),
  action: 'Unmeasured, not clean. No consent rule scores on these, and their consent status is Unknown on purpose.', sites: gBlocked.sites, detail: gBlocked.detail }));
const gSpfU = standingBy('SPF could not be determined');
if (gSpfU) col4.push(item({ title: 'SPF lookup returned nothing usable', n: gSpfU.sites.length, of: N.emailRows, ofLabel: 'domains checked', kind: 'COVERAGE', cls: 'abs-item', delta: delta(gSpfU), action: gSpfU.action, sites: gSpfU.sites }));
const missing = D.components.sites_missing;
col4.push(item({ title: 'Not inventoried for components', n: missing.length, of: D.components.expected.length, ofLabel: 'Pantheon + Nexcess sites', kind: 'COVERAGE', cls: 'abs-item',
  action: 'No plugin or theme list exists for these, so no CVE question can be answered about them and no update is counted. Zero rows is not "runs nothing".', sites: missing, detail: Object.fromEntries(missing.map(id => [id, BY_ID[id] ? BY_ID[id].host + (BY_ID[id].f.framework === 'not-wordpress' ? ' · not WordPress' : '') : ''])) }));
const nxNoBackup = AGG.nexcess.filter(s => !isMeasured(s.f.db_backup_age_days));
col4.push(item({ title: 'Backup age unmeasurable on Nexcess', n: nxNoBackup.length, of: AGG.nexcess.length, ofLabel: 'Nexcess sites', kind: 'COVERAGE', cls: 'abs-item',
  action: 'Nexcess exposes no backup API. These sites have real WordPress and plugin data and look well-measured, but "no recent backup" can only ever be found on the ' + N.backupMeasured + ' sites whose backup age is readable. Unmeasurable is not the same as unmeasured; a scanner change cannot fix this one.',
  sites: nxNoBackup.map(s => s.id) }));
const gWpNo = standingBy('WordPress core, plugin and theme status not observed');
if (gWpNo) col4.push(item({ title: 'WordPress status not observed', n: gWpNo.sites.length, of: N.sites, ofLabel: 'sites', kind: 'COVERAGE', cls: 'abs-item', delta: delta(gWpNo), action: gWpNo.action, sites: gWpNo.sites, detail: Object.fromEntries(gWpNo.sites.map(id => [id, BY_ID[id].f.framework === 'not-wordpress' ? 'control plane says WordPress 6.2.2; the site is not WordPress' : ''])) }));

/* ---- assemble ------------------------------------------------------------- */
const sweep = sweepLine();
const newest = sweep.reduce((a, b) => (a[1].observed_at > b[1].observed_at ? a : b));
const app = $('#app');
app.append(
  h('div', { class: 'wrap' },
    h('header', { class: 'top' },
      h('h1', {}, 'clevermethod fleet ', h('span', {}, '· ' + N.sites + ' sites · read-only · ledger of ' + D.all_runs.length + ' runs')),
      h('div', { class: 'sweep' }, ...sweep.map(([name, r]) => h('span', { class: ageDays(r.observed_at) > 1 ? 'stale' : '' }, name + ' ', h('b', {}, fmtEastern(r.observed_at)), ' ' + (r.deep_scanned ?? '?') + '/' + r.site_count)))),
    h('p', { class: 'certain' },
      h('b', {}, D.counts.CRIT + ' critical'), ' · ', h('b', {}, D.counts.WARN + ' warning'), ' (', AGG.backlogOnly.length + ' are a WordPress or plugin backlog, ' + AGG.warnUnest.length + ' are sites nothing has established health for', ') · ', h('b', {}, D.counts.OK + ' with nothing pending'), ' · ' + D.counts.SKIP + ' skip · ' + D.counts.FROZEN + ' frozen · ' + D.excluded_sites.length + ' excluded by ruling. ',
      'Consent: ' + D.axes.consent.WARN + ' warning · ' + D.axes.consent.OK + ' OK · ' + D.axes.consent.UNKNOWN + ' unknown. The board below is the same findings arranged by the decision each one needs.'),
    h('div', { class: 'board' },
      column('person', 'Act now', 'a person, today', col1, crit.length + (gLeak?.sites.length || 0) + (gSpf?.sites.length || 0)),
      column('schedule', 'Schedule', 'batched maintenance, no emergency', col2, col2.length),
      column('decide', 'Decide', 'a ruling, nothing to run', col3, col3.length),
      column('cover', "Can't see", 'the scanner\'s gap, not the site\'s fault', col4, col4.length)),
    movement(),
    index(),
    h('footer', { class: 'foot' },
      h('p', {}, 'Every count above is over a named set, printed beside it. Hatched tokens are absences: "not scanned" means no source wrote the fact, "unknown" means the scan asked and got no answer, "n/a" means the scan does not ask on that host. None of them is a value.'),
      h('p', {}, 'Times are the ledger\'s UTC stamps shown as Eastern (UTC−4 in August). Generated ' + D.generated + ' from a ' + D.all_runs.length + '-run ledger; the earliest full health run is ' + fmtDay(AGG.histFrom.slice(0, 10)) + ', so nothing here claims a trend.'),
      h('p', {}, 'Concept A of three. Decisions are the primary object; per-site status lives in the index and the drawer. Excluded by ruling: ' + D.excluded_sites.join(', ') + ' (scored ' + excludedCrit.map(s => WORD[s.health.status]).join(', ') + ', not counted).'))));

function column(key, title, sub, items, n) {
  return h('section', { class: 'col col-' + key },
    h('div', { class: 'col-head' }, h('h2', {}, title), h('div', { class: 'n' }, n, h('small', {}, key === 'person' ? 'sites' : 'items'))),
    h('p', { class: 'col-sub' }, sub),
    ...(items.length ? items : [h('p', { class: 'quiet' }, 'Nothing here.')]));
}
function movement() {
  const tr = D.changes.filter(c => c.class === 'TRANSITION');
  const drift = D.changes.filter(c => c.class === 'DRIFT');
  const others = D.changes.filter(c => !['TRANSITION', 'DRIFT'].includes(c.class));
  return h('section', { class: 'movement' },
    h('h2', {}, 'Movement'),
    h('div', { class: 'mv-grid' },
      h('div', {}, h('span', { class: 'n' }, tr.length), 'threshold crossing since the previous run', h('p', {}, tr.length ? tr.map(c => c.site + ' ' + c.before + ' → ' + c.after).join('; ') : 'none'), ...tr.map(c => h('p', {}, h('button', { class: 'linkish', onclick: () => openSite(c.site) }, 'open ' + c.site)))),
      h('div', {}, h('span', { class: 'n' }, drift.length), 'routine counter moves', h('p', {}, 'already-open findings ticking: ' + Object.entries(drift.reduce((m, c) => (m[c.fact] = (m[c.fact] || 0) + 1, m), {})).map(([k, v]) => k + ' ×' + v).join(', ') + '. Not news.')),
      h('div', {}, h('span', { class: 'n' }, others.length), 'inventory, onset, resolved or rule changes', h('p', {}, others.length ? others.map(c => c.class + ' ' + c.site + ' ' + c.fact).join('; ') : 'none this run')),
      h('div', {}, h('span', { class: 'n' }, AGG.wpMoved.length), 'sites moved WordPress version over the ledger', h('p', {}, fmtDay(AGG.histFrom.slice(0, 10)) + '–' + fmtDay(AGG.histTo.slice(0, 10)) + ', ' + AGG.fullRunCount + ' full runs: ' + wpMovedSummary() + '. The previous-run diff never shows this; only the ledger does.')),
      h('div', {}, h('span', { class: 'n' }, AGG.grew + ' / ' + AGG.same + ' / ' + AGG.shrank), 'plugin backlogs grew / held / shrank', h('p', {}, 'of ' + AGG.withHist + ' sites with two or more readings over the same window. Movement, not a trend: ' + AGG.fullRunCount + ' runs in ' + Math.round((new Date(AGG.histTo) - new Date(AGG.histFrom)) / 86400000) + ' days.')),
      h('div', {}, h('span', { class: 'n' }, D.coverage_changes.length), 'facts that became visible', h('p', {}, D.coverage_changes.map(c => c.fact + ' on ' + c.sites.length).join(', ') + '. Our visibility changing, not the fleet.'))));
}
function wpMovedSummary() {
  const m = {}; for (const x of AGG.wpMoved) { const k = x[1] + '→' + x[2]; m[k] = (m[k] || 0) + 1; }
  return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([k, v]) => k + ' ×' + v).join(', ') || 'none';
}
function index() {
  const rows = SITES.slice().sort((a, b) => LANE_ORDER.indexOf(lane(a)) - LANE_ORDER.indexOf(lane(b)) || a.id.localeCompare(b.id));
  const tbody = h('tbody');
  const q = h('input', { type: 'search', placeholder: 'Filter sites', 'aria-label': 'Filter sites' });
  const hostSel = h('select', {}, h('option', { value: '' }, 'All hosts'), ...[...new Set(SITES.map(s => s.host))].sort().map(x => h('option', { value: x }, x)));
  const laneSel = h('select', {}, h('option', { value: '' }, 'Everything'), ...LANE_ORDER.map(k => h('option', { value: k }, LANE[k].word)));
  const count = h('span', { class: 'count' });
  function draw() {
    tbody.innerHTML = '';
    const term = q.value.trim().toLowerCase();
    const shown = rows.filter(s => (!term || s.id.includes(term)) && (!hostSel.value || s.host === hostSel.value) && (!laneSel.value || lane(s) === laneSel.value));
    for (const s of shown) {
      const L = lane(s);
      tbody.append(h('tr', {},
        h('td', {}, h('span', { class: 'site', tabindex: 0, role: 'button', onclick: () => openSite(s.id), onkeydown: e => { if (e.key === 'Enter') openSite(s.id); } }, s.id)),
        h('td', {}, s.host.replace('CM ', '')),
        h('td', {}, h('span', { class: 'lane lane-' + L }, LANE[L].word)),
        h('td', {}, chip(s.health.status)),
        h('td', {}, chip(s.consent.status)),
        h('td', { class: 'in' }, inQueue(s))));
    }
    count.textContent = shown.length + ' of ' + rows.length + ' sites';
  }
  q.addEventListener('input', draw); hostSel.addEventListener('change', draw); laneSel.addEventListener('change', draw);
  draw();
  return h('section', { class: 'index' }, h('h2', {}, 'Every site'),
    h('div', { class: 'idx-tools' }, q, hostSel, laneSel, count),
    h('div', { class: 'idx-wrap' }, h('table', { class: 'idx' }, h('thead', {}, h('tr', {}, h('th', {}, 'Site'), h('th', {}, 'Host'), h('th', {}, 'Next'), h('th', {}, 'Health'), h('th', {}, 'Consent'), h('th', {}, 'Why it is in the queue'))), tbody)));
}
function inQueue(s) {
  const bits = [];
  for (const r of s.health.reasons) bits.push(r.text);
  for (const r of s.consent.reasons) bits.push(r.code === 'consent_no_tooling' ? 'no consent tooling' : r.code === 'consent_pre_consent_trackers' ? 'fires ' + (s.f.consent_pre_tracker_names || 'trackers') + ' before consent' : r.text);
  if (s.f.dmarc_at_from_present === false) bits.push('no DMARC at From domain');
  if (s.f.relaxed_aligned === false) bits.push('From not aligned');
  if (s.f.spf_present === false) bits.push('no SPF');
  if (D.unreviewed.includes(s.id)) bits.push('no production ruling');
  if (!s.counts) bits.push('excluded by ruling');
  return bits.length ? bits.join(' · ') : (s.health.status === 'OK' ? 'nothing pending on what was measured' : '');
}
if (location.hash.startsWith('#site=')) openSite(decodeURIComponent(location.hash.slice(6)));
