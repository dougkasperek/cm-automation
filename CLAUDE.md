# cm-automation

Read-only automation for clevermethod's 84 client WordPress sites. Keeps an
append-only ledger of what was measured and renders the dashboard at
`fleet.thudstaff.com` that replaces the manual audit workbook.

**This is a SUITE, not one workflow.** As of 2026-08-19 it is the operating
layer; Pantheon fleet health is one workflow in it. Adding a workflow means
adding a `source` to the ledger and severity codes to the shared module, never
a second scoring model or a second site list.

| workflow | state |
|---|---|
| Pantheon fleet health | live, CI, 52 sites |
| Email DNS (all hosts) | live, CI, 78 sites, no credentials |
| **Nexcess estate discovery** | **built; BLOCKED ON NEXCESS.** Cloudflare challenge. `docs/NEXCESS-SUPPORT.md` |
| Nexcess SSH deep scan | not built. Gated on the account-level-SSH-key answer |
| **Cookie consent monitor** | **built, in the suite.** 78 domains, no credentials. `docs/CONSENT.md` |
| Asana routing | not built. The missing shared plumbing |

**The scoreboard is the UNKNOWN count on the dashboard** — sites no scan has
ever reached. It is **32 today, measured 2026-08-19**. That number falling is
what progress looks like. The Nexcess discovery workflow is built and should
take it to 11, but **no Nexcess API call has been made yet, so 32 is still the
real number.** Do not quote 11 until a live run has produced it.

**Every rule below cost something to learn.** Nothing here is general good
practice; it is all scar tissue. If a rule seems obvious, read the sentence
after it.

---

## Hard boundaries

**This tool never changes a client site.** No updates, no writes, no
remediation. Applying updates stays human-gated until the read-only scan has
been trusted for several cycles. There is no write path and adding one is a
product decision, not an implementation detail.

**Claude edits files with asserted replacements, never a raw computed slice.**
On 2026-08-20 a patch built its needle as `s[s.index(START):s.index(END)]`
where END occurred EARLIER in the file than START. Python returns `""` for
that, `str.replace("", x)` inserts `x` between every character, and
`render-dashboard.py` went from 58KB to **58MB of one function repeated ten
thousand times**. Everything else in the file was gone. It was recoverable only
because the work had been committed twenty minutes earlier.

So: a replacement helper must assert the needle is non-empty, that it is
present, and that the result actually changed; a slice helper must assert
`end > start`. Both guards were added the same day and the ordering assert
fired on the very next run, on a different anchor. **Commit before a
mechanical rewrite of a file, not after.**

**Claude must not run any git command that writes the index.** Not `commit`,
and not `add`, `reset` or `update-index`. Even a bare `git status` leaves a
`.git/index.lock` on the mounted volume, and Claude cannot delete files there.
If a lock appears, `mv` it: `mkdir -p _to_delete && mv .git/index.lock
_to_delete/`. Then tell Doug to remove that folder. Leaving a lock behind means
his next commit fails with no explanation. **Claude edits files; Doug runs git.**

**`.github/` cannot be written through the device bridge.** Workflow edits land
in `ci/github-actions/` and Doug copies them across. Those two have already
diverged once, with the live workflow demanding a secret that had been deleted
for a code path that no longer existed. **Diff them before telling anyone to
run a workflow.**

**Secrets live in GitHub, never in the repo.** Keeper is unavailable. The
Cloudflare API token, the Pantheon machine token and the runner SSH key are
GitHub Actions secrets. `wrangler.toml` carries no credentials.

**Editing `ci/cloudflare/` does not change what is running.** A Worker only
changes when someone runs `wrangler deploy`, and Claude cannot. On 2026-08-20 an
audit found the deployed `cm-fleet` was a day behind the repo: the write route
removed on 2026-08-19 was still live, and `PUBLISH_TOKEN` was still set on it,
so it answered rather than returning 503. **Never describe the Worker's
behaviour from its source file.** Read the deployed code back --
`wrangler deployments view`, the dashboard's Edit code view, or the Cloudflare
MCP `workers_get_worker_code` -- and say which one you looked at.

