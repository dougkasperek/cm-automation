# Nexcess / Liquid Web CI and Automation Architecture Notes

> **Provenance: Doug's research, imported 2026-08-19. NOT verified by this
> repo.** Every "Verify" marker below is genuinely unverified — no Nexcess API
> call and no Nexcess SSH connection has been made from this codebase. Treat the
> endpoints, field names and the SSH key-propagation model as claims to test,
> not as facts to build on. Section 17 Phase 1 is the first thing to actually
> run. See `docs/SESSION-HANDOFF.md` for where this sits in the queue.
>
> **Update 2026-08-19, later the same day.** Phase 1 is now BUILT
> (`scripts/fleet-nexcess.py`, `docs/NEXCESS.md`) and still unrun. Two
> corrections to section 4, taken from the vendor's own API documentation
> repository rather than from summary pages:
>
> - The API base URL is **not documented anywhere**. Every vendor example is
>   written against `$PORTAL_API_URL` and no page says what it resolves to. The
>   scanner therefore refuses to guess one; `fleet-nexcess.py probe` measures
>   it. Add the answer to section 19's support email if probe cannot find it.
> - Auth is `Authorization: Bearer $PORTAL_API_KEY` plus
>   `Accept: application/json`, confirmed against `site/list.md` and
>   `site/show.md` in `nexcess/nexcess-api-docs`. Pagination is `page` and
>   `pageSize`, 1-based; `416` is the out-of-range status.
>
> One claim in section 4 got materially better on inspection: `GET /v1/site/{id}`
> documents `unix_username`, `environment.software.php.version` AND
> `environment.software.app.version`. If that holds live, **the wp2shell
> question is answerable for all 21 Nexcess sites with no SSH at all.** That is
> the single highest-value thing in this phase and it is the second item the
> first live run has to establish.

**Purpose:** Reference for building centralized automation across clevermethod-hosted sites on Nexcess, Liquid Web, and Pantheon.

**Status:** Working architecture document. Items marked **Verify** are not yet confirmed strongly enough to treat as production assumptions.

**Last updated:** August 19, 2026

## 1. Executive Summary

Nexcess Managed WordPress / WooCommerce can support centralized automation, but its model differs from Pantheon.

Pantheon provides a relatively unified automation model through Terminus, machine tokens, Git-based workflows, and site/environment operations.

Nexcess appears to split automation into two layers:

1. **Account-level control and discovery through the Nexcess Client Portal API**
2. **Per-site execution through SSH, WP-CLI, Git, and site-level filesystem access**

The key architectural point is:

> Nexcess SSH access is scoped to individual Managed WordPress sites, but SSH public keys are managed centrally at the Nexcess user/account level.

This means the automation system should not treat SSH as the account-wide control plane. The recommended model is to use the **Nexcess API for site inventory and management**, then use **site-specific SSH identities with a shared automation SSH key** for commands that require filesystem or WP-CLI access.

GitHub Actions is the recommended common orchestration layer across both Pantheon and Nexcess.

## 2. Recommended High-Level Architecture

```text
                         GitHub Actions
                               |
              +----------------+----------------+
              |                                 |
           Pantheon                           Nexcess
              |                                 |
      Terminus machine token            Portal API token
              |                                 |
      Site/environment ops                 GET /v1/site
                                                |
                                       Account site inventory
                                                |
                                      Site ID / domain / IP
                                        / Unix username
                                                |
                                      GitHub Actions matrix
                                                |
                                      Per-site SSH access
                                                |
                                             WP-CLI
                                                |
                                  Inspection / maintenance /
                                   deployment operations
```

This allows GitHub Actions to serve as the common automation control layer while adapting to each host's native capabilities.

## 3. Nexcess Managed WordPress SSH Model

### Confirmed

For Nexcess Managed WordPress and Managed WooCommerce:

