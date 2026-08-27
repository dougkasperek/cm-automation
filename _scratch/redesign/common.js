/* Shared helpers for the three concepts. Nothing here computes a status: statuses
   and reasons come from the embedded model (severity.py, at render time). What is
   computed here is grouping and counting, and every count is over a named set. */
const D = JSON.parse(document.getElementById('fleet-data').textContent);
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
};
const SITES = D.sites;
const BY_ID = Object.fromEntries(SITES.map(s => [s.id, s]));
const COUNTED = SITES.filter(s => s.counts);

/* ---- absence vocabulary -------------------------------------------------
   null      the source never wrote a row for this site   -> "not scanned"
   "unknown" the scan asked and got no answer             -> "unknown"
   "n/a"     the scan does not ask this question here     -> "n/a"
   Everything else is a measurement. These three are never rendered like a value. */
function kind(v) {
  if (v === null || v === undefined) return 'none';
  if (v === 'unknown') return 'unknown';
  if (v === 'n/a') return 'na';
  return 'value';
}
const ABSENT_LABEL = { none: 'not scanned', unknown: 'unknown', na: 'n/a' };
function isMeasured(v) { return kind(v) === 'value'; }

/* A value cell: measured values render plainly; absences render as a hatched
   token with the absence word, never as a number and never as a colour. */
function val(v, fmt) {
  const k = kind(v);
  if (k !== 'value') return h('span', { class: 'abs abs-' + k, title: absenceTitle(k) }, ABSENT_LABEL[k]);
  return h('span', { class: 'v' }, fmt ? fmt(v) : String(v));
}
function absenceTitle(k) {
  return { none: 'No scan has written this fact for this site.', unknown: 'The scan asked and could not read an answer.', na: 'This scan does not measure this on this host.' }[k];
}

/* ---- status chips: glyph + word, colour is secondary ----------------------- */
const GLYPH = { CRIT: '■', WARN: '▲', OK: '●', UNKNOWN: '?', SKIP: '–', FROZEN: '❄' };
const WORD = { CRIT: 'Critical', WARN: 'Warning', OK: 'OK', UNKNOWN: 'Unknown', SKIP: 'Skip', FROZEN: 'Frozen' };
function chip(status, extra = '') {
  return h('span', { class: 'chip st-' + status + (extra ? ' ' + extra : ''), 'data-st': status },
    h('span', { class: 'g', 'aria-hidden': 'true' }, GLYPH[status] || '·'), WORD[status] || status);
}
const KIND_WORD = { RISK: 'Risk', COVERAGE: 'Coverage', PLANNING: 'Planning', DRIFT: 'Drift' };
function kindChip(k) { return h('span', { class: 'kind kind-' + k }, KIND_WORD[k] || k); }

/* ---- dates ---------------------------------------------------------------- */
function fmtEastern(iso) {
  // ledger stamps are UTC. Eastern is UTC-4 in August; the concept renders the
  // offset as data (the stamp) rather than a rule, and says so in the footer.
  const d = new Date(iso + 'Z');
  const e = new Date(d.getTime() - 4 * 3600 * 1000);
  const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][e.getUTCMonth()];
  let hh = e.getUTCHours(), mm = String(e.getUTCMinutes()).padStart(2, '0');
  const ap = hh >= 12 ? 'PM' : 'AM'; hh = hh % 12 || 12;
  return `${mo} ${e.getUTCDate()}, ${hh}:${mm} ${ap} ET`;
}
function fmtDay(iso) { const d = new Date(iso + 'T00:00:00Z'); return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getUTCMonth()] + ' ' + d.getUTCDate(); }
function ageDays(iso) { return Math.round((new Date(D.generated + 'T12:00:00Z') - new Date(iso + 'Z')) / 86400000); }

