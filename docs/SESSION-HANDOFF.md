# Fleet automation: handoff for the next session

**Rewritten 2026-08-19, PICK UP HERE refreshed 2026-08-20.** Chats share this folder and project memory,
never each other's conversation history, so everything needed to resume is
written down.

**This supersedes `DESIGN-BRIEF.md` and every earlier version of itself.**

---

## PICK UP HERE — 2026-08-20, end of day

**Everything is committed and the tree is clean at `cad4e4f`.** Tests: severity
96, consent 65, ledger 117, nexcess 88.

**THE LIVE PAGE IS STALE.** `fleet.thudstaff.com` was last published before any
of today's UI work, so it still shows the single-status dashboard. First action
tomorrow:

```
./scripts/publish-dashboard.sh          # no token needed now, see below
```

It will ask for `CLOUDFLARE_ACCOUNT_ID` (`8ae221977ecb4518fecaffed03972e11`)
because Doug's wrangler login can reach two accounts and the script refuses to
guess.

### What changed today

**Scoring is per AXIS.** `health` and `consent` are separate questions with
separate statuses. Health had been silently driven by consent: 38 of 70 WARN
sites carried a consent finding and 7 were WARN for consent alone.

| | before | after |
|---|---|---|
| health | 2 CRIT / 70 WARN / 7 OK | **2 CRIT / 63 WARN / 14 OK** |
| consent | (none) | **0 CRIT / 38 WARN / 16 OK / 25 UNKNOWN** |

Read `docs/SEVERITY.md` and project memory `fleet_axes.md` before touching the
scorer. An axis is a QUESTION, not a workflow, and `axis_of()` raises for an
unmapped code rather than defaulting to health.

**The page leads with one card per question**, then the detail sections. The
site table has a captioned Consent column and a second filter that combines
with the first. The masthead was compressed so all three cards clear the fold.
Run times render in Eastern, 12-hour, always zone-labelled.

**The workbook columns are gone** from the page and the feed. Doug: "we don't
need to compete with the old way." `in_workbook` still feeds the
production-ruling queue and the inventory still holds the values.

**Coverage drops are caught at ingest.** A run that measured fewer sites than
the previous run of the same source prints what was lost and exits non-zero
unless `--allow-coverage-drop`. The run is still stored; the ledger is
append-only. See `fleet_coverage_guard.md`.

**...but in CI that exit code was throwing the run away, fixed 2026-08-22.**
`persist-ledger.sh` runs under `set -e` and called `ingest` bare, so the
non-zero exit killed the script before add/commit/push and without retrying.
On an ephemeral runner the degraded run that raised the alarm was the one run
guaranteed never to reach the ledger. It now passes `--allow-coverage-drop`
and reports the drop after the push, with the other post-push alarm. Publish
is gated on the persist job succeeding, so a drop still blocks the page.

**Cloudflare was audited and cm-fleet was redeployed.** The deployed Worker had
been a day behind the repo, still carrying the `PUT /api/publish/` route and
its `PUBLISH_TOKEN`. Both gone, verified by reading the deployed artifact back.

**`publish-dashboard.sh` no longer demands a token on a laptop** — it falls
back to the wrangler OAuth session. CI still uses the token.

### Tomorrow, in order

1. **Publish** (above). Then open the page and look at it.
2. **The publish-side coverage-drop guard.** Ingest fails loudly now, but
   ingest and publish can happen in separate sessions, so this is the layer
   that would actually have stopped 2026-08-19. `fleet-consent.yml` has
   `publish_dashboard` defaulting to TRUE, which is why the commented-out
   `schedule:` block must stay commented until this exists.