- Each website has its own SSH user.
- The SSH user is isolated to that site's filesystem.
- One site-level SSH login does not provide filesystem access to every Managed WordPress site in the account.
- **Nexcess does not provide a read-only SSH user option. VERIFIED by Nexcess support 2026-08-24.**
- **SSH users have read *and write* access within the filesystem they can access. VERIFIED by Nexcess support 2026-08-24.**
- Nexcess does not provide arbitrary folder-level restrictions for an SSH user.
- Nexcess supports SSH key authentication.
- Nexcess supports WP-CLI through SSH.

**On the two verified lines.** These were imported research until 2026-08-24,
when Nexcess support stated both directly: a read-only or command-restricted
SSH user "is not currently supported on Managed WordPress or Nexcess Cloud
accounts", and restricting an identity to `wp core version` and `wp plugin
list` while preventing writes "would not be possible". The only alternative
they offered was a bare-metal dedicated server via Sales, which is a hosting
migration, not a scanner configuration. Analysis in `docs/NEXCESS-SUPPORT.md`;
the reply itself is archived verbatim at
`docs/correspondence/2026-08-24-nexcess-in-ssh-and-api-challenge.md`.

**This is a standing consequence, not a solved item.** Any Nexcess SSH scan
holds a write-capable credential regardless of how carefully the workflow
behaves. The repo's hard boundary — this tool never changes a client site — is
enforced by the commands the workflow runs, and by nothing the host provides.

### Important distinction

The SSH **login identity** is per site, but Nexcess provides centralized SSH public-key management from the user/account portal.

Conceptually:

```text
Nexcess user / automation identity
        |
        +-- SSH public key
              |
              +-- Site A SSH username
              +-- Site B SSH username
              +-- Site C SSH username
              +-- Site D SSH username
```

This is different from:

```text
One SSH username
        |
        +-- every site filesystem
```

### Automation implication

GitHub Actions should potentially be able to store **one Nexcess automation private key** and use that key against the different per-site SSH usernames returned or maintained in the site inventory.

That would avoid maintaining an individual password or private key for every Nexcess site.

### CONFIRMED 2026-08-24 — one key reaches every site

**The central point is answered.** Nexcess support, 2026-08-24:

> A single SSH public key added through the Nexcess Client Portal is managed at
> the user/account level. This means that the same key can be used to access
> all Managed WordPress sites that the user is authorized to access, including
> sites currently associated with the account, as well as any sites added in
> the future. There is no need to add the same SSH key separately for each
> individual site.

Archived verbatim at
`docs/correspondence/2026-08-24-nexcess-in-ssh-and-api-challenge.md`.

So the diagram above is right, and the production design **may** now depend on
automatic key propagation. This is what unblocks Phase 2.

Corroborated independently by the vendor's own API documentation:
`ssh-key/add.md` documents `POST /v1/ssh-key` taking exactly `name` and `key`,
with **no site parameter**. The resource is user-scoped by construction.

Answered by that reply:

- ~~Does the key automatically propagate to all existing Managed WordPress sites?~~ **Yes.**
- ~~Does it automatically apply to newly created sites?~~ **Yes, explicitly.**
- Does propagation depend on the user's team permissions? **Partly** — the key reaches what "the user is authorized to access", so authorisation is the boundary. The mechanics of changing that authorisation were not described.

Still unanswered, and **do not read the confirmation above as covering these**:

- Is there any lag before a newly added key works on all eligible sites?
- Can a key be limited to selected sites?
- If a team member is removed from a site, is the corresponding SSH key access removed immediately?

None of the three blocks building Phase 2; the first is a first-run
observation, the other two are offboarding questions. They stay listed in
section 18.

## 4. Nexcess API

Nexcess provides Client Portal API tokens for programmatic access.

This is likely the correct account-level control plane for automation.

### Site enumeration

The Nexcess API exposes a site-list endpoint:

```text
GET /v1/site
```

This can be used to discover sites accessible to the authenticated Nexcess user.

Available site information can include items such as:

- Site ID
- Domain
- Temporary domain
- IP address
- Application
- Hosting package
- Production / staging / development status
- Cloud / service information
- Deployment information

This allows the automation system to create or refresh its Nexcess site inventory programmatically rather than maintaining a completely manual site list.

### Site details

The API also exposes:

```text
GET /v1/site/{SITE_ID}
```

Site details can include information such as:

- Unix username
- Domain
- IP
- PHP version
- WordPress/application data
- Redis information
- update configuration
- environment metadata
- autoscaling information

The **Unix username** is particularly relevant because Nexcess Managed WordPress SSH identities are per site.

### Other useful API capabilities

Documented API functionality includes operations such as:

```text
site:list
site:show
site:add
site:change-php-version
site:logs
site:purge-caches
site:show-app-update-settings
site:toggle-app-update-settings
site:show-autoscale-usage
site:stencil-list