**Access protects hostnames, never `*.workers.dev`.** Every Worker must pin
`workers_dev = false` in its own config, not just have the toggle off in the
dashboard, because wrangler defaults it to TRUE when the key is absent and the
next deploy silently re-opens it. **And `workers_dev` is a TOP-LEVEL key: it
must appear above the first `[table]` or `[[array]]` header in the file, or TOML
silently makes it a property of that table.** In `ci/cloudflare/wrangler.toml`
it sat below `[[routes]]` for a day and had therefore never been applied at all;
the off toggles in the dashboard were a manual click. Parse the file before
believing it -- `python3 -c "import tomllib; print(tomllib.load(open('wrangler.toml','rb')))"`
-- rather than reading the line and assuming it lands where it looks like it
lands. Measured state of all five hostnames, the
Access policies and the API tokens is in project memory,
`fleet_cloudflare_access.md`.

---

## The one bug this project keeps making

**A confident-looking value standing in for an absence.** It has happened
eleven times:

| what it said | what was true |
|---|---|
| `plugin_updates: 0` | nobody looked |
| no SPF record | the DNS lookup timed out |
| `wp_core_update: up-to-date` | the site is on 6.9.4, below the fix line |
| ledger holds 84 sites | 130 rows, two per site, mis-keyed |
| `Scanned **3**` | one; ssh ate the rest of the list off stdin |
| 33 of 52 sites CRIT | one rule on a fact that is never zero |
| 35 sites SKIP | 32 of them nobody has ever scanned |
| PHP 7.4 supported | the rule failed open when passed no date |
| the back door is closed | a cached HTTP response from 15 minutes earlier |
| `8.2 claimed`, `7.0.2 claimed` | the version had just been measured; the cell showed the workbook |
| all four hosts `unreachable` | three served valid TLS; this laptop had no CA bundle |
| `ok  site list returned` | HTTP 200 with a web page body; nothing had read it |
| `the token was rejected` | a Cloudflare challenge; the token was never read at all |
| `UNKNOWN: 0` | the coverage scoreboard, silently zeroed by a source that is not health |
| 23 sites "no banner, no trackers" | HTTP 403 block pages; `ok` meant the navigation did not throw |
| a current-looking dashboard | three of four workflows ingested and never published |
| `js.cookie.min.js` in `cmpScripts` | a WooCommerce helper, not a consent manager |
| the Worker is read-only, no write route, no secrets | true of the repo; the DEPLOYED Worker still had `PUT /api/publish/` and its `PUBLISH_TOKEN` |
| `workers_dev = false` is pinned in `wrangler.toml` | it sat below `[[routes]]`, so TOML made it a key of the ROUTE. Wrangler had never applied it and refused to deploy the first time anyone tried |
| a consent run covering the fleet | all four wrote 78 rows over 78 sites; one measured 54 and two measured 38 |

The thirteenth was our own diagnostic: `probe` printed one word for a DNS
failure, a TLS trust failure and a dead host alike, and sent Doug looking at
Nexcess when the fault was his Python's trust store. **A tool built to report
absences honestly has to classify its own failures too.**

**Only two were caught by code. The rest were caught by a person looking at a
rendered page or a raw number.** The twelfth was found the same way, on
2026-08-19, by rendering the page with Nexcess facts in the ledger: 21 sites
whose PHP and WordPress versions had just been measured still displayed the
workbook's unverified claim. The measurement was in the ledger and scoring
correctly, and invisible. Same family, pointed the other way — an absence
standing in for a value.

**And coverage has a DIRECTION.** Coverage going up is routine and says
nothing. Coverage going DOWN is a defect in the run, and until 2026-08-20 both
were classified `COVERAGE` and suppressed as noise together. That is how two CI
consent runs at 38 of 78 replaced a laptop run at 54 on the live dashboard and
sat there for a day. Coverage is now defined once, in `MEASURED` in
`fleet-ledger.py`, and read by three callers that must never disagree:
`deep_scanned` at ingest, the baseline guard, and the drop check. **A row
exists is not a site was measured** -- the consent sweep writes a row for every
site whether or not the page loaded, so the good run and the bad one were
indistinguishable by every count on the page.

