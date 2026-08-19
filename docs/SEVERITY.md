# Severity: how CRIT, WARN and OK are decided

**Built 2026-08-19.** Replaces the flat rule set that lived inside
`pantheon-fleet-healthcheck.sh`. Read this before changing a threshold, adding
a rule, or explaining a number on the dashboard to anyone.

---

## The problem it replaced

The first full-fleet full-mode scan, 52 sites, scored under the old model:

```
33 CRIT / 15 WARN / 3 SKIP / 1 FROZEN / 0 healthy
```

**Nothing was OK, and 63% of the fleet was CRIT.** A model that cannot rank
anything cannot be used to decide what to look at first.

Two rules produced almost all of it:

| rule | why it broke |
|---|---|
| `upstream_pending > 0 -> WARN` | Every site carries 1 or 2 pending Pantheon upstream commits. Zero sites have none. One rule on a fact that is never zero put a WARN floor under the entire fleet. |
| `core update available -> CRIT` | 32 sites were on 7.0.3 with 7.0.4 pending: one minor behind, above the `wp2shell` fix. That single rule made 32 of the 33 CRITs. |

### And it missed the one site that mattered

`cm-whitelabel` runs WordPress **6.9.4**, below the `wp2shell` fix. Its
`wp_core_update` reads **`up-to-date`**, so the core-update rule did not fire on
it. It scored CRIT only because its last backup was 2,147 days old. **Had it
been backed up yesterday it would have scored OK.**

Nothing in the old model ever read the version a site was ACTUALLY ON. That is
the rule this rebuild exists to add.

---

## Where scoring lives now

`scripts/lib/severity.py`. **Nothing computes severity anywhere else.**

It is a pure function of observed facts plus the inventory's `production`
flag, and it runs at RENDER time, not at scan time. `fleet-ledger.py` and
`render-dashboard.py` both call it; neither reads the `derived_status` the
scanner stored.

That is what makes thresholds safe to change. Retuning a constant rescores
every run in history identically, so a rules change produces no diff at all
rather than reporting all 52 sites as changed with nothing observed behind it.
This closes the *version-stamping the tool per run* item that had been open
since the ledger was built.

**The scanner still stamps its own status** for the markdown digest it prints
and for its exit code. Nothing downstream trusts it. See *Known divergence*
below.

---

## The rules

### CRIT: act now

| rule | constant | why |
|---|---|---|
| installed WordPress below the security floor | `WP_SECURITY_FLOOR = (7, 0, 2)` | The `wp2shell` unauthenticated RCE fix. Reads `wp_version`, the version the site is ON, **not** whether an update is pending. This is the rule the old model did not have. |
| PHP past its end-of-support date | `PHP_SECURITY_EOL` | A dated table, not a floor. See below. |
| no database backup in over 30 days | `BACKUP_CRIT_DAYS = 30` | Beyond a month, restore stops being a real option. |

### WARN: schedule it

| rule | constant |
|---|---|
| a WordPress core update is pending | — |
| 10 or more plugin updates pending | `PLUGIN_WARN_COUNT = 10` |
| last backup 8 to 30 days old | `BACKUP_WARN_DAYS = 7` |
| deep scan ran but the version could not be read | — |

### Informational: recorded, displayed, never scored

- **Pending Pantheon upstream commits.** Universal, so it ranks nothing.
- **Theme updates.**
- **Fewer than 10 plugin updates.**
- **PHP inside 180 days of its EOL date.** 46 of 52 sites are on 8.2, which
  ends 2026-12-31. Scoring a shared fleet-wide deadline per-site is exactly the
  `upstream_pending` mistake. It belongs in the standing findings as a PLANNING
  item, and that is where the ledger already puts it.

### Non-states

`FROZEN`, `SKIP` (the health scan reached the site, there is no environment to
measure) and `UNKNOWN` (**no health scan has ever reached this site** — all 32
Nexcess and outlier-host sites today).

---

## Two rules that are not thresholds

### Unknown is never OK

Every rule tests for a known bad value. A fact that is absent, `None`, or the
token `"unknown"` fires **nothing**. A site nobody could measure must not reach
OK by having no evidence against it.

Before adding a rule, ask what it does when the answer is unknown, and whether
a reader could take the result to mean the opposite.

### PHP is a dated table, not a floor

`PHP_MIN_SUPPORTED = (8, 0)` survived about an hour. Rendering the page exposed
it: *Still true* reported one site past PHP end-of-support while severity scored
that same site fine, because 8.1 ended **2025-12-31** and a static floor cannot
know that. `runtalnorthamerica.com` is CRIT because of this, and both the old
model and the first draft of the new one missed it.

`PHP_SECURITY_EOL` now lives in `severity.py` and `fleet-ledger.py` reads it
from there. A version absent from the table is `unknown`, never *supported*.

---