ssh-key:add
ssh-key:list
ssh-key:show
ssh-key:delete
```

Example:

```text
POST /v1/site/{SITE_ID}/purge-caches
```

WordPress core update settings also appear to be controllable through the API.

### Verify before production

The Nexcess API documentation is currently linked from Nexcess documentation, but some examples in the underlying API documentation repository are older.

Before building critical workflows around an endpoint:

1. Test it against a non-production Nexcess site.
2. Confirm current authentication requirements.
3. Confirm returned JSON fields.
4. Confirm pagination behavior for account-wide site listings.
5. Confirm API rate limits.
6. Confirm whether API permissions follow team/user portal permissions.
7. Confirm whether API tokens can be explicitly scoped.
8. Confirm token expiration / rotation behavior.
9. Confirm whether site-create, PHP-change, update-setting, and similar write endpoints are fully supported for the specific Nexcess plan types clevermethod uses.

Treat `GET /v1/site` and basic site discovery as the first API functionality to validate.

## 5. Nexcess Credentials for Automation

Recommended credential separation:

```text
NEXCESS_PORTAL_API_TOKEN
```

Used for:

- Site discovery
- Site metadata
- Account-level management operations
- Cache operations
- Other API-supported control-plane tasks

And:

```text
NEXCESS_CI_SSH_PRIVATE_KEY
```

Used for:

- SSH
- WP-CLI
- Git
- Filesystem-level operations
- Commands not exposed through the Nexcess API

### Recommended identity model

Do not use a clevermethod owner's personal Nexcess Superuser identity as the long-term automation identity.

Prefer:

```text
Dedicated Nexcess automation user/team member
        |
        +-- minimum required portal permissions
        +-- dedicated API token
        +-- dedicated SSH public key
```

Benefits:

- Easier credential rotation
- Easier revocation
- Separation from employee credentials
- Lower impact if a credential is compromised
- Clear audit trail
- No dependency on one employee's account

### Verify

Confirm that a dedicated team member can be granted exactly the Nexcess permissions required for:

- API site enumeration
- SSH access
- WP-CLI operations
- viewing environment metadata

without unnecessary billing, DNS, account-management, or destructive permissions.

Also confirm whether the API exposes the permissions of the authenticated user or whether certain API tokens have broader capabilities than the portal UI suggests.

## 6. GitHub Actions as the Orchestration Layer

GitHub Actions should remain the central CI / automation platform.

For Nexcess, a workflow can follow this pattern:

```text
GitHub Actions
      |
      +-- Read NEXCESS_PORTAL_API_TOKEN
      |
      +-- GET /v1/site
      |
      +-- Build normalized site inventory
      |
      +-- Filter eligible sites
      |
      +-- Create GitHub Actions matrix
              |
              +-- Site A
              +-- Site B
              +-- Site C
              +-- ...
                    |
                    +-- determine host/IP
                    +-- determine Unix username
                    +-- SSH using automation key
                    +-- run WP-CLI / shell inspection
                    +-- capture normalized results
```

This is a better model than storing every Nexcess site's credentials independently in GitHub Secrets.

## 7. Suggested Normalized Site Inventory

The automation platform should abstract hosting-provider differences.

Example:

```yaml
sites:
  - id: example-site
    provider: nexcess
    domain: example.com
    provider_site_id: "123456"
    environment: production
    ssh_host: 1.2.3.4
    ssh_user: abc123
    wp_path: /home/abc123/html
    active: true

  - id: second-site
    provider: pantheon
    domain: example2.com
    provider_site_id: pantheon-machine-name
    environment: live
    active: true