/* ---- reason predicates ---------------------------------------------------- */
const codes = (s, axis) => (s[axis].reasons || []).map(r => r.code);
const has = (s, axis, c) => codes(s, axis).includes(c);
const BACKLOG = new Set(['core_update', 'plugin_backlog']);
const UNESTABLISHED = new Set(['coverage_partial', 'wp_unestablished', 'wp_update_status_unknown', 'wp_version_unknown', 'nexcess_app_version_unknown', 'framework_not_wordpress']);

/* Lane = what happens next for this site. A workflow view over the axes, never a
   third axis: the per-axis statuses stay visible beside it everywhere it is used.
   Priority order is the rule; it is printed in each concept's key. */
function lane(s) {
  if (!s.counts) return 'excluded';
  const hs = s.health.status;
  if (hs === 'SKIP' || hs === 'FROZEN') return 'unmeasurable';
  if (hs === 'CRIT') return 'person';
  if (has(s, 'consent', 'consent_pre_consent_trackers') && !has(s, 'consent', 'consent_no_tooling')) return 'person';
  if (s.f.spf_present === false) return 'person';
  if (hs === 'UNKNOWN') return 'unestablished';
  if (codes(s, 'health').some(c => UNESTABLISHED.has(c))) return 'unestablished';
  if (codes(s, 'health').length) return 'schedule';
  if (s.consent.status === 'WARN' || s.f.dmarc_at_from_present === false || s.f.relaxed_aligned === false
      || D.unreviewed.includes(s.id) || s.decommission_candidate) return 'decide';
  return 'clear';
}
const LANE = {
  person:       { word: 'Needs a person',      sub: 'a measured finding that a person acts on now' },
  unestablished:{ word: 'Not established',     sub: 'looked at, but the maintenance question has no answer yet' },
  schedule:     { word: 'Needs scheduling',    sub: 'a maintenance backlog; the same work on many sites' },
  decide:       { word: 'Needs a ruling',      sub: 'nothing to run until someone decides' },
  clear:        { word: 'Nothing pending',     sub: 'measured, nothing outstanding on either axis' },
  unmeasurable: { word: 'Not measurable',      sub: 'the scan reached the site; there is nothing to measure' },
  excluded:     { word: 'Excluded by ruling',  sub: 'production: false in the inventory; scored, not counted' },
};
const LANE_ORDER = ['person', 'unestablished', 'schedule', 'decide', 'clear', 'unmeasurable', 'excluded'];

/* ---- sparkline (10 points is movement, not a trend; label it that way) ----- */
function spark(series, opts = {}) {
  const w = opts.w || 120, hh = opts.h || 28, pad = 3;
  if (!series || series.length < 2) return h('span', { class: 'abs abs-none' }, 'no history');
  const ys = series.map(p => p[1]);
  const min = Math.min(...ys), max = Math.max(...ys);
  const sx = i => pad + i * (w - 2 * pad) / (series.length - 1);
  const sy = y => max === min ? hh / 2 : pad + (hh - 2 * pad) * (1 - (y - min) / (max - min));
  const pts = ys.map((y, i) => `${sx(i).toFixed(1)},${sy(y).toFixed(1)}`).join(' ');
  const last = ys[ys.length - 1], first = ys[0];
  const dir = last > first ? 'up' : last < first ? 'down' : 'flat';
  const svg = `<svg class="spark spark-${dir}" viewBox="0 0 ${w} ${hh}" width="${w}" height="${hh}" role="img" aria-label="${series.length} runs, ${first} to ${last}">
    <polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cx="${sx(ys.length - 1).toFixed(1)}" cy="${sy(last).toFixed(1)}" r="2.5" fill="currentColor"/></svg>`;
  return h('span', { class: 'sparkwrap', html: svg + `<span class="sparklbl">${first} → ${last}</span>` });
}

