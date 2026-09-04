# Fleet automation: handoff for the next session

**Rewritten 2026-08-19, PICK UP HERE refreshed 2026-09-03.** Chats share this folder and project memory,
never each other's conversation history, so everything needed to resume is
written down.

**This supersedes `DESIGN-BRIEF.md` and every earlier version of itself.**

---

## PICK UP HERE: 2026-09-03. The fleet was fine, the alert is live, B9 is closed.

**The cold scan the previous handoff asked for was run on 2026-09-02 and
measured 47.** Run `health-2026-09-02_1147`: 47 of 49 sites with WordPress
checked, no preflight failures, `knudsen.com` and `galbanicheese.com` both
clean. A run at 10:15 the same morning measured 46 with `galbanicheese.com`
timing out once. So the evening of 2026-09-01 was self-inflicted: five scans
in five hours, two of them at once. Throttling is still the leading guess and
still unconfirmed. One scan at a time holds at 46 or 47.

**The 2026-09-02 session did not refresh this file.** What follows was read
back from the commits and the ledger on 2026-09-03, not from a record the
session left.

### What the 2026-09-02 session built

- **A Teams message when a NEW finding at CVSS 9.0 or above reaches a site**,
  sent after a successful publish. `scripts/fleet-alert.py`, a step in
  `_publish-dashboard.yml`, `test/test-fleet-alert.py`. The design and the
  rest of the plan are B12 in `docs/DO-THIS-NEXT.md`.
- It had never run in CI when this section was first written on 2026-09-03:
  the last publish of 2026-09-02 ran from `734b3f1`, before the alert commit
  `dc9cf32`, and `TEAMS_WEBHOOK_URL` was not set. Both changed the same day;
  see "Done on 2026-09-03" below.
- The env preflight got the same ceiling as the other Pantheon calls, and its
  duration is measured rather than guessed.
- The vulnerability page carries its own dates: when the match ran and when
  each host's plugin versions were read. Its "new since the last check" count
  now counts all new findings, not only new criticals.

### State as of 2026-09-03

`fleet.thudstaff.com` is current. Checked by fetching `fleet/latest.json` out
of R2 and comparing it with a fresh render from the ledger: every headline
count is identical.

- **5 CRIT, 55 WARN, 19 OK**, six sites excluded by ruling.
- **378 vulnerability findings over 65 sites**, 15 with no fix, 5 criticals
  unpatched (the oldest for 106 days), 8 sites not checked and named on the
  page. Match `vuln-intel-2026-09-02_1543`.
- **That total fell from 459 to 378 in one afternoon, and the drop is real.**
  Eight Nexcess sites had plugins updated between the 14:04 and 15:43 matches:
  92 version changes across those sites in the Nexcess scan of 15:35, for
  example `eamusicfest.com` 37 findings to 9 and `hitsfoundation.org` 28 to 2.
  Nothing in this repo records who did the updating. Ask Zach.
- Last runs per source: Pantheon health 2026-09-02_1147, Nexcess health
  2026-09-02_1535, vuln-intel 2026-09-02_1543, email 2026-09-03_2132, consent
  08-28, consent-gating 08-28.

### Done on 2026-09-03

- **The Teams webhook is set and the alert step has run three times.** Doug
  set `TEAMS_WEBHOOK_URL`; an email DNS dispatch (run 33807790859) published
  and the step ran with the secret present, printed `no new critical findings
  in vuln-intel-2026-09-02_1543 (compared against vuln-intel-2026-09-02_1404)`
  and sent nothing. No missing-webhook warning, no annotation. The two B9
  dispatches below ran it twice more with the same result. It will send its
  first message when a run finds something new at CVSS 9.0 or above, and
  nothing has yet.
- **The alert reaches the channel, proven at 22:44 UTC.** `fleet-alert.py
  --test` plus `fleet-alert-test.yml`, dispatch only, send one grey message
  titled "TEST ALERT, not a real finding" about `example.invalid`. It took
  four tries and each failure was worth having: the first secret's URL had
  lost its query string in the paste (the endpoint said `400
  ApiVersionInvalid`, which names nothing); the webhook is a Teams Workflows
  one, so the payload became an Adaptive Card; and my own shell one-liner then
  read a key the new payload did not have. Doug recreated the webhook through
  the channel's Workflows menu and set the secret from a file. The message was
  read back out of the channel through the Teams connector, posted by
  "Workflows" at 22:44:03. Both send steps now name a truncated URL before
  posting. B12 has the detail.
- **A real vulnerability match ran against changed data and stayed silent,
  correctly.** Run `vuln-intel-2026-09-03_2155` found 51 new findings since
  the previous match, all one advisory: Divi up to 4.27.6, stored XSS needing a
  Contributor login, CVSS 6.4, on 51 sites. Below 9.0, so the step printed
  "no new critical findings" and sent nothing. Better evidence than the runs
  where nothing had changed.
- **B9 is closed.** Every scanner's scan job carries a concurrency group of
  its own: `pantheon-terminus`, `wordfence-feed`, `consent-sweep` (shared by
  the cold sweep and the gating job, so a second consent run waits for both),
  `email-dns-lookup`, `nexcess-api`; the SSH scan already had `nexcess-ssh`.
  Queue rather than refuse, per workflow rather than fleet-wide, never the
  ledger lock. `test/test-workflows.py` asserts all of it and four ways of
  breaking it were verified to fail. Commit `b09d98c`, the reasoning in B9 of
  `docs/DO-THIS-NEXT.md`.
- **Observed, on two email dispatches seven seconds apart**: the second scan
  job started eight seconds after the first finished, against a four-second
  pickup for the first. A 15-second scan shows the ordering and nothing
  longer. The Pantheon case, a 45-minute wait, has not been watched.
- **Two runs in one minute share a run id.** Both email runs stamped
  `2026-09-03_2132`. Ingest is idempotent on run id and the second wrote
  nothing: `ingested 0 run(s); 1 run(s) already present`, 78 rows, not 156.
  Harmless here; a long scan stamps after its wait, so it gets its own minute.
- This section was rewritten from the commits and the ledger, because the
  2026-09-02 session did not refresh it. Commit `4a066a1`.

### The full run of 2026-09-03 evening, and what it showed

Doug asked for a full run to see whether an alert would be sent. Pantheon
full scan `health-2026-09-03_2159`, then the vulnerability match twice,
`vuln-intel-2026-09-03_2155` before the scan landed and `_2250` after.

