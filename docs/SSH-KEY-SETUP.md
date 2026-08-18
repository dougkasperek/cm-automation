# Turning on full mode: the runner SSH key

Follow this in Terminal on your Mac. Roughly 30 minutes, most of it waiting for
scans.

**What it unlocks.** Four checks that currently read *not checked* on all 52
Pantheon sites: WordPress core update pending, plugin updates, theme updates,
and the administrator count. Everything else in the pipeline is already built
and tested; this is the only missing credential.

---

## Read this first: ed25519 will not work

Pantheon **does not support ed25519 keys**, which is the modern default and what
almost every guide tells you to generate. Their docs are explicit: *"Currently,
we do not support ed25519 keys."* They accept **RSA** and **ECDSA**, and for
ECDSA only the 256-bit size.

So the command below uses RSA 4096 deliberately. If you generate an ed25519 key
out of habit, Pantheon will reject it and the failure will look like an
authentication problem rather than a key-type problem.

---

## Why a dedicated key, and not yours

This is the first credential in the pipeline that grants **write-capable access
to production sites**, even though the scan only reads. Three reasons the runner
gets its own key:

1. **Revocation is a one-line action that disturbs nobody.** Delete one key from
   the Pantheon dashboard and CI loses access instantly. If the runner used your
   key, revoking CI access would lock you out of your own fleet.
2. **The passphrase problem disappears structurally.** A CI runner cannot type a
   passphrase. Vaulting your key plus its passphrase means storing both halves of
   your personal credential in a shared secret store. A dedicated key with no
   passphrase is a smaller, cleaner exposure: it can do exactly one thing, and
   you can kill it without consequence.
3. **Attribution.** When something touches a site, "the CI runner" and "Doug" are
   different answers, and the Pantheon logs will say which.

The tradeoff is real and worth stating: a passphrase-free key sitting in GitHub's
secret store is only as safe as the repository. That is the argument for keeping
the repo private, and for step 6 below.

---

## Step 1. Generate the key

```bash
ssh-keygen -t rsa -b 4096 -C "cm-automation CI runner" -f ~/.ssh/pantheon_ci -N ""
```

`-N ""` means no passphrase. That is deliberate, see above.

**You should see:** a key fingerprint and randomart, and two new files.

```bash
ls -l ~/.ssh/pantheon_ci ~/.ssh/pantheon_ci.pub
```

`pantheon_ci` is the private half and never leaves your machine except into
GitHub's secret store. `pantheon_ci.pub` is the public half and is safe to paste
anywhere.

## Step 2. Register the public key with Pantheon

```bash
pbcopy < ~/.ssh/pantheon_ci.pub    # copies it to the clipboard
```

In the Pantheon Dashboard: your user icon (top right) → **Personal Settings** →
**SSH Keys** tab → **Add New Key** → paste → **Save**.

Keys are **account-level**, not per-site, so this one action covers the whole
fleet.

## Step 3. Prove it works from your Mac before involving CI

```bash
ssh -i ~/.ssh/pantheon_ci -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=accept-new \
    "$(terminus connection:info galbanicheese.live --field=sftp_username)"@appserver.live.$(terminus site:info galbanicheese --field=id).drush.in -p 2222 'echo ok'
```

If that is awkward, the simpler proof is just to run the scan:

```bash
cd ~/dev/cm-automation
export PANTHEON_MACHINE_TOKEN=...
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/pantheon_ci
./scripts/pantheon-fleet-healthcheck.sh --sites galbanicheese,actioncarting --no-fail-on-crit
```

**You should see:** a scan of two sites where the WordPress columns are
populated rather than `n/a`. Check the JSON directly:

```bash
python3 -c "
import json,glob
f=sorted(glob.glob('reports/fleet-health-*.json'))[-1]
for r in json.load(open(f)):
    print(r['site'], 'wp_checked=', r.get('wp_checked'), 'core=', r.get('wp_core_update'), 'plugins=', r.get('plugin_updates'))
"
```

**`wp_checked` must be `True`.** If it is still `False`, the SSH leg did not run
and full mode is not actually working, whatever else the output says. Stop here
and send me the scan output rather than continuing to CI.

**Also check `wp_version`.** As of 2026-08-18 the scan reads the version the
site is actually running, not only whether an update is pending. Add it to the
snippet above:

```bash
python3 -c "
import json,glob
f=sorted(glob.glob('reports/fleet-health-*.json'))[-1]
for r in json.load(open(f)):
    print(r['site'], 'wp_checked=', r.get('wp_checked'), 'version=', r.get('wp_version'))
"
```

