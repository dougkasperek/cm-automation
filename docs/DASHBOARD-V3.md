# The fleet page, since 2026-08-27: the evidence matrix

`scripts/render-dashboard.py --out fleet.html` now writes this page. The
previous eleven-section page is `render()` behind `--legacy-out`, kept for one
cycle as the fallback if this one is wrong in production. `docs/DASHBOARD-V2.md`
describes that page and still applies to it.

## Where it came from

Doug asked for a from-scratch redesign, built from the live data, as two or
three concepts that disagreed about the central problem: two thirds of the
fleet scored WARN and 41 of those 53 warnings were the same maintenance backlog
on every site, so the page was a wall of amber rows that told nobody where to
start. Three concepts were built and rendered from the real model
(`_scratch/redesign/`, with the review in `review.html` there):

| concept | stance | verdict |
|---|---|---|
| A, the queue | decisions are the primary object, sites live inside them | right about batching, loses the fleet as a picture |
| B, the evidence matrix | one row per site, one column per question, absence hatched | **chosen** |
| C, the client brief | one card per site, split by who has to act | fails: the inventory has no client or owner on any site |

The page is B with A's schedule column as a second tab. Doug chose it on
2026-08-27.

## What the page is

One row per site, one column per question. A cell shows what was measured and
how it scored. Two things about it are load-bearing:

**An absence is a shape, never a colour.** `null` (no source wrote the site),
`"unknown"` (the scan asked and got no answer) and `"n/a"` (the scan does not
ask on that host) each render as a hatched or dotted token with the absence
word in it. They are never a number and never green. A Nexcess site's backup
cell reads `no API`, because Nexcess exposes no backup API and unmeasurable is
a different fact from unmeasured. `test/test-page.mjs` asserts all of this on
the rendered DOM.

**Every column carries its own denominator.** The header says `48 of 52
Pantheon`, `68 of 75 inventoried`, `71 of 79 loaded`, read from the same
coverage lines the JSON feed publishes. A census bar under each header shows
how the whole fleet answers that question, hatched where nobody could.

Rows are grouped by **what happens next**, in a printed priority order: needs a
person, not established, needs scheduling, needs a ruling, nothing pending,
not measurable, excluded by ruling. This is a workflow view over the two axes
and it lives in `scripts/dashboard/page.js`, never in `severity.py`. The two
axis chips stay on every row, so the grouping can never replace the verdict.

**The banner.** The dev team asked for something at the top that says they
need not worry. The phrase they used was "all good", and on this fleet that
would be false for months: 41 sites carry a backlog and 11 have never had
health measured. So the banner is scoped, and its predicate is printed under
it in every state:

| state | when |
|---|---|
| Nothing needs a person | zero sites in the needs-a-person lane AND no coverage regression |
| N sites need a person | names them; everything else is a backlog, a ruling, or unmeasured |
| Can't say | coverage fell since the previous run, or a source did not run. Never green, never amber, and it still names who needs a person on what was measured |

The green sentence states the backlog and the unmeasured count in the same
breath. The page never contains the words "all good"; `test/test-page.py` and
`test/test-page.mjs` both assert it.

**The Schedule tab** is concept A's second column: the same backlog arranged
by the decision it needs rather than the site it sits on. A WordPress release
is one decision per target version. A plugin is one decision per component,
because every install of a component wants the same version (measured: 140
components with something pending, each with exactly one target). The top ten
components cover about half the 693 pending installs.

**The drawer** is everything recorded about one site: both axes with the
reason codes beside the reason text (grep `severity.py` for the code), every
fact family with its provenance in the heading, the pending component list,
the workbook attestations checked against the plugin inventory, and the
plugin-backlog series over the full health runs.

## The workbook is back on the page, as claims

The workbook's columns were removed on 2026-08-20 because they were displayed
as if they were evidence. This page shows the workbook's per-site attestations
(2FA, hidden login, activity log, XML-RPC) labelled as claims, beside whether
the component inventory can see a matching plugin. Four answers, kept four: a
claim of Yes with the plugin present, Yes with no plugin, No with a plugin
present anyway, No with none. Platform controls ("Yes - Pantheon") are not
checkable and say so. The column group is behind a toggle; the key defines the
word "workbook" once, because the dev team asked what it meant.

