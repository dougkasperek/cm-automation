# WordPress vulnerability intelligence: review and feasibility

**Written 2026-08-20. Section 0 added 2026-08-24 after the post-action
regroup, which answered four of the six open questions and changed the
delivery target from Asana to Teams. Steps 0 and 1 are built; step 2 onward is
not.** Inputs: `wordpressvulnerabilityintelligencefleethealthv2.md`
(the research doc), the Pods advisory and its CVE record, Wordfence's V3 API
change notices, Patchstack pricing, the Matt/Doug Teams thread from this
afternoon, and the cm-automation scanner, ledger and CLAUDE.md as they are
tonight. Nothing was built.

**Caveat on sources.** wordfence.com pages did not render for my fetch tool
(blank body), so the advisory facts below come from NVD, OpenCVE and
Patchstack, and the V3 API facts from two third-party write-ups of Wordfence's
2026-02-02 notice plus the V2 schema I already know. Two items are marked
*verify* where the live V3 response is the only authority.

---

## 0. The post-action regroup, 2026-08-24

**A meeting happened, and it answers most of section 6.** Attendees Brian,
Matt, Victoria, Zach, Doug. Transcript: `Post Action regroup.vtt` in the
Cowork Automation Portfolio `meeting-records` folder. This section is what it
settled; the sections below are the 2026-08-20 analysis and are left as
written except where marked.

**Doug has an action item, recorded in the meeting.** Matt: *"I heard Doug is
going to noodle on what he's got because it's kind of close to maybe doing
some of the formula we just talked about."* The formula Brian stated is
exactly steps 2 to 5 below: *"unique across the entire portfolio. Get the
CVEs, cross compare it. If there's a hit, then someone needs to do
something."*

### What the meeting settled

| question, from section 6 | answer |
|---|---|
| Which site, how was it found | **Zach found rogue admin users** on a site, then they looked and found them "everywhere". Not a Wordfence alert, not a client report. A person noticing a user list |
| Who owns the Wordfence account | Matt: the key is *"shy of a few minutes"* away. **Still must be created on a clevermethod-owned login**, which is the same constraint as before, but it now has an owner |
| Is Patchstack in use | not raised. Treat as no |
| Scope: plugins only? | **No, and Doug raised it.** *"Plugin concerns are just one flavor of CVE. We got to go bigger than that."* Confirmed by the July WordPress **core** vulnerability. Victoria read the feed schema aloud: type core/plugin/theme, name, slug, affected versions, patched versions, remediation |
| Delivery target | **Teams, not Asana.** Matt wants *"an email or a Teams message dropped into a channel we can all see"*. Victoria: *"I started a bit of work on the critical notifications channel."* **This changes step 5** |
| Auto-update on a hit? | **No, firmly, from both.** Matt wants a soak period, *"a week, seven days"*, unless it is a hotfix. Brian wants it through backfill test-from-prod, dev-from-test, update, examine, publish. The output is a TICKET, and *"the validation is the human element"* |

### What the meeting changed

**The root cause was not only Pods.** Section 1 below reads as a Pods
incident. Brian's account is messier and worth keeping: rogue admin users,
found by eye; a code review that revealed no changes; a database comparison
that **timed out and never completed**; and a conclusion that the users were
probably remnants of an EARLIER incident, from a white-label plugin with an
elevated-privileges flaw that had already been removed. Three other CVEs were
identified as plausible alongside Pods.

Matt's reading is the simpler one, and both were left standing in the room:
*"pods had a vulnerability that got exposed and all the sites that had pods on
it and hadn't been updated within X amount of days were exposed."*

**Nobody established which one it was.** That matters for this document
because a vulnerability feed would have caught the Pods path and would not
have caught a leftover account from a prior incident. Do not let the build
imply otherwise.

**A new inventory dimension exists.** Victoria added a **content management
model** column to the master WordPress spreadsheet: clevermethod only, both,
or client only. It decides whether we can act on a site unilaterally, which
makes it a routing input, not just a note. It is a RULING in this repo's
sense and belongs in `data/fleet-inventory.json` alongside `production`. See
the ruling backlog in `docs/DO-THIS-NEXT.md`.