## The `production` flag

Tri-state, in `data/fleet-inventory.json`, set by a human:

| value | meaning |
|---|---|
| `true` | reviewed, counts toward fleet numbers |
| `null` | **nobody has looked. Counts. Fail safe.** |
| `false` | reviewed and ruled out of scope. Scored and displayed, not counted. |

`null` scoring as production is deliberate. Defaulting unreviewed sites *out*
of the numbers means a site stops being watched because nobody classified it.

**Do not infer this from the Pantheon plan.** Keying off `plan == "Sandbox"`
would have excluded `hoffmanscheese` — 721 days without a backup, and one of
only two real CRITs in the fleet. Plan is a billing attribute.

Today exactly one site is `false`: `cm-whitelabel`, ruled a temp non-public
site by Doug on 2026-08-19.

### The review queue

`needs_review()` is **not** `production is None` — that is all 84 sites, and a
queue containing everything gets ignored.

A site in the manual audit workbook has been through a human pass already.
The queue is sites with **no `production` ruling AND no workbook row**: five
today, all on the Sandbox plan. On this fleet that set has included the two
worst-maintained sites, which is the argument for surfacing it at all.

---

## What the numbers are now

The same run, rescored:

```
2 CRIT / 32 WARN / 13 OK / 32 UNKNOWN / 3 SKIP / 1 FROZEN
(1 excluded: cm-whitelabel, itself CRIT)
```

- **CRIT:** `hoffmanscheese` (721-day backup gap), `runtalnorthamerica.com`
  (PHP 8.1, unpatched since 2025-12-31)
- **WARN:** mostly the 7.0.4 core-update backlog
- **UNKNOWN:** the 32 sites no health scan has reached. Nexcess plus the four
  outlier hosts. This is the coverage gap, stated as a number.

---

## Known divergence, unresolved

**The scanner and the dashboard now disagree.** `pantheon-fleet-healthcheck.sh`
still scores with its own inline rules, so its markdown digest calls a pending
core update CRIT while the dashboard calls it WARN. Its exit code 2 also still
gates CI on that old definition.

Fixing it means giving `severity.py` a CLI mode the shell script shells out to,
and it **changes CI failure behaviour** — under the new model a pending core
update would stop failing the build. That is probably correct and it is not a
call to make silently. Left for a decision.

---

## Tests

`test/test-severity.py`, 53 checks. Every regression above is asserted by name:

- 6.9.4 with `wp_core_update: up-to-date` must be CRIT
- `upstream_pending: 2` and nothing else wrong must be OK
- a pending core update must be WARN, not CRIT
- PHP 8.1 must be CRIT, PHP 8.2 must not be
- `php_support` must not fail open when `today` is omitted
- unknown must never fold into OK, in any of its forms

The ledger assertions run against the **committed** ledger in `history/`,
pinned to a **named** run. Never against `reports/`, which is gitignored, and
never positionally — see the note in `test/test-ledger.py` about cohort runs.


---

## Nexcess control-plane rules, added 2026-08-19

The Nexcess adapter answers PHP and WordPress version from the hosting control
plane rather than from WP-CLI. Those readings are stored under their own fact
names (`nexcess_php_version`, `nexcess_app_version`) and scored by four rules.

**`wp_below_floor` from `nexcess_app_version`** — CRIT, and only when no WP-CLI
reading exists. Scoring CRIT on control-plane evidence is deliberate. Below the
wp2shell floor is the highest-value finding this project has, the remediation
column is blank for all 21 Nexcess sites, and being wrong in this direction
produces a site to go and check. Being wrong in the other direction produces a
green row over an unauthenticated RCE.

**`php_eol` from `nexcess_php_version`** — CRIT. Same `PHP_SECURITY_EOL` table,
same function. Used only when the health scan has no PHP version, never merged
with it.

**`nexcess_app_version_unknown`** — WARN. The API answered for the site but said
nothing about the application. Without this rule such a site scores on PHP
alone and can reach OK, which prints green over a site whose wp2shell status is
exactly as unknown as it was before the scan ran.

**`coverage_partial`** — WARN. Control-plane discovery gives no backup age, no
plugin count and no theme count, and those are the facts that make a Pantheon
OK mean anything. So a Nexcess site cannot reach OK on discovery evidence. The
rule is conditioned on the site having Nexcess facts and NO health facts, so it
retires itself the moment an SSH scan supplies them.

**`wp_version_disagreement`** — WARN. WP-CLI and the control plane reporting
different versions is a finding, not a tie to break. The WP-CLI reading is what
scores, so a stale control-plane number cannot manufacture a CRIT.

`nexcess_state` is recorded and scores nothing. Its value set has never been
observed from this codebase — "stable" is the only value the vendor docs show —
and a rule written against a guessed enum either never fires or fires on
everything. Write the rule after a live run shows what the field contains.