```

For Nexcess, much of this record may be generated dynamically from the API rather than stored manually.

Avoid storing passwords, private keys, or API tokens in this inventory.

## 8. What GitHub Secrets Should Contain

At minimum:

```text
NEXCESS_PORTAL_API_TOKEN
NEXCESS_CI_SSH_PRIVATE_KEY

PANTHEON_MACHINE_TOKEN
```

Potentially:

```text
NEXCESS_CI_SSH_KNOWN_HOSTS
```

or an equivalent secure host-key-verification mechanism.

Do not disable SSH host-key verification simply to simplify automation.

If the Nexcess API cannot reliably provide all SSH connection information, maintain the missing non-secret fields in a configuration file or inventory database rather than creating individual GitHub Secrets per site.

## 9. SSH Security Considerations

Nexcess's lack of read-only SSH users is important.

Even if the automation currently performs only:

```text
wp core version
wp plugin list
wp theme list
wp option get
```

the SSH credential itself may still have write-capable access.

Therefore:

- Use a dedicated automation identity.
- Use a dedicated SSH key.
- Never reuse an employee's laptop SSH key.
- Store the private key only in the automation secret store.
- Rotate it on a documented schedule.
- Remove it immediately when the automation system is retired or replaced.
- Limit GitHub repository access.
- Protect Actions workflows that can access production secrets.
- Require code review on workflow changes affecting production.
- Avoid arbitrary command parameters coming from untrusted inputs.
- Log the commands or operation types being executed.
- Separate read/inspection workflows from intentional change workflows where possible.

Even if the SSH account cannot technically be made read-only, the **automation workflow can still enforce logical read-only behavior**.

## 10. WP-CLI Opportunities

Once connected through SSH, WP-CLI gives the automation platform a consistent WordPress-level interface.

Examples of read-oriented checks:

```bash
wp core version
wp core check-update

wp plugin list --format=json
wp theme list --format=json

wp option get siteurl
wp option get home

wp db size

wp cron event list --format=json
```

Potential future operations include:

- Plugin inventory
- Theme inventory
- Core version verification
- PHP compatibility checks
- User/admin-account audits
- cron inspection
- database-size monitoring
- URL checks
- cache clearing
- plugin/core update workflows
- post-update validation
- security and compliance data collection

Any command that changes production should be in a deliberately separate workflow from inventory/monitoring operations.

## 11. Git on Nexcess

Nexcess supports Git over SSH and documents GitHub integration patterns.

However, Nexcess should not currently be treated as having a Pantheon-equivalent native Git deployment model.

The distinction:

### Pantheon

```text
Git repository
      |
Pantheon platform workflow
      |
dev / test / live
```

### Nexcess

More closely resembles:

```text
GitHub / Git repository
      |
GitHub Actions or operator
      |
SSH / Git commands
      |
Nexcess site filesystem
```

Git is available, but clevermethod likely needs to own more of the deployment logic.

### Verify

Before standardizing Nexcess Git deployments:

- Determine whether existing clevermethod Nexcess sites were originally provisioned with Git workflows.
- Determine whether WordPress core is expected to be managed by Git or by Nexcess.
- Determine how Nexcess automated updates interact with Git-managed plugins/themes.
- Determine whether `.git` directories or deployment hooks create any support issues.
- Establish whether the desired pattern is full-site Git, custom-code-only Git, or no production Git checkout.

Do not assume that a Pantheon Git workflow should simply be replicated on Nexcess.

## 12. Nexcess Staging and Development Environments

Nexcess Managed WordPress / WooCommerce provides staging capability.

This creates potential automation patterns such as:

```text
production
    |
create/sync staging
    |
perform updates
    |
run validation
    |
approve
    |
