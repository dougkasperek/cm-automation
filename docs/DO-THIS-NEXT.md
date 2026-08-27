# What to do next, step by step

Written to be followed in order in the Terminal on your Mac. Each step says what
you should see, so you can tell whether it worked before moving on.

Total time is about 20 minutes.

---

## Part 1. Move the folder out of iCloud

**Why:** the project currently lives in iCloud Drive. iCloud tries to sync the
hidden `.git` folder that git creates, and that corrupts repositories. It does
not fail immediately, it fails later, usually at a bad moment. So the folder has
to move before git ever touches it.

### Step 1. Open Terminal and make the destination

```bash
mkdir -p ~/dev
```

Nothing prints. That is normal.

### Step 2. Copy the project over

```bash
cp -R "$HOME/Library/Mobile Documents/com~apple~CloudDocs/DATA/clevermethod/DK Sandbox/claude/Cowork Automation Portfolio/cm-automation" ~/dev/cm-automation
```

This copies rather than moves, so the original stays put as a safety net. Delete
the original later, once you are confident everything works from the new home.

### Step 3. Go there and look around

```bash
cd ~/dev/cm-automation
ls
```

**You should see:** `README.md  ci  data  docs  history  reports  requirements.txt  scripts  test`
plus the two HTML dashboards.

If `ls` comes back empty or the folder does not exist, the copy path was wrong.
Stop and check the path before continuing.

---

## Part 2. Get it running from the new location

### Step 4. Install the one dependency

```bash
pip3 install -r requirements.txt
```

This installs `dnspython`, which the email checker needs. Everything else in the
project uses only what Python ships with.

**You should see:** either "Successfully installed dnspython-2.x" or
"Requirement already satisfied".

If you get a permissions error, add `--user` on the end.

### Step 5. Run the two test suites

```bash
python3 test/test-ledger.py
python3 test/test-email-dns.py
```

**You should see:** `43 passed, 0 failed` and then `45 passed, 0 failed`.

These are the proof that the move did not break anything. Neither test touches
the network, so they work offline and give the same answer every time.

If either reports failures, stop here and send me the output. Do not commit a
broken state.

### Step 6. Run the real email check once

```bash
python3 scripts/fleet-email-dns.py check \
  --inventory data/fleet-email-inventory.json \
  --out reports \
  --stamp "$(date -u +%Y-%m-%d_%H%M)"
```

**You should see:** progress counting up to 78, then a line like
`78 sites, 960 unique DNS queries, 780 cache hits -> reports/fleet-email-dns-....json`

Takes about 25 seconds. This confirms your Mac can do the real work, not just
pass tests.

### Step 7. Read the findings

```bash
python3 scripts/fleet-email-dns.py report --scan reports/fleet-email-dns-*.json
```

**You should see:** the findings summary, starting with the 10 sites where the
clevermethod Mailgun setup is incomplete.

---

## Part 3. Put it on GitHub

### ~~Step 8. Move the workflow files where GitHub expects them~~ DONE

**Skip this step. It was completed on 2026-08-22 and the commands below would
now fail.** `ci/github-actions/` no longer exists; all five workflow files live
in `.github/workflows/`, which is the only copy and is edited directly. See the
hard boundary in `CLAUDE.md` — do not recreate a mirror.

The original step said the files were "parked in `ci/github-actions/` because
the Claude file bridge is not allowed to write into `.github/`". That
restriction is gone. Kept here rather than deleted because this file is a
numbered runbook and removing a step would renumber the rest.

To confirm it is already done:

```bash
ls .github/workflows/
```

**You should see:** `_publish-dashboard.yml`, `fleet-consent.yml`,
`fleet-email-dns.yml`, `fleet-nexcess.yml`, `pantheon-fleet-healthcheck.yml`.

**You should see:** `fleet-email-dns.yml` and `pantheon-fleet-healthcheck.yml`.

If you get "Directory not empty" on the `rmdir`, something else is in there.
Look before deleting.

### Step 9. Start the repository

```bash
git init -b main
git add -A
git status
```

**Stop and actually read the `git status` output.** Two things to confirm:

