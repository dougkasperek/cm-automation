/* Fleet dashboard page script. Inlined into fleet.html by render-dashboard.py.
   Renders from the JSON the renderer embeds; computes groupings and counts only.
   Statuses and reasons are severity.py's. */
/* Shared helpers. Nothing here computes a status: statuses
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
function val(v, fmt, absentWord) {
  const k = kind(v);
  // absentWord: a ruling that nobody typed is "not recorded", not "not scanned".
  if (k !== 'value') return h('span', { class: 'abs abs-' + k, title: absenceTitle(k) }, (k === 'none' && absentWord) || ABSENT_LABEL[k]);
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
  // ledger stamps are UTC. The renderer supplies the Eastern offset for the
  // generation date (tz_offset_minutes), so DST is decided in one place.
  const d = new Date(iso + 'Z');
  const e = new Date(d.getTime() + (D.tz_offset_minutes || 0) * 60 * 1000);
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
   Priority order is the rule; it is printed in the key. */
function lane(s) {
  if (!s.counts) return 'excluded';
  const hs = s.health.status;
  if (hs === 'SKIP' || hs === 'FROZEN') return 'unmeasurable';
  if (hs === 'CRIT') return 'person';
  if (has(s, 'consent', 'consent_pre_consent_trackers') && !has(s, 'consent', 'consent_no_tooling')) return 'person';
  /* A tag still firing after a REAL Reject All click. Stronger than the rule
     above it: that one is about a site that fires before anyone chose, which
     an opt-out model can justify; this is a visitor who explicitly refused and
     is tracked anyway, which nothing justifies. No tooling exemption for the
     same reason -- a site with no banner cannot produce this row at all, since
     the sweep has nothing to click. Grouping only; severity.py decided it. */
  if (has(s, 'consent', 'consent_gating_leak')) return 'person';
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
  /* PLAIN WORDS. Doug, 2026-08-31, reading the card: "this section/title is
     confusing, it introduces MAINTENANCE QUESTION, what is that to a new
     user?" Both halves were this page's own vocabulary. Say what was and
     was not read instead of naming an abstraction. */
  unestablished:{ word: 'Nothing measured yet', sub: 'a scan reached the site but read nothing about its upkeep: no backup age, no plugin or theme count' },
  schedule:     { word: 'Needs scheduling',    sub: 'a maintenance backlog; the same work on many sites' },
  decide:       { word: 'Needs a ruling',      sub: 'nothing to run until someone decides' },
  clear:        { word: 'Nothing pending',     sub: 'measured, nothing outstanding on either axis' },
  unmeasurable: { word: 'Not measurable',      sub: 'the scan reached the site; there is nothing to measure' },
  excluded:     { word: 'Excluded by ruling',  sub: 'production: false in the inventory; scored, not counted' },
};
const LANE_ORDER = ['person', 'unestablished', 'schedule', 'decide', 'clear', 'unmeasurable', 'excluded'];

/* FOUR CARDS OVER SEVEN LANES. Doug's concept, 2026-08-29: seven equal tiles
   ask a reader to hold seven things; the cards say what kind of answer each
   group is. Display only -- severity.py decides status, lane() decides lane,
   and this decides nothing at all.

   TWO GROUPINGS IN THE CONCEPT WERE FALSE and are not here; both are in
   CLAUDE.md's bug table:

   - `unestablished` was drawn inside a "planning / decision pending" card
     reading "work must be scheduled, defined, or ruled on". On those sites
     NOTHING IS KNOWN -- the lane is health.status UNKNOWN, or coverage_partial
     and framework_not_wordpress. There is no work to schedule and nothing to
     rule on. An absence folded into a backlog is this repo's cardinal bug, so
     it gets its own card and is never merged upward.
   - `unmeasurable` + `excluded` were drawn as "Not scored". All five ARE
     scored: SKIP and FROZEN are severity statuses, and `excluded` means
     "scored, NOT COUNTED" -- cm-whitelabel was CRIT with three findings on the
     day the card claimed the tool could produce no result for it. They are a
     quiet line under the cards, worded as what they are.

   Each card's gloss defines EVERY lane inside it. A chip carrying one of this
   page's invented lane words with no definition beside it is the 2026-08-28
   bug again, one level down. */
const GROUPS = [
  { key: 'act',      word: 'Needs a person',        lanes: ['person'],
    sub: 'a measured finding that a person acts on now: health critical, a tag that fires after a rejection, or no SPF' },
  { key: 'planning', word: 'Planning and decisions', lanes: ['schedule', 'decide'],
    sub: 'measured, and waiting on a person rather than a scan. Needs scheduling is a maintenance backlog, the same work on many sites; Needs a ruling has nothing to run until someone decides' },
  { key: 'unknown',  word: 'Nothing measured yet',  lanes: ['unestablished'],
    sub: 'a scan reached the site but read nothing about its upkeep: no backup age, no plugin or theme count. An absence, never a pass, and never counted as a backlog' },
  { key: 'clear',    word: 'Nothing pending',       lanes: ['clear'],
    sub: 'measured, nothing outstanding on either axis: health and consent both' },
];
/* Not a card. Neither is news, and neither is unscored: SKIP and FROZEN are
   statuses, and an excluded site is scored and left out of the fleet totals. */
const ASIDE_LANES = ['unmeasurable', 'excluded'];

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