So: **unknown is a value, never folded into yes or no.** When adding a fact or
a rule, state what it shows when the answer is unknown, and whether a reader
could take that to mean the opposite. When verifying a change, prefer a
measurement over an inference, and re-check that your measurement is live.

---

## Adding a workflow to the suite

Four things, in this order. Skipping any of them is how a suite becomes a pile
of scripts:

1. **Reconcile its site list against `data/fleet-inventory.json` FIRST.** Every
   tool that arrived with its own roster has disagreed with the inventory, and
   the disagreement was always a finding. The consent scanner has its own
   `sites.yaml` of 12 domains; that is a fourth list.
2. **Add a `source` and a fact family** in `fleet-ledger.py`. The fact-name
   collision guard will refuse two sources claiming the same fact name — that
   assert exists because merging unrelated measurements onto one timeline is
   silent and unrecoverable. **Add its `MEASURED` predicate in the same
   change.** `measured_count` REFUSES a source with no coverage rule rather
   than reporting it fully covered, because a source that always looks
   complete can never report a coverage drop.
3. **Add severity codes to `scripts/lib/severity.py`.** Same vocabulary, same
   module. A second scorer is two answers.
4. **Its own CI workflow.** Credential-free checks run on every push; anything
   needing secrets is manual until it has been trusted for several cycles.

The ledger, diff, dashboard and **severity** need no changes for a new provider
beyond the four steps above. They are keyed on site identity, not on host or
tool. **The RENDERER is the exception and the claim used to say otherwise.**
**A workflow that writes to the ledger MUST also publish.** Until 2026-08-19
only the Pantheon workflow did, so the email, Nexcess and consent workflows each
moved the ledger and left `fleet.thudstaff.com` rendering older data. Nobody
sees a stale page and knows it is stale. Publishing is now one shared reusable
workflow, `_publish-dashboard.yml`, called by the three; folding Pantheon's
inline copy into it is the next tidy-up.

**Do not assert a fleet COUNT in a test.** Three tests broke this session on
correct changes because they pinned a number that a new source was entitled to
move: `len(FACT_FAMILIES) == 3`, `len(unknown) == 32`, and a fixture row count.
Assert the property that must hold — "no site with no health evidence reads
OK" — not the number that happened to be true the day it was written. This is
the sibling of the existing rule about fleet-size assertions against
`reports/`.

**And a new source can change what an EXISTING number means**: the consent
sweep took UNKNOWN from 32 to 0 without anything improving, because UNKNOWN
answers "has any scan reached this" and was only ever the health-coverage
number by accident. Check what your new source does to the numbers already on
the page, not just to its own.
Adding Nexcess needed three lines in `render-dashboard.py`, because a table
column reads one named fact and a new provider answers the same question under
a different name. Scoring is generic; display is not. Assume a new provider
costs a renderer change and check the page.

## Data model, in one paragraph

Three layers, and conflating them is how the mis-keyed ledger happened.
`data/fleet-inventory.json` is the **inventory**: 84 sites keyed on domain,
human-owned, edited by hand, holding the join key and the `production` flag.
`history/*.jsonl` is the **ledger**: append-only observations, one row per tool
per site per run, nothing typed by a person. The workbook holds *claims*; the
ledger holds *measurements*; the dashboard shows both and labels which is which.

- **`history/` must NOT be gitignored.** It is the only asset here that cannot
  be regenerated.
- **`reports/` IS gitignored**, so it does not exist on a fresh clone or a CI
  runner. Anything reading it must tolerate its absence, and **no test may
  assert a fleet size against it.**
- **Ingest is append-only, so a mis-keyed row cannot be corrected in place.**
  A missing inventory is a hard error for this reason.

---

## Severity

`scripts/lib/severity.py`, and **nowhere else**. A pure function of observed
facts plus the inventory's `production` flag, evaluated at render time so
retuning a threshold rescores all history instead of reporting as a fleet
change. Full rationale in `docs/SEVERITY.md`. Two rules worth restating:

**Scoring is per AXIS, since 2026-08-20.** An axis is a QUESTION -- `health`
(is this site maintained) and `consent` (does it leak trackers) -- and a site
has a status on each independently. `evaluate()` returns `status` and `reasons`
for the HEALTH axis, `axes` for all of them, and `all_reasons` as the tagged
union. Before the split, 38 of 70 WARN sites carried a consent finding and 7
were WARN for consent alone, so the fleet-health headline moved when the
consent sweep ran and nothing about maintenance had changed.