- **No alert was sent, and both silences were correct.** The first match
  found 51 new findings, all one medium Divi advisory. The second found
  nothing new. Neither had anything at 9.0 or above that the previous run
  lacked.
- **The scan measured 47 of 49, no preflight failures**, the same as the
  healthy baseline. Preflight median 9 seconds, slowest 14.
- **Someone patched 20 Pantheon sites today**: 231 plugin version changes,
  pending plugin updates down from 396 to 218, WordPress core updated on ten
  sites. Four sites lost their critical vulnerability: `ciminelli.com`,
  `gmroot.com`, `morrison-chs.com`, `pfannenbergusa.com`. Health went from
  5 CRIT / 55 WARN / 19 OK to **1 CRIT / 45 WARN / 33 OK**; the one CRIT left
  is `runtalnorthamerica.com`. Findings went 429 to 371 across the two matches,
  and sites carrying a 9.0 or above went 4 to 0 (none). Same as the Nexcess
  sites yesterday: nothing in this repo records who did it. Ask Zach.
- **The Pantheon workflow's publish job could not have alerted.** It was an
  inline copy of the shared publish workflow from before that file existed,
  and the alert step never reached it. Found by reading the run's job steps.
  Folded into the shared workflow the same evening; `test-workflows.py` now
  refuses an inline publish job in any scanner. **Not yet observed**: the next
  Pantheon run is the first through the shared publish, and its job list
  should show "Tell someone if a new critical appeared".
- The commit that folded it, `3da32ed`, says in its message that this
  section was written. It was not: the script writing it crashed on a site
  whose worst score reads `unknown`, after the commit had been staged. This
  commit is the correction.

### The secrets-management concept, for Nick (2026-09-03 evening)

Brian's to-do from the 2026-09-01 regroup: a concept for secrets management,
Nick presenting the week of 2026-09-08. **Doug's call: Nick builds it; the
repo gives him guidance, not the answer.** `docs/SECRETS-CONCEPT.md` is that
guidance: Brian's ask in his words, six questions in the order that each
changes the next, two ten-minute tests on one Pantheon site, the premium
plugin list with site counts from the fleet scan, what Doug covers (the
Keeper quote and the CI half in `docs/SECRETS.md`), and the traps. A first
version of that file held a finished concept with sourced findings; it was
replaced the same evening at Doug's instruction and the draft is outside the
repo, Doug's to share after Nick has formed his own view.

### Decisions that are Doug's, in order

1. ~~**The git history scrub, before the transfer.**~~ **DECIDED
   2026-09-03: leave the history as it is.** Measured first: no rewrite had
   run, the six-name access map was never committed, and what history holds
   is the old DASHBOARD.md Access section, 1,813 lines of old handoff naming
   other Workers' bindings and secret names, the exposure-map entries, and
   one colleague's email. No credential anywhere. `docs/HANDOVER.md`
   section 3 has the measurement and the decision. Do not reopen without
   new information.

2. **Two schedules are ON since 2026-09-03 evening, the first in this repo.**
   The vulnerability probe daily at 11:37 UTC (07:37 ET during EDT), because
   the alert is only as timely as the match that feeds it; and the worker
   exposure check every six hours at 13 past (00:13, 06:13, 12:13, 18:13 UTC),
   because its whole value is noticing quickly. **Neither has been observed
   yet.** Read the first scheduled probe on 2026-09-04: it must reach the
   ledger AND publish AND run the alert step, which is exactly what a
   scheduled run silently fails to do when a job is gated on a bare
   `inputs.x` (every input is empty on a schedule). Every input the probe
   reads now goes through a default and `test-workflows.py` refuses a bare
   one in any scheduled workflow, verified to fail three ways. GitHub can
   delay a scheduled run by minutes at busy times; a run at 11:50 is not a
   fault. The Pantheon, email, consent and Nexcess schedules stay commented
   out until a person has watched these two for a week.

3. **Which Teams channel.** The webhook points somewhere; B12 asks whether
   routine publishes and criticals should share it. A channel that gets both
   will be muted.

### Not done, and worth knowing

- The Pantheon queue has not been watched. The first time two Pantheon
  dispatches overlap, whether by hand or by a schedule, read the second run's
  scan job and confirm it waited. It costs nothing to check and it is the
  case B9 was opened on.
- Three email DNS runs landed today, all 70 of 78. Two were for B9. The
  ledger diff between them is empty, as expected.

---

## Previously: 2026-09-01, late. Start with one cold scan.

**Do this first, before anything else.** One Pantheon health scan, from cold,
with nothing else running. It answers a question tonight could not:

```bash
cd ~/dev/cm-automation
gh run list --limit 5 --json status --jq '[.[] | select(.status != "completed")] | length'   # must be 0
gh workflow run pantheon-fleet-healthcheck.yml -f run_mode=full -f target_env=live \
  -f fail_on_crit=false -f persist_ledger=true -f publish_dashboard=true
```

**Check the count against 47.** That is what a healthy run measured at 17:28 on
2026-09-01. If it comes back near 47 the fleet is fine and the evening was
self-inflicted. If it fails again, the run will now SAY WHY, which it could not
do this morning.

**Do not pass `allow_coverage_drop`.** Nothing is expected to drop. If the guard
refuses, that is the finding.

### What happened on 2026-09-01, in order

Five full Pantheon scans ran in five hours and the measured count fell every
time: 47, then 46, then 45 and 46 from two that ran at once, then **26 of 49
with 22 sites failing their environment preflight**. An hour of doing nothing
took the next run back to **46**.

**That fits throttling and nothing has confirmed it.** Treat it as the leading
guess and not as the answer. What is measured: `terminus env:list` did not
return within 20 seconds and terminus printed nothing at all, which rules out
an auth failure and rules out an active refusal, both of which write to stderr.

Two of those scans ran concurrently because the workflow was dispatched twice,
two minutes apart, once by Doug and once by Claude. Both started on the same
site 48 seconds apart and `lasershows.com` measured cleanly in one and ERRORed
in the other. That is B9, and it is worth settling before the schedules are
turned on, because a schedule firing during a manual run produces exactly it.

### What was fixed, and what it means for tomorrow

`run_with_timeout` was sending the child's stderr to `/dev/null`, so a timeout,
a rate-limited reply, an auth failure and a malformed response all produced one
empty string and one message. It keeps both stderr and the exit status now, and
the scanner reports which of the two it was.

