# Secrets: what they are, and the Keeper path

Status as of 2026-08-09: **researched, not implemented.** Phase 1 deliberately
uses native platform secrets so the first CI run has exactly one moving part.
Keeper replaces one step in the pipeline and nothing else.

**2026-09-03: this file covers the CI half only.** The other half, premium
plugin licence keys on Pantheon and Nexcess and how Keeper could feed them
without a person typing values, is `docs/SECRETS-CONCEPT.md`, written for the
team regroup the week of 2026-09-08. The short version: Keeper has no PHP SDK,
so it cannot feed WordPress directly; the delivery is CI into Pantheon Secrets,
read by a constant in `wp-config.php`, and only for plugins that read one.

---

## 1. The secret inventory

| Secret | Used by | Type | Needed for the first run? |
|---|---|---|---|
| Pantheon machine token | every Terminus script | short string | **Yes** |
| Pantheon-registered SSH private key | anything calling `terminus remote:wp` (fleet healthcheck full mode, WPStatistics fleet scan, `galbani-wpstatistics-pull.sh`) | multi-line PEM | No, phase 2 |
| SSH key passphrase | same, only if the key carries one | short string | No, and see below |
| GA4 service-account JSON key (`agent-ga4-reader@cm-agent-integrations.iam.gserviceaccount.com`) | `ga4-agent-pull.py` | JSON **file** | No, separate migration |

Two notes worth carrying into the handoff conversation:

- **The passphrase problem solves itself.** The whole reason the local scripts
  needed `ssh-agent` juggling is that Doug's key is passphrase-protected and an
  unattended script cannot answer a prompt. In CI the right answer is a
  **dedicated, passphrase-free key generated for the runner** and registered to
  a Pantheon account, not Doug's personal key with its passphrase in a vault.
  That also means revoking CI access is a one-line action in Pantheon that does
  not disturb anyone's laptop.
- **The GA4 key is a file, not a string.** Both Keeper integrations can write a
  record attachment straight to a path on the runner, which is exactly what
  `GOOGLE_APPLICATION_CREDENTIALS` wants. That is the cleanest of the four.

---

## 2. What Keeper actually offers

Keeper Secrets Manager (KSM) is an add-on to a Keeper Enterprise/Business
account. It has to be enabled on the account before any of this works, and it
is separate from ordinary vault sharing. **First real question for whoever
administers clevermethod's Keeper: is the Secrets Manager add-on active?** If
it is not, none of the three paths below exist yet.

All three paths authenticate the same way: a **KSM Application** is created in
the vault, records are shared to it, and it produces an initialized
**configuration blob** (JSON or base64). That blob is the CI credential. It is
not a human login, which is exactly what you want for a pipeline.

### Path A - GitHub Actions native action

`Keeper-Security/ksm-action@v1`

```yaml
- name: Fetch secrets from Keeper
  uses: Keeper-Security/ksm-action@v1
  with:
    keeper-secret-config: ${{ secrets.KSM_CONFIG }}
    secrets: |
      RECORD_UID/field/password        > env:PANTHEON_MACHINE_TOKEN
      RECORD_UID/file/id_pantheon      > file:/home/runner/.ssh/id_pantheon
      RECORD_UID/file/ga4-key.json     > file:/tmp/ga4-key.json
```

Destinations: `env:NAME` (environment variable), bare `NAME` (step output),
`file:/path` (write attachment to disk). Retrieved values are auto-masked in
logs.

### Path B - Azure DevOps native task

`ksmazpipelinetask@1`, from the "Keeper Secrets Manager" Visual Studio
Marketplace extension.

```yaml
- task: ksmazpipelinetask@1
  inputs:
    keepersecretconfig: $(KSM_CONFIG)
    secrets: |
      RECORD_UID/field/password    > var:PANTHEON_MACHINE_TOKEN
      RECORD_UID/file/id_pantheon  > file:/home/vsts/.ssh/id_pantheon
```