- `history/observations.jsonl` **is** in the list. That file is the running
  record of what your fleet has looked like over time, and it is the one thing
  here that cannot be recreated by re-running something. It must be committed.
- Nothing under `reports/` is in the list. Those are raw scan outputs, they get
  regenerated every run, and GitHub keeps copies as build artifacts anyway.

If `history/observations.jsonl` is missing from the list, tell me before going
further. The ignore rules would be wrong.

### Step 10. Make the first commit

```bash
git commit -m "Initial import: fleet health scan, ledger, email DNS check"
```

**You should see:** a summary line with the number of files changed.

### Step 11. Create the repository on GitHub

Go to https://github.com/new and fill in:

- **Owner:** dougkasperek
- **Repository name:** cm-automation
- **Visibility:** Private. This matters. The project contains security posture
  data for 78 client sites.
- **Do not** tick "Add a README", "Add .gitignore" or "Choose a license". The
  repository must be completely empty or the next step will conflict.

Click "Create repository".

### Step 12. Connect and push

GitHub will show you a page of setup commands. Ignore them and use these:

```bash
git remote add origin https://github.com/dougkasperek/cm-automation.git
git push -u origin main
```

**You should see:** upload progress, then "branch 'main' set up to track
'origin/main'".

If it asks for a password, GitHub does not accept your account password here.
Either use the GitHub Desktop app to push, or create a personal access token at
https://github.com/settings/tokens and paste that in as the password.

Refresh the repository page in your browser. Your files should be there.

---

## Part 4. First run in GitHub Actions

### Step 13. Run the email check in the cloud

On the repository page, click the **Actions** tab.

The first time, GitHub shows a "Workflows aren't being run on this forked
repository" or a green "I understand my workflows, go ahead and enable them"
button. Click through it if you see it.

In the left sidebar, click **Fleet Email DNS Check**, then the **Run workflow**
button on the right, then the green **Run workflow** in the dropdown.

**Why this one first:** it needs no password, token or key of any kind. So if it
goes red, the problem can only be GitHub itself, the network or the workflow
file. It cannot be a credentials problem. That makes it a clean test of whether
CI works at all, before anything with secrets is involved.

Wait about a minute, then click into the run.

**You should see:** a green tick, and a summary panel on the run page showing the
same findings you saw in Step 7, plus a collapsible section showing the rule
agreement percentages.

### Step 14. Only after that is green, add the Pantheon token

Go to the repository, then **Settings**, then **Secrets and variables**, then
**Actions**, then **New repository secret**.

- **Name:** `PANTHEON_MACHINE_TOKEN`
- **Secret:** your Pantheon machine token

Then Actions, **Pantheon Fleet Health Check**, **Run workflow**, and set:

- run_mode: `api-only`
- target_env: `live`
- sites: leave blank
- fail_on_crit: `false`

**Why these settings:** api-only needs no SSH key, and fail_on_crit false means
nothing can turn the build red on purpose. So a red run genuinely means something
is broken rather than something being reported.

Compare the results against the scans already in `reports/` on your Mac. They
should agree. If they do not, that disagreement is the finding, and it is worth
chasing before trusting either one.

---

## What is left after this

Three things need a person rather than code, and none of them wait on any of the
above:

1. **The 21 Nexcess sites with no wp2shell verification.** One month after a
   critical WordPress vulnerability, the remediation record is blank for every
   Nexcess site. Someone should confirm they are clean and write it down.
   *(2026-08-24: the SSH deep scan that would answer this automatically is no
   longer gated — Nexcess confirmed one account-level key reaches all 21 sites.
   It still has to be built, so this stays a human task for now. See
   `docs/NEXCESS.md`, "Phase 2: the gate is open".)*
2. **hoffmanscheese and hoosierfeeder.com.** One is on Pantheon but in nobody's
   audit. The other is in the audit but Pantheon does not return it. Both are
   five-minute answers from whoever knows the fleet.
3. **shuman-plastics.com and dynapurge.com** on Flywheel are running PHP 7.4,
   which stopped receiving security patches in November 2022. That is a client
   conversation, since the hosting is theirs.

