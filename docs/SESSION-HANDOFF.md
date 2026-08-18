# Fleet automation: handoff for the next session

**Written 2026-08-18.** Chats share this folder and project memory, never each
other's conversation history, so everything needed to resume is written down.

**This supersedes `DESIGN-BRIEF.md`**, which was the equivalent file for the
previous session and is now historical.

---

## The goal, in Doug's words

> "I want a dashboard to view the automation data, not an XLS. The dashboard
> will eventually replace the xls."

Everything below serves that. The dashboard is the destination; the scans and
the ledger are how it gets fed.

Two decisions that follow from it, both made 2026-08-18:

- **Read-only for now.** Attestations, SSO and an audit trail come later, once
  it is in production. So access control is entirely Cloudflare Access at the
  edge and the app needs no auth of its own.
- **Hosting is Cloudflare.** Platform for CI is **GitHub Actions**; Azure DevOps
  is off the table.

---

## Where things actually stand

### Working and proven

| thing | state |
|---|---|
| Repo | **live**, `github.com/dougkasperek/cm-automation`, private |
| Email DNS check, 78 sites | **green in GitHub Actions**, 26s, artifact uploaded |
| Pantheon health scan, 52 sites | works locally, **api-only**, zero errors |
| Unified 84-site inventory | built. The domain-to-machine-name join key |
| Ledger | both tools feeding one history, one site = one timeline |
| Dashboard | built, verified in both colour schemes, filters work |
| Tests | `test-ledger.py` **73**, `test-email-dns.py` **58**, both offline |

### Uncommitted on Doug's Mac right now

```
 M README.md
 M fleet.html
 M scripts/render-dashboard.py
?? docs/SECRETS-ADDENDUM.md
?? docs/SSH-KEY-SETUP.md
```

**First action in the next session: get these committed.** They are the backup
label fix, the WP columns, and the SSH guide.

---

## The immediate next step

**Turn on full mode.** `docs/SSH-KEY-SETUP.md` is a step-by-step Doug can
follow.

It is the only missing credential. Four checks currently read *not checked* on
all 52 Pantheon sites: WordPress core update pending, plugin updates, theme
updates, administrator count. The scan code, the workflow's SSH handling and the
dashboard columns are all already built and tested.

**The single most important thing it could surface:** the workbook asserts
WordPress **7.0.2 on all 78 sites** and nothing has ever verified it on any of
them. One month after `wp2shell`, an RCE whose only fix was that upgrade, a site
that is not on 7.0.2 is the finding that justifies this whole project.

After that, in order:

1. **Deploy the dashboard to Cloudflare.** Worker and R2 code exist in
   `ci/cloudflare/cm-fleet-worker.js`, never deployed. Needs its own hostname
   (suggest `fleet.thudstaff.com`) and **its own Access policy** — the deck's
   allowlist is partners-only and must not include developers. Tor and a
   developer have both asked for this.
2. **Nexcess**, deliberately after the SSH key: 46 sites versus 21, and Nexcess
   Managed WordPress also has SSH plus WP-CLI, so the deep-scan code written for
   Pantheon is what Nexcess reuses. The one genuine unknown is site enumeration;
   its API endpoint needs ten minutes with a token in hand.
3. **Wire the dashboard render into CI** so it regenerates per run.

---

## Three things that need a person, not code

None of these are blocked on any of the above.

1. **21 Nexcess sites have no `wp2shell` verification.** They are the only blanks
   in that column; every Pantheon and every outlier-host site says Yes. The
   event log explains why: Pantheon shipped audit scripts, other hosts needed a
   manual check, and nobody got there. This is the largest open evidence gap.
2. **`hoffmanscheese`** is in Pantheon but in nobody's audit. **`hoosierfeeder.com`**
   is in the audit but Pantheon does not return it. Both are five-minute answers
   from whoever knows the fleet.
3. **`shuman-plastics.com` and `dynapurge.com`** on Flywheel run PHP 7.4,
   unpatched since November 2022. Client-controlled hosting, so it is a client
   conversation.

---

## Traps. Each of these cost real time already

- **Pantheon rejects ed25519 SSH keys.** Use RSA 4096. A rejected key looks like
  an auth failure, not a key-type failure.
- **Claude cannot run `git commit` through the Cowork device bridge.** It cannot
  delete `.git/index.lock`, so `git add` succeeds and `commit` then fails and
  leaves the repo locked. Claude edits files; Doug runs git.
- **`reports/` is gitignored**, so it does not exist on a fresh clone or a CI
  runner. Anything reading it must tolerate its absence. This broke CI run #1.
- **`history/` must NOT be gitignored.** The ledger is the one asset that cannot
  be regenerated.
- **GitHub's "Re-run jobs" replays the original commit.** It will not pick up a
  fix. Use **Run workflow** for a fresh run.
- **`.github/` cannot be written by the bridge**, so workflow edits land in
  `ci/github-actions/` and Doug copies them across. That staging directory is
  gitignored so a second diverging copy never gets committed.
- **The dashboard's light-mode palette is only legal because every state chip
  carries a text label.** Render a chip as a bare dot and the contrast relief is
  gone. Re-run the dataviz validator before touching colour.

---

## A recurring bug class worth naming

Four separate times this session, a number read confidently and was wrong:

| where | what it said | what was true |
|---|---|---|
| the scan's `plugin_updates: 0` | no plugin updates pending | nobody looked |
| the email checker on a DNS timeout | no SPF record | the lookup failed |
| `standing()` in the dashboard | 1 site affected | 48 |
| the dashboard's `BACKUP: 0` | no backups | backed up **today** |

Every one was a confident-looking value standing in for an absence or a
misreading. **The last was caught by Doug on first contact, and the third only
by rendering the page and looking at it.** When adding a column, ask what it
shows when the answer is unknown, and whether a reader could take it to mean the
opposite.

---

## Read these, in this order

| file | what it holds |
|---|---|
| `docs/DATA-MODEL.md` | the inventory and ledger the dashboard reads. Start here |
| `docs/DASHBOARD-V2.md` | the dashboard, and why there are two renderers |
| `docs/SSH-KEY-SETUP.md` | the immediate next step |
| `docs/AUDIT-SHEET-ANALYSIS.md` | the manual workbook, per-column, and Nexcess |
| `docs/EMAIL-DNS.md` | the recovered Pass/Fail rule and three bugs |
| `docs/DESIGN-REVISIT.md` | the ledger-not-scanner reframe |
| `docs/GIT-SETUP.md`, `docs/RUNBOOK.md`, `docs/SECRETS.md` | mechanics |

Project memory carries the same material in shorter form. `MEMORY.md` indexes it.

---

## Open, undecided

- **Does CI commit the ledger back to the repo?** Currently no: the workflow asks
  only for `contents: read`. That means CI history is 90-day artifacts rather
  than permanent. Revisit after several clean runs.
- **Which GitHub account or org long term.** `dougkasperek` is personal. If Matt
  or the developers need the fleet data, an org may fit better. Same tension as
  Cloudflare Access, where developers need the fleet view but must not get the
  [removed].
- **Whether the two renderers ever merge.** Only if the live "watch a scan fill
  in" view is taught to read the ledger mid-scan. Not needed yet.