Doug chose to leave it in on 2026-08-27 ("lets leave it for now"). Removing it
is one column group and one panel.

## How it is built

The renderer decides WHAT is true; the page decides only how to group and
count it.

```
build_model(m)  ->  page_data(m)  ->  JSON, embedded in the file
                    scripts/dashboard/page.css   inlined
                    scripts/dashboard/page.js    inlined, renders the DOM
```

`page_data()` is built from the same `m` as `render()`, `render_components()`
and `emit_data()`, so the page and the feed cannot disagree; `test/test-page.py`
asserts every status, reason code and fact on the page is the feed's. The
page carries a superset of `EMIT_FACTS` (`PAGE_FACTS`): the email DNS family,
the measured sending domain, the inventory rulings, plus per-site attestations,
the pending component list and the history series.

The page is one file that fetches nothing. No web fonts (system stacks), no
CDN, no second request for data. It opens from `file://` and from behind Access.

`page.js` computes no status and holds no threshold. It reads
`D.severity_rules` for the one threshold it prints (the WordPress security
floor), and the test refuses a literal.

The Eastern offset is decided by the renderer (`eastern()`) and passed as
`tz_offset_minutes`, so DST has one home.

## What changed for the tests

`test/test-ledger.py` and `test/test-severity.py` each had a block that read
the committed `fleet.html` and matched the old markup (`<th>Sends from</th>`,
`whose backup age can be read at all`). Each is re-stated as the property it
protected, asserted against the embedded model and the page source. The
assertions on `RD.render()` itself still pass, because `render()` still exists;
they describe the legacy page and go when it does.

Two new suites:

- `test/test-page.py`, offline, 33 checks: one file with no network; the
  page's model is the feed's; absence survives into the record; attestation
  answers stay four; no threshold or status in the script; the banner's
  predicate is printed; never "all good".
- `test/test-page.mjs`, headless Chromium via the repo's playwright, 39 checks:
  one row per site; lane counts sum to the fleet; every row has one cell per
  header; every measured column states `N of M`; absence cells carry no status
  class and no number; chip counts equal the model's; the banner has exactly
  one state, and the green and can't-say branches are exercised on an edited
  copy of the file; the drawer opens and prints every reason code; the body
  does not scroll sideways at 375px.

`scripts/publish-dashboard.sh` runs `test/test-page.py` after rendering and
refuses to publish if it fails. The DOM test is not in the publish job yet:
it needs a Chromium download on the runner, which is a cost to decide on
rather than add silently. Run it by hand before a publish until then:

```bash
./scripts/render-dashboard.py --out fleet.html --components-out components.html
python3 test/test-page.py
node test/test-page.mjs
```

## Decisions reversed, and why

- **Static HTML with no client-side code.** The page is rendered in the
  browser from embedded JSON. The rule was protecting simplicity and
  self-containment, and both survive: one 620KB file, vanilla JS, no framework,
  no network. What it buys is the drawer, the filters and the tabs without a
  second page.
- **Two published pages.** `components.html` is still rendered and published,
  unchanged, and the schedule tab links to it. Nothing on the fleet page
  depends on it any more; retire it when the catalogue's own filters are
  folded into the drawer.
- **The eleven-section structure, the three bands, the tile row, the suite
  cards, the key as a section.** Gone. The findings they carried are in the
  matrix, the lanes, the banner and the drawer. Rendered side by side, the
  old page was 13,115px tall at 1100px wide with a quarter of its text
  explaining its own headline; this one is about 4,500px and the explanation
  is the key.

## Not done

- Retire `render()` and the tests that pin its markup after one published
  cycle.
- Put `test/test-page.mjs` in the publish job, once the Chromium cost is
  accepted.
- Staleness in the banner: green currently states the scan dates it rests on
  rather than judging them, because no cadence is defined. Once the crons are
  on, a source older than its cadence should flip the banner to can't-say.
- Which findings count as "needs a person" is my rule (health critical, a
  consent banner that leaks, no SPF), printed under the banner. The dev team
  may want health critical only. Either way it is one function, `lane()`.