And one decision for when you are ready: should the GitHub job save its results
back into the repository, so the history builds up automatically? Right now it
does not, because a brand new automated job should not have permission to write
to its own repository until you have watched it behave for a while.

---

## Backlog: maintaining the rulings

**Logged 2026-08-24. Nothing built. Doug asked for the thinking to be recorded
rather than acted on.**

A ruling is the half of the data model a person decides rather than a tool
measures: which sites exist, who hosts them, and whether a site counts as
production. It lives in `data/fleet-inventory.json`. The question raised was
whether to build a way to maintain rulings, or edit that file, from a UI.

### The finding that should shape the answer

**83 of the 84 sites are `production: null`. Exactly one ruling has ever been
recorded**, `cm-whitelabel` as `false`. No site has ever been explicitly marked
`true`. Measured 2026-08-24 by reading the inventory, not inferred.

`render-dashboard.py` already knew, in a comment at the review-queue block:
"Deliberately NOT every site whose `production` is null, which is all 84 and
would be ignored." That was written as a display decision. Read as a fact about
the fleet, it says the ruling concept is unused.

~~Note the CLI line under it prints "%d site(s) need a production ruling" for
the narrow set of five that have no ownership record AND no ruling. **83 need
one.**~~ **FIXED 2026-08-26.** It now prints both, and says which is which:
the five with no owner and no ruling, then "83 of 85 site(s) have no
production ruling at all". The on-page copy was always accurate; the CLI line
was the project's signature shape, a narrow set described in broad words.

### Recommendation: do the pass, do not build the editor

"A way to edit the JSON master" assumes the bottleneck is editing. The evidence
says it is not: nobody has been blocked from editing that file, the work simply
has not been done. Building an editor for an activity performed once in the
project's life commits us to auth, a write path and provenance plumbing to
serve unproven demand.

The fair counter, which cannot be ruled out from the data: nobody ruled
*because* it means opening JSON in a git repo, so only Doug can do it. That is
testable cheaply. Do the pass once and see whether a queue actually forms.

The shape of the work also argues against an app. Most of the null list are
obvious client sites where `production: true` needs no judgment. Five to ten
look genuinely non-production from their names alone:
`live-frontline-construction.pantheonsite.io`, `clevermethod-forward`,
`pfannenbergsales`, `hoffmanscheese`, and the `moorseville-nc` /
`nc-moorseville` pair. So it is one bulk pass with a handful of real decisions,
then a few per year as sites are added or retired.

### In order, when it is picked up

1. **Run the ruling pass once.** Generate a pre-filled worksheet of all 84 with
   host, status and current evidence; a person marks it up; apply the result in
   one commit. This has to happen under every option, so it is the only step
   that is unconditionally worth doing.
2. **A small CLI to apply rulings safely.** `fleet-ruling.py set <site>
   --production false --why "..."`: validate the site exists, refuse unknown
   keys, write canonically formatted JSON so diffs stay readable, put the reason
   in the commit. Roughly a hundred lines, and worth having either way because
   it removes hand-editing JSON and hoping.
3. **Put the real number on the page.** 83 of 84 sites have no production
   ruling. That is a coverage number of the same kind as the health-coverage
   scoreboard and belongs beside it. One line, never a per-site flag: a fact
   true of every site ranks nothing.
4. **Only if non-technical people must rule, build a proposal flow, not an
   editor.** A form that PROPOSES a ruling and routes it, with a person
   applying it.

### Why a proposal flow rather than a direct editor, if it comes to that

- **Provenance is free.** A commit or a task records who ruled, when and why. A
  live-store edit loses all three unless we rebuild them.
- **It would mean putting a write route back into the Worker.** `PUT
  /api/publish/` was deliberately removed, and an audit found it still deployed
  a day later with `PUBLISH_TOKEN` still set. Re-opening a write path on the
  same hostname as the read-only dashboard is the riskiest item here, and
  "editing `ci/cloudflare/` does not change what is running" means trusting a
  deploy nobody can verify from source.
- **Low frequency, high consequence.** The production flag drives severity for
  the whole fleet. That is the profile where review beats direct edit.

