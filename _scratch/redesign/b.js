/* Concept B — The Evidence Matrix. One row per site, one column per question.
   A cell shows what was measured and how it scored; an absence is hatched and
   never coloured. Statuses come from severity.py's reasons; email columns use
   the standing findings, since email is not a scored axis. */
const inGroup = {}; for (const g of D.standing) inGroup[g.cause] = new Set(g.sites);
const inSet = (cause, id) => inGroup[cause]?.has(id);
const reason = (s, axis, code) => s[axis].reasons.find(r => r.code === code);

const A = (v, text) => ({ state: kind(v) === 'na' ? 'na' : 'abs', text: text || ABSENT_LABEL[kind(v)] });
const G = text => ({ state: 'good', text });
const W = text => ({ state: 'warn', text });
const C = text => ({ state: 'crit', text });
const I = text => ({ state: 'info', text });
const P = text => ({ state: 'plan', text });
const NA = text => ({ state: 'na', text: text || 'n/a' });
const nx = s => s.host === 'CM Nexcess';
const cov = what => { const c = D.coverage.find(x => x.what.startsWith(what)); return c ? [c.known, c.of] : null; };

const COLS = [
  { group: 'Axes', key: 'health', label: 'Health', axis: 'health' },
  { group: 'Axes', key: 'consent', label: 'Consent', axis: 'consent' },
  { group: 'Platform', key: 'backup', label: 'Last DB backup', cov: cov('Pantheon platform'), covLabel: 'Pantheon', cell: s => {
      const r = s.health.reasons.find(x => x.code.startsWith('backup'));
      if (r) return r.level === 'CRIT' ? C(s.f.db_backup_age_days + 'd') : W(s.f.db_backup_age_days + 'd');
      if (isMeasured(s.f.db_backup_age_days)) return G(s.f.db_backup_age_days === 0 ? 'today' : s.f.db_backup_age_days + 'd');
      if (nx(s)) return NA('no API');
      return A(s.f.db_backup_age_days);
    }, title: 'Days since the last database backup. Nexcess exposes no backup API, so there it is unmeasurable, not unmeasured.' },
  { group: 'Platform', key: 'php', label: 'PHP', cov: [SITES.filter(s => isMeasured(s.f.php_version) || isMeasured(s.f.nexcess_php_version)).length, SITES.length], covLabel: 'either source', cell: s => {
      const v = isMeasured(s.f.php_version) ? s.f.php_version : s.f.nexcess_php_version;
      if (reason(s, 'health', 'php_eol')) return C(v + ' EOL');
      if (isMeasured(v)) return s.info.some(t => t.startsWith('PHP')) ? P(v) : G(v);
      return A(v);
    }, title: 'PHP version from WP-CLI, or from the Nexcess control plane when WP-CLI has none. Blue = inside 180 days of end of security support (planning, not scored).' },
  { group: 'WordPress', key: 'wpv', label: 'Installed', cov: [SITES.filter(s => isMeasured(s.f.wp_version)).length, D.components.expected.length], covLabel: 'Pantheon + Nexcess', cell: s => {
      if (reason(s, 'health', 'wp_below_floor')) return C(s.f.wp_version + ' < floor');
      if (reason(s, 'health', 'framework_not_wordpress')) return NA('not WP');
      if (isMeasured(s.f.wp_version)) return G(s.f.wp_version);
      if (reason(s, 'health', 'wp_version_unknown') || reason(s, 'health', 'wp_unestablished')) return W('unread');
      return A(s.f.wp_version);
    }, title: 'The version the site is on, read with wp core version. Below ' + D.severity_rules.wp_security_floor + ' is critical.' },
  { group: 'WordPress', key: 'core', label: 'Core update', cov: [SITES.filter(s => isMeasured(s.f.wp_core_update)).length, D.components.expected.length], covLabel: 'Pantheon + Nexcess', cell: s => {
      if (reason(s, 'health', 'core_update')) return W('→ ' + s.f.wp_core_update);
      if (reason(s, 'health', 'wp_update_status_unknown')) return W('unread');
      if (s.f.wp_core_update === 'up-to-date') return G('current');
      return A(s.f.wp_core_update);
    }, title: 'A pending core release. Warning: schedule it. Not the same as being below the security floor.' },
  { group: 'WordPress', key: 'plugins', label: 'Plugin updates', cov: cov('Component inventory'), covLabel: 'inventoried', cell: s => {
      if (reason(s, 'health', 'plugin_backlog')) return W(String(s.f.plugin_updates));
      if (isMeasured(s.f.plugin_updates)) return s.f.plugin_updates === 0 ? G('0') : I(String(s.f.plugin_updates));
      return A(s.f.plugin_updates);
    }, title: 'Pending plugin updates. Ten or more scores a warning; fewer is recorded and not scored.' },
  { group: 'WordPress', key: 'themes', label: 'Theme updates', cov: cov('Component inventory'), covLabel: 'inventoried', cell: s => isMeasured(s.f.theme_updates) ? (s.f.theme_updates === 0 ? G('0') : I(String(s.f.theme_updates))) : A(s.f.theme_updates), title: 'Pending theme updates. Recorded, never scored.' },
  { group: 'WordPress', key: 'upstream', label: 'Upstream', cov: cov('Pantheon platform'), covLabel: 'Pantheon', cell: s => { if (nx(s)) return NA('n/a'); return isMeasured(s.f.upstream_pending) ? (s.f.upstream_pending === 0 ? G('0') : I(String(s.f.upstream_pending))) : A(s.f.upstream_pending); }, title: 'Pantheon upstream commits not merged. Universal, so it ranks nothing; recorded only.' },
  { group: 'WordPress', key: 'inv', label: 'Inventoried', cov: cov('Component inventory'), covLabel: 'Pantheon + Nexcess', cell: s => {
      if (s.f.components_checked === true) return G(String((s.pending || []).length) + ' pend.');
      if (s.f.components_checked === false) return W('failed');
      return A(s.f.components_checked);
    }, title: 'Whether a plugin, mu-plugin and theme list exists for this site. Zero rows and "runs nothing" are different answers.' },
  { group: 'Consent', key: 'loaded', label: 'Page loaded', cov: cov('Cookie consent'), covLabel: 'domains', cell: s => {
      if (s.f.consent_scan_ok === true) return G('HTTP ' + s.f.consent_http_status);
      if (s.f.consent_scan_ok === false) return { state: 'abs', text: 'HTTP ' + (s.f.consent_http_status ?? '?') };
      return A(s.f.consent_scan_ok, 'not in sweep');
    }, title: 'Did a headed browser get the homepage. A refused page is unmeasured, not clean.' },
  { group: 'Consent', key: 'tooling', label: 'Consent tooling', cov: cov('Cookie consent'), covLabel: 'loaded', cell: s => {
      if (s.f.consent_scan_ok !== true) return A(s.f.consent_scan_ok === false ? 'unknown' : null, s.f.consent_scan_ok === false ? 'unknown' : 'not in sweep');
      if (reason(s, 'consent', 'consent_no_tooling')) return W('none');
      return G(s.f.consent_banner_vendor || 'present');
    }, title: 'Which consent manager the homepage runs, if any.' },
  { group: 'Consent', key: 'pre', label: 'Fire before consent', cov: cov('Cookie consent'), covLabel: 'loaded', cell: s => {
      if (s.f.consent_scan_ok !== true) return A(s.f.consent_scan_ok === false ? 'unknown' : null, s.f.consent_scan_ok === false ? 'unknown' : 'not in sweep');
      const r = reason(s, 'consent', 'consent_pre_consent_trackers');
      if (r) return reason(s, 'consent', 'consent_no_tooling') ? W(String(s.f.consent_pre_trackers)) : C(String(s.f.consent_pre_trackers) + ' w/ banner');
      return G('0');
    }, title: 'Trackers that fired on load before any consent interaction. A floor: some vendors decline to fire under automation. Red when a banner is present and the tags did not wait for it.' },
  { group: 'Email', key: 'spf', label: 'SPF', cov: cov('SPF'), covLabel: 'domains', cell: s => {
      if (s.f.spf_present === true) return G(s.f.spf_all_qualifier || 'yes');
      if (s.f.spf_present === false) return C('none');
      return A(s.f.spf_present);
    }, title: 'SPF at the sending domain the workbook recorded. "unknown" is a lookup that failed, not a missing record.' },
  { group: 'Email', key: 'dkim', label: 'DKIM', cov: cov('DKIM'), covLabel: 'domains', cell: s => s.f.dkim_present === true ? G(s.f.dkim_selector || 'yes') : s.f.dkim_present === false ? C('none') : A(s.f.dkim_present), title: 'DKIM, verified only when the selector is known.' },
  { group: 'Email', key: 'dmarc', label: 'DMARC @From', cov: cov('DMARC'), covLabel: 'domains', cell: s => {
      if (s.f.dmarc_at_from_present === true) return s.f.dmarc_at_from_policy === 'none' ? I('p=none') : G('p=' + s.f.dmarc_at_from_policy);
      if (s.f.dmarc_at_from_present === false) return C('none');
      return A(s.f.dmarc_at_from_present);
    }, title: 'DMARC at the domain recipients see. p=none is monitoring only (recorded, one policy decision covers all of them).' },
  { group: 'Email', key: 'align', label: 'Aligned', cov: cov('DMARC'), covLabel: 'domains', cell: s => s.f.relaxed_aligned === true ? G('yes') : s.f.relaxed_aligned === false ? C('no') : A(s.f.relaxed_aligned), title: 'From domain aligned with the sending domain. DMARC fails on unaligned mail even when SPF and DKIM pass.' },
  { group: 'Email', key: 'from', label: 'Sending domain', cov: cov('Sending domain'), covLabel: 'post-smtp sites', cell: s => {
      const m = s.f.smtp_from_domain, r = s.f.recorded_from_domain;
      if (isMeasured(m)) { if (isMeasured(r) && m !== r) return C('≠ ruling'); return G(m === 'smtp.clevermethod.net' ? 'CM relay' : 'own'); }
      if (kind(m) === 'na') return NA(isMeasured(r) ? 'ruling only' : 'none');
      return A(m);
    }, title: 'The domain the site actually sends from, read off post-smtp, beside the workbook ruling. A disagreement means every DNS cell on this row is about the wrong domain.' },
];
const ATT_COLS = [
  { group: 'Attested', key: 'att_hide_login', label: 'Login hidden', att: 'hide_login' },
  { group: 'Attested', key: 'att_wp_2fa', label: '2FA', att: 'wp_2fa' },
  { group: 'Attested', key: 'att_activity_log', label: 'Activity log', att: 'activity_log' },
  { group: 'Attested', key: 'att_xmlrpc', label: 'XML-RPC off', att: 'xmlrpc_disabled' },
].map(c => ({ ...c, cov: [SITES.filter(s => s.att.some(a => a.key === c.att && a.evidence === 'evidence')).length, SITES.filter(s => s.att.some(a => a.key === c.att)).length], covLabel: 'confirmed of claimed', cell: s => {
  const a = s.att.find(x => x.key === c.att); if (!a) return A(null, 'no row');
  const said = a.value == null ? '—' : String(a.value).replace(/ - .*$/, '').slice(0, 5);
  if (a.evidence === 'evidence') return G(said + ' ✓');
  if (a.evidence === 'no-evidence') return W(said + ' ✗');
  if (a.evidence === 'platform') return NA(said + ' · platform');
  if (a.evidence === 'not-inventoried') return A(null, said + ' · uninv.');
  if (a.evidence === 'unclaimed-evidence') return I(said + ' ✓?');
  return I(said);
}, title: 'What the workbook says beside what the component inventory can see. ✓ a matching plugin is active; ✗ the claim is Yes and no matching plugin is present. Platform controls (Pantheon, Cloudflare WAF) are not checkable here.' }));