**The WAF has a known side effect.** Brian: any plugin using
`/wp-admin/admin-ajax.php` to write to the database is blocked by the
block-unknown-WP-admin-source-IP rule. Four issues are open in Asana under
"CF onboarding issues". Not this tool's problem, but it is why a site may
misbehave in a way unrelated to anything here.

### The 312, since Matt challenged it

Matt, on hearing the number: *"312 plugins, it sounds like a lot. There's no
way it's right."*

**He was right that it was wrong, and the defect was worth more than the
count.** It is **310**. Two components were counted twice because WP-CLI
reports the on-disk directory name and the casing differs between sites:
`Divi-Child` on 25 sites and `Divi-child` on 16 are one theme on 41;
`PDFEmbedder-premium` on 11 and `pdfembedder-premium` on 2 are one plugin on
12. Fixed 2026-08-24 by keying the catalogue on the lowercase slug at render
time, with every observed casing kept and shown on the row.

The count was the small half. **Wordfence publishes lowercase slugs**, so the
matcher in step 4 would have hit 2 of our 12 PDFEmbedder sites and reported
the other 10 clean. See the step 4 row.

A second defect fell out of the same check: `hoffmanscheese` carries
`pdfembedder-premium 3.2` **inactive** beside `PDFEmbedder-premium 5.1.4`
active. Two copies on disk. The catalogue counted rows as sites and said 13.
This is the first real instance of open question 6, and it argues for the
proposed answer: inactive is WARN, never CRIT, and never silently excluded.

The rest of the shape is unchanged. Measured
from `history/components.jsonl`, run `health-2026-08-23_1956`:

| | |
|---|---|
| distinct components | **312** = 287 plugins, 12 mu-plugins, 13 themes |
| installs | 1,842 across 47 of 53 Pantheon sites |
| on exactly ONE site | **156**, half the catalogue |
| on 10 or more sites | 50 |

So the shared white-label core is about **50 components**, which is the number
Matt has a mental model for. The other half is a long tail of one-site
plugins, and **that tail is the part nobody has a mental model of**, which is
precisely the exposure a catalogue exists to surface. Both halves of his
reaction were correct.

---

## 1. The incident

| | |
|---|---|
| Plugin | Pods – Custom Content Types and Fields (slug `pods`), ~100k installs |
| CVE | CVE-2026-19598, CWE-863, CVSS 3.1 **9.8** (AV:N/AC:L/PR:N/UI:N) |
| Flaw | `pods_admin` AJAX router routes every access check through `pods_error()`, which on one code path only logs and returns false. Every guard is bypassed; an unauthenticated visitor can reach admin methods (reset passwords, create admins). |
| Affected | 2.8–2.8.23.3, 2.9–2.9.19.3, 3.0–3.0.10.3, 3.1–3.1.4.1, 3.2–3.2.8.2, 3.3–3.3.9 (**six branches**) |
| Fixed | 3.3.9.1, 3.2.8.3, 3.1.4.2, 3.0.10.4, 2.9.19.4, 2.8.23.4 |
| Disclosed | 2026-08-15 (Wordfence is the CNA); patches ~36 hours later |
| Exploited | Patchstack marks it "Known to be exploited". **Not in CISA KEV** as of today. |

Matt, 19:36 ET: *"PODS. need a better way to monitor the WordPress CVEs"*, then
*"so then we'd know the total catalog of plugins we're using and if any hit
against here."* Which site was hit and how it was found is not in the thread.
That is question 1 below.

Two things about this incident shape the design:

- **There was a ~36 hour window with no patch.** During it, the only useful
  output is "these N sites run Pods, here are the versions, here is the
  workaround." Update-availability monitoring cannot see that window at all.
- **Six patched branches.** Any version matcher has to handle multiple
  disjoint affected ranges per record. The Pods record is the test fixture.
- **KEV lags.** Patchstack flagged exploitation; CISA has not listed it five
  days on. KEV cannot be the only exploitation signal.

---

