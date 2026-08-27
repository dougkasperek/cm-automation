// Does OneTrust actually GATE the tags, or does it only draw a banner?
//
// WHY THIS EXISTS
// ---------------
// `check-site.mjs` does one cold page load and records what fired. That
// observation cannot distinguish two very different sites:
//
//   a site on an OPT-OUT model, correctly configured, where tags are
//   supposed to fire on load outside a geo-restricted region; and
//
//   a site where nobody gated the tags at all.
//
// Both produce "4 trackers fired before consent". Nick Federico, 2026-08-20:
// the correctness lives in the GTM trigger -- each tag's firing trigger is set
// to watch OneTrust's targeting-cookie state, so the tag itself asks whether
// it has permission. That is testable from outside, and it is testable
// WITHOUT knowing the site's consent model:
//
//   pass 1  cold load, no consent state        -> what fires by default
//   pass 2  OptanonConsent set to all-denied   -> what still fires
//
// If a tag is gated on the OneTrust groups, pass 2 suppresses it. If a tag
// fires identically in both passes, its trigger is not reading consent state
// -- which is a real defect on any model, opt-in or opt-out.
//
// READ-ONLY. Loads a public homepage twice and sets a cookie in a throwaway
// browser profile. Nothing is written to the site, and nothing persists.
//
// The tracker patterns are IMPORTED from check-site.mjs rather than copied.
// A second copy of the detection table is a second answer, and this repo has
// a table of what that costs.
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

// check-site.mjs is a script, not a module -- it runs on import. Read the
// patterns out of its source rather than executing it. Brittle by nature, so
// it asserts it found them rather than silently scanning for nothing.
const src = readFileSync(join(HERE, 'check-site.mjs'), 'utf8');
const block = src.match(/const TRACKER_PATTERNS = \[([\s\S]*?)\n\];/);
if (!block) {
  console.error('could not read TRACKER_PATTERNS out of check-site.mjs.');
  console.error('It moved or was renamed. Fix this rather than shipping a copy.');
  process.exit(2);
}
const TRACKERS = [...block[1].matchAll(/\{\s*name:\s*'([^']+)',\s*re:\s*(\/.*?\/)\s*\}/g)]
  .map(m => ({ name: m[1], re: new RegExp(m[2].slice(1, -1)) }));
if (TRACKERS.length < 5) {
  console.error(`only parsed ${TRACKERS.length} tracker pattern(s); expected the full table.`);
  process.exit(2);
}

const domain = process.argv[2];
if (!domain) {
  console.error('usage: node test-gating.mjs <domain>');
  process.exit(2);
}

// OneTrust stores consent in OptanonConsent. C0001 is strictly necessary and
// cannot be switched off; C0002 performance, C0003 functional, C0004
// targeting, C0005 social. All-denied except the mandatory group is what a
// visitor who refuses everything looks like.
const DENIED_GROUPS = 'C0001:1,C0002:0,C0003:0,C0004:0,C0005:0';

function optanonCookies(host) {
  const stamp = new Date(0).toISOString(); // fixed: no Date.now() in this repo
  const shared = { domain: `.${host}`, path: '/', expires: -1 };
  return [
    { ...shared, name: 'OptanonConsent',
      value: `isGpcEnabled=0&datestamp=${encodeURIComponent(stamp)}&version=202401.1.0`
             + `&isIABGlobal=false&consentId=00000000-0000-0000-0000-000000000000`
             + `&interactionCount=1&groups=${encodeURIComponent(DENIED_GROUPS)}` },
    // Presence of this cookie is what OneTrust reads as "the banner has been
    // answered", which is what stops it re-prompting and re-defaulting.
    { ...shared, name: 'OptanonAlertBoxClosed', value: stamp },
  ];
}

async function pass(browser, url, cookies, label, clickSel) {
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
  });
  if (cookies) await ctx.addCookies(cookies);
  const page = await ctx.newPage();
  const hits = [];
  // GOOGLE'S CONSENT SIGNAL, captured rather than assumed. Under Consent Mode
  // a denied visitor still gets a GA/Ads request -- a COOKIELESS ping carrying
  // `gcs=G100`-style flags. That is the correct behaviour, not a leak, and
  // check-site.mjs already declines to count it as one. Without reading `gcs`
  // here, a correctly configured site and a leaking one look identical in the
  // denied pass, which is the exact ambiguity this script exists to remove.
  const gcs = [];
  page.on('request', r => {
    const u = r.url();
    for (const t of TRACKERS) if (t.re.test(u)) hits.push(t.name);
    const m = u.match(/[?&]gcs=(G1[01][01])/);
    if (m) gcs.push(m[1]);
  });
  let error = null, status = null;
  try {
    const resp = await page.goto(url, { waitUntil: 'load', timeout: 45000 });
    status = resp ? resp.status() : null;
    // Tags fire on triggers that can lag load; the cold sweep waits too.
    await page.waitForTimeout(6000);
    if (clickSel) {
      // Clear what fired BEFORE the click. On an opt-out site everything fires
      // on load by design; the question is what fires AFTER a rejection.
      try {
        await page.click(clickSel, { timeout: 8000 });
        hits.length = 0; gcs.length = 0;
        await page.waitForTimeout(2000);
        await page.reload({ waitUntil: 'load', timeout: 45000 });
        await page.waitForTimeout(6000);
      } catch (e) {
        error = `could not click ${clickSel}: ${e.message.split('\n')[0]}`;
      }
    }
  } catch (e) {
    error = e.message.split('\n')[0];
  }
  const allCookies = await ctx.cookies();
  const cookieNames = allCookies.map(c => c.name);
  // DID OUR DENIAL SURVIVE? OneTrust's own script recomputes consent from its
  // geolocation rules on load. Under an opt-out rule outside a restricted
  // region it may legitimately OVERWRITE an all-denied cookie with a granted
  // one -- in which case this test has proved nothing about gating, and must
  // say so rather than reporting "not gated".
  const optanon = allCookies.find(c => c.name === 'OptanonConsent');
  const groups = optanon ? decodeURIComponent(optanon.value).match(/groups=([^&]*)/) : null;
  await ctx.close();
  return { label, status, error, fired: [...new Set(hits)].sort(),
           // G100 = both storage types denied. G111 = both granted.
           gcs: [...new Set(gcs)].sort(),
           optanon_groups_after_load: groups ? groups[1] : null, cookieNames };
}

