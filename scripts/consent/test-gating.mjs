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
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

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

// OneTrust stores consent in OptanonConsent. C0001 is strictly necessary and
// cannot be switched off; C0002 performance, C0003 functional, C0004
// targeting, C0005 social. All-denied except the mandatory group is what a
// visitor who refuses everything looks like.
const DENIED_GROUPS = 'C0001:1,C0002:0,C0003:0,C0004:0,C0005:0';

// STRICTLY NECESSARY IS ALWAYS GRANTED. `C0001` -- or bare `1` on sites using
// OneTrust's numeric group IDs -- cannot be switched off, so it comes back
// `:1` on every site including a fully denied one. A predicate that asks "did
// any group come back granted" therefore flags all 27 sites and means nothing.
// Written down because that is exactly the mistake made reading run 1322 by
// hand on 2026-08-28.
const NECESSARY_GROUPS = new Set(['C0001', '1']);

// WAS THE PAGE ACTUALLY LOADED UNDER A DENIAL?
//
// The synthetic pass writes an all-denied OptanonConsent and OneTrust's own
// script then recomputes consent from its geolocation rules during load. Under
// an opt-out rule outside a restricted region it may legitimately OVERWRITE
// our denial with a granted one -- in which case the pass has proved NOTHING
// about gating and must say so, rather than letting the tags it then records
// read as a leak.
//
// That was already the stated contract in a comment above the pass, and
// `optanon_groups_after_load` was captured for it on 2026-08-27. Nothing read
// it: it is consumed only for the COLD pass, as `consent_groups_default`. A
// captured fact with an unkept promise, which is this repo's signature bug
// aimed at its own instrument. Measured 2026-08-28: the denial survived on all
// 27 sites, so nothing was being hidden -- but nothing was checking either.
//
// Returns null when no cookies were written, because the question does not
// apply to the cold or click passes and `false` there would be a value
// standing in for "not asked".
export function denialOutcome(writtenGroups, observedGroups) {
  if (!writtenGroups) return null;              // cold and click passes
  if (!observedGroups) {
    // No OptanonConsent after load at all. Not denied, not granted: unread.
    return { denied: null, schema_matched: null, granted: [],
             note: 'no OptanonConsent cookie after load' };
  }
  const parse = g => g.split(',').map(p => p.split(':')).filter(p => p.length === 2);
  const written = parse(writtenGroups), observed = parse(observedGroups);
  const granted = observed
    .filter(([id, v]) => v === '1' && !NECESSARY_GROUPS.has(id))
    .map(([id]) => id);

  // DID OUR COOKIE EVEN APPLY? Six of the 27 sites answer with numeric group
  // IDs (`1:1,2:0,4:0`) while we write `C0001..C0005`. OneTrust replaced our
  // cookie wholesale. The end-of-load state may then be the SITE'S default
  // rather than our denial, and on an opt-out site those differ. Recorded as
  // its own fact rather than folded into `denied`, because the two answer
  // different questions and merging them is how an absence becomes a value.
  const ours = new Set(written.map(([id]) => id).filter(id => !NECESSARY_GROUPS.has(id)));
  const theirs = observed.map(([id]) => id).filter(id => !NECESSARY_GROUPS.has(id));
  const schema_matched = theirs.length === 0 ? null : theirs.some(id => ours.has(id));

  return {
    denied: granted.length === 0,
    schema_matched,
    granted,
    note: granted.length ? 'OneTrust overwrote the denial; this pass proves nothing about gating'
        : schema_matched === false ? 'denied at end of load, but OneTrust replaced our cookie: '
                                   + 'this may be the site default, not our denial'
        : null,
  };
}

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

