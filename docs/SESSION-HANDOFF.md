# Fleet automation: handoff for the next session

**Rewritten 2026-08-19, PICK UP HERE refreshed 2026-08-27.** Chats share this folder and project memory,
never each other's conversation history, so everything needed to resume is
written down.

**This supersedes `DESIGN-BRIEF.md` and every earlier version of itself.**

---

## PICK UP HERE — 2026-08-28, afternoon: the v3 re-run is DONE, ingested and published. Nick is next, and he is a human task

**Nothing in this repo is waiting on code right now.** State verified this
afternoon rather than read off this file, which is the point of the paragraph
below:

- Gating v3 ran twice this morning — `2026-08-28_1212` (concurrency 3) and
  `2026-08-28_1322` (concurrency 1, after an hour's cooldown). Identical
  results. Both are in the ledger.
- The four artifacts in R2 (`fleet/dashboard.html`, `components.html`,
  `consent.html`, `latest.json`) are **byte-identical** to the local
  `reports/publish-preview/` render of 09:46. Checked by pulling each object
  back with `wrangler r2 object get --remote` and comparing sha256, not by
  trusting a success line.
- All 15 offline suites green: 13 Python plus `test-page.mjs` (42) and
  `test-gating-window.mjs` (10).
- `HEAD` == `origin/main` == `a8d92df`, confirmed against the remote with
  `git ls-remote`, not inferred.

**This block replaces one that told the next session to do the re-run.** It was
already done and published when it was written. Same shape as every other doc
in the bug table: correct the morning it stops being true.

### The v3 fleet numbers, measured from run 1322 this afternoon

**18 of 27 tested. 0 still firing. 14 sending cookieless `gcs=G100` pings.**

The only thing that fires on any tested site after a real Reject All is a GA4
`collect` at `gcs=G100` — the cookieless consent-mode ping, which is the
correct denied behaviour and is exactly what Nick said should be there.

Nine inconclusive, two causes, both diagnosed:
- **4 have no clickable Reject control** (3 known, plus `hoosierfeeder.com`,
  new to the roster — it loaded for the first time in the 08-28 cold sweep
  after HTTP 403 in every earlier run).
- **5 draw a Cloudflare "Just a moment" challenge on the SECOND navigation.**
  Measured on `breakstones.com` with headers and body read. v2's reload drew
  the identical 403, so it is not the new window, and cooldown at concurrency 1
  changed nothing.

**Read the numbers off the CLICK pass, not the synthetic one.** The three pass
labels are `cold load, no consent state`, `real click on Reject All`, and
`OneTrust set to all-denied`. Only the middle one is the v3 measurement. A
substring match on "denied" silently selects the synthetic pass and gives 19
G100 sites instead of 14 — done accidentally this afternoon, caught by the
count disagreeing with the commit message.

### Open, and NOT blocked on anyone

**`interstatewaste.com`'s two passes disagree.** The synthetic all-denied pass
records `gcs=G111` — consent GRANTED — with DoubleClick and GA4 firing, while
the real click pass on the same site in the same run records the correct
`G100`. The verdict is taken from the click pass, so the site reads GATED and
that is right. But this file already contains the rule: **two passes of one
test disagreeing about one site is a defect in the test**, and that rule is
what caught the Clarity finding. It is the only site of 27 that does it, and
nothing has looked at why. Most likely the synthetic OptanonConsent cookie this
pass writes does not match the group IDs an opt-out configuration uses, in
which case the synthetic pass is not measuring what it claims on opt-out sites
generally — not just here.

### Next, in order

1. **Send Nick the correction.** Human task, and now unblocked: the v3 numbers
   above are the ones to quote. His second objection — that a compliant site
   should still send cookieless pings while our report showed none — is
   answered: 14 of the 18 tested sites send them.
2. **The `interstatewaste` pass disagreement**, above. Code, and mine to do.
3. **The 5 Cloudflare-challenged sites.** The WAF skip rule is Matt's existing
   item for the 8 CI-blocked sites; these 5 are the same problem seen from the
   gating sweep. Until it lands they are unreadable from this instrument, and
   saying so is better than a number that excludes them silently.
4. B1 is still blocked on CONTENT (`client`/`owner`, Victoria's question), B6
   is still open, and there are still **no severity codes for gating** until
   Nick answers what counts as a pass. The measurements are true whatever he
   says.

---

## Previously — 2026-08-28, morning: the gating window was wrong AGAIN, fixed as v3

**The correction to Nick has NOT been sent, and that is now correct twice
over.** An outside review of the whole repo ran today (delivered to Doug as a
shareable page; its top items are also in `docs/DO-THIS-NEXT.md` territory) and
its most urgent finding was in the gating test we fixed yesterday:

**v2's window erased the load it exists to measure.** The 2026-08-27 fix
cleared the request counters after `page.reload({waitUntil:'load'})` resolved.
The load event fires AFTER the fresh page's load-phase requests — where GA4
pageview hits normally fire — so everything the consent-denied page did while
loading was recorded and then wiped. "Nothing fires after rejection" is the
best possible result, and the instrument manufactured it: run 2159's "0 of 23
still fire" is unmeasured, and the bug-table sentence "ZERO requests on all
23" was false as written (3 sites show G100 pings even through the broken
window). Both are corrected in place.

**Fixed as v3, 2026-08-28.** The reject pass now closes the page and measures
a FRESH one on the same context: the rejection cookie persists, the listener
exists before the first request, the window is the measured page's lifetime.
No clear whose ordering can be wrong a third time. It is the shape the
synthetic-cookie pass always had — which is also why Nick being right about
the trigger still stands: that pass was never mis-windowed.

- `test/test-gating-window.mjs` (new, 10 checks) drives both boundaries
  against a local fixture: a load-phase request IS measured, the old page's
  post-click beacon is NOT. **Verified to fail against v2 before v3 existed**
  (the two load-phase checks failed, the exclusion passed — exactly the
  defect).
- `test-consent.py` is 124: two new greps refuse the known regression shapes.
- The sweep's `method` string changed with the window, deliberately: the
  ledger refuses a baseline whose method differs, so the FIRST v3 run gets no
  baseline and no change rows. One quiet run is the honest price; do not
  "fix" it.

### Next, in order

1. **Re-run the gating sweep with v3.** The last cold-scan JSON on this
   laptop is from 2026-08-22 (the 08-25 run was CI), so run a fresh cold
   sweep first, then gate from it:

   ```
   node scripts/consent/run-sweep.mjs --stamp "$(date -u +%Y-%m-%d_%H%M)"
   node scripts/consent/run-gating-sweep.mjs \
       --from-scan reports/fleet-consent-<that stamp>.json \
       --stamp "$(date -u +%Y-%m-%d_%H%M)"
   ```

   **Expect G100 pings to APPEAR on sites currently reading "none", and
   possibly load-phase trackers nobody has seen yet.** That is the correct
   behaviour becoming visible, not a regression. Then ingest, render, read
   the consent page.
2. **Then send Nick the correction**, quoting v3 numbers only. His second
   objection — that a compliant site should still send cookieless pings and
   our report showed none — was v2's defect showing; the re-run should
   finally answer it properly.
3. Everything in the 2026-08-27 block below still stands otherwise: B1 blocked
   on content, B6 open, no gating severity codes until Nick answers.

### Also 2026-08-28: six review findings fixed, each verified to fail first

An outside review of the whole repo ran today. The gating window above was its
most urgent item; five more landed the same day, one commit each:

1. **The JSON feed reported the wrong health run, permanently.** `latest`
   picked by run_id STRING compare, and `health-nexcess-…` sorts after
   `health-…` on every date, so `/api/fleet-scan` named the 22-site Nexcess
   run as THE health run while the page showed the 52-site one. Fixed to
   observed_at; test-page.py asserts feed==page against runs.jsonl.
2. **Six fabricated red "no" cells in the Aligned column.** The alignment
   booleans folded "never measured" into False; three-state now, and the
   candidate rules carry Unknown through instead of printing a confident
   Fail for a timed-out lookup. The six wrong ledger rows self-correct on
   the next email-dns run.
3. **Item 22 on the API leg.** A failed upstream:updates:list recorded a
   measured-looking 0 (reads as RESOLVED). Now null -> unknown, and the mock
   finally fails that call so the branch is testable.
4. **The queued wrong sentence.** page.js printed "0 facts became visible
   this run (, on undefined sites)" on any quiet run, and claimed the first
   fact's site count for every fact. Guarded, per-fact counts, DOM-tested in
   both states. Pages re-rendered and committed.
5. **CI now runs every offline suite on every push**
   (`.github/workflows/offline-tests.yml`, incl. both Chromium suites), and
   test-email-dns.py stops pinning the fleet at 78 — it asserts the scan
   covers its roster instead.
6. **build-fleet-inventory.py refuses an existing --out.** A rerun per its
   own Usage block would have silently erased every hand ruling in the
   inventory. test-build-inventory.py asserts the refusal.

Not done, still Doug's: the `client`/`owner` content for B1; turning on the
email-dns and worker-exposure schedules; ruling the four Lactalis redirect
domains (their consent rows describe lactalisusa.com, not themselves).

---

## Previously — 2026-08-27, end of day: everything is pushed, published and deployed

`HEAD` and `origin/main` are both `1af5401`. All four pages are live and were
verified by reading them back from R2 and from the deployed Worker, not by
trusting a success message. **The Worker was redeployed today** — the first
time in this project's history that a route was added, so it is worth knowing
that `wrangler deploy` from `ci/cloudflare` is a human action and the file
means nothing until it runs.

Live: `/` (evidence matrix), `/components`, **`/consent` (new)**,
`/api/fleet-scan`.

### The consent work, which is most of today

The dashboard used to report `interstatewaste.com` as leaking four trackers.
It is opt-out outside California, working exactly as designed, and the agency's
own OneTrust audit records it compliant. **The sweep observed correctly and the
rule drew a conclusion the observation could not support** — the cold load
cannot tell a correctly configured opt-out site from an ungated one, because
both produce an identical result.

Four things fixed that, in order:

1. **`consent_model` and `consent_managed` are inventory rulings**, seeded from
   Nick Federico's `onetrust-audit.xlsx` and living beside `production`. A scan
   can never supply them. `scripts/seed-consent-rulings.py` refuses to
   overwrite a differing value without `--force`, which is what makes the
   inventory the master rather than a mirror of a spreadsheet being retired.
2. **Severity reads the model.** Opt-out firing on load is reported as
   configured behaviour on the PLANNING axis, not a finding. Opt-in is a
   finding. No model recorded gets its own code, `consent_trackers_unruled`,
   because whether it is intended has not been established.
3. **The gating sweep**, `scripts/consent/run-gating-sweep.mjs`. Clicks Reject
   All and reloads: does the site actually stop? Its own ledger source,
   `consent-gating`. First run 26 tooled sites, 23 tested, **2 still firing**.
4. **Its own page**, `/consent`, on the dashboard's chrome, with an ours-only
   toggle.

### The finding that was not one — read this before trusting the gating sweep

The sweep reported **MS Clarity still firing after Reject All** on
`actioncarting.com` and `interstatewaste.com`. It was raised with Nick Federico
on Teams. **He validated it by hand, said the trigger is correct, and he was
right.**

`test-gating.mjs` cleared its request counters BEFORE the post-rejection
reload, merging the window where the ALREADY-OPEN page finishes its work with
the window that actually answers the question — a fresh consent-denied load.
Clarity flushes its session buffer on consent change, and those beacons were
attributed to a tag ignoring consent.

~~Fixed, and re-run fleet-wide: **0 of 23 tested sites still fire after Reject
All.**~~ **That number is a v2 measurement and is unmeasured.** The window it
was taken through erased the load it existed to measure — see the 08-28 block
at the top. The v3 answer is **0 of 18**, and the difference is not 5 sites
getting worse: 5 of yesterday's 23 now draw a Cloudflare challenge on the
second navigation and are honestly inconclusive rather than dishonestly clean.

**The lesson, because it is more useful than the fix.** The instrument's own
two passes disagreed about the same site — the synthetic-cookie pass had Google
correct at `gcs=G100` and Clarity stopped, the click pass had Google absent and
Clarity firing. That contradiction was in the output before the message was
sent. Two passes of one test disagreeing about one site is a defect in the
test. And Nick's second objection, that Google should still send cookieless
pings on rejection when our report showed none, was the same bug from the
outside and was the more informative half of his reply.

**Doug owes Nick a correction**, and it has not been sent as of this writing.

### Settled today, so nobody re-opens it

- **The 11 Lactalis OneTrust sites are NOT ours.** Nick's sheet of 15 is the
  complete list. There is a signed OneTrust SOW for Lactalis American Group in
  SharePoint and it is an integration project, not ongoing management. Written
  up as B5 in `docs/DO-THIS-NEXT.md`, closed.
- **7 sites that look like they leak do not.** Google at `gcs=G100` after a
  rejection is the cookieless consent-mode ping and is correct. The first
  fleet-wide run reported 9 failures where the answer was 2.

### Next, in the order I would take it

1. **Send Nick the correction.** We told him two of his sites were leaking and
   they are not. Human task, and the first one.
2. **B1 in `docs/DO-THIS-NEXT.md` is blocked on CONTENT, not code.** Victoria
   Brake asked how to handle clients not paying for maintenance. The field is
   an hour's work; the answer is a list nobody has. `client` and `owner` have
   existed on all 85 records since the inventory was created and are recorded
   on **zero** of them. Do not add a third empty column.
3. **The consent page does not say where "ours" comes from** (B6). It prints a
   ruling with the confidence of a measurement, and Doug has said the list
   grows as clients onboard.
4. **No severity codes for gating yet, deliberately.** Whether "Reject All,
   then nothing fires" is the standard is Nick's question. The measurements are
   true whatever he answers.

---

## Previously — 2026-08-27, evening: the new page is built, not pushed, not published

**`render-dashboard.py --out` now writes the evidence-matrix page.** Doug chose
it from three rendered concepts and said "ship it". Everything below the
horizontal rule is the state at end of the working day, before that decision;
the six UI changes it describes are in `render()`, which is now the LEGACY
page behind `--legacy-out`.

What was done, in `docs/DASHBOARD-V3.md` and CLAUDE.md "The page, since
2026-08-27":

- `scripts/dashboard/page.js` + `page.css`, inlined by the new `render_page()`;
  `page_data()` embeds the model (a superset of the feed). No web fonts, no
  network, one file.
- `test/test-page.py` (33, offline) and `test/test-page.mjs` (39, headless
  Chromium). Two old blocks in `test-ledger.py` and `test-severity.py` that
  matched the old markup are re-stated as properties on the model.
  Ledger 314 / severity 142 / page 33 / DOM 39, all green.
- `publish-dashboard.sh` runs `test/test-page.py` after rendering and refuses
  to publish on failure. Dry run passes.
- `fleet.html` and `components.html` re-rendered and committed.

**To do, in order:**

1. `git push` (Doug; Claude does not push).
2. `./scripts/publish-dashboard.sh --dry-run`, open
   `reports/publish-preview/dashboard.html`, read it. Then
   `./scripts/publish-dashboard.sh`.
3. Read https://fleet.thudstaff.com on a phone and a laptop.
4. Decide whether `test/test-page.mjs` goes in the publish job (Chromium
   download on the runner) — see DASHBOARD-V3.md "Not done".
5. After one published cycle, retire `render()`, `--legacy-out`, and the
   `RD.render(...)` assertions in `test-ledger.py`.

---

## PICK UP HERE — 2026-08-27, end of day (superseded above)

**Nothing is published.** Today's scan is ingested, rendered and committed;
the last commit pushed is `09ff524`. Doug asked for six UI changes before
publishing, and they are built. **Push and publish are both still to do.**

### The six UI changes

Five were built. **One was already done and I said so rather than rebuilding
it.**

1. **Three marked layers.** Summary / Detail / Complete inventory, as bands
   with a rule, a label and a sentence. Nothing moved — the eleven sections are
   in the order they already were. The reference band carries a heavier rule
   because that is where reading stops and lookup starts: `Every site` alone is
   102KB of a 174KB page.
2. **What changed, compressed.** 22 of 23 sites moved only a plugin counter.
   Those are folded behind a summary that names them; the one real transition
   renders outside the fold. Folded, not dropped — DRIFT rows are real records
   and a bare "22 sites" would be a summary standing in for the evidence.
3. **Rulings state the decision.** Three columns: what is unresolved, why no
   scan can settle it, what a person must decide. The decision text is read
   from the inventory's `reconciliation`, not hardcoded. No action controls.
4. **One key, three groups.** The two scattered keys are merged. The grouping
   is load-bearing: `CRIT/WARN/OK` is a verdict, `SKIP/FROZEN` is the absence
   of one, and flattening them is what lets a reader treat SKIP as a mild WARN.
5. **Jump links**, plus a route back to the summary at the foot of each layer.
   A test asserts no link points at an id that does not exist.
6. **Coverage vs website changes — ALREADY DONE, not rebuilt.** Coverage
   changes already have their own section saying "our visibility changing, not
   the fleet", and no COVERAGE chip appears in `What changed`. Verified by
   counting the chips rendered in that section: 23 DRIFT, 1 TRANSITION, 0
   COVERAGE.

### Two defects found doing it

**The rulings column answered a different question on one row.** It read
`reasons or "<ruling text>"`, so `hoffmanscheese` showed its backup age and
plugin count where the other four showed why their ruling is missing. The
decision required is identical for all five.

**Three CSS variables I invented did not exist.** `--quiet`, `--rule`,
`--link`. An undefined custom property does not error, it inherits, so the page
still looked deliberate. Now checked by diffing variables used against
variables `:root` defines.

Suites: ledger **316**, severity 127, score-scan 24, nexcess 96, consent 76,
nexcess-ssh 43, wp-calls 48, email-dns 58, worker-exposure 40,
access-policies 46. Page read at 1100px and at 375px; no horizontal overflow.

### State, measured today

| | |
|---|---|
| health | 2 CRIT / 53 WARN / 25 OK / 3 SKIP / 1 FROZEN, one excluded |
| health-coverage scoreboard | 11 |
| standing findings | 17 |
| latest health run | `health-2026-08-27_1246`, 48 of 52 measured |

### What is still open

1. **DRIFT and COVERAGE still mean two things on one page.** The key now says
   so explicitly. Renaming either vocabulary is a product decision and was not
   guessed at.
2. **The consent baseline.** No baseline since 2026-08-22. Probable fix is to
   diff over the INTERSECTION of the two site sets. Not built.
3. **`lancastervillageny.gov` records the relay as its from address.** A
   workbook correction.
4. **The Top issues table is capped at six by size**, so the two core-update
   groups (21 and 11) sit below it.

### Still a human task, unchanged

- **Send the Nexcess question-1 reply**, thread
  `thread::sJecUJQ2cS6EeEacWJKo2D0::`, drafted at the bottom of
  `docs/NEXCESS-SUPPORT.md`.
- **Check the `github-deploy-[removed]` token scope** in the Cloudflare
  dashboard. Re-scope, do not delete.

---

## Previously — 2026-08-27, after the scan

**Today's scan is ingested, rendered, pushed and published**, and both the push
and the publish were verified by reading them back rather than trusting a
success message. The live page was downloaded out of R2 and is byte-identical
to the committed `fleet.html`.

### Three fixes after the scan, all reported by Doug reading the page

1. **The scanner was a second severity scorer, three weeks out of date.** On
   the same 52 rows it said `33 CRIT / 15 WARN / 0 OK` where severity.py says
   `3 CRIT / 34 WARN / 11 OK`. Its bash rules were the pre-2026-08-19 model,
   including `upstream_pending > 0 -> WARN`, the rule that makes OK
   unreachable. The dashboard was never affected; the summary, the CSV, the
   markdown and the **exit code** all were. Fixed by adding
   `scripts/score-scan.py`, which calls severity.py — not by porting the
   thresholds, which would be a third copy. 24 new tests.
2. **The components page said "68 of 75 Pantheon sites".** It is 53 Pantheon
   and 22 Nexcess. `COMPONENT_HOSTS` was widened when the Nexcess scan landed,
   which fixed the denominator and left the noun. The same sentence also
   disclaimed "the 32 sites on other hosts" — a count that included the 22
   Nexcess sites the page inventories. Both now read one module-level tuple.
   The real out-of-scope count is 10.
3. **The Kind column had no legend.** RISK, COVERAGE, PLANNING and DRIFT were
   undocumented on a page whose only legend explains CRIT/WARN/OK. Added, and
   it names the collision: DRIFT and COVERAGE each mean one thing in that
   column and a different thing in the change feed below.

Suites: score-scan **24**, ledger 288, severity 127, nexcess 96, consent 76,
nexcess-ssh 43, wp-calls 48, email-dns 58, worker-exposure 40,
access-policies 46.

### One decision waiting on Doug

**DRIFT and COVERAGE mean two different things on one page.** The legend now
says so, which is honest but not a fix. Renaming either vocabulary — the
standing-finding axes or the change classes — is a product decision about words
Doug's team may already use, so it was not guessed at. Nothing is broken; a
reader who skips the legend carries the wrong meaning down the page.

### State, measured today by scoring the ledger

| | |
|---|---|
| health | 2 CRIT / 53 WARN / 25 OK / 3 SKIP / 1 FROZEN, one excluded |
| health-coverage scoreboard | 11 |
| standing findings | 17 |
| core update pending | 32 sites — 21 want 7.0.4, 11 want 7.1 |
| plugin backlog (>= 10) | 27 sites, up 3 |
| latest health run | `health-2026-08-27_1246`, 48 of 52 measured |

### What is still open

1. **The consent baseline, unchanged.** No baseline since 2026-08-22, so the
   source produces no change rows and no trend. Probable fix is to diff over
   the INTERSECTION of the two site sets and say how many were excluded.
   Written up at the end of `docs/DO-THIS-NEXT.md`. Not built.
2. **`lancastervillageny.gov` records the relay as its from address.** A
   workbook correction, not a code change.
3. **The Top issues table is capped at six by size**, so the two core-update
   groups (21 and 11) sit below it while the 32 sites they cover are the
   largest single driver of WARN.

### A note on the scan itself

The first run of the day measured 47 of 52 and ingest refused to let it drive
the page. `choosechq.com` timed out on the 20s `env:list` preflight. Every full
run since 2026-08-19 had measured exactly 48, so this was the first deviation
in eight runs; the site answered normally on its own in 82s and the re-run
measured 48 with no failures. **The 20s ceiling is not too tight.** Both runs
are in the ledger, and the renderer correctly diffs against 2026-08-26 rather
than the degraded run, because `previous_run_of_same_source` refuses a baseline
whose measured set is a strict subset.

### Still a human task, unchanged

- **Send the Nexcess question-1 reply**, thread
  `thread::sJecUJQ2cS6EeEacWJKo2D0::`, drafted at the bottom of
  `docs/NEXCESS-SUPPORT.md`. Do not send the request/response headers they
  asked for; the challenge was our own missing `post_handshake_auth`.
- **Check the `github-deploy-[removed]` token scope** in the Cloudflare
  dashboard. Re-scope, do not delete.

---

## Previously — 2026-08-27, midday

**Open question 1 from yesterday is answered, and the answer was not the one
the question assumed.** The premise was that 52 of 85 WARN is a severity
problem and `core_update` should be demoted the way `upstream_pending` was.
Measured today, that is wrong: `upstream_pending` was demoted because it was
never zero, and `wp_core_update` reads up-to-date on **36 of 68** measurable
sites against 32 pending. It discriminates, so it stays a per-site WARN.

The real defect was next to it. `standing()` emitted twelve causes and **not
one of them was a core update or a plugin backlog**, which is what 40 of the 52
WARN sites are WARN for. The table was amber and the action list beside it was
silent about why. Two groups added, one per core target version plus one for
the backlog. Standing findings: 14 -> 17.

Three defects found doing it, all in CLAUDE.md's table. The plugin group
rendered **twice** (17 sites and 7) because `standing()` runs per cohort and
both health cohorts can raise it; the twelve existing groups had never collided
only because they read Pantheon-only facts. `standing_was` had the same bug, so
the trend arrow would have read `was 7` on a 24-site group. And the first
action line asserted "one release behind" over a site on 7.0.2, two patches
back.

Suites: ledger **288** (was 274), severity 127, nexcess 96, consent 76,
nexcess-ssh 43, wp-calls 48, email-dns 58, worker-exposure 40,
access-policies 46, run-local 60.

**Not pushed, not published.** Both are human actions. `git log origin/main..`
to see what is waiting.

### State, measured today by scoring the ledger

| | |
|---|---|
| health | 2 CRIT / 52 WARN / 26 OK / 3 SKIP / 1 FROZEN, one excluded |
| health-coverage scoreboard | 11 |
| standing findings | 17 |
| core update pending | 32 sites — 21 want 7.0.4, 11 want 7.1 |
| plugin backlog (>= 10) | 24 sites, 378 updates, worst `hoffmanscheese` at 27 |

### What is still open

1. **A fresh Pantheon scan was started 2026-08-27 and its result is not in
   this document.** It runs about 2.4 minutes per site over 52 sites. If it
   finished, ingest it and re-render; if it did not, nothing is lost — the
   ledger is append-only and the numbers above come from `health-2026-08-26_1351`.
2. **The consent baseline, unchanged from yesterday.** No baseline since
   2026-08-22; the source produces no change rows and no trend. Probable fix is
   to diff over the INTERSECTION of the two site sets and state how many were
   excluded. Written up at the end of `docs/DO-THIS-NEXT.md`. Not built.
3. **`lancastervillageny.gov` records the relay as its from address.** A
   workbook correction, not a code change.
4. **The Top issues table is capped at six by size**, so the two core-update
   groups (21 and 11) sit below it while the 32 sites they cover are the
   largest single driver of WARN. Splitting by target is still right — the
   action line is only honest when it is one decision — but whether the ranking
   should know that two groups share a cause is an open question. Not built,
   and deliberately not guessed at.

### Still a human task, unchanged

- **Send the Nexcess question-1 reply**, thread
  `thread::sJecUJQ2cS6EeEacWJKo2D0::`, drafted at the bottom of
  `docs/NEXCESS-SUPPORT.md`. Do not send the request/response headers they
  asked for; the challenge was our own missing `post_handshake_auth`.
- **Check the `github-deploy-[removed]` token scope** in the Cloudflare
  dashboard. Re-scope, do not delete.

---

## Previously — 2026-08-26, end of day

**Everything is pushed and published, and both were verified rather than
assumed.** `HEAD` and `origin/main` are both `3e016a8`; the R2 object matches
the committed `fleet.html`, md5 `11c4f4e8b365fa38d60b7050fbc6706b`. Working
tree clean. Suites: ledger **274**, severity 127, nexcess 96, consent 76,
nexcess-ssh 43, wp-calls 48, email-dns 58, worker-exposure 40,
access-policies 46, run-local 60.

Measured by scoring the ledger today:

| | |
|---|---|
| health | 2 CRIT / 52 WARN / 26 OK / 3 SKIP / 1 FROZEN, one excluded |
| health-coverage scoreboard | 11 |
| UNKNOWN | 0 |
| sending domain measured | 59 of 75 |
| latest runs | `health-2026-08-26_1351`, `health-nexcess-2026-08-26_1941`, `email-dns-2026-08-25_2002`, `consent-2026-08-25_2204`, `nexcess-2026-08-25_1749` |

### The three open questions, in the order I would take them

1. **52 of 85 sites read WARN, and that is the real problem with the page.**
   30 for a WordPress core update, 22 for a plugin backlog, 11 for having no
   health evidence at all. CLAUDE.md already says a fact true of every site
   ranks nothing, and a core update pending on 30 sites is close to that. This
   is a severity question and it is worth more than anything left in the UI
   list. No layout fixes a fleet where two thirds of rows are amber.
2. **The consent sweep has had no baseline since 2026-08-22.** Its coverage
   improved monotonically (38, 50, 69, 71) and `previous_run_of_same_source`
   refuses any candidate whose measured set is a strict subset, so every
   earlier run is refused. That source produces no change rows and no trend.
   The rule is right; the consequence is not obviously wanted. Probable fix:
   diff over the INTERSECTION of the two site sets and state how many were
   excluded. Written up at the end of `docs/DO-THIS-NEXT.md`. Not built.
3. **`lancastervillageny.gov` records the relay as its from address** —
   `...@mail.smtp2go.com`. The site says `email.lancastervillageny.gov`. A
   workbook correction, not a code change. It is the only disagreement of the
   38 comparable sites.

### What shipped today

**The sending domain is measured, on both transports.** `wp option get
postman_options`, gated on post-smtp appearing in the plugin list the scan
already fetches. Four facts, stored beside the workbook's ruling. On Nexcess it
is the seventh command, **approved by Doug Kasperek 2026-08-26** and recorded in
the script header. 59 of 75 sites, 37 of 38 agreeing.

**The UI revision.** `docs/clevermethod-fleet-ui-improvement-direction.md` was
assessed and the parts worth taking applied: four exception tiles that filter
the table, a change feed grouped by site, coverage as `48 checked · 4 not
checked — of 52`, one sweep line under the masthead, folded methodology with
qualification kept inline, and a **Top issues** table with a direction against
the previous run. What was refused is written up in `docs/DO-THIS-NEXT.md`, each
because it would recreate a row already in CLAUDE.md's table. The mockups and
the forked renderer are deleted.

### Five defects found, all in the bug table

`ITEM 22 IS LIVE` from the detector built to catch item 22, three days after it
was fixed. Eight false sending-domain disagreements, from comparing the From:
domain against the sending domain. The coverage guard comparing two disjoint
cohorts, which needed fixing in three places and the two fixed first were not
the one ingest runs. post-smtp storing neither key the parser looked for. And
`measuring post-smtp closes 6 of the 7 blanks`, which was my own claim and
closes one.

### Still a human task, unchanged

- **Send the Nexcess question-1 reply**, thread
  `thread::sJecUJQ2cS6EeEacWJKo2D0::`, drafted at the bottom of
  `docs/NEXCESS-SUPPORT.md`. Do not send the request/response headers they
  asked for; the challenge was our own missing `post_handshake_auth`.
- **Check the `github-deploy-[removed]` token scope** in the Cloudflare
  dashboard. Re-scope, do not delete.

---

## Previously — 2026-08-24, the Nexcess reply

**Nexcess answered the 2026-08-22 ticket. Two of three questions settled, and
the SSH deep scan is no longer gated.** Analysis in `docs/NEXCESS-SUPPORT.md`,
"The reply, 2026-08-24". The reply itself is archived verbatim in
**`docs/correspondence/`, a new directory** — external messages that a doc
relies on as evidence now live in the repo rather than in someone's inbox.
Its README defines the convention; read that before adding a second one.

| question | answer |
|---|---|
| Does one account-level SSH key reach every Managed WordPress site? | **Yes**, existing and future. Phase 2 is unblocked |
| Is there a read-only SSH user? | **No.** Every SSH identity is write-capable. Not restrictable to `wp core version` |
| Can the API be exempted from the Cloudflare challenge? | **Not answered.** They suggested a browser User-Agent |

**The User-Agent suggestion was re-tested live 2026-08-24 and is still
challenged** — `probe` and `probe --user-agent browser` both return HTTP 403
`Just a moment...` from `portal.nexcess.net/api`, with a deliberately invalid
token in both, because the challenge is served before the token is read. A
reply is drafted at the bottom of `docs/NEXCESS-SUPPORT.md`; **sending it is a
human task.**

Also checked: the `api-token` docs they linked still write every example
against `$PORTAL_API_URL` and define it nowhere, so our "what is the right base
URL" question is unanswered rather than resolved. Separately, `ssh-key/add.md`
documents `POST /v1/ssh-key` with no site parameter, which corroborates the
account-level answer from the vendor's own docs.

### Next, in order

1. **Send the question-1 reply.** Human task, existing thread
   `thread::sJecUJQ2cS6EeEacWJKo2D0::`.
2. **Build the Nexcess SSH deep scan (Phase 2).** No longer gated. Two things
   it needs first: the per-site `unix_username` join key, which normally comes
   from the blocked API and for 21 sites can be read out of the portal by hand;
   and a dedicated automation keypair, public half added at user level, private
   half a GitHub secret. Follow the five steps in CLAUDE.md, "Adding a workflow
   to the suite" — including the `MEASURED` and `COVERAGE_FLAGS` pair and a
   coverage line from day one.
3. **Treat the command list as a security control.** There is no read-only
   user, so nothing on the host prevents a write. This is now recorded in
   CLAUDE.md's hard boundaries.

**Published 2026-08-24, and verified by reading R2 back.** The dashboard copy
fix is live. The published object is byte-identical to the committed
`fleet.html`, md5 `a11810c8a68b7a0bfdf848d605e610b7`. Two things learned doing
it, both in `docs/DASHBOARD.md`: a publish CAN be verified without Access by
pulling `dash-data/fleet/dashboard.html` back out of R2, and the wrangler OAuth
token publishes fine despite `whoami` listing no R2 scope, so no
`CLOUDFLARE_API_TOKEN` is needed from a logged-in laptop. Still nobody has
opened `fleet.thudstaff.com` in a browser; the Worker sits between R2 and the
hostname, so the read-back is not a substitute for that.

**Worker exposure is now checked rather than asserted, 2026-08-24.**
`./scripts/check-worker-exposure.py` fetches all five workers.dev URLs and all
five hostnames anonymously. **Measured clear the same day: every workers.dev
route returns Cloudflare's `error code: 1042`, every hostname 302s to Access.**
That includes `[removed]`, whose toggle nothing pins. Item 3b below said the
dashboard toggle "remains the only live control"; it is still the only
*control*, but it is no longer the only *observation*. 23 offline tests cover
the classifiers, and they were verified to fail before they passed: breaking
"a timeout is UNKNOWN" to return CLOSED turns 5 of them red.

**The bindings ARE enumerable, which removes the stated blocker to a config.**
`[removed]` uses `DECK` (R2 `[removed]`) and `DECK_DB` (D1 `[removed]`,
uuid `[removed]`), plus six secrets: `[removed]`,
`[removed]`, `[removed]`, `[removed]`, `[removed]`,
`[removed]`. Enumerated from `env.*` in `cf-worker-r2.js`. **This is NOT a
recommendation to add a config** — adding one changes how that Worker deploys,
which is the risky operation, and detection is the cheaper fix. It is recorded
so the decision is now a choice rather than a blocker.

**Still open and NOT verified this session: the `github-deploy-[removed]` token
scope.** Item 4 below says all accounts, R2 write, no expiry. Token scopes are
not readable with the wrangler OAuth login, so that line is still a document
rather than a measurement. **Check it in the dashboard.** Re-scope, do not
delete.

**The exposure check answers AUTHENTICATION, not AUTHORISATION, and the
difference matters before the dashboard is shared.** It proves a stranger
cannot get in. It says nothing about what a logged-in person can reach. Access
authorises per application, so signing in at `fleet.thudstaff.com` does not
grant `[removed]`; the deck's policy is evaluated fresh. SSO makes that
seamless enough to be easy to assume otherwise.

Added 2026-08-24: the check now also asserts each hostname hands off to a
**distinct Access application**, measured live as five distinct tags. Two
hostnames on one application share one policy and one audience. That is the
closest a credential-free check can get.

**WHO is in each policy still cannot be read**, and this is the second time
that gap has bitten: the Zero Trust API needs a scope the wrangler OAuth token
does not carry, and answers `success: true` with an empty list, so "not
permitted to look" reads exactly like "nothing is there". See the bug table.

**BEFORE SENDING `fleet.thudstaff.com` TO VICTORIA, run this.** She will have
a valid Access session, and the question is whether editing the subdomain gets
her into `[removed]`, which holds [removed], [removed] and the
[removed].

An earlier draft of this block said to ask her to try it and report back. That
is not a control: it relies on the person being tested to self-report, it tests
one hostname, and it happens after the link has been sent. The thing that
actually decides the answer is the `cm` application's policy, so read the
policy.

`scripts/check-access-policies.py` does that. **It needs one read-only token
that does not exist yet** -- My Profile -> API Tokens -> Custom, with Access:
Apps and Policies (Read) and Access: Organizations, Identity Providers, Groups
(Read). Then:

```
export CF_ACCESS_TOKEN=...
export CLOUDFLARE_ACCOUNT_ID=8ae221977ecb4518fecaffed03972e11
./scripts/check-access-policies.py --expect data/access-expectations.json
```

`data/access-expectations.json` encodes the intent: victoria and nick reach
`fleet.thudstaff.com` and nothing else. It fails in BOTH directions, so an
unexpected grant and a missing one are both findings.

### RUN 2026-08-24. Victoria is clear to receive the fleet link.

**Measured, not inferred.** `[removed]` and `[removed]` are ALLOWED on
`fleet.thudstaff.com` and **DENIED on all four others**, including
`[removed]`. Editing the subdomain gets them nothing.

**Every ALLOW on this account names an individual.** No `email_domain`, no
`everyone`, no `ip` rule anywhere, and zero UNKNOWN verdicts. That absence is
the reassuring part, because those rules admit people without listing them and
are exactly what a human review of a member list misses.

Two things the run corrected:

- **`data/access-expectations.json` was wrong about matt and brian.** It gave
  them three applications from `docs/DASHBOARD.md`; they have all five. The
  file now holds measured membership, and doug was missing from it entirely.
- **`docs/DASHBOARD.md` named the wrong policy on `cmcom`.** It said `[removed]`;
  it is `cmcom-viewers`. Same three people, so nothing was wrong about access,
  but the table named an object that was not there. Corrected.

And one bug in the script itself, found by reading the output: **`_comment` was
evaluated as an identity.** Keys are now skipped when `_`-prefixed, and a key
without an `@` is a hard error rather than a silent skip, because a silently
skipped key is an identity nobody is checking. In the bug table.

The rule the script exists for: **a policy can admit someone without naming
them.** `email_domain`, `everyone` and `ip` rules all do. Reading a list of
email rules and concluding "she is not on it" is the mistake this replaces.

**NEXCESS PHASE 1 IS UNBLOCKED, 2026-08-25, and the blocker was ours.**
`probe` returns `ok 200 site list returned` against a real token. Five days of
"Nexcess is blocking us with a Cloudflare challenge" came from one line:
`_ssl_context()` built a TLS context by hand and omitted `post_handshake_auth`,
which `http.client` sets for you and which changes the TLS 1.3 ClientHello.
Isolated by bisecting the context; ALPN was tested and is not the factor.

**What this changes:**

- The 21 `unix_username` values come from the API, not from copying SSH
  Command lines out of the portal by hand. That was the last prerequisite for
  the SSH deep scan other than the keypair.
- `docs/NEXCESS-SUPPORT.md` carries a correction to send. **Do not send the
  request/response headers Suraksha asked for** -- we would be handing a vendor
  a capture of our own bug, on top of a ticket that already told them a TLS
  fingerprint was "ruled out". It was not.
- Everything in `docs/NEXCESS.md` about the challenge is now the record of a
  wrong diagnosis, not current state, and is marked as such.

**Access membership drifted, and it is an argument for the migration.**
Enumerated for the first time 2026-08-25: `[removed]` holds access to an
application and appears in no document. Probably a legitimate grant nobody
wrote down; the point is that nothing could have told you it existed. Access
here is hand-typed email lists on a personal Cloudflare account, with no
directory behind it, no offboarding path and no owner for the audit. Written up
in `docs/DASHBOARD.md` under the migration section.

`./scripts/check-access-policies.py --expect data/access-expectations.json`
now reports anyone named in a policy who is not in the file, and reports
separately when a broad rule makes enumeration impossible. Measured clear on
that second point: every allow policy names individuals.

**Backlogged, not started: measure the sending domain.** From Victoria's
question in the demo. `post-smtp` is on 39 sites and holds its host in
WordPress options, so the existing deep scan can turn a workbook ruling into a
measurement and close the 7 blanks. Store it under a different fact name so a
disagreement with the workbook shows rather than resolves silently. Full entry
at the end of `docs/DO-THIS-NEXT.md`.

**Backlogged, not started: maintaining the rulings.** See the "Backlog:
maintaining the rulings" section at the end of `docs/DO-THIS-NEXT.md`. The
finding behind it is worth knowing before anyone quotes the production flag:
**83 of 84 sites are `production: null` and exactly one ruling has ever been
recorded.** The recommendation is to run the ruling pass once rather than build
an editor, and specifically not to put a write route back into the Worker.

Nothing in the ledger, dashboard or CI changed today. The 2026-08-23 state
below is still current.

---

## Previously — 2026-08-23, end of day (third pass)

**Committed, clean and PUSHED.** `git ls-remote origin main` and `HEAD` are
both `9f099c0`. Tests: ledger **197**, severity 116, email-dns 58, nexcess 88,
consent 75, wp-calls 45, run-local 49.

*(An earlier draft of this block said 16 commits were unpushed. That was
inferred from the rule that `push` is a human action, never checked.
`git status --short` reports working-tree changes only — it says nothing about
ahead/behind, and a `## main...origin/main` line with no marker means level.
`git ls-remote` is the check that talks to the remote.)*

**Doug is showing the dashboard to the team on 2026-08-24.** Both pages are
published and were verified by reading the objects back out of R2. Access
membership was confirmed by Doug. The one check nobody has done is opening
`fleet.thudstaff.com` in a browser and looking at it — Access blocks Claude, so
every visual check this session was against local renders.

| source | run | measured |
|---|---|---|
| health | `health-2026-08-23_1956` (**full**) | 52 scanned, 48 deep, **47 inventoried** |
| email-dns | `email-dns-2026-08-23_2354` | 70 of 78 |
| consent | `consent-2026-08-23_0109` | 69 of 78 |
| nexcess | — | **never run**, 0 of 21 |

Health **2 CRIT / 73 WARN / 4 OK / 3 SKIP / 1 FROZEN**. One change needing a
decision. `components.jsonl` holds **1,842 rows, 312 distinct components**
across 47 of 53 Pantheon sites.

### What exists now that did not this morning

**The component inventory, steps 0–2 of `docs/VULN-INTEL-REVIEW.md`.** The
scanner keeps the full `wp plugin list` rather than the update backlog, plus
must-use plugins; `history/components.jsonl` is a fourth ledger file, one row
per site per component, same `run_id` as the facts beside it. Rationale and the
`components_checked` coverage flag are in `docs/DATA-MODEL.md` section 2b.

**`/components`, the catalogue.** Plugin-major, because that is the question a
count cannot answer. Sortable, filterable by text, type, scope and site, with a
site picker and `?site=` deep links from the fleet table's plugin count. Route
added to the Worker and **deployed** — verified by reading the deployed code
back through the Cloudflare MCP, not from the source file.

**It already answered the question it was built for:** all 30 sites running
`pods` are on **3.3.9.1**, which is the FIXED version for CVE-2026-19598. No
feed, one search box.

**House style, from [removed].** `[removed]/src/form.html`'s paper, purple-cast ink,
hairlines, Helvetica Neue stack, uppercase 800-weight labels and square
corners. **The severity colours are deliberately NOT [removed]'s** — ours are
colourblind-validated and its `--good`/`--red` are not; a test asserts those
two hues stay absent. **Light only, no dark mode** — [removed] ships light only,
and `body{background}` is now load-bearing because nothing else stops the page
inheriting a dark host ground.

**A QA pass before sharing** removed a footer promising trend charts nothing
implemented, gave every table its own scroller (the page scrolled sideways on a
phone; "What changed" was 616px in a 348px card), and marked the non-production
row that makes "CRIT 2" filter to three.

### Start here next time

1. **Steps 3 and 4 are blocked on a credential, not code.** The Wordfence V3
   key must be created on a **clevermethod-owned login**. Same problem as the
   Cloudflare tokens.
2. **`fleet.clevermethod.net` needs a role grant.** Doug holds
   `Administrator Read Only` on the clevermethod, Inc. Cloudflare account, so
   every write in that migration fails regardless of token scope. Full finding
   in `docs/DASHBOARD.md`, "Which Cloudflare account, and what it can do".
3. **The version comparator is confirmed necessary.** `Divi` runs at 13
   versions across 45 sites, four-part strings like `4.9.97.43` are common, so
   not semver and `packaging` will not do.
4. **`render-fleet-dashboard.py` (v1) still has a dark block** and was left
   alone on purpose. Its own change if the local live view should match.

### Things that will look like bugs and are not

- **`cm-whitelabel` has no component rows.** Its database is not installed, so
  every DB-backed WP-CLI call exits 1. `components_checked: false`, no rows.
- **"CRIT 2" filters to three rows.** `cm-whitelabel` is `production: false` —
  shown but not counted. Its row now says so inline.
- **Two coverage lines read 47 of 52 and 47 of 53.** Both right: one counts
  ledger rows, the other uses the INVENTORY as denominator per CLAUDE.md step
  5. The gap is `hoosierfeeder.com`.
- **The catalogue's Sites / Versions / Pending stay fleet-wide under a site
  filter.** Deliberate; the banner says so and the per-site value is in "On
  this site".
- **The fleet table scrolls sideways on a phone.** Correct for 16 columns, but
  a phone shows about three of them.

### Two traps this session walked into

**`fleet-email-dns.py` takes `data/fleet-email-inventory.json`, NOT
`data/fleet-inventory.json`.** The site inventory has no `sending_domain` on
any row, so the wrong file yields 78 rows measuring nothing. The coverage
guard caught it and refused to publish; the ledger, being append-only, kept
the failed run, and diffing the good run against it produced 117 false
TRANSITIONs. Fixed by rule 2b in `previous_run_of_same_source`: a run that
measured NOTHING is a baseline only when it is a different MODE — the empty-set
exception is load-bearing for health's api-only runs and wrong everywhere else.

**Run IDs are UTC and the page renders Eastern.** `consent-2026-08-23_0109`
displays as "Aug 22, 9:09 PM EDT". Both correct; a run ID quoted aloud sounds a
day fresher than it is.

### Still true and unchanged

**Nothing is scheduled.** All four crons stay commented out. Turning them on is
still the next real decision and email-dns is still the one to do first:
credential-free, no browser, no variance.

**The scoreboard is still 32** — sites with no health evidence at all. The
component inventory does not move it; it covers sites that already had health
evidence.

### Earlier on 2026-08-23 (first pass)

Item 21 (`wp_unestablished`, `wp_update_status_unknown`), item 22 (Pantheon's
mu-plugin PHP notices ahead of WP-CLI's JSON), the security event log into git,
and the workbook coming off the dashboard. Detail in the sections below and in
`docs/SECURITY-EVENTS.md`. Also this session: the `git` ban was lifted, the
dead `fleet_cloudflare_access.md` memory pointer in CLAUDE.md was replaced with
the real record in `docs/DASHBOARD.md`, and `docs/GETTING-STARTED.md` was added
as a one-page orientation for viewers.

### What changed 2026-08-22

**The consent sweep runs a HEADED browser and the 403 problem is solved.**
50 of 78 -> 77 of 78. The variable was `headless`, nothing else: not the
vendor, not the User-Agent, not the IP, not the rate. Headless also could not
see Hotjar or Meta Pixel on ANY site, so every earlier count was an undercount.
Full method in `docs/CONSENT.md`, "The instrument".

**CI runs headed too, via xvfb, proven on a runner.** The sweep verifies its own
browser: it reads the User-Agent on the first result and exits 3 if it asked for
headed and got headless, so a broken display can never silently produce
undercounted rows.

**A change of INSTRUMENT is not a change in the fleet.** Runs carry a `method`,
separate from `mode`, and `previous_run_of_same_source()` refuses a baseline
whose method differs. Without it the first headed run was a wave of false ONSET
rows. Health/email/nexcess declare no method and are unaffected.

**The coverage guard now covers publishing, not just ingest.** The page states a
coverage drop above the coverage box, and `publish-dashboard.sh` refuses to
upload without `--allow-coverage-drop`. Separately, `persist-ledger.sh` was
DISCARDING the very run that tripped the ingest guard: it ran ingest bare under
`set -e`, so the job died before the commit. Fixed; it stores first and fails
after.

**`ci/github-actions/` is gone.** It was a gitignored mirror of
`.github/workflows/`. Edit `.github/workflows/` directly. Do not recreate a
mirror.

**Four written-down action items turned out to be wrong**, each disproved by one
command. They are corrected in place below: the Pantheon allowlist request (a
Cloudflare challenge, wrong vendor), two Workers already pinned, "delete
`github-deploy-[removed]`" (its CI uses it), and a bucket name in
`cf-worker-r2.js` that does not exist. The habit worth keeping: check a claim
before acting on it. This repo already applies that to code; it applies to these
notes just as hard.

### 2026-08-23, later: the workbook is off the page, and the event log is in git

**`docs/SECURITY-EVENTS.md` is new and is the important one.** Three incidents —
the April reCAPTCHA compromise, wp2shell in July, and **Pods (CVE-2026-19598) on
2026-08-20** — copied out of the workbook's `Security Event Log` sheet, which
had never been extracted. `extract-audit-workbook.py` reads `Sites` and
`Security Plugins` and nothing else, so a live incident record existed in
exactly one place.

**Three sites had users added in the Pods incident**: `breakstones`,
`frontline-construction`, `zehnder-america-zna`, each with "salt rotated" beside
it. Doug: caught early, believed resolved, team meeting 2026-08-24. The log's
own status points at an "outstanding issues tab" that does not exist.

**A dashboard feature for capturing security events was deliberately NOT built.**
Three incidents is not a schema, `Remediation Complete?` is already a lifecycle
nobody specified, and the team meets on the live one tomorrow. The five
questions to settle first are at the bottom of `SECURITY-EVENTS.md`.

**The extractor was mis-mapping columns and would have imported the wrong one.**
It keyed on POSITION with `notes` at index 27. The workbook gained three columns
(`GCDN Configured`, `WAF Mode`, `Admin Routes Protected by IP Access Rule`)
before `Notes`, which moved to 30. Re-running it would have written GCDN values
into the notes field on all 78 sites and exited 0. It now resolves columns by
HEADER TEXT and hard-errors on a missing one. Verified against the live header:
`notes` resolves to 30, and a renamed column exits non-zero.

**The word "workbook" is gone from the page.** Not the findings — the
reconciliation section is the highest-signal thing on it — but the wording now
describes the inventory, which is what the page actually reads. Seven
reconciliation strings were rewritten in `fleet-inventory.json`. A test that
pinned the literal "absent from the workbook" was rewritten to assert the
property its own name states.

**UI pass, all measured rather than eyeballed:**

| change | why |
|---|---|
| removed "the SSH-based full scan is not wired up yet" | false for four days, and contradicted the coverage block on the same page |
| masthead drops the tool count | it said 3; there are 4 registered sources |
| one provenance block, "What this page knows, and what it does not" | provenance was in five places. The coverage box moved up under the scoreboard and absorbed the run line. Per-number caveats stay inline with their numbers |
| the block lists every REGISTERED source | Nexcess shows "never run" rather than being absent, which would read as "not covered" |
| legend loses its 32-domain list | 233px of a 879px section, inside a block headed "What the states mean". The health card already names the number one screen above |
| new table filter, "No health evidence" | reproduces that list exactly — verified, 32 rows |
| suite card chips are buttons that filter and jump to the table | "Every site" is 47% of the page and starts at 53%, about seven screens down. Reordering was the obvious fix and the wrong one: opening on a table where 73 of 84 rows say WARN reads as "everything is broken". Verified: health OK jumps to exactly the 4 OK sites |
| the chip tooltip names the state, not the count | card counts exclude `production: false`; the table still shows those rows. Consent UNKNOWN says 10 and lists 11, the extra being cm-whitelabel |

**One mistake worth recording.** The first attempt to move the coverage block
sliced from a `# --- coverage ---` banner to a `# --- reconciliation ---` banner
and swallowed two whole sections, because an earlier comment matched the start
marker. The assert only checked the block contained the heading, not that it
contained *nothing else*, so it passed. Caught by measuring the rendered section
order, not by a test. Bound a slice on both ends and assert what it must NOT
contain.

**Section titles rewritten after Doug read the page, same day.** Three of them
assumed knowledge a first-time reader does not have:

- **"What this tool can now see"** reads as "new tooling was added". It is not
  that: it fires on any coverage change in EITHER direction since the previous
  run. Now **"What the scanner started, or stopped, being able to see"**, and
  the blurb says a fact going dark is a defect in the run, not good news.
- **"Still true"** left the obvious question unanswered — true since when? Now
  **"Still open, as of the latest run of each tool"**, and it names *What
  changed* rather than saying "the section above", which stopped being accurate
  the moment a section was inserted between them.
- The provenance blurb said **"Nothing is copied from a spreadsheet"** — an
  homage to the workbook we had just spent the session removing — and **"the
  only values a person types"**, which reads as though someone types into this
  page. It now names the two kinds of value on the page, measurement and
  ruling, says where each comes from, and states that nobody edits the page.

**Not done, deliberately:** "Still open" is 1704px, the largest block before the
table and bigger than the legend that prompted this. Raised, not changed.

### BACKLOG 2026-08-23: decommission the test/temp sites

**Doug is confirming with the team. Nothing has been changed.** He named the
two Mooresville sites and cm-whitelabel; the evidence says the set is probably
the six sites absent from the workbook, all on the Sandbox plan:

| site | state | evidence |
|---|---|---|
| `clevermethod-forward` | SKIP | live env never initialized |
| `moorseville-nc` | SKIP | live env never initialized |
| `pfannenbergsales` | SKIP | live env never initialized |
| `nc-moorseville` | FROZEN | frozen by Pantheon; near-duplicate name of `moorseville-nc` |
| `hoffmanscheese` | CRIT | no backup in 725 days, core update pending |
| `cm-whitelabel` | CRIT | 6.9.4, no database installed, already `production: false` |

Separately, `eamusicfest.com` and `hitsfoundation.org` carry
`decommission_candidate: true` from the workbook import, with notes asking the
same question. Different sites, same conversation.

**Three things to settle before anything is changed:**

1. **A ruling, not an inference.** CLAUDE.md says not to infer `production`
   from the Pantheon plan, because that would have excluded the fleet's
   worst-maintained site — which is `hoffmanscheese`, on this list. The team
   deciding a site is a test site is exactly what `production: false` records.
   "They are all Sandbox" is not the same statement and must not become the
   reason.
2. **Removing `hoffmanscheese` takes fleet CRIT from 2 to 1.** Correct if it is
   genuinely a test site. It is also the shape of improving a number by
   deleting the evidence, so the record should say which it was.
3. **Do not delete inventory rows.** Each of these has 7 ledger rows, the
   ledger is append-only and keyed on `site_id`, and the site still exists on
   Pantheon — so the next scan rediscovers it and its rows land unresolved
   (`sites_not_in_inventory`, and a test asserts no committed run left one).
   **Decommission on Pantheon first, then update the inventory.**

**Mechanism:** `production: false` already does the right thing — excluded from
fleet counts, still scanned, still shown, still scored on its own row. Used
once today, on cm-whitelabel.

**`decommission_candidate` is a dead field.** Written by
`build-fleet-inventory.py`, read by nothing. Either wire it into the page or
drop it; a field nobody reads and nobody updates is the same problem the
consent-ownership note is parked on.

**Numbers this moves if all six go:** fleet 84 -> 78, the Pantheon denominator
52 -> 46, and CLAUDE.md's headline still says 84. The HEALTH-COVERAGE
scoreboard of 32 is NOT affected — none of these are in it.

### Open, and what it is waiting on

- **Matt, on the Cloudflare rules.** 8 sites block the CI runner because a
  custom rule "Challenge the top abusive ASNs" lists AS8075 (Microsoft/Azure).
  Confirmed from firewall events on 42northbrewing. The rule is on all four
  zones inspected. Fix is a Skip rule at Order 1 matching a secret header, the
  same shape as the "Allow safe IPs" rule already on `clevermethod.com`. Once
  it lands, CI reaches 77 and the weekly `schedule:` block can be uncommented.
- **Nexcess support**, ticket sent 2026-08-22. Unblocks the estate scan and
  should take the never-scanned count from 32 to 11.
- **The API tokens.** `github-deploy-[removed]` still needs RE-SCOPING from All
  accounts to one. See item 4.

- ~~**`run-all-fleet-scans.sh` hardcodes `run_mode=api-only`**~~ **FIXED
  2026-08-22.** Full is now the default in three places: the run-everything
  script, the workflow's own `run_mode` input, and CLAUDE.md's documented
  command. `api-only` remains selectable — it needs no SSH key and is the
  fallback if `PANTHEON_SSH_KEY` is ever revoked — but it is no longer what you
  get by not choosing.

  Three stale claims caused this, and all three are corrected: the workflow
  header said "PHASE 1 (now): API-only, no SSH key" long after the key was
  registered and full had run in CI; the run-everything script passed
  `api-only` for a reason that had expired; and CLAUDE.md documented the
  api-only invocation as *the* scan command. test-ledger.py now asserts all
  three, including that the header no longer makes the false claim.

### ~~OPEN~~ FIXED 2026-08-23, item 21: an api-only run makes 45 sites read OK

**Fixed the same day it was written down.** `severity.py` gained
`wp_unestablished`, a WARN on the health axis: a site whose WordPress status
was never established cannot reach OK, whichever mode failed to establish it.
Rationale in `docs/SEVERITY.md`.

Measured after the fix, both runs rendered and looked at:

| run | mode | before | after |
|---|---|---|---|
| `health-2026-08-23_0033` | api-only | 2 CRIT / 32 WARN / **45 OK** | 2 CRIT / 77 WARN / **0 OK** |
| `health-2026-08-23_0111` | full | 2 CRIT / 70 WARN / 7 OK | **unchanged** |

The live page does not move, because the newest health run is full and the rule
is silent on it. That is the point: it fires only in the window where the page
was lying.

Three things worth keeping from the fix:

- **The page was already half-right.** The coverage box said "WordPress core,
  plugins, themes (needs SSH): 0 of 52" and the standing findings said
  "WordPress core, plugin and theme status not observed" — on the same page as
  45 OK. A contradiction inside one page is not caught by any test that reads
  one number.
- **The HEALTH-COVERAGE scoreboard is unchanged at 32, deliberately.** It counts
  sites with no backup age AND no plugin or theme count; an api-only site has a
  backup age, so it is not one of them. Folding these in would have moved Doug's
  scoreboard for a reason that is about the scanner's mode, not the fleet.
  Flagged rather than done.
- **A ledger test fixture was silently measuring nothing.** `row()` in
  `test-ledger.py` defaults to an api-only row, so the "status move driven only
  by new visibility is COVERAGE" check had both sides land on WARN once this
  rule existed, and the status fact stopped moving at all. The fixture's AFTER
  side is now a clean deep scan, so the move is WARN -> OK and the check
  measures what its name says.

The original write-up follows.


**Found by reading a dry-run page, in the window between two batches.** Batch 1
ran api-only; the render said **2 CRIT / 32 WARN / 45 OK** while the coverage
box on the same page said **"WordPress core, plugins, themes: 0 of 52"**. The
page claimed 45 sites were fine and that it had measured nothing about their
WordPress, simultaneously. Batch 2 ran full and it went back to 7 OK, which is
how this stays invisible.

Every severity rule correctly refuses to fire on `unknown`. The gap is in the
two guards meant to catch the consequence:

- `wp_version_unknown` requires `wp_checked is True` — a deep scan that ran and
  failed. In api-only `wp_checked` is `False`, so it never fires.
- `coverage_partial` requires a site seen by Nexcess or consent but NOT by
  health. Here health DID see it, just without SSH.

api-only lands between them. **The rule that should exist is the sibling of
`coverage_partial`: a site whose WordPress status was never established cannot
reach OK, whichever mode failed to establish it.** Not urgent while full is the
default, but api-only remains the no-SSH fallback, so it will recur.

### ~~OPEN~~ SETTLED AND FIXED 2026-08-23, item 22

**Measured, not argued. Neither hypothesis in the original write-up was right.**
`diagnose-wp-calls.sh` was run against all five suspect sites. There are TWO
causes, and the four that mattered were losing real data:

| site | Pantheon name | scanner recorded | WP-CLI actually returned |
|---|---|---|---|
| galbanicheese.com | `galbanicheese` | up-to-date, 0, 0 | **7.1 available, 15 plugins, 3 themes** |
| lifebreath.com | `life-breath` | up-to-date, 0, 0 | **7.1 available, 5 plugins** |
| morrison-chs.com | `morrison-chs` | up-to-date, 0, 0 | **7.1 available, 6 plugins** |
| sgroilawley.com | `sgroifinancial` | up-to-date, 0, 0 | none pending, **1 plugin** |
| cm-whitelabel | `cm-whitelabel` | up-to-date, 0, 0 | nothing — no database installed |

**Four of the seven OK sites were OK because their output was being thrown
away.** Not one of them was a failed connection: every call exited 0 and the
JSON was intact.

**Cause 1, the four sites: a `strip_noise` gap.** Pantheon's own
`wp-native-php-sessions` mu-plugin emits ~40 lines of `PHP Deprecated: Return
type of Pantheon_Sessions\Session_Handler::open(...)` on PHP 8.2, on STDOUT,
ahead of WP-CLI's JSON. `strip_noise` did not cover those lines, so
`json_or_empty` refused the whole response and the scanner wrote its default.
**The RUNBOOK has predicted this exact failure since it was written** — *"jq
parse failures | new noise line not covered by strip_noise | add the pattern"*.
It was never acted on because there was no symptom: the defaults turned a parse
failure into a clean measurement.

**Cause 2, cm-whitelabel: no database.** Every call that needs the DB exits 1
with *"The site you have requested is not installed"*. `wp core version` reads
the version off disk, needs no DB, and answers 6.9.4 — which is why the row
looked measured. The control call is what separated this from a dead SSH path.

**Both fixed, in one change:**

- `strip_noise` covers `PHP Deprecated:` / `Deprecated:` / `PHP Notice:` /
  `Notice:` / `PHP Warning:` / stack-trace frames. `Fatal error` is
  deliberately NOT filtered — a fatal should stay unparseable and record as
  unknown.
- The scanner's three branches now distinguish a genuine `[]` from an empty
  result: `wp_core_update` goes to `unknown`, `plugin_updates` and
  `theme_updates` to JSON `null`, which `fact()` already reads as UNKNOWN. No
  ingest change was needed.
- The scanner's own status no longer says OK when a WP-CLI call did not answer.

**Two mock sites carry the regression:** `noticysite` (notice wall in front of
real data — asserts 15/3/7.1 come through) and `dbmissing` (cm-whitelabel's
shape — asserts unknown/null/null and not-OK). `run-local-test.sh` is 42.

**NOT YET DONE: the ledger still holds the old numbers.** These fixes change
what the NEXT scan records; `health-2026-08-23_0111` still says those four
sites are clean, and the live page still shows 7 OK. **A full scan needs to be
run and ingested before the page tells the truth**, and the four sites will
move from OK to WARN/CRIT when it does. That is the fix landing, not the fleet
getting worse — three of them have a WordPress core update pending that has
been invisible the whole time.

The original write-up follows.


**READY TO SETTLE. Run one command and this stops being a question.**
`scripts/diagnose-wp-calls.sh` was written 2026-08-23 for exactly this. It runs
the scanner's four WP-CLI calls against named sites and reports, per call,
whether the clean value the scanner would record is a MEASUREMENT or a
FABRICATION:

```bash
./scripts/diagnose-wp-calls.sh --json reports/item22.json cm-whitelabel sgroilawley
```

**Load the SSH key into the agent first** — `ssh-add --apple-use-keychain
~/.ssh/id_rsa`. On 2026-08-23 the first real run stopped at `Enter passphrase
for key`: the agent held no identities, and ssh reads that prompt from
`/dev/tty`, which the script's `< /dev/null` does not close. An unanswered
prompt is killed by the 60s timeout and reported as a failed call — a fact
about one laptop wearing a fleet finding's clothes, which is the `probe`
mistake exactly. The script now preflights `ssh-add -l`, warns before running
anything, and if timeouts occur while the agent was empty it says so in the
summary instead of letting you record it as evidence.

Needs terminus, a Pantheon session and the SSH key — so it runs on your laptop
or in CI, not from a Claude session. Exit 0 means every call was real; exit 2
means at least one failed and the scanner would have written a clean value for
it. **Put `sgroilawley` (or any site with known pending updates) in every
batch**: a run where everything reads clean is either good news or a dead SSH
path, and without a control you cannot tell which.

What it does that the scanner cannot:

- **It keeps stderr.** `run_with_timeout` sends it to `/dev/null`, which is
  right for parsing and is why nobody has ever seen why a call failed. The
  reason a call failed is the thing that was being discarded.
- **It separates `json_or_empty`'s two rejections** — "nothing came back" and
  "something came back and it was not JSON". The scanner sees one empty string
  for both, plus for a timeout, plus for a genuine `[]`. Four events, one
  value.
- **`core version` is the CONTROL.** It shares the SSH session with the other
  three. If it returns a version and `core check-update` returns nothing, the
  session worked and the empty result is a real answer — which is precisely
  the distinction this item is blocked on.

A drift guard in `test/test-wp-calls.py` asserts the diagnostic's four calls
and its timeout are exactly the scanner's. A diagnostic that runs slightly
different commands answers a different question and looks like it answered this
one, and the answer would go straight into this file as settled.

**Do not change the defaults until this has been run.** The original write-up
follows.


`pantheon-fleet-healthcheck.sh` sets `wp_checked="true"` BEFORE the WP-CLI
calls, then:

- `plugin_updates=0` and `theme_updates=0` stay at their defaults if the call
  returns nothing — recorded as "we looked, nothing pending".
- `wp_core_update` falls to `"up-to-date"` on an empty result, which is the
  same answer as a genuinely current site.

`wp_version` gets this right (`[ -z "$wp_version" ] && wp_version="unknown"`).
Its three siblings do not. This is the FIRST row of CLAUDE.md's table
(`plugin_updates: 0 | nobody looked`) surviving in a narrower form: the
whole-site case was fixed, the per-call case was not.

**Evidence it may be live, not theoretical.** On `health-2026-08-23_0111`, five
sites report `plugin_updates: 0`, and four of them report
`wp_core_update: up-to-date` while running a version below 7.1 — which we know
exists, because `sgroilawley.com` runs it. `cm-whitelabel` is among them at
6.9.4, BELOW the wp2shell floor, reporting up-to-date.

**NOT ESTABLISHED, and do not assume either way:** whether those four are
failed calls or whether Pantheon's upstream delivery model makes
`wp core check-update` legitimately answer "up-to-date" for a site whose core
it manages. Both are plausible and nothing recorded separates them. Settle that
BEFORE changing the defaults, or the fix will be aimed at the wrong cause —
which is the mistake this file has recorded five times now.

The plugin COUNTS themselves look sound: across 48 sites, 08-20 to 08-23, 36
were unchanged, 11 moved by 1-5, and one dropped 10 to 1 (someone ran updates).
Failed calls would look like noise, not that. It is specifically the ZEROS that
cannot be distinguished from silence.

### PARKED 2026-08-22: consent ownership, so a finding knows who to route to

Deliberately not built. The analysis is done and is in `docs/CONSENT-DELTA.md`
§3b — the sweep reports all 78 sites identically, but a finding on a site whose
CMP is in clevermethod's tenant goes to Nick, and one on a client-tenant site
goes to the account lead. `animatics.com` is the live example: it was flagged,
and Nick cannot act on it.

**The design was agreed, so do not re-derive it:**

- One inventory field, `consent_owner: "clevermethod" | "client" | null`,
  sitting beside `production` and `in_workbook`. It is a CLAIM, not a
  measurement, and belongs in the human-owned layer.
- **Tri-state with a fail-safe null, exactly like `production`.** `null` means
  nobody has ruled and routes to US. The same argument applies verbatim: a site
  must not stop being watched because nobody got round to classifying it.
- **It changes ROUTING, never SEVERITY.** It may split standing findings into
  "ours" and "the client's", add a filter, and let the consent card say "29
  leaking, of which 4 are in our tenant". It must never decide whether a
  finding is reported. Ownership is the field most likely to go stale — it
  changes every time an implementation is sold — so it is the last field that
  should ever be allowed to hide something. A `consent_owner: client` that
  suppresses a WARN is this project's signature bug with a new label.

**The commercial half is the point, not a side effect.** Client-tenant findings
are an asset: "we observed these trackers firing before consent on the site
your team manages" is something we bring them. The reporting should make that
list easy to lift out and send, not bury it.

**BLOCKED ON A DECISION, not on code:** who maintains the field and on what
cadence. `onetrust-audit.xlsx` covers only the 15 OneTrust sites; the 34 with
no tooling at all have no evidence of ownership anywhere, so their value is a
pure judgement call. That answer decides whether this is 15 rows or 78, and
should be settled before anyone writes code. A field nobody updates is a lie
with a timestamp.

### The older entries below are kept, and some are wrong

Everything under this line predates 2026-08-22 and is corrected in place where
it was found to be wrong. Read the strikethroughs; they are the record of what
was believed and why it was not true.

### What changed 2026-08-20

**Scoring is per AXIS.** `health` and `consent` are separate questions with
separate statuses. Health had been silently driven by consent: 38 of 70 WARN
sites carried a consent finding and 7 were WARN for consent alone.

| | before | after |
|---|---|---|
| health | 2 CRIT / 70 WARN / 7 OK | **2 CRIT / 63 WARN / 14 OK** |
| consent | (none) | **0 CRIT / 38 WARN / 16 OK / 25 UNKNOWN** |

Read `docs/SEVERITY.md` and project memory `fleet_axes.md` before touching the
scorer. An axis is a QUESTION, not a workflow, and `axis_of()` raises for an
unmapped code rather than defaulting to health.

**The page leads with one card per question**, then the detail sections. The
site table has a captioned Consent column and a second filter that combines
with the first. The masthead was compressed so all three cards clear the fold.
Run times render in Eastern, 12-hour, always zone-labelled.

**The workbook columns are gone** from the page and the feed. Doug: "we don't
need to compete with the old way." `in_workbook` still feeds the
production-ruling queue and the inventory still holds the values.

**Coverage drops are caught at ingest.** A run that measured fewer sites than
the previous run of the same source prints what was lost and exits non-zero
unless `--allow-coverage-drop`. The run is still stored; the ledger is
append-only. See `fleet_coverage_guard.md`.

**...but in CI that exit code was throwing the run away, fixed 2026-08-22.**
`persist-ledger.sh` runs under `set -e` and called `ingest` bare, so the
non-zero exit killed the script before add/commit/push and without retrying.
On an ephemeral runner the degraded run that raised the alarm was the one run
guaranteed never to reach the ledger. It now passes `--allow-coverage-drop`
and reports the drop after the push, with the other post-push alarm. Publish
is gated on the persist job succeeding, so a drop still blocks the page.

**Cloudflare was audited and cm-fleet was redeployed.** The deployed Worker had
been a day behind the repo, still carrying the `PUT /api/publish/` route and
its `PUBLISH_TOKEN`. Both gone, verified by reading the deployed artifact back.

**`publish-dashboard.sh` no longer demands a token on a laptop** — it falls
back to the wrangler OAuth session. CI still uses the token.

### Tomorrow, in order

1. **Publish** (above). Then open the page and look at it.
2. **The publish-side coverage-drop guard.** Ingest fails loudly now, but
   ingest and publish can happen in separate sessions, so this is the layer
   that would actually have stopped 2026-08-19. `fleet-consent.yml` has
   `publish_dashboard` defaulting to TRUE, which is why the commented-out
   `schedule:` block must stay commented until this exists.
3. ~~**Pin `workers_dev = false` on [removed], [removed] and [removed].**~~
   **MOSTLY DONE — measured 2026-08-22 by parsing every config, not by
   reading the line.** Four of the five Workers on this account pin it:

   | Worker | config | `workers_dev` |
   |---|---|---|
   | `cm-fleet` | `ci/cloudflare/wrangler.toml` | pinned `false`, top-level |
   | `[removed]` | `~/dev/[removed]/wrangler.toml` | pinned `false`, top-level |
   | `[removed]` | `…/Partner Dashboard/[removed]/wrangler.toml` | pinned `false`, top-level |
   | `[removed]` | `…/clevermethod-com-2026/04-New Site Build/Active/cm-staging/wrangler.jsonc` | pinned `false` (JSON, no TOML ordering trap) |
   | **`[removed]`** | **none exists** | **nothing pins it** |

   `[removed]` and `[removed]` were already done and this note never caught up.
   Each was verified with `tomllib` / a JSON parse, so the TOML ordering trap
   is ruled out rather than eyeballed.

   **The remaining gap is `[removed]`, and it is the one holding
   partner-confidential material.** `~/dev/[removed]` has no wrangler config at
   all; `deploy.sh` only does `wrangler r2 object put`, never `wrangler
   deploy`, so the Worker is dashboard-managed and its toggle is held by
   nothing but a manual click. Adding a `wrangler.toml` is NOT a free fix —
   creating one where none existed changes how the Worker can be deployed, and
   a wrong `main` would ship the wrong code. Decide deliberately: either add a
   correct config that pins it, or write the dashboard-managed status into
   `deploy.sh` so the next person knows the toggle is the only control.

   **Why the pin is load-bearing, confirmed by reading the DEPLOYED code of
   both Workers on 2026-08-22.** Neither `[removed]` nor `[removed]` has any
   authentication of its own worth the name:

   - `[removed]` `/api/save` accepts ANY non-empty
     `Cf-Access-Authenticated-User-Email` and writes to R2 on it.
     `/api/harvest`, `/api/asana`, `/api/financials` and `/api/notes` check
     nothing at all, and the financial seed data is compiled into the Worker.
   - `[removed]` gates `analytics.html` and `/api/stats` on that same header
     starting with `doug`. `/api/harvest` and `/api/asana` check nothing.

   Both are fine **only** because Access is the sole route in. On a
   `workers.dev` URL the header is client-supplied, so the pin is not
   hardening — it is the whole control.
3b. **`[removed]` addressed 2026-08-22, without adding a config.** The Worker is
   dashboard-managed by an explicit earlier decision, and a `wrangler.toml`
   declaring bindings nobody can enumerate could drop one on the next deploy.
   Instead the constraint is written into `deploy.sh` and
   `[removed]/.github/workflows/deploy.yml` (that repo, not this one) — the two
   files someone would touch — so the
   risk is no longer silent. Also fixed a comment in `cf-worker-r2.js` naming
   bucket `deck-assets`, which does not exist; the account has only
   `[removed]` and `dash-data`. That is the line someone would copy into
   a config. **The dashboard toggle remains the only live control — re-check
   it after any change to that Worker.**

4. **The API tokens — audited 2026-08-22, and one instruction here was
   wrong.** All three are no-expiry USER tokens on Doug's personal
   Cloudflare account. `github-deploy-[removed]` is scoped to **All accounts**
   and can reach `clevermethod, Inc.` too. **RE-SCOPE it, do NOT delete it** —
   this line used to say "delete or re-scope", and delete is wrong:
   `[removed]/.github/workflows/deploy.yml` uses `CLOUDFLARE_API_TOKEN` on every
   push to main, so deleting it breaks deck deploys. It needs R2 write on ONE
   account, not all of them.

   | credential | scope | last used | expiry |
   |---|---|---|---|
   | `cm-fleet r2 publisher` | 1 account, R2 only | Aug 22 | none |
   | `Cloudflare Agent Token` | +20 perms, **all zones** | Jul 18 | none |
   | `github-deploy-[removed]` | **all accounts**, R2 write | Jul 18 | none |
   | **Global API Key** | everything, cannot be scoped | — | none |

   `cm-fleet r2 publisher` is correctly scoped and is the only one in active
   use; it needs an expiry, nothing else. The Agent Token is auto-created by
   Cloudflare Ask AI, carries 20+ permissions across all zones, and has not
   been used in a month — revoke unless Ask AI is in active use. The Global API
   Key cannot be scoped at all; check nothing depends on it, then roll it.
5. ~~**Ask Pantheon to allowlist the consent scanner.**~~ **WITHDRAWN
   2026-08-22 — Pantheon is not the blocker and this request would have done
   nothing.** All 20 answer from Cloudflare with a bot challenge; the request
   never reaches Pantheon. It is per-zone Cloudflare settings across at least
   four different DNS providers, so there is no one conversation and no one
   owner. See "The 403s" below for what replaces it.
6. ~~**Send `docs/NEXCESS-SUPPORT.md`.**~~ **SENT 2026-08-22**, both questions
   in one ticket. Now waiting on Nexcess, not on us. Do not re-send. Record
   their answers per "When they answer" in that file.
7. **Asana routing.** The last unbuilt step of deck slide 16.

### The 403s — SOLVED 2026-08-22. The variable was HEADLESS.

**The scanner now runs headed and 27 of the 28 blocked sites load.** No vendor
conversation, no allowlist, no client access, no per-zone work. One setting.

Everything below is kept because the route to the wrong answer is worth
reading: the notes said Pantheon was blocking us and the fix was an allowlist
request; the blocker was a Cloudflare bot challenge on the clients' own zones;
the remedy for that would have been a WAF Skip rule, which Bot Fight Mode does
not support on a free plan; and the actual answer was none of those. Three
wrong answers were written down as action items before anyone changed one
setting and measured. Full methodology in `docs/CONSENT.md`, "The instrument".

**The bigger half of that finding:** headless also could not see Hotjar or Meta
Pixel on ANY site, so the 50 sites it *could* read were undercounted too. This
was never only about the 28.

**CI wired for xvfb 2026-08-22 and PROVEN THE SAME DAY.** A two-site manual
run (`only=zehnderamerica.com,blockclub.co`, both ledger and publish off)
returned `scanned 2 of 2`. `zehnderamerica.com` is blocked to a headless
browser, so scanning it is positive evidence that headed genuinely worked on
the runner rather than an absence of errors.

The self-check that made it safe to ship unproven is still in place and still
earns its keep: the sweep reads the browser's own User-Agent on the first
result and exits 3 if it asked for headed and got headless, before anything
reaches the ledger. It guards every future run, not just the first.

The `schedule:` block stays commented out. The publish-side coverage guard now
exists, but a cron sweep should not be enabled in the same change as an
unproven CI browser.

### The 403s, split by host — the headless-era measurements

| host | blocked from a laptop | blocked from CI | of |
|---|---|---|---|
| **CM Pantheon** | **20** | 22 | 47 |
| **CM Nexcess** | **1** | **15** | 21 |
| Azure | 3 | 3 | 4 |
| Flywheel / Pressable / WP Engine | 0 | 0 | 6 |

**Two different causes, and conflating them makes this look like one big
blocker when it is two small ones.**

- **Nexcess is IP reputation.** 1 from a residential connection, 15 from a
  GitHub runner. Nothing to fix — run it from a normal connection.
- **Pantheon is ~~a bot rule~~ A CLOUDFLARE BOT CHALLENGE, corrected
  2026-08-22.** The half that was right: 20 blocked from both IPs identically,
  so it is not about where the request comes from. The half that was wrong:
  whose rule it is.

**What was actually measured, 2026-08-22.** Nobody had read a response header
before writing the action item down. All 20 blocked CM Pantheon sites:

| | |
|---|---|
| `server: cloudflare` | **20 of 20** |
| `cf-mitigated: challenge` | 16 |
| 301 first, challenge after the redirect | 4 |
| reaching Pantheon at the point of blocking | **0** |

A site that scans fine looks different: `cottrillspharmacy.com` returns
`server: nginx` with `x-styx-req-id`, Pantheon's Styx edge.

**Being Cloudflare-fronted is not the trigger.**
`celticindustrialservices.com` is `server: cloudflare`, returns 200, and shows
a Pantheon `x-styx-req-id` behind it. So this is per-zone bot settings — Bot
Fight Mode or a WAF rule on those specific zones — not a platform policy.

**And they are not one estate.** Authoritative DNS across the blocked set:
Cloudflare (`clevermethod.com`, `ntlibrary.org`), Network Solutions
(`actioncarting.com`, `interstatewaste.com`), managed-ip (`zehnderamerica.com`),
MediaTemple (`galbanicheese.com`). Four providers, mostly Cloudflare
partial/CNAME setups fronting client-controlled DNS. `wrangler whoami` reaches
exactly ONE account, Doug's own; the `clevermethod, Inc.` account referenced
elsewhere in these notes is not reachable with that credential.

**So the next step is not a request, it is an inventory.** Which Cloudflare
account holds each of the 20 zones. Not yet established — the OAuth token
carries `zone (read)` and can answer it:

```bash
curl -s "https://api.cloudflare.com/client/v4/zones?per_page=100" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq -r '.result[].name' | sort
```

`clevermethod.com` is itself on the blocked list, so at least one is
self-service today. Split the rest into zones clevermethod administers and
zones the client does, and only the second group is a conversation.

**And invert the User-Agent advice.** The old note suggested an identifying
`cm-automation-consent-scan/1.0` UA to turn "allowlist these IPs" into
"allowlist this string". Against Cloudflare Bot Management a non-browser UA
scores **worse**, not better — the old note half-suspected this and now we know
the blocker.

**A skip rule may not be available at all, corrected 2026-08-22 against
Cloudflare's docs.** The first version of this note said the fix was "a WAF
skip rule on a custom header or source IP". That is true only on **Pro and
above**. Cloudflare's own documentation is explicit:

> You cannot bypass or skip Bot Fight Mode using WAF custom rules or Page
> Rules... it operates in a separate evaluation pipeline where *Skip*,
> *Bypass*, and *Allow* actions have no effect.

**Bot Fight Mode is the FREE-plan feature, and it has no exception mechanism
of any kind** — not by header, not by IP, not by user agent. On a free zone the
only choices are to turn Bot Fight Mode off (weakening the client's bot
protection) or upgrade that zone to Pro. Both are the client's decision and
one of them costs money.

**So the diagnostic that decides everything is which FEATURE is challenging,
per zone.** Cloudflare dashboard → the zone → Analytics → Events tab → the
**Service** field on a blocked request:

| Service says | Plan | Fix |
|---|---|---|
| `Bot Fight Mode` | Free | **No exception possible.** Turn it off, or upgrade to Pro. |
| `Super Bot Fight Mode` | Pro+ | Custom rule, action *Skip*, target *All Super Bot Fight Mode rules*. Straightforward. |
| a custom or managed rule | any | Adjust that rule. |

Until that field has been read for a given zone, nobody knows whether that
zone is fixable, cheap, or a paid upgrade. Do not promise a client a fix
before reading it.

**Whether this is worth doing at all is a real question.** The original note
sized it as "one conversation". It is now: per zone, get access, read the
Service field, then a decision that may cost money or weaken their security —
across up to 20 zones spanning four DNS providers. Weigh that against simply
reporting those sites as UNMEASURED, which the dashboard already does
honestly, and against the reframe below.

**The reframe worth considering.** "This site challenges automated clients" is
itself a finding worth telling a client, independent of consent. The same rule
blocks uptime monitors, accessibility scanners, SEO crawlers and partner
integrations. That is a conversation with value on its own, where "please let
our scanner in" is a favour we are asking for.

**This is a repeat of a documented failure.** CLAUDE.md's table already
carries `the token was rejected | a Cloudflare challenge; the token was never
read at all`, from the Nexcess portal. Same edge, same challenge, same
misattribution — a confident cause standing in for one nobody had established.

### Also open

- Standing findings still group by RISK / COVERAGE / PLANNING / DRIFT rather
  than by axis, so consent findings share one list with health and email.
- `hitsfoundation.org` fails TLS negotiation outright. Unrelated to consent.
- `pantheon-fleet-healthcheck.yml` still has its own inline publish job;
  folding it into `_publish-dashboard.yml` is a tidy-up.
- The 5 sites needing a production ruling, and the human triage queue.
- `reports/fleet-preview.html` is scratch in a gitignored directory.

### One incident worth reading

A patch script destroyed `scripts/render-dashboard.py` mid-session: it built a
replacement needle from `s[s.index(START):s.index(END)]` where END occurred
earlier in the file than START. Python returns `""`, `str.replace("", x)`
inserts x between every character, and the file went from 58KB to 58MB.
Recovered from the commit made twenty minutes earlier. **Commit before a
mechanical rewrite of a file, not after.** The rule is now in `CLAUDE.md`.

---

## READ THIS FIRST IF YOU ARE STARTING COLD

**`CLAUDE.md` in the repo root is the operating manual.** Read it before
touching anything. It holds the hard boundaries, the definition of done, and
the eleven-row table of times this project mistook a confident-looking value
for an answer. It was written 2026-08-19 and did not exist before that.

### BUILT LATER THE SAME DAY: Nexcess Phase 1

`scripts/fleet-nexcess.py`, `test/test-nexcess.py` (58 checks, offline),
`ci/github-actions/fleet-nexcess.yml`, `docs/NEXCESS.md`. Ledger source
`nexcess`, severity rules, and a renderer fix. **Not yet run against the
Nexcess API — no call has ever been made from this codebase.** The next action
is Doug running `./scripts/fleet-nexcess.py probe` with a portal token.

Measured this session on a simulated run (fixture data, never ingested into
`history/`): the render path works and the fleet moves
**2 CRIT / 31 WARN / 14 OK / 32 UNKNOWN → 9 CRIT / 45 WARN / 14 OK / 11
UNKNOWN**. OK does not move, by design: discovery gives no backup age and no
plugin counts, so a Nexcess site tops out at WARN with `coverage_partial` until
an SSH scan supplies them.

**Those simulated numbers are NOT fleet facts.** The real UNKNOWN count is
still 32 and stays 32 until a live run.

Rendering that page found the twelfth entry for CLAUDE.md's table: 21 sites
whose versions had just been measured still displayed the workbook's claim,
because the table columns read `php_version` and `wp_version` and the Nexcess
facts are stored under their own names on purpose. Fixed — the dashboard now
shows three labelled evidence tiers (plain / *per host* / *claimed*).

### ALSO BUILT TODAY: the cookie consent monitor, in the suite

`scripts/consent/run-sweep.mjs` + `check-site.mjs`, `test/test-consent.py`
(42 checks, offline, no browser), `ci/github-actions/fleet-consent.yml`
(credential-free), `docs/CONSENT.md`. Third ledger source `consent`, three
severity codes at WARN, `package.json` + lockfile committed.

**The pilot's `sites.yaml` is superseded. The roster is the inventory: 78
domains, up from 12.** Reconciling the pilot's twelve before writing any
integration code found **two wrong**: `morrisoncontainerhandlingsolutions.com`
does not resolve at all, and `hoosierfeedercompany.com` 302s to
`hoosierfeeder.com`. One in six, on the list that decides what gets watched.

That second finding moved a standing open item: `hoosierfeeder.com` resolves to
Cloudflare, not Pantheon's range, which is consistent with the workbook's "CM
Pantheon" being wrong. The origin host behind Cloudflare is **not** established
and the inventory note says so.

**Rendering a simulated full sweep took UNKNOWN from 32 to ZERO** with nothing
improved — the sweep reaches every domain, so no site is left in "nobody
looked". UNKNOWN was only ever the health-coverage number by accident. The page
now states health coverage on its own line and the JSON feed carries
`no_health_evidence`. **Watch that, not UNKNOWN.** Third time a render caught
something no test would have.

**RUN AND INGESTED 2026-08-19.** 54 of 78 sites genuinely seen: 17 clean with
OneTrust, **3 with tooling that leaks anyway** (`blockclub.co`,
`hoosierfeeder.com`, `pfannenbergusa.com`), 25 leaking with no tooling, 9 clean
with no tooling. 23 sites answer HTTP 403 to a headless browser and are
UNMEASURED. `zehnder-rittling.com` is clean.

**The first run caught a bug in the tool**: `ok` meant "page.goto did not
throw", so 23 HTTP 403 block pages were classified as having nothing to fix —
30% of the fleet clean on the evidence of an error page. Same shape as the
Nexcess probe reading a status code as an answer. Fixed, with a 403 fixture.

Fleet now: **2 CRIT / 70 WARN / 7 OK / 0 UNKNOWN / 3 SKIP / 1 FROZEN**, and 32
sites with no health evidence. The WARN jump is consent: 34 no-tooling +
28 leaking.

### The scope changed today

Doug, 2026-08-19: *"this dashboard (and eventual operating layer) is only
useful if it considers all of our sites, not just pantheon. additionally, i
want to have the cookie consent monitor built and running as part of a 'suite'
of automations built for our operation layer."*

So this is no longer one Pantheon workflow. It is **a suite feeding one
operating layer**, and the next two pieces are:

1. **Nexcess plumbing** — 21 sites with zero coverage today. See
   `docs/NEXCESS-ARCHITECTURE.md`, imported today and **entirely unverified**.
2. **Cookie consent monitor** — already exists as a runnable standalone pilot
   at `DK Sandbox/claude/Cowork Automation Portfolio/cookie-consent/`. Node +
   Playwright, read-only, zero credentials. It needs to be brought into the
   suite: same ledger, same dashboard, same severity vocabulary.

---

## WHAT SHIPPED 2026-08-19 (the day before)

**The dashboard is live at `https://fleet.thudstaff.com`**, behind Cloudflare
Access, updated automatically by CI. That was the goal of the whole build.

| thing | state |
|---|---|
| Severity model | **rebuilt.** `scripts/lib/severity.py`, the only scorer. `docs/SEVERITY.md` |
| Publish path | **rewired.** Renders from the ledger, uploads straight to R2 |
| Worker `cm-fleet` | **read-only**, no write route, no secrets. `workers_dev = false` |
| CI end-to-end | **proven.** scan -> ingest -> push -> render -> publish, all green |
| `CLAUDE.md` | **written.** The operating manual the deck promised |
| Tests | ledger 106, severity 68, mock 32, email 58 |

### The severity rebuild, in one paragraph

The old model scored **33 of 52 sites CRIT and nothing healthy**, because
`upstream_pending > 0` was a WARN and no site ever has zero. It also missed the
one genuinely exposed site, because that site's `wp_core_update` read
`up-to-date` while it ran WordPress 6.9.4. Scoring now lives in one module,
re-derived at render time, so a threshold change rescores all history instead
of reporting as a fleet change. Current: **2 CRIT / 32 WARN / 13 OK /
32 UNKNOWN / 3 SKIP / 1 FROZEN.**

**The 32 UNKNOWN are the point of the next phase: they are the sites no health
scan has ever reached.** 21 Nexcess plus the outlier hosts.

### The two real CRITs

- **`hoffmanscheese`** — no database backup in 721 days. Also absent from the
  audit workbook. Still needs a person.
- **`runtalnorthamerica.com`** — PHP 8.1, past end of security support since
  2025-12-31. Found only because the PHP table was unified; a hardcoded
  `< 8.0` floor missed it.

`cm-whitelabel` (WordPress 6.9.4, no backup in 2,147 days) is **closed** —
Doug ruled it a temp non-public site. It carries `production: false`, so it is
still scanned and shown but excluded from fleet counts.

---

## The goal, in Doug's words

> "I want a dashboard to view the automation data, not an XLS. The dashboard
> will eventually replace the xls."

Everything below serves that. The dashboard is the destination; the scans and
the ledger are how it gets fed.

Two decisions that follow from it, both made 2026-08-18:

- **Read-only for now.** Attestations, SSO and an audit trail come later, once
  it is in production. Access control is entirely Cloudflare Access at the edge
  and the app needs no auth of its own.
- **Hosting is Cloudflare.** CI is **GitHub Actions**; Azure DevOps is off.

---

## Where things actually stand

**The fleet has been measured.** First full-fleet full-mode scan completed
2026-08-19 00:02 UTC, 52 sites, in the ledger and pushed.

| thing | state |
|---|---|
| Repo | live, `github.com/dougkasperek/cm-automation`, private |
| Email DNS check, 78 sites | green in Actions, 26s |
| **Pantheon full mode** | **works locally AND in CI.** Run #5 green |
| **Full fleet scanned** | **52 sites, 48 deep-scanned.** Coverage 0 -> 48 of 52 |
| Unified 84-site inventory | built, keyed on domain |
| Ledger | 8 runs, both tools, every row resolving |
| Dashboard | 84 sites, real WordPress versions, verified both schemes |
| CI writes to the ledger | built, **never yet exercised** - see below |
| Tests | ledger **106**, severity **68**, mock harness **32**, email **58** |
| Publish path | **rewired to the ledger 2026-08-19.** Blocked only on Cloudflare setup |
| Severity | **rebuilt 2026-08-19**, `scripts/lib/severity.py`. See `docs/SEVERITY.md` |

### THE FIRST REAL RESULTS, 2026-08-19

```
52 scanned | 33 CRIT / 15 WARN / 3 SKIP / 1 FROZEN / 0 healthy
versions:  7.0.3 x33   7.0.4 x13   7.0.2 x1   6.9.4 x1   (4 never reached the WP stage)
32 sites have a core update to 7.0.4 pending
384 plugin updates pending across 43 of 48 measurable sites
```

**`cm-whitelabel` is on 6.9.4 — the only site below 7.0.2, so the only one below
the `wp2shell` fix line.** Two things make it worse: `wp_core_update` reports
`up-to-date`, so the pre-2026-08-18 columns called it clean and only the
installed version exposes it; and it has **no DB backup in 2,147 days**. Sandbox
plan, zero plugin updates, reads like abandoned internal scratch — **but it was
scanned on `live` and nobody has confirmed whether it resolves publicly. That is
the first question to answer.**

**`hoffmanscheese`: no backup in 721 days, 29 plugin updates.** Note that
`cm-whitelabel` and `hoffmanscheese` are the same two sites already flagged as
present in Pantheon and absent from the workbook. **The two sites with no audit
record are the two worst-maintained sites in the fleet.**

The workbook claims 7.0.2 and *plugins up to date* for all 78. Exactly **one**
site is on 7.0.2. 7.0.3 and 7.0.4 are both above the `wp2shell` fix, so those 45
are a maintenance backlog, not 45 emergencies.

### Known-good but unexercised

- **`persist_ledger` has never run.** It was unticked on run #5, so the job
  skipped. It also needs **Settings -> Actions -> General -> Workflow
  permissions -> Read and write**, or the push is capped at 403. That setting
  applies to every workflow in the repo; the tighter alternative is a
  repo-scoped fine-grained PAT used only by the persist step. **Undecided.**

## What was found and fixed on 2026-08-18 (second half)

Four defects, all of the same family: a value that looked like an answer and was
not one.

**1. The committed ledger was mis-keyed and incomplete.** It was written at the
initial import, before `data/fleet-inventory.json` existed, so its health rows
were keyed on Pantheon machine names rather than domains. `git log -- history/`
showed one commit, ever. Rendering from the repo as committed gave **130 rows
for an 84-site fleet** — 52 machine names and 78 domains, zero overlap — while
the `fleet.html` committed beside it correctly said 84, because it had been
rendered from a normalised ledger that was never committed. Rebuilt from
`reports/`; possible only because those four files still existed on one laptop.

**2. Nothing CI produced had ever reached the ledger.** `reports/` is
gitignored, ingest was a manual laptop step, and both workflows had
`contents: read`. Fixed by `scripts/persist-ledger.sh` and a `persist-ledger`
job in both workflows. **Read `docs/CI-LEDGER.md` before touching either.**

**3. The scan never recorded the WordPress version.** It ran
`core check-update`, which reports the version *available* and yields the string
`"up-to-date"` when there is none. The workbook claims 7.0.2 fleet-wide, and
`"up-to-date"` cannot be compared to `7.0.2`, so the central question of the
project was unanswerable from a scan that looked complete. Now captured as
`wp_version` via `core version`, stored as a deep-only fact, and rendered in its
own dashboard column that flags any disagreement with the workbook.

**4. Local runs stamped in Eastern, CI stamps UTC.** The ledger derives
`observed_at` from the filename stamp and orders runs by it to choose the pair it
diffs, so a laptop run and a CI run could sort four hours out of step and the
diff would compare the wrong pair. Dormant while only one machine wrote to the
ledger; live the moment CI does. `pantheon-fleet-healthcheck.sh` now uses
`date -u`.

Also: `fleet-ledger.py` and `render-dashboard.py` were committed
**non-executable**, so the `./scripts/...` commands in `SSH-KEY-SETUP.md` step 7
failed with *Permission denied*. Mode fixed on five scripts.

### Uncommitted on Doug's Mac right now, 2026-08-19 (severity work)

```
scripts/lib/severity.py      new    the only place severity is computed
docs/SEVERITY.md             new
test/test-severity.py        new    53 checks
scripts/fleet-ledger.py             COVERAGE class, re-derived scoring,
                                    cohort-run baselines, one PHP table
scripts/render-dashboard.py         fleet health + review queue sections
data/fleet-inventory.json           cm-whitelabel production:false;
                                    stale observed_status removed from 6 records
test/test-ledger.py                 named-run fixtures, 106 checks
fleet.html                          re-rendered
```

**`test/run-local-test.sh` has NOT been run against these changes** -- it
exceeds the desktop bridge's 45s timeout. The scanner was not touched, so it
should be unaffected, but run it before pushing.

### Uncommitted on Doug's Mac, earlier

```
docs/CI-LEDGER.md            new
scripts/persist-ledger.sh    new
ci/github-actions/*.yml      both workflows, to be copied into .github/
fleet.html, history/*.jsonl  the repaired ledger and its render
scripts/fleet-ledger.py, render-dashboard.py, pantheon-fleet-healthcheck.sh
test/test-ledger.py, test/run-local-test.sh, test/mock/terminus
five scripts with a corrected exec bit
```

---

## Do this next, in order

### 1. NEXCESS. This is the next build task.

21 sites, zero coverage, and the largest evidence gap in the security audit:
**every blank cell in the workbook's `wp2shell Security Flaw Remedied?` column
is a Nexcess site.** They are also 32 of the dashboard's UNKNOWN rows.

`docs/NEXCESS-ARCHITECTURE.md` holds Doug's research. **Read its provenance
header: nothing in it has been verified from this codebase.** The model it
proposes:

```
Portal API token  -> GET /v1/site        -> site inventory, Unix usernames
ONE automation    -> per-site SSH users  -> WP-CLI, read-only
SSH key
```

**The critical unverified claim** is that one SSH public key added at the
Nexcess user level authorises every Managed WordPress site that user can reach.
If true, this is one credential for 21 sites. If false, it is 21 credentials
and a very different design. Section 19 of that doc is a ready-made support
email; **sending it is a human task and it gates the SSH half.**

Sequencing that does NOT wait on that answer:

- **The 21 sites are already in `data/fleet-inventory.json`.** API enumeration
  is not required for a first pass; the inventory IS the site list. Enumeration
  only buys discovery of sites nobody wrote down — which on Pantheon found the
  two worst-maintained sites in the fleet, so it is worth having, second.
- Phase 1 of section 17 (read-only estate discovery via `GET /v1/site`) needs
  only a portal API token, and validates the doc's field-name claims.
- The deep-scan half reuses the Pantheon WP-CLI work almost unchanged. Same
  commands, different transport.

**The ledger, severity, diff and dashboard need NO changes** — they are keyed
on site identity, not host. Adding a provider means adding an adapter, and the
`UNKNOWN` count falling is the measure of success.

### 2. COOKIE CONSENT MONITOR, into the suite.

Lives at `DK Sandbox/claude/Cowork Automation Portfolio/cookie-consent/`. Node
18 + Playwright, loads each public homepage, watches what fires before consent,
detects banner tooling, writes a dated exception report. Read-only, no
credentials, already runnable.

Bringing it into the suite means:

- a third `source` in the ledger, beside `health` and `email-dns`
- its own fact family in `OBSERVED` (the fact-name collision guard in
  `fleet-ledger.py` will catch a mistake here)
- severity codes in `scripts/lib/severity.py`, using the same vocabulary
- its own CI workflow, same shape as the email one: no credentials, so it can
  run on every push

**Its roster is a separate `sites.yaml` of 12 domains**, drawn from Harvest
project names. That is a fourth site list, and this project has already been
bitten once by lists that disagree. **Reconcile it against
`data/fleet-inventory.json` before wiring anything.**

Note its README already describes the production shape: *"Claude reads a
CLAUDE.md, calls the same scanner, does the classification, opens Asana tasks
for new FAILs."* That matches the deck.

### 3. Asana routing — the last step of the deck's pattern.

Slide 16 promises: *"open an Asana item only where a person is needed, and keep
it open until confirmed."* Digest and dashboard are built; routing is not.
Asana appears in three design docs and no code. This is what turns a report
into an operating layer, and it is shared plumbing for every workflow in the
suite rather than Pantheon-specific.

### 4. Turn on the schedule.

The cron block is written and commented out in the workflow. The deck's own
rule is that execution is earned over several cycles; today was cycle one and
the first that ran end to end.

### 5. The scanner still scores severity itself.

`pantheon-fleet-healthcheck.sh` keeps its own inline rules, so its digest calls
a pending core update CRIT while the dashboard calls it WARN, and **its exit
code 2 still gates CI on the old definition**. Fixing it means a CLI mode on
`severity.py` and **changing what fails a build**. Left deliberately for a
decision. See the end of `docs/SEVERITY.md`.

## Three things that need a person, not code

1. **21 Nexcess sites have no `wp2shell` verification.** The only blanks in that
   column. Largest open evidence gap.
2. **`hoffmanscheese`** is in Pantheon but in nobody's audit. **`hoosierfeeder.com`**
   is in the audit but Pantheon does not return it.
3. **`shuman-plastics.com` and `dynapurge.com`** on Flywheel run PHP 7.4,
   unpatched since November 2022. Client-controlled hosting.

---

## Traps. Each of these cost real time already

- **Pantheon rejects ed25519 SSH keys.** Use RSA 4096. A rejected key looks like
  an auth failure, not a key-type failure.
- **Claude must not run ANY git command that writes the index** — not `commit`,
  and not `add`, `reset` or `update-index` either. It cannot delete
  `.git/index.lock`, so the repo is left locked and Doug has to clear it by
  hand. This happened again on 2026-08-18 via `git update-index --chmod=+x`.
  Claude edits files; Doug runs git.
- **`reports/` is gitignored**, so it does not exist on a fresh clone or a CI
  runner. Anything reading it must tolerate its absence, and **no test may
  assert a fleet size against it** — it holds whatever the last local scan
  produced, including one-site cohort runs. Deterministic assertions belong
  against the committed ledger in `history/`.
- **`history/` must NOT be gitignored.** The ledger is the one asset here that
  cannot be regenerated.
- **`ingest` is append-only, so a mis-keyed row cannot be corrected in place.**
  It has to be rebuilt from `reports/`, which only works while those files still
  exist. This is why a missing inventory is now a hard error.
- **GitHub's "Re-run jobs" replays the original commit.** Use **Run workflow**.
- **`.github/` cannot be written by the bridge**, so workflow edits land in
  `ci/github-actions/` and Doug copies them across. That directory is gitignored
  so a second diverging copy never gets committed.
- **The dashboard's light-mode palette is only legal because every state chip
  carries a text label.** Render a chip as a bare dot and the relief is gone.

---

## A recurring bug class worth naming

Six times now, a number read confidently and was wrong:

| where | what it said | what was true |
|---|---|---|
| the scan's `plugin_updates: 0` | no plugin updates pending | nobody looked |
| the email checker on a DNS timeout | no SPF record | the lookup failed |
| `standing()` in the dashboard | 1 site affected | 48 |
| the dashboard's `BACKUP: 0` | no backups | backed up today |
| the committed ledger | 84 sites, one history each | 130 rows, two per site |
| `wp_core_update: "up-to-date"` | the site is on 7.0.2 | nobody ever read the version |
| `terminus auth:whoami` exit 0 | authenticated | no session at all; CI never once logged in |
| the digest's `Scanned **3**` | three sites scanned | one; ssh ate the rest of the list |
| `cm-whitelabel` core `up-to-date` | patched | 6.9.4, below the wp2shell fix |
| severity `0 healthy` | the fleet is in crisis | one rule on a never-zero fact |
| `wp_version` absent in an old run | 48 sites changed version | the fact did not exist yet |
| the coverage table's `wp_checked` | 48 sites went dark | 48 sites became visible |
| `php_support()` with no date | PHP 7.4 is supported | a rule failing OPEN |
| 35 `SKIP` on the first render | nothing there to check | 32 sites nobody has ever scanned |

Every one was a confident-looking value standing in for an absence or a
misreading. **Only two were caught by code. The rest were caught by a person
looking at a rendered page or a raw number.** When adding a column, ask what it
shows when the answer is unknown, and whether a reader could take it to mean the
opposite.

---

## Read these, in this order

| file | what it holds |
|---|---|
| `docs/DATA-MODEL.md` | the inventory and ledger the dashboard reads. Start here |
| `docs/SEVERITY.md` | **how CRIT/WARN/OK are decided, and the `production` flag** |
| `docs/CI-LEDGER.md` | how CI writes to the ledger, and why it did not before |
| `docs/DASHBOARD-V2.md` | the dashboard, and why there are two renderers |
| `docs/SSH-KEY-SETUP.md` | full mode, now proven working |
| `docs/AUDIT-SHEET-ANALYSIS.md` | the manual workbook, per-column, and Nexcess |
| `docs/EMAIL-DNS.md` | the recovered Pass/Fail rule and three bugs |
| `docs/DESIGN-REVISIT.md` | the ledger-not-scanner reframe |
| `docs/GIT-SETUP.md`, `docs/RUNBOOK.md`, `docs/SECRETS.md` | mechanics |

---

## Open, undecided

- **Which GitHub account or org long term.** `dougkasperek` is personal.
- **Whether the two renderers ever merge.** Only if the live view learns to read
  the ledger mid-scan. Not needed yet.
- ~~**Version-stamping the tool per run.**~~ **Solved differently, 2026-08-19.**
  It happened exactly as predicted -- the first full-mode run reported 325
  changes, 274 of which were facts becoming visible for the first time. Rather
  than stamp a version, severity is now re-derived for BOTH sides of a diff
  with the current rules, and a new `COVERAGE` change class collapses
  unknown-boundary crossings to one line per fact. The same run now reports 11.
- **Whether the scanner should score at all.** It still does, with its own
  inline rules, so its digest and its CI exit code disagree with the dashboard.
  Fixing it means a CLI mode on `severity.py` and a change to what fails a
  build. See the end of `docs/SEVERITY.md`.