Asana routing is already listed in `CLAUDE.md` as the missing shared plumbing.
A ruling proposal is a good first thing to ride on it, if that gets built.

**Note this does NOT touch the hard boundary.** "This tool never changes a
client site" is about client sites; the inventory is ours. The risk here is a
write path in the Worker and the loss of provenance, not a write to a client.

### One thing worth checking regardless

`moorseville-nc` and `nc-moorseville` both exist, both with no domain, both
unruled. That looks like one site keyed twice, and "ledger holds 84 sites / 130
rows, two per site, mis-keyed" is already in the bug table. A ruling pass would
surface inventory hygiene like this, which is a further argument for doing it as
a review rather than through a form. Related to item 2 above: `hoffmanscheese`
appears in both lists.

---

## Measure the sending domain instead of trusting it

**Logged 2026-08-24 from Victoria's question in the first outside review.
BUILT for Pantheon 2026-08-26; the Nexcess half needs a re-approval, below.
Nothing has run yet, so the coverage line reads `0 of 75` on the page.**

Two things in the original entry were wrong and are corrected in place below:

- **It said post-smtp is on 39 sites.** That was the Pantheon-only count,
  written before the Nexcess SSH scan existed. Measured from the component
  catalogue 2026-08-26: **39 of 47 inventoried Pantheon sites and 20 of 21
  Nexcess sites, 59 in all.**
- **It said this closes the 7 blanks. It closes ONE**, and that one is on the
  Nexcess side that has not been built. Corrected 2026-08-26 after measuring
  the component catalogue rather than the host column.

  **The sites with no recorded sending domain are, with one exception, the
  sites with no SMTP plugin.** That is not a coincidence — the workbook cell
  is blank because there was nothing to write in it. `lactalisamericangroup`,
  `lactalisheritagedairy`, `lactalisyogurtusa`, `midwestyogurt` and
  `eamusicfest` run no mailer at all: they send through PHP `mail()` or the
  host's own relay, so there is no plugin option to read and **no version of
  this design reaches them**. Extending it to `wp-mail-smtp` would not help;
  they do not run that either.

  `hitsfoundation.org` is the exception, and the only blank this feature can
  close. It is on Nexcess and it runs post-smtp.

  `woodmarkpharmacy.com` is on Azure, which no deep scan reaches. It is also
  already checked at its own domain, derived from `from_address`, so its
  column is not blank on the page.

### What was built

`wp option get postman_options --format=json`, gated on post-smtp appearing in
the plugin list the scan already fetched, so a site without it costs no extra
call. Three facts — `smtp_plugin_seen`, `smtp_from_domain`, `smtp_relay_host` —
documented in `docs/DATA-MODEL.md` section 2a. The option key is tried under
several spellings and records `unknown` when none match, because **it has never
been verified against a live site**: `terminus` is not authenticated on this
laptop. `scripts/diagnose-wp-calls.sh` now runs the same call and is the cheap
way to settle it on one real site before trusting a fleet-wide number.

### The Nexcess half needs a re-approval, and was NOT done

`scripts/nexcess-fleet-healthcheck.sh` runs a list of six commands that is a
**security control**, reviewed and approved by Doug on 2026-08-25, because
Nexcess issues no read-only SSH user and the credential can write to 22 client
sites. Adding a seventh command invalidates that approval, and nothing on the
host would stop the change — there is no permission error to hit.

The command to add is the same read: `wp option get postman_options
--format=json`. It reads one WordPress option and writes nothing.

**Measured 2026-08-26, what the Nexcess half is actually worth:** 20 of the 21
Nexcess sites run post-smtp, so it takes the measurement from 39 sites to 59 —
**a third of the achievable coverage**. It adds 19 workbook claims to
cross-check. And it closes `hitsfoundation.org`, **the only one of the six
blanks any version of this feature can close.**

So the half that needed no approval closes no blanks, and the one blank within
reach is behind the approval. **Re-review it, record the new approval in the
script header, then add it** — not the other way round.

---

**Original entry, 2026-08-24.**