Three values are possible and they mean different things. A version string means
it read it. `unknown` means it asked and got nothing back. `n/a` means it did not
ask, which on a full-mode WordPress site is a bug. **The first cohort scan run
before this field existed stores `unknown`; re-run it.**

## Step 4. Add the private key to GitHub

```bash
pbcopy < ~/.ssh/pantheon_ci        # note: NO .pub this time
```

Repository → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**.

- **Name:** `PANTHEON_SSH_KEY`
- **Secret:** paste

It must include the `-----BEGIN OPENSSH PRIVATE KEY-----` and
`-----END OPENSSH PRIVATE KEY-----` lines and the trailing newline. `pbcopy`
preserves all of that; retyping or trimming it will not.

The workflow already knows what to do with this. It writes the key to
`~/.ssh/id_pantheon`, sets `IdentitiesOnly yes` so the runner cannot silently
fall back to another key, and sets `StrictHostKeyChecking accept-new`.

**That last setting is not cosmetic.** A fresh runner has no `known_hosts`, so
without it every single site emits a host-key warning on stdout, and that
warning is what broke `jq` on the first real fleet run. It is already in the
workflow; do not remove it.

## Step 5. Run a small cohort in CI

Actions → **Pantheon Fleet Health Check** → **Run workflow**:

| input | value |
|---|---|
| `run_mode` | **full** |
| `target_env` | `live` |
| `sites` | `galbanicheese,actioncarting,clevermethod` |
| `fail_on_crit` | `false` |

Three sites, so a credential problem surfaces in a minute rather than fifteen.
If the secret is missing or malformed the workflow fails immediately with an
explicit message rather than a confusing timeout.

## Step 6. Full fleet, then compare against a local run

Run the workflow again with `sites` blank. Then run the same scan locally the
**same day**, and compare:

```bash
./scripts/pantheon-fleet-healthcheck.sh --no-fail-on-crit
```

Download the CI artifact and diff the two JSON files on facts, ignoring
timestamps.

**Do not skip this.** A CI run and a local run disagreeing is the single most
likely way this quietly produces wrong answers, and it is only detectable while
both still exist. It has already paid for itself once: the email checker's
timeout bug was found exactly this way, when GitHub said 8 and my laptop said 9.

## Step 7. Ingest and look at the dashboard

```bash
./scripts/fleet-ledger.py ingest
./scripts/render-dashboard.py --out fleet.html && open fleet.html
```

Both scripts were committed non-executable until 2026-08-18, so these two lines
returned *Permission denied*. The mode is fixed. If you ever see that again,
`python3 scripts/fleet-ledger.py ...` works regardless of the mode bit.

**What should change.** The coverage meter *WordPress core, plugins, themes*
goes from **0 of 52** to 52 of 52. The **WP version** column stops reading
*7.0.2 claimed* in muted ink and starts showing what each site actually reports,
with a red *workbook says 7.0.2* chip on any site that disagrees. The WP core
column now answers only whether an update is pending — it no longer borrows the
workbook's version to fill its gap, because that answered a different question
than the one its heading asks.

**What to look at first:** any site where the observed value disagrees with the
workbook's claim. The workbook asserts WordPress 7.0.2 on all 78 sites and
nothing has ever verified it. Post-`wp2shell`, a site that is not on 7.0.2 is
the most important thing this project could find.

---

## If it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Pantheon rejects the key on paste | it is an ed25519 key | regenerate with `-t rsa -b 4096` |
| `Permission denied (publickey)` | key not registered, or the runner picked a different one | confirm it is listed in Personal Settings; `IdentitiesOnly yes` is already set in the workflow |
| Many sites `ERROR` | API timeouts under CI network conditions | raise `API_CALL_TIMEOUT` in the script |
| `jq` parse failures | a host-key or noise line reached stdout | check `accept-new` is still in the workflow, then add the pattern to `strip_noise` in `lib/common.sh` and add a mock case |
| Run hangs | a grandchild `ssh` not reaped by the poll-kill helper | job-level `timeout-minutes` is the backstop; investigate that site manually |
| `wp_checked` still `False` | the SSH leg silently did not run | full mode is not working. Do not trust the output |

## After it works

Rotate this key on whatever cadence you rotate anything else, and delete it from
Pantheon the moment the repo changes hands or the CI account changes. It is one
line in the dashboard and it costs nothing to redo.

The next rung after this is **not** applying updates. It is phase 3 in
`docs/RUNBOOK.md`: scheduled runs with `fail_on_crit` on, once several cycles
have been reviewed by a human. Execution authority is a ladder, and reading
WordPress state is still the bottom rung.
