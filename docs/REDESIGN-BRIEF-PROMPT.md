# Prompt: complete dashboard redesign

Copy everything below the line into a new session.

---

You are a senior UI/UX designer. I want a **complete redesign** of the
`fleet.thudstaff.com` dashboard, not an improvement pass on what exists.

Start by understanding the system and the data. Then design what this data
should actually look like, from scratch.

## What this system is

`cm-automation` is read-only monitoring for 85 client WordPress sites across
six hosting providers. Four independent scanners write measurements into an
append-only ledger. A renderer reads the ledger and produces two static HTML
pages. Nothing in this system ever changes a client site. It only reports.

The dashboard replaced a manual audit spreadsheet. Its readers are the agency
team who maintain these sites and the account people who talk to the clients
about them.

## Read these first, in this order

**The system:**
- `CLAUDE.md`: project overview. Read it for what the system *is* and what the
  data *means*. See the section below about which parts to treat as binding.
- `docs/DATA-MODEL.md`: the three-layer model: inventory, ledger, components.
  This one matters most. Get this right or the design will misrepresent things.
- `docs/SEVERITY.md`. How a site gets a status, what the axes are, and why
  "unknown" is deliberately never folded into a yes or a no.

**The current implementation:**
- `scripts/render-dashboard.py`: 3,092 lines, the renderer that produces both
  pages. This is what you are replacing.
- `fleet.html`: 174KB, 11 sections, the current main page.
- `components.html`: 605KB, the plugin/theme catalogue.

**The data itself. Read the actual records, not just the schema:**
- `data/fleet-inventory.json`: 85 sites, hand-maintained, holds ownership,
  the production flag, and the workbook's historical claims.
- `history/observations.jsonl`: 2,340 rows, one per tool per site per run,
  43 runs.
- `history/components.jsonl`: 11,178 rows, one per installed plugin,
  mu-plugin and theme per site.
- `history/runs.jsonl`: run metadata.

**Prior design thinking, as context and not as instruction:**
- `docs/DASHBOARD-V2.md`, `docs/DESIGN-BRIEF.md`, `docs/DESIGN-REVISIT.md`,
  `docs/clevermethod-fleet-ui-improvement-direction.md`

Render the current pages and look at them before you design anything:

```bash
./scripts/render-dashboard.py --out /tmp/current.html --components-out /tmp/current-components.html
```

## What the data actually contains

Four sources, each answering a different question:

| source | what it measures | reach |
|---|---|---|
| `health` | backups, PHP, WordPress core/plugin/theme versions | 52 Pantheon + 22 Nexcess, two transports |
| `email-dns` | SPF, DKIM, DMARC, sending domain alignment | 78 domains, no credentials |
| `consent` | cookie banners and trackers firing before consent | 78 domains, real headed browser |
| `nexcess` | provider control-plane inventory | 22 sites |

Two independent scoring axes, so a site has a status on each:
- **health**. Is this site being maintained (14 severity codes)
- **consent**: does it leak trackers before consent (2 codes)

Six states: `CRIT`, `WARN`, `OK`, `UNKNOWN`, `SKIP`, `FROZEN`.

Findings are also grouped by cause into four kinds: `RISK`, `COVERAGE`,
`PLANNING`, `DRIFT`.

There is more in the ledger than the current page shows. Look for what is
being measured and never surfaced, and for what is surfaced that nobody needs.
A redesign that only rearranges the existing 11 sections has not used the data.

## You are not bound by what is recorded in this project

Every UI decision in this repo was made incrementally, under time pressure,
usually in response to a specific complaint. The result is a page that grew
rather than one that was designed. **Treat all of it as disposable:**

- The 11-section structure and the order of those sections
- The three-band Summary / Detail / Complete inventory framing
- The tile row, the "Top issues" table, the card-per-axis "suite" block
- The typography, the palette, the square-cornered chip system, the light-only
  theme
- Every heading, every explanatory paragraph, every fold
- The decision to publish two separate pages
- The decision to render static HTML with no client-side framework
- Any rule in `CLAUDE.md` or `docs/` that constrains layout, wording,
  interaction, or visual style

If a prior decision was right, you will arrive at it yourself. Do not preserve
anything because the repo says so. Where you deliberately reverse a recorded
decision, say which one and why: briefly, once, not as an apology.

## What you should not do

One thing is not a style constraint, and it is the reason this system exists.

