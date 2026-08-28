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
| Cookie consent, headed | live, 77 of 78 sites. CI headed via xvfb, **proven on a runner 2026-08-22** |
| **Nexcess estate discovery** | **UNBLOCKED 2026-08-25.** The challenge was OURS, not Nexcess's: a hand-built SSL context omitted `post_handshake_auth`. `probe` now returns `ok 200 site list returned`. See the bug table |
| **Nexcess SSH deep scan** | **live, 21 of 22 sites, ran fleet-wide 2026-08-25.** Writes to the `health` source over SSH, under `kind: health-nexcess`. CI is manual dispatch only. **No read-only SSH user exists, so the command list in the script is a security control.** Seven commands, all reads; the seventh re-approved 2026-08-26 |
| ~~Nexcess SSH deep scan (old)~~ | ~~not built. UNGATED 2026-08-24~~ — one account-level key reaches all 21 sites, existing and future. And there is **no read-only SSH user**: the credential is write-capable, so the workflow's command list is a security control |
| **Cookie consent monitor** | **built, in the suite.** 78 domains, no credentials. `docs/CONSENT.md` |
| **Consent gating sweep** | **built 2026-08-27.** Clicks Reject All and reloads: do the tags actually stop? Its own source, `consent-gating`, because it asks a different question from the cold sweep and the consent MEASURED predicate is false on every gating row. First run: 26 tooled sites, 23 tested, **2 still firing** (MS Clarity, both Interstate Waste sites), 7 firing correctly as cookieless `gcs=G100` pings, 3 untested. Own page at `/consent`. **No severity codes yet** — what counts as a pass is a question for Nick, and the measurement is true whatever the answer. **Both 2026-08-27 windows were wrong** (v1 counted the old page's tail, v2 erased the new page's load — see the bug table); the window is v3 since 2026-08-28 and the fleet numbers await a re-run |
| Asana routing | not built. The missing shared plumbing |

**The scoreboard is the HEALTH-COVERAGE count on the dashboard** — sites that
have been looked at but have **no health evidence**: no backup age, no plugin
or theme count. It is **11, re-measured 2026-08-25** after the Nexcess SSH scan first ran (it was 32), and it is the number printed
under the fleet-health card. That number falling is what progress looks like.

It breaks down as **Azure 4, Pressable 3, Flywheel 2, WP Engine 1, Pantheon 1**
(`hoosierfeeder.com`). The Nexcess 21 are gone: the SSH deep scan ran on
2026-08-25 and measured 21 of 22. **Nothing remaining is worth more than four**,
and there is no single build that clears the rest.

**The 11 belongs to the SSH scan, NOT to API discovery, and this file said
otherwise until 2026-08-24.** It read "the Nexcess discovery workflow is built
and should take it to 11". Discovery cannot move this number at all, by
construction: `coverage_partial` fires on `(nexcess_seen or consent_seen) and
not health_seen`, and the Nexcess adapter deliberately writes `nexcess_*` fact
names that are not in `HEALTH_FACTS` — ingest maps the scanner's `php_version`
to `nexcess_php_version` precisely so the two evidence tiers can never be
confused. Scoring a site seen only by the control plane still returns
`coverage_partial`. Verified by running `severity.evaluate()` on such a site,
not by reading the rule.

**It used to be the UNKNOWN count, and quoting UNKNOWN today is wrong.**
UNKNOWN answers "has ANY scan reached this site", and the consent sweep reaches
all 78 domains, so UNKNOWN was **0** for a week. It went to **1** on
2026-08-25 when `app.eastauroracc.com` arrived from the Nexcess API in no
roster, reached by no scan; the SSH scan reached it hours later and it is
**0 again, measured 2026-08-26** by scoring the ledger, not by reading a page.

Do not read that round trip as nothing happening. For part of one day the
dashboard printed `UNKNOWN ... that number is 0` as literal copy while the
answer was 1 — see the bug table. The scoreboard did NOT move, and stayed at
32, because `coverage_partial` fires on `(nexcess_seen or consent_seen) and not
health_seen` and no source had seen the new site at all. A site nothing has
looked at is UNKNOWN, not partially-covered. Verified by scoring, not by
reading the rule. The two were the same figure by coincidence until
2026-08-19; they are different questions. See the `UNKNOWN: 0` row in the table
below — this paragraph is what that row was about, and it sat here
contradicting it for two days.

**Every rule below cost something to learn.** Nothing here is general good
practice; it is all scar tissue. If a rule seems obvious, read the sentence
after it.

---

## Hard boundaries

**This tool never changes a client site.** No updates, no writes, no
remediation. Applying updates stays human-gated until the read-only scan has
been trusted for several cycles. There is no write path and adding one is a
product decision, not an implementation detail.

**On Nexcess, read-only is a property of this code and of nothing else.**
Nexcess confirmed 2026-08-24 that no read-only or command-restricted SSH user
exists on Managed WordPress; every SSH identity has read *and write* on the
site filesystem, and Nexcess said restricting one to `wp core version` and
`wp plugin list` is not possible. So the list of commands the Nexcess SSH scan
runs is the only thing standing between a read-only tool and a write-capable
one — review it as a security control, not as a scan definition.

**That list was reviewed and approved by Doug Kasperek on 2026-08-25**, in
`scripts/nexcess-fleet-healthcheck.sh`, before the first fleet-wide run, and
**re-approved on 2026-08-26** when `wp option get postman_options` was added.
Seven commands, all reads. **Changing it invalidates the approval**, and
nothing in the system will stop the change: there is no permission error to
hit, because the credential can already write. Re-review and record the new
approval in the script header.

**`test-nexcess-ssh.py` now checks the LIST rather than one command's
absence.** It asserts every command the script runs is enumerated in the
header, every enumerated command is actually run, and the header's stated
count matches the list it sits over. The old assertion was "`option get` does
not appear", which a legitimate approval had to DELETE — a control that a
correct change removes teaches people to remove controls. Both directions were
tested by breaking them.

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

~~**Claude must not run any git command that writes the index.**~~ **LIFTED
2026-08-23.** The rule existed for one reason: the repo lived on a mounted
iCloud volume, a bare `git status` left a `.git/index.lock` there, and Claude
could not delete files on that volume — so Doug's next commit failed with no
explanation. The repo moved to `~/dev/cm-automation` (see
`docs/DO-THIS-NEXT.md`) and the premise went with it. Checked before lifting:
repeated `git status` runs from a Claude session leave no lock behind.

Claude may now run `add`, `commit` and `status`. **Still not `push`** — that is
outward-facing and stays a human action. If a lock ever does appear, `mv` it:
`mkdir -p _to_delete && mv .git/index.lock _to_delete/`, then say so.

