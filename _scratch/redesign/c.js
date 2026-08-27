/* Concept C — The Client Brief. One card per site, written for the person who
   talks to the client. Each measured finding is assigned to an actor by a fixed
   mapping printed at the foot of the page: exposed (a client could notice),
   ask the client (a decision only they can make), we handle (agency work),
   not established (nobody has measured it). The mapping is a rule; the
   findings are the model's own. */
const inGroup = {}; for (const g of D.standing) inGroup[g.cause] = new Set(g.sites);
const inSet = (cause, id) => inGroup[cause]?.has(id);
const reason = (s, axis, code) => s[axis].reasons.find(r => r.code === code);
const nx = s => s.host === 'CM Nexcess';

function brief(s) {
  const exp = [], ask = [], we = [], un = [];
  const H = s.health, Cn = s.consent;
  // exposed: measured, and a client or a third party could notice it
  if (reason(s, 'health', 'wp_below_floor')) exp.push('WordPress ' + s.f.wp_version + ' is below the ' + D.severity_rules.wp_security_floor + ' security floor');
  if (reason(s, 'health', 'php_eol')) exp.push('PHP ' + (isMeasured(s.f.php_version) ? s.f.php_version : s.f.nexcess_php_version) + ' stopped receiving security patches (' + D.severity_rules.php_security_eol[isMeasured(s.f.php_version) ? s.f.php_version : s.f.nexcess_php_version] + ')');
  const b = reason(s, 'health', 'backup_stale'); if (b) exp.push(b.text + (s.f.plan === 'Sandbox' ? ' (Sandbox plan: no nightly backup)' : ''));
  if (reason(s, 'consent', 'consent_pre_consent_trackers') && !reason(s, 'consent', 'consent_no_tooling')) exp.push('Consent banner (' + s.f.consent_banner_vendor + ') is present and ' + s.f.consent_pre_tracker_names + ' fired before it');
  if (s.f.spf_present === false) exp.push('No SPF record on the sending domain: mail from it cannot pass SPF');
  if (s.f.dmarc_at_from_present === false) exp.push('No DMARC at ' + s.id + ': nothing protects the brand domain from spoofing');
  if (s.f.relaxed_aligned === false) exp.push('From domain is not aligned with the sending domain' + (isMeasured(s.f.recorded_from_domain) ? ' (' + s.f.recorded_from_domain + ')' : ' (none recorded)') + ': DMARC fails on that mail');
  // ask the client
  if (reason(s, 'consent', 'consent_no_tooling')) ask.push('Is consent tooling in scope? None is on the homepage' + (reason(s, 'consent', 'consent_pre_consent_trackers') ? ', and ' + s.f.consent_pre_tracker_names + ' fires on load' : ''));
  if (s.f.dmarc_at_from_present === true && s.f.dmarc_at_from_policy === 'none') ask.push('DMARC is p=none (monitoring only): move to quarantine or reject?');
  if (D.unreviewed.includes(s.id)) ask.push('Is this a client site or scratch? No owner and no production ruling');
  if (s.decommission_candidate) ask.push('Marked as a decommission candidate' + (s.notes ? ': ' + s.notes : ''));
  else if (s.notes && /\?/.test(s.notes)) ask.push(s.notes);
  if (isMeasured(s.f.smtp_from_domain) && isMeasured(s.f.recorded_from_domain) && s.f.smtp_from_domain !== s.f.recorded_from_domain) ask.push('Which domain does it send from? The site says ' + s.f.smtp_from_domain + ', the workbook says ' + s.f.recorded_from_domain);
  // we handle
  const cu = reason(s, 'health', 'core_update'); if (cu) we.push('WordPress ' + s.f.wp_version + ' → ' + s.f.wp_core_update);
  if (isMeasured(s.f.plugin_updates) && s.f.plugin_updates > 0) we.push(s.f.plugin_updates + ' plugin update' + (s.f.plugin_updates === 1 ? '' : 's') + (reason(s, 'health', 'plugin_backlog') ? ' (over the 10 line)' : ''));
  if (isMeasured(s.f.theme_updates) && s.f.theme_updates > 0) we.push(s.f.theme_updates + ' theme update' + (s.f.theme_updates === 1 ? '' : 's'));
  if (isMeasured(s.f.upstream_pending) && s.f.upstream_pending > 0) we.push(s.f.upstream_pending + ' Pantheon upstream commit' + (s.f.upstream_pending === 1 ? '' : 's') + ' to merge');
  const php = s.info.find(t => t.startsWith('PHP')); if (php) { const m = php.match(/PHP ([\d.]+) leaves security support in (\d+) days \((\S+)\)/); we.push(m ? 'PHP ' + m[1] + ' leaves security support ' + m[3] + ', in ' + m[2] + ' days' : php); }
  // not established
  if (reason(s, 'health', 'coverage_partial')) un.push('no health evidence: backup, plugins, WordPress');
  if (reason(s, 'health', 'framework_not_wordpress')) un.push('not WordPress; control plane disagreed');
  if (reason(s, 'health', 'wp_update_status_unknown') || reason(s, 'health', 'wp_unestablished') || reason(s, 'health', 'wp_version_unknown')) un.push('WordPress update status unread');
  if (s.f.consent_scan_ok === false) un.push('consent: page refused (HTTP ' + (s.f.consent_http_status ?? '?') + ')');
  if (s.f.consent_scan_ok == null && s.in_workbook) un.push('consent: not in sweep');
  if (s.f.spf_present === 'unknown') un.push('SPF lookup failed');
  if (s.f.dkim_present === 'unknown') un.push('DKIM selector unknown');
  if (nx(s) && !isMeasured(s.f.db_backup_age_days)) un.push({ na: true, t: 'backup age: no API on Nexcess' });
  if (s.f.components_checked !== true && !reason(s, 'health', 'coverage_partial') && (H.status !== 'SKIP' && H.status !== 'FROZEN')) un.push('components not inventoried');
  if (H.status === 'SKIP') un.push({ na: true, t: 'no environment to measure' });
  if (H.status === 'FROZEN') un.push({ na: true, t: 'frozen by Pantheon' });
  return { exp, ask, we, un };
}
const BRIEFS = SITES.map(s => ({ s, ...brief(s) }));
// rank: the model's own CRIT level first, then exposure count, then asks, then
// agency work. Ties are ties; nothing is weighted. Exposure count alone put two
// DNS gaps above a 730-day backup gap, which is the ranking this concept is
// most likely to get wrong, so the one severity the model states is honoured.
const critN = x => x.s.health.reasons.filter(r => r.level === 'CRIT').length;
BRIEFS.sort((a, b) => (a.s.counts ? 0 : 1) - (b.s.counts ? 0 : 1) || critN(b) - critN(a) || b.exp.length - a.exp.length || b.ask.length - a.ask.length || b.we.length - a.we.length || a.s.id.localeCompare(b.s.id));
let rank = 0, prevKey = null;
BRIEFS.forEach((x, i) => { const k = (x.s.counts ? 'c' : 'x') + critN(x) + '/' + x.exp.length + '/' + x.ask.length + '/' + x.we.length; if (k !== prevKey) { rank = i + 1; prevKey = k; } x.rank = rank; });

