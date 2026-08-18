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

| thing | state |
|---|---|
| Repo | live, `github.com/dougkasperek/cm-automation`, private |
| Email DNS check, 78 sites | green in GitHub Actions, 26s |
| Pantheon health scan, 52 sites | works locally |
| **Full mode (SSH + WP-CLI)** | **WORKS.** Proven on galbanicheese, `wp_checked: true` |
| Unified 84-site inventory | built, keyed on domain |
| Ledger | repaired, 4 runs, both tools, every row resolving |
| Dashboard | 84 sites, WP version column, verified in both schemes |
| **CI writes to the ledger** | **built, not yet run.** `docs/CI-LEDGER.md` |
| Tests | ledger **90**, email **58**, mock harness **27**. All offline |

### The full-mode result so far

One site, `galbanicheese`, `reports/fleet-health-2026-08-18_1643.json`:
`wp_checked: true`, `plugin_updates: 0`, `theme_updates: 0`,
`wp_core_update: "up-to-date"`, and `upstream_pending: 2`.

Those zeros are real readings, not the fabricated kind. **The full fleet has not
been scanned in full mode yet.**

---

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

### Uncommitted on Doug's Mac right now

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

1. **`rm -f .git/index.lock`**, then commit the above. A session left a stale
   lock; see the traps below.
2. **Copy both workflows** from `ci/github-actions/` into `.github/workflows/`.
   The bridge cannot write `.github/`. Nothing in CI changes until this is done.
3. **Re-run the 2-site cohort locally** so `wp_version` is actually populated —
   the galbanicheese run above predates the field and stores `unknown`.
4. **Then the full fleet in full mode**, then the same scan in CI, then compare
   the two on facts. `docs/SSH-KEY-SETUP.md` steps 5 and 6.
5. **Look at the WP version column.** Any site not on 7.0.2 is the most
   important thing this project can surface. One month after `wp2shell`, an RCE
   whose only fix was that upgrade.
6. **Recover the lost email run.** One `email-dns` run observed
   `2026-08-18 15:00:00` appears in the old rendered page and has no report file
   anywhere. Its Actions artifact should still exist for 90 days. Download it
   into `reports/` and ingest.
7. **Deploy the dashboard to Cloudflare.** Worker and R2 code in
   `ci/cloudflare/cm-fleet-worker.js`, never deployed. Needs its own hostname
   (suggest `fleet.thudstaff.com`) and **its own Access policy** — the deck's
   allowlist is partners-only and must not include developers.
8. **Nexcess.** 46 sites vs 21, and Nexcess Managed WordPress also has SSH plus
   WP-CLI, so the deep-scan code written for Pantheon is what it reuses. The one
   genuine unknown is site enumeration.

---

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
- **Version-stamping the tool per run.** When the MEANING of a fact changes, the
  first diff afterwards reports it as a fleet change. Adding `wp_version` will do
  exactly this on the first full-mode fleet run. Still not built.
