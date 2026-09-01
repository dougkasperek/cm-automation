// Fleet-wide consent GATING sweep: does rejecting actually stop the tags?
//
// WHAT THIS ANSWERS THAT THE COLD SWEEP CANNOT
// --------------------------------------------
// `run-sweep.mjs` loads each homepage once and records what fired. That
// observation cannot separate two very different sites:
//
//   an OPT-OUT site, correctly configured, where tags are meant to fire on
//   load outside a geo-restricted region; and
//
//   a site where nobody wired the consent state into the tag triggers.
//
// Both produce "4 trackers fired". On 2026-08-25 that ambiguity reported
// `interstatewaste.com` as leaking, and it is compliant.
//
// This sweep clicks REJECT ALL and reloads. A tag that stops is gated. A tag
// that fires identically is not reading consent state, and that is a defect on
// EITHER model -- which is why this test needs no ruling to interpret.
//
// IT RECORDS, IT DOES NOT SCORE.
// ------------------------------
// What counts as "pass" is a question for the people who configure these
// sites, and it has been asked and not yet answered: is "Reject All, then
// nothing fires except strictly necessary" the standard, or are there
// legitimate exceptions? Rather than guess, this writes what each tag DID and
// leaves the verdict to severity at render time -- which is where every other
// judgement in this system already lives. If the standard turns out to be
// different, the measurements stay true and only the rule changes.
//
// NOT READ-ONLY IN THE SENSE THE COLD SWEEP IS.
// ---------------------------------------------
// `check-site.mjs` never clicks, and test-consent.py asserts that. This one
// must click to ask its question. It clicks exactly one control -- the
// banner's own Reject button -- on a public page, in a throwaway browser
// profile. Nothing is submitted, no credential is read, nothing is written to
// the site. Reviewed on that basis 2026-08-27; if the scope of the clicking
// ever grows beyond a consent banner, it needs re-reviewing.
//
// SCOPE: only sites where the cold sweep DETECTED consent tooling. A site with
// no banner has no Reject button, so the question does not apply and a "could
// not click" result there would be noise indistinguishable from a failure.
import { execFile } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const TESTER = join(HERE, 'test-gating.mjs');

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const OUT = arg('out', 'reports');
const STAMP = arg('stamp');
const ONLY = arg('only');
const CONCURRENCY = Number(arg('concurrency', '3'));
const SITES_FILE = arg('sites');

if (!STAMP) {
  console.error('--stamp is required, e.g. --stamp "$(date -u +%Y-%m-%d_%H%M)"');
  console.error('The ledger derives a run\'s time from it; generating one here');
  console.error('would let two runs of the same sweep disagree about when.');
  process.exit(2);
}

// The roster comes from the LAST COLD SWEEP, not from the inventory: the
// question is only askable where a banner was actually seen. Passing --sites
// overrides it for a one-off.
let roster;
if (SITES_FILE) {
  roster = readFileSync(SITES_FILE, 'utf8').split('\n').map(s => s.trim()).filter(Boolean);
} else {
  const src = arg('from-scan');
  if (!src) {
    console.error('pass --from-scan reports/fleet-consent-<stamp>.json, or --sites <file>.');
    console.error('The roster is the set of sites where a banner was DETECTED;');
    console.error('a site with no banner has no Reject button and the question');
    console.error('does not apply to it.');
    process.exit(2);
  }
  const scan = JSON.parse(readFileSync(src, 'utf8'));
  roster = (scan.sites || [])
    .filter(s => s.ok && s.bannerDetected)
    .map(s => s.domain);
}
if (ONLY) roster = roster.filter(d => d === ONLY);
if (!roster.length) {
  console.error('no sites with detected consent tooling in the roster.');
  process.exit(2);
}

console.error(`gating sweep: ${roster.length} site(s) with consent tooling, `
              + `${CONCURRENCY} at a time`);

function testOnce(domain) {
  return new Promise(res => {
    execFile('node', [TESTER, domain],
      { timeout: 240000, maxBuffer: 8 * 1024 * 1024 },
      (err, stdout) => {
        if (stdout) {
          try { return res(JSON.parse(stdout.trim())); } catch (_) { /* fall through */ }
        }
        // A CRASH IS NOT A CLEAN SITE. Without this the catch-all would return
        // an object with no trackers in it, and "nothing fired after rejection"
        // is the best possible result -- so a failure would read as a pass.
        // EXIT 3 IS THE HEADED CHECK, NOT A SITE PROBLEM. test-gating.mjs
        // aborts with 3 when it asked for a headed browser and got headless,
        // which on a runner means xvfb is missing or DISPLAY is unset. That is
        // a fact about the RUN, not about this site, and recording it as one
        // INCONCLUSIVE row per site would bury it 27 times over while the
        // sweep carried on producing floors. Same reasoning as the ssh-agent
        // warning in diagnose-wp-calls.sh, which is reported before any
        // verdict because it explains all of them.
        if (err && err.code === 3) {
          console.error('');
          console.error('ABORTING THE SWEEP: the tester could not get a headed browser.');
          console.error('Every remaining site would report a floor, and a floor');
          console.error('reads as "nothing fires after rejection" -- a pass.');
          console.error('On a server: install xvfb and run under `xvfb-run -a`.');
          process.exit(3);
        }
        res({
          domain, usable: false,
          verdict: 'INCONCLUSIVE: the gating test did not complete',
          error: err ? String(err.message).slice(0, 200) : 'no output from the tester',
        });
      });
  });
}

const results = [];
const queue = [...roster];
let done = 0;

async function worker() {
  while (queue.length) {
    const d = queue.shift();
    const r = await testOnce(d);
    results.push(r);
    done += 1;
    const v = (r.verdict || '').split(':')[0];
    console.error(`  [${done}/${roster.length}] ${d}: ${v}`);
  }
}

await Promise.all(Array.from({ length: Math.max(1, CONCURRENCY) }, worker));
results.sort((a, b) => a.domain.localeCompare(b.domain));

const usable = results.filter(r => r.usable);
const out = {
  schema: 'fleet-consent-gating/1',
  stamp: STAMP,
  // The window changed 2026-08-28 (reload -> fresh consent-denied page; see
  // the v1/v2/v3 note in test-gating.mjs), so the method string changed WITH
  // it: the ledger refuses a baseline whose method differs, and the first run
  // of v3 must not be diffed against a v2 run that could not see the load
  // phase. One run with no baseline is the honest price.
  method: 'chromium-headed, cold load then real Reject All click, then a fresh consent-denied load',
  // THE DENOMINATOR, stated. "3 sites still fire after rejection" means
  // nothing without how many were successfully tested.
  sites_in_roster: roster.length,
  sites_tested: usable.length,
  sites_inconclusive: results.length - usable.length,
  sites: results,
};

mkdirSync(OUT, { recursive: true });
const path = join(OUT, `fleet-consent-gating-${STAMP}.json`);
writeFileSync(path, JSON.stringify(out, null, 2));

console.error('');
console.error(`tested ${usable.length} of ${roster.length} -> ${path}`);
const bad = usable.filter(r => (r.still_firing_after_reject_all || []).length);
console.error(`${bad.length} site(s) still fire at least one tracker after Reject All:`);
for (const r of bad) {
  console.error(`   ${r.domain}: ${r.still_firing_after_reject_all.join(', ')}`);
}
const incon = results.filter(r => !r.usable);
if (incon.length) {
  console.error(`${incon.length} inconclusive (NOT clean -- untested):`);
  for (const r of incon) console.error(`   ${r.domain}: ${r.verdict}`);
}