Kept rather than deleted because it is another written-down rule that outlived
its reason. Check a claim before acting on it, including the claims in this file.

**`.github/workflows/` is the ONLY copy of a workflow. Edit it directly.**

Until 2026-08-22 there was a second copy in `ci/github-actions/`, because
`.github/` could not be written through the device bridge. That mirror was
**gitignored**, so it was never version-controlled — the documented process said
"edit here, copy across" while "here" was a scratch directory nobody else could
see. The two diverged once already, with the live workflow demanding a secret
that had been deleted for a code path that no longer existed.

The mirror is gone. `.github/` is writable in this repo; all five files were
verified byte-identical before it was deleted. **If a future environment cannot
write `.github/`, say so and stop — do not recreate a second copy.** A mirror of
the thing that actually runs is a place for the two to disagree, and the copy
that loses is always the one nobody is looking at.

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

**Access protects hostnames, never `*.workers.dev`. Since 2026-08-24 this is
CHECKED, not asserted:** `./scripts/check-worker-exposure.py` fetches all five
workers.dev URLs and all five hostnames anonymously and fails unless every
Worker is refused at the edge and every hostname bounces to Access. It needs no
credentials, so it runs on every push. Measured clear on 2026-08-24.

**That check answers AUTHENTICATION only.** Whether a logged-in person can
reach a DIFFERENT hostname by editing the subdomain is authorisation, decided
by that application's own policy, and `check-access-policies.py` is what reads
it. **A policy can admit someone without naming them** -- `email_domain`,
`everyone`, `ip` -- which is precisely the thing a human reading a list of
email rules will miss, and why "ask them to try it and report back" is not a
control. An unrecognised rule type reports UNKNOWN and never DENIED: a rule the
code cannot parse is a rule it cannot clear anyone against.

It needs a **read-only** token the wrangler OAuth login is not: Access: Apps
and Policies (Read) plus Access: Organizations, Identity Providers, Groups
(Read). Without Zero Trust scope the endpoint answers `success: true` with an
empty list, so the script treats zero applications as a scope problem rather
than as an empty account. `data/access-expectations.json` holds the intended
answer per person and CI fails on a difference in EITHER direction.

The check exists because **`[removed]` cannot be pinned in config and that is a
deliberate decision, not an oversight.** It is dashboard-managed; its bindings
(`DECK` -> R2 `[removed]`, `DECK_DB` -> D1 `[removed]`) and six
secrets live on the Worker, and a config declaring an incomplete set would drop
one on the next deploy. You cannot pin a dashboard-managed Worker from a repo.
You can notice within minutes when it opens. **Detection, where prevention is
the riskier operation.**

Every OTHER Worker must still pin
`workers_dev = false` in its own config, not just have the toggle off in the
dashboard, because wrangler defaults it to TRUE when the key is absent and the
next deploy silently re-opens it. **And `workers_dev` is a TOP-LEVEL key: it
must appear above the first `[table]` or `[[array]]` header in the file, or TOML
silently makes it a property of that table.** In `ci/cloudflare/wrangler.toml`
it sat below `[[routes]]` for a day and had therefore never been applied at all;
the off toggles in the dashboard were a manual click. Parse the file before
believing it -- `python3 -c "import tomllib; print(tomllib.load(open('wrangler.toml','rb')))"`
-- rather than reading the line and assuming it lands where it looks like it
lands. Measured state of all five hostnames and their Access applications is
in `docs/DASHBOARD.md`, "Access: what is configured".

**That pointer used to say project memory, `fleet_cloudflare_access.md`. No such
file exists.** Checked 2026-08-23: this project's memory directory holds
`MEMORY.md` and three preference notes, nothing else. Whether it was lost or
never written cannot be determined, and that is the point -- project memory is
per-user and outside git, so a measured record kept there is invisible to
review, cannot be diffed, and disappears without leaving a gap anyone can see.
Same shape as the gitignored `ci/github-actions/` mirror: the copy that loses is
the one nobody is looking at. **Measured infrastructure state goes in the
repo.**

---

## The one bug this project keeps making

