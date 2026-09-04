# Handover: moving cm-automation to clevermethod

**Written 2026-08-31.** Every number in this file was measured the day it was
written, with the command that produced it named beside it. Where a figure came
from an earlier session it says so and carries that session's date.

This is the operational handover: what moves, what does not, in what order, and
what the receiving team will trip over. It is not an introduction to the
project -- that is `README.md`, then `CLAUDE.md`.

---

## 1. What is being handed over

| thing | where it lives today |
|---|---|
| the repo, all 264 commits | `github.com/dougkasperek/cm-automation`, private |
| the ledger -- 20,645 rows across four files | `history/*.jsonl`, in the repo, **not regenerable** |
| the inventory -- 85 sites | `data/fleet-inventory.json`, hand-owned |
| the dashboard | `fleet.thudstaff.com`, served by the `cm-fleet` Worker out of R2 |
| six CI secrets and three variables | GitHub Actions, on the repo |

## 2. What is NOT being handed over, and must not be swept along

**Other Workers on the same Cloudflare account.** The account hosts unrelated
applications that share one zone (`thudstaff.com`) and one Access login domain.
**Only `cm-fleet` is part of this handover**, and some of the others are on a
deliberately separate Access policy so that the people who need the fleet
dashboard cannot open them by editing the subdomain.

**Any Cloudflare work done during this handover must preserve that
separation.** Verifying it needs the Access policy tooling, which was removed
from this repo on 2026-08-31 along with its expectations file -- both named
applications and individuals outside this project's scope. They are kept
outside the repo; ask Doug.

This repo's own perimeter check, `scripts/check-worker-exposure.py`, was
narrowed to `cm-fleet` the same day. It proves no stranger can reach the fleet
page. It says nothing about the rest of the account, by design.

**The marketing work.** It is not in this repo and never has been. Verified
2026-08-31: all 142 tracked files are fleet work. The partner deck, service
concepts, SOW templates, Harvest exports, GA4 puller and ops-dashboard Workers
live in the iCloud folder *Cowork Automation Portfolio*, outside git. Nothing
needs splitting.

---

## 3. What was checked before the transfer

All measured 2026-08-31 unless stated.

| question | answer | how |
|---|---|---|
| Does any commit contain a credential? | **No.** The only match is prose in `docs/SSH-KEY-SETUP.md` explaining what a key file looks like | `git log --all -p` piped through a pattern set covering private keys, `ghp_`/`github_pat_`, AWS, Slack, certificates |
| Is the working tree clean and pushed? | Yes, `main` == `origin/main` | `git status --short`, `git ls-remote origin main` |
| Will anything start running by itself after transfer? | **Yes, two, since 2026-09-03.** The vulnerability probe daily at 11:37 UTC and the worker exposure check every six hours. The other four `cron:` blocks are commented out. Both scheduled workflows need the org's secrets and variables in place before their first run there, or the probe fails at "Confirm the key is present" and the exposure check fails to reach the Worker | `grep -rn "^\s*-\s*cron" .github/workflows` |
| Does the deployed Worker match the repo? | **Yes.** All five routes present including `/vulnerabilities`; no write route; no `PUT /api/publish` | Cloudflare MCP `workers_get_worker_code` on `cm-fleet` |
| How big is the transfer? | `.git` is 31M, 264 commits, two authors (Doug and the Actions bot) | `du -sh .git`, `git log` |

**A GitHub org transfer carries all of that.** Commits, branches, tags, issues,
PRs, and a redirect from the old URL. **It does not carry the Actions secrets or
variables.** Those are recreated by hand -- see step 2 below.

Because the history holds no credential, **no history rewrite is needed on
security grounds**. That was checked rather than assumed.