## 2. What we have today

**The scanner runs the right command and throws the answer away.**
`pantheon-fleet-healthcheck.sh` line 309 runs
`wp plugin list --update=available --format=json`, then stores
`jq 'length'`. The ledger holds `plugin_updates` (a count) and
`theme_updates` (a count). No slug, no name, no version, no status. Line 1 of
CLAUDE.md's bug table is `plugin_updates: 0` standing in for "nobody looked".

So the doc's Phase 1, *"confirm inventory quality"*, understates it. **There
is no component inventory to confirm.** Nothing in the repo can answer "which
of our sites run Pods?" tonight, and that is the question Matt asked.

What exists that a vulnerability engine can use:

| asset | state |
|---|---|
| `wp_version` per site | measured, 48 of 52 Pantheon sites |
| PHP version | measured (Pantheon), claimed (Nexcess) |
| `production` flag | in the inventory, load-bearing |
| `attestations` per site | in the inventory, with source and date |
| append-only ledger, per-source fact families, collision guard | built |
| severity module, one scorer, per-axis | built; CRIT means security tier |
| CI on GitHub Actions with secrets, scheduled workflows | built |
| Pantheon deep scan (SSH + WP-CLI) | live, 48 sites |
| Nexcess deep scan | not built; blocked on the SSH-key question |

Coverage is the hard limit: a component inventory built on the existing
deep scan reaches **48 of 84 sites**. The 21 Nexcess sites and the 10 sites on
Azure, Pressable, Flywheel and WP Engine stay dark until their SSH paths exist. The page has to say so per site,
or "no vulnerable component" reads as clean on a site nobody inventoried.

---

## 3. The doc: agree, disagree, adjust

### Agree

- **Intersection, not a news feed** (§1, §29). Correct framing. Matt said the
  same thing in his own words.
- **Lives in Fleet Health, not a fourth module** (§2). In this repo's terms:
  a new fact family in the ledger, new codes in `severity.py`, scored on the
  **health** axis. CRIT is already defined as "act now, security tier", which
  is exactly what an exploited unauthenticated privesc is. No new axis.
- **Do not scrape the Wordfence site; use the feed** (§4). Yes.
- **`vulnerability_id` primary, `cve_id` nullable** (§6). Pods had a CVE at
  disclosure, many do not.
- **KEV as escalation only** (§7). Correct, and the Pods case shows it lags.
- **One feed first** (§8). Yes. Reconciling two feeds is a project in itself.
- **Inventory reuse; do not SSH the fleet on every feed event** (§10, §11).
  Matches how the ledger already works.
- **Match on slug + type + version, never display name** (§12).
- **Read-only; remediation is a separate, later, human-gated decision**
  (§23). This is CLAUDE.md's first hard boundary.
- **Licensing is a requirement, not an afterthought** (§25).

### Disagree or adjust

1. **Phase 1 is the whole first build, and it is small.** The doc treats
   inventory as something to verify. It has to be created: keep the full
   `wp plugin list --format=json` and `wp theme list --format=json` output
   (drop `--update=available`) and write one row per site per component. The
   command already runs inside the existing SSH session; the cost is storage
   shape, not a new scan. Add mu-plugins (`wp plugin list --status=must-use`)
   since `plugin list` omits them by default.

2. **The P1–P4 priority model is a second scoring model.** CLAUDE.md: *"never
   a second scoring model."* Map it onto what exists:
   `component_known_vulnerable` at **CRIT** when unauthenticated, or KEV, or
   RCE/privesc/auth-bypass/file-upload by CWE, or CVSS ≥ 9; **WARN** otherwise;
   a second code `component_vulnerable_no_patch` so "no fix exists yet" is
   visible as its own line. Use the existing `production` flag where the doc
   says "environment". Fleet prevalence ("12 sites run it") is a rendered
   aggregate, not a severity input.

3. **The finding lifecycle (§19) is a workflow state machine; the ledger is
   append-only observations.** `new → confirmed → patched → verified → closed`
   falls out of re-measurement: the next inventory run shows the new version,
   the rule stops firing, the diff records the change. Don't build states.
   `accepted_risk` and `false_positive` are attestations on the inventory
   record (that structure exists, with `by`, `at`, `source`), not ledger rows.