This project's entire failure history is **a confident-looking value standing
in for an absence**: a plugin count of 0 when nobody looked; "no SPF record"
when the DNS lookup timed out; 23 sites reported clean when the scanner got
403 block pages. `CLAUDE.md` has a table of about forty of these.

So: design freely, but do not let the page assert something the data does not
support. Specifically,

- An unmeasured value must never render as a good one. Absence needs a visual
  treatment that cannot be mistaken for a measurement.
- A count needs its denominator when the denominator is not the whole fleet.
- The scanner losing sight of a site is not the same event as a site getting
  worse, and must not look like it.
- Do not invent a number, a label, or a per-site reason that is not in the
  data. If a record does not say why, the page says nobody has established why.

That is a data-accuracy requirement, not a design limitation. How you express
it visually is entirely yours, and the current treatment is not a good answer,
it is mostly prose paragraphs apologising for the numbers above them.

## Get the real data first

Before designing, export the live model. This is the same object the current
renderer draws from, so anything in it is fair game:

```bash
./scripts/render-dashboard.py --out /tmp/current.html --emit-data /tmp/fleet-data.json
```

That gives you a 178KB JSON file containing:

| key | what it is |
|---|---|
| `sites` | all 85, each with `status`, per-axis `axes`, `reasons` with codes and text, and the raw measured facts |
| `standing` | 17 findings grouped by cause, each with `axis`, `sites`, `action` |
| `changes` | 24 changes since the previous run of each tool, classified |
| `coverage` | 10 coverage lines: what was measured, out of what |
| `health` | fleet counts per state, per axis |
| `severity_rules` | the thresholds, so the page can explain itself |
| `no_health_evidence` | the 11 sites nothing has established health for |

Component data is separate and not in that export. Read
`history/components.jsonl` directly (11,178 rows, 362 distinct components
across 68 sites).

**Use this data. Not mock data.** A layout that has never met 85 real rows,
53 amber ones and a 362-component catalogue has not been tested. Embed the
JSON in your artifact so it is self-contained.

## What I want back

**Two or three rendered concepts, as artifacts I can open and click.** Not one
proposal, and not fragments. Each concept should be a complete, working page
built from the real data.

Give me genuinely different directions, not three coats of paint on one
layout. Each should take a **different stance on the central problem** (see
below). I want to compare approaches, so make them actually differ in
structure, hierarchy and what they choose to lead with. If a direction turns
out to be wrong once you build it, say so and show it anyway: a concept that
fails for a clear reason is useful.

Alongside the concepts:

1. **A short critique of the current dashboard.** What is structurally wrong,
   not a list of nitpicks. Lead with the single biggest problem.
2. **A design rationale per concept**. Who it serves, what it puts in the
   first five seconds, what it defers, and what it deliberately gives up.
3. **A recommendation.** Which one you would ship and why.

Do not ask me to approve a plan before you build something I can look at. Show
me the concepts, then we will talk.

**Do not modify the renderer, and do not touch the repo's committed files.**
Choosing a direction comes first; implementation comes after. Work in artifacts
and scratch files. Do not push and do not publish.

## The central problem

The fleet currently scores **2 CRIT, 53 WARN, 25 OK, 3 SKIP, 1 FROZEN.**

Two thirds of it is amber, and 40 of those 53 warnings are a pending WordPress
update or a plugin backlog: real maintenance work, no emergency, largely the
same on every site. The current page renders that as 53 near-identical warning
rows, which tells a reader nothing about where to start.

A redesign that produces a prettier wall of 53 amber rows has not solved
anything. This is the most interesting problem here and I want the concepts to
disagree with each other about how to handle it. Some directions worth someone
taking: batch by the decision required rather than by site; separate "needs a
person" from "needs scheduling"; rank by client exposure rather than by
severity; or argue that per-site status is the wrong primary object entirely.

## Checking your own work

- Open every concept and look at it. Most defects in this project's history
  were found by a person looking at a rendered page, not by a test.
- Check at 1100px and at 375px.
- Artifacts must be self-contained: no CDN scripts, no external stylesheets,
  no remote fonts or images. Inline everything, embed the data.
- Confirm your numbers against the export rather than typing them in. If a
  concept says "53 sites need attention", that figure should come from the
  data it rendered.

One thing to know for later, not now: `test/test-ledger.py` has 316 assertions
and many of them pin the current markup, so whichever concept gets built for
real **will fail a lot of them**. That is expected. When we get there, each
failure needs a decision about whether it was protecting a real property or
just describing the old layout. Nothing to do about it at the concept stage.
