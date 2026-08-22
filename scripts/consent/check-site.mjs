// Deterministic consent-coverage scanner. Read-only: loads the public homepage,
// observes what fires before any consent interaction, detects consent tooling.
// Returns JSON on stdout. No AI, no writes, no logins.
import { chromium } from 'playwright';

const domain = process.argv[2];
if (!domain) {
  console.error('usage: node check-site.mjs <domain> [headless]');
  console.error('Default is HEADED. Headless cannot see sites behind a bot');
  console.error('challenge, and misses trackers that detect automation.');
  process.exit(2);
}

const TRACKER_PATTERNS = [
  { name: 'GA4 collect',        re: /google-analytics\.com\/(g|j)\/collect|analytics\.google\.com\/g\/collect/ },
  { name: 'DoubleClick',        re: /stats\.g\.doubleclick\.net|googleads\.g\.doubleclick\.net\/pagead/ },
  { name: 'Meta Pixel',         re: /facebook\.com\/tr[/?]/ },
  { name: 'MS Clarity',         re: /clarity\.ms\/(collect|eus|s)/ },
  { name: 'Hotjar',             re: /hotjar\.(com|io)\/api|content\.hotjar\.io/ },
  { name: 'LinkedIn Insight',   re: /px\.ads\.linkedin\.com/ },
  { name: 'Bing UET',           re: /bat\.bing\.com\/action/ },
  { name: 'TikTok',             re: /analytics\.tiktok\.com/ },
  { name: 'Pinterest',          re: /ct\.pinterest\.com/ },
];

const BANNER_VENDORS = [
  { name: 'OneTrust',   scriptRe: /cookielaw\.org|onetrust/i, sel: '#onetrust-banner-sdk' },
  { name: 'Cookiebot',  scriptRe: /consent\.cookiebot\.com/i, sel: '#CybotCookiebotDialog' },
  { name: 'CookieYes',  scriptRe: /cookieyes\.com/i,          sel: '.cky-consent-container' },
  { name: 'Complianz',  scriptRe: /complianz/i,               sel: '#cmplz-cookiebanner-container' },
  { name: 'Osano',      scriptRe: /osano\.com/i,              sel: '.osano-cm-window' },
  { name: 'Termly',     scriptRe: /termly\.io/i,              sel: '#termly-code-snippet-support' },
  { name: 'Iubenda',    scriptRe: /iubenda\.com/i,            sel: '#iubenda-cs-banner' },
];

// NOTE ON THE 9-SECOND WAIT below: it is a judgement, not a measurement. Tag
// managers fire late, and a shorter wait would under-report leaks -- which is
// the direction that reads as an all-clear. If a site is ever suspected of
// firing later than this, raise it here rather than concluding the site is
// clean.
// HEADED BY DEFAULT. Headless is an explicit opt-out, and that default is the
// whole point of this block.
//
// Measured 2026-08-22, six sites across five configurations. Headless bundled
// Chromium, headless real Chrome (`channel: 'chrome'`), and headless with
// --disable-blink-features=AutomationControlled all scored 0 of 6 against
// sites behind a Cloudflare bot challenge. Headed scored 6 of 6 -- bundled
// Chromium and real Chrome alike. So the variable is HEADLESS, not the browser
// binary, not the User-Agent and not the source IP. Across all 28 sites the
// sweep could not see, 27 load headed. (The 28th, hitsfoundation.org, fails
// TLS negotiation: a real finding, and not this one.)
//
// AND IT IS NOT ONLY A COVERAGE PROBLEM. On blockclub.co, which headless could
// already see, headless reports 4 pre-consent trackers and headed reports 6,
// reproducibly. Hotjar and Meta Pixel run their own headless detection and
// decline to fire, so headless cannot see them on ANY site. Every headless
// number was a floor, not a total -- an undercount, in the direction that
// reads as an all-clear.
//
// Headed needs a display. On a laptop that means visible windows; in CI it
// means xvfb, which is deliberately not wired up yet because it has not been
// proven on a runner.
const browserMode = process.argv[3] === 'headless' ? 'headless' : 'headed';

// What was REQUESTED (browserMode) and what we actually GOT (browserActual)
// are recorded separately. In CI headed only works because xvfb supplies a
// virtual screen; if that is missing the run could otherwise produce headless
// numbers wearing a headed label, which is this project's signature bug with
// our own handwriting on it. A headless Chromium says `HeadlessChrome/...` in
// its User-Agent and a headed one says `Chrome/...`, so the browser itself is
// the witness.
const result = { domain, browserMode, browserActual: null, finalUrl: null, ok: false, error: null,
  bannerVendor: null, bannerVisible: false, genericBannerVisible: false,
  preConsentTrackers: [], consentModeDenied: false, scripts: [], scannedAt: new Date().toISOString() };

