# Cookie-consent coverage sweep

Read-only. Zero credentials. Loads each public homepage in a real browser,
records what fires **before any consent interaction**, and records which consent
tooling is present.

It is the third source feeding the ledger, beside `health` and `email-dns`, and
the fourth workflow in the suite.

---

## The one thing this tool must never do

**It does not say "compliant" or "non-compliant". Ever.**

That is not lawyerly caution, it is the product. clevermethod's position splits
two claims that clients and other agencies routinely conflate:

- **Correctness** is mechanical and testable, and clevermethod guarantees it:
  does the consent tooling do what it was configured to do?
- **Posture** is policy — how aggressive to be inside the discretionary band —
  and the **client owns it**.

A tool that quietly upgrades "two trackers fired before consent" into "this
site is non-compliant" destroys that distinction, and the distinction is what
makes a "you are blocking real traffic" complaint answerable. `test-consent.py`
asserts the verdict words appear nowhere in the sweep, the ledger or the
severity module.

Say: *"coverage gap on the sampled page."* Never: *"non-compliant."*

## Why not use OneTrust's own reporting

**OneTrust is the thing being observed.** Its reporting tells you what OneTrust
believes it blocked. This sweep watches the wire and records what actually
fired. When those disagree, the disagreement is the finding, and Zehnder is
what that disagreement looks like when nobody is watching the wire.

Three more reasons it has to be independent:

- Not every site runs OneTrust. The scanner detects Cookiebot, CookieYes,
  Complianz, Osano, Termly and Iubenda too, plus a generic banner heuristic.
  **A site with no CMP at all is the case that matters most**, and no CMP can
  report on its own absence.
- OneTrust's scanning product is priced per domain. This is 78 domains.
- Same rule as the Nexcess adapter: a vendor's control plane is weaker evidence
  than direct observation, and gets its own fact names so a disagreement stays
  visible instead of one silently overwriting the other.

OneTrust still has a place later — cookie inventory and categorisation per
site, which is configuration data the wire does not give us. Additive source,
not the correctness check.

## The roster is the inventory. There is no second list.

The pilot at `DK Sandbox/claude/Cowork Automation Portfolio/cookie-consent/`
carried its own `sites.yaml`: 12 domains, taken from Harvest project names that
happened to contain one. Reconciling it against `data/fleet-inventory.json` on
2026-08-19, before writing any integration code, found **two wrong out of
twelve**:

| pilot roster entry | what is actually true |
|---|---|
| `morrisoncontainerhandlingsolutions.com` | **Does not resolve. No such host.** The inventory's `morrison-chs.com` is correct and resolves into Pantheon's range. |
| `hoosierfeedercompany.com` | **302-redirects to `hoosierfeeder.com`.** One property, two names. |

A one-in-six error rate, on the list that decides what gets watched at all.
That is the Zehnder lesson restated as a data problem: **the sweep can only
watch what the roster names**, so a second roster is a second place to be
wrong. `sites.yaml` is superseded. Do not recreate it.

The second finding also moved a standing open item. `hoosierfeeder.com` is
recorded in the workbook as CM Pantheon, and the Pantheon account returns no
matching site. It resolves to Cloudflare (104.21.x), not Pantheon's 23.185.0.x,
which is consistent with it not being on Pantheon at all. **The origin host
behind Cloudflare has not been established** and that is written into the
inventory's reconciliation note exactly that way.

Roster today: **78 scannable domains.** Six inventory entries are Pantheon
machine names with no domain and are reported as skipped, with the reason —
a site missing from a coverage sweep with no explanation is indistinguishable
from a site that passed.

## What it records, and what each absence means

| fact | meaning |
|---|---|
| `consent_scan_ok` | did the page load at all |
| `consent_banner_vendor` | OneTrust / Cookiebot / CookieYes / Complianz / Osano / Termly / Iubenda / `generic` / `none` |
| `consent_banner_detected` | any of the above, or a generic fixed banner mentioning cookies with a button |
| `consent_pre_trackers` | count that fired before any consent interaction |
| `consent_pre_tracker_names` | sorted, comma-joined. Sorted so a reorder is not a diff. |
| `consent_mode_denied` | GA hits carried `gcs=G10x`, i.e. cookieless pings |
| `consent_http_status`, `consent_final_url` | a redirect changing is worth a history |