apply changes to production
```

Nexcess also provides automated plugin-update functionality with visual comparison.

This should be evaluated before building redundant update-testing functionality from scratch.

### Potential role

Nexcess native tools may handle:

- plugin-update testing
- visual comparison
- staging copy operations

GitHub Actions could handle:

- estate-wide orchestration
- inventory
- compliance checks
- custom validation
- reporting
- cross-host standardization
- alerting
- dashboards

## 13. Cron / Scheduled Tasks

Nexcess supports scheduled commands / cron jobs.

These could be useful for site-local jobs, but they should not become the primary control plane for clevermethod's multi-site automation.

Prefer:

```text
GitHub Actions
    |
central schedule
    |
all hosting providers
```

instead of distributing automation logic across dozens of individual Nexcess cron configurations.

Use Nexcess cron only when the task truly needs to execute locally at the site/server level.

## 14. Liquid Web

Liquid Web infrastructure products should be treated separately from Nexcess Managed WordPress.

For Liquid Web VPS, Cloud Dedicated, or Bare Metal environments:

- Normal server-level SSH is available.
- SSH permissions are fundamentally scoped to the server/user configuration.
- Liquid Web supports API-based infrastructure management.
- Liquid Web provides a CLI.
- Liquid Web provides Terraform tooling.
- Infrastructure automation is substantially broader than Nexcess Managed WordPress.

Potential Liquid Web automation areas include:

- server provisioning
- cloning
- resizing
- start/stop operations
- firewall management
- backups
- DNS
- storage
- IP management
- account assets
- credentials

If clevermethod has sites on Liquid Web infrastructure rather than Nexcess Managed WordPress, those should be classified separately in the automation inventory.

Example:

```yaml
provider: liquidweb-vps
```

rather than:

```yaml
provider: nexcess
```

## 15. Solid Deployments

Liquid Web / Solid Central includes Solid Deployments for moving WordPress data between environments.

It can synchronize:

- WordPress files
- themes
- plugins
- uploads
- database tables
- URLs / paths through search-and-replace

This is potentially useful for staging-to-production deployment or site migration.

It should not currently be considered the primary clevermethod CI system.

Treat it as an operational deployment/synchronization tool rather than a replacement for GitHub Actions.

### Verify

Investigate whether Solid Deployments provides:

- API access
- CLI access
- webhook integration
- useful deployment status data
- GitHub Actions integration
- selective file/table deployment appropriate for clevermethod workflows

If it is UI-only or minimally automatable, it should remain outside the primary CI control plane.

## 16. Pantheon vs. Nexcess vs. Liquid Web

| Capability | Pantheon | Nexcess Managed WP | Liquid Web VPS / Cloud |
|---|---|---|---|
| Central API credential | Yes | Yes | Yes |
| Central site/server discovery | Yes | Yes | Yes |
| CLI | Terminus | SSH + WP-CLI + API | Liquid Web CLI + SSH |
| Native Git deployment workflow | Strong | Limited / custom | User-managed |
| GitHub Actions suitability | Strong | Strong as external orchestrator | Strong |
| Account-level SSH key management | Yes | Yes | Yes |
| Single SSH identity across estate | Platform model | No, per site | Depends on server/user design |
| WP-CLI | Yes | Yes | User-managed |
| Staging | Native | Native | User-managed |
| Infrastructure API | Platform-specific | Moderate | Extensive |
| Terraform | Not primary model | No meaningful equivalent identified | Yes |
| Native WordPress update tooling | Yes | Yes | Depends on configuration |

## 17. Recommended Build Strategy

### Phase 1: Read-only estate discovery

Build account/site enumeration first.

For Nexcess:

```text
API token
   |
GET /v1/site
   |
normalize site metadata
   |