SPF, DKIM and DMARC are all queried at the **sending domain**, and that value
is a ruling: a person types it into the "Email Sending Domain" column of the
audit workbook and `extract-audit-workbook.py` reads it. Nothing in DNS reveals
where a WordPress site was configured to send from, so it cannot be derived.

A wrong value does not fail loudly. It queries `_dmarc.` at a host nobody sends
from and returns a confident answer about the wrong domain. **7 of 78 sites
have none recorded** and report UNKNOWN, which is honest but is a fact we could
have.

**The fix is already reachable.** `post-smtp` is installed on 39 sites and
stores its host and from-address in WordPress options. The deep scan is already
running WP-CLI on those sites, so one more call turns the ruling into a
measurement:

```
wp option get postman_options --format=json
```

### Why it is worth doing rather than tidy

- **It closes the 7 blanks** with a measured value rather than a request for
  someone to fill in a spreadsheet cell.
- **It cross-checks the other 71.** A workbook claim disagreeing with the
  site's actual SMTP configuration is a finding, and this suite has never once
  found a claim and a measurement agreeing by accident.
- **It follows the pattern already proven with Nexcess.** Store it under a
  DIFFERENT fact name from the workbook's value, never overwriting it, so the
  disagreement is visible rather than resolved silently. `nexcess_php_version`
  beside `php_version` is the precedent.

### What to watch

- **Only `post-smtp` is covered.** 39 of 78. Other sites use different SMTP
  plugins or the host's mailer, so this raises coverage, it does not complete
  it. Say so on the page or "no measured sending domain" reads as "no mail".
- **Pantheon only.** The 21 Nexcess and 10 outlier-host sites have no deep scan
  reaching them, so they stay on the workbook value regardless.
- **The option key may vary by post-smtp version.** Verify against one site
  before writing a rule, per the usual.

---

## The UI revision, 2026-08-26

**Done.** `docs/clevermethod-fleet-ui-improvement-direction.md` was assessed,
and the parts worth taking were applied to `render-dashboard.py` directly. The
mockups and the forked renderer that carried them are deleted: a second copy of
the thing that publishes is a place for the two to disagree.

Applied: four exception tiles that each filter the table, a change feed grouped
by site, coverage stated as `48 checked · 4 not checked — of 52`, one sweep
line under the masthead, folded methodology with qualification kept inline, and
two columns that had been printing a bare `unknown`.

**Refused, and why.** Each of these would have re-created a defect already in
CLAUDE.md's table:

- **OK renamed to "Healthy".** 14 of the 26 OK sites have no measurable backup
  age. OK means nothing is pending that needs a person; it is not a statement
  that the site is fine.
- **Improved / Regressed / Informational.** The headless-to-headed browser
  switch raised tracker counts on many sites at once and nothing had started
  firing. The ledger's own classification already separates the fleet changing
  from the instrument changing.
- **Action buttons in the decision queue.** The page is read-only by decision,
  and a write route was removed from the Worker once and found still deployed
  a day later.
- **Compressing qualification along with methodology.** A qualification says
  what a number is *of*. Fold it and the number is wrong.

**Not done, and it is the app question.** Site detail, tabs, saved views,
persistent navigation. That turns two static files into a client-side
application. Worth deciding on its own merits.

**And one measurement that argues against the premise.** The direction document
opens on there being too much prose. There isn't, or at least that is not where
the bulk is: above the site table the page carries about 2,250 visible words;
the table itself carries 2,277, and "Still open" and "Sites that do not
reconcile" carry 805 between them. This revision reorganises the top of the
page. It does not shorten the page.

### Top issues, and the source that has no baseline

Added 2026-08-26 from the second concept. The largest standing findings are
now named near the top with a direction against the previous comparable run.
The full list stays where it was; this is the way in.

**It surfaced a real limitation. The consent sweep has no baseline at all.**
`previous_run_of_same_source` refuses a candidate whose measured site set is a
strict subset of the current run's, which is right -- diffing a 38-site run
against a 54-site one reports coverage gain as fleet change. But consent
coverage has improved monotonically (38 -> 50 -> 69 -> 71), so *every* earlier
run is a subset and none is comparable. That source therefore produces no
change rows and no trend, and has not since 2026-08-22.

