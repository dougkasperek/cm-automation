# Build or buy the fleet layer

**Assessed 2026-08-30. Verdict: keep building, buy nothing, turn on two things
the hosts already include and clevermethod already pays for.**

**PANTHEON WORKSPACE TIER CONFIRMED BY DOUG 2026-08-30: PLATINUM.** Multidev and
Autopilot are included, and Platinum is one of the two tiers that get Autopilot's
daily and custom schedules rather than the limited set on Gold. Judged on the 68 sites that are the bulk of the
fleet, not the 10 outliers.

## The short version

The commercial WordPress fleet managers sell one headline feature: apply
updates to every site from one screen.

- **On the 47 Pantheon sites it cannot run at all.** Pantheon: "Code is
  writable in the Dev (or a Multidev) environment, but is locked in Test and
  Live." A management plugin cannot apply an update to a live Pantheon site.
- **On the 21 Nexcess sites it can run, and is redundant.** Nexcess Visual
  Comparison already stages plugin updates every 4 days, compares screenshots,
  and blocks any update that changes the site beyond a threshold. Enabled by
  default, no extra cost.

That is 68 of 78 sites where the thing being sold is either impossible or
already paid for.

## What cm-automation does that nothing on the market does

| capability | buyable |
|---|---|
| Update status: core, plugins, themes | yes, both sides fine |
| Installed component inventory | yes |
| PHP version, backup age, plan | yes |
| Pantheon upstream drift | **no** |
| SPF / DKIM / DMARC | **no** |
| Consent cold sweep | **no** |
| Consent gating (does Reject All stop the tags) | **no** |
| Append-only ledger and the change model | **no** |
| Severity tuned per axis to this fleet | **no** |
| Attestation capture | **no, and nobody sells it** |

Seven of ten are not for sale. Two of them are billable service lines.

## Products and list price at 78 sites

| product | cost | shape |
|---|---|---|
| MainWP | $199/yr | self-hosted, unlimited sites, flat fee, backups/uptime via integrations |
| ManageWP | $1,800/yr | free tier + $150/mo per 100-site bundle |
| WP Umbrella | ~$2,000/yr | EUR1.99/site/mo, all-inclusive, Patchstack scanning every 6h |
| Patchstack Developer | ~$2,478/yr | 25 sites + $12.50/mo per additional 5 |

They provide six real things: bulk updates, backups, uptime, vulnerability
scanning, white-label client reports, one-click login. All six require a child
plugin on every managed site.

## The gaps that are real

1. **Uptime.** Nothing in the stack watches whether a site is up. New Relic
   free tier has unlimited ping monitors, all 78 domains, no credentials.
   Generate the monitor list from `data/fleet-inventory.json` so it cannot
   become a fifth site list.
2. **Vulnerability data.** `fleet-vuln.py` is days old. Wordfence publishes a
   free feed. Consume it; keep our own scoring. Do not maintain a matcher.
3. **Update execution.** The scanner reports pending upstream merges and
   nothing applies them. **Pantheon Autopilot** with the destination set to
   `Do Not Deploy` is the read-only-until-trusted principle applied to a tool
   already paid for. Multidev + visual regression on core/plugins/themes/
   upstream, bulk-enable up to 100 sites. **Autopilot's Multidev does NOT count
   against the site's Multidev allowance.** Limits: core/plugins/themes only
   (custom code and templates still need a person), up to 25 pages per site,
   anonymous pages only. **Nexcess Visual Comparison** is the parallel on the
   other 21 and is already on.
4. **Client-facing reports.** A renderer change to a tool we own, or a product
   decision later.
5. **Attestation capture.** Until the dashboard records who verified what and
   when, the workbook does not die.

## Next actions

1. ~~Confirm the Pantheon workspace tier.~~ **DONE: Platinum.**
2. Enable Autopilot with the destination set to `Do Not Deploy`. Start with a
   cohort drawn from the sites the scanner already flags as `upstream_pending`,
   and compare Autopilot's verdict against what the scan expected.
3. Confirm Nexcess Visual Comparison is on and read what it has been doing.
   Nobody has looked. If it has been silently blocking updates on 21 sites,
   that explains pending counts that will not clear.
4. New Relic ping monitors, all 78 domains, free.
5. Wordfence feed for vulnerability data.
6. **Retire the "Pantheon allowlist ask" from the standing list.** It is a dead
   item that keeps resurfacing. The consent 403s were never Pantheon's rule
   (`server: cloudflare`, `cf-mitigated: challenge` on the CLIENTS' own zones,
   four different DNS providers, zero requests reaching Pantheon), and running
   the browser HEADED solved it on 2026-08-22 anyway: 27 of 28 blocked sites
   load, CI proven via xvfb. Residual is 7 sites that refuse the GitHub runner,
   which the coverage-drop guard already handles. See
   `docs/SESSION-HANDOFF.md` "The 403s".
7. Revisit WP Umbrella only if the agency sells managed maintenance as a
   product with monthly white-label reports as the deliverable. Service
   decision, not a tooling one.

**New spend: none.**

## Not verified

- Whether any Pantheon site is on a **Basic** plan. Basic cannot use New Relic,
  and the workspace tier does not change that; it is a per-site plan question.
- How Nexcess Visual Comparison behaves on sites the team also updates by hand.
  Nexcess says it does not replace manual management via wp-admin or WP-CLI.
- Whether the Flywheel and Azure sites are ones we can install anything on.
  Two Flywheel sites are client-controlled and still on PHP 7.4.
- Pricing is list price read from vendor pages 2026-08-30, not partner pricing.

## Sources

docs.pantheon.io/pantheon-workflow | docs.pantheon.io/guides/autopilot/enable-autopilot |
docs.pantheon.io/guides/multidev | docs.pantheon.io/guides/account-mgmt/plans/workspace-plans |
docs.nexcess.com/sites-stores/managed-wordpress/plugin-management/visual-comparison/ |
mainwp.com/pricing | managewp.com/pricing | wp-umbrella.com/pricing |
docs.patchstack.com/getting-started/pricing-plans/ | newrelic.com/pricing/free-tier