// Browser path: honour PLAYWRIGHT_CHROMIUM_PATH when set, otherwise let
// Playwright find its own install. The pilot hardcoded a container path, which
// works in exactly one environment and fails on a laptop with an error that
// reads like a Playwright bug rather than a wrong path.
//
// This stays the ONLY environment variable this file reads. test-consent.py
// asserts that, because a scanner that reads the environment is a scanner that
// can read a credential. The mode is an argument for the same reason.
const launchOpts = {
  headless: browserMode === 'headless',
  ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
    : {}),
};
const browser = await chromium.launch(launchOpts);
try {
  const ctx = await browser.newContext({ locale: 'en-US', viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage();
  const hits = [];
  page.on('request', req => {
    const u = req.url();
    for (const t of TRACKER_PATTERNS) if (t.re.test(u)) hits.push({ tracker: t.name, url: u.slice(0, 220) });
  });
  // Read before navigating: it is a property of the browser, not the site, and
  // it must be recorded even when the page then fails to load.
  const ua = await page.evaluate(() => navigator.userAgent);
  result.browserActual = /headless/i.test(ua) ? 'headless' : 'headed';

  const resp = await page.goto('https://' + domain, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(9000); // let tag managers and late tags fire
  result.finalUrl = page.url();
  result.status = resp ? resp.status() : null;

  // consent-mode: GA hits carrying gcs=G1xx with denied storage are cookieless pings
  for (const h of hits) {
    if (/GA4|DoubleClick/.test(h.tracker) && /[?&]gcs=G1[01]0/.test(h.url)) result.consentModeDenied = true;
  }
  // dedupe trackers
  const seen = new Set();
  result.preConsentTrackers = hits.filter(h => { const k = h.tracker; if (seen.has(k)) return false; seen.add(k); return true; });

  // banner vendor detection: scripts + rendered element
  const scriptSrcs = await page.evaluate(() => [...document.scripts].map(s => s.src).filter(Boolean));
  // Kept in the output on purpose. "No banner vendor detected" and "no consent
  // tooling exists" are different claims, and only this list can tell them
  // apart: an unrecognised CMP still loads a script with a recognisable name.
  // Without it, a vendor we have not listed reads as a site with nothing.
  //
  // The pattern deliberately does NOT match a bare /cookie/. The first real
  // sweep matched `js.cookie.min.js` -- a generic cookie-reading helper that
  // ships inside WooCommerce -- on three sites, and a reader seeing a non-empty
  // list there would reasonably conclude a CMP was present. A diagnostic that
  // produces false positives is worse than no diagnostic, because it gets
  // trusted.
  result.scripts = scriptSrcs.filter(s => /onetrust|cookielaw|cookiebot|complianz|osano|termly|iubenda|cookieyes|usercentrics|didomi|quantcast|trustarc|klaro|borlabs|cmplz|moove|civic|termsfeed|cookie-?law|consent-?manager|cookie-?notice|cookie-?consent/i.test(s)).slice(0, 8);
  for (const v of BANNER_VENDORS) {
    const inScripts = scriptSrcs.some(s => v.scriptRe.test(s));
    const el = await page.$(v.sel);
    const visible = el ? await el.isVisible().catch(() => false) : false;
    if (inScripts || visible) { result.bannerVendor = v.name; result.bannerVisible = visible; break; }
  }
  if (!result.bannerVendor) {
    // generic banner heuristic: a visible fixed element mentioning cookies with a button
    result.genericBannerVisible = await page.evaluate(() => {
      const els = [...document.querySelectorAll('div,section,aside,dialog')].slice(0, 800);
      return els.some(e => {
        const st = getComputedStyle(e);
        if (st.display === 'none' || st.visibility === 'hidden') return false;
        if (!/fixed|sticky/.test(st.position)) return false;
        const t = (e.innerText || '').toLowerCase();
        return t.length < 1500 && /cookie|consent/.test(t) && e.querySelector('button, a[role=button], input[type=button]');
      });
    });
    if (result.genericBannerVisible) result.bannerVisible = true;
  }
  result.ok = true;
} catch (err) {
  result.error = String(err.message || err).slice(0, 200);
} finally {
  await browser.close();
}
console.log(JSON.stringify(result));