**A page that would not load is still written to the ledger**, carrying
`consent_scan_ok: false` and `unknown` for everything else. Never `0`, never
`false`. "0 trackers fired" on a page that never loaded is an all-clear
manufactured from an absence.

This differs from the Nexcess adapter, which drops rows it could not describe,
and the difference is deliberate: there, the API listing was itself the
measurement, so an all-unknown row added nothing. Here the site refusing to
load is a fact about the site, and a row that quietly vanishes from a coverage
sweep is not one anybody notices.

## Severity

**WARN, not CRIT.** Doug's ruling, 2026-08-19: CRIT stays a security tier — act
now, unpatched RCE, no backup, PHP past end of support — so the CRIT count
remains a short list somebody works through. A consent gap is real and it is a
client conversation.

| code | fires when |
|---|---|
| `consent_pre_consent_trackers` | one or more trackers fired before consent |
| `consent_no_tooling` | the page loaded and no consent tooling was detected |
| `coverage_partial` | the site has been looked at but has no health evidence |

**Consent-mode-denied GA pings are not counted as a leak.** They are cookieless
signals from a site that has Consent Mode configured *correctly*. Counting them
would flag every site that got it right, which is backwards.

**A page that would not load scores nothing**, and says so in an info line:
*"its consent posture is unmeasured, not clean."* Plenty of sites refuse
headless clients, and a rule that fires on all of them is a WARN floor under
the fleet for a reason identical everywhere — the exact mistake
`upstream_pending` was making before the severity rebuild.

## The first real sweep, 2026-08-19, and what it caught in this tool

78 eligible, 77 navigated, **and the first classification was wrong about 23 of
them.**

`ok` meant "page.goto did not throw". Twenty-three sites answered **HTTP 403** —
a WAF refusing the headless client — and a block page contains no consent banner
and fires no trackers. All 23 were classified as having nothing to fix. **Thirty
per cent of the fleet reported clean on the evidence of an error page.**

Fixed: `ok` now requires a 2xx, a non-2xx sets `httpBlocked`, and the status is
kept on the failed row because it is usually the reason. The severity info line
names it, so *"this site is down"* and *"this site will not talk to our
scanner"* stay distinguishable.

This is the same mistake as the Nexcess probe calling an HTTP 200 a site list
without reading the body, made independently, three days apart, by the same
author. **A status code is not an answer.** It is now asserted in
`test-consent.py` with a 403 fixture.

### The corrected run, ingested 2026-08-19

Of **54 sites genuinely seen** (78 eligible, 23 WAF-blocked, 1 TLS failure):

| | count |
|---|---|
| consent tooling present, nothing fires before consent | 17 |
| **consent tooling present, trackers fire anyway** | **3** |
| no consent tooling, trackers fire | 25 |
| no consent tooling, nothing fires | 9 |

All 17 tooled sites are OneTrust, all render a banner to a US visitor, and 12
show consent-mode-denied pings, i.e. Consent Mode is configured and working.
**`zehnder-rittling.com` is among the clean 17.**

The three where tooling is present and trackers fire anyway are the Zehnder
shape and the highest-value rows on the page: `blockclub.co`,
`hoosierfeeder.com`, `pfannenbergusa.com`. Two of the three were detected by
the generic banner heuristic rather than a named vendor, which means a
hand-rolled banner — the worst combination, because it looks like consent is
being collected and nothing is waiting for it.

Trackers seen: GA4 28, DoubleClick 12, MS Clarity 6, LinkedIn Insight 2, Bing
UET 1.

`hitsfoundation.org` failed with `ERR_SSL_VERSION_OR_CIPHER_MISMATCH`. That is
a TLS finding in its own right, not a consent one.

**23 sites answer HTTP 403 to a headless browser.** They are UNMEASURED, and
they are also a finding about the fleet: a third of clevermethod's sites refuse
a plain automated client.

**RESOLVED 2026-08-22: the scanner now runs HEADED, and 27 of the 28 load.**
See "The instrument" below. Everything in this section remains true of the
headless era and is kept because it is how the wrong answer was reached.