const T = {
  exposed: BRIEFS.filter(x => x.exp.length).length,
  ask: BRIEFS.filter(x => x.ask.length).length,
  we: BRIEFS.filter(x => x.we.length).length,
  un: BRIEFS.filter(x => x.un.some(u => !u.na)).length,
  nothing: BRIEFS.filter(x => !x.exp.length && !x.ask.length && !x.we.length && !x.un.some(u => !u.na)).length,
  askItems: BRIEFS.reduce((n, x) => n + x.ask.length, 0),
  expItems: BRIEFS.reduce((n, x) => n + x.exp.length, 0),
};
const consentAsk = BRIEFS.filter(x => x.ask.some(t => t.startsWith('Is consent tooling'))).length;
const dmarcAsk = BRIEFS.filter(x => x.ask.some(t => t.startsWith('DMARC is p=none'))).length;

const q = h('input', { type: 'search', placeholder: 'Find a site', 'aria-label': 'Find a site' });
const hostSel = h('select', {}, h('option', { value: '' }, 'All hosts'), ...[...new Set(SITES.map(s => s.host))].sort().map(x => h('option', { value: x }, x)));
const only = h('select', {}, h('option', { value: '' }, 'Every site'), h('option', { value: 'exp' }, 'With client-visible exposure'), h('option', { value: 'ask' }, 'Needs the client'), h('option', { value: 'we' }, 'We owe them work'), h('option', { value: 'un' }, 'Something not established'), h('option', { value: 'nothing' }, 'Nothing to tell them'));
const count = h('span', { class: 'count' });
const grid = h('div', { class: 'cards' });
function draw() {
  const term = q.value.trim().toLowerCase();
  const rows = BRIEFS.filter(x => (!term || x.s.id.includes(term)) && (!hostSel.value || x.s.host === hostSel.value) && (!only.value || (
    only.value === 'exp' ? x.exp.length : only.value === 'ask' ? x.ask.length : only.value === 'we' ? x.we.length : only.value === 'un' ? x.un.some(u => !u.na) : (!x.exp.length && !x.ask.length && !x.we.length && !x.un.some(u => !u.na)))));
  grid.innerHTML = '';
  for (const x of rows) grid.append(card(x));
  count.textContent = rows.length + ' of ' + BRIEFS.length + ' sites';
}
q.addEventListener('input', draw); hostSel.addEventListener('change', draw); only.addEventListener('change', draw);
function li(g, t) { return h('li', {}, h('span', { class: 'g' }, g), t); }
function card(x) {
  const s = x.s;
  const nothing = !x.exp.length && !x.ask.length && !x.we.length && !x.un.some(u => !u.na);
  const ruling = s.production === false ? 'excluded by ruling' : s.production === true ? 'production' : 'no production ruling';
  return h('article', { class: 'card' + (x.exp.length ? ' rank-top' : '') + (nothing ? ' nothing' : '') },
    h('div', { class: 'ch' }, h('span', { class: 'nm', role: 'button', tabindex: 0, onclick: () => openSite(s.id), onkeydown: e => { if (e.key === 'Enter') openSite(s.id); } }, s.id),
      h('span', { class: 'meta' }, s.host.replace('CM ', '') + (isMeasured(s.f.plan) ? ' · ' + s.f.plan : '') + ' · ' + ruling),
      h('span', { class: 'chips' }, chip(s.health.status), chip(s.consent.status))),
    x.exp.length ? h('div', { class: 'blk b-exp' }, h('div', { class: 'lbl' }, 'Exposed'), h('ul', {}, ...x.exp.map(t => li('■', t)))) : null,
    x.ask.length ? h('div', { class: 'blk b-ask' }, h('div', { class: 'lbl' }, 'Ask the client'), h('ul', {}, ...x.ask.map(t => li('→', t)))) : null,
    x.we.length ? h('div', { class: 'blk b-we' }, h('div', { class: 'lbl' }, 'We handle'), h('ul', {}, ...x.we.map(t => li('▲', t)))) : null,
    x.un.length ? h('div', { class: 'blk b-un' }, h('div', { class: 'lbl' }, 'Not established'), h('ul', {}, ...x.un.map(u => h('li', { class: u.na ? 'na' : '' }, u.na ? u.t : u)))) : null,
    nothing ? h('div', { class: 'none' }, 'Nothing to tell them.', h('small', {}, 'On what was measured. ' + (s.sources.length ? 'Sources: ' + s.sources.join(', ') + '.' : ''))) : null,
    h('div', { class: 'foot' }, h('span', { class: 'rank' }, 'rank ' + x.rank + ' of ' + BRIEFS.length), h('span', {}, x.exp.length + ' exposed · ' + x.ask.length + ' to ask · ' + x.we.length + ' to do')));
}