function factRow(label, v, fmt, note, absentWord) {
  return h('div', { class: 'fr' }, h('dt', {}, label), h('dd', {}, val(v, fmt, absentWord), note ? h('small', {}, ' ' + note) : null));
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
        h('ul', {}, ...(s.health.reasons.length ? s.health.reasons.map(r => h('li', {}, r.text, h('code', { class: 'rc' }, ' ' + r.code))) : [h('li', { class: 'quiet' }, s.health.status === 'OK' ? 'Nothing pending on what was measured.' : 'No reason recorded.')]))),
      h('div', { class: 'ax' }, h('div', { class: 'axl' }, 'Consent — does it leak trackers?'), chip(s.consent.status),
        h('ul', {}, ...(s.consent.reasons.length ? s.consent.reasons.map(r => h('li', {}, r.text, h('code', { class: 'rc' }, ' ' + r.code))) : [h('li', { class: 'quiet' }, s.consent.status === 'OK' ? 'No tracker fired before consent on the homepage.' : s.consent.status === 'UNKNOWN' ? (s.f.consent_scan_ok == null ? 'Not in the consent sweep: no domain the sweep could load. Unmeasured, not clean.' : 'The sweep did not load the page (HTTP ' + (s.f.consent_http_status ?? 'unknown') + '). Unmeasured, not clean.') : 'Not measured.')]))),
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
          factRow('Sending domain (ruling)', s.f.recorded_from_domain, null, null, 'not recorded'),
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
          factRow('Consent model (ruling)', s.f.consent_model, null, null, 'not recorded'),
          factRow('Consent managed by CM (ruling)', s.f.consent_managed, yesno, null, 'not recorded'),
          factRow('Consent note (ruling)', s.f.consent_note, null, null, 'none'),
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

/* ---- fleet-level aggregates ------------------------------------------------ */
const AGG = (() => {
  const c = COUNTED;
  const byLane = {}; for (const s of SITES) (byLane[lane(s)] ||= []).push(s);
  const backlogOnly = c.filter(s => s.health.status === 'WARN' && codes(s, 'health').every(x => BACKLOG.has(x)));
  /* The two halves, named once. The Schedule panel used to recompute this
     filter three times in one sentence, and the Schedule tab lists BOTH
     halves -- a backlog site that needs a person for some other reason is
     still a scheduling decision. Splitting it here is what lets the panel
     say so instead of claiming those sites are only in the matrix. */
  const backlogScheduled = backlogOnly.filter(s => lane(s) === 'schedule');
  const backlogElsewhere = backlogOnly.filter(s => lane(s) !== 'schedule');
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
  return { byLane, backlogOnly, backlogScheduled, backlogElsewhere, warnUnest, pendingSites, pluginTotal, themeTotal, inventoried, grew, same, shrank, withHist, wpMoved,
           histFrom: fullRuns[0]?.observed_at, histTo: fullRuns[fullRuns.length - 1]?.observed_at, fullRunCount: fullRuns.length, nexcess };
})();