3. ~~**Pin `workers_dev = false` on [removed], [removed] and [removed].**~~
   **MOSTLY DONE — measured 2026-08-22 by parsing every config, not by
   reading the line.** Four of the five Workers on this account pin it:

   | Worker | config | `workers_dev` |
   |---|---|---|
   | `cm-fleet` | `ci/cloudflare/wrangler.toml` | pinned `false`, top-level |
   | `[removed]` | `~/dev/[removed]/wrangler.toml` | pinned `false`, top-level |
   | `[removed]` | `…/Partner Dashboard/[removed]/wrangler.toml` | pinned `false`, top-level |
   | `[removed]` | `…/clevermethod-com-2026/04-New Site Build/Active/cm-staging/wrangler.jsonc` | pinned `false` (JSON, no TOML ordering trap) |
   | **`[removed]`** | **none exists** | **nothing pins it** |

   `[removed]` and `[removed]` were already done and this note never caught up.
   Each was verified with `tomllib` / a JSON parse, so the TOML ordering trap
   is ruled out rather than eyeballed.

   **The remaining gap is `[removed]`, and it is the one holding
   partner-confidential material.** `~/dev/[removed]` has no wrangler config at
   all; `deploy.sh` only does `wrangler r2 object put`, never `wrangler
   deploy`, so the Worker is dashboard-managed and its toggle is held by
   nothing but a manual click. Adding a `wrangler.toml` is NOT a free fix —
   creating one where none existed changes how the Worker can be deployed, and
   a wrong `main` would ship the wrong code. Decide deliberately: either add a
   correct config that pins it, or write the dashboard-managed status into
   `deploy.sh` so the next person knows the toggle is the only control.

   **Why the pin is load-bearing, confirmed by reading the DEPLOYED code of
   both Workers on 2026-08-22.** Neither `[removed]` nor `[removed]` has any
   authentication of its own worth the name:

   - `[removed]` `/api/save` accepts ANY non-empty
     `Cf-Access-Authenticated-User-Email` and writes to R2 on it.
     `/api/harvest`, `/api/asana`, `/api/financials` and `/api/notes` check
     nothing at all, and the financial seed data is compiled into the Worker.
   - `[removed]` gates `analytics.html` and `/api/stats` on that same header
     starting with `doug`. `/api/harvest` and `/api/asana` check nothing.

   Both are fine **only** because Access is the sole route in. On a
   `workers.dev` URL the header is client-supplied, so the pin is not
   hardening — it is the whole control.
4. **The API tokens.** All three are no-expiry USER tokens on Doug's personal
   Cloudflare account. `github-deploy-[removed]` is scoped to **All accounts**
   and can reach `clevermethod, Inc.` too. Delete or re-scope it; move the CI
   token to an Account token with an expiry.
5. ~~**Ask Pantheon to allowlist the consent scanner.**~~ **WITHDRAWN
   2026-08-22 — Pantheon is not the blocker and this request would have done
   nothing.** All 20 answer from Cloudflare with a bot challenge; the request
   never reaches Pantheon. It is per-zone Cloudflare settings across at least
   four different DNS providers, so there is no one conversation and no one
   owner. See "The 403s" below for what replaces it.
6. ~~**Send `docs/NEXCESS-SUPPORT.md`.**~~ **SENT 2026-08-22**, both questions
   in one ticket. Now waiting on Nexcess, not on us. Do not re-send. Record
   their answers per "When they answer" in that file.
7. **Asana routing.** The last unbuilt step of deck slide 16.

### The 403s, split by host — this is the finding, not "the scanner is blocked"

| host | blocked from a laptop | blocked from CI | of |
|---|---|---|---|
| **CM Pantheon** | **20** | 22 | 47 |
| **CM Nexcess** | **1** | **15** | 21 |
| Azure | 3 | 3 | 4 |
| Flywheel / Pressable / WP Engine | 0 | 0 | 6 |

**Two different causes, and conflating them makes this look like one big
blocker when it is two small ones.**

- **Nexcess is IP reputation.** 1 from a residential connection, 15 from a
  GitHub runner. Nothing to fix — run it from a normal connection.
- **Pantheon is ~~a bot rule~~ A CLOUDFLARE BOT CHALLENGE, corrected
  2026-08-22.** The half that was right: 20 blocked from both IPs identically,
  so it is not about where the request comes from. The half that was wrong:
  whose rule it is.

**What was actually measured, 2026-08-22.** Nobody had read a response header
before writing the action item down. All 20 blocked CM Pantheon sites:

| | |
|---|---|
| `server: cloudflare` | **20 of 20** |
| `cf-mitigated: challenge` | 16 |
| 301 first, challenge after the redirect | 4 |
| reaching Pantheon at the point of blocking | **0** |

A site that scans fine looks different: `cottrillspharmacy.com` returns
`server: nginx` with `x-styx-req-id`, Pantheon's Styx edge.