const GLY = { crit: '■', warn: '▲', good: '●', info: '·', plan: '◔', abs: '', na: '' };
function cellEl(col, s) {
  if (col.axis) return h('td', { class: 'ax' }, chip(s[col.axis].status));
  const r = col.cell(s);
  return h('td', { class: 'c s-' + r.state, title: col.label + ': ' + r.text + (r.state === 'abs' ? ' — not measured' : r.state === 'na' ? ' — not measurable here' : '') }, r.state in GLY && GLY[r.state] ? h('span', { class: 'g' }, GLY[r.state]) : null, h('span', { class: 't' }, r.text));
}
function census(col) {
  if (col.axis) return h('th');
  const n = { crit: 0, warn: 0, plan: 0, good: 0, info: 0, abs: 0, na: 0 };
  for (const s of SITES) n[col.cell(s).state]++;
  const tot = SITES.length;
  const seg = (k, cls) => n[k] ? h('i', { class: cls, style: 'width:' + (100 * n[k] / tot) + '%', title: k + ' ' + n[k] }) : null;
  return h('th', { title: `critical ${n.crit} · warning ${n.warn} · planning ${n.plan} · measured, nothing pending ${n.good + n.info} · not measured ${n.abs} · not measurable ${n.na}` },
    h('div', { class: 'census-bar' }, seg('crit', 'cb-crit'), seg('warn', 'cb-warn'), seg('plan', 'cb-plan'), seg('info', 'cb-good'), seg('good', 'cb-good'), seg('abs', 'cb-abs'), seg('na', 'cb-na')));
}

