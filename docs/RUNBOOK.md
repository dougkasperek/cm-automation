# Runbook: Pantheon Fleet Health Check

## What it answers

For every site in the Pantheon fleet, on one chosen environment:

| Field | Source | Needs SSH? |
|---|---|---|
| Site exists, frozen, plan | `site:list` | no |
| Target environment exists and is initialized | `env:list` | no |
| PHP version | `env:info` | no |
| Newest DB backup age | `backup:list` | no |
| Pending upstream (platform) commits | `upstream:updates:list` | no |
| WP core update available | `remote:wp core check-update` | **yes** |
| Plugin updates available | `remote:wp plugin list` | **yes** |
| Theme updates available | `remote:wp theme list` | **yes** |

The top five are why `--api-only` is a genuinely useful mode and not just a
smoke test: it still produces real backup and upstream-drift severity across
the whole fleet without an SSH key existing anywhere in the pipeline.

**Why not just read the Pantheon dashboard?** The dashboard's Status column is
platform-level only - Active/Frozen, traffic against plan. It does not show
per-site WordPress core, plugin, or theme update status, or backup age. That is
the security and maintenance data this produces, collapsed into one
severity-ranked report instead of 54 manual site visits.

---

## Severity

| Status | Meaning |
|---|---|
| `CRIT` | DB backup older than the threshold (default 2 days), no backup at all, or a WP core update pending |
| `WARN` | Plugin updates, theme updates, or pending upstream commits |
| `OK` | Everything checked came back clean |
| `FROZEN` | Site is dormant on Pantheon; deep checks skipped by design |
| `SKIP` | Target environment confirmed absent or never initialized - **not** an error |
| `ERROR` | Checks could not be completed. Status genuinely unknown. Investigate manually |

`SKIP` and `ERROR` are deliberately separate. Collapsing them once mislabeled a
known-good site (galbanicheese) as nonexistent, because a timed-out response
parsed as valid-and-empty. If you see `ERROR`, the site has not been assessed.

Exit codes: `0` clean, `1` hard failure (auth, tools, no sites), `2` CRIT found.

---

## Running locally

```bash
export PANTHEON_MACHINE_TOKEN=...

# First run on any new machine or account: cheap, API-only, five sites.
./scripts/pantheon-fleet-healthcheck.sh --api-only --no-fail-on-crit --limit 5

# Named test cohort.
./scripts/pantheon-fleet-healthcheck.sh --api-only --sites galbanicheese,actioncarting

# Full scan (requires an SSH key registered with Pantheon).
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_rsa
./scripts/pantheon-fleet-healthcheck.sh
```

Outputs land in `./reports/` as `.md` (digest), `.csv` (spreadsheet), and
`.json` (machine-readable, and the input for any future Asana routing).
The JSON is rewritten after **every site**, so killing a stuck run keeps
everything gathered up to that point.

---

## Running in GitHub Actions

Actions tab -> *Pantheon Fleet Health Check* -> **Run workflow**.

| Input | Phase 1 value |
|---|---|
| `run_mode` | `api-only` |
| `target_env` | `live` |
| `sites` | leave blank, or a small cohort for the very first run |
| `fail_on_crit` | `false` |

One repository secret is required: `PANTHEON_MACHINE_TOKEN`.
Phase 2 adds `PANTHEON_SSH_KEY`. See `docs/SECRETS.md`.

Results appear three ways: the digest is rendered into the run's job summary,
all three files are attached as a build artifact for 30 days, and the exit code
is re-raised at the end of the job.

---

## Phased rollout

1. **API-only, manual, `fail_on_crit=false`.** Proves runner egress to
   pantheon.io, machine-token auth, Terminus install, and artifact collection.
   Nothing can fail the build, so a red run means a real infrastructure problem.
2. **Full mode on a small cohort.** Generate a dedicated passphrase-free SSH key
   for the runner, register it with Pantheon, add `PANTHEON_SSH_KEY`, run
   against 3-5 known-good sites. This is where `StrictHostKeyChecking
   accept-new` earns its keep - a fresh runner has no `known_hosts`, so without
   it every site emits a host-key line that breaks `jq`.
3. **Full fleet, still manual.** Compare against a local run of the same day.
   They should agree. If they do not, the difference is the finding.
4. **Scheduled, `fail_on_crit=true`.** Uncomment the `schedule` block. Only
   after several cycles of clean, human-reviewed runs.
5. **Route exceptions onward** (Asana, per the partner deck's slide 16 model).
   Not scoped yet. The JSON output is the intended input.

Do not skip step 3. A CI run and a local run disagreeing is the single most
likely way this quietly produces wrong answers, and it is only detectable while
both still exist.

---

## Known failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `no sites returned` | bad/expired machine token, or the runner cannot reach pantheon.io | check the secret; check egress |
| Many sites `ERROR` | API timeouts under CI network conditions | raise `API_CALL_TIMEOUT` in the script |
| `jq` parse failures | new noise line not covered by `strip_noise` | add the pattern to `strip_noise` in `lib/common.sh` and add a mock case |
| Run hangs despite timeouts | a grandchild `ssh` not reaped by the poll-kill helper | the job-level `timeout-minutes` is the backstop; investigate the site manually |
| A site's env reads absent but you know it exists | `ERROR`, not `SKIP` - treat as unknown | rerun that site alone with `--sites` |