/* ---- the site drawer: every recorded fact, labelled by how it was known ----- */
let drawerEl;
function openSite(id) {
  const s = BY_ID[id]; if (!s) return;
  if (!drawerEl) {
    drawerEl = h('div', { class: 'drawer', role: 'dialog', 'aria-modal': 'true' });
    document.body.append(drawerEl);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSite(); });
  }
  drawerEl.innerHTML = '';
  drawerEl.append(renderSite(s));
  drawerEl.classList.add('open');
  document.body.classList.add('drawer-open');
  location.hash = 'site=' + encodeURIComponent(id);
  drawerEl.scrollTop = 0;
  $('.drawer .close').focus();
}
function closeSite() { if (drawerEl) drawerEl.classList.remove('open'); document.body.classList.remove('drawer-open'); if (location.hash.startsWith('#site=')) history.replaceState(null, '', location.pathname + location.search); }

function factRow(label, v, fmt, note) {
  return h('div', { class: 'fr' }, h('dt', {}, label), h('dd', {}, val(v, fmt), note ? h('small', {}, ' ' + note) : null));
}
function yesno(v) { return v === true ? 'yes' : v === false ? 'no' : String(v); }
function renderSite(s) {
  const L = lane(s);
  const ruling = s.production === true ? 'production (ruled)' : s.production === false ? 'not production (ruled)' : 'no ruling — counts as production';
  const nx = s.host === 'CM Nexcess';
  const pending = s.pending || [];
  const wrap = h('div', { class: 'site-detail' },
    h('div', { class: 'sd-head' },
      h('button', { class: 'close', onclick: closeSite, 'aria-label': 'Close' }, '×'),
      h('div', { class: 'sd-name' }, s.id),
      h('div', { class: 'sd-meta' }, [s.host, s.hsn && s.hsn !== s.id ? 'machine name ' + s.hsn : null, ruling, s.in_workbook ? 'in the audit workbook' : 'not in the workbook'].filter(Boolean).join(' · ')),
    ),
    h('div', { class: 'sd-axes' },
      h('div', { class: 'ax' }, h('div', { class: 'axl' }, 'Health — is it maintained?'), chip(s.health.status),
        h('ul', {}, ...(s.health.reasons.length ? s.health.reasons.map(r => h('li', {}, r.text)) : [h('li', { class: 'quiet' }, s.health.status === 'OK' ? 'Nothing pending on what was measured.' : 'No reason recorded.')]))),
      h('div', { class: 'ax' }, h('div', { class: 'axl' }, 'Consent — does it leak trackers?'), chip(s.consent.status),
        h('ul', {}, ...(s.consent.reasons.length ? s.consent.reasons.map(r => h('li', {}, r.text)) : [h('li', { class: 'quiet' }, s.consent.status === 'OK' ? 'No tracker fired before consent on the homepage.' : s.consent.status === 'UNKNOWN' ? (s.f.consent_scan_ok == null ? 'Not in the consent sweep: no domain the sweep could load. Unmeasured, not clean.' : 'The sweep did not load the page (HTTP ' + (s.f.consent_http_status ?? 'unknown') + '). Unmeasured, not clean.') : 'Not measured.')]))),
      h('div', { class: 'ax' }, h('div', { class: 'axl' }, 'What happens next'), h('span', { class: 'lane lane-' + L }, LANE[L].word), h('p', { class: 'quiet' }, LANE[L].sub)),
    ),
    s.info.length ? h('div', { class: 'sd-info' }, h('div', { class: 'axl' }, 'Recorded, not scored'), h('ul', {}, ...s.info.map(t => h('li', {}, t)))) : null,
    s.notes ? h('div', { class: 'sd-note' }, h('div', { class: 'axl' }, 'Inventory note'), h('p', {}, s.notes)) : null,
    s.reconciliation ? h('div', { class: 'sd-note warn' }, h('div', { class: 'axl' }, 'Does not reconcile'), h('p', {}, s.reconciliation)) : null,
    h('div', { class: 'sd-grid' },
      h('section', {}, h('h4', {}, 'Platform', h('small', {}, nx ? ' Nexcess control plane, portal API' : ' Pantheon, terminus')),
        h('dl', {},
          factRow('Plan', s.f.plan), factRow('Environment', s.f.env),
          factRow('PHP (site)', s.f.php_version),
          nx ? factRow('PHP (control plane)', s.f.nexcess_php_version) : null,
          factRow('Last DB backup', s.f.db_backup_age_days, v => v === 0 ? 'today' : v + ' days ago', nx ? 'Nexcess exposes no backup API: unmeasurable here' : null),
          factRow('Upstream commits pending', s.f.upstream_pending),
          factRow('Frozen', s.f.frozen, yesno),
          nx ? factRow('Nexcess state', s.f.nexcess_state) : null,
          nx ? factRow('Nexcess temp domain', s.f.nexcess_temp_domain) : null,
        )),
      h('section', {}, h('h4', {}, 'WordPress', h('small', {}, ' WP-CLI over SSH')),
        h('dl', {},
          factRow('Framework', s.f.framework),
          factRow('Installed version', s.f.wp_version, null, s.f.wp_version && s.f.wp_version !== 'unknown' && cmpVer(s.f.wp_version, D.severity_rules.wp_security_floor) < 0 ? 'below the ' + D.severity_rules.wp_security_floor + ' security floor' : null),
          nx ? factRow('Version (control plane)', s.f.nexcess_app_version) : null,
          factRow('Core update', s.f.wp_core_update),
          factRow('Plugin updates', s.f.plugin_updates), factRow('Theme updates', s.f.theme_updates),
          factRow('Components inventoried', s.f.components_checked, yesno),
        ),
        h('div', { class: 'sd-spark' }, h('span', { class: 'quiet' }, 'Plugin backlog, ' + histSpan(s) + ': '), spark(s.hist.plugins, { w: 200, h: 36 })),
        s.hist.wp.length > 1 && new Set(s.hist.wp.map(p => p[1])).size > 1 ? h('p', { class: 'quiet' }, 'WordPress moved ' + s.hist.wp[0][1] + ' → ' + s.hist.wp[s.hist.wp.length - 1][1] + ' between ' + fmtDay(s.hist.wp[0][0]) + ' and ' + fmtDay(s.hist.wp[s.hist.wp.length - 1][0]) + '.') : null,
      ),
      h('section', {}, h('h4', {}, 'Email DNS', h('small', {}, ' public DNS, no credentials')),
        h('dl', {},
          factRow('Sending domain (ruling)', s.f.recorded_from_domain),
          factRow('Sending domain (measured)', s.f.smtp_from_domain, null, isMeasured(s.f.smtp_from_domain) && isMeasured(s.f.recorded_from_domain) && s.f.smtp_from_domain !== s.f.recorded_from_domain ? 'disagrees with the ruling: every DNS row below is about the ruled domain' : null),
          factRow('Mailer plugin', s.f.smtp_plugin_seen), factRow('Transport', s.f.smtp_transport), factRow('Relay host', s.f.smtp_relay_host),
          factRow('SPF', s.f.spf_present, yesno), factRow('SPF qualifier', s.f.spf_all_qualifier),
          factRow('SPF checked at', s.f.spf_checked_at),
          factRow('DKIM', s.f.dkim_present, yesno), factRow('DKIM selector', s.f.dkim_selector),
          factRow('DMARC at From domain', s.f.dmarc_at_from_present, yesno), factRow('DMARC policy (From)', s.f.dmarc_at_from_policy),
          factRow('DMARC at sending domain', s.f.dmarc_at_sending_present, yesno), factRow('DMARC policy (sending)', s.f.dmarc_at_sending_policy),
          factRow('From aligned with sending', s.f.relaxed_aligned, yesno),
          factRow('DNS host (inventory)', s.dns), factRow('Mail provider (inventory)', s.email_provider),
        )),
      h('section', {}, h('h4', {}, 'Cookie consent', h('small', {}, ' headed Chromium, homepage only')),
        h('dl', {},
          factRow('Page loaded', s.f.consent_scan_ok, yesno), factRow('HTTP status', s.f.consent_http_status),
          factRow('Banner vendor', s.f.consent_banner_vendor), factRow('Banner detected', s.f.consent_banner_detected, yesno),
          factRow('Trackers before consent', s.f.consent_pre_trackers), factRow('Which', s.f.consent_pre_tracker_names),
          factRow('Consent Mode denied by default', s.f.consent_mode_denied, yesno),
          factRow('Final URL', s.f.consent_final_url),
        ),
        h('p', { class: 'quiet' }, 'Hotjar and Meta Pixel decline to fire under automation on some sites, so a tracker count is a floor.')),
      h('section', { class: 'span2' }, h('h4', {}, 'Pending component updates', h('small', {}, ' ' + pending.length + ' from the component inventory')),
        pending.length ? h('table', { class: 'mini' }, h('thead', {}, h('tr', {}, h('th', {}, 'Component'), h('th', {}, 'Type'), h('th', {}, 'Installed'), h('th', {}, 'Available'))),
          h('tbody', {}, ...pending.map(p => h('tr', {}, h('td', { class: 'mono' }, p[0]), h('td', {}, p[1]), h('td', { class: 'mono' }, p[2]), h('td', { class: 'mono' }, p[3] || ''))))) :
          h('p', { class: 'quiet' }, s.f.components_checked === true ? 'Inventoried; nothing pending.' : 'This site was not inventoried, so there is no list. Zero rows is not "nothing pending".')),
      h('section', { class: 'span2' }, h('h4', {}, 'Workbook attestations', h('small', {}, ' a person said so; checked against the component inventory where a plugin can be seen')),
        s.att.length ? h('table', { class: 'mini' }, h('thead', {}, h('tr', {}, h('th', {}, 'Claim'), h('th', {}, 'Workbook value'), h('th', {}, 'Confirmed by'), h('th', {}, 'Inventory evidence'))),
          h('tbody', {}, ...s.att.map(a => h('tr', {}, h('td', {}, a.label), h('td', {}, a.value == null ? val(null) : String(a.value)), h('td', { class: 'quiet' }, a.by || 'nobody here yet (' + (a.source || 'import') + ')'), h('td', {}, attEvidence(a)))))) :
          h('p', { class: 'quiet' }, 'No workbook row for this site.')),
      s.claimed && Object.values(s.claimed).some(v => v) ? h('section', { class: 'span2' }, h('h4', {}, 'What the workbook claimed, beside what was measured'),
        h('dl', {},
          factRow('PHP claimed / measured', null), h('div', { class: 'fr' }, h('dt', {}, 'PHP'), h('dd', {}, claimVsMeasured(s.claimed.php_version, nx ? s.f.nexcess_php_version : s.f.php_version))),
          h('div', { class: 'fr' }, h('dt', {}, 'WordPress'), h('dd', {}, claimVsMeasured(s.claimed.wp_version, s.f.wp_version))),
          h('div', { class: 'fr' }, h('dt', {}, 'Plugins up to date'), h('dd', {}, claimVsMeasured(s.claimed.plugins_utd, isMeasured(s.f.plugin_updates) ? (s.f.plugin_updates === 0 ? 'Yes' : 'No (' + s.f.plugin_updates + ' pending)') : s.f.plugin_updates))),
        )) : null,
    ),
    h('div', { class: 'sd-foot quiet' }, 'Sources that have written this site: ' + (s.sources.join(', ') || 'none') + '.')
  );
  return wrap;
}
function attEvidence(a) {
  const m = { evidence: ['ev-yes', 'plugin active in inventory'], 'no-evidence': ['ev-no', 'claimed yes; no matching plugin in inventory'], 'unclaimed-evidence': ['ev-yes', 'not claimed, but a matching plugin is active'], 'consistent-no': ['ev-na', 'not claimed; no plugin either'], platform: ['ev-na', 'platform control; inventory cannot see it'], 'not-inventoried': ['ev-abs', 'site not inventoried'], 'n/a': ['ev-na', 'not checkable by any scan'] }[a.evidence];
  return h('span', { class: 'ev ' + m[0] }, m[1]);
}
function claimVsMeasured(c, m) {
  const frag = document.createDocumentFragment();
  frag.append(h('span', { class: 'claim' }, c == null ? 'no claim' : String(c)), ' → ', val(m));
  if (c != null && isMeasured(m) && String(c) !== String(m)) frag.append(h('small', { class: 'disagree' }, ' differs'));
  return frag;
}
function histSpan(s) { const p = s.hist.plugins; return p.length > 1 ? p.length + ' runs, ' + fmtDay(p[0][0]) + '–' + fmtDay(p[p.length - 1][0]) : 'history'; }
function cmpVer(a, b) { const pa = String(a).split('.').map(Number), pb = String(b).split('.').map(Number); for (let i = 0; i < 3; i++) { const d = (pa[i] || 0) - (pb[i] || 0); if (d) return d; } return 0; }

