#!/usr/bin/env node
// The fleet page, rendered: what the DOM must show once page.js has run.
//
// test/test-page.py checks the model and the source. This one opens the file
// in headless Chromium (the same playwright the consent sweep uses) and reads
// the page the way a person does. Most of the defects in CLAUDE.md's table
// were found by a person looking at a rendered page; this is that look,
// automated for the properties that can be stated.
//
//   node test/test-page.mjs            # renders ./fleet.html
//   node test/test-page.mjs PATH.html  # any rendered page
//
// Offline: file:// only. A page that requested anything from the network
// fails here, because the page must open from behind Access with no second
// request and must never disagree with data that arrived separately.
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const file = resolve(process.argv[2] || 'fleet.html');
const html = readFileSync(file, 'utf8');
const model = JSON.parse(html.match(/<script type="application\/json" id="fleet-data">(.*?)<\/script>/s)[1].replace(/<\\\//g, '</'));

let pass = 0, fail = 0;
const check = (name, cond, detail = '') => {
  if (cond) { pass++; console.log('ok    ' + name); }
  else { fail++; console.log('FAIL  ' + name + (detail ? '  <- ' + String(detail).slice(0, 200) : '')); }
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [], requests = [];
page.on('pageerror', e => errors.push(e.message));
page.on('request', r => { if (!r.url().startsWith('file:')) requests.push(r.url()); });
await page.goto('file://' + file);
await page.waitForSelector('table.matrix tbody tr.row');

console.log('-- it renders, alone --');
check('no script error', errors.length === 0, errors.join(' | '));
check('no request left the page', requests.length === 0, requests.join(' '));

console.log('\n-- every site, once --');
const rows = await page.$$eval('tr.row', els => els.map(e => e.querySelector('.nm').textContent));
check('one row per site in the model', rows.length === model.sites.length, rows.length + ' vs ' + model.sites.length);
check('no site twice', new Set(rows).size === rows.length);
// EVERY SITE IS IN EXACTLY ONE LANE, and the strip must account for all of
// them. Read the four card headings plus the aside, never `.lanes .n`
// generally -- the chips inside a card repeat their card's members, so summing
// every number in the strip double-counts and the total silently exceeds the
// fleet. Four cards + the aside = 85.
const laneCounts = await page.$$eval('.gc-hd .n, .lanes-aside b', els => els.map(e => +e.textContent));
check('the lane counts sum to the fleet', laneCounts.reduce((a, b) => a + b, 0) === model.sites.length, laneCounts.join('+'));
const chipSums = await page.$$eval('.gc', cards => cards.map(c => ({
  head: +c.querySelector('.gc-hd .n').textContent,
  chips: [...c.querySelectorAll('.gc-chips b')].map(b => +b.textContent),
})));
check('a card with chips equals the sum of its chips',
      chipSums.every(c => !c.chips.length || c.chips.reduce((a, b) => a + b, 0) === c.head),
      JSON.stringify(chipSums));
const grpCounts = await page.$$eval('tr.grp .n', els => els.map(e => +e.textContent));
check('the row groups carry the same counts as the lane strip', grpCounts.reduce((a, b) => a + b, 0) === model.sites.length, grpCounts.join('+'));

console.log('\n-- columns line up and carry their denominators --');
const nHead = await page.$eval('table.matrix thead tr.cols', tr => tr.querySelectorAll('th').length);
const cellCounts = await page.$$eval('tr.row', els => els.map(e => e.querySelectorAll('td').length));
check('every row has one cell per header', cellCounts.every(n => n === nHead), nHead + ' headers; rows ' + [...new Set(cellCounts)].join(','));
const covs = await page.$$eval('table.matrix thead tr.cols th .cov', els => els.map(e => e.textContent.trim()));
// the site column's own "85 of 85" and the two axis columns' "scored" are the
// only headers that are not a measurement; every other column is counted over
// a named set and must say which.
const measured = covs.slice(1).filter(t => t !== 'scored');
check('every measured column header states "N of M"', measured.length > 0 && measured.every(t => /^\d+ of \d+/.test(t)), covs.join(' | '));
check('at least one denominator is smaller than the fleet (or it would not be worth printing)', measured.some(t => { const m = t.match(/^(\d+) of (\d+)/); return m && +m[2] < model.sites.length; }));

console.log('\n-- absence is a shape, never a colour --');
const absStyled = await page.$$eval('td.c.s-abs', els => els.map(e => e.className));
check('there are absence cells on this fleet', absStyled.length > 0);
check('no absence cell also carries a status class', absStyled.every(c => !/s-(good|warn|crit|info|plan)\b/.test(c)));
const absText = await page.$$eval('td.c.s-abs .t', els => els.map(e => e.textContent.trim()));
check('absence cells carry an absence word, never a number', absText.every(t => !/^\d+$/.test(t)), absText.filter(t => /^\d+$/.test(t)).join(','));
const valueSpans = await page.$$eval('.v', els => els.map(e => e.textContent.trim()));
check('no value span renders the unknown sentinel', valueSpans.every(t => t !== 'unknown' && t !== 'n/a'));
const naCells = await page.$$eval('tr.row', els => els.filter(e => e.querySelector('.hs').textContent.includes('Nexcess')).map(e => e.querySelectorAll('td.c')[0].textContent.trim()));
check("every Nexcess backup cell is 'no API', unmeasurable rather than blank", naCells.length > 0 && naCells.every(t => t === 'no API'), [...new Set(naCells)].join(','));

console.log('\n-- statuses are the model\'s --');
const healthChips = await page.$$eval('tr.row td.ax:nth-child(2) .chip', els => els.map(e => e.dataset.st));
const modelHealth = model.sites.map(s => s.health.status);
for (const st of ['CRIT', 'WARN', 'OK', 'SKIP', 'FROZEN', 'UNKNOWN']) {
  check('health ' + st + ' chips equal the model', healthChips.filter(x => x === st).length === modelHealth.filter(x => x === st).length);
}
const consentChips = await page.$$eval('tr.row td.ax:nth-child(3) .chip', els => els.map(e => e.dataset.st));
check('consent chips equal the model', ['WARN', 'OK', 'UNKNOWN'].every(st => consentChips.filter(x => x === st).length === model.sites.filter(s => s.consent.status === st).length));
const chipText = await page.$$eval('.chip', els => els.map(e => e.textContent.trim()));
check('every chip carries a word, never colour alone', chipText.every(t => /[A-Za-z]/.test(t)));

console.log('\n-- the lane vocabulary is defined where it is used --');
// "Not established", "Needs a ruling", "Needs scheduling" are this page's own
// invented terms. Until 2026-08-28 the strip at the top rendered the word and
// the count alone; the definitions existed in LANE[].sub and were shown only
// inside the matrix group headers and the site drawer. Doug, who designed the
// lanes, said he could not remember them.
//
// The bug table already carries this row once: a key put one click away on a
// page where every <details> renders closed. So this asserts the definition is
// VISIBLE -- rendered, non-empty, and not inside a fold -- rather than merely
// present somewhere in the file. A title= tooltip would also fail this, and
// should: it needs a mouse.
// ASSERT THE PROPERTY, NOT THE SHAPE. This block used to count seven `.lanes
// li` and read a `.lane-sub` out of each, which is a description of the markup
// on the day it was written; the four-card grouping of 2026-08-29 broke all of
// it while leaving the guarantee intact. The guarantee is: every lane word
// this page invents is displayed, and a visible definition is displayed WITH
// it -- in its card, or on the aside line. Where it lives is not the contract.
const laneDefs = await page.evaluate(() => Object.entries(LANE).map(([key, L]) => {
  // THE WHOLE BANNER BLOCK, not just `.lanes`. The guarantee stated above is
  // that every lane word is displayed with a visible definition, and that
  // "where it lives is not the contract" -- but this scoped to `.lanes` and so
  // encoded a location anyway. The aside line moved into `.cov-line` on
  // 2026-08-31, a sibling inside the same banner, and three checks failed on a
  // page that still satisfied the guarantee.
  const strip = document.querySelector('.banner');
  // The container that displays this lane's word: a card, or the aside line.
  const host = [...strip.querySelectorAll('.gc, .lanes-aside')]
    .find(e => e.textContent.includes(L.word));
  if (!host) return { key, word: L.word, found: false };
  const gloss = host.classList.contains('lanes-aside')
    // On the aside each lane has its OWN gloss span; pick the one next to this
    // word, not the first on the line.
    ? [...host.querySelectorAll('button')].filter(b => b.textContent.includes(L.word))
        .map(b => (b.nextElementSibling || {}).textContent || '').join('')
    : (host.querySelector('.gc-sub') || {}).textContent || '';
  return { key, word: L.word, found: true, gloss: gloss.trim(),
           folded: !!host.closest('details'),
           shown: !!host.offsetParent };
}));
check('every lane is displayed', laneDefs.length === 7 && laneDefs.every(l => l.found),
      JSON.stringify(laneDefs.filter(l => !l.found).map(l => l.word)));
check('every lane carries a definition, not just a word',
      laneDefs.every(l => l.gloss && l.gloss.length > 10),
      JSON.stringify(laneDefs.map(l => [l.word, (l.gloss || '').length])));
check('...and none of them is inside a fold', laneDefs.every(l => !l.folded));
check('...and each one is actually rendered, not display:none',
      laneDefs.every(l => l.shown), JSON.stringify(laneDefs.map(l => [l.word, l.shown])));
check('...and the definition is distinct from the word',
      laneDefs.every(l => l.gloss.trim() !== l.word.trim()));
// A CARD GLOSS MUST DEFINE EVERY LANE IT HOLDS. A chip reading "17 Needs a
// ruling" under a group heading is one of this page's invented words with no
// meaning beside it -- the 2026-08-28 bug, one level down. So where a card
// covers more than one lane, its gloss has to name each of them.
const multi = await page.evaluate(() => [...document.querySelectorAll('.gc')]
  .filter(c => c.querySelectorAll('.gc-chips button').length > 1)
  .map(c => ({
    chips: [...c.querySelectorAll('.gc-chips button')].map(b => b.textContent.replace(/^\d+\s*/, '').trim()),
    gloss: (c.querySelector('.gc-sub') || {}).textContent || '',
  })));
check('a card holding several lanes defines each of them in its gloss',
      multi.length > 0 && multi.every(c => c.chips.every(w => c.gloss.includes(w))),
      JSON.stringify(multi.map(c => c.chips.filter(w => !c.gloss.includes(w)))));
// THE ABSENCE IS NEVER FOLDED INTO A BACKLOG. Drawn that way in the concept:
// "Not established" sat inside a planning card reading "work must be
// scheduled, defined, or ruled on", about sites where nothing is known.
check('the "Not established" lane is not grouped with scheduling or rulings',
      await page.evaluate(() => {
        const c = document.querySelector('.gc-unknown');
        return !!c && !/Needs scheduling|Needs a ruling/.test(c.textContent);
      }));
// AND NOTHING CALLS A SCORED SITE UNSCORED. SKIP and FROZEN are severity
// statuses and an excluded site is scored and left out of the totals --
// cm-whitelabel was CRIT with three findings the day a card claimed otherwise.
check('no group claims a site is unscored', !/not scored/i.test(await page.$eval('.lanes', e => e.textContent)));

console.log('\n-- the banner --');
// SCOPE THE PROSE CHECKS TO THE PROSE. The lane strip moved INSIDE .banner on
// 2026-08-29, so e.textContent now carries seven lane words, seven counts and
// seven glosses. A check that reads the whole container can be satisfied by
// text it was never about -- which is how a check goes vacuous without anyone
// editing it.
const banner = await page.$eval('.banner', e => ({
  cls: e.className,
  text: e.textContent,
  prose: e.querySelector('.bn-head').textContent + ' ' + e.querySelector('.bn-sub').textContent,
}));
check('exactly one banner state', ['banner-green', 'banner-red', 'banner-cant'].filter(c => banner.cls.includes(c)).length === 1, banner.cls);
check('the predicate is printed under it', banner.text.includes('Green requires'));
const bodyText = await page.evaluate(() => document.body.innerText.toLowerCase());
check("the page never says 'all good'", !bodyText.includes('all good'));
// THE SCOREBOARD MUST BE ON THE PAGE. CLAUDE.md calls the health-coverage
// count "the number printed under the fleet-health card" and "what progress
// looks like". The v3 page has no fleet-health card, and until 2026-08-29 the
// only fleet-level statement of the number lived inside the GREEN banner
// sentence -- a state this fleet has never been in. The project's own measure
// of progress was invisible on its own dashboard for the life of the redesign.
// Property: the count renders in whatever state the banner is in.
const covLine = await page.$eval('.banner .cov-line', e => e.textContent).catch(() => '');
check('the fleet states its health-coverage count', /\d+ with no health evidence/.test(covLine), covLine.slice(0, 120));
// ...AND IS NOT READ AS THE "Not established" LANE. On 2026-08-29 both were
// 11 over different sets -- the lane holds app.eastauroracc.com and not
// elderwoodipa.com, the count the reverse -- and in the green state they are
// 11 and 12. Two figures that agree by coincidence are the ones nobody
// catches, so the line prints its own split by lane.
check('...and says which lanes those sites are in, so it cannot be read as one',
      /Cuts across the lanes rather than being one: \d+ in |Nothing is in this state/.test(covLine),
      covLine.slice(0, 200));

const personN = await page.$eval('.lanes li:first-child .n', e => +e.textContent);
// THREE STATES, NOT TWO. This read `banner-red ? names them : personN === 0`
// until 2026-08-28, which quietly assumed the live ledger never carries a
// coverage regression. The moment one did -- a CI consent sweep reaching 71 of
// 79 where a laptop reaches 78 -- the banner correctly went can't-say with 4
// sites in the lane and a CORRECT page failed. The can't-say branch names them
// too, in its own clause, and the check below already covers that case.
// THE HEADLINE SAYS WHAT CHANGED, NOT WHAT THE CARD ALREADY SAYS. It used to
// assert the count appeared in the prose, which is what Doug objected to on
// 2026-08-31: "11 sites need a person" sat directly above a card reading
// "11 Needs a person". The count belongs to the card. What the banner owns is
// the thing no card can say -- whether any of it is NEW since the last look --
// because a red headline over a months-old backlog is an alert that never
// changes, which is the defect the vulnerability page was rewritten for.
check('a red banner says whether anything is new since the last run',
      !banner.cls.includes('banner-red')
      || /newly need|Nothing new since the last run/.test(banner.prose),
      banner.prose.slice(0, 120));
// ...and it must not simply restate the tile's number as its headline.
check('...without repeating the lane count as the headline',
      !banner.cls.includes('banner-red')
      || !new RegExp('^\\s*' + personN + ' sites? need a person').test(banner.prose),
      banner.prose.slice(0, 60));
// ...AND ACTUALLY NAMES THEM. The check above is titled "names exactly the
// needs-a-person sites" and never tested a name: the headline already reads
// "4 sites need a person", so `includes(personN + ' site')` passes with the
// site list replaced by "See the matrix." Proven by doing exactly that, on
// 2026-08-29 -- the negative control failed to fail, which is the only way a
// check like this is ever found. The names come from the matrix rather than
// the model, so this also cross-checks the lane tile against the table.
const personSites = await page.evaluate(() => {
  const out = []; let inLane = false;
  for (const tr of document.querySelectorAll('table.matrix tbody tr')) {
    if (tr.classList.contains('grp')) { inLane = /Needs a person/.test(tr.textContent); continue; }
    if (inLane) out.push(tr.querySelector('.nm').textContent);
  }
  return out;
});
check('the needs-a-person lane and its tile agree', personSites.length === personN,
      personSites.length + ' rows vs ' + personN + ' on the tile');
check('...and the banner names every one of them',
      !banner.cls.includes('banner-red') || (personSites.length > 0 && personSites.every(id => banner.prose.includes(id))),
      JSON.stringify(personSites.filter(id => !banner.prose.includes(id))));
check('the banner is red or can\'t-say whenever anyone needs a person', personN === 0 || !banner.cls.includes('banner-green'));
// THE LANE STRIP IS PART OF THE BANNER, and its definitions must survive the
// move. The lane checks above read '.lanes li' wherever it sits; this pins
// WHERE it sits, so the two cannot be separated again without a test saying so.
check('the lane strip is inside the banner, not a second box below it',
      await page.$eval('.lanes', e => !!e.closest('.banner')));
check('...and the predicate still sits under both',
      await page.$eval('.bn-rule', e => !!e.closest('.banner')));
check('a coverage regression forces can\'t-say', model.coverage_regressions.length === 0 || banner.cls.includes('banner-cant'));

// THE BANNER DOES NOT RESTATE THE SWEEP STRIP. Until 2026-08-29 its basis
// clause appended the per-source coverage fractions -- the same sweepLine()
// runs the strip renders directly above it, which also carries each run's
// timestamp and stale marker. Two copies of one fact, 40px apart, and the
// banner held the worse one. Asserted as a PROPERTY (no source name from the
// strip appears in the banner) rather than against the sentence, so a reword
// cannot quietly put it back.
// The source name is the text node BEFORE the <b> timestamp. Reading the
// whole div and trimming at the first digit gives "Pantheon health Aug", which
// appears nowhere and made this check pass against a banner that HAD been put
// back -- caught by running the negative control, not by reading it.
const sweepNames = await page.$$eval('.sweep > div', els =>
  els.map(e => (e.firstChild ? e.firstChild.textContent : '').trim()).filter(Boolean));
check('the sweep strip has a line per source', sweepNames.length >= 3, JSON.stringify(sweepNames));
const bnSub = await page.$eval('.bn-sub', e => e.textContent);
check('the banner does not repeat the sweep strip\'s per-source coverage',
      sweepNames.every(n => !bnSub.includes(n)),
      JSON.stringify(sweepNames.filter(n => bnSub.includes(n))));
// ...and the other half of what was duplicated: the N/M fractions themselves.
// The can't-say branch writes coverage in words ("measured 71 of 79, down from
// 78"), never as a fraction, so this stays true in every banner state.
check('...nor their N/M fractions', !/\d+\/\d+/.test(bnSub), bnSub.slice(0, 160));

// THE KEY IS A KEY, NOT A PLACE TO PUT PARAGRAPHS. It carried a Workbook
// paragraph and a sentence describing the row grouping, neither of which
// defined a symbol; both explained things stated better elsewhere (the site
// drawer, and the group headers you can see). Property: every item in the key
// defines one glyph. Prose has no swatch, so it cannot pass.
// THE MASTHEAD IS A TITLE, NOT AN ABSTRACT. Until 2026-08-29 a paragraph sat
// under the h1 -- "One row per site, one column per question. Hatched is
// unmeasured. Schedule tab: the same evidence arranged by decision." -- whose
// three clauses were each stated lower down, beside the thing they describe
// and in a form that follows the data. A summary of a page, at the top of the
// page, is three more copies to keep true, and static copy beside live counts
// is the defect this file already pins in two other places. Property: the
// masthead holds the title and the sweep strip, and no prose.
// NOTE: the CONSENT page keeps its `p.thesis`, legitimately -- it states the
// two-question distinction that page exists for and that page says nowhere
// else. This check runs against the fleet page only.
const topParas = await page.$$eval('header.top p', els => els.map(e => e.textContent.trim()));
check('the masthead carries no prose paragraph', topParas.length === 0, JSON.stringify(topParas));

const keyItems = await page.$$eval('.key li', els =>
  els.map(e => ({ hasSwatch: !!e.querySelector('.cell'), words: e.textContent.trim().split(/\s+/).length })));
check('the key has an entry per cell state', keyItems.length >= 5, String(keyItems.length));
check('every key entry defines a symbol', keyItems.every(k => k.hasSwatch),
      JSON.stringify(keyItems.filter(k => !k.hasSwatch)));
check('no key entry is a paragraph', keyItems.every(k => k.words <= 12),
      JSON.stringify(keyItems.filter(k => k.words > 12).map(k => k.words)));

// THE WORKBOOK IS NOT A COLUMN GROUP. Its per-site claims live in the site
// drawer, which carries a "Confirmed by" cell the matrix cells never had.
const groupNames = await page.$$eval('thead tr.groups th', els => els.map(e => e.textContent.trim()));
check('the matrix carries no audit-workbook column group',
      !groupNames.some(g => /workbook/i.test(g)), JSON.stringify(groupNames));
await page.click('tr.row .nm');
await page.waitForSelector('.drawer.open .site-detail');
const drawerWb = await page.$eval('.drawer', d => {
  const sec = [...d.querySelectorAll('section')].find(x => /Workbook attestations/.test(x.textContent));
  return sec ? sec.textContent : '';
});
check('...because the site drawer carries the claims instead',
      /Workbook attestations/.test(drawerWb) && /Confirmed by/.test(drawerWb), drawerWb.slice(0, 80));
// CLOSE IT THE WAY A PERSON DOES. Clearing .open and body.drawer-open by hand
// does not stick: openSite() sets location.hash, the hashchange listener fires
// on the NEXT task and re-opens the drawer. The page then swallows every later
// click behind the backdrop, and playwright reports it 30 seconds later as an
// unrelated test timing out. Escape runs closeSite(), which clears the hash.
await page.keyboard.press('Escape');
await page.waitForFunction(() => !document.body.classList.contains('drawer-open'));

// THE OTHER TWO STATES, driven with an edited copy of the same file. The
// green branch and the can't-say branch never run on a fleet with someone
// needing a person, so on most days nothing exercises them.
import { writeFileSync, unlinkSync } from 'node:fs';
async function variant(mutate) {
  const m2 = JSON.parse(JSON.stringify(model));
  mutate(m2);
  const tmp = file + '.variant.html';
  writeFileSync(tmp, html.replace(/<script type="application\/json" id="fleet-data">.*?<\/script>/s,
    '<script type="application/json" id="fleet-data">' + JSON.stringify(m2).replace(/<\//g, '<\\/') + '</script>'));
  const p2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await p2.goto('file://' + tmp);
  await p2.waitForSelector('.banner');
  const b = await p2.$eval('.banner', e => ({
    cls: e.className,
    text: e.textContent,
    prose: e.querySelector('.bn-head').textContent + ' ' + e.querySelector('.bn-sub').textContent,
  }));
  await p2.close(); unlinkSync(tmp);
  return b;
}
const green = await variant(m2 => { for (const s of m2.sites) {
  if (s.health.status === 'CRIT') { s.health.status = 'OK'; s.health.reasons = []; }
  s.consent.reasons = s.consent.reasons.filter(r => r.code !== 'consent_pre_consent_trackers');
  if (s.f.spf_present === false) s.f.spf_present = true; }
  // GREEN NEEDS BOTH HALVES OF THE PREDICATE. Clearing the sites but not the
  // regressions tests nothing: a coverage drop forces can't-say by design, so
  // this variant could never reach green once the ledger carried one, and the
  // failure looked like a banner defect rather than an unstated precondition.
  m2.coverage_regressions = []; });
check('with nobody needing a person the banner is green', green.cls.includes('banner-green'), green.cls);
// The sentence must be in the SENTENCE. The red state drops its equivalent
// clause because the lane strip below says it better; green keeps this one,
// because in green there is no red headline and this is the only thing
// standing between the banner and "all good". Reading .prose rather than the
// container means the lane counts cannot stand in for it.
//
// ONE FIGURE IN THE SENTENCE, NOT TWO, since 2026-08-29. It used to carry the
// coverage count too, directly above a "Not established" chip that was a
// different set in red and a different NUMBER in green (11 vs 12, measured).
// The coverage count is checked above instead, on its own line, where it
// renders in every state rather than only this one. The guarantee is
// unchanged in substance: green never reads as an all-clear, because the
// sentence names the backlog and the block names the coverage gap.
check('...and says it is NOT "all good" in the same breath: the backlog is in the sentence',
      /\d+ sites carry a maintenance backlog/.test(green.prose) && !green.text.toLowerCase().includes('all good'),
      green.prose.slice(0, 160));
check('...and the green block still carries the coverage count beside it',
      /\d+ with no health evidence/.test(green.text), green.text.slice(0, 160));
// THE REAL RECORD SHAPE, not an invented one. This fixture carried a `what`
// key, which `coverage_regressions()` has never emitted -- its keys are
// source, run_id, deep_scanned, site_count, previous_run_id,
// previous_deep_scanned and lost. page.js read `r.what || JSON.stringify(r)`,
// so the fixture passed while the LIVE page printed a raw JSON object into the
// banner for every real regression. A mock is evidence about the parser, never
// about the world -- and here the mock was built to match the parser's mistake.
const cant = await variant(m2 => { m2.coverage_regressions = [{
  source: 'consent', run_id: 'consent-2026-08-22_0900',
  deep_scanned: 38, site_count: 78,
  previous_run_id: 'consent-2026-08-21_0900', previous_deep_scanned: 54,
  lost: 16 }]; });
check("a coverage regression makes the banner can't-say even with nobody needing a person", cant.cls.includes('banner-cant') && !cant.cls.includes('banner-green'), cant.cls);
check('...and names the drop', cant.text.includes('38 of 78'), cant.text.slice(0, 160));
check('...and still names who needs a person on what was measured', personN === 0 || cant.text.includes(personN + ' site'), cant.text.slice(0, 300));

console.log('\n-- the coverage-change sentence, in both its states --');
// The paragraph rendered unconditionally, so the first run with no coverage
// change would print "0 facts became visible this run (, on undefined sites):
// the instrument changed, not the fleet" -- a confident wrong sentence queued
// for the steady state. And it claimed the FIRST fact's site count for every
// fact listed; the four smtp facts all sharing 21 sites is exactly why nobody
// would notice when they stopped sharing it.
async function sinceText(mutate) {
  const m2 = JSON.parse(JSON.stringify(model));
  mutate(m2);
  const tmp = file + '.variant.html';
  writeFileSync(tmp, html.replace(/<script type="application\/json" id="fleet-data">.*?<\/script>/s,
    '<script type="application/json" id="fleet-data">' + JSON.stringify(m2).replace(/<\//g, '<\\/') + '</script>'));
  const p2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await p2.goto('file://' + tmp);
  await p2.waitForSelector('.banner');
  const t = await p2.evaluate(() => document.body.innerText);
  await p2.close(); unlinkSync(tmp);
  return t;
}
const quiet = await sinceText(m2 => { m2.coverage_changes = []; });
check('a run with no coverage change renders no instrument-changed sentence',
  !quiet.includes('became visible this run'),
  (quiet.match(/.{0,90}became visible.{0,60}/s) || [''])[0]);
check('...and "undefined" appears nowhere in the rendered text', !quiet.includes('undefined'));
const mixed = await sinceText(m2 => {
  m2.coverage_changes = [{ fact: 'fact_a', sites: ['s1', 's2', 's3'] },
                         { fact: 'fact_b', sites: ['s4'] }]; });
check('each fact carries its own site count, never the first fact\'s',
  mixed.includes('fact_a on 3 sites') && mixed.includes('fact_b on 1 site'),
  (mixed.match(/.{0,140}became visible.{0,140}/s) || [''])[0]);

console.log('\n-- the drawer and the schedule tab --');
await page.click('tr.row .nm');
await page.waitForSelector('.drawer.open .site-detail');
const drawerName = await page.$eval('.drawer .sd-name', e => e.textContent.trim());
check('clicking a site opens its drawer', drawerName === rows[0], drawerName);
const codes = await page.$$eval('.drawer .rc', els => els.map(e => e.textContent.trim()));
const site0 = model.sites.find(s => s.id === rows[0]);
check('the drawer prints every reason code the model has for the site', codes.length === site0.health.reasons.length + site0.consent.reasons.length, codes.join(','));
await page.keyboard.press('Escape');
await page.click('.tabs button[data-v="schedule"]');
const items = await page.$$eval('#view-schedule .item', els => els.length);
check('the schedule tab has its decisions', items >= 4, items);
const itemNums = await page.$$eval('#view-schedule .it-num', els => els.map(e => e.textContent));
check('every schedule item states what it is counted over', itemNums.every(t => /of \d+|components|installs/.test(t)), itemNums.join(' | '));
// THE SIDE PANEL DESCRIBES THIS TAB, and until 2026-08-29 its last paragraph
// described a different one: "The 4 sites that need a person today, the
// rulings and the coverage gaps stay in the matrix" -- while the column
// beside it listed iroquoisfence.com, one of those four, and the panel's own
// FIRST paragraph said so. A backlog site that needs a person for some other
// reason is still a scheduling decision and is listed here. Rulings and
// coverage gaps really are absent, so that clause survived the cut.
// Measured while writing this: THREE of the four needs-a-person sites appear
// somewhere in the Schedule column -- iroquoisfence.com as a backlog decision
// of its own, hoffmanscheese and runtalnorthamerica.com inside the install
// lists of batched components. So the old sentence was not off by one site,
// it was off by three, and no version of "those sites are elsewhere" is true.
// There is deliberately NO positive check that the panel names them: a site
// inside a component's install list is not a decision about that site, and a
// check demanding the panel name it would fail on a correct page.
const sideText = await page.$eval('.sched-side', e => e.textContent);
check('the schedule panel never says the needs-a-person sites are only in the matrix',
      !/need s?a person[^.]*stay in the matrix/.test(sideText),
      (sideText.match(/[^.]*stay in the matrix[^.]*/) || [''])[0]);

// THE RECONCILIATION IS ARITHMETIC, so check the arithmetic rather than the
// wording. The inline version recomputed its filter three times in one
// sentence and hardcoded the plural, printing "the other 1
// (iroquoisfence.com) need a person ... and are listed here too" every day
// the count was 1 -- which was every day the page has existed. At a count of
// 0 the same sentence would have rendered an empty parenthesis; that branch
// had never run.
const split = sideText.match(/(\d+) sites carry a warning that is only a WordPress or plugin backlog\. (\d+) of them sit under "needs scheduling" in the matrix(?:; the other (\d+) \(([^)]*)\) (needs?) a person for something else first and (is|are) listed here too\.|, and every one of them is listed here\.)/);
check('the schedule panel reconciles the backlog against the matrix', !!split, sideText.slice(0, 220));
check('...its two halves add up to its total',
      !!split && Number(split[2]) + Number(split[3] || 0) === Number(split[1]),
      split ? split.slice(1, 4).join(' / ') : 'no match');
check('...and its verbs agree with the count it just printed',
      !!split && (!split[3] || (Number(split[3]) === 1
        ? (split[5] === 'needs' && split[6] === 'is')
        : (split[5] === 'need' && split[6] === 'are'))),
      split ? 'n=' + split[3] + ' "' + split[5] + '" "' + split[6] + '"' : 'no match');

check('the URL records the view', page.url().includes('view=schedule'));

console.log('\n-- narrow screens --');
await page.setViewportSize({ width: 375, height: 800 });
await page.waitForTimeout(200);
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check('the body does not scroll sideways at 375px', overflow <= 0, overflow + 'px');

await browser.close();
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
