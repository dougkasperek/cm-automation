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

### Step 8. Move the workflow files where GitHub expects them

GitHub only runs workflow files that live in `.github/workflows/`. They are
currently parked in `ci/github-actions/` because the Claude file bridge is not
allowed to write into `.github/`. That restriction goes away now.

```bash
mkdir -p .github/workflows
mv ci/github-actions/*.yml .github/workflows/
rmdir ci/github-actions
```

Then check:

```bash
ls .github/workflows/
```

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