/* ---- fleet-level aggregates every concept states ---------------------------- */
const AGG = (() => {
  const c = COUNTED;
  const byLane = {}; for (const s of SITES) (byLane[lane(s)] ||= []).push(s);
  const backlogOnly = c.filter(s => s.health.status === 'WARN' && codes(s, 'health').every(x => BACKLOG.has(x)));
  const warnUnest = c.filter(s => s.health.status === 'WARN' && codes(s, 'health').some(x => UNESTABLISHED.has(x)));
  const pendingSites = SITES.filter(s => (isMeasured(s.f.plugin_updates) && s.f.plugin_updates > 0) || (isMeasured(s.f.theme_updates) && s.f.theme_updates > 0));
  const pluginTotal = SITES.reduce((n, s) => n + (isMeasured(s.f.plugin_updates) ? s.f.plugin_updates : 0), 0);
  const themeTotal = SITES.reduce((n, s) => n + (isMeasured(s.f.theme_updates) ? s.f.theme_updates : 0), 0);
  const inventoried = new Set(D.components.sites_inventoried);
  // history: over the full-run window, per site with >= 2 plugin readings
  let grew = 0, same = 0, shrank = 0, withHist = 0, wpMoved = [];
  for (const s of SITES) {
    const p = s.hist.plugins; if (p.length >= 2) { withHist++; const d = p[p.length - 1][1] - p[0][1]; if (d > 0) grew++; else if (d < 0) shrank++; else same++; }
    const w = s.hist.wp; if (w.length >= 2 && w[0][1] !== w[w.length - 1][1]) wpMoved.push([s.id, w[0][1], w[w.length - 1][1]]);
  }
  const fullRuns = D.all_runs.filter(r => r.source === 'health' && r.mode === 'full' && r.site_count > 3);
  const nexcess = SITES.filter(s => s.host === 'CM Nexcess');
  return { byLane, backlogOnly, warnUnest, pendingSites, pluginTotal, themeTotal, inventoried, grew, same, shrank, withHist, wpMoved,
           histFrom: fullRuns[0]?.observed_at, histTo: fullRuns[fullRuns.length - 1]?.observed_at, fullRunCount: fullRuns.length, nexcess };
})();

/* Newest run per source family, for the sweep line. */
function sweepLine() {
  const L = D.latest;
  const items = [['Pantheon health', L.health], ['Nexcess health', L['health-nexcess']], ['Email DNS', L['email-dns']], ['Consent', L.consent], ['Nexcess estate', L.nexcess]].filter(x => x[1]);
  return items;
}
window.addEventListener('hashchange', () => { const m = location.hash.match(/^#site=(.+)$/); if (m) openSite(decodeURIComponent(m[1])); });