/* Newest run per source family, for the sweep line. */
function sweepLine() {
  const L = D.latest;
  /* EVERY source that has run, not a hand-picked five. `vuln-intel` and
     `consent-gating` were both missing until 2026-09-01 -- each had run, each
     has its own page linked from the masthead, and neither said when it last
     looked. Same family as the masthead's "3 tools feeding one ledger" over
     four sources: a list of instruments that quietly omits one lets a stale
     source read as a current one, which is the single thing this strip exists
     to prevent. The .filter keeps a source with no runs off the strip; the
     coverage box is where a never-run source is named. */
  const items = [['Pantheon health', L.health], ['Nexcess health', L['health-nexcess']], ['Email DNS', L['email-dns']], ['Consent', L.consent], ['Consent gating', L['consent-gating']], ['Vulnerabilities', L['vuln-intel']], ['Nexcess estate', L.nexcess]].filter(x => x[1]);
  return items;
}
window.addEventListener('hashchange', () => { const m = location.hash.match(/^#site=(.+)$/); if (m) openSite(decodeURIComponent(m[1])); });

/* The page: the evidence matrix, with the schedule view as a second tab, over one
   drawer and one dataset. One row per site, one column per question.
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
      if (s.f.wp_core_update === 'up-to-date') return G('up-to-date');
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
  { group: 'WordPress', key: 'vuln', label: 'Vulnerable', href: '/vulnerabilities', cov: cov('Known vulnerabilities'), covLabel: 'matched', cell: s => {
      /* Absence FIRST. A site with no component inventory cannot be matched at
         all, and on this axis "no findings" is the best possible result -- so
         an unmatched site rendered as a green 0 would read as the cleanest
         site on the fleet. 17 of 85 were unmatchable on 2026-08-31. */
      /* TWO different absences, and both must carry a WORD. `vuln_checked`
         false is a measured fact -- the matcher ran and this site has no
         component inventory to match -- so kind() calls it a value and
         ABSENT_LABEL has no entry for it; A(false) with no text renders an
         EMPTY cell, which is the worst of the three since it reads as
         nothing to report. Found by reading the rendered column, where most
         of the fleet came out blank. (Avoid writing a digit followed by the
         word site in this file even in a comment: the typed-count guard in
         test-page.py scans quoted spans and cannot tell the two apart.) */
      if (s.f.vuln_checked === false) return A(null, 'not checked');
      if (s.f.vuln_checked !== true) return A(s.f.vuln_checked);
      if (reason(s, 'health', 'vuln_critical')) return C(String(s.f.vuln_worst_cvss));
      if (reason(s, 'health', 'vuln_no_fix')) return W(String(s.f.vuln_nofix) + ' no fix');
      /* Findings that a normal update closes are NOT a warning here: they are
         the plugin backlog in the column two along, and colouring them twice
         would report one backlog as two problems. */
      if (isMeasured(s.f.vuln_affected) && s.f.vuln_affected > 0)
        return I(String(s.f.vuln_affected) + ' fixable');
      /* "0 known", never "clear". Wordfence not having published an advisory
         is not evidence a component is sound. */
      return G('0 known');
    }, title: 'Known vulnerabilities from the Wordfence feed, matched against the installed component versions. Red = something critical or with no fix; blue = findings a normal update closes, already counted as the plugin backlog. See /vulnerabilities.' },
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
/* THE WORKBOOK IS NOT A COLUMN GROUP ANY MORE. Removed 2026-08-29.
   It was on this page four times: a paragraph in the key, four columns behind
   a checkbox, the site drawer's "Workbook attestations" table, and the totals
   section below the matrix. The drawer beats the columns outright -- it
   carries a "Confirmed by" cell that renders "nobody here yet (import)" in
   place, which is exactly what the key paragraph was saying in prose, said
   where the claim is. The totals section names the only rows anyone acts on
   (a claim with no matching plugin). Two copies were doing no work and one of
   them cost a paragraph of key.
   These four survive because the totals section still counts over them; they
   are no longer matrix columns, so they carry no cell(), cov or title. */
const ATT_COLS = [
  { label: 'Login hidden', att: 'hide_login' },
  { label: '2FA', att: 'wp_2fa' },
  { label: 'Activity log', att: 'activity_log' },
  { label: 'XML-RPC off', att: 'xmlrpc_disabled' },
];

const GLY = { crit: '■', warn: '▲', good: '●', info: '·', plan: '◔', abs: '', na: '' };
function cellEl(col, s) {
  if (col.axis) return h('td', { class: 'ax' }, chip(s[col.axis].status));
  const r = col.cell(s);
  return h('td', { class: 'c s-' + r.state, title: col.label + ': ' + r.text + (r.state === 'abs' ? ' — not measured' : r.state === 'na' ? ' — not measurable here' : '') }, r.state in GLY && GLY[r.state] ? h('span', { class: 'g' }, GLY[r.state]) : null, h('span', { class: 't' }, r.text));
}
/* THE CENSUS BAR ROW IS GONE. Removed 2026-08-29.
   A seven-segment stacked bar under every column header, computed over the
   whole fleet and never following the filter, whose only legend was a title=
   tooltip (needs a mouse) and one clause in a footer 3,800px below the row it
   explained. Every fact it summarised is still stated in place: the column
   header carries its own denominator, and each of the 85 cells carries its own
   state. What went with it was an explanation nobody could reach from the
   thing being explained. */

let laneFilter = [], absOnly = false;   // a card selects several lanes, a chip one
const sameFilter = a => a.length === laneFilter.length && a.every(x => laneFilter.includes(x));
const q = h('input', { type: 'search', placeholder: 'Filter sites', 'aria-label': 'Filter sites' });
const hostSel = h('select', {}, h('option', { value: '' }, 'All hosts'), ...[...new Set(SITES.map(s => s.host))].sort().map(x => h('option', { value: x }, x)));
const absBox = h('input', { type: 'checkbox', onchange: e => { absOnly = e.target.checked; draw(); syncUrl(); } });
const count = h('span', { class: 'count' });
const mwrap = h('div', { class: 'mwrap' });
q.addEventListener('input', () => { draw(); syncUrl(); }); hostSel.addEventListener('change', () => { draw(); syncUrl(); });
/* Every filter state is a URL, so a pasted link means the same view. */
function syncUrl() {
  const u = new URLSearchParams();
  if (view === 'schedule') u.set('view', 'schedule');
  if (hostSel.value) u.set('host', hostSel.value);
  if (laneFilter.length) u.set('lane', laneFilter.join(','));
  if (q.value.trim()) u.set('q', q.value.trim());
  if (absOnly) u.set('unmeasured', '1');
  const qs = u.toString();
  history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
}
function readUrl() {
  const u = new URLSearchParams(location.search);
  if (u.get('host')) hostSel.value = u.get('host');
  // Every named lane must exist, or the filter silently matches nothing and
  // the page looks like an empty fleet.
  if (u.get('lane')) { const ls = u.get('lane').split(',').filter(x => LANE[x]); if (ls.length) laneFilter = ls; }
  if (u.get('q')) q.value = u.get('q');
  if (u.get('unmeasured') === '1') { absOnly = true; absBox.checked = true; }
}

function draw() {
  const cols = COLS;
  const term = q.value.trim().toLowerCase();
  const rows = SITES.filter(s => (!term || s.id.includes(term)) && (!hostSel.value || s.host === hostSel.value) && (!laneFilter.length || laneFilter.includes(lane(s)))
    && (!absOnly || cols.some(c => !c.axis && ['abs'].includes(c.cell(s).state))));
  const groups = []; let last = null;
  for (const c of cols) { if (c.group !== last) { groups.push({ name: c.group, n: 1 }); last = c.group; } else groups[groups.length - 1].n++; }
  const thead = h('thead', {},
    h('tr', { class: 'groups' }, h('th', { class: 'site' }), ...groups.map(g => h('th', { colspan: g.n },
      g.name === 'Consent'
        // These three columns are all the matrix can hold. Whether the tags
        // stop when a visitor REJECTS is per tracker per pass, so it lives on
        // its own page -- and the route to it belongs here, where a reader is
        // already looking at consent, not only in the footer.
        ? h('a', { href: '/consent', title: 'Consent detail: what fires on load, what still fires after Reject All, who manages each site' }, g.name)
        : g.name))),
    h('tr', { class: 'cols' }, h('th', { class: 'site' }, 'Site', h('span', { class: 'cov' }, rows.length + ' of ' + SITES.length)),
      // A column may carry its own route. The Consent GROUP links out because
      // all three of its columns share one page; Vulnerable is one column
      // inside WordPress, so the link belongs on the column and linking the
      // whole group would point four unrelated columns at it.
      ...cols.map(c => h('th', { title: c.title || '' },
        c.href ? h('a', { href: c.href }, c.label) : c.label, c.cov ? h('span', { class: 'cov' + (c.cov[0] < c.cov[1] ? ' short' : '') }, c.cov[0] + ' of ' + c.cov[1] + (c.covLabel ? ' ' + c.covLabel : '')) : h('span', { class: 'cov' }, c.axis ? 'scored' : '')))));
  const tbody = h('tbody');
  for (const L of LANE_ORDER) {
    const rs = rows.filter(s => lane(s) === L).sort((a, b) => a.id.localeCompare(b.id));
    if (!rs.length) continue;
    /* The gloss is on the TILE, not here as well. Both rendered LANE[L].sub
       verbatim, ~600px apart. The tiles are the copy that has to keep it: they
       are what a reader meets first, and test-page.mjs pins them unfolded for
       that reason. */
    tbody.append(h('tr', { class: 'grp' }, h('th', { colspan: 1 }, LANE[L].word, h('span', { class: 'n' }, rs.length)), h('td', { colspan: cols.length })));
    for (const s of rs) tbody.append(h('tr', { class: 'row' },
      h('td', { class: 'site' }, h('span', { class: 'nm', tabindex: 0, role: 'button', onclick: () => openSite(s.id), onkeydown: e => { if (e.key === 'Enter') openSite(s.id); } }, s.id), h('span', { class: 'hs' }, s.host.replace('CM ', '') + (s.production === false ? ' · excluded' : '') + (D.unreviewed.includes(s.id) ? ' · no ruling' : ''))),
      ...cols.map(c => cellEl(c, s))));
  }
  mwrap.innerHTML = ''; mwrap.append(h('table', { class: 'matrix' }, thead, tbody));
  count.textContent = rows.length + ' rows · ' + cols.filter(c => !c.axis).length + ' questions';
  $$('.lanes [data-lanes]').forEach(b => b.setAttribute('aria-pressed', String(sameFilter(b.dataset.lanes.split(',')))));
}

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


let view = 'matrix';
const tabs = h('div', { class: 'tabs', role: 'tablist' },
  h('button', { role: 'tab', 'aria-selected': 'true', 'data-v': 'matrix', onclick: () => setView('matrix') }, 'Evidence'),
  h('button', { role: 'tab', 'aria-selected': 'false', 'data-v': 'schedule', onclick: () => setView('schedule') }, 'Schedule', h('small', {}, col2.length + ' decisions · ' + AGG.backlogOnly.length + ' backlog sites')));
function setView(v) {
  view = v;
  $$('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.v === v)));
  $('#view-matrix').hidden = v !== 'matrix'; $('#view-schedule').hidden = v !== 'schedule';
  syncUrl();
}
/* The "do I need to worry" line. Three states and the predicate is printed under
   each: green needs zero sites in the needs-a-person lane AND no coverage
   regression; a coverage drop or a source that did not run reads "can't say",
   never green, never amber. The scanner losing sight of a site must not look
   like the fleet getting better. */
/* One regression, as a sentence a person can read. Deliberately names the
   source and both numbers: "fewer" without the pair is the same sentence
   whether one site or forty went missing. */
function coverageDropPhrase(r) {
  const src = r.source || r.run_id || 'a source';
  const now = r.deep_scanned, was = r.previous_deep_scanned, of = r.site_count;
  if (typeof now !== 'number' || typeof was !== 'number') {
    return src + ' measured fewer sites than last run';
  }
  return src + ' measured ' + now + (typeof of === 'number' ? ' of ' + of : '')
       + ', down from ' + was;
}

function banner() {
  const person = SITES.filter(s => lane(s) === 'person');
  /* A site whose health status CROSSED into CRIT on this run. Read off the
     change rows the ledger already computed, so the page adds no history of
     its own. With no change rows there is nothing to compare and the headline
     says nothing about newness rather than claiming "none". */
  const becameCrit = new Set(D.changes
    .filter(c => c.fact === 'status' && c.after === 'CRIT')
    .map(c => c.site));
  const personNew = person.filter(s => becameCrit.has(s.id));
  const regressAll = D.coverage_regressions || [];
  /* A drop a person acknowledged when the run was ingested is not an
     unexplained one. On 2026-09-01 three Pantheon sites were deleted, the run
     measured 47 against 48, the operator dispatched with allow_coverage_drop
     -- and this banner still read "Can't say ... nothing here is green until
     it is explained", over a drop that HAD been explained. The flag reached
     the publisher and never reached the page.
     Split, not filtered: an expected drop is still said out loud, with its
     numbers, in the line under the lanes. What it no longer does is hold the
     whole page at "Can't say". An acknowledgement that made a regression
     invisible would be a way of hiding one. */
  const regress = regressAll.filter(r => !r.expected);
  const regressOk = regressAll.filter(r => r.expected);
  const runs = sweepLine();
  const oldest = runs.reduce((a, b) => (a[1].observed_at < b[1].observed_at ? a : b));
  const newest = runs.reduce((a, b) => (a[1].observed_at > b[1].observed_at ? a : b));
  /* NOT the per-source fractions again. Until 2026-08-29 this appended
     `(Pantheon health 48/52, Nexcess health 21/22, ...)` -- the same
     sweepLine() runs the sweep strip renders 40px directly above, which also
     carries each run's timestamp and its stale marker. Two copies of one
     fact, and the banner held the worse one. The date range stays because
     the strip does not state it. */
  const basis = 'on scans from ' + fmtDay(oldest[1].observed_at.slice(0, 10)) + ' to ' + fmtDay(newest[1].observed_at.slice(0, 10));
  const backlog = AGG.backlogOnly.length;
  let state, head, sub;
  if (regress.length) {
    state = 'cant'; head = "Can't say";
    /* SAY WHAT DROPPED, IN WORDS. This read `r.what || JSON.stringify(r)`
       until 2026-08-28. `what` is a key on D.coverage -- the coverage box --
       and NOT on a regression record, whose keys are source, deep_scanned,
       site_count, previous_deep_scanned and previous_run_id. So the fallback
       fired every time and the fleet banner printed a raw JSON object into
       user-facing copy:

         Can't say - Coverage fell since the previous run ({"source":"consent",
         "run_id":"consent-2026-08-28_1613","deep_scanned":71,...

       Latent since the banner was written: no coverage regression had ever
       reached a rendered page, because the guard blocks the publish. It took
       running four scans in one afternoon to see it. A `||` fallback that
       hides a wrong key is the same shape as `${pj:-[]}` turning four failed
       WP-CLI calls into "runs nothing". */
    sub = 'Coverage fell since the previous run (' + regress.map(coverageDropPhrase).join('; ') + '). A scan that saw fewer sites is not a fleet that got better; nothing here is green until it is explained.'
      + (person.length ? ' On what WAS measured, ' + person.length + ' site' + (person.length === 1 ? '' : 's') + ' need' + (person.length === 1 ? 's' : '') + ' a person: ' + person.map(s => s.id).join(', ') + '.' : '');
  } else if (person.length) {
    state = 'red';
    /* WHAT CHANGED, NOT JUST WHAT IS STANDING. Measured 2026-08-31: the
       vulnerability rules roughly tripled this lane, and the CRITs that did it
       sit on advisories with a MEDIAN AGE OF 86 DAYS, the oldest 857. A
       red headline counting sites that need a person, over a months-old backlog
       is the same defect the vulnerability page was rewritten for: a page that
       would have said the same thing every day for two years is not an alert,
       it is the page's permanent state.
       The severity is right -- a site running a two-year-old unpatched RCE IS
       critical, and demoting it by age would be worse. What was wrong is the
       framing, so the headline now separates the two. */
    /* THE HEADLINE DOES NOT REPEAT THE CARD. Doug, 2026-08-31: "let the card
       do its job, no need to repeat it as a banner" -- the head printed the
       lane count and the word, directly above a card printing the same count
       and the same word. The card owns the count; the headline owns the
       thing no card can say, which is what is DIFFERENT since the last look.
       The names stay in the sub: a test asserts every id in the lane appears
       in the banner prose, added after an earlier check claimed to verify
       names and never tested one. */
    head = personNew.length
      ? personNew.length + ' site' + (personNew.length === 1 ? '' : 's')
        + ' newly need' + (personNew.length === 1 ? 's' : '') + ' a person'
      /* NOT "no new problems": that sat as reassuring copy inside a RED block,
         and the colour and the words contradicted each other before a reader
         got as far as the names. The clause after the dash is what justifies
         the red without restating the card's number. */
      : D.changes.length
        ? 'Nothing new since the last run \u2014 the sites below still need a person'
      : 'Sites need a person';
    /* NO "everything else is a backlog (N sites), a ruling, or unmeasured (M
        sites)" HERE. The lane strip is inside this banner now and says it
        better: it counts the rulings rather than saying "a ruling", and it
        names three lanes the sentence never mentioned. Worse, the two numbers
        were NOT the lanes below them -- `backlog` is backlogOnly (42) against
        a schedule lane of 41, and `unmeasured` is no_health_evidence, which on
        2026-08-29 was ELEVEN, exactly like the "Not established" lane beside
        it, over a different set of sites: it holds elderwoodipa.com, which is
        in "needs a person", and not app.eastauroracc.com, which is not. Two
        figures that agree by coincidence are the ones nobody catches.
        The green branch keeps its sentence -- see below. */
    sub = (personNew.length
        ? 'New: ' + personNew.map(s => s.id).join(', ') + '. Also outstanding: '
          + person.filter(s => !becameCrit.has(s.id)).map(s => s.id).join(', ')
        : person.map(s => s.id).join(', '))
      + '. Based ' + basis + '.';
  } else {
    state = 'green'; head = 'Nothing needs a person';
    /* THIS SENTENCE STAYS, unlike the red branch's. In the red state the
       headline names a problem, so nothing is at risk of reading as an
       all-clear; in the green state this sentence IS the safeguard, and
       test-page.mjs pins its shape for that reason. It is the answer to the
       two-word reassurance the dev team asked for and this fleet cannot
       honestly give -- a phrase this file must not contain, in copy OR in a
       comment, because page.js is embedded verbatim in the rendered HTML and
       the guard scans the whole page. */
    /* ONE FIGURE, NOT TWO. This sentence used to carry the coverage count as
       well -- "and 11 have never had health measured" -- printed directly
       above a "Not established" chip that was 11 in the red state over a
       DIFFERENT set of sites and 12 in the green state over a nested one.
       Measured both ways on 2026-08-29. It was the last surviving instance of
       the thing the 2026-08-29 merge existed to remove: a prose number beside
       a lane count from another source. The coverage count now has its own
       line in coverageLine(), inside this same block, next to its own
       definition and its split by lane -- so it renders in EVERY state, not
       only the one this fleet has never been in. */
    sub = backlog + ' sites carry a maintenance backlog; none of it needs anyone today. Based ' + basis + '.';
  }
  /* ONE BLOCK, NOT TWO. The banner and the lane strip were stacked boxes both
     summarising the same fleet, and the banner's prose restated the strip in
     numbers that were NOT the strip's -- see the red branch above. They are one
     statement: the headline is a claim about the "needs a person" lane, which
     is literally what the predicate underneath says. Doug, looking at the two
     of them: "can we combine these?" */
  return h('div', { class: 'banner banner-' + state, role: 'status' },
    h('div', { class: 'bn-head' }, h('span', { class: 'bn-glyph', 'aria-hidden': 'true' }, state === 'green' ? '●' : state === 'red' ? '■' : '?'), head),
    h('p', { class: 'bn-sub' }, sub),
    lanes(),
    /* OUTSIDE `lanes()`, deliberately. This number is not a lane, and
       test-page.mjs sums every count inside `.lanes` against the fleet size --
       so a first version that rendered it in there broke a correct check.
       The DOM says what the copy says. */
    coverageLine(),
    /* ONE CLAUSE. It was 45 words of definition under a block that already
       defines every lane inside it. What a reader needs is the bar, not a
       restatement of the lane predicates two inches above. */
    h('p', { class: 'bn-rule' }, 'Green requires an empty "needs a person" lane and no drop in coverage.'));
}
/* THE DEFINITION IS PART OF THE CARD, not a tooltip and not a fold.
   These words are the page's own vocabulary -- "Not established" and "Needs a
   ruling" mean nothing until someone tells you -- and until 2026-08-28 the
   strip rendered the word and the count alone. Doug, who designed the lanes,
   said he could not remember them. The matrix group headers stopped repeating
   the definitions on 2026-08-29, so this is the ONLY place they are given.
   Do not fold it, tooltip it, or move it back down into the table.
   A KEY YOU HAVE TO DISCOVER IS NOT A KEY -- and a title= tooltip is worse,
   because it needs a mouse. That applies to the CHIPS too: a card gloss must
   define every lane whose word appears as a chip inside it. */
/* THE HEALTH-COVERAGE COUNT, which until 2026-08-29 was not on this page at
   all. CLAUDE.md calls it the scoreboard -- "that number falling is what
   progress looks like" -- and says it is printed under the fleet-health card.
   There is no fleet-health card on the v3 page. The only fleet-level statement
   of the number was inside the GREEN banner sentence, and this fleet has never
   been green, so the project's own measure of progress had been invisible
   since the redesign. Per site it was still in the drawer (`coverage_partial`,
   "Seen only by the consent sweep"); nothing totalled it.

   IT IS NOT A LANE, and the breakdown is here to stop it being read as one.
   On 2026-08-29 it was 11 and the "Not established" lane was also 11, over
   DIFFERENT SETS: the lane holds app.eastauroracc.com and not
   elderwoodipa.com, this count holds elderwoodipa.com and not
   app.eastauroracc.com. Two figures that agree by coincidence are the ones
   nobody catches, so the split by lane is computed and printed, never
   asserted. */
function coverageLine() {
  /* Read here rather than passed in: coverageLine() is called from more than
     one place and threading it through would put the same fact in two
     signatures. */
  const expectedDrops = (D.coverage_regressions || []).filter(r => r.expected);
  const ids = D.no_health_evidence;
  const by = {};
  let offRoster = 0;
  for (const id of ids) {
    const s = SITES.find(x => x.id === id);
    if (!s) { offRoster++; continue; }
    (by[lane(s)] ||= []).push(id);
  }
  const parts = LANE_ORDER.filter(L => by[L]).map(L => by[L].length + ' in ' + LANE[L].word);
  if (offRoster) parts.push(offRoster + ' not in the table');
  /* ONE FOOTNOTE, NOT THREE. Doug, 2026-08-31: "too much repeating, can these
     be consolidated?" -- three grey paragraphs sat under the cards saying
     different things in the same voice. The two aside LANES join this line
     rather than becoming a card: they keep the `lanes-aside` class and their
     `b` counts because test-page.mjs sums `.gc-hd .n, .lanes-aside b` against
     the fleet size, and this count is deliberately NOT in that sum -- it cuts
     across the lanes rather than being one. */
  return h('p', { class: 'cov-line' },
    h('span', { class: 'lanes-aside' }, ...ASIDE_LANES.map((L, i) => [
      i ? h('span', { class: 'sep' }, '\u00b7') : null,
      h('button', { 'data-lanes': L, onclick: () => pick([L]) },
        h('b', {}, laneCounts[L]), ' ' + LANE[L].word),
      h('span', { class: 'aside-sub' }, ' \u2014 ' + LANE[L].sub)]).flat().filter(Boolean)),
    h('span', { class: 'sep' }, '\u00b7'),
    h('b', {}, ids.length), ' with no health evidence',
    h('span', { class: 'aside-sub' }, ' \u2014 no backup age and no plugin or theme count. '
      + (ids.length ? 'Cuts across the lanes rather than being one: ' + parts.join(', ') + '.'
                    : 'Nothing is in this state.')),
    /* An acknowledged coverage drop, stated with its numbers. It does not
       gate the banner, and it is not silent either. */
    ...(expectedDrops.length
        ? [h('span', { class: 'sep' }, '\u00b7'),
           h('b', {}, expectedDrops.reduce((n, r) => n + r.lost, 0)),
           ' fewer site' + (expectedDrops.reduce((n, r) => n + r.lost, 0) === 1 ? '' : 's') + ' measured',
           h('span', { class: 'aside-sub' }, ' \u2014 ' + expectedDrops.map(coverageDropPhrase).join('; ')
             + ', recorded as expected when the run was ingested. Not a scan that lost sight of them.')]
        : []));
}

/* Module scope: coverageLine() renders the aside-lane chips now, and they are
   clickable filters like every other lane chip. */
function pick(ls) { laneFilter = sameFilter(ls) ? [] : ls; draw(); syncUrl(); }

function lanes() {
  const n = ls => ls.reduce((a, L) => a + laneCounts[L], 0);
  return h('div', { class: 'lanes' },
    h('ul', { class: 'grp-cards' }, ...GROUPS.map(g => h('li', { class: 'gc gc-' + g.key },
      h('button', { class: 'gc-hd', 'data-lanes': g.lanes.join(','), onclick: () => pick(g.lanes) },
        h('span', { class: 'n' }, n(g.lanes)), h('span', { class: 'w' }, g.word)),
      h('p', { class: 'gc-sub' }, g.sub),
      /* Only where a card covers more than one lane. A single-lane card would
         print its own count twice, and the chip would say nothing the heading
         did not. */
      g.lanes.length > 1
        ? h('p', { class: 'gc-chips' }, ...g.lanes.map((L, i) => [
            i ? h('span', { class: 'sep' }, '\u00b7') : null,
            h('button', { 'data-lanes': L, onclick: () => pick([L]) },
              h('b', {}, laneCounts[L]), ' ' + LANE[L].word)]).flat().filter(Boolean))
        : null))),
    /* NOT A CARD, and NOT "not scored" -- see GROUPS. Both of these are
       measured outcomes: SKIP and FROZEN are severity statuses, and an
       excluded site is scored and then left out of the fleet totals. */
    );
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

/* The Schedule panel's opening paragraph. A function because it has a branch:
   backlogElsewhere can be empty, and the inline version could not say so --
   at a count of 0 it would have rendered "the other 0 () need a person for
   something else first", a sentence with an empty parenthesis in it. It has
   never been 0 on this fleet, which is why nobody saw it. The same inline
   version also hardcoded the plural and printed "the other 1
   (iroquoisfence.com) need a person ... and are listed here too" every day
   the count was 1, which was every day. */
function schedIntro() {
  const n = AGG.backlogElsewhere.length;
  let t = AGG.backlogOnly.length + ' sites carry a warning that is only a WordPress or plugin backlog. '
        + AGG.backlogScheduled.length + ' of them sit under "needs scheduling" in the matrix';
  if (n) {
    t += '; the other ' + n + ' (' + AGG.backlogElsewhere.map(s => s.id).join(', ') + ') need'
       + (n === 1 ? 's' : '') + ' a person for something else first and ' + (n === 1 ? 'is' : 'are')
       + ' listed here too.';
  } else {
    t += ', and every one of them is listed here.';
  }
  return t + ' This tab arranges the backlog by the decision instead of the site. A WordPress release is one decision per target version; a plugin is one decision per component, because every install wants the same version.';
}

$('#app').append(h('div', { class: 'wrap' },
  h('header', { class: 'top' },
    h('div', {}, /* The counts are in the tools row, above the table, where they are LIVE --
   they follow the filter. This masthead copy and the Evidence tab label were
   both static, so a reader filtering down to one host read the whole-fleet
   total twice beside a much shorter table. Three copies, one of them true.

   NO PROSE PARAGRAPH HERE. Until 2026-08-29 a `p.thesis` sat under the h1:
   "One row per site, one column per question. Hatched is unmeasured. Schedule
   tab: the same evidence arranged by decision." Each clause is stated lower
   down, next to the thing it describes and in a form that follows the data:
   the tools row's live row/question count, the key's "not measured -- an
   absence, never a pass", and the Schedule panel's "This tab arranges the
   backlog by the decision instead of the site." An abstract of a page, at the
   top of the page, is three more copies to keep true. test-page.mjs asserts
   header.top carries no paragraph. */
      h('h1', {}, 'clevermethod fleet', h('small', {}, 'read-only')),
      /* THE OTHER PAGES, AT THE TOP. Doug, 2026-08-31: they were in the
         footer, below a table of 85 rows, which is not where a reader looks
         for "where else can I go". The Consent column header and the
         Vulnerable column header still link out too -- those are the route
         from the question, this is the route from the page. */
      h('nav', { class: 'topnav' },
        h('a', { href: '/components' }, 'Components'),
        h('a', { href: '/consent' }, 'Consent'),
        h('a', { href: '/vulnerabilities' }, 'Vulnerabilities'),
        h('a', { href: '/api/fleet-scan' }, 'JSON feed'))),
    h('div', { class: 'sweep' }, ...sweep.map(([name, r]) => h('div', { class: ageDays(r.observed_at) > 1 ? 'stale' : '' }, name + ' ', h('b', {}, fmtEastern(r.observed_at)), ' ' + (r.deep_scanned ?? '?') + '/' + r.site_count)))),
  banner(),
  tabs,
  h('div', { class: 'view view-matrix', id: 'view-matrix' },
  h('div', { class: 'tools' }, q, hostSel, h('label', {}, absBox, 'Only rows with an unmeasured cell'), count),
  h('ul', { class: 'key' },
    h('li', {}, h('span', { class: 'c s-crit cell' }, '■'), 'critical / risk'), h('li', {}, h('span', { class: 'c s-warn cell' }, '▲'), 'warning: schedule or decide'),
    h('li', {}, h('span', { class: 'c s-plan cell' }, '◔'), 'planning, dated'), h('li', {}, h('span', { class: 'c s-good cell' }, '●'), 'measured, nothing pending'),
    h('li', {}, h('span', { class: 'c s-info cell' }, '·'), 'measured, recorded, not scored'), h('li', {}, h('span', { class: 'c s-abs cell' }), 'not measured — an absence, never a pass'),
    h('li', {}, h('span', { class: 'c s-na cell' }, 'n/a'), 'not measurable on this host')),
  mwrap),
  h('div', { class: 'view view-schedule', id: 'view-schedule', hidden: true },
    h('div', { class: 'sched' },
      h('div', { class: 'sched-main' }, ...col2),
      h('aside', { class: 'sched-side' },
        h('h2', {}, 'Reading this view'),
        h('p', {}, schedIntro()),
        h('p', {}, 'Counts carry the set they are counted over. "Of ' + D.components.sites_inventoried.length + ' inventoried sites" is not the fleet: ' + D.components.sites_missing.length + ' Pantheon and Nexcess sites have no component list, and ' + (SITES.length - D.components.expected.length) + ' sites are on hosts no inventory reaches.'),
        h('p', {}, 'The arrow beside a count is movement since the previous run of the same tool, from the ledger\'s own baseline. "No baseline" means the instrument changed and no honest comparison exists.'),
        h('p', {}, h('a', { href: '/components' }, 'Full component catalogue'), ' — every plugin, mu-plugin and theme, with the sites that run each.'),
        /* WHAT IS NOT ON THIS TAB, and nothing else. This paragraph read
           "Nothing here is an emergency. The N sites that need a person
           today, the rulings and the coverage gaps stay in the matrix; this
           tab is the maintenance calendar." Two of its three clauses restated
           the first paragraph, and the third was FALSE: on 2026-08-29 the
           Schedule column listed iroquoisfence.com, a site the "needs a
           person" lane names, while this sentence said those sites stay
           in the matrix. (Spelling out the lane's count here would trip
           test-page.py's typed-count check, which reads comments too.) The first paragraph said the opposite in the same
           panel. Checked by reading the rendered column for the id, not by
           reading the code. Rulings and coverage gaps ARE absent from this
           tab, so that clause stays -- naming an absence is the one thing
           these subtraction passes never cut. */
        h('p', {}, 'Rulings and coverage gaps are not scheduled here; they stay in the matrix.')))),
  h('div', { class: 'below' },
    h('section', {}, h('h2', {}, 'What the audit workbook claims, and what the plugin inventory can see'),
      h('p', {}, 'The audit workbook is the manual spreadsheet this page replaces. Every attestation was imported from it with no confirming person or date, and nobody here has re-confirmed one. Where a claim names a plugin, the component inventory can confirm it; open any site to see its claims beside what was measured.'),
      h('div', { class: 'att-grid' }, ...attTotals.map(a => h('div', { class: 'a' }, h('b', {}, a.label),
        h('span', { class: 'n' }, a.evidence), ' confirmed of ', h('span', { class: 'n' }, a.claimedYes), ' claimed yes', h('br'),
        h('span', { class: 'n ' + (a['no-evidence'] ? 'bad' : '') }, a['no-evidence']), ' claimed with no plugin seen', a.sites.length ? h('small', {}, ' (' + a.sites.join(', ') + ')') : null, h('br'),
        h('span', { class: 'n' }, a['not-inventoried']), ' not inventoried', a.platform ? [h('br'), h('span', { class: 'n' }, a.platform), ' platform control, not checkable'] : null, a['unclaimed-evidence'] ? [h('br'), h('span', { class: 'n' }, a['unclaimed-evidence']), ' not claimed, plugin present anyway'] : null)))),
    h('section', {}, h('h2', {}, 'Since the previous run'),
      h('p', {}, D.changes.filter(c => c.class === 'TRANSITION').length + ' threshold crossing: ' + (D.changes.filter(c => c.class === 'TRANSITION').map(c => c.site + ' ' + c.before + ' → ' + c.after).join('; ') || 'none') + '. ' + D.changes.filter(c => c.class === 'DRIFT').length + ' counters moved on findings already open.'),
      h('p', {}, 'Over the ledger (' + fmtDay(AGG.histFrom.slice(0, 10)) + '–' + fmtDay(AGG.histTo.slice(0, 10)) + '): ' + AGG.wpMoved.length + ' sites moved WordPress version; plugin backlogs grew on ' + AGG.grew + ', held on ' + AGG.same + ', shrank on ' + AGG.shrank + ' of ' + AGG.withHist + '. Movement, not a trend.'),
      // Only when something DID become visible: rendered unconditionally this
      // said "0 facts became visible this run (, on undefined sites): the
      // instrument changed, not the fleet" on every quiet run -- a confident
      // wrong sentence queued for the steady state. And each fact carries its
      // OWN site count; the [0] shorthand claimed the first fact's count for
      // every fact, unnoticed only because the four smtp facts shared 21.
      D.coverage_changes.length ? h('p', {}, D.coverage_changes.length + ' fact(s) became visible this run (' +
        D.coverage_changes.map(c => c.fact + ' on ' + c.sites.length + ' site' + (c.sites.length === 1 ? '' : 's')).join(', ') +
        '): the instrument changed, not the fleet.') : null)),
  h('footer', { class: 'foot' },
    h('p', {}, 'Health counts: ' + D.counts.CRIT + ' critical · ' + D.counts.WARN + ' warning · ' + D.counts.OK + ' OK · ' + D.counts.SKIP + ' skip · ' + D.counts.FROZEN + ' frozen, ' + D.excluded_sites.length + ' excluded by ruling (' + D.excluded_sites.join(', ') + '). Consent: ' + D.axes.consent.WARN + ' warning · ' + D.axes.consent.OK + ' OK · ' + D.axes.consent.UNKNOWN + ' unknown.'),
    /* The route list moved to the masthead on 2026-08-31 and is NOT repeated
       here: a reader who has reached the footer has passed the nav twice. What
       stays is provenance, which belongs at the end. */
    h('p', {}, 'Times are the ledger\'s UTC stamps shown as Eastern (' + D.tz_note + '). Generated ' + D.generated + ' from a ' + D.all_runs.length + '-run ledger. Read-only: nothing on this page changes a site.'))));
readUrl();
draw();
if (new URLSearchParams(location.search).get('view') === 'schedule') setView('schedule');
$$('#view-schedule .item').forEach((it, i) => { if (i === 2) it.open = true; });
if (location.hash.startsWith('#site=')) openSite(decodeURIComponent(location.hash.slice(6)));
