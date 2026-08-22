// run-sweep.mjs - fleet-wide cookie-consent coverage sweep.
//
// Read-only. Zero credentials. Loads each public homepage, watches what fires
// BEFORE any consent interaction, and records which consent tooling is present.
//
// THE ROSTER IS data/fleet-inventory.json AND NOTHING ELSE.
// The pilot carried its own sites.yaml, built from the 12 Harvest project names
// that happened to contain a domain. Reconciling it against the inventory on
// 2026-08-19 found two wrong entries out of twelve:
//
//   morrisoncontainerhandlingsolutions.com   does not resolve. No such host.
//   hoosierfeedercompany.com                 302s to hoosierfeeder.com
//
// A one-in-six error rate, on the list that decides what gets watched at all.
// That is the Zehnder lesson stated as a data problem: the sweep can only watch
// what the roster names, so a second roster is a second place to be wrong.
// There is now one roster. Do not add another.
//
// WHY NODE AND PLAYWRIGHT, in a repo whose contract is stdlib-Python-only:
// there is no way to observe what a page requests before consent without
// running the page. This is the one workflow that genuinely needs a browser,
// and the exception is stated here rather than discovered later.
//
// Usage:
//   node scripts/consent/run-sweep.mjs \
//     --inventory data/fleet-inventory.json --out reports \
//     --stamp "$(date -u +%Y-%m-%d_%H%M)" [--concurrency 4] [--only a.com,b.com]
//
// Runs a HEADED browser, so it needs a display: on a laptop that means visible
// windows for the duration. `--headless` opts out and is kept only for a
// display-less environment; it UNDERCOUNTS, and the run records which was used.

import { execFile } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const CHECKER = join(HERE, 'check-site.mjs');

function arg(name, fallback = null) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const INVENTORY = arg('inventory', 'data/fleet-inventory.json');
const OUT = arg('out', 'reports');
const STAMP = arg('stamp');
// Parallel browsers. Default 4. Verified headed at 4 on 2026-08-22: 12 sites
// in 6 seconds, no instability.
//
// The old note here argued against raising it because "23 of ~78 sites already
// answer 403 to a headless client". That premise is gone -- those 403s were a
// bot challenge that headless could never pass and headed passes, not a WAF
// reacting to crawl rate. Raising it is still a poor trade for a different
// reason: a blocked site is UNMEASURED, so speed would be bought with the one
// thing this tool produces. The run is ~4 minutes at 4 regardless, because each
// site carries a fixed 9-second settle that no parallelism removes.
const CONCURRENCY = Number(arg('concurrency', '4'));
const ONLY = arg('only');

// HEADED unless --headless is passed. See check-site.mjs for the measurements:
// headless cannot load 27 of the 28 sites behind a bot challenge, and cannot
// see Hotjar or Meta Pixel on ANY site because those two detect automation and
// decline to fire. A headless run is therefore an undercount, and low is the
// direction that reads as an all-clear.
//
// The mode is recorded on the run as `method`, because the ledger must never
// diff a headed run against a headless one: the tracker counts are not
// comparable, and 4-becoming-6 is new visibility, not a new problem.
const HEADLESS = process.argv.includes('--headless');
const METHOD = HEADLESS ? 'chromium-headless' : 'chromium-headed';

if (!STAMP) {
  console.error('--stamp is required (UTC, YYYY-MM-DD_HHMM).');
  console.error('The ledger takes run identity from the filename, so it is not cosmetic.');
  process.exit(2);
}

// ---------------------------------------------------------------------------
// Roster
// ---------------------------------------------------------------------------

const inv = JSON.parse(readFileSync(INVENTORY, 'utf8'));

// A site_id is only scannable if it is a real domain. Six inventory entries are
// Pantheon machine names with no domain at all, and they are REPORTED as
// skipped rather than silently dropped: a site missing from a coverage sweep
// with no explanation is indistinguishable from a site that passed.
const looksLikeDomain = d => typeof d === 'string' && /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(d);

const skipped = [];
let roster = [];
for (const s of inv.sites) {
  const d = (s.domain || '').toLowerCase();
  if (!looksLikeDomain(d)) {
    skipped.push({ site_id: s.site_id, reason: 'no scannable domain in the inventory' });
    continue;
  }
  roster.push({ domain: d, site_id: s.site_id, host: s.host || null, client: s.client || null });
}

if (ONLY) {
  const want = new Set(ONLY.split(',').map(x => x.trim().toLowerCase()));
  roster = roster.filter(r => want.has(r.domain));
}

