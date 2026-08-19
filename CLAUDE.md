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
| **Nexcess** | **next.** 21 sites, zero coverage. `docs/NEXCESS-ARCHITECTURE.md` |
| **Cookie consent monitor** | **next.** Exists standalone; joining the suite |
| Asana routing | not built. The missing shared plumbing |

**The scoreboard is the UNKNOWN count on the dashboard** — sites no scan has
ever reached. It is 32 today. That number falling is what progress looks like.

**Every rule below cost something to learn.** Nothing here is general good
practice; it is all scar tissue. If a rule seems obvious, read the sentence
after it.

---

## Hard boundaries

**This tool never changes a client site.** No updates, no writes, no
remediation. Applying updates stays human-gated until the read-only scan has
been trusted for several cycles. There is no write path and adding one is a
product decision, not an implementation detail.

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

**Only two were caught by code. The rest were caught by a person looking at a
rendered page or a raw number.**

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
   silent and unrecoverable.
3. **Add severity codes to `scripts/lib/severity.py`.** Same vocabulary, same
   module. A second scorer is two answers.
4. **Its own CI workflow.** Credential-free checks run on every push; anything
   needing secrets is manual until it has been trusted for several cycles.

The ledger, diff, dashboard and renderer need no changes for a new provider or
a new check. They are keyed on site identity, not on host or tool.

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
python3 test/test-severity.py     #  68
python3 test/test-email-dns.py    #  58   (needs dnspython)
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