**Being Cloudflare-fronted is not the trigger.**
`celticindustrialservices.com` is `server: cloudflare`, returns 200, and shows
a Pantheon `x-styx-req-id` behind it. So this is per-zone bot settings — Bot
Fight Mode or a WAF rule on those specific zones — not a platform policy.

**And they are not one estate.** Authoritative DNS across the blocked set:
Cloudflare (`clevermethod.com`, `ntlibrary.org`), Network Solutions
(`actioncarting.com`, `interstatewaste.com`), managed-ip (`zehnderamerica.com`),
MediaTemple (`galbanicheese.com`). Four providers, mostly Cloudflare
partial/CNAME setups fronting client-controlled DNS. `wrangler whoami` reaches
exactly ONE account, Doug's own; the `clevermethod, Inc.` account referenced
elsewhere in these notes is not reachable with that credential.

**So the next step is not a request, it is an inventory.** Which Cloudflare
account holds each of the 20 zones. Not yet established — the OAuth token
carries `zone (read)` and can answer it:

```bash
curl -s "https://api.cloudflare.com/client/v4/zones?per_page=100" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq -r '.result[].name' | sort
```

`clevermethod.com` is itself on the blocked list, so at least one is
self-service today. Split the rest into zones clevermethod administers and
zones the client does, and only the second group is a conversation.

**And invert the User-Agent advice.** The old note suggested an identifying
`cm-automation-consent-scan/1.0` UA to turn "allowlist these IPs" into
"allowlist this string". Against Cloudflare Bot Management a non-browser UA
scores **worse**, not better — the old note half-suspected this and now we know
the blocker. What works there is a WAF skip rule matched on something
verifiable: a custom header carrying a shared secret, or the source IP.

**This is a repeat of a documented failure.** CLAUDE.md's table already
carries `the token was rejected | a Cloudflare challenge; the token was never
read at all`, from the Nexcess portal. Same edge, same challenge, same
misattribution — a confident cause standing in for one nobody had established.

### Also open

- Standing findings still group by RISK / COVERAGE / PLANNING / DRIFT rather
  than by axis, so consent findings share one list with health and email.
- `hitsfoundation.org` fails TLS negotiation outright. Unrelated to consent.
- `pantheon-fleet-healthcheck.yml` still has its own inline publish job;
  folding it into `_publish-dashboard.yml` is a tidy-up.
- The 5 sites needing a production ruling, and the human triage queue.
- `reports/fleet-preview.html` is scratch in a gitignored directory.

### One incident worth reading

A patch script destroyed `scripts/render-dashboard.py` mid-session: it built a
replacement needle from `s[s.index(START):s.index(END)]` where END occurred
earlier in the file than START. Python returns `""`, `str.replace("", x)`
inserts x between every character, and the file went from 58KB to 58MB.
Recovered from the commit made twenty minutes earlier. **Commit before a
mechanical rewrite of a file, not after.** The rule is now in `CLAUDE.md`.

---

## READ THIS FIRST IF YOU ARE STARTING COLD

**`CLAUDE.md` in the repo root is the operating manual.** Read it before
touching anything. It holds the hard boundaries, the definition of done, and
the eleven-row table of times this project mistook a confident-looking value
for an answer. It was written 2026-08-19 and did not exist before that.

### BUILT LATER THE SAME DAY: Nexcess Phase 1

`scripts/fleet-nexcess.py`, `test/test-nexcess.py` (58 checks, offline),
`ci/github-actions/fleet-nexcess.yml`, `docs/NEXCESS.md`. Ledger source
`nexcess`, severity rules, and a renderer fix. **Not yet run against the
Nexcess API — no call has ever been made from this codebase.** The next action
is Doug running `./scripts/fleet-nexcess.py probe` with a portal token.

Measured this session on a simulated run (fixture data, never ingested into
`history/`): the render path works and the fleet moves
**2 CRIT / 31 WARN / 14 OK / 32 UNKNOWN → 9 CRIT / 45 WARN / 14 OK / 11
UNKNOWN**. OK does not move, by design: discovery gives no backup age and no
plugin counts, so a Nexcess site tops out at WARN with `coverage_partial` until
an SSH scan supplies them.

**Those simulated numbers are NOT fleet facts.** The real UNKNOWN count is
still 32 and stays 32 until a live run.

