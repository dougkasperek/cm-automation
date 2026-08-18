# CI writes to the ledger

**Written 2026-08-18**, after finding that it never had.

## What was wrong

`history/observations.jsonl` is the one asset in this repo that cannot be
regenerated. Until today it was also the only one CI could not write to.

Three things combined:

1. `reports/` is gitignored, deliberately, so raw scan output never enters git.
2. `fleet-ledger.py ingest` was a manual step run on Doug's laptop.
3. Both workflows declared `permissions: contents: read`.

So every scan CI produced was a 90-day artifact and then nothing. The ledger
only grew when someone happened to run ingest locally while the reports were
still on disk.

Two consequences were already real by the time this was found:

- The committed ledger held **no email observations at all**, while the
  `fleet.html` committed beside it had been rendered from a ledger that did.
- The committed ledger was **mis-keyed**. It was written at the initial import,
  before `data/fleet-inventory.json` existed, so its health rows were keyed on
  Pantheon machine names instead of domains. Rendering from the repo as
  committed produced **130 rows for an 84-site fleet**: 52 machine names and 78
  domains with zero overlap. It was repairable only because the four source
  reports still happened to exist on one laptop.
- One email run, observed `2026-08-18 15:00:00`, appears in the old rendered
  page and **has no report file anywhere**. Its artifact should still be in
  Actions for 90 days. Nothing else has ever been lost.

## The design

`scripts/persist-ledger.sh`, called by a `persist-ledger` job in both workflows.

**Order of operations is the design.** Observations are committed *before*
anything is allowed to fail. An unrecognised site is a real finding and it does
raise the alarm, but it raises it after the data is safe, never instead. Failing
first would discard the run that discovered the problem.

**Conflicts are avoided, not resolved.** Two appends to one JSONL rebase badly.
On every attempt the script resets to the current remote head and re-ingests
onto it. `ingest` is idempotent on `run_id`, so this is always safe and cannot
duplicate a run. Three attempts, then it fails loudly.

**A separate job, for two reasons.** Only it needs `contents: write`, and only
it takes the `fleet-ledger-write` concurrency lock — a lock on the scan job
would queue a 45-minute run behind a 25-second one. The lock name is shared by
both workflows, so the Pantheon scan and the email check cannot race.

**It runs even when the scan job failed.** A CRIT finding fails that job by
design when `fail_on_crit` is on, and those observations are exactly the ones
worth keeping.

**`fleet.html` is committed alongside the ledger.** The renderer is
deterministic — same ledger in, byte-identical HTML out — so this produces no
churn, and it is what keeps the committed page and the committed ledger from
disagreeing again.

## The guards that would have caught this on day one

| guard | where | what it catches |
|---|---|---|
| a missing inventory is a hard error | `load_inventory` | ingesting without the join key, which is how the ledger got mis-keyed |
| unresolved rows are counted and printed | `ingest` / CLI | a row stored under a tool's own identifier, silently giving one site two histories |
| `--fail-on-unresolved` | `fleet-ledger.py` | the same, for CI, where nobody reads stdout |
| `--strict` | `render-dashboard.py` | a ledger site the inventory does not have. Reproduces the 130-row failure against the old ledger and exits 1 |
| an absent `reports/` is zero runs | `ingest` | the fresh-clone and failed-scan case that broke CI run #1 |

## Open

**Whether CI should commit to `main` at all** is now decided by use rather than
by argument: `persist_ledger` is a workflow input, default on. Turning it off
returns to artifacts-only. The cost of leaving it off is written above.