**It is NOT one decision, and it is not Pantheon's.** Measured 2026-08-22 by
reading response headers, which nobody had done: all 20 blocked CM Pantheon
sites answer `server: cloudflare` with `cf-mitigated: challenge`. Zero reach
Pantheon, so Pantheon has nothing to allowlist. Being Cloudflare-fronted is not
itself the trigger — `celticindustrialservices.com` is behind Cloudflare,
returns 200, and shows a Pantheon `x-styx-req-id` — so this is per-zone bot
settings. Those zones use at least four different DNS providers (Cloudflare,
Network Solutions, managed-ip, MediaTemple), so there is no one account and no
one owner. See `docs/SESSION-HANDOFF.md`, "The 403s".

### The geo question, checked rather than assumed

"No consent tooling detected" from a US IP could mean a banner geo-gated to the
EU. Checked in a real browser on `morrison-chs.com`: no CMP script, none of 13
CMP globals (`OneTrust`, `Cookiebot`, `Didomi`, `__tcfapi`, …), no fixed
element mentioning cookies, and eight cookies already set. The absence is real.

`cmpScripts` in the scan output settles it at fleet scale: **31 of the 34
no-tooling sites loaded no consent-related script at all**, and the three
matches were false positives — `js.cookie.min.js` is a cookie-reading helper
that ships inside WooCommerce, and the third was a tracking pixel with
"Capture" in its URL. The pattern has been tightened so a bare `cookie` no
longer matches. **A diagnostic that produces false positives is worse than no
diagnostic, because it gets trusted.**

`cmpScripts` is deliberately NOT a ledger fact. It is evidence for interpreting
`consent_banner_vendor`, and it lives in `reports/` where someone reading a
finding can consult it. Giving it a timeline would mean diffing URLs that change
on every cache-buster and calling that a fleet change.


## What rendering the page caught

Ingesting a full simulated sweep took **UNKNOWN from 32 to zero**, and nothing
had improved. The sweep reaches every domain, so no site was left in "nobody
looked", and the number Doug named as the scoreboard silently became 0.

UNKNOWN answers *"has any scan reached this site."* It never answered *"do we
know this site's health."* Those were the same number only by accident, while
health was the only scan there was, and every source added to the suite breaks
that coincidence again.

The dashboard now states health coverage on its own line — *"N site(s) have
been looked at but have NO health evidence"* — and `no_health_evidence` is a
first-class array in the JSON feed. Watch that number, not UNKNOWN.

**This is the third time a render caught something no test would have.** Do not
skip definition-of-done #2.

## Node and Playwright, in a stdlib-Python repo

There is no way to observe what a page requests before consent without running
the page. This is the one workflow that genuinely needs a browser. `package.json`
and `package-lock.json` are committed so CI resolves the versions this ran on;
`node_modules/` is ignored.

`PLAYWRIGHT_CHROMIUM_PATH` overrides the browser binary. The pilot hardcoded a
container path, which works in exactly one environment and fails elsewhere with
an error that reads like a Playwright bug rather than a wrong path.

## Running it

```bash
npm install
npx playwright install chromium        # first time only

node scripts/consent/run-sweep.mjs \
  --inventory data/fleet-inventory.json \
  --out reports \
  --stamp "$(date -u +%Y-%m-%d_%H%M)" \
  --concurrency 4

# a handful, without a full sweep
node scripts/consent/run-sweep.mjs ... --only zehnder-rittling.com,ciminelli.com
```

Then, once a person has read the output:

```bash
python3 test/test-consent.py                      # offline, no browser
./scripts/fleet-ledger.py ingest --reports ./reports --history ./history
./scripts/render-dashboard.py --out fleet.html
```

**Ingest is append-only. A mis-keyed row cannot be corrected in place.**

Expect roughly 78 × 12s ÷ concurrency, so about four minutes at
`--concurrency 4`.

### Leave concurrency at 4

Not politeness for its own sake. **Raising it costs coverage, which is the one
thing the sweep produces.**

- 23 of ~78 of these sites already answer HTTP 403 to a headless browser. More
  concurrency makes a WAF likelier to read the sweep as a crawl and block more
  of them, and **a blocked site is UNMEASURED** — it leaves the numbers
  entirely rather than showing up as a finding.
- Memory is not the constraint. Each unit is a headless Chrome at ~300MB; a
  GitHub `ubuntu-latest` runner (4 vCPU / 16GB) would take 8 comfortably.
- The saving is small anyway. Every site carries a fixed 9-second settle, so
  going from 4 to 8 turns a four-minute run into a two-minute one.