Rendering that page found the twelfth entry for CLAUDE.md's table: 21 sites
whose versions had just been measured still displayed the workbook's claim,
because the table columns read `php_version` and `wp_version` and the Nexcess
facts are stored under their own names on purpose. Fixed — the dashboard now
shows three labelled evidence tiers (plain / *per host* / *claimed*).

### ALSO BUILT TODAY: the cookie consent monitor, in the suite

`scripts/consent/run-sweep.mjs` + `check-site.mjs`, `test/test-consent.py`
(42 checks, offline, no browser), `ci/github-actions/fleet-consent.yml`
(credential-free), `docs/CONSENT.md`. Third ledger source `consent`, three
severity codes at WARN, `package.json` + lockfile committed.

**The pilot's `sites.yaml` is superseded. The roster is the inventory: 78
domains, up from 12.** Reconciling the pilot's twelve before writing any
integration code found **two wrong**: `morrisoncontainerhandlingsolutions.com`
does not resolve at all, and `hoosierfeedercompany.com` 302s to
`hoosierfeeder.com`. One in six, on the list that decides what gets watched.

That second finding moved a standing open item: `hoosierfeeder.com` resolves to
Cloudflare, not Pantheon's range, which is consistent with the workbook's "CM
Pantheon" being wrong. The origin host behind Cloudflare is **not** established
and the inventory note says so.

**Rendering a simulated full sweep took UNKNOWN from 32 to ZERO** with nothing
improved — the sweep reaches every domain, so no site is left in "nobody
looked". UNKNOWN was only ever the health-coverage number by accident. The page
now states health coverage on its own line and the JSON feed carries
`no_health_evidence`. **Watch that, not UNKNOWN.** Third time a render caught
something no test would have.

**RUN AND INGESTED 2026-08-19.** 54 of 78 sites genuinely seen: 17 clean with
OneTrust, **3 with tooling that leaks anyway** (`blockclub.co`,
`hoosierfeeder.com`, `pfannenbergusa.com`), 25 leaking with no tooling, 9 clean
with no tooling. 23 sites answer HTTP 403 to a headless browser and are
UNMEASURED. `zehnder-rittling.com` is clean.

**The first run caught a bug in the tool**: `ok` meant "page.goto did not
throw", so 23 HTTP 403 block pages were classified as having nothing to fix —
30% of the fleet clean on the evidence of an error page. Same shape as the
Nexcess probe reading a status code as an answer. Fixed, with a 403 fixture.

Fleet now: **2 CRIT / 70 WARN / 7 OK / 0 UNKNOWN / 3 SKIP / 1 FROZEN**, and 32
sites with no health evidence. The WARN jump is consent: 34 no-tooling +
28 leaking.

### The scope changed today

Doug, 2026-08-19: *"this dashboard (and eventual operating layer) is only
useful if it considers all of our sites, not just pantheon. additionally, i
want to have the cookie consent monitor built and running as part of a 'suite'
of automations built for our operation layer."*

So this is no longer one Pantheon workflow. It is **a suite feeding one
operating layer**, and the next two pieces are:

1. **Nexcess plumbing** — 21 sites with zero coverage today. See
   `docs/NEXCESS-ARCHITECTURE.md`, imported today and **entirely unverified**.
2. **Cookie consent monitor** — already exists as a runnable standalone pilot
   at `DK Sandbox/claude/Cowork Automation Portfolio/cookie-consent/`. Node +
   Playwright, read-only, zero credentials. It needs to be brought into the
   suite: same ledger, same dashboard, same severity vocabulary.

---

## WHAT SHIPPED 2026-08-19 (the day before)

**The dashboard is live at `https://fleet.thudstaff.com`**, behind Cloudflare
Access, updated automatically by CI. That was the goal of the whole build.

| thing | state |
|---|---|
| Severity model | **rebuilt.** `scripts/lib/severity.py`, the only scorer. `docs/SEVERITY.md` |
| Publish path | **rewired.** Renders from the ledger, uploads straight to R2 |
| Worker `cm-fleet` | **read-only**, no write route, no secrets. `workers_dev = false` |
| CI end-to-end | **proven.** scan -> ingest -> push -> render -> publish, all green |
| `CLAUDE.md` | **written.** The operating manual the deck promised |
| Tests | ledger 106, severity 68, mock 32, email 58 |

### The severity rebuild, in one paragraph