Destinations: `var:` (job-local variable), `out:` (cross-job, the default),
`file:`. Keeper's own docs suggest storing the config blob in Azure Key Vault.

**The notation syntax is identical across A and B.** `UID/field/name > dest`
and `UID/file/name > file:path` work the same in both. That is a real point in
Keeper's favour for this specific project: the secret *mapping* is portable
even though the task wrapper is not.

### Path C - `ksm` CLI (`keeper-secrets-manager-cli`, pip-installable)

```bash
pip install keeper-secrets-manager-cli
export PANTHEON_MACHINE_TOKEN="$(ksm secret notation keeper://UID/field/password)"
ksm secret download -u UID --name id_pantheon --file-output ~/.ssh/id_pantheon
```

This is the only path that is **genuinely platform-neutral** - the same three
lines run on GitHub, on Azure, in a container, and on a laptop.

---

## 3. Recommendation

**Phase 1: native platform secrets. Do not introduce Keeper yet.**

Store `PANTHEON_MACHINE_TOKEN` as a GitHub Actions repository secret and get a
green run. Adding Keeper at the same time as the first-ever CI execution means
that when the run fails you cannot tell whether the problem is the runner, the
token, Terminus, Pantheon egress, or Keeper. One variable at a time.

**Phase 2: add Keeper via Path A, then evaluate Path C before the Azure call.**

Path A is the lowest-friction way to prove the KSM application and record
sharing are set up correctly, because the action reports clearly when a UID is
wrong. Once that works, the question worth answering deliberately is whether to
keep the platform-native action or move to the CLI:

- Path A/B keep the YAML declarative and the secrets masked automatically, at
  the cost of a per-platform rewrite of the fetch step. Small cost - it is
  roughly ten lines, and the notation strings themselves carry over verbatim.
- Path C means one `scripts/fetch-secrets.sh` that both platforms call, so the
  CI YAML shrinks to `./scripts/fetch-secrets.sh && ./scripts/whatever.sh`.
  That matches this repo's stated design rule (logic in scripts, YAML is a thin
  wrapper) more honestly than A/B do. The cost is that masking becomes your
  responsibility, and a pip install is added to every run.

My read: **Path A for phase 2** because it is the fastest way to prove the
Keeper side works at all, and it is the path with real vendor docs behind it.
Revisit Path C only if Matt actually chooses Azure DevOps, at which point one
shared `fetch-secrets.sh` becomes worth more than two declarative blocks.

**Do not use Keeper for the KSM config blob itself.** The config is the
bootstrap credential and has to live in the platform's own secret store
(GitHub Actions secrets / Azure Key Vault). Keeper protects everything else,
not itself.

---

## 4. Open questions for the clevermethod Keeper admin

1. Is the Secrets Manager add-on enabled on the account, or is it vault-only?
2. Can a KSM Application be created for CI, and who owns/rotates its config?
3. Should the runner get a dedicated Pantheon account with its own passphrase-free
   SSH key, rather than reusing Doug's personal key? (Strong yes from here.)
4. Does the GA4 service account need its own Keeper record, or does it stay in
   Google Cloud with workload identity federation instead? Federation would
   remove the JSON key entirely, which is better than storing it anywhere -
   worth 20 minutes of research before defaulting to the key file.

---

Sources: [Keeper GitHub Actions docs](https://docs.keeper.io/en/keeperpam/secrets-manager/integrations/github-actions),
[ksm-action repo](https://github.com/Keeper-Security/ksm-action),
[Keeper Azure DevOps extension docs](https://docs.keeper.io/en/keeperpam/secrets-manager/integrations/azure-devops-plugin),
[Keeper Secrets Manager CLI - secret command](https://docs.keeper.io/en/keeperpam/secrets-manager/secrets-manager-command-line-interface/secret-command),
[keeper-secrets-manager-cli on PyPI](https://pypi.org/project/keeper-secrets-manager-cli/)