// Exported so test/test-gating-window.mjs can drive the measured window
// against a local fixture page. The waits are parameters for the same reason:
// the window's BOUNDARIES are the contract, its durations are tuning, and the
// fixture only needs to outlast its own timings.
export async function pass(browser, url, cookies, label, clickSel,
                           { settleMs = 6000, persistMs = 3000, measureMs = 9000 } = {}) {
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
  });
  if (cookies) await ctx.addCookies(cookies);
  let page = await ctx.newPage();
  const hits = [];
  // GOOGLE'S CONSENT SIGNAL, captured rather than assumed. Under Consent Mode
  // a denied visitor still gets a GA/Ads request -- a COOKIELESS ping carrying
  // `gcs=G100`-style flags. That is the correct behaviour, not a leak, and
  // check-site.mjs already declines to count it as one. Without reading `gcs`
  // here, a correctly configured site and a leaking one look identical in the
  // denied pass, which is the exact ambiguity this script exists to remove.
  const gcs = [];
  const arm = p => p.on('request', r => {
    const u = r.url();
    for (const t of TRACKERS) if (t.re.test(u)) hits.push(t.name);
    const m = u.match(/[?&]gcs=(G1[01][01])/);
    if (m) gcs.push(m[1]);
  });
  arm(page);
  let error = null, status = null;
  try {
    const resp = await page.goto(url, { waitUntil: 'load', timeout: 45000 });
    status = resp ? resp.status() : null;
    // Tags fire on triggers that can lag load; the cold sweep waits too.
    await page.waitForTimeout(settleMs);
    if (clickSel) {
      // THE MEASURED WINDOW IS A FRESH PAGE, NOT A RELOAD. This is the third
      // version of this window; the first two were wrong in opposite
      // directions, so the boundaries are stated exactly:
      //
      // v1 cleared the counters BEFORE the reload. Scripts on the open page
      // keep working until navigation, so Clarity flushing its session buffer
      // after the click was counted as a tag ignoring consent. That reported
      // "MS Clarity still fires after Reject All" on two compliant sites, and
      // it reached Nick Federico as a finding.
      //
      // v2 cleared them AFTER page.reload({waitUntil:'load'}) resolved. The
      // load event fires after the fresh page's load-phase requests -- which
      // is where GA4 pageview hits normally fire -- so the clear ERASED the
      // exact load this test exists to measure, and the gcs=G100 pings with
      // it. "Nothing fires after rejection" is the best possible result, and
      // v2 manufactured it out of a window that excluded the load.
      //
      // v3: close the page and open a FRESH one on the same context. The
      // rejection cookie lives on the context, so the new page loads
      // consent-denied, and its listener exists before its first request, so
      // the whole load is inside the window. The window IS the measured
      // page's lifetime; there is no clear whose ordering can be wrong again.
      // This is the shape the synthetic-cookie pass has always had, which is
      // why that pass saw the G100 pings v2 could not.
      //
      // test/test-gating-window.mjs asserts BOTH boundaries against a local
      // fixture: a load-phase request IS measured, and the old page's
      // post-click beacon is NOT. It was run against v2 and failed before
      // this version existed.
      try {
        await page.click(clickSel, { timeout: 8000 });
      } catch (e) {
        error = `could not click ${clickSel}: ${e.message.split('\n')[0]}`;
      }
      if (!error) {
        // Let the rejection persist and the old page settle. Anything that
        // fires here is the PREVIOUS page finishing, and is deliberately not
        // measured.
        await page.waitForTimeout(persistMs);
        await page.close();
        hits.length = 0; gcs.length = 0;
        page = await ctx.newPage();
        arm(page);
        const resp2 = await page.goto(url, { waitUntil: 'load', timeout: 45000 });
        status = resp2 ? resp2.status() : status;
        await page.waitForTimeout(measureMs);
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
  const observed = groups ? groups[1] : null;
  // The cookies we wrote, if any, so denialOutcome can compare schemas rather
  // than assume the site uses the group IDs we sent.
  const writtenOptanon = (cookies || []).find(c => c.name === 'OptanonConsent');
  const written = writtenOptanon
    ? (decodeURIComponent(writtenOptanon.value).match(/groups=([^&]*)/) || [])[1] || null
    : null;
  return { label, status, error, fired: [...new Set(hits)].sort(),
           // G100 = both storage types denied. G111 = both granted.
           gcs: [...new Set(gcs)].sort(),
           optanon_groups_after_load: observed,
           // Null on the cold and click passes: they write no cookie, so the
           // question does not apply. See denialOutcome.
           denial: denialOutcome(written, observed),
           cookieNames };
}

// The CLI half. Guarded so importing pass() from a test does not launch a
// browser at a real site -- run-gating-sweep.mjs spawns this file as a
// subprocess and takes this path.
const RUN_AS_CLI = process.argv[1]
  && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (RUN_AS_CLI) {

const domain = process.argv[2];
if (!domain) {
  console.error('usage: node test-gating.mjs <domain>');
  process.exit(2);
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

}
