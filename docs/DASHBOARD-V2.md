# The fleet dashboard (ledger-backed)

**Superseded 2026-08-27.** `--out` now writes the evidence-matrix page described
in `docs/DASHBOARD-V3.md`. The page this file describes is `render()`, still
reachable with `--legacy-out` for one cycle. The data-side decisions below
(one model, severity at render time, the palette rules, the standing-group
bugs) still hold; the layout decisions do not.

`scripts/render-dashboard.py` reads the ledger and the inventory and writes one
self-contained HTML file. No build step, no CDN, no fonts fetched, no framework.
It opens from `file://` and deploys to a Worker unchanged.

```bash
./scripts/fleet-ledger.py ingest
./scripts/render-dashboard.py --out fleet.html
open fleet.html
```

## Why there are two renderers

| script | reads | job |
|---|---|---|
| `render-dashboard.py` | the ledger | the fleet view: history, both tools, 84 sites |
| `render-fleet-dashboard.py` | one in-progress scan file | the live "watch it fill in" demo |

They are not duplicates. The live view works precisely because the scan scripts
rewrite their JSON after every site, so a run is watchable as it happens. The
ledger only updates on ingest, after a run finishes. **Merge them only if the
live view is ever taught to read the ledger mid-scan**, which is not needed yet
and would trade a genuinely nice property for tidiness.

## What the page leads with, and why

**The hero number is the count of changes needing a decision**, not the number of
sites or of findings. Two health runs 14 hours apart differed by one integer
across 52 sites. A page that opens with 84 rows of mostly-unchanged state teaches
people to stop reading it.

Then, in order: the changes themselves, the standing findings **grouped by
cause**, coverage, sites that do not reconcile, and only then the full table.

`DRIFT`-class changes are counted but not listed. A counter ticking on an
already-open finding is not news.

## Deliberately not a chart

The counts are a handful of named classes, which the form heuristic calls a stat
tile and a table, not a bar chart. And with four runs in the ledger a trend line
would be points pretending to be a trend. The footer says so on the page rather
than leaving a suspicious empty space.

Charts arrive when there is history to justify them. That is a real threshold,
not a placeholder: roughly a month of daily runs.

## Colour

The project's validated status palette, re-checked 2026-08-18 with the dataviz
validator:

| mode | good | bad | info | surface | result |
|---|---|---|---|---|---|
| light | `#1baf7a` | `#eb6834` | `#2a78d6` | `#faf7f2` | all checks pass |
| dark | `#199e70` | `#d95926` | `#3987e5` | `#1a1a19` | all checks pass |

Dark mode is a **selected** set of steps validated against the dark surface, not
an automatic flip of the light one.

Two things to know before touching these:

- **The gray `#8d9199` fails the validator's chroma floor on purpose.** It is a
  deliberate neutral for "not applicable", not a categorical hue, so it is
  validated as a status colour rather than as part of the categorical set.
- **Light mode carries a contrast WARN** against the surface. That is
  dischargeable only by visible labels or a table view. This page is both:
  **every state chip carries its text label**, so colour is never the only
  signal. If you ever render a chip as a bare dot, that relief is gone and the
  palette no longer passes.

Do not swap these for brand colours without re-running
`validate_palette.js` **in another repo, not this one** (checked 2026-08-23: no such file here). That repo's own severity green and amber fail
colourblind separation at protan delta-E 3.8, and
`pantheon-fleet-health.html` in that repo still uses those failing tokens.

## Read-only, on purpose

Attestations, SSO and an audit trail come after this is in production. Nothing on
this page changes a site, so access control is entirely Cloudflare Access at the
edge and the app needs no auth of its own.

## A bug this caught

The first render showed **1** in the Sites column for the coverage and planning
rows, where the truth was 48 and 46. `standing()` was packing those groups as a
pre-formatted summary string, so the count was counting the string. Now `sites`
is always a real list of site ids and any per-site extra lives in `detail`.

Found by rendering the page and looking at it, which is the last step of the
dataviz procedure and the one most easily skipped.

### And a second, 2026-08-27

Two standing groups were added: a pending WordPress core update and a plugin
backlog: because the page had 52 amber rows and an action list that never
said why. `standing()` emitted twelve causes and neither of those was among
them, while 40 of the 52 WARN sites were WARN for exactly those two facts.

The groups rendered **twice**: `Plugin updates pending: 17 sites` and, three
rows down, `Plugin updates pending: 7 sites`. The truth is 24. The renderer
calls `standing()` once per COHORT and extends a flat list, so any cause that
both health cohorts can raise appears once per cohort with the fleet split
between them, and each action line quotes its own half as the total, which is
how one of them came to read `268 update(s) across 17 site(s)`.

The twelve existing groups never collided. That is luck, not design: upstream
commits, backup age and PHP version are facts only the Pantheon cohort
carries, so no group had ever been raisable by both. The first group that was
raisable by both duplicated immediately.

Standing is now unioned **per source** and scored once. Per source, not across
all sources: rows are keyed on site, and 46 sites carry both a health row and
an email row, so a flat union would have silently kept one of each pair and
dropped the other: a worse bug than the one being fixed, and a silent one. An
assert refuses to guess if two cohorts of one source ever do overlap.

`standing_was`, the baseline behind the "since the previous run" arrow, had the
same defect one layer down: it keyed on cause, so the second cohort's count
overwrote the first. A 24-site group whose baseline was also 24 would have
rendered `↑ 17 was 7`. It is accumulated per source too.

Found the same way as the first one: by rendering the page and reading the
rows.