`preflight_why` and `preflight_stderr` are in the health fact family, so the
reason reaches the ledger rather than only a CI log. They read UNKNOWN on a
healthy row and any move across that boundary classifies as COVERAGE, so
nothing new shows up in the change feed.

**Practical effect: if tomorrow's scan fails, do not guess.** Read the reason:

```bash
python3 -c "
import json
rows=[json.loads(l) for l in open('history/observations.jsonl')]
run=max(r['run_id'] for r in rows if r.get('source')=='health' and not r['run_id'].startswith('health-nexcess'))
for r in rows:
    if r['run_id']==run and r.get('preflight_why') not in (None,'unknown'):
        print(r['site_id'], '->', r['preflight_why'], '|', r.get('preflight_stderr'))
"
```

### State as of tonight

Everything is published and current. `fleet.thudstaff.com` carries health run
`health-2026-09-01_2350` and vulnerability run `vuln-intel-2026-09-02_0056`,
verified by reading the objects back out of R2 rather than from a log.

- **9 CRIT, 55 WARN, 15 OK**, six sites excluded by ruling.
- **453 vulnerability findings over 64 sites**, 15 with no fix, 9 sites not
  checked and named on the page.
- `knudsen.com` timed out tonight and is unmeasured. One site, one run, not a
  pattern yet. Watch whether it recurs.
- The coverage guard refused three publishes today and every refusal was right.
  The one that went through was the only drop that had an explanation.

### Also done on 2026-09-01

- **Every em dash is out of the dashboard copy and the repo**, along with the
  aphoristic sentence shapes. Doug asked for this twice. The exceptions are
  `docs/correspondence/` (verbatim vendor messages, never edited), the frozen
  Wordfence fixture, `_scratch/`, and three comments that quote a string which
  used to exist.
- **Zach patched two sites** and it is visible: `crackerbarrelcheese.com` and
  `ciminelliflorida.com` closed eight advisories between them. The fleet total
  rose anyway, from 391 to 455, and all 143 added findings come from ten
  advisories Wordfence published since 31 August. The fleet improved; the world
  published more.
- **B8, B9, B10 and B11 were added** to `docs/DO-THIS-NEXT.md`. B11 is the
  OneTrust API question and its first open item gates the rest: does the tier
  clevermethod is on include API access at all. That is Nick's answer.
- **`docs/HANDOVER.md`** covers moving the repo and the dashboard to the
  clevermethod org. The GitHub transfer is ready; Cloudflare needs a Super
  Administrator on the clevermethod, Inc. account to grant three roles first.

### Two things I would not let slide

**The git history still holds everything scrubbed from the working tree today**,
including the other Workers, the access map and six colleagues' names. A
stranger cloning the repo sees a clean tree; `git log -p` does not. That is a
decision for before the transfer, not after.

**A dispatch is not gated on whether something is already running.** Check
first, every time. See B9.

---

## Previously: 2026-08-29, evening: two more cuts, and a correction

### The correction first

**The block below this one says `origin/main` is `29a650f` and four commits are
unpushed. That was wrong when it was written.** Measured this session:

    $ git ls-remote origin main
    be0b75c30ad8cff2e033f45db16663c7f900dae7	refs/heads/main

`git rev-list --count be0b75c..<remote>` is 0. Nothing was unpushed. The claim
was written by the session that made those commits and read forward into the
next one, which is the same shape as every row in CLAUDE.md's bug table. It has
a row of its own now.

**`git status` through the device bridge leaves a `.git/index.lock` that the
bridge cannot delete.** One was left this session and moved to `_to_delete/`,
where an older one from a previous session was already sitting. See the
hard-boundaries section of CLAUDE.md; `_to_delete/` needs a person to empty it.

### State

`HEAD` and `origin/main` were `be0b75c` at the start of this session. **Four
commits on top, all pushed, and PUBLISHED 2026-08-29 evening Eastern.**
`origin/main` is `2153605`; tree clean.

**The live page at https://fleet.thudstaff.com is current for the first time
since the v3 UI work.** Before publishing, the dry-run render was checked
against the committed artifacts by sha256 and was **byte-identical, not merely
identical apart from the date stamp**:

    59e6d80ccc6a4e3a  reports/publish-preview/dashboard.html == fleet.html
    7462371bc8d1b0c5  reports/publish-preview/components.html == components.html

So what is live is what was reviewed. The publish itself is Doug's report plus
the script's own post-upload read-back, which compares byte counts and fails
the run if an object cannot be pulled back; **no sha256 comparison against R2
was made by this session.** If that matters later, the 2026-08-28 precedent is
`wrangler r2 object get --remote` on each of the four keys and `shasum -a 256`
on the pair. Rendering on a new day dirties `fleet.html`
and `components.html` by one line, the embedded `"generated"` date, and
nothing else; the fleet counts were byte-identical to the committed artifact.

### What came off