const sweep = sweepLine();
$('#app').append(h('div', { class: 'wrap' },
  h('header', { class: 'top' },
    h('div', {}, h('h1', {}, 'What would we tell each client, ', h('em', {}, 'and what do we need from them?')),
      h('p', { class: 'thesis' }, 'A brief per site, ranked by what a client could notice. Maintenance we owe them is listed but never leads; a question only they can answer is separated from work only we can do.'),
      h('p', { class: 'cannot' }, 'The inventory carries no client, owner or contract tier on any of the ' + SITES.length + ' sites (all ' + SITES.length + ' are blank), so this page cannot group sites by account or weight them by value. It ranks by exposure count, and says so on every card.')),
    h('div', { class: 'sweep' }, ...sweep.map(([name, r]) => h('div', { class: ageDays(r.observed_at) > 1 ? 'stale' : '' }, name + ' ', h('b', {}, fmtEastern(r.observed_at)), ' ' + (r.deep_scanned ?? '?') + '/' + r.site_count)))),
  h('div', { class: 'strip' },
    h('div', { class: 's s-exp' }, h('div', { class: 'n' }, T.exposed, h('small', {}, 'of ' + SITES.length)), h('div', { class: 'l' }, 'Client-visible exposure'), h('p', {}, T.expItems + ' measured findings a client or a third party could notice.')),
    h('div', { class: 's s-ask' }, h('div', { class: 'n' }, T.ask, h('small', {}, 'of ' + SITES.length)), h('div', { class: 'l' }, 'Need the client'), h('p', {}, T.askItems + ' questions; ' + consentAsk + ' are the consent-scope question and ' + dmarcAsk + ' the DMARC policy question.')),
    h('div', { class: 's s-we' }, h('div', { class: 'n' }, T.we, h('small', {}, 'of ' + SITES.length)), h('div', { class: 'l' }, 'We owe them work'), h('p', {}, 'Core, plugin, theme or upstream updates, or the PHP 8.2 wave. Never an emergency on its own.')),
    h('div', { class: 's s-un' }, h('div', { class: 'n' }, T.un, h('small', {}, 'of ' + SITES.length)), h('div', { class: 'l' }, 'Something not established'), h('p', {}, 'A question nobody has been able to measure. Not counted as clean; ' + T.nothing + ' sites have nothing to tell on what was measured.'))),
  h('div', { class: 'tools' }, q, hostSel, only, count),
  h('p', { class: 'rule' }, 'Order: sites excluded by ruling last; otherwise a critical health finding first, then most exposed, then most to ask, then most to do; ties share a rank. Red-edged cards carry at least one client-visible exposure. Hatched tokens are absences, and a card with no red block has been measured clean only on the questions the scans could ask.'),
  grid,
  h('section', { class: 'mapping' }, h('h2', {}, 'How a finding is assigned to an actor'),
    h('dl', {},
      h('dt', {}, 'Exposed'), h('dd', {}, 'WordPress below the security floor; PHP past end of support; no database backup in over 30 days; a consent banner present while trackers fire before it; no SPF record; no DMARC at the From domain; From domain not aligned with the sending domain. All measured, all from severity.py or the standing findings.'),
      h('dt', {}, 'Ask the client'), h('dd', {}, 'No consent tooling on the homepage (a scope decision); DMARC at p=none (a policy decision); no owner and no production ruling; a decommission flag or an open question in the inventory note; the site\'s measured sending domain disagreeing with the workbook.'),
      h('dt', {}, 'We handle'), h('dd', {}, 'A pending core release; pending plugin and theme updates, whatever the count; unmerged Pantheon upstream commits; the dated PHP 8.2 wave.'),
      h('dt', {}, 'Not established'), h('dd', {}, 'No health evidence; WordPress status unread; the consent sweep refused or never attempted; an SPF or DKIM lookup that failed; components not inventoried. Dotted tokens are things no scan can measure on that host, which is a different fact.'))),
  h('footer', { class: 'foot-page' },
    h('p', {}, 'Health: ' + D.counts.CRIT + ' critical · ' + D.counts.WARN + ' warning · ' + D.counts.OK + ' OK · ' + D.counts.SKIP + ' skip · ' + D.counts.FROZEN + ' frozen · ' + D.excluded_sites.length + ' excluded by ruling. Consent: ' + D.axes.consent.WARN + ' warning · ' + D.axes.consent.OK + ' OK · ' + D.axes.consent.UNKNOWN + ' unknown. The same findings, arranged by who has to act.'),
    h('p', {}, 'Concept C of three. Times are the ledger\'s UTC stamps shown as Eastern (UTC−4 in August). Generated ' + D.generated + ' from ' + D.all_runs.length + ' runs.'))));
draw();
if (location.hash.startsWith('#site=')) openSite(decodeURIComponent(location.hash.slice(6)));
