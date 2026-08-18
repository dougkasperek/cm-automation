# Fleet automation: revisiting the overall design

**2026-08-17.** Written after building a working history ledger and change
detector against the two real 52-site runs on disk. Everything below is
grounded in output from that prototype (`scripts/fleet-ledger.py`,
`test/test-ledger.py`, 43 assertions passing), not in argument.

This supersedes section 5 of `DESIGN-BRIEF.md`. The brief listed seven areas of
open questions. Working the real data collapses most of them into one
structural change plus four smaller ones.

---

## The reframe in one sentence

**What exists is a scanner that emits reports. What the work needs is a ledger
that emits decisions.** Every problem in the brief's list is downstream of that
one gap.

A scanner answers "what is true right now" and throws the answer in a folder. A
ledger answers "what changed, what is still true, and what has to be decided"
and keeps the record. The scan script is good and is not the thing to change.
The layer above it does not exist yet.

---

## Five findings from the real data that should drive the design

### 1. The entire WARN/OK split in the fleet is one boolean

| status | `upstream_pending` | count |
|---|---|---|
| OK | 0 | 10 |
| WARN | 1 | 36 |
| CRIT | 1 | 2 |

Not one site in the fleet has a non-zero plugin, theme or core count. So the
severity model, run against production, is currently reporting exactly one bit
of information per site: has this site merged the pending Pantheon upstream
commit. The ten "healthy" sites are the ten that merged it.

That is not a health check. It is an upstream-drift check wearing a health
check's labels.

**And the single status field actively loses information.** The two CRIT sites
*also* need that merge, but a site gets exactly one label, so the digest says 36
where the true blast radius is 38. The prototype counts 38 because it groups by
cause instead of by row.

### 2. Unknown is folded into a *positive* in the data, not just the display

Settled principle 5 says unknown is never folded into negative. The real
problem turned out to be the other direction, and it is in the JSON:

```json
{ "site": "lasershows", "wp_checked": false,
  "plugin_updates": 0, "theme_updates": 0, "wp_core_update": "n/a" }
```

In api-only mode nobody looked at plugins, and the scan writes `0`. That `0`
renders as a literal `0` in the Plugins column of every row of the CSV and the
markdown digest, which reads as *no plugin updates pending*. `"n/a"` is honest;
`0` is a fabricated negative.

Consequence: **ten sites currently render green OK with three of eight fact
fields never observed.** That is the same class of defect as the known-bad
banner bug already fixed on the dashboard — a display asserting more confidence
than the data supports — and it is worse here because it is in the stored data,
so every downstream consumer inherits it.

This was found by a unit test, not by reading. The prototype's ledger now
refuses the fabricated zero at ingest (`DEEP_ONLY` coercion to `unknown`), but
**the scan script should stop emitting it.** Two-line fix in
`pantheon-fleet-healthcheck.sh`.

### 3. The scan has no idea what any site *is*, and that is the biggest gap

There is no client, no production flag, no owner, no contract tier anywhere in
the pipeline. Two things fall out of that:

- **Both CRIT rows are Sandbox scratch sites.** All six Sandbox sites in the
  fleet are non-production: 3 uninitialized, 1 frozen, 2 with ancient backups.
  All 46 paid-plan sites have a 0-day-old backup. So the highest severity tier
  in the entire fleet currently produces **zero production-actionable
  findings** — and it will keep producing two forever, which is precisely how a
  real missing backup gets ignored later.
- **"hoffmanscheese looks client-named."** That guess appears in three
  documents. It is only necessary because nothing knows whether hoffmanscheese
  is a client.

**Proposal: a checked-in `fleet-inventory.json`.** Site -> client, contract
tier, production yes/no, owner, deliberate exceptions. Thirty lines of data, no
infrastructure, reviewed in a pull request like anything else.

It pays for itself immediately:
- Severity becomes plan-and-purpose-aware without suppressing anything: a
  Sandbox site with no backup is *expected*, and stating that explicitly is
  different from hiding it.
- **It resolves 52-vs-54 permanently and structurally.** Inventory is the
  authority, the scan is the observation, and disagreement between them is
  itself a finding. A site in Pantheon but absent from inventory is an
  `INVENTORY`-class change — the highest tier in the prototype. Today that
  discrepancy is a note in a memory file that a human has to remember to chase.
- Asana routing gets an assignee, which is otherwise unanswerable (brief 5C).

### 4. The most important fact in the data scores zero