**Measured again 2026-09-03, because the 2026-09-01 handoff said the opposite
and both could not be right.** They were answering different questions. No
commit holds a credential, as above. The history DOES still hold what the
2026-08-31 scoping commit (`7faf6c7`) cut from the working tree: the
"Access: what is configured" section of `docs/DASHBOARD.md` (110 lines, one
hostname, no email addresses, six lines naming a person), 1,813 lines of this
handoff's tail naming other Workers' bindings and secret NAMES and a D1 id,
and the other Workers' entries in the exposure check. One colleague's email
address is in history and gone from the tree. **The six-name access map was
never in git at all**: `data/access-expectations.json`, its checker and its
test have no commit under any path, so the 2026-09-01 claim that history
holds "six colleagues' names" from that file is wrong. What history holds is
infrastructure detail about Workers that are not this project's, plus a few
names in prose. **Doug's decision, 2026-09-03: leave the history as it
is.** No rewrite before the transfer. Recorded so the next session does not
reopen it; the measurement above is what the decision was made on.

---

## 4. Step 1 -- the GitHub transfer

Matt has to grant repository-creation rights in the `clevermethod` org first, or
the target will not be selectable in the transfer dialog.

1. Settings -> Danger Zone -> **Transfer ownership** -> `clevermethod`.
2. Recreate the six secrets. They cannot be read back out of the old repo; each
   has to come from its own source.

   | secret | source |
   |---|---|
   | `PANTHEON_MACHINE_TOKEN` | Pantheon, Account -> Machine Tokens |
   | `PANTHEON_SSH_KEY` | the runner key -- see `docs/SSH-KEY-SETUP.md` |
   | `NEXCESS_PORTAL_API_TOKEN` | Nexcess portal |
   | `NEXCESS_SSH_KEY` | the Nexcess account key -- see the security note below |
   | `WF_KEY` | Wordfence Intelligence |
   | `CLOUDFLARE_API_TOKEN` | Cloudflare, scoped to Workers R2 Storage: Edit on ONE account |

3. Recreate the three variables: `CLOUDFLARE_ACCOUNT_ID`,
   `NEXCESS_PORTAL_API_URL`, `FLEET_PUBLISH_URL`.
4. Point your local clone at the new remote:

   ```bash
   cd ~/dev/cm-automation && git remote set-url origin https://github.com/clevermethod/cm-automation.git
   ```

5. Run one workflow by hand and confirm it goes green before trusting the rest.

**Treat the transfer as the moment to rotate `NEXCESS_SSH_KEY`, not to copy
it.** `CLAUDE.md` records why: Nexcess has no read-only SSH user, so that one
account-level credential has read *and write* on all 21 site filesystems, and
the command list in `scripts/nexcess-fleet-healthcheck.sh` is the only thing
making the tool read-only. Handing over a write-capable key is a good moment to
issue a new one and retire the old.

---

## 5. Step 2 -- the strings that change, and when

Three references to the personal account are baked into files. **Two of them
must change at transfer time, not before** -- changing them early breaks the
thing they point at.

| file | what it says | when to change it |
|---|---|---|
| `scripts/run-all-fleet-scans.sh` | now derives the repo from `git remote`, so it needs no edit | done 2026-08-31 |
| `scripts/check-worker-exposure.py:95` | `SUBDOMAIN = "doug-kasperek.workers.dev"` | only when Cloudflare moves (step 3), not with the repo |
| `test/test-worker-exposure.py:82` | asserts the `doug-kasperek.cloudflareaccess.com` login host | same -- it will correctly fail the moment the account changes |

Docs naming the old repo URL -- `docs/GIT-SETUP.md`, `docs/DO-THIS-NEXT.md`,
`docs/SESSION-HANDOFF.md` -- are prose and can be corrected at leisure.
`docs/GIT-SETUP.md` describes *creating* this repo and is now history; say so at
the top of it rather than deleting it.

---

## 6. Step 3 -- Cloudflare, which is a separate piece of work

**Do not attempt this at the same time as the GitHub transfer.** They are
independent, and this one depends on a permission grant from someone else.

`docs/DASHBOARD.md`, section "Which Cloudflare account, and what it can do",
measured this on 2026-08-23 and it is still the controlling document. The short
version:

- Everything -- all five Workers, the `dash-data` bucket, the `thudstaff.com`
  zone, every Access application -- is in **Doug's personal Cloudflare account**.
