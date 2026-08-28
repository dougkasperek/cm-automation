#!/usr/bin/env node
// The gating test's measured window, asserted against a page we control.
//
// This instrument has now been wrong about its window twice, in opposite
// directions, and both versions passed every source-grep contract test:
//
//   v1 cleared its counters BEFORE the post-rejection reload, so the OLD
//      page's tail (Clarity flushing its buffer) was counted as a tag
//      ignoring consent. Reported two compliant sites as leaking; went to
//      Nick Federico as a finding.
//
//   v2 cleared them AFTER page.reload({waitUntil:'load'}) resolved. The load
//      event fires after the fresh page's load-phase requests -- where GA4
//      pageview hits normally fire -- so the clear erased the exact load the
//      test exists to measure, and the gcs=G100 pings with it. "Nothing fires
//      after rejection" is the best possible result, and v2 manufactured it.
//
// A grep cannot see either defect, because both versions contain the same
// tokens in a plausible order. So this test runs pass() itself, against a
// local fixture page that fires one tracker DURING its load phase and a
// different tracker FROM THE OLD PAGE after the Reject click, and asserts
// each lands on the correct side of the window. Offline: the fixture's
// tracker URLs are paths on 127.0.0.1 crafted to match the real patterns, so
// nothing leaves the machine.
//
//   node test/test-gating-window.mjs
//
// Needs `npm i` (playwright), like test-page.mjs. Headless is fine here: the
// headed requirement exists because real vendors decline to fire under
// automation, and the fixture is not a real vendor.
import { createServer } from 'node:http';
import { chromium } from 'playwright';
import { pass, denialOutcome } from '../scripts/consent/test-gating.mjs';

let ok = 0, bad = 0;
const check = (name, cond, detail = '') => {
  if (cond) { ok++; console.log('ok    ' + name); }
  else { bad++; console.log('FAIL  ' + name + (detail ? '  <- ' + String(detail).slice(0, 200) : '')); }
};

// ---------------------------------------------------------------------------
// denialOutcome: did the synthetic pass actually load under a denial?
//
// Pure, so it needs no browser and runs first. These exist because the fact it
// reads -- `optanon_groups_after_load` on the DENIED pass -- was captured on
// 2026-08-27 to guard exactly this and then read by nothing for two days.
// ---------------------------------------------------------------------------
const WRITTEN = 'C0001:1,C0002:0,C0003:0,C0004:0,C0005:0';

// THE MISTAKE THIS GUARDS. C0001 is Strictly Necessary and comes back `:1` on
// every site, denied or not. Reading run 1322 by hand without excluding it
// flagged all 27 sites as "denial overwritten". If this check ever fails, the
// helper has started counting the mandatory group.
check('the mandatory group coming back granted is not an overwrite',
      denialOutcome(WRITTEN, 'C0001:1,C0002:0,C0003:0,C0004:0,OSSTA_BG:0').denied === true);
check('...and the same holds on the numeric group schema',
      denialOutcome(WRITTEN, '1:1,2:0,4:0').denied === true);

// The case the guard exists for: OneTrust recomputing consent to GRANTED.
const overwritten = denialOutcome(WRITTEN, 'C0001:1,C0002:1,C0003:0,C0004:1');
check('a real overwrite is reported as not denied', overwritten.denied === false);
check('...and names which groups came back granted',
      JSON.stringify(overwritten.granted) === JSON.stringify(['C0002', 'C0004']),
      JSON.stringify(overwritten.granted));
check('...and says the pass proved nothing, rather than leaving it to be inferred',
      /proves nothing/.test(overwritten.note || ''), overwritten.note);

// UNKNOWN IS A VALUE. The cold and click passes write no cookie, so the
// question does not apply to them -- `false` there would be a value standing
// in for "not asked", which is this repo's one bug.
check('a pass that wrote no cookie reports null, not false',
      denialOutcome(null, 'C0001:1,C0002:0') === null);
check('no OptanonConsent after load is unknown, not denied',
      denialOutcome(WRITTEN, null).denied === null);

// The second unknown: our C000x cookie replaced by a numeric-schema one. The
// end state is denied, but it may be the site's default rather than ours.
const replaced = denialOutcome(WRITTEN, '1:1,2:0,4:0');
check('a replaced cookie schema is flagged', replaced.schema_matched === false);
check('...and says the denial may be the site default, not ours',
      /site default/.test(replaced.note || ''), replaced.note);
