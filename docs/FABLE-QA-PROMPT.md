# Prompt: full QA, direction, and opportunity review

Copy everything below the line into a new session.

**Revised 2026-08-27.** The first version handed the reviewer its own answers:
Part 3 asked "find the data we collect and do not use" and then listed twelve
things we collect and do not use. A reviewer anchors on a list like that and
grades it. The thirteenth item, the one nobody has noticed, is the whole point
of asking. Those tables are now an appendix the reviewer meets AFTER forming a
view, and every fact in them survived the move.

---

You are reviewing `cm-automation` as a senior engineer and a product thinker at
once. Three parts, and **Part 1 is the one I care most about**. It is first
for that reason, not because it is easiest.

## What this system is

Read-only monitoring for 85 client WordPress sites across six hosting
providers, built by an agency (clevermethod) to replace a manual audit
spreadsheet. Five scanners write to an append-only ledger; a renderer produces
three static pages behind Cloudflare Access at `fleet.thudstaff.com`.

It has been built in about ten days, mostly in one long session per day, and it
shows in places. Nothing has ever been refactored.

## Read these first

- `CLAUDE.md`: the project's own rules and, more usefully, a table of roughly
  fifty bugs it has made. Read that table. It is the best single description of
  how this system fails.
- `docs/DATA-MODEL.md`: inventory, ledger, components. Three layers.
- `docs/SEVERITY.md`: how a site gets a status, and why "unknown" is never
  folded into yes or no.
- `docs/DO-THIS-NEXT.md`: the current backlog, including six items raised by
  the team on 2026-08-27.
- `docs/SESSION-HANDOFF.md`, "PICK UP HERE": where things stand.

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

**Do not read Appendix A until you have finished Part 1.** It lists what we
already know we are sitting on. Reading it first turns a review into a
marking exercise, and what you find that is NOT in it is the reason for
this review.

---

## Part 1: opportunity. The important one.

**This system already collects data it does not use.** Find it, and say what
it is worth.

This is an agency. The fleet is client sites. Some clients pay for maintenance
and some do not, and the team cannot currently tell which from this tool.

Go and look. Query the ledger, read the inventory, open the pages. Then answer:

- **What is measured and shown nowhere?** Facts sitting in
  `history/observations.jsonl` and `history/components.jsonl` that no page
  renders and no rule scores.
- **What is designed and empty?** Fields that exist in
  `data/fleet-inventory.json` on every row and were never filled in. An empty
  field somebody designed in is a question nobody answered; say which are
  worth answering and which should be deleted.
- **What work does the data already justify?** Scoped projects sitting in a
  JSON file, where the evidence for the pitch is already measured.
- **What would make a paying client glad they pay**, and what would make a
  non-paying client consider it? A senior dev on the team, Victoria Brake,
  raised exactly this on 2026-08-27. See `docs/DO-THIS-NEXT.md` B1.
- **Where does the data show risk the agency carries and has not priced?**
- **What would be cheap and is not built?** A per-client view. A shareable
  read-only page. An export. A "what changed on your site this month" digest.
  Judge them; do not just list them.

Then read Appendix A and tell me what you found that is not in it. That
difference is the most useful output of this whole review.

## Part 2: direction

The system started as "is the fleet patched" and has grown a consent axis, an
email axis, a component catalogue, and an ownership model. Ask whether that is
coherent or accretion.

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

**If the honest answer to any of this is that something should be deleted or
stopped, say that.** A review that can only recommend building more is not a
review. Parts of this were built in a day and have never been questioned by
anyone who was not present when they were written.

## Part 3: codebase QA

Be specific and rank by consequence. What is fragile, duplicated, untested, or
wrong.

Form your own view before reading the next paragraph, which is what WE think
is worst and may be wrong.

> `scripts/render-dashboard.py` is around 3,500 lines and does model-building,
> three page renders, a JSON feed and CSS. Five scanners have five shapes: two
> bash, two Python, one Node, each with its own error handling. Test suites
> total roughly 1,000 assertions across 14 files, every one with its own
> hand-rolled `check()`. `test/test-page.mjs` needs Chromium and is not in CI.
> The ledger is append-only with no compaction, 45 runs so far.

Tell us where that self-assessment is wrong, not only where it is right.

The bug table in `CLAUDE.md` is a spec for what to grep for: it describes about
fifty ways this system has produced a confident-looking value that was not
true. Look for the same shapes in code it has not yet caught.

Say what you would fix first if you had a day, and what you would leave alone.

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

---

## Appendix A: what we already know

**Read this only after Part 1.** It exists so the review is not spent
rediscovering things, and so you can tell us what we have missed rather than
confirming what we have not.

### Signal in the ledger, measured 2026-08-27

| what we know | sites |
|---|---|
| trackers fire before consent, no consent tooling at all | 37 |
| OneTrust present that clevermethod does not manage | 22 |
| DMARC published but `p=none`, so no enforcement | 49 |
| PHP 8.2, security support ends 2026-12-31 | 46 |
| plugin backlog of 10 or more | 27 |
| no health evidence of any kind | 11 |
| distinct components installed, 2,346 installs, 693 updates pending | 362 |

Some of those are on a page. Several are one query away and on none.

### Inventory fields designed in and never filled

| field | recorded on |
|---|---|
| `client` | **0 of 85** |
| `owner` | **0 of 85** |
| `attestations` | 79 of 85, all imported from the workbook, none confirmed |
| `workbook_last_known` | 79 of 85, carried but no longer rendered |
| `decommission_candidate` | 2 of 85 |

### Already argued, so do not re-derive

- 46 sites need a PHP upgrade before December 2026.
- 37 sites have no consent tooling at all.
- 22 sites run consent tooling clevermethod does not manage, on clients we do
  serve.

These are known. What is not known is what they are worth, who would pay for
the work, and what the tool should do about them, which is Part 1.