let showAtt = false, laneFilter = '', absOnly = false;
const q = h('input', { type: 'search', placeholder: 'Filter sites', 'aria-label': 'Filter sites' });
const hostSel = h('select', {}, h('option', { value: '' }, 'All hosts'), ...[...new Set(SITES.map(s => s.host))].sort().map(x => h('option', { value: x }, x)));
const attBox = h('input', { type: 'checkbox', onchange: e => { showAtt = e.target.checked; draw(); } });
const absBox = h('input', { type: 'checkbox', onchange: e => { absOnly = e.target.checked; draw(); } });
const count = h('span', { class: 'count' });
const mwrap = h('div', { class: 'mwrap' });
q.addEventListener('input', draw); hostSel.addEventListener('change', draw);

function draw() {
  const cols = showAtt ? COLS.concat(ATT_COLS) : COLS;
  const term = q.value.trim().toLowerCase();
  const rows = SITES.filter(s => (!term || s.id.includes(term)) && (!hostSel.value || s.host === hostSel.value) && (!laneFilter || lane(s) === laneFilter)
    && (!absOnly || cols.some(c => !c.axis && ['abs'].includes(c.cell(s).state))));
  const groups = []; let last = null;
  for (const c of cols) { if (c.group !== last) { groups.push({ name: c.group, n: 1 }); last = c.group; } else groups[groups.length - 1].n++; }
  const thead = h('thead', {},
    h('tr', { class: 'groups' }, h('th', { class: 'site' }), ...groups.map(g => h('th', { colspan: g.n }, g.name))),
    h('tr', { class: 'cols' }, h('th', { class: 'site' }, 'Site', h('span', { class: 'cov' }, rows.length + ' of ' + SITES.length)),
      ...cols.map(c => h('th', { title: c.title || '' }, c.label, c.cov ? h('span', { class: 'cov' + (c.cov[0] < c.cov[1] ? ' short' : '') }, c.cov[0] + ' of ' + c.cov[1] + (c.covLabel ? ' ' + c.covLabel : '')) : h('span', { class: 'cov' }, c.axis ? 'scored' : '')))),
    h('tr', { class: 'census' }, h('th', { class: 'site' }, h('span', { class: 'cov' }, 'column census, all ' + SITES.length)), ...cols.map(census)));
  const tbody = h('tbody');
  for (const L of LANE_ORDER) {
    const rs = rows.filter(s => lane(s) === L).sort((a, b) => a.id.localeCompare(b.id));
    if (!rs.length) continue;
    tbody.append(h('tr', { class: 'grp' }, h('th', { colspan: 1 }, LANE[L].word, h('span', { class: 'n' }, rs.length), h('small', {}, LANE[L].sub)), h('td', { colspan: cols.length })));
    for (const s of rs) tbody.append(h('tr', { class: 'row' },
      h('td', { class: 'site' }, h('span', { class: 'nm', tabindex: 0, role: 'button', onclick: () => openSite(s.id), onkeydown: e => { if (e.key === 'Enter') openSite(s.id); } }, s.id), h('span', { class: 'hs' }, s.host.replace('CM ', '') + (s.production === false ? ' · excluded' : '') + (D.unreviewed.includes(s.id) ? ' · no ruling' : ''))),
      ...cols.map(c => cellEl(c, s))));
  }
  mwrap.innerHTML = ''; mwrap.append(h('table', { class: 'matrix' }, thead, tbody));
  count.textContent = rows.length + ' rows · ' + cols.filter(c => !c.axis).length + ' questions';
  $$('.lanes button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lane === laneFilter)));
}

const sweep = sweepLine();
const laneCounts = Object.fromEntries(LANE_ORDER.map(L => [L, SITES.filter(s => lane(s) === L).length]));
const attTotals = (() => {
  const out = [];
  for (const c of ATT_COLS) {
    const n = { evidence: 0, 'no-evidence': 0, platform: 0, 'not-inventoried': 0, 'unclaimed-evidence': 0, 'consistent-no': 0, claimedYes: 0 };
    for (const s of SITES) { const a = s.att.find(x => x.key === c.att); if (!a) continue; if (String(a.value).startsWith('Yes')) n.claimedYes++; n[a.evidence] = (n[a.evidence] || 0) + 1; }
    out.push({ label: c.label, ...n, sites: SITES.filter(s => s.att.some(x => x.key === c.att && x.evidence === 'no-evidence')).map(s => s.id) });
  }
  return out;
})();

$('#app').append(h('div', { class: 'wrap' },
  h('header', { class: 'top' },
    h('div', {}, h('h1', {}, 'clevermethod fleet', h('small', {}, SITES.length + ' sites · ' + (COLS.length - 2) + ' questions · read-only')),
      h('p', { class: 'thesis' }, 'One status per site answers the wrong question. This page shows every question beside every site, so a finding and a gap in coverage are visible in the same glance and can never be confused for each other.')),
    h('div', { class: 'sweep' }, ...sweep.map(([name, r]) => h('div', { class: ageDays(r.observed_at) > 1 ? 'stale' : '' }, name + ' ', h('b', {}, fmtEastern(r.observed_at)), ' ' + (r.deep_scanned ?? '?') + '/' + r.site_count)))),
  h('ul', { class: 'lanes' }, ...LANE_ORDER.map(L => h('li', {}, h('span', { class: 'n' }, laneCounts[L]), h('button', { 'data-lane': L, onclick: () => { laneFilter = laneFilter === L ? '' : L; draw(); } }, LANE[L].word)))),
  h('div', { class: 'tools' }, q, hostSel, h('label', {}, attBox, 'Workbook claims vs inventory'), h('label', {}, absBox, 'Only rows with an unmeasured cell'), count),
  h('ul', { class: 'key' },
    h('li', {}, h('span', { class: 'c s-crit cell' }, '■'), 'critical / risk'), h('li', {}, h('span', { class: 'c s-warn cell' }, '▲'), 'warning: schedule or decide'),
    h('li', {}, h('span', { class: 'c s-plan cell' }, '◔'), 'planning, dated'), h('li', {}, h('span', { class: 'c s-good cell' }, '●'), 'measured, nothing pending'),
    h('li', {}, h('span', { class: 'c s-info cell' }, '·'), 'measured, recorded, not scored'), h('li', {}, h('span', { class: 'c s-abs cell' }), 'not measured — an absence, never a pass'),
    h('li', {}, h('span', { class: 'c s-na cell' }, 'n/a'), 'not measurable on this host'),
    h('li', {}, 'Rows are grouped by what happens next, in priority order: person › not established › schedule › ruling › nothing pending › not measurable › excluded. The two axis chips stay on every row.')),
  mwrap,
  h('div', { class: 'below' },
    h('section', {}, h('h2', {}, 'What the workbook claims, and what the inventory can see'),
      h('p', {}, 'Every attestation was imported from the audit workbook with no confirming person or date. Where a claim names a plugin, the component inventory can confirm it. Toggle the column group above to see it per site.'),
      h('div', { class: 'att-grid' }, ...attTotals.map(a => h('div', { class: 'a' }, h('b', {}, a.label),
        h('span', { class: 'n' }, a.evidence), ' confirmed of ', h('span', { class: 'n' }, a.claimedYes), ' claimed yes', h('br'),
        h('span', { class: 'n ' + (a['no-evidence'] ? 'bad' : '') }, a['no-evidence']), ' claimed with no plugin seen', a.sites.length ? h('small', {}, ' (' + a.sites.join(', ') + ')') : null, h('br'),
        h('span', { class: 'n' }, a['not-inventoried']), ' not inventoried', a.platform ? [h('br'), h('span', { class: 'n' }, a.platform), ' platform control, not checkable'] : null, a['unclaimed-evidence'] ? [h('br'), h('span', { class: 'n' }, a['unclaimed-evidence']), ' not claimed, plugin present anyway'] : null)))),
    h('section', {}, h('h2', {}, 'Since the previous run'),
      h('p', {}, D.changes.filter(c => c.class === 'TRANSITION').length + ' threshold crossing: ' + (D.changes.filter(c => c.class === 'TRANSITION').map(c => c.site + ' ' + c.before + ' → ' + c.after).join('; ') || 'none') + '. ' + D.changes.filter(c => c.class === 'DRIFT').length + ' counters moved on findings already open.'),
      h('p', {}, 'Over the ledger (' + fmtDay(AGG.histFrom.slice(0, 10)) + '–' + fmtDay(AGG.histTo.slice(0, 10)) + '): ' + AGG.wpMoved.length + ' sites moved WordPress version; plugin backlogs grew on ' + AGG.grew + ', held on ' + AGG.same + ', shrank on ' + AGG.shrank + ' of ' + AGG.withHist + '. Movement, not a trend.'),
      h('p', {}, D.coverage_changes.length + ' facts became visible this run (' + D.coverage_changes.map(c => c.fact).join(', ') + ', on ' + D.coverage_changes[0]?.sites.length + ' sites): the instrument changed, not the fleet.'))),
  h('footer', { class: 'foot' },
    h('p', {}, 'Health counts: ' + D.counts.CRIT + ' critical · ' + D.counts.WARN + ' warning · ' + D.counts.OK + ' OK · ' + D.counts.SKIP + ' skip · ' + D.counts.FROZEN + ' frozen, ' + D.excluded_sites.length + ' excluded by ruling (' + D.excluded_sites.join(', ') + '). Consent: ' + D.axes.consent.WARN + ' warning · ' + D.axes.consent.OK + ' OK · ' + D.axes.consent.UNKNOWN + ' unknown. Column headers carry each question\'s own denominator; a census bar under each shows how the whole fleet answers it, hatched where nobody could.'),
    h('p', {}, 'Concept B of three. Times are the ledger\'s UTC stamps shown as Eastern (UTC−4 in August). Generated ' + D.generated + '.'))));
draw();
if (location.hash.startsWith('#site=')) openSite(decodeURIComponent(location.hash.slice(6)));