store/report inventory
```

Validate:

- all expected sites are returned
- staging sites can be distinguished from production
- domains are accurate
- Unix usernames are available
- SSH hosts/IPs are usable
- pagination is handled
- disabled/old sites are identifiable

### Phase 2: Read-only SSH validation

Use the dedicated automation SSH key to connect to a small number of Nexcess sites.

Run only:

```bash
wp core version
wp plugin list --format=json
wp theme list --format=json
```

Validate:

- centralized SSH key behavior
- username mapping
- filesystem paths
- host-key handling
- connection limits
- concurrent SSH behavior

### Phase 3: Fleet-wide inspection

Create a GitHub Actions matrix from the Nexcess API site inventory.

Run read-oriented WordPress checks across all eligible sites.

Collect normalized output.

### Phase 4: Pantheon + Nexcess normalization

Create one reporting schema regardless of provider.

Example:

```json
{
  "site": "example.com",
  "provider": "nexcess",
  "environment": "production",
  "wordpress_version": "x.x.x",
  "php_version": "x.x",
  "plugins": [],
  "themes": [],
  "checked_at": "ISO-8601 timestamp"
}
```

### Phase 5: Dashboard / reporting

Publish normalized results into the clevermethod automation dashboard.

The dashboard should not need to understand hosting-provider implementation differences.

### Phase 6: Controlled write operations

Only after read-only automation is stable, evaluate controlled operations such as:

- cache clearing
- plugin updates
- WordPress core updates
- staging refresh
- deployment
- update validation

Write-capable workflows should be separately permissioned and intentionally invoked.

## 18. Open Questions / Further Investigation

These should be resolved before treating the architecture as production-ready.

### Nexcess SSH

- ~~**Verify:** Does one user-level SSH public key automatically work across every Managed WordPress site accessible to that user?~~ **ANSWERED 2026-08-24: yes.** See section 3.
- ~~**Verify:** Does that include future sites automatically?~~ **ANSWERED 2026-08-24: yes, explicitly.**
- ~~**Verify:** Is a read-only or command-restricted SSH user available?~~ **ANSWERED 2026-08-24: no.** Not on Managed WordPress or Nexcess Cloud. Every SSH user is write-capable.
- **Verify:** How quickly is access revoked when team permissions change? *(asked 2026-08-22, not answered in the 2026-08-24 reply)*
- **Verify:** Can SSH keys be scoped to selected sites? *(asked 2026-08-22, not answered in the 2026-08-24 reply)*
- **Verify:** Is there a lag before a newly added key works on all eligible sites? *(observable on first run; no need to ask)*
- **Verify:** Are there SSH concurrency or rate limits relevant to running dozens of GitHub Actions jobs simultaneously?
- **Verify:** Is the SSH hostname always stable, or should automation use the IP / another endpoint returned by the API?
- **Verify:** What is the canonical WordPress path for all Managed WordPress plans?

### Nexcess API

- **Verify:** Current API rate limits.
- **Verify:** Pagination model for large accounts.
- **Verify:** API token expiration behavior.
- **Verify:** Token rotation process.
- **Verify:** Whether tokens inherit exact portal/team permissions.
- **Verify:** Whether granular API scopes exist.
- **Verify:** Which documented write endpoints remain fully supported in 2026.
- **Verify:** Whether the API reliably exposes the site SSH/Unix username for all relevant Nexcess plan types.
- **Verify:** Whether staging/development site relationships can be identified cleanly through the API.
- **Verify:** Whether site lifecycle events are available through webhooks or another event mechanism.

### Git / Deployment

- **Verify:** Recommended Nexcess pattern for Git-based production deployment.
- **Verify:** Interaction between Git-managed code and Nexcess automatic plugin/core updates.
- **Verify:** Whether Nexcess provides deployment hooks not clearly surfaced in current documentation.
- **Verify:** Whether production Git checkouts are considered supported best practice.

### Nexcess Native Update Tools

- Evaluate Visual Comparison and automated plugin updates.
- Determine what data/results can be exported or consumed programmatically.
- Determine whether these tools can complement GitHub Actions rather than duplicating functionality.

### Liquid Web

- Inventory which clevermethod properties actually run on Liquid Web VPS/Cloud versus Nexcess Managed WordPress.
- Determine whether Liquid Web API/Terraform support is relevant to current production assets.
- Evaluate whether a common infrastructure automation module is needed.

### Solid Deployments

- Determine whether Solid Deployments exposes APIs, CLI commands, webhooks, or automation hooks.
- Determine whether it has a useful role in the clevermethod deployment workflow.

## 19. Recommended Nexcess Support Questions

**SENT 2026-08-22 as one ticket. PARTLY ANSWERED 2026-08-24.** The full text
of what was asked, what came back, and the outstanding reply are in
`docs/NEXCESS-SUPPORT.md`. Items 1 and 2 are answered; the rest of this list
was either not covered or was never sent, and is marked accordingly.

1. ~~If an SSH public key is added under a Nexcess user's **SSH Keys**, does it automatically authorize that key for every Managed WordPress site the user currently has access to?~~ **ANSWERED 2026-08-24: yes, keys are user/account-level.**
2. ~~Does the same key automatically work on newly created Managed WordPress sites?~~ **ANSWERED 2026-08-24: yes, stated explicitly.**
3. When site/team access is removed from that user, is SSH access using that key removed immediately? **asked, not answered**
4. Can a user-level SSH key be limited to selected sites? **asked, not answered**
**Items 5–12 were never sent.** The 2026-08-22 ticket carried only the two
blocking questions, deliberately — a twelve-part list invites one paragraph
answering none of it. They remain worth asking once the API is reachable, at
which point most of 6–10 become measurable rather than askable.

5. Are there documented SSH concurrency limits for automated connections across many Managed WordPress sites?
6. Are there published Client Portal API rate limits?
7. Do Client Portal API tokens inherit the permissions of the user/team that created them?
8. Are API tokens scopeable or time-limited?
9. Is `GET /v1/site` the recommended API for maintaining an account-wide Managed WordPress site inventory?
10. Is the Unix/SSH username returned by the site-detail API considered stable and supported for automation?
11. Is there a current recommended CI/CD pattern for GitHub Actions + Nexcess Managed WordPress?
12. Are there any Nexcess deployment hooks, APIs, or webhooks not currently documented publicly?

## 20. Current Recommendation

Proceed with the following design assumption for the proof of concept:

```text
GitHub Actions
      |
      +-- Nexcess Portal API token
      |       |
      |       +-- discover sites
      |       +-- retrieve metadata
      |
      +-- dedicated Nexcess SSH key
              |
              +-- site-specific SSH usernames
              +-- WP-CLI
              +-- read-only operational workflow
