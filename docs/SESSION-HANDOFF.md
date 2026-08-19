# Fleet automation: handoff for the next session

**Written 2026-08-18, second revision, late.** Chats share this folder and
project memory, never each other's conversation history, so everything needed to
resume is written down.

**This supersedes `DESIGN-BRIEF.md`**, and it replaces the earlier version of
itself from the same day, which is now wrong in several places.

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

**1. ~~Triage `cm-whitelabel`.~~ CLOSED 2026-08-19.** Doug: temp non-public
site, not a concern. Marked `production: false` in the inventory, so it is
still scanned and still shown on its own row but does not count toward fleet
health. **`hoffmanscheese` is still open** — 721-day backup gap, 29 plugin
updates, and one of the two remaining CRITs.

**2. ~~Recalibrate severity.~~ DONE 2026-08-19. See `docs/SEVERITY.md`.**
Scoring moved to `scripts/lib/severity.py` and is now re-derived at RENDER time
from the ledger, so thresholds can change without a rules move reporting as a
fleet change. The run rescores to **2 CRIT / 32 WARN / 13 OK / 32 UNKNOWN /
3 SKIP / 1 FROZEN**, with `cm-whitelabel` excluded by a `production: false`
ruling. **One thing is left open there: the scanner still scores with its own
inline rules, so its digest and its CI exit code disagree with the dashboard.**

**3. Deploy to Cloudflare. THE CODE IS DONE; the Cloudflare side is not.**
`publish-dashboard.sh` was rewired to `render-dashboard.py` on 2026-08-19 and
now takes **no scan file** — it renders from the ledger. `--emit-data` writes
the JSON feed from the same model object as the page, so `/api/fleet-scan`
stayed and serves `{"schema":"fleet-dashboard/2", ...}`. A `publish-dashboard`
job exists in the workflow, **default off**, running after `persist-ledger`.

**What is left is all in Doug's Cloudflare and GitHub settings**, in this order:
Worker `cm-fleet` via `wrangler deploy`, R2 binding `FLEET` -> `dash-data`,
`PUBLISH_TOKEN` secret, hostname (suggest `fleet.thudstaff.com`), **its own
Access policy** — the deck's allowlist is partners-only and must not include
developers. Then repo variable `FLEET_PUBLISH_URL` and repo secret
`FLEET_PUBLISH_TOKEN`, then flip `publish_dashboard` on. Full walkthrough is
`docs/DASHBOARD.md`. **Run `./scripts/publish-dashboard.sh --dry-run` and look
at the page before any of it.**

**4. Turn on `persist_ledger` and then the schedule.** See the permissions
decision above.

**5. Nexcess.** 46 sites vs 21, still zero `wp2shell` verification, and the
reason the dashboard covers 52 of 78 rather than all of them. The deep-scan code
written for Pantheon is what it reuses; the one real unknown is enumeration.

**Not on the critical path:** the CI-versus-local comparison in
`SSH-KEY-SETUP.md` step 6. Worth doing as validation eventually, but there is a
clean local baseline now and CI has proven it authenticates and reads versions.

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