console.error(`roster: ${roster.length} scannable, ${skipped.length} skipped, from ${INVENTORY}`);
console.error(`browser: ${METHOD}${HEADLESS ? '  (UNDERCOUNTS -- see check-site.mjs)' : ''}`);

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

function scanOnce(domain) {
  return new Promise(res => {
    execFile('node', HEADLESS ? [CHECKER, domain, 'headless'] : [CHECKER, domain],
      { timeout: 120000, maxBuffer: 8 * 1024 * 1024 },
      (err, stdout) => {
        if (stdout) {
          try { return res(JSON.parse(stdout.trim().split('\n').pop())); } catch (_) { /* fall through */ }
        }
        res({ domain, ok: false, error: err ? String(err.message).slice(0, 200) : 'no output from the checker' });
      });
  });
}

// A NAVIGATION THAT DID NOT THROW IS NOT A SITE THAT WAS SEEN.
//
// The first real sweep, 2026-08-19, found 23 of 78 sites answering HTTP 403 --
// a WAF refusing the headless client. Every one recorded "no banner, no
// trackers", because that is what an error page contains, and the
// classification read all 23 as clean. Thirty per cent of the fleet reported as
// having nothing to fix, on the evidence of a block page.
//
// So `ok` means the scanner SAW THE SITE, and that requires a 2xx.
//
// APPLIED HERE, in scan(), NOT in the summary loop. It used to run after every
// worker had finished, so the live progress line printed `ok` for a site that
// had returned 403 and only the summary corrected it. A four-site run on
// 2026-08-22 logged "ok" four times and then "scanned 0 of 4". The rule was
// right and ran too late to reach the line a person actually watches -- which
// is the same defect it exists to prevent, in our own output.
//
// It also means the retry below reacts to a 403, instead of treating it as
// success and never retrying.
function markSeen(r) {
  const twoXX = typeof r.status === 'number' && r.status >= 200 && r.status < 300;
  if (r.ok && !twoXX) {
    r.ok = false;
    r.error = r.error || ('HTTP ' + r.status + ': the server refused the request, so the '
      + 'scanner saw an error page rather than the site');
    r.httpBlocked = true;
  }
  return r;
}

// One retry, and the retry is recorded. A site that only ever answers on the
// second attempt is a different thing from one that answers first time, and
// hiding that would make an intermittent site look stable.
async function scan(domain) {
  let r = markSeen(await scanOnce(domain));
  if (!r.ok) {
    const first = r.error;
    r = markSeen(await scanOnce(domain));
    r.retried = true;
    if (!r.ok && !r.error) r.error = first;
  }
  return r;
}

// ASKED FOR IS NOT GOT. Checked on the first result that carries an answer,
// then never again -- one launch decides it for the whole run.
//
// If headed was requested and the browser came up headless, every number after
// this point would be an undercount labelled `chromium-headed`: wrong, and
// wrong in the direction that reads as an all-clear, under a label we wrote
// ourselves. In CI that happens the moment xvfb is missing or DISPLAY is
// unset. Abort rather than write it to an append-only ledger.
let verified = false;
function verifyBrowser(r) {
  if (verified || !r || !r.browserActual) return;
  verified = true;
  if (r.browserActual === browserModeWanted()) return;
  console.error('');
  console.error(`ABORTING: asked for a ${browserModeWanted()} browser and got ${r.browserActual}.`);
  console.error('Every result from this run would be an undercount carrying the wrong label.');
  console.error('On a server this means no display: install xvfb and run under `xvfb-run -a`,');
  console.error('or pass --headless deliberately and accept that the numbers are a floor.');
  process.exit(3);
}
function browserModeWanted() { return HEADLESS ? 'headless' : 'headed'; }

const results = [];
const queue = [...roster];
let done = 0;

async function worker() {
  while (queue.length) {
    const s = queue.shift();
    const r = await scan(s.domain);
    verifyBrowser(r);
    r.site_id = s.site_id;
    r.host = s.host;
    r.client = s.client;
    results.push(r);
    done += 1;
    console.error(`  [${done}/${roster.length}] ${s.domain} ${r.ok ? 'ok' : 'FAILED: ' + (r.error || '').slice(0, 80)}`);
  }
}

await Promise.all(Array.from({ length: Math.max(1, CONCURRENCY) }, worker));

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------
// Deliberately NOT a compliance verdict. This records what was observed:
// whether consent tooling was detected, and what fired before any consent
// interaction. The words "compliant" and "non-compliant" do not appear
// anywhere in this workflow, and must not be added. Severity is derived later,
// from the facts, in scripts/lib/severity.py.