Two minutes is not worth trading measured sites for. Raise it only for an
`--only` run against a handful of domains.

The 9-second settle in `check-site.mjs` is a judgement, not a measurement: tag
managers fire late, and a shorter wait under-reports leaks, which is the
direction that reads as an all-clear.

## In CI

`ci/github-actions/fleet-consent.yml`, copied to `.github/workflows/` by hand
because the file bridge cannot write there. **Diff the two before telling
anyone to run it.**

Credential-free, so unlike the Nexcess and Pantheon workflows it can run on a
schedule without anyone first deciding to trust it with a secret. Findings are
GitHub warnings, never a red build: a build that goes red for a client
conversation teaches people to ignore the build.

It calls the shared `_publish-dashboard.yml` after persisting, so the ledger and
`fleet.thudstaff.com` move together. That was added 2026-08-19 when the first
ingest revealed that three of four workflows updated the ledger and left the
live page showing older data — a stale dashboard that looks current is worse
than an obviously missing one.


---

## The instrument

**The sweep runs a HEADED browser. Headless is an explicit opt-out and it
undercounts.** This is the single most important thing on this page, because
the previous default was wrong in the direction that reads as an all-clear.

Measured 2026-08-22, six sites across five configurations:

| configuration | sites loading |
|---|---|
| headless bundled Chromium (the old default) | 0 of 6 |
| headless + `--disable-blink-features=AutomationControlled` | 0 of 6 |
| headless real Chrome (`channel: "chrome"`) | 0 of 6 |
| **headed bundled Chromium** | **6 of 6** |
| headed real Chrome | 6 of 6 |

The variable is **headless**. Not the browser binary, not the User-Agent, not
the source IP -- laptop and CI runs were blocked identically. Across all 28
sites the sweep could not see, **27 load headed**. The 28th,
`hitsfoundation.org`, fails TLS negotiation and is a separate finding.

**And it was never only a coverage problem.** On `blockclub.co`, a site
headless could already read, two runs each way:

```
headless  n=4  DoubleClick, GA4, LinkedIn, MS Clarity
headed    n=6  DoubleClick, GA4, Hotjar, LinkedIn, MS Clarity, Meta Pixel
```

Hotjar and Meta Pixel run their own headless detection and decline to fire.
A headless browser cannot see them on **any** site. So every count from the
headless era is a floor, not a total, on all 50 sites it could read as well as
the 28 it could not.

### Why the ledger will not compare the two

A headed run reports more trackers on many sites at once, and every one was
already firing. Diffed against a headless run that is a wave of ONSET rows:
new problems that are not new. `COVERAGE` does not catch it, because these
values never touch the `unknown` token -- 4 became 6.

So the run carries a `method`, and `previous_run_of_same_source()` refuses a
candidate whose method differs. The first headed run finds no baseline and
emits no diff. Sources with no `method` at all -- health, email-dns, nexcess --
compare exactly as before, which is what keeps health's load-bearing
`api-only -> full` exception intact.

### Authorization

Running headed makes automated traffic indistinguishable from a person's. What
makes that legitimate is that these are clevermethod's own client sites under
management contract. There are no stealth plugins, no fingerprint spoofing and
no challenge solving anywhere in this workflow -- it is a real browser doing
what a real browser does, and the read-only contract above is unchanged.

Two things follow, and they are decisions rather than code:

1. **Say so.** "We run automated read-only scans of your public pages" belongs
   in the service description. Becoming undetectable quietly is not the same as
   being welcome.
2. **Prefer being allowed to being unflagged.** Where a client zone is
   Cloudflare Pro or above, a WAF custom rule with the *Skip* action naming the
   scanner is better than passing unnoticed. On the Free plan there is no such
   mechanism -- Bot Fight Mode runs outside the Ruleset Engine and cannot be
   skipped at all -- which is why the allowlist request that was queued for a
   month would never have worked.

### Running it

```bash
node scripts/consent/run-sweep.mjs --stamp "$(date -u +%Y-%m-%d_%H%M)"
```

Headed needs a display. On a laptop that means visible browser windows for the
duration of the run. CI is **not** wired for this yet: it needs `xvfb`, which
has not been proven on a runner, so `fleet-consent.yml` is unchanged and should
not be triggered expecting headed results.