The old model scored **33 of 52 sites CRIT and nothing healthy**, because
`upstream_pending > 0` was a WARN and no site ever has zero. It also missed the
one genuinely exposed site, because that site's `wp_core_update` read
`up-to-date` while it ran WordPress 6.9.4. Scoring now lives in one module,
re-derived at render time, so a threshold change rescores all history instead
of reporting as a fleet change. Current: **2 CRIT / 32 WARN / 13 OK /
32 UNKNOWN / 3 SKIP / 1 FROZEN.**

**The 32 UNKNOWN are the point of the next phase: they are the sites no health
scan has ever reached.** 21 Nexcess plus the outlier hosts.

### The two real CRITs

- **`hoffmanscheese`** — no database backup in 721 days. Also absent from the
  audit workbook. Still needs a person.
- **`runtalnorthamerica.com`** — PHP 8.1, past end of security support since
  2025-12-31. Found only because the PHP table was unified; a hardcoded
  `< 8.0` floor missed it.

`cm-whitelabel` (WordPress 6.9.4, no backup in 2,147 days) is **closed** —
Doug ruled it a temp non-public site. It carries `production: false`, so it is
still scanned and shown but excluded from fleet counts.

---

## The goal, in Doug's words

> "I want a dashboard to view the automation data, not an XLS. The dashboard
> will eventually replace the xls."

Everything below serves that. The dashboard is the destination; the scans and
the ledger are how it gets fed.

Two decisions that follow from it, both made 2026-08-18:

- **Read-only for now.** Attestations, SSO and an audit trail come later, once
  it is in production. Access control is entirely Cloudflare Access at the edge
  and the app needs no auth of its own.
- **Hosting is Cloudflare.** CI is **GitHub Actions**; Azure DevOps is off.

---

## Where things actually stand

**The fleet has been measured.** First full-fleet full-mode scan completed
2026-08-19 00:02 UTC, 52 sites, in the ledger and pushed.

| thing | state |
|---|---|
| Repo | live, `github.com/dougkasperek/cm-automation`, private |
| Email DNS check, 78 sites | green in Actions, 26s |
| **Pantheon full mode** | **works locally AND in CI.** Run #5 green |
| **Full fleet scanned** | **52 sites, 48 deep-scanned.** Coverage 0 -> 48 of 52 |
| Unified 84-site inventory | built, keyed on domain |
| Ledger | 8 runs, both tools, every row resolving |
| Dashboard | 84 sites, real WordPress versions, verified both schemes |
| CI writes to the ledger | built, **never yet exercised** - see below |
| Tests | ledger **106**, severity **68**, mock harness **32**, email **58** |
| Publish path | **rewired to the ledger 2026-08-19.** Blocked only on Cloudflare setup |
| Severity | **rebuilt 2026-08-19**, `scripts/lib/severity.py`. See `docs/SEVERITY.md` |

### THE FIRST REAL RESULTS, 2026-08-19

```
52 scanned | 33 CRIT / 15 WARN / 3 SKIP / 1 FROZEN / 0 healthy
versions:  7.0.3 x33   7.0.4 x13   7.0.2 x1   6.9.4 x1   (4 never reached the WP stage)
32 sites have a core update to 7.0.4 pending
384 plugin updates pending across 43 of 48 measurable sites
```

**`cm-whitelabel` is on 6.9.4 — the only site below 7.0.2, so the only one below
the `wp2shell` fix line.** Two things make it worse: `wp_core_update` reports
`up-to-date`, so the pre-2026-08-18 columns called it clean and only the
installed version exposes it; and it has **no DB backup in 2,147 days**. Sandbox
plan, zero plugin updates, reads like abandoned internal scratch — **but it was
scanned on `live` and nobody has confirmed whether it resolves publicly. That is
the first question to answer.**

**`hoffmanscheese`: no backup in 721 days, 29 plugin updates.** Note that
`cm-whitelabel` and `hoffmanscheese` are the same two sites already flagged as
present in Pantheon and absent from the workbook. **The two sites with no audit
record are the two worst-maintained sites in the fleet.**

The workbook claims 7.0.2 and *plugins up to date* for all 78. Exactly **one**
site is on 7.0.2. 7.0.3 and 7.0.4 are both above the `wp2shell` fix, so those 45
are a maintenance backlog, not 45 emergencies.