4. **Webhooks (§5, §27) mean a public write endpoint.** The only public
   surface is the `cm-fleet` Worker, which was made read-only with no secrets
   on 2026-08-19 after an audit found drift. A webhook receiver reverses that
   decision. Scheduled polling from GitHub Actions needs no new surface.
   Defer webhooks indefinitely; the polling cadence below is enough.

5. ~~**The rate limit is now known: 1 request per 30 minutes by default**,
   feed size ~120 MB~~ **BOTH WRONG. Corrected 2026-08-30 against the vendor
   page itself.** Wordfence publishes **no rate-limit number and no feed
   size**. The V3 doc says only that requests are subject to usage limits,
   that exceeding them returns **429**, and that a higher limit is granted by
   emailing `wfi-support@wordfence.com` with a reason. Both figures came from
   third-party write-ups of the 2026-02-02 notice and were repeated here in
   the same voice as a measurement -- CLAUDE.md's rule about stating a cause
   without checking, pointed at a vendor fact.

   **Both are now MEASURED, run 33313337785 on 2026-08-30.** The feed is
   **153,806,638 bytes decoded, 39,455 records**, 18,189 distinct slugs,
   11,823 of them with `patched=false`. And the limit is real and tight:
   two full-feed requests **nine seconds apart** returned
   `429 API key limit exceeded, try again later` on the second.

   That one data point says two requests nine seconds apart is over the
   line. **It does not establish 30 minutes**, and writing it up as though
   it did would be the same error as the figure it replaces. What it does
   settle is the design: **fetch once per run and cache**, which is what
   `fleet-vuln.py fetch --out` exists for. Back off on 429; email
   `wfi-support@wordfence.com` if a higher limit is ever needed.

   Still true: key required, **free** for personal and commercial use, and
   the disclosure-to-patch window was 36 hours for Pods, so a poll every few
   hours is ample. Do not commit the feed; cache it in the runner and commit
   only the filtered records that touch slugs in our catalog.

6. **Version comparison (§13).** WordPress plugin versions are not semver;
   `3.3.9.1` and `2.9.19.4` are normal. The repo's contract is stdlib Python,
   so no `packaging`. Write a small comparator that mirrors PHP
   `version_compare`, and test it against the six Pods ranges before anything
   else. **VERIFIED 2026-08-30 against the vendor page; no longer a guess.**
   The feed represents ranges as `{from_version, from_inclusive, to_version,
   to_inclusive}` with `*` for unbounded. Two details the guess did not
   carry. First, `*` is meaningful only as the ENTIRE string -- `1.*` matches
   an asterisk literally, so there is no glob to expand. Second, the KEY of
   an `affected_versions` entry may be a bare version, a range, or a
   bracketed interval, and it is display text: **parse the value object,
   never the key.**

7. **The dashboard headline (§17, "74 / 78 Healthy") is the single-status
   page we removed yesterday.** Scoring is per axis now. This is a section
   under the Health card plus the existing site table, not a new headline.

8. **Client-facing exposure (§27) is out of scope.** The page is internal,
   behind Cloudflare Access, read-only. Attribution still has to be right for
   internal use (Wordfence requires its copyright notice to be carried with
   the data; the feed includes a `copyrights` block per record).

9. **§22 on Nexcess is behind the repo.** The challenge finding is already in
   `fleet_nexcess.md` with the exhausted-tests table. Nothing to add, except
   that the inventory coverage gap (21 sites) is exactly this blocker.

10. **Missing from the doc: the catalog is a deliverable on its own.** Before
    any feed, "which plugins does the fleet run, on how many sites, at what
    versions" answers Matt's question and is the audit workbook's missing
    column. Ship that first; it is also how you check the feed integration by
    eye.

11. **Missing: WordPress core.** `wp_version` is already a fact. The same
    matcher covers core vulnerabilities for free.