That is honest rather than wrong, and it is not obviously the behaviour we
want: a source that keeps getting better at seeing the fleet never gets to
report what changed. The fix is not to relax the rule -- it exists for a
measured reason. It is probably to diff over the INTERSECTION of the two
site sets, which compares like with like on the sites both runs measured and
says how many were excluded. Not built. Decide before building.

---

## TABLED 2026-08-27: three managed sites on hosting this fleet does not cover

Nick's OneTrust audit workbook lists **15** sites clevermethod manages consent
for. Twelve are in `data/fleet-inventory.json`. Three are not:

- `buffalowebsitedevelopment.com`
- `homearcadegames.com`
- `mightytaco.com`

They are not missing by mistake. They sit on hosting none of this suite's
scanners reach, which is **a new hosting scenario, not a gap in the roster**.
Doug tabled it the day it was found.

**Do not add inventory rows for them until the hosting question is answered.**
An inventory row for a site no scanner reaches produces a permanent UNKNOWN
that looks like a coverage failure, and the inventory is the one file in this
repo that a person maintains by hand. `test-consent-rulings.py` asserts they
stay out, so this decision cannot be quietly reversed.

When it is picked up, the questions are: what hosting are they on, does any
existing adapter reach it, and are there other clevermethod sites there that
this fleet has never counted.

## OPEN 2026-08-27: the audit workbook and the scanner disagree on one site

`onetrust-audit.xlsx` records `interstatewaste.com` as
**"Scripts Fire w/ Respect to Consent: Yes"**.

Measured 2026-08-27 with `scripts/consent/test-gating.mjs`: after a real click
on Reject All and a reload, DoubleClick, GA4 and Meta Pixel all stopped, and
**MS Clarity kept firing**. The workbook's own Cookies sheet categorises
Clarity's `_clck` and `_clsk` as **C0002 Performance**, and the consent state
after the rejection read `C0002:0` -- denied.

So the categorisation is right and the tag is not honouring it. This is the
first thing the scanner has caught that the manual audit missed, which is the
entire argument for the scanner.

**Not yet raised with Nick.** Worth confirming on a second site before it is,
since one measurement on one page is one measurement on one page.

---

# Backlog from the team, 2026-08-27

From a Teams thread between Doug and **Victoria Brake (Sr Dev)** after the new
UI went live, reading `runtalnorthamerica.com`. Recorded because every item is
a decision about what the tool is FOR, not a defect in what it does.

The thread's own summary, in Doug's words: *"we will need some kind of admin
json to connect the raw data feed to the reality of our business."*

**That file already exists.** It is `data/fleet-inventory.json`, and it is
already the human-owned layer: `production`, `client`, `owner`, and since
2026-08-27 `consent_managed`, `consent_model`, `consent_rule`. Nothing new
needs inventing. What is missing is the CONTENT, and a way for a person to
reach it.

---

## B1. `maintenance_contract` — is a backlog our job or their decision?

**Victoria:** *"all of this security/version stuff does lead into the question
of how to handle this for clients who aren't paying for maintenance. does it
become their responsibility to update/manage this stuff then? we may need a way
to indicate that in this tool."*

One field per site, and then the same three-way split the consent axis got on
2026-08-27:

| | |
|---|---|
| we maintain it, and it is behind | our queue |
| we maintain it, and it is current | nothing to say |
| we do NOT maintain it, and it is behind | shown, flagged as theirs |

Doug: *"it could show good stewardship/value and could lead to upsells for
those we are not contracted with."* The third row is the one that does that, and
it is the row the page cannot draw today.

**The plumbing is an hour or two. The CONTENT is the blocker, and it is not a
small one.** Measured 2026-08-27:

| field | recorded on |
|---|---|
| `client` | **0 of 85** |
| `owner` | **0 of 85** |
| `production` | 2 of 85 |
| `consent_managed` | 85 of 85 |

`client` and `owner` have existed since the inventory was created and **nobody
has ever filled either in**. `consent_managed` reached 85 only because Nick's
`onetrust-audit.xlsx` existed and was imported. So: **do not add this field
until there is a source for the answer.** Two more permanently-empty columns
beside the two that are already empty would make the page worse, and by this
project's own rules an unrecorded ruling scores nothing, so the split would
render and do nothing.