### Known-good but unexercised

- **`persist_ledger` has never run.** It was unticked on run #5, so the job
  skipped. It also needs **Settings -> Actions -> General -> Workflow
  permissions -> Read and write**, or the push is capped at 403. That setting
  applies to every workflow in the repo; the tighter alternative is a
  repo-scoped fine-grained PAT used only by the persist step. **Undecided.**

## What was found and fixed on 2026-08-18 (second half)

Four defects, all of the same family: a value that looked like an answer and was
not one.

**1. The committed ledger was mis-keyed and incomplete.** It was written at the
initial import, before `data/fleet-inventory.json` existed, so its health rows
were keyed on Pantheon machine names rather than domains. `git log -- history/`
showed one commit, ever. Rendering from the repo as committed gave **130 rows
for an 84-site fleet** — 52 machine names and 78 domains, zero overlap — while
the `fleet.html` committed beside it correctly said 84, because it had been
rendered from a normalised ledger that was never committed. Rebuilt from
`reports/`; possible only because those four files still existed on one laptop.

**2. Nothing CI produced had ever reached the ledger.** `reports/` is
gitignored, ingest was a manual laptop step, and both workflows had
`contents: read`. Fixed by `scripts/persist-ledger.sh` and a `persist-ledger`
job in both workflows. **Read `docs/CI-LEDGER.md` before touching either.**

**3. The scan never recorded the WordPress version.** It ran
`core check-update`, which reports the version *available* and yields the string
`"up-to-date"` when there is none. The workbook claims 7.0.2 fleet-wide, and
`"up-to-date"` cannot be compared to `7.0.2`, so the central question of the
project was unanswerable from a scan that looked complete. Now captured as
`wp_version` via `core version`, stored as a deep-only fact, and rendered in its
own dashboard column that flags any disagreement with the workbook.

**4. Local runs stamped in Eastern, CI stamps UTC.** The ledger derives
`observed_at` from the filename stamp and orders runs by it to choose the pair it
diffs, so a laptop run and a CI run could sort four hours out of step and the
diff would compare the wrong pair. Dormant while only one machine wrote to the
ledger; live the moment CI does. `pantheon-fleet-healthcheck.sh` now uses
`date -u`.

Also: `fleet-ledger.py` and `render-dashboard.py` were committed
**non-executable**, so the `./scripts/...` commands in `SSH-KEY-SETUP.md` step 7
failed with *Permission denied*. Mode fixed on five scripts.

### Uncommitted on Doug's Mac right now, 2026-08-19 (severity work)

```
scripts/lib/severity.py      new    the only place severity is computed
docs/SEVERITY.md             new
test/test-severity.py        new    53 checks
scripts/fleet-ledger.py             COVERAGE class, re-derived scoring,
                                    cohort-run baselines, one PHP table
scripts/render-dashboard.py         fleet health + review queue sections
data/fleet-inventory.json           cm-whitelabel production:false;
                                    stale observed_status removed from 6 records
test/test-ledger.py                 named-run fixtures, 106 checks
fleet.html                          re-rendered
```

**`test/run-local-test.sh` has NOT been run against these changes** -- it
exceeds the desktop bridge's 45s timeout. The scanner was not touched, so it
should be unaffected, but run it before pushing.

### Uncommitted on Doug's Mac, earlier

```
docs/CI-LEDGER.md            new
scripts/persist-ledger.sh    new
ci/github-actions/*.yml      both workflows, to be copied into .github/
fleet.html, history/*.jsonl  the repaired ledger and its render
scripts/fleet-ledger.py, render-dashboard.py, pantheon-fleet-healthcheck.sh
test/test-ledger.py, test/run-local-test.sh, test/mock/terminus
five scripts with a corrected exec bit
```

---

## Do this next, in order

### 1. NEXCESS. This is the next build task.

21 sites, zero coverage, and the largest evidence gap in the security audit:
**every blank cell in the workbook's `wp2shell Security Flaw Remedied?` column
is a Nexcess site.** They are also 32 of the dashboard's UNKNOWN rows.

`docs/NEXCESS-ARCHITECTURE.md` holds Doug's research. **Read its provenance
header: nothing in it has been verified from this codebase.** The model it
proposes:

```
Portal API token  -> GET /v1/site        -> site inventory, Unix usernames
ONE automation    -> per-site SSH users  -> WP-CLI, read-only
SSH key
```

**The critical unverified claim** is that one SSH public key added at the
Nexcess user level authorises every Managed WordPress site that user can reach.
If true, this is one credential for 21 sites. If false, it is 21 credentials
and a very different design. Section 19 of that doc is a ready-made support
email; **sending it is a human task and it gates the SSH half.**

Sequencing that does NOT wait on that answer:

- **The 21 sites are already in `data/fleet-inventory.json`.** API enumeration
  is not required for a first pass; the inventory IS the site list. Enumeration
  only buys discovery of sites nobody wrote down — which on Pantheon found the
  two worst-maintained sites in the fleet, so it is worth having, second.
- Phase 1 of section 17 (read-only estate discovery via `GET /v1/site`) needs
  only a portal API token, and validates the doc's field-name claims.
- The deep-scan half reuses the Pantheon WP-CLI work almost unchanged. Same
  commands, different transport.

**The ledger, severity, diff and dashboard need NO changes** — they are keyed
on site identity, not host. Adding a provider means adding an adapter, and the
`UNKNOWN` count falling is the measure of success.

### 2. COOKIE CONSENT MONITOR, into the suite.

Lives at `DK Sandbox/claude/Cowork Automation Portfolio/cookie-consent/`. Node
18 + Playwright, loads each public homepage, watches what fires before consent,
detects banner tooling, writes a dated exception report. Read-only, no
credentials, already runnable.

Bringing it into the suite means:

- a third `source` in the ledger, beside `health` and `email-dns`
- its own fact family in `OBSERVED` (the fact-name collision guard in
  `fleet-ledger.py` will catch a mistake here)
- severity codes in `scripts/lib/severity.py`, using the same vocabulary
- its own CI workflow, same shape as the email one: no credentials, so it can
  run on every push

**Its roster is a separate `sites.yaml` of 12 domains**, drawn from Harvest
project names. That is a fourth site list, and this project has already been
bitten once by lists that disagree. **Reconcile it against
`data/fleet-inventory.json` before wiring anything.**

Note its README already describes the production shape: *"Claude reads a
CLAUDE.md, calls the same scanner, does the classification, opens Asana tasks
for new FAILs."* That matches the deck.

### 3. Asana routing — the last step of the deck's pattern.

Slide 16 promises: *"open an Asana item only where a person is needed, and keep
it open until confirmed."* Digest and dashboard are built; routing is not.
Asana appears in three design docs and no code. This is what turns a report
into an operating layer, and it is shared plumbing for every workflow in the
suite rather than Pantheon-specific.

### 4. Turn on the schedule.

The cron block is written and commented out in the workflow. The deck's own
rule is that execution is earned over several cycles; today was cycle one and
the first that ran end to end.

### 5. The scanner still scores severity itself.

`pantheon-fleet-healthcheck.sh` keeps its own inline rules, so its digest calls
a pending core update CRIT while the dashboard calls it WARN, and **its exit
code 2 still gates CI on the old definition**. Fixing it means a CLI mode on
`severity.py` and **changing what fails a build**. Left deliberately for a
decision. See the end of `docs/SEVERITY.md`.

## Three things that need a person, not code

1. **21 Nexcess sites have no `wp2shell` verification.** The only blanks in that
   column. Largest open evidence gap.
2. **`hoffmanscheese`** is in Pantheon but in nobody's audit. **`hoosierfeeder.com`**
   is in the audit but Pantheon does not return it.
3. **`shuman-plastics.com` and `dynapurge.com`** on Flywheel run PHP 7.4,
   unpatched since November 2022. Client-controlled hosting.

---

## Traps. Each of these cost real time already

- **Pantheon rejects ed25519 SSH keys.** Use RSA 4096. A rejected key looks like
  an auth failure, not a key-type failure.
- **Claude must not run ANY git command that writes the index** — not `commit`,
  and not `add`, `reset` or `update-index` either. It cannot delete
  `.git/index.lock`, so the repo is left locked and Doug has to clear it by
  hand. This happened again on 2026-08-18 via `git update-index --chmod=+x`.
  Claude edits files; Doug runs git.