- On the clevermethod, Inc. account Doug holds **Administrator Read Only**.
  Every write in a migration fails there regardless of what API token is used.
  A Super Administrator on that account must first grant **Workers Platform
  Admin**, **Cloudflare R2 Admin** and **Cloudflare Zero Trust**.
- **Access applications and policies do not transfer.** They are per-account
  Zero Trust objects and get rebuilt against whatever identity provider
  clevermethod, Inc. uses. That also changes the login hostname for all five
  applications at once, which is a reason to do it deliberately rather than
  twice.
- Moving to `fleet.clevermethod.net` is not a route change. Cloudflare will not
  attach a Worker to a zone its account does not own, so the Worker has to be
  deployed **into** clevermethod, Inc.: new R2 bucket, new API token, new
  GitHub secrets.

**The interim state, named plainly:** if the repo moves and Cloudflare does not,
the team's dashboard runs on Doug's personal Cloudflare account, published by
his personal API token stored in the org's repo. That works. It is not a
finished handover, and it should have a date on it rather than becoming the
arrangement by default.

---

## 7. What the receiving team will trip over

**The documentation is 12,240 lines and none of it is onboarding.** `CLAUDE.md`
is 946 lines of accumulated rules and mistakes; `docs/SESSION-HANDOFF.md` is
2,729 lines of session continuity. Both are worth keeping and neither answers
"what is this and how do I run it" in under an hour. The gap is a short
`docs/ONBOARDING.md`; `docs/SESSION-HANDOFF.md` should be marked as an archive
of how the project got here rather than as a document anyone reads front to back.

**Six pointers reference project-memory files that do not exist.** Claude
project memory is per-user and outside git, so even a file that does exist on
one machine is invisible to everyone else. Verified 2026-08-31: the memory
directory holds `MEMORY.md` and six preference notes, and none of the six named
files is among them.

| file | points at |
|---|---|
| `docs/DESIGN-BRIEF.md:27-29` | `fleet_dashboard.md`, `cicd_workflow_migration.md`, `terminus_council_initiatives.md` |
| `docs/SESSION-HANDOFF.md:1984,2000` | `fleet_axes.md`, `fleet_coverage_guard.md` |
| `docs/VULN-INTEL-REVIEW.md:294` | `fleet_nexcess.md` |

`CLAUDE.md` already ruled on this once, about `fleet_cloudflare_access.md`:
measured infrastructure state goes in the repo, because the copy nobody can see
is the copy that loses. These six are the same finding, unfixed. Each needs
either a repo document to point at instead, or the sentence deleted. Two more
in `scripts/run-all-fleet-scans.sh` were removed on 2026-08-31, along with two
stale claims in the same header: that Nexcess is "blocked upstream (Cloudflare
challenges the portal API)", resolved 2026-08-25 when the challenge turned out
to be ours, and that the publish-side coverage-drop guard does not yet exist --
it does, in `scripts/publish-dashboard.sh`.

**~~A stale copy of this repo sits in iCloud.~~ Deleted 2026-08-31.**
*Cowork Automation Portfolio/cm-automation*: 44 files, every one dated
2026-08-18, no `.git`, 264 commits behind. Checked before deleting: ten files
were not in the repo's object store, and all ten were disposable -- two
`__pycache__` artifacts and eight `reports/` files from scans that **are** in
the ledger (`health-2026-08-16_1725`, `health-2026-08-17_0726`,
`email-dns-2026-08-17_1545`). Moved to `~/.Trash`, not shredded, if anyone
wants to check that reasoning. This project has been burned twice by a second
copy nobody was looking at -- the gitignored `ci/github-actions/` mirror and
the project-memory note above.

**A Google service-account key is loose in that same iCloud folder**
(`cm-agent-integrations-*.json`). Not part of the transfer, but it is a
credential in a synced directory and this is the moment to deal with it.

---

## 8. Housekeeping in the repo itself