**Blocked on:** a list of which clients pay for maintenance. Books, Harvest, or
somebody typing it once.

## B2. `pci` — a per-site PHP floor

**Victoria:** *"if we have a site that has PCI as a factor (like
woodmarkpharmacy) then that might force the PHP version requirement to 'as new
as possible for stable releases'."*

A boolean per site that raises the PHP threshold for that site alone. Small,
and unlike B1 the content is a short list somebody already knows.

## B3. PHP: the floor, and where it ranks

**Victoria:** *"php versions not receiving security fixes anymore... should be
on at least 8.3 based on the php docs. 8.4/8.5 (green) is ideal, but orange is
ok. outside of orange should be updated."*

**Check this against the fleet before implementing it.** Measured 2026-08-27:

| version | sites | security support ends |
|---|---|---|
| 8.1 | 1 | 2025-12-31 (past) |
| **8.2** | **46** | 2026-12-31 |
| 8.3 | 1 | 2027-12-31 |

A floor at 8.3 flags **47 of 48 measurable sites**. CLAUDE.md: a fact true of
every site ranks nothing, and that is the exact rule `upstream_pending` broke.
Victoria is not wrong -- she is describing a fleet-wide upgrade wave with a
date on it, which the page already carries as a PLANNING item. The per-site
version of her point is B2: PCI sites should not sit in that wave.

**She also ranks it differently from the model.** Her order is *WP core, then
plugins, then PHP*. Severity today puts `php_eol` at CRIT, above both. That is
defensible for PHP PAST end of support and it is worth putting to her
explicitly rather than assuming she meant something else.

## B4. Editing the rulings in the browser

**Doug:** *"what i meant by write is simply editing of the json in the browser."*
Later, or not at all -- his call, recorded so the reasoning is not lost.

The argument for it is B1's table. `client` and `owner` are empty after months
not because nobody cares but because filling them means editing JSON in a git
repo. **A field nobody can reach is a field nobody fills.**

The argument against is that this tool is read-only in both directions today:
it never writes to a client site, and nothing writes to the inventory except a
person with git. An edit form means auth, an audit trail, and a way to tell a
scan-derived fact from a typed one. Worth doing deliberately; not worth
sliding into.

## B5. CLOSED 2026-08-27 — the Lactalis sites are not ours, and the map is right

The consent page marks 14 sites as running consent tooling clevermethod does
not manage. Eleven of them are Lactalis brands on OneTrust, all with zero
trackers before consent, and **none is in Nick's `onetrust-audit.xlsx` Sites
sheet**, which holds 15. SharePoint also holds a signed
`lag-ambrosi-onetrust-integration-sow.docx` -- *"OneTrust Cookie Banner
Integration, Client: Lactalis American Group, Inc."*

That looked like a gap. **Doug confirmed it is not: the 15 in the sheet are the
complete list, and the eleven Lactalis sites run their own OneTrust.**

So `data/fleet-inventory.json` is correct as seeded and the consent page's
numbers are right as rendered: 12 managed sites in this fleet, 39 not ours, 10
ours-and-gated.

**The distinction that resolved it is worth keeping.** "We built it" and "we
manage it" are different, and `consent_managed` means the second. An
integration SOW is a project and it ends; clevermethod stood these up and
Lactalis has run them since. A future reader who finds that SOW will have the
same question, which is why the answer lives here and not only in a Teams
thread.

**What NOT to infer from this.** Do not read management from an SOW, from
OneTrust being present, or from a site being a client. The only source for
`consent_managed` is a person saying so -- which is why the seed script refuses
to overwrite it without `--force`.

## B6. The consent page does not say where "ours" comes from

The page prints `OURS` with the same confidence as a measured tracker count.
It is a ruling, seeded from a spreadsheet on one day, and Doug has said the
list grows as clients onboard -- so it is guaranteed to drift. The page should
carry the provenance and the date. Small, and it is this project's signature
bug otherwise.