- **`reports/` is gitignored**, so it does not exist on a fresh clone or a CI
  runner. Anything reading it must tolerate its absence, and **no test may
  assert a fleet size against it** — it holds whatever the last local scan
  produced, including one-site cohort runs. Deterministic assertions belong
  against the committed ledger in `history/`.
- **`history/` must NOT be gitignored.** The ledger is the one asset here that
  cannot be regenerated.
- **`ingest` is append-only, so a mis-keyed row cannot be corrected in place.**
  It has to be rebuilt from `reports/`, which only works while those files still
  exist. This is why a missing inventory is now a hard error.
- **GitHub's "Re-run jobs" replays the original commit.** Use **Run workflow**.
- **`.github/` cannot be written by the bridge**, so workflow edits land in
  `ci/github-actions/` and Doug copies them across. That directory is gitignored
  so a second diverging copy never gets committed.
- **The dashboard's light-mode palette is only legal because every state chip
  carries a text label.** Render a chip as a bare dot and the relief is gone.

---

## A recurring bug class worth naming

Six times now, a number read confidently and was wrong:

| where | what it said | what was true |
|---|---|---|
| the scan's `plugin_updates: 0` | no plugin updates pending | nobody looked |
| the email checker on a DNS timeout | no SPF record | the lookup failed |
| `standing()` in the dashboard | 1 site affected | 48 |
| the dashboard's `BACKUP: 0` | no backups | backed up today |
| the committed ledger | 84 sites, one history each | 130 rows, two per site |
| `wp_core_update: "up-to-date"` | the site is on 7.0.2 | nobody ever read the version |
| `terminus auth:whoami` exit 0 | authenticated | no session at all; CI never once logged in |
| the digest's `Scanned **3**` | three sites scanned | one; ssh ate the rest of the list |
| `cm-whitelabel` core `up-to-date` | patched | 6.9.4, below the wp2shell fix |
| severity `0 healthy` | the fleet is in crisis | one rule on a never-zero fact |
| `wp_version` absent in an old run | 48 sites changed version | the fact did not exist yet |
| the coverage table's `wp_checked` | 48 sites went dark | 48 sites became visible |
| `php_support()` with no date | PHP 7.4 is supported | a rule failing OPEN |
| 35 `SKIP` on the first render | nothing there to check | 32 sites nobody has ever scanned |

Every one was a confident-looking value standing in for an absence or a
misreading. **Only two were caught by code. The rest were caught by a person
looking at a rendered page or a raw number.** When adding a column, ask what it
shows when the answer is unknown, and whether a reader could take it to mean the
opposite.

---

## Read these, in this order

| file | what it holds |
|---|---|
| `docs/DATA-MODEL.md` | the inventory and ledger the dashboard reads. Start here |
| `docs/SEVERITY.md` | **how CRIT/WARN/OK are decided, and the `production` flag** |
| `docs/CI-LEDGER.md` | how CI writes to the ledger, and why it did not before |
| `docs/DASHBOARD-V2.md` | the dashboard, and why there are two renderers |
| `docs/SSH-KEY-SETUP.md` | full mode, now proven working |
| `docs/AUDIT-SHEET-ANALYSIS.md` | the manual workbook, per-column, and Nexcess |
| `docs/EMAIL-DNS.md` | the recovered Pass/Fail rule and three bugs |
| `docs/DESIGN-REVISIT.md` | the ledger-not-scanner reframe |
| `docs/GIT-SETUP.md`, `docs/RUNBOOK.md`, `docs/SECRETS.md` | mechanics |

---

## Open, undecided

- **Which GitHub account or org long term.** `dougkasperek` is personal.
- **Whether the two renderers ever merge.** Only if the live view learns to read
  the ledger mid-scan. Not needed yet.
- ~~**Version-stamping the tool per run.**~~ **Solved differently, 2026-08-19.**
  It happened exactly as predicted -- the first full-mode run reported 325
  changes, 274 of which were facts becoming visible for the first time. Rather
  than stamp a version, severity is now re-derived for BOTH sides of a diff
  with the current rules, and a new `COVERAGE` change class collapses
  unknown-boundary crossings to one line per fact. The same run now reports 11.
- **Whether the scanner should score at all.** It still does, with its own
  inline rules, so its digest and its CI exit code disagree with the dashboard.
  Fixing it means a CLI mode on `severity.py` and a change to what fails a
  build. See the end of `docs/SEVERITY.md`.