**A confident-looking value standing in for an absence.** Every row below is
one occurrence. **The count that used to sit here said eleven, over a table that
had long since passed thirty** -- an asserted number that nobody reread when the
table grew, which is the same rule this file states two sections down: assert
the property, not the number that was true the day it was written. Add rows;
do not add a total.

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
| `4 trackers` on a site the sweep COULD see | 6. Hotjar and Meta Pixel detect automation and decline to fire, so a headless browser cannot see them on ANY site. Every headless count was a floor printed as a total |
| Pantheon blocks the scanner, and the fix is an allowlist | a Cloudflare bot challenge, and the variable was HEADLESS. Headed loads 27 of the 28 "blocked" sites. Three separate wrong answers were written down before anyone changed one setting and measured |
| a current-looking dashboard | three of four workflows ingested and never published |
| `js.cookie.min.js` in `cmpScripts` | a WooCommerce helper, not a consent manager |
| the Worker is read-only, no write route, no secrets | true of the repo; the DEPLOYED Worker still had `PUT /api/publish/` and its `PUBLISH_TOKEN` |
| `workers_dev = false` is pinned in `wrangler.toml` | it sat below `[[routes]]`, so TOML made it a key of the ROUTE. Wrangler had never applied it and refused to deploy the first time anyone tried |
| Pantheon is blocking the scanner; ask them to allowlist it | a CLOUDFLARE bot challenge on 20 client zones. Zero requests reached Pantheon. Nobody had read a response header before the action item was written down |
| a consent run covering the fleet | all four wrote 78 rows over 78 sites; one measured 54 and two measured 38 |
| 45 sites `OK` on an api-only run | nothing about any site's WordPress had been read. The same page said "WordPress core, plugins, themes: 0 of 52" two cards lower. Fixed 2026-08-23 by `wp_unestablished` |
| `plugin_updates: 0`, `theme_updates: 0`, `wp_core_update: up-to-date` on four OK sites | WP-CLI had returned **15 plugin updates, 3 theme updates and WordPress 7.1 available** on one of them. Pantheon's own mu-plugin emits PHP deprecation notices on stdout ahead of the JSON, `strip_noise` did not cover them, `json_or_empty` refused the lot, and the scanner wrote its clean default. Item 22, measured 2026-08-23 |
| "WordPress core, plugin and theme status needs the SSH-based full scan, which is not wired up yet" on the live page | it had been wired up and running in CI for four days. The coverage block on the SAME page said "WordPress core, plugins, themes (needs SSH): 46 of 52". Removed 2026-08-23 |
| the masthead's "3 tools feeding one ledger" | four. It counted sources that had RUN; Nexcess has a registered source, a coverage line and zero runs. Fixed 2026-08-23 — the provenance block now lists every registered source and says "never run" |
| a sixth site `OK` after all that | its `wp core version` answered and the three database-backed calls did not, so the VERSION was known and the UPDATE STATUS was not. `wp_unestablished` tests the version, so it stayed silent. Fixed the same day by `wp_update_status_unknown` |
| a fifth site `up-to-date` at 6.9.4 | its database is not installed at all. Every call that needs the DB exits 1; `core version` reads the version off disk and answers, so the row looked measured |
| the coverage box lists three sources | a fourth, Nexcess, existed and had never once run, with nothing on the page saying so — the box only appended a line `if source in latest`, so a source with zero runs was never `in latest` and simply never appeared |
| the Access API returned `0 applications` | five exist. The wrangler OAuth token carries no Zero Trust scope, and the endpoint answers `success: true` with an empty list rather than 403. Caught 2026-08-23 by curling the five hostnames and seeing five distinct Access redirects |
| `the token was rejected` on Nexcess, then five days of `Nexcess is blocking us with a Cloudflare bot challenge` | **the challenge was OURS.** `_ssl_context()` built a context by hand to fix macOS certificate verification. `http.client` sets `post_handshake_auth = True` on the context it builds for you; a hand-built one does not, and that flag changes the TLS 1.3 ClientHello. Cloudflare fingerprints the hello, and one with no post-handshake-auth extension matches no browser, so it was challenged. Same machine, same second: `context=None` -> 401 from the application, hand-built context -> 403 challenge, hand-built plus the flag -> 401. ALPN was tested and is not the factor. A support ticket, two vendor replies and a documented "ruled out: not a TLS fingerprint problem" all rested on it |
| the email card's "no column in the fleet table below" | four: SPF, DKIM, DMARC sending, DMARC from. The card denied the existence of columns rendered 200 lines below it, on the live page, until someone counted them |
| `<code>unknown</code>` as a sending domain on six rows | the ledger's absence sentinel is the STRING `"unknown"`, not `None`, so a falsiness test let it through into a cell as though it were a hostname |
| `2 have no recent database backup` on a fleet of 85 | out of **48** whose backup age can be read at all. Backup age comes from `terminus backup:list`, a Pantheon API call; Nexcess exposes no equivalent, so for 22 sites it is UNMEASURABLE rather than unmeasured. It got worse the day the SSH scan landed: those sites moved out of an honest UNKNOWN into WARN with real WordPress data, so they look well-measured while backup status is invisible. The card now states the denominator |
| a 22-site Nexcess health run is the latest `health` run, so it is the fleet | it wiped the 52 Pantheon sites off the page. `health` now has TWO transports over disjoint cohorts, and the model took one latest run per SOURCE. Components fell 310 -> 128, and CRIT, SKIP and FROZEN vanished. Caught by looking at the render, one step before publishing. Now grouped per `(source, kind)`, merged across cohorts, and diffed within one |
| `app.eastauroracc.com` is WordPress 6.2.2, per the Nexcess control plane | it is not WordPress at all. No `wp-config.php` anywhere, a `composer.json` requiring only `mailchimp/marketing`, and `wp core version` answering "This does not seem to be a WordPress installation". It scored CRIT `wp_below_floor` on the control plane's claim, putting a site that cannot have wp2shell onto the wp2shell remediation list. A positively non-WordPress `framework` now exempts it, and the disagreement is reported as `framework_not_wordpress` rather than becoming silent |
| a green CI step means that step succeeded | the Nexcess probe step ended in `\|\| true`. The token in GitHub was rejected, `probe` printed **"unauthorised, token rejected by the application"**, the step went GREEN, and the run failed three steps later as a Python traceback ending in `ApiError: 401 {"message":"Unauthorized"}`. The workflow knew the answer at step four and reported it at step six in the least readable form available. **A diagnostic whose exit code is discarded is not a diagnostic** |
| a scanner that runs on a laptop runs on a runner | `reports/` is **gitignored**, so it does not exist on a fresh clone. The Nexcess SSH scanner wrote into it and called `mkdir -p` at the END, which is no use to a redirect 40 lines earlier. The first real CI run died on `./reports/...json.tmp: No such file or directory` **after resolving all 22 targets correctly** — everything that could have been wrong was right. This file already says "anything READING it must tolerate its absence"; nothing said anything about writing |
| `--known-hosts` pins the SSH host keys, so CI cannot be fooled | it enforced NOTHING. `StrictHostKeyChecking` was set twice, `accept-new` then `yes`, and **ssh takes the FIRST value it is given for an option, not the last.** The flag looked right, the file was correct, and the pin did nothing. Caught only by a NEGATIVE control: removing a host from the pinned file and watching the scan succeed anyway — after which `accept-new` helpfully WROTE that host into the file it had been told to treat as authoritative. **A control that is present, looks correct and enforces nothing is worse than none, because it is the one nobody re-tests.** Test that a control REFUSES, never only that it permits |
| a clean reconciliation, after the join was fixed | the LEDGER join was fixed and the SCANNER's was not. `discover` still matched on domain, so the next run reported 18 sites "in the API, in no inventory row" AND the same 18 "in the inventory, absent from the API": 36 findings, every one false. **A reconciliation that cries wolf is worse than none** — it is step 1 of adding a workflow, and a real disagreement would be invisible in that noise. Fix a join in every place that joins, not in the one that failed |
| the Nexcess API's `domain` field is the site's domain | it is the **nxcli temp domain** for 18 of 22 sites, because the production domain was never set as primary in Nexcess. Joining the inventory on it resolved 18 sites to `0f614220a1.nxcli.net` and friends. Caught before ingest by the "every ingested row resolves to the inventory" guard, which is the only reason it is a paragraph here and not a corrupted append-only ledger. The real domain sits in `nickname`, which is free text: `2studs`, `Elma Historical Society`. The join is now `nexcess_site_id`, a stable integer, recorded in the inventory |
| `312 distinct components` | 310. `Divi-Child` and `Divi-child` are one theme on 41 sites, `PDFEmbedder-premium` and `pdfembedder-premium` one plugin on 12. WP-CLI reports the DIRECTORY name and the casing differs per site, so the catalogue keyed on the raw slug split both. The count was the small half: Wordfence publishes LOWERCASE slugs, so a case-sensitive CVE match on `pdfembedder-premium` would have hit 2 sites and missed 11, in the exact plugin family the catalogue was built for. Found because Matt said "there's no way it's right" and it got measured |
| `13 sites run PDFEmbedder-premium` | 12. `hoffmanscheese` carries it twice, `3.2` inactive beside `5.1.4` active. The catalogue counted ROWS as sites. Inactive still means files on disk |
| the wrangler OAuth token has no R2 scope, so publishing will probably fail | it publishes fine. `whoami` lists 29 scopes and no R2, yet `r2 object put` and `get --remote` both succeed. The inverse of the row below: there a missing scope read as "nothing is there", here it read as "you cannot do this". A scope listing predicts neither. Run the command |
| the expectations file says who can reach what | it says who can reach what **among the people already written in it**. `[removed]` had access to `[removed]` and was invisible to the check, because nobody had listed her. It answered "does this person reach only what they should" and never "who else has a key", which is the more dangerous question. It now enumerates every email named in every allow policy and reports any the file omits — and reports separately that an `email_domain` or `everyone` rule makes enumeration **impossible**, so an empty list is never mistaken for nobody |
| `_comment` cannot reach the four applications it is expected to | `_comment` is not a person. The expectations file used a `_`-prefixed key for commentary, and the loader evaluated every key as an email, so a JSON comment was scored against five Access policies and then had its own prose joined into an "EXPECTED ACCESS MISSING" line. Found on the first real run, by looking at the output |
| `count: 0` for the `clevermethod.net` zone | the zone exists and is active. The token is scoped to one account and the zone is in another. Same endpoint, same shape: not permitted to see it reads exactly like it is not there |
| `components: []` on a site | every WP-CLI call had failed. Its database is not installed, so each DB-backed call exits 1, and a `${pj:-[]}` default turned four failures into "we inventoried it and it runs nothing". Caught by running the mock, 2026-08-23 |
| `updates pending` inside a per-site view | the fleet-wide flag. The filter listed components whose update is waiting on some OTHER site, in a view whose every other number was about the one selected |
| `the 1 component(s) installed on <site>` | 31 were installed; 1 was merely being shown. The banner counted VISIBLE rows, so switching on a filter rewrote a fact about the site into a fact about the view |
| `the Nexcess discovery workflow should take the scoreboard to 11` | it cannot move it at all. Discovery writes `nexcess_*` facts, `coverage_partial` fires on exactly that — a site seen by the control plane and not by a health scan. The 11 is real and belongs to the **SSH** scan. The sentence sat in this file for five days, one paragraph above the rule that contradicts it, and was believed because the number was right |
| `ITEM 22 IS LIVE`, from the diagnostic built to detect item 22 | item 22 was FIXED on 2026-08-23. The scanner's failure branches record `unknown` and `null`; nothing fabricates. `diagnose-wp-calls.sh` mirrors those branches by hand, the mirror was never updated, and it had been reporting the bug it exists to catch as live on every failing call ever since — about `cm-whitelabel`, the very site that motivated the fix — and **exiting 2** while doing it. Its own output printed the contradiction two lines apart: `=> FABRICATED (exit 1)` above `the scanner records: plugin_updates=unknown, no inventory`. A comment in `test-wp-calls.py` had already spotted half of it and corrected only the wording, leaving the verdict. The verdict is now DERIVED from the record line, so the two cannot disagree; `test-wp-calls.py` asserts the property rather than either string. Same failure as the gitignored `ci/github-actions/` mirror, and its own drift guard covered the COMMAND LIST and not the BRANCH MODEL |
| the ssh-agent warning that explains a wall of timeouts | it lived inside the `any_fabricated` branch. Fixing the row above meant nothing fabricates, so the branch stopped firing and silently took the warning with it — the one line that tells you a run of timeouts is a passphrase prompt on your own laptop rather than a fleet finding. Introduced and caught within the hour, by a test that asserted the warning and the FABRICATED verdict together. It is reported before any verdict now, because it is a fact about the RUN |
| a coverage-drop guard, after the cohort split was fixed | it compared the 22-site Nexcess run against the 52-site Pantheon run and reported `21 of 22 measured, was 48 (-27)` on every alternating ingest from 2026-08-25. Nothing had dropped; the two cohorts measure disjoint sites. The RENDERER was fixed for the cohort split and **three other places that group runs were not**: `previous_run_of_same_source`, `coverage_regressions`, and ingest's own `last_by_source`. Fixing the first two did not silence the warning, and their tests passed, because ingest calls neither — the path that actually runs was the third. **Grep for every place that groups runs before believing one is fixed.** A guard that cries wolf on every other run is a guard nobody reads, and this one gates a publish. Both directions tested: a real drop inside one cohort is still refused |
| a mock built from what post-smtp *ought* to store | it stores neither. The first cut read `.from_email`, which post-smtp does not use, and expected a populated `hostname`. The offline suite passed against a mock invented to match the parser. The real option, read off `actioncarting.live`, carries `envelope_sender` and `sender_email`, and `hostname` is the EMPTY STRING because the transport is `mailgun_api` — Mailgun over HTTP, no SMTP relay. jq's `//` falls back on null and false but **not** on `""`, so the relay fact would have read `unknown` about a site that had answered plainly. Both halves passed every test until a real site was asked. **A mock is evidence about the parser, never about the world** |
| a diagnostic verdict of `FABRICATED` on the sending-domain call | it records `unknown`. Item 22 is about calls whose FAILURE BRANCH writes a clean value, so a failure reads as good news; this call has no such branch. Scoring it FABRICATED put an accurate absence in the same column as a plugin count that is a lie, and set the script exit to 2. It also printed the "the scanner records:" line EMPTY, because the call was added to `WP_CALLS` and not to the description table — five calls with a consequence and a sixth with a blank reads as "this one has none". Both found by running it on two real sites |
| `measuring post-smtp closes 6 of the 7 blank sending domains` | it closes **one**. Written the same day the feature was built, from the inventory's host column: 4 blanks on Pantheon, 2 on Nexcess, 1 on Azure, therefore 6 reachable. Nobody checked whether those sites run the plugin the measurement depends on. Five of the six run **no mailer at all** — they send through PHP `mail()` or the host's relay, so there is no option to read and no version of this design reaches them. The blank cell and the missing plugin are the same fact: the workbook is empty because there was nothing to write in it. A reachability claim derived from the host column instead of from the component catalogue, in a repo that has both |
| the email card's `7 site(s) have none recorded` sending domain | those 7 are sites with **no email row at all** — outside the check's 78 entirely. The sites that genuinely have no recorded sending domain carry the STRING `"unknown"` in `spf_checked_at`, which is truthy, so the test `not x.get("spf_checked_at")` counted **none of them**. There are 6. Both figures were 7 on the day it was found, which is why nobody found it sooner. Same family as the `<code>unknown</code>` row above, one layer up: the sentinel defeated the absence test rather than the display |
| `34 sites send through smtp.clevermethod.net` | correct, and typed. Third hardcoded number found on this page in one day. Computed 2026-08-26 |
| the dashboard's `no site is UNKNOWN on health and that number is 0` | it was the literal characters `0`, typed on 2026-08-19 when the consent sweep had just taken UNKNOWN to zero, in a sentence explaining that UNKNOWN and coverage are different questions. It was **wrong on 2026-08-25**: `app.eastauroracc.com` arrived from the Nexcess API, no source had seen it, UNKNOWN was 1 and the page said 0. The SSH scan reached it the same day and took it back to 0, which is the worst case — a hardcoded claim that is usually right is the one nobody rereads. Computed 2026-08-26, across production and non-production alike, with a test that was verified to fail |
| `16 commits are unpushed, that is the first thing to do` | everything was pushed. Inferred from the rule that `push` is a human action and repeated four times without checking. `git status --short` reports working-tree changes ONLY and says nothing about ahead/behind; `git ls-remote origin main` is the check that talks to the remote |
| the scan's own `Summary: 33 CRIT / 15 WARN / 0 OK` | 3 CRIT / 34 WARN / 11 OK. `pantheon-fleet-healthcheck.sh` carried its OWN severity model in bash, and it was the model severity.py replaced on **2026-08-19** — core update to CRIT, any pending plugin to WARN, any upstream commit to WARN. That last one is the rule that made OK unreachable for the whole fleet, which is why it printed zero OK on a fleet where a quarter of sites have nothing pending. The dashboard was never wrong, because severity is recomputed at render time and this field is deliberately ignored. Everything a PERSON reads was wrong: the summary, the markdown, the CSV, and the **exit code** — whose own header calls exit 2 "the signal a scheduler or CI job should alert on". It would have alerted on 33 of 52 sites every run; CI passes `--no-fail-on-crit`, which is the only reason nobody saw it for three weeks. Fixed by CALLING severity.py, not by porting the thresholds — a third copy is two answers again |
| `This page can see 68 of 75 Pantheon sites` | 53 Pantheon and 22 Nexcess. The Nexcess SSH scan landed 2026-08-25 and `COMPONENT_HOSTS` was widened the same day, so the DENOMINATOR was corrected from 53 to 75 and the sentence under it was not. The number was right and the noun was wrong, which is the hardest version to spot. **Its next clause was wrong too**: "nothing here is a statement about the 32 sites on other hosts", computed as everything `!= "CM Pantheon"` — which includes the 22 Nexcess sites the page inventories two screens below. It disclaimed its own data. The real out-of-scope count is 10. Both halves now read one module-level tuple. Reported by Doug reading the page |
| a note that severity had nothing to say about | the note the OLD model wrote, surviving untouched. The first cut of `score-scan.py` fell back to the incoming note when severity produced no reasons — which is exactly the OK and FROZEN rows, the only place nothing overwrites it. So the fix for the stale scorer would have left the stale scorer's text on every clean row. Caught by a test written in the same change, before it ran anywhere |
| a legend, for the Kind column | a `<details>`, closed. The words were undefined, that was the report, and the fix put the definition one click away on a page where **every** `<details>` renders closed — the one explaining CRIT, WARN and OK included. So the page had no visible key anywhere and no way to know one existed. Doug: "now I see it. its buried." **A key you have to discover is not a key.** The four glosses are inline and unfolded under the table now; the fold keeps only the note that DRIFT and COVERAGE mean something else in the change feed. Assert a key is NOT inside a `<details>`, not merely that it exists |
| the rulings table's `Why it is here` | for four of five rows, why the ruling is missing. For `hoffmanscheese` it printed **`No database backup in 730 days; 27 plugin updates pending`** — its health findings, which are true, are on its own row two sections down, and are not why a ruling is outstanding. The cell read `reasons or "<the ruling text>"`, severity FIRST, so any site with findings answered a different question in the same column. A reader comparing rows would conclude the four blanks were bureaucratic and this one urgent, when **the decision required is identical**. The fallback was also a hardcoded second copy of the inventory's `reconciliation`, so correcting the record could not correct the page |
| `var(--quiet)`, `var(--rule)`, `var(--link)` in new CSS | none of the three exists. The tokens are `--ink2`, `--line`, and links are `color-mix(in srgb,var(--info) 85%,var(--ink))`. An undefined custom property does not error — it falls back to the inherited value, so quiet text renders as body text and a 1px rule renders black, and the page still LOOKS deliberate. Caught by diffing the variables used in the rendered CSS against the ones `:root` defines, which is now the check: **parse the output, do not read the source and assume the name was right** |
| the standing list explains why the fleet is amber | it never mentioned the two facts that COLOUR it. Measured 2026-08-27: 52 of 85 sites read WARN and 40 of those were WARN for a core update, a plugin backlog, or both, while `standing()` emitted twelve causes and named neither. The table was amber and the action list beside it was silent on why. The tempting fix was to demote `core_update` the way `upstream_pending` was demoted, and the measurement REFUSES it: `upstream_pending` went because it was never zero, and `wp_core_update` reads up-to-date on 36 of 68 measurable sites against 32 pending. It discriminates. The gap was the grouped view, not the threshold |
| `NOT FULLY GATED` on 9 sites | 2. The gating verdict HAD the `gcs=G100` exclusion and I dropped it while rewriting the verdict to be driven by the click pass. A Google tag still firing after a rejection is only a leak if it did NOT switch to cookieless, and on 7 of the 9 it had — the correct denied behaviour, which `docs/CONSENT.md` has said since the first sweep. The measurements were right the whole time; re-deriving from the stored passes gave the true answer without re-measuring anything, which is the argument for storing observations and scoring separately |
| the consent page is published | it was in R2 and **unreachable**. `publish-dashboard.sh` uploaded `fleet/consent.html`, the fleet page linked to `/consent` from the Consent column header, and the deployed Worker had routes for `/`, `/components` and `/api/fleet-scan` and 404'd everything else. The test written that day asserted the UPLOAD and not the ROUTE — half a contract. **A page in R2 that no route serves is invisible, and it looks exactly like a page that was never rendered**, so nothing complains. `test-worker-exposure.py` now asserts the two sets match in BOTH directions: every HTML file the publisher uploads has a route, and every route points at something the publisher uploads. Found by Doug opening the URL |
| `MS Clarity still fires after Reject All` on two sites | **nothing fires. The test was wrong and the sites are fine.** `test-gating.mjs` cleared its request counters BEFORE reloading, so it merged two windows: what fires after the click, and what fires on a fresh consent-denied load. Scripts already running on an open page keep working until navigation, so Clarity flushing its session buffer landed in the same bucket as a tag ignoring consent. ~~Instrumented properly, the post-reload window has **ZERO requests on all 23 tested sites**~~ — that sentence was the NEXT bug: the "proper" instrumentation (v2) opened its window after the load event and erased the load phase, and 3 of the 23 recorded G100 pings even through it, so it was false as written. See the v2 row at the end of this table, 2026-08-28. Nick Federico checked it by hand, said the trigger was correct, and was told by our tooling that it was not. **The disagreement was visible in my own output before I sent it**: the synthetic-cookie pass had Google correct at `gcs=G100` and Clarity stopped, the click pass had the exact opposite, and two passes of one test disagreeing about one site is a defect in the test, not a finding about the site. His second objection — that Google should still send cookieless pings and my report showed none — was the same bug seen from the other side |
| `interstatewaste.com` leaks 4 trackers before consent | it is opt-out outside California and doing exactly what it was configured to do. The sweep does ONE COLD LOAD and records what fired; on an opt-in site that is a finding and on an opt-out site it is the intended behaviour, and **the two produce an identical observation**. So the rule was scoring an absence — the site's consent MODEL, which no scan can read. Nick Federico said so, the agency's own OneTrust audit records the site compliant, and a real Reject All test confirmed three of the four tags stop cleanly. `consent_model` is now an inventory ruling beside `production`, and an opt-out site firing on load is reported as configured behaviour on the PLANNING axis rather than as a defect |
| a leaking site with consent tooling is a defect WE own | tooling present never meant we built it. 22 sites in this fleet run OneTrust that clevermethod does not manage, and the group splitting them used `consent_banner_detected` because it was the only signal available. `consent_managed` is now recorded per site, so the group of 4 became 2 configured-as-intended and 2 belonging to someone else — and the "defect we own" group, whose action line called it "the highest-value rows here", is empty |
| `consent_model` belongs in `CONSENT_FACTS` | that tuple IS the definition of `consent_seen` — `any(k in site for k in CONSENT_FACTS)` — and it feeds `COVERAGE_FACTS`, which decides UNKNOWN. The rulings are seeded onto EVERY inventory row, so all 85 sites read as swept and three with no environment to measure moved SKIP -> WARN. **An inventory ruling is not evidence that anything looked.** Ten minutes, caught by the fleet counts moving when nothing had been measured |
| the scanner's `ERROR` row, scored by severity | severity has no ERROR state and should not: it scores facts, and that row has none because the scan could not look. Passing it through turned "we could not reach this site" into **SKIP**, which means "we looked and there is no live environment" — a different and more reassuring statement — and blanked the note saying the preflight had timed out. ERROR now passes through unscored. Caught by the mock suite, which is the only test that runs the scanner end to end |
| a Nexcess site whose SSH scan FAILED, scored `OK` with an EMPTY reason list | it has a plugin backlog. The scanner was honest — `wp_checked: false` and the literal `unknown` for every WordPress fact, nothing fabricated. **Severity had a gap between three rules that each declined to fire**: `wp_unestablished` needs no version from ANY source and the control plane had one; `nexcess_app_version_unknown` needs the same; and `wp_update_status_unknown` was gated on `wp_checked is True`, which a FAILED scan sets to false. So the one shape none of them covered was the one that matters. Latent from the day the SSH scan was built, surfacing 2026-08-28 on the first fleet-wide run where it failed: 1 of 22 sites reached from a GitHub runner, and **7 real client sites with plugin backlogs would have published green**. The guard now asks whether a version is known from ANY source, not whether the deep scan succeeded, so the three rules partition the space instead of overlapping. Caught by the coverage-drop guard refusing to publish, then by diffing the render against the live feed |
| `wp_below_floor` CRIT on `app.eastauroracc.com`, again | it is still not WordPress. The 2026-08-25 fix exempts a positively non-WordPress `framework`, and that fix is intact — but the failed scan of 2026-08-28 recorded `framework: unknown` where the good run recorded `not-wordpress`, and the renderer takes the LATEST run per cohort. **A failed scan un-learned a measured fact and resurrected a fixed bug**, putting a site that cannot have wp2shell back on the wp2shell list. Not caused by the severity fix above; measured across three renders to be sure. Open: the question is whether a run that says `unknown` should overwrite a prior run that MEASURED the answer, which is a merge-semantics decision, not a severity one |
| four workflows dispatched together will serialise, because they share a concurrency group | **two of their ingests would be silently cancelled.** GitHub keeps only ONE run pending per group by default; a newly queued run CANCELS the one already waiting, and `cancel-in-progress: false` does not change that — it governs the RUNNING job, not the pending one. So four dispatches run one persist, hold a second, and drop the third and fourth with no error, no failed run and nothing on any page. Fixed 2026-08-28 with `queue: max` (100 pending) on all eight groups, applied by parsing rather than by editing text, and asserted by `test/test-workflows.py` — verified to fail by removing the key and by flipping `cancel-in-progress`. **Documented behaviour, not yet observed on this repo:** read the run list after the first all-at-once dispatch and confirm every persist job actually ran. The publish side had no group at all until the same day |
| the guard's own advice: "pass `--allow-coverage-drop` if the drop is real and expected" | **no workflow exposed that flag.** From Actions there was no way to say "yes, expected" at all, so a legitimately smaller run blocked every publish from every workflow until somebody published by hand. The case that forced it: the consent sweep reaches 78 of 79 sites from a laptop and **71 of 79 from a GitHub runner**, because 7 sites refuse the runner with HTTP 403. Neither number is wrong — they are different vantage points — and the page ALREADY names each blocked site and says its consent posture is unmeasured rather than clean. The drop was real, expected and explained, and unpublishable. `allow_coverage_drop` is now a dispatch input on all five scanners, default false, and must reach BOTH guards: `persist-ledger.sh` looks at the run it just ingested, `publish-dashboard.sh` looks at the whole ledger's standing state, and telling one leaves the publish refusing anyway |
| a green `test-ledger.py`, then a correct page failing it | the assertion was `"no baseline" in _page` — true only while some standing cause happened to lack a comparable earlier run. Four scans landed in one afternoon, every cause acquired a baseline, and the page became correct in a way the test called failure. **This file states the rule twice — assert the property, not the number true that day — and the test broke it.** Now asserted both ways off the model, plus a guard that the no-baseline branch still exists so it cannot pass vacuously. That guard was ITSELF vacuous on the first cut: it matched `"no baseline"` anywhere in the renderer, including a COMMENT, so renaming the rendered span passed. It matches `>no baseline</span>` now, and was verified to fail |
| the fleet banner's `Can't say` explanation | **a raw JSON object, in the headline copy of the main page.** `page.js` read `r.what || JSON.stringify(r)`; `what` is a key on `D.coverage` — the coverage BOX — and never on a regression record, whose keys are `source`, `deep_scanned`, `site_count` and `previous_deep_scanned`. So the fallback fired every time and the banner printed `Coverage fell since the previous run ({"source":"consent","run_id":"consent-2026-08-28_1613",...`. It also **broke the 375px layout**, because an unbreakable JSON string overflows — a second failing check nobody would have connected to the first. Latent since the banner was written: the coverage guard blocks the publish, so no regression had ever reached a rendered page. It took four scans in one afternoon to see it. **The DOM test's fixture had a `what` key, so the mock matched the parser's mistake and passed** — a mock is evidence about the parser, never about the world. Fixture now uses the real record shape and was verified to catch both failures |
| `OK` beside `4 before consent` in the same cell | both true, and together they read as a contradiction. The status was right and the cell never said why: on an opt-out site the four are the configured behaviour. A green verdict next to its own contrary-looking evidence is a reader's problem even when the model is correct. The cell now reads `4 on load, as configured`. Found by reading the rendered row |
| `Plugin updates pending: 17 sites`, and a second row saying `7 sites` | 24. `standing()` is called once per COHORT, so a cause both health cohorts can raise renders twice with the fleet split across the two rows, each action line quoting its own half as the total (`268 update(s) across 17 site(s)`). The twelve existing groups never collided, but only by luck — upstream, backup and PHP read facts only the Pantheon cohort carries. Same family as the cohort split itself, and the fourth place that needed the same fix. Now unioned per SOURCE and scored once; a flat union across sources would have been worse, since 46 sites carry both a health row and an email row and one of each pair would have been dropped silently. The baseline had it too: `standing_was` keyed on cause, so the second cohort overwrote the first and a 24-site group whose baseline was 24 would have drawn `was 7` |
| `One update decision covers all 21 site(s). Being one release behind...` | 20 of the 21 were one behind and `valbresocheese.com` was on 7.0.2, two patches back. A blanket distance nobody had measured, in an action line written the same hour. What is actually true of the group is the TARGET, so that is what it claims now; the per-site distance sits in `detail`. Caught by reading the rendered row, not the code |
| `0 of 23 sites still fire after Reject All`, from the FIXED gating test | the fix overcorrected. v2 cleared the counters after `reload({waitUntil:'load'})` resolved, and the load event fires AFTER the fresh page's load-phase requests — where GA4 pageviews fire — so the window erased the exact load the test exists to measure, `gcs=G100` pings included. "Nothing fires after rejection" is the best possible result, and the instrument manufactured it; the row above claiming ZERO on all 23 was written from it, over data that showed 3 sites pinging G100 anyway. Fixed 2026-08-28 as v3: the reject pass measures a FRESH page on the same context, whose listener exists before its first request, so the window is the page's lifetime and no clear can be mis-ordered again — the shape the synthetic-cookie pass always had. `test/test-gating-window.mjs` drives both boundaries against a local fixture and **failed against v2 before v3 existed**. Every fleet gating number is unmeasured until a v3 re-run |

One of them was our own diagnostic: `probe` printed one word for a DNS
failure, a TLS trust failure and a dead host alike, and sent Doug looking at
Nexcess when the fault was his Python's trust store. **A tool built to report
absences honestly has to classify its own failures too.**

**Only two were caught by code. The rest were caught by a person looking at a
rendered page or a raw number.** The `8.2 claimed` row was found the same way, on
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

Five things, in this order. Skipping any of them is how a suite becomes a pile
of scripts:

1. **Reconcile its site list against `data/fleet-inventory.json` FIRST.** Every
   tool that arrived with its own roster has disagreed with the inventory, and
   the disagreement was always a finding. **Proven again 2026-08-25:** the
   first real Nexcess run returned 22 sites against an inventory of 21, and the
   extra was `app.eastauroracc.com`, a live production WordPress install in no
   roster at all. **And do not assume the provider's `domain` field is the
   site's domain** — pick a join key the provider guarantees is stable, record
   it in the inventory, and make ingest REFUSE a row it cannot resolve rather
   than invent a key. The consent scanner has its own
   `sites.yaml` of 12 domains; that is a fourth list.
2. **Add a `source` and a fact family** in `fleet-ledger.py`. The fact-name
   collision guard will refuse two sources claiming the same fact name — that
   assert exists because merging unrelated measurements onto one timeline is
   silent and unrecoverable. **Add its `MEASURED` predicate AND its
   `COVERAGE_FLAGS` entry in the same change.** `measured_count` REFUSES a
   source with no coverage rule rather than reporting it fully covered,
   because a source that always looks complete can never report a coverage
   drop. `COVERAGE_FLAGS` is the other half: it names the FACT that predicate
   reads, so `classify()` scores a move in it as the tool's coverage changing
   rather than as fleet news. `consent_scan_ok` had a MEASURED entry and no
   COVERAGE_FLAGS entry for two days, and when a WAF blocked four sites the
   one event was reported three ways — 8 of the 14 headline "changes needing
   a decision" were the scanner losing sight of a site, not a site getting
   worse. Both halves, one change.
3. **Add severity codes to `scripts/lib/severity.py`.** Same vocabulary, same
   module. A second scorer is two answers.
4. **Its own CI workflow.** Credential-free checks run on every push; anything
   needing secrets is manual until it has been trusted for several cycles.
5. **Add a coverage line for it in `render-dashboard.py`'s coverage box —
   present from the day the source is registered, not gated on whether it
   has ever produced a run.** Nexcess got a real `source` in the ledger on
   2026-08-19 and no coverage line, because the box only appended a line
   `if "<source>" in latest`. A source with zero runs is never `in latest`,
   so the box listed three sources and stayed silent about the fourth — a
   new viewer had no way to tell "not covered" from "not built". Base the
   denominator on the **inventory** (which sites this source is expected to
   reach), never on ledger rows, so the line reads "0 of N" honestly before
   the first run and moves the moment a real scan lands. See the Nexcess
   block in `render-dashboard.py` for the pattern to copy.

The ledger, diff, dashboard and **severity** need no changes for a new provider
beyond the five steps above. They are keyed on site identity, not on host or
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
`data/fleet-inventory.json` is the **inventory**: 85 sites keyed on domain,
human-owned, edited by hand, holding the join key and the `production` flag.
`history/*.jsonl` is the **ledger**: append-only observations, one row per tool
per site per run, nothing typed by a person. The workbook holds *claims*; the
ledger holds *measurements*; the dashboard shows both and labels which is which.

- **`history/` must NOT be gitignored.** It is the only asset here that cannot
  be regenerated.
- **`history/components.jsonl` is a fourth file, not a fourth source.** Added
  2026-08-23. Written by the same `health` run under the same `run_id`, it
  holds one row per site per installed plugin, mu-plugin and theme. It is
  separate from `observations.jsonl` because that ledger diffs SCALAR facts,
  and a 40-element list per site would either be diffed element-wise -- every
  routine version bump becoming fleet news -- or stored as a blob nothing can
  query. A site that could not be inventoried produces NO ROWS and records
  `components_checked: false`; zero rows and "runs nothing" are different
  answers. See `docs/DATA-MODEL.md` section 2b.
- **`reports/` IS gitignored**, so it does not exist on a fresh clone or a CI
  runner. Anything reading it must tolerate its absence, and **no test may
  assert a fleet size against it.**
- **Ingest is append-only, so a mis-keyed row cannot be corrected in place.**
  A missing inventory is a hard error for this reason.

---

## The page, since 2026-08-27

`render-dashboard.py --out` writes the **evidence matrix**: one row per site,
one column per question, absence hatched, every column header carrying its own
denominator, a Schedule tab that arranges the backlog by decision, and a banner
whose green state is scoped and whose predicate is printed under it. Chosen by
Doug from three rendered concepts (`_scratch/redesign/`, `docs/DASHBOARD-V3.md`).
The previous page is `render()` behind `--legacy-out` for one cycle.

- **The page never says "all good".** The dev team asked for it; on this fleet
  it would be false for months. The banner says "Nothing needs a person" and
  states the backlog and the unmeasured count in the same sentence. Two tests
  assert the phrase is absent. Do not add it back under another wording.
- **`scripts/dashboard/page.js` computes no status and holds no threshold.**
  It groups and counts what `severity.py` decided, read from the JSON the
  renderer embeds. The "what happens next" lane is a display grouping and must
  never move into `severity.py`; `test/test-page.py` asserts both.
- **An absence is a shape.** `null`, `"unknown"` and `"n/a"` each render as a
  hatched or dotted token with the word in it, never a number, never green.
  A Nexcess backup cell says `no API`: unmeasurable, which is not unmeasured.
- **The page's model is the feed's.** `page_data()` and `emit_data()` are built
  from one `m`; the test compares every status, reason code and fact.
- **The DOM test is not in CI.** It needs Chromium on the publish runner, a
  cost to decide on, not add silently. Run `node test/test-page.mjs` by hand
  before a publish until then. `publish-dashboard.sh` runs the offline test.

---

## Severity

`scripts/lib/severity.py`, and **nowhere else**. **The Pantheon scanner was a
second scorer until 2026-08-27** and had drifted three weeks behind; it now
pipes its rows through `scripts/score-scan.py`, which calls this module. Do
not add severity rules to a scanner. See the bug table. A pure function of observed
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
./scripts/pantheon-fleet-healthcheck.sh --no-fail-on-crit             # scan (full)
./scripts/pantheon-fleet-healthcheck.sh --api-only --no-fail-on-crit  # no SSH
./scripts/diagnose-wp-calls.sh cm-whitelabel sgroilawley.com          # item 22: did the WP-CLI calls actually run?
                                                                      # also the cheap way to settle the post-smtp option key on one real site
./scripts/nexcess-fleet-healthcheck.sh --dry-run                      # who would the SSH scan connect to?
./scripts/nexcess-fleet-healthcheck.sh --sites eamusicfest.com        # one site, real
./scripts/fleet-nexcess.py probe                                      # confirm the base URL
./scripts/fleet-nexcess.py discover --stamp "$(date -u +%Y-%m-%d_%H%M)"
node scripts/consent/run-sweep.mjs --stamp "$(date -u +%Y-%m-%d_%H%M)"  # needs npm i
./scripts/fleet-ledger.py ingest --reports ./reports --history ./history
./scripts/render-dashboard.py --out fleet.html \                    # the evidence-matrix page (docs/DASHBOARD-V3.md)
    --components-out components.html                                  # both pages
./scripts/nexcess-ssh-targets.py --history ./history                   # who does the SSH scan connect to, and as whom?
./scripts/check-worker-exposure.py                                    # is any Worker reachable without Access?
./scripts/check-access-policies.py --who someone@clevermethod.com     # which apps can this person open?
./scripts/check-access-policies.py --expect data/access-expectations.json
./scripts/publish-dashboard.sh --dry-run                              # preview
./scripts/serve-dashboard.py --dir ./reports --open                   # live view
```

`render-fleet-dashboard.py` (v1) and `render-dashboard.py` (v2) are **both
current**. v1 feeds the live local view that fills in while a scan runs; v2
reads the ledger and is what gets published. Do not delete either.

---

## Testing

```bash
python3 test/test-score-scan.py       # 27   offline, no scan
python3 test/test-consent-rulings.py  # 17   offline, no network
python3 test/test-nexcess-ssh.py      # 43   offline, no key
python3 test/test-worker-exposure.py  # 48   offline, no network
python3 test/test-workflows.py        # 56   offline; the CI concurrency contract
python3 test/test-access-policies.py  # 46   offline, no token
python3 test/test-ledger.py       # 319
python3 test/test-severity.py     # 150
python3 test/test-page.py         #  35   offline; the page's model is the feed's, never "all good"
node test/test-page.mjs           #  42   headless Chromium; the rendered DOM. Needs `npm install`
python3 test/test-email-dns.py    #  65   (needs dnspython)
python3 test/test-build-inventory.py #  6  offline; the seed generator REFUSES an existing inventory
python3 test/test-nexcess.py      #  96   offline, no API call
python3 test/test-consent.py      # 126   offline, no browser
node test/test-gating-window.mjs  #  20   headless Chromium + a local fixture
                                  #       server; the gating window's two
                                  #       boundaries. Verified to FAIL against
                                  #       the v2 window before v3 existed
python3 test/test-wp-calls.py     #  48   offline, drives the mock
./test/run-local-test.sh          #  62   1-3 min, silent, two mock sites hang
                                  #       on purpose. Never run it through the
                                  #       device bridge: 45s timeout.
```

- **The counts above are as of 2026-08-28 and drift every session.** Five of
  them were wrong the day after they were last refreshed. They are a smoke
  signal, not a contract; CI asserts the suites PASS, never that they hold a
  particular number. Correct them when you notice, do not trust them.
- **Every offline suite runs in CI on every push** since 2026-08-28,
  `.github/workflows/offline-tests.yml` — including the two Chromium suites,
  whose install step is the one fleet-consent.yml already ran. Before that,
  597 of ~1,000 assertions (severity and ledger entire) had no CI path at all.
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

THIS IS CRITICAL:

Use simple, direct, professional language.

Prefer short sentences and short paragraphs. State the important point first.

Avoid literary phrasing, rhetorical flourishes, metaphors, clever turns of phrase, dramatic framing, and sophisticated-sounding prose when plain language will do.

Avoid phrases such as “the thing worth your attention,” “worth saying plainly,” “the argument for,” “what this really tells us,” or similar editorialized constructions.

Write like an experienced colleague explaining something clearly and efficiently.

Do not add introductory or concluding prose unless it adds useful information.

Comments in code explain **why**, especially why something non-obvious is the
way it is. Most comments in this repo name a specific failure. Keep that.

for Doug, provide explicite direction when a command is to be run. provide the exact command and sequence.