**The masthead's `p.thesis`.** `One row per site, one column per question.
Hatched is unmeasured. Schedule tab: the same evidence arranged by decision.`
Each clause is stated lower down, beside the thing it describes and in a form
that follows the data: the tools row's live `85 rows · 16 questions`, the
key's `not measured: an absence, never a pass`, and the Schedule panel's
`This tab arranges the backlog by the decision instead of the site`. All three
were checked on the rendered page, not in the source, before the cut.

**The `.top .thesis` CSS rule stays.** The consent page emits its own
`p.thesis` and inlines `page.css`. The rule is commented as consent-only now.

**The Schedule panel's fifth paragraph, from three clauses to one.** It read
"Nothing here is an emergency. The 4 sites that need a person today, the
rulings and the coverage gaps stay in the matrix; this tab is the maintenance
calendar." Two clauses restated paragraph 1. **The third was false**, and that
was found by reading the rendered Schedule column for site ids rather than by
reading the copy: three of the four needs-a-person sites are on that tab,
`iroquoisfence.com` as a backlog decision of its own, `hoffmanscheese` and
`runtalnorthamerica.com` inside batched components' install lists. Paragraph 1
of the same panel said the first of those explicitly. It now reads:

> Rulings and coverage gaps are not scheduled here; they stay in the matrix.

Rulings and coverage gaps really are absent from the tab: the six decisions
are all drift and maintenance. Naming an absence is the one thing these passes
do not cut.

### One bug fixed on the way, found by looking at the page

Paragraph 1 printed `the other 1 (iroquoisfence.com) need a person for
something else first and are listed here too`. The plural was hardcoded, and
the count has been 1 every day the page has existed, so that sentence was
ungrammatical on every render anyone has seen. The inline version also
recomputed its filter three times in one sentence, and at a count of 0 would
have rendered an empty parenthesis: a branch that had never run.

`backlogScheduled` and `backlogElsewhere` are named once in `AGG` now, and the
paragraph is built by `schedIntro()`, which has the zero branch and agrees its
verbs with the count it just printed.

### Measurement

| | before | after |
|---|---|---|
| first data row | 730px | **707px** |
| page height | 4400px | 4377px |
| chrome words | 320 | **301** |

**Then the coverage line put 25px and 38 words back**. See the section below.
The day ended at **732px / 339 words** against **730px / 320** at its start.

**These are NOT comparable to the 697px in the block below.** That figure was
measured on Doug's mac; these were measured in headless Chromium 141 on Linux,
which has different fonts and wraps differently. What is comparable is the
delta: **-23px and -19 words**, both measured this session on the same page in
the same browser.

`_scratch/measure-page.mjs` is new and committed, because every earlier session
measured this by hand and quoted a number the next one could not reproduce. It
states its own definitions in its header. Run it where you want the number:

```bash
./scripts/render-dashboard.py --out fleet.html --components-out components.html
node _scratch/measure-page.mjs fleet.html
```

### Tests

`test-page.mjs` is **63 → 68** in this pass, and **71** after the
coverage-line pass below. Three new checks here, **each verified to fail
against the previous page** before it was fixed:

- the masthead carries no prose paragraph
- the Schedule panel never says the needs-a-person sites are only in the matrix
- the panel's backlog split reconciles, adds up, and agrees its verbs with its
  own count

A fourth check was written and **removed for being wrong**: it demanded the
panel name every needs-a-person site the Schedule column mentions, which fails
on a correct page, because a site inside a component's install list is not a
decision about that site. The reason is written above the surviving checks so
nobody adds it back.

`test-page.py` went red once on the way and it was a real catch: its
typed-count rule reads comments too, so a comment saying "the four sites"
tripped it. Reworded, not suppressed.

**13 of 17 suites were run this session, all green.** score-scan 27,
consent-rulings 17, nexcess-ssh 43, worker-exposure 48, workflows 67,
access-policies 46, ledger 319, severity 166, page.py 35, build-inventory 6,
nexcess 96, consent 126, and page.mjs 68 (71 after the pass below; ledger,
severity, page.py, score-scan and consent-rulings were re-run after it).

**The other four could not run through the device bridge and Doug ran them on
the mac the same evening. All green:** email-dns 65, wp-calls 48,
gating-leak 14, gating-window 20: the counts CLAUDE.md's testing table already
carried, so none had drifted.

```bash
cd ~/dev/cm-automation
python3 test/test-email-dns.py      # needs dnspython
python3 test/test-wp-calls.py       # exceeds the device bridge's 45s cap
node test/test-gating-leak.mjs      # needs Chromium
node test/test-gating-window.mjs    # needs Chromium
```

**17 of 17 suites pass as of 2026-08-29 evening.** The bridge VM cannot install
a browser: `npx playwright install` is refused with `403 Connection blocked by
network allowlist`, so a session working through the bridge runs 13 and has to
hand these four to a person. That split is in CLAUDE.md's testing section.

### Later the same evening: the health-coverage count is on the page

**The scoreboard was not on the dashboard.** CLAUDE.md calls the
health-coverage count "the number printed under the fleet-health card" and
"what progress looks like". There is no fleet-health card on the v3 page. Its
only fleet-level appearance was inside the GREEN banner sentence, and this
fleet has never been green, so the project's own measure of progress has been
invisible since the redesign. Found by searching the rendered text of both
tabs, not the source. Per site it was in the drawer the whole time
(`coverage_partial`, "Seen only by the consent sweep"); nothing totalled it.

It now renders in **every** state, in the banner block, as:

> **11** with no health evidence: a scan reached the site, but no backup age
> and no plugin or theme count. Cuts across the lanes rather than being one:
> 1 in Needs a person, 10 in Not established.

The split is computed, not asserted, and it is there to stop the count being
read as the `Not established` chip beside it. Measured this session: in the red
state both are 11 over **different sets**: the lane holds
`app.eastauroracc.com` and not `elderwoodipa.com`, the count the reverse. In
the green state they are **11 and 12**.

**The green banner sentence now carries one figure, not two:**

> 42 sites carry a maintenance backlog; none of it needs anyone today.

The coverage clause moved to its own line rather than being deleted. The
not-an-all-clear guarantee is unchanged in substance and is now pinned by two
checks instead of one: the sentence must name the backlog, and the block must
carry the coverage count.

**The line is not `.lanes-aside` and not inside `.lanes`, and that took two
tries.** `test-page.mjs` sums `.gc-hd .n, .lanes-aside b` against the fleet
size; a number that cuts across the lanes does not belong in that sum. Both
wrong versions were caught by the existing suite, not by reading the diff. It
has `.cov-line` of its own now, with the reason in both the JS and the CSS.

**It costs height and that is the trade.** 707px → **732px** before the first
data row, 301 → **339** chrome words, same script and browser as the earlier
measurement. That is 2px above where the day started, and 38 words spent on a
number that was previously on no page at all. If you want it shorter, the
sentence that can go is the definition ("a scan reached the site, but no backup
age and no plugin or theme count"), but that makes it a bare number, which is
what the four cards existed to stop.

`test-page.mjs` is **68 → 71**. Three more checks, each verified to fail
against the page as it stood before this pass.

### Still on the table

- **The Evidence tab has no sub-label while Schedule has one.** Unchanged and
  still deliberate.
- **`render()` and `--legacy-out`.** Examined this session, not touched, and
  **it is not the small delete this file has been calling it.** `render()` is
  ~1,460 lines (3,364–2,827 in `render-dashboard.py`), with ten `RD.render(...)`
  assertion sites in `test-ledger.py` and one in `test-page.py`. Three of the
  strings those assertions pin appear **only** in the legacy page and nowhere
  in `fleet.html`:

      no site is UNKNOWN on health
      had no recorded From: address at all
      all agreeing with what was recorded

  The first is the copy behind the `UNKNOWN: 0` row in CLAUDE.md's bug table.
  Deleting `render()` deletes that coverage unless those assertions are
  re-pointed at the new page, or the copy is consciously dropped from the
  product. That is a decision about what the new page should say, not a
  cleanup. Give it its own session.
- ~~**The green-state residual.**~~ **DONE 2026-08-29, evening. See the
  coverage-line section above.** Measuring it first changed the fix: the
  backlog pair agreed on the day's data (42 and 42, by coincidence, still from
  different sources) and the coverage pair was the one that visibly disagreed
  (11 against 12 in green; both 11 in red over different sets). And the count
  turned out to be on no page in any state, which was the bigger problem.
- **"The page renders the last GOOD run per source"** (DECIDED 2026-08-28).
  Still the next substantial piece. Untouched.

### To resume, cold

```bash
cd ~/dev/cm-automation
./scripts/render-dashboard.py --out fleet.html --components-out components.html
node test/test-page.mjs
for t in test/test-*.py; do echo "== $t"; python3 "$t"; done
open fleet.html
```

**Render BEFORE testing, every time.** `test-page.mjs` renders nothing.

---

## Previously: 2026-08-29, morning: three passes on the page (superseded above)

**Three commits, none pushed.** `HEAD` is `cc28ac7`; `origin/main` is still on
`29a650f`, checked with `git ls-remote` rather than inferred. Working tree
clean. **Nothing has been published**: `publish-dashboard.sh` has not run.

    cc28ac7  Four cards over the seven lanes, minus two false groupings
    a646c9d  Merge the banner and the lane strip into one block
    f336122  Subtract six things from the fleet page

The session ran in three passes, each asked for separately. Nothing below is
waiting on code; all 17 suites pass and every page state was rendered and
looked at.

### The measurement, all three states, one viewport

Measured at 1280×900 this session, not carried over from an earlier one. The
figure to quote is **759px → 697px** of header before the first data row.

| state | first data row | page | chrome words |
|---|---|---|---|
| before the session | 759px | 4583px | 331 |
| after the six cuts | 654px | 4334px | 250 |
| after the merge | 661px | 4341px | 237 |
| **after the four cards** | **697px** | **4376px** | **285** |

Superseded by the evening block at the top of this file, which measures the
same page with a committed script rather than by hand.

**The last two rows go the wrong way and that is deliberate.** The merge cost
7px in borders and the cards cost 36px in definitions, including two the
concept had dropped. Do not "reclaim" that by shortening a card gloss; those
words are the fix for a bug in the bug table. An earlier version of this
measurement claimed the merge made things WORSE, because it counted the lane
strip twice once it moved inside the banner.

### Pass one: what came off

| cut | why it was safe |
|---|---|
| the banner's `(Pantheon health 48/52, Nexcess health 21/22, …)` | the same `sweepLine()` runs render in the strip 40px above it, with timestamps and a stale marker the banner has no room for |
| the audit-workbook checkbox and its four columns, and the Workbook paragraph in the key | the drawer shows SIX claims per site with a `Confirmed by` cell reading `nobody here yet (workbook import 2026-08-18)`: the thing the paragraph said in prose, said beside the claim. The totals section below the matrix names the sites where a claim has no matching plugin |
| two of the three `85 sites · 16 questions` | the survivor is the tools-row count, the only one that follows the filter |
| "Rows are grouped by what happens next…" | it described a layout you can see: the group headers are in the table, the AXES group is labelled |
| the lane gloss inside the matrix group headers | the same words render on the tiles, ~600px up. The tiles keep them: `test-page.mjs` pins them rendered and unfolded, and the 2026-08-28 comment above them now says so |
| the census bar row, with the footer clause that was its only legend | computed over all 85 sites, never followed the filter, explained by a `title=` tooltip and one sentence 3,800px below it. Its column denominator and its 85 cells all stay |

Nothing that names an absence was touched: the hatch, `n/a`, `no API`,
`not in sweep`, every column denominator, the banner predicate, the
`1 excluded by ruling (cm-whitelabel)` naming, and the drawer's "Zero rows is
not 'nothing pending'".

### Pass one: two things went wrong doing it, both in the bug table now

1. **`test-page.mjs` renders nothing. It opens `./fleet.html`, a committed
   artifact.** Two runs reported "47 passed" against a page rendered before the
   edits, in the same voice as a real pass. CI had the same hole: its step had
   no render before it, so any change to `page.js` without a re-render passed
   green. `offline-tests.yml` renders first now. Locally the sequence is
   `./scripts/render-dashboard.py --out fleet.html && node test/test-page.mjs`.
2. **The first version of the new banner check was vacuous.** It trimmed each
   sweep line at the first digit, producing `Pantheon health Aug`: a string
   that appears nowhere, so it passed against a banner with the duplication
   put back. Found by running the negative control, not by reading it.

**Every new check was verified to fail** by re-adding the thing it forbids and
watching it go red. `test-page.mjs` is 47 → 55.

### Pass two: the banner and the lane strip merged into one block

Doug, looking at the two stacked boxes: *"can we combine these?"* Yes, and it
turned out to be a correctness fix, not a layout one. **The banner's prose was
printing numbers that were not the tiles beneath it**: "a backlog (42 sites)"
over a `Needs scheduling` tile of 41, and "unmeasured (11 sites)" over a
`Not established` tile of 11, the same figure over a different set of sites.
Both pairs are in the bug table now.

The red state names who needs a person and stops; the lane counts say the rest.
The green state keeps its equivalent sentence, because there it is the only
thing stopping the banner reading as an all-clear, and `test-page.mjs` pins its
shape.

**It cost 7px, it did not save any.** Measured at 1280×900 across three
renders: 759px of header before the first data row at the start of the session,
654px after the six cuts, 661px after the merge. Chrome prose went 331 → 250 →
237 words. The merge buys coherence and removes two misleading numbers; it does
not buy height, and the first version of this measurement claimed it made
things WORSE because it double-counted the lane strip now that it sits inside
the banner.

**One residual, seen in the green render and left alone.** The green sentence's
backlog count comes from `backlogOnly` and the tile below it from the
`schedule` lane, so in that state they can differ: the synthetic green render
showed 42 in the sentence and 44 on the tile. Fixing it means changing wording
that `test-page.mjs` pins as the "not an all-clear" guarantee, which is not a
thing to do casually. Decide it deliberately.

**Still true after pass three**, now against the `Needs scheduling` chip inside
the Planning card rather than a tile. It is the last surviving instance of the
thing pass two existed to remove: a prose number beside a lane count from a
different source, and the only reason it survived is that the guard pins the
sentence. **It appears in the GREEN state only**, which this fleet has never
been in, so nobody has seen it on a real page.

### Pass three: the seven tiles became four cards

Doug's concept, drawn as a mockup: group the lanes into cards with the counts
as chips beneath. Built. **Two of the four groups as drawn were false**, both
now in CLAUDE.md's bug table, both caught by scoring the sites rather than
reading the label:

- `Not scored` held `4 Not measurable` and `1 Excluded by ruling`. **All five
  are scored.** SKIP and FROZEN are severity statuses, and `excluded` means
  scored and not counted: `cm-whitelabel` was **CRIT with three findings** the
  day a card said the tool could produce no result for it. They are a quiet
  line under the cards now, worded as what they are.
- `Planning / decision pending` held `11 Not established` beside the backlog
  and the rulings, under "work must be scheduled, defined, or ruled on". On
  those sites nothing is known, so there is no work to schedule. **The absence
  folded into a backlog**, in the page's own headline block. It has its own
  card and is never merged upward.

Two more, recorded in `docs/DASHBOARD-V3.md` as copy rules rather than as bugs:
the predicate had lost `(health critical, a consent banner that leaks, or no
SPF)`, which is the only place the page says what puts a site in that lane; and
the same set was called three different names in one block. The build uses
"Needs a person" everywhere, matching the predicate and the matrix headers.

**The cards cost height, and the definitions are why.** 697px before the first
data row, against 654px for the seven tiles and 759px at the start of the
session. The cards carry fuller definitions than the tiles did, including the
two the concept dropped, so they are wordier on purpose: 285 chrome words
against 250. Net against where the session started, still 62px and 46 words
better.

`test-page.mjs` was rewritten around this rather than patched. The old lane
block counted seven `.lanes li` and read a `.lane-sub` out of each, which
describes the markup of 2026-08-28 and broke entirely on a change that kept the
guarantee intact. It now asserts the property: **every lane word this page
invents is displayed, and a visible definition is displayed with it**, wherever
that lives. Plus three new guards, each verified to fail: a card holding
several lanes must define each in its gloss, "Not established" must not be
grouped with scheduling or rulings, and nothing may call a scored site unscored.

### Still on the table, not done

- **The thesis line.** `One row per site, one column per question. Hatched is
  unmeasured. Schedule tab: the same evidence arranged by decision.` All three
  clauses are stated better lower down: the tools-row count, the key's
  `not measured: an absence, never a pass`, and the Schedule tab's own
  sub-label. Not cut because Doug did not pick it; it is the obvious next one.
- **The Evidence tab now has no sub-label while Schedule has one.** They are
  the same height and it renders fine, but it is lopsided. Restoring a label
  means re-adding a third copy of the count, so the alternative is to cut
  Schedule's, which would remove the only preview of what is behind that tab.
  Left alone deliberately.
- **`render()` and `--legacy-out`.** Handoff candidate 3, untouched. CLAUDE.md
  says retire after one published cycle; that cycle passed days ago, and
  `test-ledger.py` still carries `RD.render(...)` assertions for it.
- **The Schedule side panel's five paragraphs.** Paragraph 5 ("Nothing here is
  an emergency… this tab is the maintenance calendar") restates paragraph 1 and
  the thesis line. Candidate 4 territory, not examined closely this session.

### Before publishing

`fleet.html` and `components.html` in the repo root are re-rendered and
committed with the change. **Nothing has been published**; `publish-dashboard.sh`
has not run, and pushing is a human action.

### To resume, cold

```bash
./scripts/render-dashboard.py --out fleet.html --components-out components.html
```

**Render BEFORE testing, every time.** `test-page.mjs` renders nothing. It
opens `./fleet.html`, a committed artifact, so running it on a page.js edit
without this step tests the last commit's page and reports a pass. It cost two
false "47 passed" this session and CI had the same hole.

```bash
node test/test-page.mjs
```

Then the offline suites, all of which run in CI on every push:

```bash
for t in test/test-*.py; do echo "== $t"; python3 "$t"; done
```

To look at the page rather than the HTML, which is how most of the bug table
was found, and is step 2 of the definition of done:

```bash
open fleet.html
```

---

## Previously: 2026-08-28, afternoon: the v3 re-run is DONE, ingested and published

**Nothing in this repo is waiting on code right now.** State verified this
afternoon rather than read off this file, which is the point of the paragraph
below:

- Gating v3 ran twice this morning: `2026-08-28_1212` (concurrency 3) and
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
`collect` at `gcs=G100`: the cookieless consent-mode ping, which is the
correct denied behaviour and is exactly what Nick said should be there.

Nine inconclusive, two causes, both diagnosed:
- **4 have no clickable Reject control** (3 known, plus `hoosierfeeder.com`,
  new to the roster. It loaded for the first time in the 08-28 cold sweep
  after HTTP 403 in every earlier run).
- **5 draw a Cloudflare "Just a moment" challenge on the SECOND navigation.**
  Measured on `breakstones.com` with headers and body read. v2's reload drew
  the identical 403, so it is not the new window, and cooldown at concurrency 1
  changed nothing.

**Read the numbers off the CLICK pass, not the synthetic one.** The three pass
labels are `cold load, no consent state`, `real click on Reject All`, and
`OneTrust set to all-denied`. Only the middle one is the v3 measurement. A
substring match on "denied" silently selects the synthetic pass and gives 19
G100 sites instead of 14: done accidentally this afternoon, caught by the
count disagreeing with the commit message.

### Open, and NOT blocked on anyone

**`interstatewaste.com`'s two passes disagree, and the disagreement is
EXPLAINED. It is not a defect.** I wrote it up as a test defect first and that
was wrong; the correction is here rather than removed because the reasoning is
the useful part.

In run 1322 the synthetic all-denied pass records `gcs=G111`: consent GRANTED
with DoubleClick and GA4 firing, while the real click pass on the same site
in the same run records the correct `G100`. The rule in this file says two
passes disagreeing about one site is a defect in the test. It is the right
rule and it is what caught the Clarity finding. It does not apply here:

- **The denial survived.** Measured on all 27 sites: every non-necessary group
  came back `:0` in `optanon_groups_after_load` on the denied pass. Zero sites
  had a group overwritten to granted. So OneTrust STORED the denial on
  `interstatewaste` and Google was still told granted.
- That is the mechanism `test-gating.mjs` already documents fifteen lines
  above the pass it runs: **a cookie present at load never UPDATES**, so a
  consent signal pushed on OneTrust's update event never fires. On an opt-out
  site the Google default is granted, so Google stays at G111. A real click
  produces the update, and G100 appears, which is exactly what the click pass
  measures.
- The click pass is definitive, the verdict is taken from it, the site reads
  GATED, and **that is correct**.

Worth knowing when reading the JSON by hand: the first pass at this by eye got
it wrong, because `C0001` (or group `1`) is Strictly Necessary and is ALWAYS
`:1`. A predicate that asks "did any group come back granted" flags all 27
sites unless it excludes the necessary group.

**The real gap is smaller and is mine to fix.** `optanon_groups_after_load` is
captured on all three passes and read on ONE: the cold pass, as
`consent_groups_default`. Nothing reads it on the DENIED pass, which is the
pass it was captured to guard. The code comment says the test "must say so
rather than reporting 'not gated'"; nothing says so. If OneTrust ever did
overwrite our denial, the pass would show tags firing and no field would
record that the pass had proved nothing. A captured fact with an unkept
promise, which is this repo's signature bug pointed at its own instrument.

**And a second unknown, found measuring the first.** Six sites answer with a
NUMERIC group schema (`1:1,2:0,4:0`: breakstones, crackerbarrel, knudsen,
kraftnaturalcheese, scottishcheddarcheese, valbresocheese) while the cookie we
write uses `C0001..C0005`. OneTrust replaced our cookie with its own. Whether
it honoured our denial or fell back to a denied DEFAULT cannot be told from
what is recorded, so on those six the synthetic pass may be measuring the
site's default rather than our denial. It does not affect any verdict: the
click pass does that, but it should be recorded as unknown rather than read
as a successful denial.

### DECIDED 2026-08-28: the page renders the last GOOD run per source

**Agreed by Doug. Not built.** This is the next substantial piece of work and
it wants its own session.

**The problem it solves, measured today rather than imagined.** A consent
coverage drop: 71 of 79 from a runner against 78 from a laptop, because 7
sites refuse GitHub IPs: blocked every publish from every workflow. Fresh
Pantheon, Nexcess and email data could not reach the page because ONE source
saw less from a different vantage point. There are only two answers today:
publish the worse data, or publish nothing.

**The third answer: render the last good run for that source, and say so.**
Coverage stops being a publish gate and becomes a per-source fact the page
states, which is what this repo already does with every other absence.

What it buys, in order of value:

1. **A failed scan stops being an emergency.** Today a degraded run blocks the
   whole page, so every failure is urgent and the only remedy is a full
   re-run, which cost two Nexcess SSH runs and two consent sweeps on
   2026-08-28 alone. A contained failure is fixed when someone gets to it.
2. **A stable reference for debugging.** The page's state currently depends on
   whether the newest run happened to be good. With a fallback, "what the page
   shows" versus "what the newest run said" is itself the diagnostic.
3. **`--allow-coverage-drop` can be retired.** It was added 2026-08-28 because
   there was no way to say "expected" from Actions. A bypass that gets used
   routinely stops being a decision.
4. **Consent decouples from the fleet scans** without splitting the ledger.
   It already has its own page at `/consent`; what does not exist is a page
   that can be current about five sources while one is degraded.

**TWO CONDITIONS, or it becomes the bug it is fixing.**

- **The fallback must be LOUD on the page**, not merely correct. A page
  rendering last-good data silently is precisely "behind the ledger and looks
  current", which is the worst shape in this repo and the thing
  `_publish-dashboard.yml` was created to stop.
- **It needs an age bound.** A source failing for a week must degrade to
  UNMEASURED, not keep showing week-old numbers as though they were today's.

**SCOPE BOUNDARY, agreed and worth holding.** This fixes the publish coupling
and the common case, including `app.eastauroracc.com`. That scan measured 1
of 22, so it IS a coverage drop and the fallback catches it.

It does **not** fix the general `unknown`-overwrite question. A scan that
reaches all 22 sites and records `unknown` for one fact is not a coverage drop,
so per-run fallback misses it. **Do not answer that by carrying individual
FACTS forward.** The ledger holds observations; carrying a fact forward because
the newest run did not measure it means inventing data and calling it a
measurement. A RUN either happened well or it did not, which is why per-run
fallback is honest and per-fact is not. Leave the per-fact question alone
unless it bites in practice.

**Every place that groups runs will need this**, and CLAUDE.md records that the
last cohort change had to be fixed in four places before the warning stopped
firing: `previous_run_of_same_source`, `coverage_regressions`, ingest's
`last_by_source`, and the renderer. Grep for all of them first.

### Next, in order

1. **NOTHING HAS BEEN SENT TO NICK.** Corrected 2026-08-28, late: this file
   said the correction was DONE, because earlier in the session Doug said he
   had told Nick he was right and it should have been recorded elsewhere. He
   later said plainly: "i did not send anything to nick yet. i dont have
   confidence in the tooling." The later statement is the record.

   **His reason is the important part and it is not unreasonable.** This
   instrument has been wrong twice about this exact question, and both times it
   produced the BEST possible answer -- v1 counted the old page's tail, v2
   erased the load it existed to measure. A third wrong answer sent to the same
   person would be the end of the tool's credibility with him.

   **What the evidence actually supports**, separated so the decision is not
   all-or-nothing:

   - **The correction itself is well supported and does not depend on the
     fleet numbers.** It is a claim about TWO sites. Three independent signals
     agree that `actioncarting.com` and `interstatewaste.com` are fine: the
     synthetic-cookie pass, the real-click pass, and Nick's own manual check of
     the trigger.
   - **The laptop measurement is reproducible.** Three runs nine hours apart --
     1212, 1322, 2151 -- all identical: 27 roster, 18 tested, 0 leaking.
   - **The fleet numbers are weaker.** 9 of 27 are untestable, and the CI run
     reached only 10 of 26 for reasons not yet established.

   **THE GAP THAT WOULD EARN CONFIDENCE, and it is real: this instrument has
   never once reported a leak.** Zero on 18 sites, three runs running. That is
   the same shape as both previous defects, and there is no end-to-end proof it
   would catch a site that genuinely ignores a rejection. `test-gating-window`
   proves a load-phase request IS measured, which is a window-level positive
   control, not a sweep-level one. Build a local fixture that ignores the
   rejection, run it through the real sweep, and assert it comes out as a leak.
   Until that exists, "0 leaking" is unfalsified rather than verified, and Doug
   is right to hold.

2. **The `interstatewaste` pass disagreement**, above. Code, and mine to do.
3. **The 5 Cloudflare-challenged sites.** The WAF skip rule is Matt's existing
   item for the 8 CI-blocked sites; these 5 are the same problem seen from the
   gating sweep. Until it lands they are unreadable from this instrument, and
   saying so is better than a number that excludes them silently.
4. ~~no severity codes for gating~~ **WRITTEN 2026-08-28.**
   `consent_gating_leak`, consent axis, WARN, routed to "needs a person"
   because a visitor who explicitly refused and is tracked anyway is the
   strongest consent finding available. **0 sites leak**, measured. Untested
   is an info line on 9 sites, never a WARN: a rule firing on all of them
   ranks nothing, which is the `upstream_pending` mistake.

   **Nothing was waiting on Nick, and this file said it was for a day.** The
   standard was settled in `docs/CONSENT.md` from the first sweep and
   implemented in two scripts. Doug spotted it: "I thought this was all asked
   and answered previously." It was. Checked before writing this time,
   `git log -S` confirms no gating severity code has ever existed, so nothing
   was lost or reverted either.

   Still genuinely open: B1 blocked on CONTENT (`client`/`owner`, Victoria's
   question) and B6.

---

## Previously: 2026-08-28, morning: the gating window was wrong AGAIN, fixed as v3

**The correction to Nick has NOT been sent, and that is now correct twice
over.** An outside review of the whole repo ran today (delivered to Doug as a
shareable page; its top items are also in `docs/DO-THIS-NEXT.md` territory) and
its most urgent finding was in the gating test we fixed yesterday:

**v2's window erased the load it exists to measure.** The 2026-08-27 fix
cleared the request counters after `page.reload({waitUntil:'load'})` resolved.
The load event fires AFTER the fresh page's load-phase requests. Where GA4
pageview hits normally fire, so everything the consent-denied page did while
loading was recorded and then wiped. "Nothing fires after rejection" is the
best possible result, and the instrument manufactured it: run 2159's "0 of 23
still fire" is unmeasured, and the bug-table sentence "ZERO requests on all
23" was false as written (3 sites show G100 pings even through the broken
window). Both are corrected in place.

**Fixed as v3, 2026-08-28.** The reject pass now closes the page and measures
a FRESH one on the same context: the rejection cookie persists, the listener
exists before the first request, the window is the measured page's lifetime.
No clear whose ordering can be wrong a third time. It is the shape the
synthetic-cookie pass always had, which is also why Nick being right about
the trigger still stands: that pass was never mis-windowed.

- `test/test-gating-window.mjs` (new, 10 checks) drives both boundaries
  against a local fixture: a load-phase request IS measured, the old page's
  post-click beacon is NOT. **Verified to fail against v2 before v3 existed**
  (the two load-phase checks failed, the exclusion passed: exactly the
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
   objection. That a compliant site should still send cookieless pings and
   our report showed none. Was v2's defect showing; the re-run should
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
   test-email-dns.py stops pinning the fleet at 78. It asserts the scan
   covers its roster instead.
6. **build-fleet-inventory.py refuses an existing --out.** A rerun per its
   own Usage block would have silently erased every hand ruling in the
   inventory. test-build-inventory.py asserts the refusal.

Not done, still Doug's: the `client`/`owner` content for B1; turning on the
email-dns and worker-exposure schedules; ruling the four Lactalis redirect
domains (their consent rows describe lactalisusa.com, not themselves).

---

## Previously: 2026-08-27, end of day: everything is pushed, published and deployed

`HEAD` and `origin/main` are both `1af5401`. All four pages are live and were
verified by reading them back from R2 and from the deployed Worker, not by
trusting a success message. **The Worker was redeployed today**: the first
time in this project's history that a route was added, so it is worth knowing
that `wrangler deploy` from `ci/cloudflare` is a human action and the file
means nothing until it runs.

Live: `/` (evidence matrix), `/components`, **`/consent` (new)**,
`/api/fleet-scan`.

### The consent work, which is most of today

The dashboard used to report `interstatewaste.com` as leaking four trackers.
It is opt-out outside California, working exactly as designed, and the agency's
own OneTrust audit records it compliant. **The sweep observed correctly and the
rule drew a conclusion the observation could not support**: the cold load
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

### The finding that was not one. Read this before trusting the gating sweep

The sweep reported **MS Clarity still firing after Reject All** on
`actioncarting.com` and `interstatewaste.com`. It was raised with Nick Federico
on Teams. **He validated it by hand, said the trigger is correct, and he was
right.**

`test-gating.mjs` cleared its request counters BEFORE the post-rejection
reload, merging the window where the ALREADY-OPEN page finishes its work with
the window that actually answers the question: a fresh consent-denied load.
Clarity flushes its session buffer on consent change, and those beacons were
attributed to a tag ignoring consent.

~~Fixed, and re-run fleet-wide: **0 of 23 tested sites still fire after Reject
All.**~~ **That number is a v2 measurement and is unmeasured.** The window it
was taken through erased the load it existed to measure. See the 08-28 block
at the top. The v3 answer is **0 of 18**, and the difference is not 5 sites
getting worse: 5 of yesterday's 23 now draw a Cloudflare challenge on the
second navigation and are honestly inconclusive rather than dishonestly clean.

**The lesson, because it is more useful than the fix.** The instrument's own
two passes disagreed about the same site: the synthetic-cookie pass had Google
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

## Previously: 2026-08-27, evening: the new page is built, not pushed, not published

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
   download on the runner). See DASHBOARD-V3.md "Not done".
5. After one published cycle, retire `render()`, `--legacy-out`, and the
   `RD.render(...)` assertions in `test-ledger.py`.

---

---

## Older sessions

Sessions before 2026-08-27 are not in this file. They were cut on 2026-08-31,
when the repo transferred to the clevermethod org: every section was already
marked superseded, and they carried material outside this project -- other
Workers on the account, their secret names, and individual Access grants.

Nothing durable was lost. The reasoning those sessions produced lives in
`CLAUDE.md`, `docs/DATA-MODEL.md`, `docs/SEVERITY.md`, `docs/DASHBOARD.md` and
`docs/CONSENT.md`, which is where it belongs -- a chronological log is a poor
place to look something up. If you find a claim here with no explanation
behind it, that is a bug in those documents, not a reason to restore this one.