**PHP 8.2 leaves security support on 31 December 2026 — 136 days out — and 46
of 52 sites are on it.** Separately, `runtalnorthamerica` (Performance Medium,
a paying client) is on PHP 8.1, which is already past end of security support
and receiving no patches at all.

Verified against php.net/supported-versions on 2026-08-17, and kept in the
prototype as a data table (`PHP_SECURITY_EOL`) rather than an if-chain so it can
be updated without touching logic.

The scan collects `php_version` and displays it in a column. It never scores
it. So the report leads with 36 rows about one merge and is silent about a
fleet-wide deadline with a fixed date.

This is not an alert. Nothing is broken today and nothing will be broken
tomorrow. It is a **planning** output, and the reporting model has no such
category — which is the real lesson: a model with only pass/fail per site cannot
express the most valuable thing the scan already knows.

### 5. Cadence has to follow volatility, and volatility is near zero

Two runs, 14 hours apart, 52 sites: **one integer changed.** The prototype's
diff confirms it and, more usefully, 13 assertions confirm the differ catches
new sites, vanished sites, resolved upstreams, threshold crossings both
directions, coverage changes and rule changes — so the quiet answer is a real
measurement, not a broken comparison.

A daily digest against this fleet is 364 emails a year saying nothing. Cadence
belongs to the *channel*, not to the scan:

| | cadence | content |
|---|---|---|
| scan | daily | cheap, builds history, no output to a human |
| push | only on a non-DRIFT change | "what changed and what to decide" |
| standing summary | weekly, fixed day | "what is still true", sent even when quiet |
| dashboard | on demand | the snapshot |

The weekly send happening even when nothing changed is deliberate. Silence has
to be distinguishable from breakage.

---

## What the digest actually reads like

Real output, from the two real runs (`reports/digest-sample.md`):

```
# Fleet delta - 2026-08-17 07:26:00
Compared with health-2026-08-16_1725 (14h earlier). 52 site(s) both runs.

## What changed
**Nothing that needs a decision.**
1 counter(s) moved on findings already open (suppressed):
- hoffmanscheese db_backup_age_days 719 -> 720

## Still true (grouped by cause, not by site)
RISK     - No recent DB backup ......... 2 sites, both Sandbox
RISK     - PHP past end of security support ... runtalnorthamerica (8.1)
COVERAGE - WP core/plugin/theme not observed ... 48 sites
PLANNING - PHP 8.2 support ends in 136 days .... 46 sites
DRIFT    - One unmerged Pantheon upstream commit ... 38 sites, one merge
```

Compare with the current digest: a 38-row table where 36 rows are the same
sentence, led by two Sandbox scratch sites, with a `0` in the Plugins column of
every row that nobody checked, and no mention of December.

---

## Answering the brief's open questions

### A. Reporting model — answered by the change classes

Five classes, in descending order of how much a human should care. This is the
core proposal and it is implemented:

| class | meaning | routes to |
|---|---|---|
| `INVENTORY` | a site appeared or vanished | push; nothing else is trustworthy until explained |
| `TRANSITION` | crossed a severity boundary, or coverage changed | push |
| `ONSET` | a condition became true | push, create task |
| `RESOLVED` | a condition became false | push, close task |
| `DRIFT` | a counter moved on an already-open finding | ledger only, suppressed |
| `RULE_CHANGE` | derived status moved with no observed change | push, labelled as *our rules moved, not the fleet* |

`DRIFT` is what makes the model work: `hoffmanscheese` 719 -> 720 is a clock
ticking on something already reported, not news. `RULE_CHANGE` exists because a
severity change with no underlying fact change is a very different conversation,
and conflating the two sends people chasing a ghost.

**Should `upstream_pending` be WARN?** No. It should be its own axis. Replace
one status per site with four independent ones:

- **RISK** — no usable backup, EOL PHP, WP core update pending. Exposure.
- **DRIFT** — upstream commits, plugin/theme updates. Debt.
- **COVERAGE** — what was not observed. Confidence.
- **LIFECYCLE** — plan, frozen, uninitialized, production flag. Does it count.

A site then has a risk tier *and* a drift state, and the 36-vs-38 information
loss disappears. This is the one settled decision worth reopening, because the
single-status field is the reason two of these five findings exist.

**Plan-aware thresholds:** do not suppress. Report with cause attached, as the
prototype does. "Both on Sandbox, which gets no automatic nightly backup, so
decide whether these are production" is actionable. Hiding it is how a real
missing backup gets lost.

### B. Persistence — append-only JSONL on disk, in git

Recommendation, and the prototype implements it: `history/observations.jsonl`
plus `history/runs.jsonl`. One line per site per run.

