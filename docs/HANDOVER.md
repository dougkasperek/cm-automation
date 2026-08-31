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

**The other four Workers on the same Cloudflare account.** Measured 2026-08-24
and recorded in `docs/DASHBOARD.md`: `cm-fleet`, `[removed]`, `[removed]`, `[removed]`
and `[removed]` share one account, one zone (`thudstaff.com`) and one Access
login domain. Only `cm-fleet` is part of this handover.

`[removed]` in particular holds [removed], [removed] and the ownership
discussion. It is deliberately on a different Access policy (`[removed]`) from the
fleet page (`fleet viewers`) so that the developers who need the dashboard
cannot reach it by editing the subdomain. **Any Cloudflare work done during this
handover must preserve that separation**, and `scripts/check-access-policies.py`
with `data/access-expectations.json` is what proves it still holds.

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
| Will anything start running by itself after transfer? | **No.** Every `cron:` block in all nine workflows is commented out | `grep -rn "^\s*-\s*cron" .github/workflows` returns nothing |
| Does the deployed Worker match the repo? | **Yes.** All five routes present including `/vulnerabilities`; no write route; no `PUT /api/publish` | Cloudflare MCP `workers_get_worker_code` on `cm-fleet` |
| How big is the transfer? | `.git` is 31M, 264 commits, two authors (Doug and the Actions bot) | `du -sh .git`, `git log` |

**A GitHub org transfer carries all of that.** Commits, branches, tags, issues,
PRs, and a redirect from the old URL. **It does not carry the Actions secrets or
variables.** Those are recreated by hand -- see step 2 below.

Because the history is clean, **no history rewrite is needed**. That is the
expensive branch this handover gets to skip, and it was checked rather than
assumed.

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

**A stale copy of this repo sits in iCloud.** *Cowork Automation Portfolio/
cm-automation*: 44 files, every one dated 2026-08-18, no `.git`, 264 commits
behind. Delete it before handover. This project has been burned twice by a
second copy nobody was looking at -- the gitignored `ci/github-actions/` mirror
and the project-memory note above.

**A Google service-account key is loose in that same iCloud folder**
(`cm-agent-integrations-*.json`). Not part of the transfer, but it is a
credential in a synced directory and this is the moment to deal with it.

---

## 8. Housekeeping in the repo itself

```bash
cd ~/dev/cm-automation && git worktree remove .claude/worktrees/xenodochial-yalow-3aa7b7 && git branch -d claude/xenodochial-yalow-3aa7b7
```

That branch is merged into `main` with no unique commits (checked with
`git branch --merged main`); the worktree is a leftover session artifact.

`_scratch/` is **tracked** -- 24 files including four full redesign concepts and
a model dump. It is the record of why the v3 page looks the way it does, which
is worth keeping, but it is the largest source of "what is this?" for a new
reader. Either move it under `docs/` with a README, or say in `README.md` that
it is an archive.

---

## 9. Open, and honestly unverified

- **Whether the R2 bucket contents are backed up anywhere.** The pages are
  regenerable from the ledger, so this is low stakes, but nobody has said it out
  loud.
- **Whether anyone besides Doug has run a full scan end to end.** Every green CI
  run is evidence the pipeline works; none of it is evidence a second person can
  drive it. That is the first thing worth doing after the seats exist, and it is
  the real test of whether this handover worked.