check('a matching schema is not flagged',
      denialOutcome(WRITTEN, 'C0001:1,C0002:0,C0003:0,C0004:0,OSSTA_BG:0')
        .schema_matched === true);

// The fixture. Tracker URLs are local paths containing the real patterns:
//   /t/clarity.ms/collect            -> "MS Clarity"   (fires during every load)
//   /t/google-analytics.com/g/collect?gcs=G100         (fires during every load)
//   /t/facebook.com/tr?from=oldpage  -> "Meta Pixel"   (fires ONLY from the old
//                                       page, 500ms after the Reject click)
// The slow image holds the load event back ~250ms so the load-phase fetches
// are unambiguously issued before it -- which is exactly the window v2 erased.
const PAGE = `<!doctype html>
<meta charset="utf-8">
<title>gating window fixture</title>
<script>
  fetch('/t/clarity.ms/collect');
  fetch('/t/google-analytics.com/g/collect?gcs=G100');
</script>
<img src="/slow.png" alt="">
<button id="onetrust-reject-all-handler">Reject All</button>
<script>
  document.getElementById('onetrust-reject-all-handler').addEventListener('click', () => {
    document.cookie = 'fixture_rejected=1; path=/';
    setTimeout(() => fetch('/t/facebook.com/tr?from=oldpage'), 500);
  });
</script>`;

const log = [];
const server = createServer((req, res) => {
  log.push(req.url);
  if (req.url === '/' || req.url.startsWith('/?')) {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(PAGE);
  } else if (req.url.startsWith('/slow.png')) {
    setTimeout(() => { res.writeHead(200, { 'content-type': 'image/png' }); res.end(); }, 250);
  } else {
    res.writeHead(204);
    res.end();
  }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ headless: true });
// Short waits: the property under test is the window's BOUNDARIES, not its
// duration. They only need to clear the fixture's own timings (250ms image,
// 500ms old-page beacon). An older pass() that ignores this argument just
// runs the production waits and the assertions still hold.
const waits = { settleMs: 1000, persistMs: 1500, measureMs: 1200 };

console.log('-- control: the fixture fires during load at all --');
const cold = await pass(browser, url, null, 'fixture cold load', null, waits);
check('cold load sees the load-phase tracker', cold.fired.includes('MS Clarity'),
      JSON.stringify(cold.fired));
check('cold load sees the load-phase G100 ping', cold.gcs.includes('G100'),
      JSON.stringify(cold.gcs));
check('cold load never sees the click-only beacon', !cold.fired.includes('Meta Pixel'),
      JSON.stringify(cold.fired));

console.log('\n-- the click pass: both boundaries of the measured window --');
const rejected = await pass(browser, url, null, 'fixture click pass',
                            '#onetrust-reject-all-handler', waits);
check('the pass completed', rejected.error === null && rejected.status === 200,
      `error=${rejected.error} status=${rejected.status}`);
// THE v2 DEFECT: a tracker firing during the consent-denied load's own load
// phase must be IN the window. Under v2 it was recorded and then erased.
check('a tracker firing during the consent-denied load is measured',
      rejected.fired.includes('MS Clarity'), JSON.stringify(rejected.fired));
check('a load-phase cookieless G100 ping is measured',
      rejected.gcs.includes('G100'), JSON.stringify(rejected.gcs));
// THE v1 DEFECT: the old page finishing its work after the click must stay
// OUT of the window. This is the Clarity-flush case that reached Nick.
check('the old page\'s post-click beacon stays outside the window',
      !rejected.fired.includes('Meta Pixel'), JSON.stringify(rejected.fired));
check('...and that beacon really was sent, so the exclusion is not vacuous',
      log.some(u => u.startsWith('/t/facebook.com/tr')), log.join(' '));
check('the rejection state persisted into the measured load',
      rejected.cookieNames.includes('fixture_rejected'),
      JSON.stringify(rejected.cookieNames));
check('the page was loaded twice: once to click, once to measure',
      log.filter(u => u === '/' || u.startsWith('/?')).length >= 2,
      log.join(' '));

await browser.close();
server.close();
console.log(`\n${ok} passed, ${bad} failed`);
process.exit(bad ? 1 : 0);
