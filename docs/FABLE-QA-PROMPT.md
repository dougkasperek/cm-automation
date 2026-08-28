# Prompt: full QA, direction, and opportunity review

Copy everything below the line into a new session.

---

You are reviewing `cm-automation` as a senior engineer and a product thinker at
once. I want three things, and the third is the one I care most about.

1. **A codebase QA.** What is fragile, duplicated, untested, or wrong.
2. **A read on the direction.** Is this becoming the right thing?
3. **Missed opportunities.** We already collect data we do not use. Find it.

## What this system is

Read-only monitoring for 85 client WordPress sites across six hosting
providers, built by an agency (clevermethod) to replace a manual audit
spreadsheet. Five scanners write to an append-only ledger; a renderer produces
three static pages behind Cloudflare Access at `fleet.thudstaff.com`.

It has been built in about ten days, mostly in one long session per day, and it
shows in places. Nothing has ever been refactored.

## Read these first

- `CLAUDE.md` — the project's own rules and, more usefully, a table of roughly
  fifty bugs it has made. Read that table. It is the best single description of
  how this system fails.
- `docs/DATA-MODEL.md` — inventory, ledger, components. Three layers.
- `docs/SEVERITY.md` — how a site gets a status, and why "unknown" is never
  folded into yes or no.
- `docs/DO-THIS-NEXT.md` — the current backlog, including six items raised by
  the team on 2026-08-27.
- `docs/SESSION-HANDOFF.md`, "PICK UP HERE" — where things stand.

Then render the pages and look at them:

```bash
./scripts/render-dashboard.py --out /tmp/fleet.html \
    --components-out /tmp/components.html --consent-out /tmp/consent.html
```

And run everything, so you know the baseline is green before you judge it:

```bash
for t in test/test-*.py; do echo "== $t"; python3 "$t" | tail -1; done
node test/test-page.mjs | tail -1
./test/run-local-test.sh | tail -1
```

## Part 1 — codebase QA

Be specific and rank by consequence. Things worth looking hard at:

- **`scripts/render-dashboard.py` is ~3,500 lines** and does model-building,
  three page renders, a JSON feed, and CSS. It has never been split.
- **Five scanners, five shapes.** `pantheon-fleet-healthcheck.sh` and
  `nexcess-fleet-healthcheck.sh` are bash; the consent tools are Node; the
  Nexcess and email tools are Python. Each has its own error handling.
- **Test suites total ~1,000 assertions across 14 files** with a hand-rolled
  `check()` in each. No shared harness, no CI matrix for the browser tests.
- **`test/test-page.mjs` needs Chromium and is not in CI.** Run by hand.
- **The ledger is append-only and has no compaction.** 45 runs so far.
- Look for the failure modes CLAUDE.md's table describes, in code it has not
  yet caught. That table is a spec for what to grep for.

Say what you would fix first if you had a day, and what you would leave alone.

## Part 2 — direction

The system started as "is the fleet patched" and has grown a consent axis, an
email axis, a component catalogue, and an ownership model. Ask whether that is
coherent or accretion.

Specifically:

- **Is per-site status still the right primary object?** 53 of 85 sites read
  WARN, and most of that is one WordPress release and a plugin backlog. The
  page has a Schedule tab that arranges the same evidence by decision instead.
  Which one is the product?
- **Two axes today, health and consent.** Email findings score on neither and
  appear only as standing groups. Is that right, or is email a third axis?
- **The ledger records; severity scores at render time.** That split has paid
  off repeatedly. Is anything violating it?
- **Read-only is a hard boundary** and has been re-argued three times. Is it
  still the right line, and what would change if it moved?

## Part 3 — opportunity, and this is the important one

**We already collect data we do not use.** Find it, and say what it is worth.

Two kinds of answer are useful:

**(a) Signal already in the ledger that the pages never show.** Measured
2026-08-27:

| what we know | sites |
|---|---|
| trackers fire before consent, no consent tooling at all | 37 |
| OneTrust present that clevermethod does not manage | 22 |
| DMARC published but `p=none` — no enforcement | 49 |
| PHP 8.2, security support ends 2026-12-31 | 46 |
| plugin backlog of 10 or more | 27 |
| no health evidence of any kind | 11 |
| distinct components installed, 2,346 installs, 693 updates pending | 362 |

Each of those is a fact the system already holds. Some are on a page. Several
are one query away and on none.

**(b) Inventory fields that exist and are empty.** These were designed in and
never filled:

| field | recorded on |
|---|---|
| `client` | **0 of 85** |
| `owner` | **0 of 85** |
| `attestations` | 79 of 85, all imported from the workbook, none confirmed |
| `workbook_last_known` | 79 of 85, carried but no longer rendered |
| `decommission_candidate` | 2 of 85 |

An empty field designed in and never populated is a question nobody answered.
Say which ones are worth answering.

### Revenue and retention specifically

This is an agency. The fleet is client sites. Some clients pay for maintenance
and some do not, and the team cannot currently tell which from this tool.

Look for:

- **Work the data already justifies.** 46 sites need a PHP upgrade before
  December. 37 sites have no consent tooling. Those are scoped projects sitting
  in a JSON file.
- **Retention arguments.** What could this tool show a client that would make
  them glad they pay? What would it show a client who does not pay that would
  make them consider it? A senior dev on the team, Victoria Brake, raised
  exactly this on 2026-08-27 — see `docs/DO-THIS-NEXT.md` B1.
- **Risk the agency carries.** 22 sites run consent tooling clevermethod does
  not manage, on clients we do serve. Where else does the data show exposure
  nobody has priced?
- **Things that would be cheap and are not built.** A per-client view. A
  shareable read-only page. An export. A "what changed on your site this month"
  digest. Judge them; do not just list them.

## How to answer

- **Lead with the single most valuable thing you found**, then the rest.
- **Rank by value, not by category.** I would rather have five things worth
  doing than thirty observations.
- **Ground every claim in the data.** Query the ledger rather than assuming.
  This project's entire bug table is confident-looking values that nobody
  checked, and a review that adds to it is worse than none.
- **Say what you are unsure about.** "I do not know whether the team would use
  this" is a useful sentence.
- **Where you propose a feature, say what it costs** and what has to be true
  for it to work. Several good ideas here are blocked on data nobody has
  entered, not on code.

Do not implement anything. Do not push, publish, or deploy. This is a review.
