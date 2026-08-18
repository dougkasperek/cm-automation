# Moving cm-automation into git

Target: **https://github.com/dougkasperek/cm-automation**, private.

## Why the move is a prerequisite, not cleanup

The repo currently lives under `DK Sandbox/claude/Cowork Automation Portfolio`,
which is **iCloud Documents**. iCloud syncing a `.git` directory produces
conflict files and index corruption. Running `git init` in place is asking for
trouble later, at the worst possible moment.

`~/dev` is not a folder this session can see, so this part is yours to run.

## Sequence

```bash
# 1. Move out of iCloud. Copy first, delete the original only once you are happy.
mkdir -p ~/dev
cp -R "$HOME/Library/Mobile Documents/com~apple~CloudDocs/DATA/clevermethod/DK Sandbox/claude/Cowork Automation Portfolio/cm-automation" ~/dev/cm-automation
cd ~/dev/cm-automation

# 2. Dependencies. openpyxl is already present on this Mac; dnspython is not.
pip3 install -r requirements.txt

# 3. Prove it works from the new location before committing anything.
python3 test/test-ledger.py        # 43 assertions
python3 test/test-email-dns.py     # 45 assertions, offline

# 4. The workflow file has to live in .github/workflows/. It is kept in
#    ci/github-actions/ only because the Cowork device bridge refuses to write
#    under .github/. Once this is in git that constraint is gone, so move it
#    and delete the duplicate.
mkdir -p .github/workflows
git mv 2>/dev/null || true
mv ci/github-actions/fleet-email-dns.yml .github/workflows/
mv ci/github-actions/pantheon-fleet-healthcheck.yml .github/workflows/ 2>/dev/null || true
rmdir ci/github-actions 2>/dev/null || true

# 5. Init and first commit.
git init -b main
git add -A
git status          # LOOK at this before committing. reports/ should be absent,
                    # history/*.jsonl should be present.
git commit -m "Initial import: fleet health scan, ledger, email DNS check"

# 6. Create the private repo and push.
#    With the gh CLI:
gh repo create dougkasperek/cm-automation --private --source=. --remote=origin --push
#    Or by hand: create it empty at https://github.com/new (private, no README),
#    then:
# git remote add origin git@github.com:dougkasperek/cm-automation.git
# git push -u origin main
```

## Check `git status` before that first commit

Two things to confirm:

- **`reports/` is ignored.** That was already true in the old `.gitignore` and
  it still is. Raw scan output is regenerable and CI keeps it as an artifact.
- **`history/` is NOT ignored.** The ledger is the one thing here that cannot be
  regenerated. If `history/observations.jsonl` does not appear in
  `git status`, the ignore rule is wrong and needs fixing before the commit.

## Keep it private

It holds fleet security posture data for 78 client sites. Private also avoids a
GitHub trap: scheduled workflows are auto-disabled after 60 days of repository
inactivity, but only on **public** repos. A daily ops job on a repo nobody
commits to would eventually just stop.

## One decision this forces

The design keeps the ledger as append-only JSONL in git. That works cleanly for
local runs. For **CI** runs it raises a question that has not been answered yet:

**Does the CI job commit the updated ledger back to the repo?**

- **Yes**: history accumulates automatically and the repo stays the single
  source of truth. Costs `permissions: contents: write` and a bot commit per
  run, which also solves the 60-day inactivity problem as a side effect.
- **No**: CI runs produce artifacts only, and the ledger only grows when you run
  locally. Simpler and safer, but then CI history is 90-day artifacts rather
  than a permanent record.

The current workflow is written the **No** way, because it only asks for
`contents: read` and a first CI job should not have write access to its own
repo. Worth revisiting once a few runs have been reviewed.

## After the push

```bash
# Pantheon machine token, for the health check workflow.
gh secret set PANTHEON_MACHINE_TOKEN --repo dougkasperek/cm-automation

# The email DNS workflow needs no secret at all. Run it first.
gh workflow run "Fleet Email DNS Check" --repo dougkasperek/cm-automation
```

Run the email job before the Pantheon one. It has nothing to authenticate, so a
red run can only mean a runner, network or workflow problem. If it is green and
the Pantheon job is red, the machine token is the answer without guessing.