```

However, do **not** make automated fleet-wide SSH dependent on centralized SSH-key propagation until Nexcess confirms that behavior.

The API + SSH model appears sufficient to build a centralized clevermethod WebOps automation layer across Nexcess and Pantheon without maintaining unique credentials for every site, but the credential-propagation and API-permission details need to be validated before production rollout.

## Sources

Nexcess / Liquid Web documentation referenced during research:

- Nexcess SSH user setup: https://www.nexcess.net/help/secure-shell-ssh-user-setup-for-the-nexcess-cloud/
- Nexcess SSH key management: https://www.nexcess.net/help/add-ssh-key-to-server-for-your-nexcess-cloud-account/
- Nexcess API tokens: https://docs.nexcess.com/sites-stores/account/account-security/api-tokens/
- Nexcess API documentation repository: https://github.com/nexcess/nexcess-api-docs
- Nexcess GitHub / Git documentation: https://www.liquidweb.com/help-docs/control-panel/nexcess/github/
- Nexcess WordPress documentation: https://docs.nexcess.com/learn/applications/wordpress/
- Nexcess cron documentation: https://docs.nexcess.com/sites-stores/managed-woocommerce/store-management/cron-jobs/
- Nexcess staging/development environments: https://docs.nexcess.com/sites-stores/managed-woocommerce/store-management/dev-staging-environments/
- Nexcess Visual Comparison: https://docs.nexcess.com/sites-stores/managed-wordpress/plugin-management/visual-comparison/
- Liquid Web SSH keys: https://www.liquidweb.com/help-docs/server-administration/linux/setting-up-and-using-ssh-keys/
- Liquid Web API: https://api.liquidweb.com/docs
- Liquid Web CLI: https://www.liquidweb.com/help-docs/portal/using-the-liquid-web-command-line-interface-lw-cli/
- Solid Deployments: https://www.liquidweb.com/help-docs/control-panel/solid-central/deploy-your-wordpress-site/