Measured: **19.5 KB per run.** Daily for a year is 7 MB; daily for five years
is 35 MB, and roughly a tenth of that gzipped. This is not a database problem.

| | JSONL in git | D1 |
|---|---|---|
| infra | none | account, binding, migrations |
| works on Doug's Mac and a runner identically | yes | needs network + creds |
| history is reviewable in a diff | yes | no |
| greppable with tools already installed | yes | no |
| query across 5 years from a Worker | slow | yes |

D1 becomes right the moment the *hosted dashboard* needs to query trend across
many runs. Until then it is a dependency with no payoff. **Path: JSONL stays the
source of truth permanently; publish a rolled-up JSON to R2 for the dashboard,
and add D1 later as a read replica if the dashboard ever needs real queries.**
The ledger is the asset; the store is an implementation detail.

Grain: per-site-per-run, because it supports both questions ("this site's
history" and "this run's snapshot") and per-run-only supports one. Retention:
keep everything; 35 MB over five years makes deletion a non-question.

### C. Exception routing — the change classes *are* the routing rule

This needed no new design. Duplicate suppression, called out in the brief as the
hard part, falls out for free:

- `ONSET` creates a task. `RESOLVED` closes it. `TRANSITION` comments on the
  open one. `DRIFT` does nothing at all.
- One task per **cause**, not per site, with the affected sites in the body. The
  38-site upstream merge is one task.
- Assignee comes from `fleet-inventory.json`. Without inventory this question
  has no answer, which is another argument for finding 3.

### D. Scope — one library, several entry points

`wpstatistics-fleet-scan.sh` shares the fleet and the cadence, so it ingests
into the same ledger and its findings join the same digest.

The client-reporting scripts (`galbani-*`, `ga4-agent-pull.py`) share almost
nothing: different cadence, different audience, per-client not per-fleet, and
one is Python with a service-account credential. **Separate workflow, shared
`lib/`.** Forcing them into one workflow buys nothing and couples two release
cadences.

### E. Execution authority — the ladder now has a measurable gate

The rungs were already documented. What was missing was what unlocks each one,
and the ledger supplies it: **a rung unlocks when the ledger shows N consecutive
runs where the diff predicted the change correctly.** Trust becomes a measured
quantity rather than a feeling. That is not possible without history, which is
another reason B comes before E.

### F. Platform and secrets — unchanged, and deliberately still open

Nothing here changes Matt's GitHub-vs-Azure call, which is the point of the
thin-wrapper rule. Keeper still stays out of phase 1.

### G. Surfacing — the dashboard should show the diff, not just the snapshot

The live local server needs nothing and already works. What it should gain is
the delta view: "last changed 14h ago, one field" is more useful at a glance
than 38 rows. The hosted path stays blocked on its own hostname and Access
policy, which is a decision, not a build.

---

## What this asks you to reopen

Six of the seven settled principles are untouched and should stay. One is worth
reopening:

**Reopen: one status per site.** Findings 1 and 4 both trace to it. Four axes
instead of one label.

**Mild expansion, not a break: the portability contract.** The scanner stays
bash because it shells out to Terminus. The ledger is Python stdlib, following
the precedent `render-fleet-dashboard.py` already set. No pip, no services, no
`date -d`, runs on macOS and Linux unchanged — the contract's *intent* is
intact.

---

## Order of work

1. **Fix the fabricated zeros in the scan.** Two lines. Smallest change with the
   largest correctness payoff, and everything downstream inherits it.
2. **Add `fleet-inventory.json`.** Unblocks severity, ownership, routing, and
   the 52-vs-54 question at once.
3. **Adopt the ledger.** Ingest is idempotent, so run it over the existing
   reports and every future one; history starts accumulating today.
4. **Split status into four axes.** Touches the scan, the renderer and the
   digest, so do it after 1 and 2 are settled.
5. **Wire the digest to a channel**, delta-on-change plus weekly-standing.
6. Then Asana routing, then the authority ladder, both of which need 2 and 3.

Steps 1 through 3 are each under an hour and none of them need CI, a platform
decision, or a secret.

---

## Prototype status

`scripts/fleet-ledger.py` — ingest / diff / digest / timeline. Stdlib only,
append-only, idempotent. Working against both real runs.

`test/test-ledger.py` — 43 assertions, all passing. Deliberately includes 13
that prove the differ *catches* changes, because a change detector that reports
"nothing" is worthless until shown to be capable of reporting something.

Not built: inventory join, the four-axis rescore, channel delivery, Asana. Those
are decisions first.