**Done 2026-08-31:** the leftover `claude/xenodochial-yalow-3aa7b7` branch and
its worktree under `.claude/worktrees/` are removed. `git worktree remove`
refused it for holding modified and untracked files, which was worth stopping
for: it carried the CVSS banding work in `scripts/fleet-vuln.py` and two new
test files. All of it had already landed on `main` -- the test files byte
identical, `BANDS`/`UNKNOWN_BAND`/`band()` present in
`scripts/fleet-vuln.py:580`, and every line it added to `CLAUDE.md` present
there too. Verified before forcing, not after.

**Still open.** `_scratch/` is **tracked** -- 24 files including four full redesign concepts and
a model dump. It is the record of why the v3 page looks the way it does, which
is worth keeping, but it is the largest source of "what is this?" for a new
reader. Either move it under `docs/` with a README, or say in `README.md` that
it is an archive.

---

## 9. A site that leaves the fleet has nowhere to go

**Found 2026-09-01, by measuring rather than reasoning.** Three Pantheon
Sandbox sites were deleted from the host that day. There is no state in this
repo that means "gone", and the two consequences both point the wrong way.

**A deleted site renders forever, as UNKNOWN.** Measured against the real run
of 2026-09-01, which is the correction to what this section said first: all
**85 sites still render**, and the three deleted ones read **UNKNOWN** with no
reasons -- not, as a simulation written the same hour predicted, frozen at the
CRIT, SKIP and FROZEN they last scored. They are excluded from the counted
totals, so the headline is right; `excluded` carries `UNKNOWN: 3`.

The first version of this paragraph was written from that simulation and
stated in the same voice as a measurement. It was wrong within the hour, on
this repo's own cardinal rule. The real behaviour is milder in one way -- no
permanent stale CRIT -- and wrong in another that matters more: **UNKNOWN
means "no scan has reached this site", and these sites are not unreached, they
are gone.** An absence standing in for a different absence.

Deleting the inventory record is not the fix. The ledger is append-only and
holds observations under those `site_id`s, so removing the record makes them
**orphans** -- the renderer says so and `--strict` refuses. That is the
signature of the mis-keying bug that once rendered an 84-site fleet as 130
rows, and it is the right guard. The rows were kept on purpose.

**And a decommission looks exactly like a failed scan.** The last Pantheon run
measured **48 of 52**; the next measures **47 of 49**. `coverage_regressions`
trips on any drop in the same mode -- the test is `c >= p` or nothing -- so
`persist-ledger.sh` refuses at ingest and `publish-dashboard.sh` refuses at
publish. Correct behaviour: the guard cannot tell "we deleted three sites" from
"the scan lost three sites", and it exists because two bad consent runs once
replaced a good one on the live page for a day.

**The one-time workaround**, needed on the next Pantheon dispatch only. After
that run lands, 47 is the baseline and later runs are clean:

```bash
gh workflow run pantheon-fleet-healthcheck.yml -f run_mode=full -f target_env=live -f fail_on_crit=false -f persist_ledger=true -f publish_dashboard=true -f allow_coverage_drop=true
```

**The real fix is a `retired` ruling**, alongside `production`. It would let
the guard drop those sites from the denominator instead of reporting a loss,
and let the page render them as retired rather than as a CRIT that never
improves. It is a ruling, not a measurement -- no scan can tell a deleted site
from an unreachable one, which is the whole reason `production` is a human
field too.

Two traps for whoever builds it, both already paid for elsewhere in this repo:

- **It is not `production: false`.** That means "not a production site", and
  `cm-whitelabel` uses it correctly while still existing. Folding the two
  loses the distinction the moment anyone asks which of these sites are still
  running.
- **A retired site must not read as clean.** Whatever the page shows, it must
  not be a green cell or an absence: the site's last known state was a real
  measurement and the reason it stopped is a ruling. Unknown is a value.

## 10. Open, and honestly unverified

- **Whether the R2 bucket contents are backed up anywhere.** The pages are
  regenerable from the ledger, so this is low stakes, but nobody has said it out
  loud.
- **Whether anyone besides Doug has run a full scan end to end.** Every green CI
  run is evidence the pipeline works; none of it is evidence a second person can
  drive it. That is the first thing worth doing after the seats exist, and it is
  the real test of whether this handover worked.