- **Map a code by the QUESTION it answers, never by the tool that found it.**
  `coverage_partial` fires on the consent sweep and is a HEALTH reason,
  because it says "no health evidence exists for this site".
- **`axis_of()` raises for an unmapped code.** Defaulting to health is how
  consent came to drive the health headline, and it would do it silently. The
  guard immediately caught `backup_stale`, a conditional code that a grep for
  `add(bucket, "literal")` misses.
- **A terminal state -- FROZEN, UNKNOWN, SKIP -- is a statement about the SITE
  and lands on every axis.** And never show terminal states per axis card: "3
  sites are SKIP for consent" is not a thing. Found by looking at the page.

- **A fact that is true of every site ranks nothing.** `upstream_pending` was a
  WARN and no site could ever be healthy. PHP 8.2 expiring is the same shape:
  46 sites share it, so it is a planning item, not a per-site warning.
- **`production: null` means nobody has ruled, and scores AS production.**
  Fail safe. Do not infer it from the Pantheon plan; that would have excluded
  the fleet's worst-maintained site, which happens to be on a Sandbox plan.

---

## Commands

```bash
./scripts/pantheon-fleet-healthcheck.sh --api-only --no-fail-on-crit  # scan
./scripts/fleet-nexcess.py probe                                      # confirm the base URL
./scripts/fleet-nexcess.py discover --stamp "$(date -u +%Y-%m-%d_%H%M)"
node scripts/consent/run-sweep.mjs --stamp "$(date -u +%Y-%m-%d_%H%M)"  # needs npm i
./scripts/fleet-ledger.py ingest --reports ./reports --history ./history
./scripts/render-dashboard.py --out fleet.html                        # the page
./scripts/publish-dashboard.sh --dry-run                              # preview
./scripts/serve-dashboard.py --dir ./reports --open                   # live view
```

`render-fleet-dashboard.py` (v1) and `render-dashboard.py` (v2) are **both
current**. v1 feeds the live local view that fills in while a scan runs; v2
reads the ledger and is what gets published. Do not delete either.

---

## Testing

```bash
python3 test/test-ledger.py       # 106
python3 test/test-severity.py     #  70
python3 test/test-email-dns.py    #  58   (needs dnspython)
python3 test/test-nexcess.py      #  88   offline, no API call
python3 test/test-consent.py      #  59   offline, no browser
./test/run-local-test.sh          #  32   1-3 min, silent, two mock sites hang
                                  #       on purpose. Never run it through the
                                  #       device bridge: 45s timeout.
```

- **Assertions go against the committed ledger, pinned to a NAMED `run_id`.**
  Never against `reports/`, and never positionally. `health_runs[-2]` went red
  the day a debugging run landed between two fleet runs, and nobody noticed.
- **A mock must reproduce production's side effects, not just its output.** The
  terminus mock drains stdin because ssh does. That is what catches the bug
  where a scan of ten sites silently scanned one.
- **A test that only passes in one environment is not passing.** This suite has
  been broken by a gitignored directory, by a positional index, and by stdin
  being a terminal.

---

## Definition of done

1. The relevant test suite passes, and any new rule has a test that was
   **verified to fail** before it was fixed.
2. **The page was rendered and looked at.** Not the HTML source, the page. Most
   of the table above was found this way.
3. Any number stated in a commit message or to Doug was measured in this
   session, not inferred from a previous one.
4. Docs updated in the same change. A doc that describes the old behaviour is
   worse than no doc: `DASHBOARD.md` told people to deploy with wrangler for a
   month while no wrangler config existed.
5. No `.git/index.lock` left behind.

---

## Style

Plain English. Lead with the finding, then the reason. No rhetorical framing,
no metaphors, and do not make a straightforward technical finding sound
profound. Prefer *"the workbook says all 78 sites run 7.0.2, and exactly one
does"* over any dressed-up version of it.

Comments in code explain **why**, especially why something non-obvious is the
way it is. Most comments in this repo name a specific failure. Keep that.
