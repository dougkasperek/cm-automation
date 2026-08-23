# Fleet automation: design brief for the next round

> **SUPERSEDED. Read `docs/SESSION-HANDOFF.md` instead.** Kept for the record.
> Parts of this file are known wrong: it describes committing workflows to
> `ci/github-actions/` and copying them across, and that mirror was deleted on
> 2026-08-22. `.github/workflows/` is the only copy.

**Purpose.** This file is the cold-start handoff for a new session about
*expanding the design of the workflow*. Chats share this folder and project
memory, never each other's conversation history, so everything needed to resume
is written down here.

**Status: 2026-08-17.** Phase 1 works. The health check has now run to
completion three times against the real fleet. Nothing is in CI or production
yet, and that is deliberate.

---

## 1. Read these first

| Source | What it holds |
|---|---|
| `README.md` | the design rule and the portability contract |
| `docs/RUNBOOK.md` | severity model, how to run, failure modes |
| `docs/SECRETS.md` | secret inventory, Keeper research, recommendation |
| `docs/DASHBOARD.md` | live demo, hosting, the Access blocker |
| project memory `fleet_dashboard.md` | dashboard decisions, the known-bad-flagging bug |
| project memory `cicd_workflow_migration.md` | CI handoff brief and Keeper decisions |
| project memory `terminus_council_initiatives.md` | fleet history, the dev-team demand signal |

---

## 2. What exists and is proven

```
cm-automation/
  scripts/pantheon-fleet-healthcheck.sh   read-only fleet scan, api-only + full modes
  scripts/render-fleet-dashboard.py       scan JSON -> self-contained HTML, both schemas
  scripts/serve-dashboard.py              watches reports/, serves live, stdlib only
  scripts/publish-dashboard.sh            render + push to the Worker
  scripts/lib/common.sh                   portable timeout, noise strip, auth
  ci/cloudflare/cm-fleet-worker.js        R2-backed host. Built, unit tested, NOT deployed
  .github/workflows/...yml                thin wrapper. Written, never executed
  test/                                   mock terminus + 19 assertions, all passing
  reports/                                three real runs
```

Proven by real runs, not by argument:

- **API-only mode works and is enough to be useful.** Zero ERROR rows across 52
  sites. The comparable SSH-dependent plugin scan had 14 undetermined sites.
- **The galbanicheese bug is genuinely fixed.** It now reads WARN with a
  0-day-old backup on Performance Large.
- **The scan is deterministic.** See below, which is the important part.

---

## 3. The finding that should shape the next design round

Two runs, 14 hours apart, 52 sites each:

| | 8/16 17:25 | 8/17 07:26 |
|---|---|---|
| CRIT | 2 | 2 |
| WARN | 36 | 36 |
| OK | 10 | 10 |
| SKIP | 3 | 3 |
| FROZEN | 1 | 1 |

**The only difference in the entire fleet was `hoffmanscheese` backup age going
from 719 days to 720.** One integer, on one site.

Three consequences worth designing around:

**a. The valuable output is the diff, not the snapshot.** A daily digest that
re-reports the same 36 warnings every morning is noise, and noise is how people
learn to ignore an alert. The report someone should actually receive is
"hoffmanscheese aged past 720 days, nothing else changed." The snapshot stays
useful as a dashboard you go look at; the *push* should be the delta.

**b. There is no historical store.** Every run is a standalone file in a folder.
Nothing can currently answer "is our backup posture improving," "how long has
cm-whitelabel been failing," or "what changed this week." The diff above was
computed by hand with jq. That is the single biggest structural gap.

**c. The 36 WARNs are one fact, not 36.** Every one is `upstream_pending=1`,
i.e. a single Pantheon platform release nobody has merged. The severity model
counts sites when it should sometimes be grouping causes. 36 rows of the same
cause reads as a crisis and is actually one merge decision.

---

## 4. Design principles already settled, do not relitigate

1. **Logic in scripts, CI YAML is a thin wrapper.** This is what keeps the
   GitHub vs Azure DevOps choice cheap for Matt. If a change needs workflow YAML
   edited to alter *what gets checked*, it is in the wrong place.
2. **Portability contract: macOS bash 3.2 and Linux bash 5.x, unchanged.** No
   `mapfile`, no `date -d`, no `timeout` binary. This is not theoretical; a
   `mapfile` call stopped the script completing for weeks.
3. **Read-only until trust is earned.** Execution authority is a ladder, not a
   switch. Nothing auto-applies yet by design.