for (const r of results) {
  // A consent-mode-denied GA ping is a cookieless signal, not a tracker firing
  // with storage. Counting it as a pre-consent tracker would flag every site
  // that has Consent Mode configured CORRECTLY, which is backwards.
  const real = (r.preConsentTrackers || []).filter(
    t => !(r.consentModeDenied && /GA4|DoubleClick/.test(t.tracker)));
  r.realPreConsentTrackers = real.map(t => t.tracker).sort();
  r.bannerDetected = Boolean(r.bannerVendor) || Boolean(r.genericBannerVisible);

}

const scan_out = {
  kind: 'consent-sweep',
  // Bumped to /2 on 2026-08-22 with the move to a headed browser. The payload
  // gained `method`, and the numbers changed MEANING: a /1 run is a floor, a
  // /2 headed run is a total. A consumer that treats them as the same series
  // will read new visibility as a regression.
  schema: 'consent-sweep/2',
  method: METHOD,
  roster_source: INVENTORY,
  run_stamp: STAMP,
  eligible: roster.length,
  scanned_ok: results.filter(r => r.ok).length,
  skipped_no_domain: skipped,
  sites: results.map(r => ({
    domain: r.domain,
    site_id: r.site_id,
    ok: Boolean(r.ok),
    error: r.error || null,
    retried: Boolean(r.retried),
    browserActual: r.browserActual || null,
    status: r.status ?? null,
    httpBlocked: Boolean(r.httpBlocked),
    finalUrl: r.finalUrl || null,
    // The consent-related script srcs the page loaded. Distinguishes "no CMP"
    // from "a CMP we do not recognise", which the vendor list alone cannot.
    cmpScripts: r.scripts || [],
    bannerVendor: r.bannerVendor || null,
    bannerVisible: Boolean(r.bannerVisible),
    genericBannerVisible: Boolean(r.genericBannerVisible),
    bannerDetected: Boolean(r.bannerDetected),
    preConsentTrackers: r.realPreConsentTrackers || [],
    consentModeDenied: Boolean(r.consentModeDenied),
  })),
};

if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });
const path = join(OUT, `fleet-consent-${STAMP}.json`);
writeFileSync(path, JSON.stringify(scan_out, null, 2));

// ---------------------------------------------------------------------------
// Summary. Coverage first, because a blank here is an unanswered question.
// ---------------------------------------------------------------------------

const ok = scan_out.sites.filter(s => s.ok);
const failed = scan_out.sites.filter(s => !s.ok);
const blocked = failed.filter(s => s.httpBlocked);
const leaking = ok.filter(s => s.preConsentTrackers.length > 0);
const noTooling = ok.filter(s => !s.bannerDetected);

console.log('');
console.log(`Consent coverage sweep  (${METHOD})`);
console.log(`  roster            ${roster.length} scannable, ${skipped.length} with no domain`);
console.log(`  scanned           ${ok.length} of ${roster.length}`);
console.log(`  could not scan    ${failed.length}   (never counts as a pass)`);
console.log(`    of which blocked  ${blocked.length}   HTTP 4xx/5xx: a WAF refused the scanner`);
console.log('');
console.log(`  trackers before consent   ${leaking.length}`);
console.log(`  no consent tooling seen   ${noTooling.length}`);
console.log('');
for (const s of leaking.sort((a, b) => b.preConsentTrackers.length - a.preConsentTrackers.length)) {
  console.log(`  LEAK  ${s.domain.padEnd(38)} ${s.bannerVendor || (s.genericBannerVisible ? 'generic banner' : 'no banner')}  <- ${s.preConsentTrackers.join(', ')}`);
}
if (noTooling.length) {
  console.log('');
  for (const s of noTooling) console.log(`  NO TOOLING  ${s.domain}`);
}
if (failed.length) {
  console.log('');
  for (const s of failed) console.log(`  UNSCANNED   ${s.domain.padEnd(38)} ${(s.error || '').split('\n')[0].slice(0, 90)}`);
}
if (skipped.length) {
  console.log('');
  for (const s of skipped) console.log(`  SKIPPED     ${s.site_id.padEnd(38)} ${s.reason}`);
}
console.log('');
console.log('These are technical observations against a defined standard. They are');
console.log('not legal conclusions and they do not certify compliance.');
console.log('');
console.log(`-> ${path}`);