12. **Missing: the 36-hour window needs a "no patch yet" state**, and a place
    to record the vendor workaround. That is the one moment this tool earns
    its keep, and the doc's model (§14, `patched: true`) only has the
    after-patch case as an example.

---

## 4. Feed choice

| | Wordfence Intelligence V3 | Patchstack Threat Intel API | WPScan API | CISA KEV |
|---|---|---|---|---|
| Cost | Free with account key | Separate product; Developer plan is $69/mo and the API is not listed as included | Free tier is small; paid above | Free, no key |
| Coverage | Largest WordPress-specific DB; Wordfence is a CNA | Comparable; Patchstack is also a CNA and often first to flag exploitation | Smaller | Cross-ecosystem, lags |
| Machine format | JSON feed, affected ranges per slug | JSON API | JSON API | JSON |
| Rate limit | 1 / 30 min default | plan-dependent | plan-dependent | none practical |
| Exploitation signal | ~~in record text/priority~~ **NONE. Corrected 2026-08-30: the V3 schema has no exploitation field at all** | explicit "known exploited" flag | partial | the catalog itself |

**Two V3 feeds exist, and this review knew about only one.** `/production`
carries `cve`, `cvss`, `cwe`, `description`, `remediation` and `researchers`;
`/scanner` carries enough to MATCH and nothing else. The severity mapping in
item 2 above is written on CVSS and CWE, which are production-only, so
**production is the feed** and that is a constraint, not a preference. Both
carry `informational`, a boolean this review did not know about, marking
records with "extremely limited or no real-world impact" -- a filter input.

And because Wordfence carries no exploitation signal, **KEV is the only one
in this design**, which the struck-through table row above had hidden.

Start with Wordfence V3 production (free, complete, machine-matchable) plus
KEV (free, one file). Revisit Patchstack only if we want its exploitation flag as a
second signal after the first cycle.

**Human task now:** create the Wordfence account and API key on a
clevermethod-owned login, not Doug's personal one. The Cloudflare token audit
this week found all three API tokens on Doug's personal account; don't add a
fourth.

---

## 5. Feasibility plan

Sized against the repo as it stands. Steps 0–2 need no feed and no new
credential.