4. **SKIP and ERROR stay distinct.** Confirmed-absent is not the same as
   could-not-determine. Collapsing them once produced a false result on a
   known-good site.
5. **Unknown is never folded into negative** anywhere in the reporting.
6. **Known-bad markers describe a symptom, never a site name.** Flagging a
   correct row as broken teaches people to ignore the flag.
7. **State colors are validated, not brand-picked.** The deck's own severity
   green and amber fail colorblind separation at protan delta-E 3.8.

---

## 5. Open design questions, roughly in dependency order

### A. Reporting model
- Diff-based digest: what counts as a change worth pushing? A status
  transition? Any field? A threshold crossing?
- Grouping by cause vs listing by site, given the 36-WARN case.
- Should `upstream_pending` even be WARN, or is it a separate "platform drift"
  dimension that belongs on its own line?
- Sandbox-plan sites have no automatic backups. Should plan-aware thresholds
  suppress a CRIT that is really a plan choice, or is suppressing it exactly how
  a real missing backup gets hidden later?

### B. Persistence and trend
- Where does run history live? A file per run in R2, rows in D1, or a single
  append-only JSONL? D1 already exists on this account for deck analytics.
- Retention, and whether per-site history or per-run snapshots is the right
  grain.
- Does the dashboard grow a trend view, or does trend belong in the digest only?

### C. Exception routing
- The deck's slide 16 model routes only exceptions to Asana. What creates a
  task, what updates one, what closes one? Duplicate suppression is the hard
  part, and the diff model above is probably the answer.
- Ownership: who is the assignee, and is that per-site or per-severity?
- Channel: Asana, Teams, email, ntfy. The deck implies Asana.

### D. Scope: which scripts join the workflow
- `wpstatistics-fleet-scan.sh` needs a post-fix re-run and would drop straight in.
- `galbani-wpstatistics-pull.sh` and `galbani-pantheon-metrics-pull.sh` are the
  client-reporting leg, a different cadence and a different audience.
- `ga4-agent-pull.py` is the odd one: Python, service-account JSON, no Terminus.
- Is this one workflow with several jobs, or several workflows sharing a library?

### E. Execution authority ladder
Read-only is step one. The documented next rungs, in increasing order of
caution: automated pre-update backups, applying updates on a multidev branch for
review before merge, then Pantheon's own mass-update tooling. What has to be
true before each rung unlocks, and who signs off?

### F. Platform and secrets
- GitHub Actions vs Azure DevOps is still Matt's call and still uncommitted.
- Keeper is researched, not implemented. Phase 1 deliberately uses native
  platform secrets so a first failure has one obvious cause.
- The runner should get a dedicated passphrase-free SSH key, not Doug's personal
  key with its passphrase vaulted.

### G. Surfacing
- Local live server works today and needs nothing.
- Hosted URL needs its own hostname and its own Cloudflare Access policy,
  because the deck's allowlist is partners-only and must not include developers.
- Does this ever become client-facing, which is a different product question
  than an internal ops tool.

---

## 6. Constraints any design has to respect

- **Claude cannot reach Pantheon.** Verified, not assumed: `api.pantheon.io`,
  `terminus.pantheon.io` and `pantheon.io` all fail from the cloud sandbox, and
  the device bridge has no network at all. Every scan runs on Doug's Mac or on a
  CI runner. Any design that assumes an agent can fetch live fleet data is wrong.
- **Fleet size disagrees between scans.** 52 sites in the health runs, 54 in the
  August plugin scan. Unreconciled. Worth resolving before any count is quoted
  to anyone.
- **`.github/` paths cannot be written by the device bridge.** Workaround in use:
  commit to `ci/github-actions/` then copy with `device_bash`.
- **The repo is not in git yet** and still lives under the Cowork Automation
  Portfolio folder rather than `~/dev`.

---

## 7. Explicitly not decided

Platform choice. Keeper implementation. Schedule and cadence. Asana routing
mechanics. Whether the dashboard gets hosted at all. Whether fleet health or
client reporting is the pilot that gets formalized first. Whether any of this
becomes a client-facing service rather than internal tooling.

---

## 8. Live demo, for reference

```bash
# terminal 1
./scripts/serve-dashboard.py --dir ./reports --open

# terminal 2
export PANTHEON_MACHINE_TOKEN=...
./scripts/pantheon-fleet-healthcheck.sh --api-only --no-fail-on-crit
```

The page fills in site by site as the scan runs. No Cloudflare, no Access
policy, no CI, no deploy.
