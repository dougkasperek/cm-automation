#!/usr/bin/env node
// Can the gating sweep actually CATCH a leak?
//
// WHY THIS EXISTS
// ---------------
// This instrument has reported ZERO leaks on every fleet run it has ever done:
// 18 of 27 tested, 0 leaking, reproduced three times across 2026-08-28. That
// number may well be true. Nothing proved it.
//
// And the direction matters. "Nothing fires after rejection" is the BEST
// POSSIBLE RESULT of this test, and this instrument has been wrong twice
// before in exactly that direction:
//
//   v1 cleared its counters BEFORE the post-rejection reload, so the old
//      page's tail was counted as a leak -- wrong the other way, and it went
//      to a client contact as a finding.
//   v2 cleared them AFTER the reload's load event, erasing the load phase it
//      exists to measure. It reported "0 of 23 still fire" over data that had
//      G100 pings in it.
//
// Both passed every test that existed at the time, because every test asked
// whether a CLEAN site reads clean. None planted a leak and demanded it be
// found. So "0 leaking" has been UNFALSIFIED, not verified -- and on
// 2026-08-28 Doug declined to send the fleet numbers to Nick Federico over
// exactly this, which is the correct call on the evidence available.
//
// This test plants three sites and requires the verdict to tell them apart:
//
//   LEAKY     ignores the rejection completely. Every tag fires again on the
//             consent-denied load. MUST come out as a leak, by name.
//   COMPLIANT stops every tag except a Google request that switches to a
//             cookieless gcs=G100 ping. MUST come out GATED, NOT a leak --
//             docs/CONSENT.md has ruled since the first sweep that a G100
//             ping is what a correctly configured site does.
//   PARTIAL   stops some tags and keeps one non-Google tag firing. MUST be a
//             leak naming only that tag, so the exclusion cannot be a blanket
//             "ignore anything that also fired on load".
//
// The third is the one that would have caught the real regression: on
// 2026-08-27 the G100 exclusion was dropped during a rewrite and 9 sites were
// reported NOT FULLY GATED when the true answer was 2.
//
// Offline. Tracker URLs are local paths on 127.0.0.1 crafted to match the real
// patterns, so nothing leaves the machine.
//
//   node test/test-gating-leak.mjs
//
// Needs `npm i` (playwright). Headless is fine: the headed requirement exists
// because real vendors decline to fire under automation, and a fixture is not
// a real vendor.
import { createServer } from 'node:http';
import { chromium } from 'playwright';
import { pass, gatingVerdict } from '../scripts/consent/test-gating.mjs';

let ok = 0, bad = 0;
const check = (name, cond, detail = '') => {
  if (cond) { ok++; console.log('ok    ' + name); }
  else { bad++; console.log('FAIL  ' + name + (detail ? '  <- ' + String(detail).slice(0, 240) : '')); }
};

// A rejection is remembered in a cookie, exactly as OneTrust does it, so the
// FRESH page the click pass measures knows the visitor already refused. That
// is the whole mechanism under test: v3 measures a new page on the same
// context, and without a persisted rejection there would be nothing to honour.
const REJECTED_COOKIE = 'fixture_rejected=1';

function page(mode) {
  // `mode` decides what the page does on a load where consent was denied.
  //   leaky     -> fire everything again
  //   compliant -> fire only a cookieless Google ping
  //   partial   -> fire the cookieless Google ping AND one real tracker
  return `<!doctype html>
<meta charset="utf-8">
<title>gating ${mode} fixture</title>
<script>
  var denied = document.cookie.indexOf('${REJECTED_COOKIE}') !== -1;
  if (!denied) {
    // Cold load: a normal-looking set of tags, and Google with consent granted.
    fetch('/t/clarity.ms/collect');
    fetch('/t/facebook.com/tr?id=1&ev=PageView');
    fetch('/t/google-analytics.com/g/collect?gcs=G111');
  } else if ('${mode}' === 'leaky') {
    // IGNORES THE REJECTION. Identical to the cold load.
    fetch('/t/clarity.ms/collect');
    fetch('/t/facebook.com/tr?id=1&ev=PageView');
    fetch('/t/google-analytics.com/g/collect?gcs=G111');
  } else if ('${mode}' === 'compliant') {
    // Correct: everything stops, Google switches to a cookieless ping.
    fetch('/t/google-analytics.com/g/collect?gcs=G100');
  } else {
    // PARTIAL: Google behaves, MS Clarity does not.
    fetch('/t/google-analytics.com/g/collect?gcs=G100');
    fetch('/t/clarity.ms/collect');
  }
</script>
<img src="/slow.png" alt="">
<button id="onetrust-reject-all-handler">Reject All</button>
<script>
  document.getElementById('onetrust-reject-all-handler').addEventListener('click', function () {
    document.cookie = '${REJECTED_COOKIE}; path=/';
  });
</script>`;
}