| step | what | depends on | size |
|---|---|---|---|
| ~~**0**~~ | ~~Scanner keeps full plugin/theme/mu-plugin JSON per site. New ledger file `history/components.jsonl`...~~ **DONE 2026-08-23.** Built as specified, with one addition: `components_checked` is carried on the observation row and registered in `COVERAGE_FLAGS`/`COVERAGE_DIRECTION`, so a site nobody could inventory is distinguishable from one running nothing, and the first run does not report ~46 rows of fleet news. **No real scan has run yet, so `history/components.jsonl` does not exist and every count below is still 0.** | the existing deep scan | done |
| ~~**1**~~ | **DONE 2026-08-23.** Built as a separate PAGE rather than a section under Health: a section on the fleet page is site-major, and the question a count cannot answer is "which sites run this component, at what versions". Route `/components` on the Worker, rendered by `render-dashboard.py --components-out`, published in the same loop as the fleet page. Coverage stated first and the uninventoried sites NAMED. Original spec: Dashboard: "Components" section under Health. Fleet catalog (distinct slugs, site count, version spread), per-site list, search. Per-site line "components not inventoried" where coverage is missing. **Must also add a coverage-box line, "Component inventory: N of 52", denominator from the INVENTORY not from ledger rows.** As of 2026-08-23 the page holds 1,842 component rows and says nothing about how many sites they cover, which is the same shape as the Nexcess line that was missing for two days. Deferred here deliberately rather than forgotten. | 0 | ~half a day |
| **2** | `wp_version` + catalog answer "who runs X at version Y" via a CLI query. This is the Pods question, answerable from the ledger. | 0 | hours |
| **3** | Wordfence V3 fetch in a scheduled workflow (every 6h), key in GitHub secrets. Filter to slugs in the catalog + core, commit only those records as source `vuln-intel`. KEV fetch in the same job. | key, 0 | ~1 day |
| ~~**4**~~ | **THE COMPARATOR HALF IS DONE, 2026-08-30.** `scripts/lib/vercmp.py` implements PHP `version_compare` and Wordfence range matching, three-valued (True / False / **None meaning cannot say**). Verified against real PHP 8.5.9 on **6,537 pairs, zero mismatches**; 2,602 of those answers are frozen in `test/fixtures/php-version-compare.json` so the check needs no PHP. The **real** Pods record is `test/fixtures/wf-pods-production.json`, pulled by run 33314981104 -- 17 advisories, all scoring clean against the 3.3.9.1 the whole fleet runs. The hand-transcribed ranges agreed on all six, and were deleted anyway. Seven ways of breaking the module were verified to fail. **Still to do: the matcher that walks the catalogue against the whole feed, and the severity codes.** | 3 | half done |
| **4** | **MATCH ON LOWERCASE SLUG. Non-negotiable, and it is why the catalogue merges casings at render time.** Wordfence publishes lowercase slugs; WP-CLI reports the on-disk directory name, which differs per site. A case-sensitive match of `pdfembedder-premium` hits 2 of our 12 sites. Also: match on SITES not installs, since a site can carry the component twice. Matcher + `version_compare` comparator + severity codes (`component_known_vulnerable` CRIT/WARN, `component_vulnerable_no_patch`). Tests: the six Pods ranges, an unbounded range, a non-numeric version, a slug not in the feed. Render and look. | 3 | ~1 day |
| **5** | **Teams, not Asana. Changed by the 2026-08-24 meeting.** Matt asked for *"an email or a Teams message dropped into a channel we can all see"*, and Victoria has already started a **critical notifications channel**. A new CRIT component finding on a production site posts there. Asana task creation stays on the list as a later step, because the meeting also said the validation is a human step and a ticket should follow the human, not precede them. **Talk to Victoria before building: her channel may already define the message shape.** | 4 | smaller than the Asana item |
| **6** | Nexcess SSH inventory, when the key question is answered. Same rows, different transport. Coverage 48 → 69. | Nexcess | separate phase |
| — | Webhooks | never, unless polling proves too slow | — |

Effort totals roughly three days of build to step 4, on top of the
already-queued publish, coverage guard and token work.

---

## 6. Questions before building

**Four of these were answered by the 2026-08-24 meeting. See section 0.**

1. ~~**Which site, which version, how was it found**~~ **ANSWERED: Zach found
   rogue admin users by eye, not via any alert.** And the root cause was never
   pinned: the users may be remnants of an earlier incident rather than Pods.
   So the honest answer to "would step 2 have caught it" is **maybe**, and the
   build must not claim otherwise.
2. **Are any Pantheon sites composer-managed?** `wp plugin list` still sees
   those plugins, but the fix path differs (composer.json, not a dashboard
   update), and that matters for the remediation note.
3. **Auto-update policy.** Do any sites have plugin auto-updates on? If so
   the inventory will show version drift between scans that is not a person
   acting, and the diff should say so.
4. ~~**Who owns the Wordfence account**~~ **ANSWERED: Matt, and the key is
   "shy of a few minutes" away.** The constraint is unchanged: it must be
   created on a **clevermethod-owned login**, not a personal one.
5. ~~**Is Patchstack already in use**~~ **Not raised in the meeting. Treat as
   no.** Wordfence is the feed.
6. **Do inactive plugins count as exposed?** Many WordPress vulnerabilities
   need the plugin active; some (file-based) do not. Proposal: inactive =
   WARN, never CRIT, and the row says "inactive".

7. **NEW, from the meeting. What does the Teams critical notifications channel
   already expect?** Victoria has started it. Building a second message format
   against a channel that already has one is how two things that should agree
   start disagreeing. Ask before writing the payload.
8. **NEW. Does the content management model belong in the inventory?** It
   decides whether a site can be acted on unilaterally, which makes it a
   routing input for step 5 rather than a spreadsheet note. It is a ruling,
   and 83 of 84 sites have no ruling recorded at all today. See the backlog in
   `docs/DO-THIS-NEXT.md`.