const url = `https://${domain}/`;
// HEADED. Hotjar and Meta Pixel decline to fire under headless automation, so
// a headless run reports a floor as a total -- already a row in the bug table.
const browser = await chromium.launch({ headless: false });

const cold = await pass(browser, url, null, 'cold load, no consent state');
const denied = await pass(browser, url, optanonCookies(domain.replace(/^www\./, '')),
                          'OneTrust set to all-denied');
// THE DEFINITIVE PASS: click the real Reject button.
//
// Setting the cookie before load is not the same event as a visitor rejecting.
// Nick describes triggers that watch for OneTrust's targeting cookies being
// UPDATED -- and a cookie present at load never updates, so a trigger bound to
// the update event would never re-evaluate. A tag that ignores the pre-set
// cookie but honours a real click is correctly configured; the synthetic pass
// alone cannot tell those apart, and reporting it as "not gated" would be a
// confident value standing in for an untested one.
const rejected = await pass(browser, url, null, 'real click on Reject All',
                            '#onetrust-reject-all-handler');
await browser.close();

// THE CLICK PASS IS THE ANSWER. The synthetic-cookie pass is kept because it
// is diagnostic -- it shows which tags read consent STATE versus which need the
// update EVENT -- but it must not drive the verdict. On interstatewaste.com,
// 2026-08-27, the two disagreed: the cookie pass said GA4 and DoubleClick were
// ungated, and a real Reject All stopped both. Reporting the cookie pass as the
// finding would have sent someone after a defect that does not exist.
const usable = !cold.error && !rejected.error
  && cold.status && cold.status < 400 && rejected.status && rejected.status < 400;

// A GOOGLE TAG THAT KEEPS FIRING AT gcs=G100 IS NOT A LEAK. Under Consent
// Mode a denied visitor still gets a GA/Ads request; it is COOKIELESS, and it
// is what a correctly configured site does. docs/CONSENT.md has said so since
// the first sweep, and check-site.mjs already declines to count it.
//
// The first fleet-wide run, 2026-08-27, is why this is here: the verdict below
// was rewritten to be driven by the click pass and the G100 case was dropped in
// the rewrite. It reported NOT FULLY GATED on 9 sites when 7 of them had
// Google switching to cookieless exactly as designed. The real answer was 2.
const googleDenied = rejected.gcs.length > 0 && rejected.gcs.every(g => g === 'G100');
const stillFiring = rejected.fired.filter(
  t => !(googleDenied && /GA4|DoubleClick/.test(t)));
const compliantGoogle = rejected.fired.filter(t => !stillFiring.includes(t));
const stoppedByReject = cold.fired.filter(t => !rejected.fired.includes(t));

const out = {
  domain, url,
  passes: [cold, denied, rejected],
  // What the site does to a visitor who has done nothing. On an opt-out model
  // this is expected behaviour, not a finding, which is why it is reported as
  // an observation and never scored here.
  fires_on_cold_load: cold.fired,
  consent_groups_default: cold.optanon_groups_after_load,
  // The finding, if there is one.
  stopped_by_reject_all: stoppedByReject,
  // The finding. Google tags that switched to cookieless are NOT in here.
  still_firing_after_reject_all: stillFiring,
  // Reported separately so the distinction is visible rather than implied:
  // these fired, and firing was correct.
  cookieless_after_reject: compliantGoogle,
  google_stopped_after_reject: !rejected.gcs.length
    || rejected.gcs.every(g => g === 'G100'),
  // Diagnostic only. A tag that ignores a pre-set cookie but honours a click
  // is reading the update event, which is how OneTrust + GTM is normally wired.
  diagnostic_preset_cookie_pass: {
    fired: denied.fired,
    note: 'A pre-set cookie fires no update event, so a trigger bound to that '
        + 'event will not re-evaluate. Disagreement with the click pass is '
        + 'expected and is NOT a defect.',
  },
  usable,
  verdict: !usable
    ? 'INCONCLUSIVE: a pass did not load cleanly, or Reject All could not be clicked'
    : !cold.fired.length
      ? 'NOTHING FIRED on a cold load; there was nothing to gate'
      : !stillFiring.length
        ? 'GATED: everything that fired on load stopped after Reject All'
        : `NOT FULLY GATED: ${stillFiring.join(', ')} still fired after Reject All`,
};
console.log(JSON.stringify(out, null, 2));