const log = [];
const server = createServer((req, res) => {
  log.push(req.url);
  const m = /^\/(leaky|compliant|partial)\b/.exec(req.url);
  if (m) {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(page(m[1]));
  } else if (req.url.startsWith('/slow.png')) {
    setTimeout(() => { res.writeHead(200, { 'content-type': 'image/png' }); res.end(); }, 200);
  } else {
    res.writeHead(204);
    res.end();
  }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ headless: true });
// Short waits: what is under test is the VERDICT, not the window's duration.
// The window's own boundaries are test-gating-window.mjs.
const waits = { settleMs: 800, persistMs: 800, measureMs: 1000 };

// Drive all three passes exactly as the CLI does, then score with the same
// function the CLI uses. Nothing here re-implements the verdict.
async function run(mode) {
  const url = `${base}/${mode}`;
  const cold = await pass(browser, url, null, 'cold load, no consent state', null, waits);
  const denied = await pass(browser, url, null, 'OneTrust set to all-denied', null, waits);
  const rejected = await pass(browser, url, null, 'real click on Reject All',
                              '#onetrust-reject-all-handler', waits);
  return gatingVerdict(cold, denied, rejected);
}

console.log('-- control: the fixture fires on a cold load at all --');
const leaky = await run('leaky');
check('the cold load saw tags, so there is something to gate',
      leaky.fires_on_cold_load.length >= 2, JSON.stringify(leaky.fires_on_cold_load));
check('...and the pass completed, so a failure cannot masquerade as clean',
      leaky.usable, leaky.verdict);

console.log('\n-- THE POINT: a site that ignores the rejection is caught --');
check('a leaking site is NOT reported as gated',
      !/^GATED/.test(leaky.verdict), leaky.verdict);
check('...it is reported as a leak',
      /NOT FULLY GATED/.test(leaky.verdict), leaky.verdict);
check('...and the tags are named, because the remedy is per-tag',
      ['MS Clarity', 'Meta Pixel'].every(t => leaky.still_firing_after_reject_all.includes(t)),
      JSON.stringify(leaky.still_firing_after_reject_all));
// GA4 IS a leak on this fixture and must be listed. The leaky page keeps
// sending gcs=G111 -- consent GRANTED -- after the visitor refused. The G100
// exclusion must not swallow that: it exempts a Google tag that switched to
// COOKIELESS, not any Google tag at all.
check('...including Google, because this one did NOT switch to cookieless',
      leaky.still_firing_after_reject_all.includes('GA4 collect'),
      JSON.stringify(leaky.still_firing_after_reject_all));
check('...and Google is not credited with honouring the denial',
      leaky.google_stopped_after_reject === false,
      String(leaky.google_stopped_after_reject));

console.log('\n-- and a compliant site is not slandered --');
const compliant = await run('compliant');
check('a site whose tags stop is reported GATED',
      /^GATED/.test(compliant.verdict), compliant.verdict);
check('...with nothing in the leak list',
      compliant.still_firing_after_reject_all.length === 0,
      JSON.stringify(compliant.still_firing_after_reject_all));
// THE 2026-08-27 REGRESSION, in test form. The G100 exclusion was dropped in a
// rewrite and 9 sites were reported NOT FULLY GATED when the answer was 2.
check('...and the cookieless Google ping is recorded, not silently dropped',
      compliant.cookieless_after_reject.length > 0,
      JSON.stringify(compliant.cookieless_after_reject));
check('...and Google is reported as having honoured the denial',
      compliant.google_stopped_after_reject === true);

console.log('\n-- the mixed case, which is the one that discriminates --');
const partial = await run('partial');
check('a site where ONE tag ignores consent is a leak',
      /NOT FULLY GATED/.test(partial.verdict), partial.verdict);
check('...naming only the offender',
      JSON.stringify(partial.still_firing_after_reject_all) === JSON.stringify(['MS Clarity']),
      JSON.stringify(partial.still_firing_after_reject_all));
// If the G100 rule were a blanket "ignore anything that fired on load", the
// Google request here would be listed as a leak too. It must not be.
check('...and NOT the compliant Google ping alongside it',
      !partial.still_firing_after_reject_all.some(t => /GA4|DoubleClick/.test(t)),
      JSON.stringify(partial.still_firing_after_reject_all));

await browser.close();
server.close();
console.log(`\n${ok} passed, ${bad} failed`);
process.exit(bad ? 1 : 0);
