# Secrets management: the concept for the team

**For Nick Federico, to present at the regroup the week of 2026-09-08.**
Written 2026-09-03 from the 2026-09-01 regroup transcript, `docs/SECRETS.md`
(Doug's Keeper notes for the CI side, 2026-08-09), the fleet's own component
catalogue, and vendor documentation read on 2026-09-03. Every vendor claim
below carries a source at the end; the ones marked **unverified** were not
found on any vendor page and have to be tested or asked.

Brian asked for: the pieces, the flow, the steps, the cost, the assumptions,
and the known challenges. Not a working thing. This is that.

---

## 1. The problem, stated the way the data supports it

Brian framed it on the call as "Autopilot brings live down and steps on dev,
and Zach spends time pasting keys back". Two corrections before building on
it, both from the call itself and from Pantheon's docs.

**The mechanism is real and it is opt-in.** Autopilot's *Sync Environment*
setting copies Live's database and files to Dev before each run; code is not
copied. Premium plugin licence keys live in the database (`wp_options`), so
whatever Live holds overwrites whatever Dev held. (Sources 1, 2.)

**The keys were lost because they were never on Live.** A key entered on Dev
during a build, and never entered on Live at launch, is gone at the next sync.
Zach said so and fixed it by hand: put the key on Live once and it flows down
from then on. He called it "one and done", and he is right about the
inconvenience half. That half is a two-minute step at launch, not a system.

**What is left is the security half, and it is the half Brian named last.**
Zach copies the actual key value through his clipboard into a settings page
on each site. Nobody's eyes should be on the value; it should come from a
store and be placed by a machine. And a key that lives in code or in a
platform secret survives every refresh and every new environment, which a
key in the database does not.

So the concept has one job: **premium plugin licence keys and the automation
suite's own credentials are placed by machines, from one store of record,
and no person types or sees the values.**

---

## 2. The pieces

Four, and three already exist.

| piece | what it is | cost | state |
|---|---|---|---|
| **Keeper** (the vault of record) | The company's existing vault. Keeper Secrets Manager (KSM) is the add-on that lets a *machine* read from it: an "Application" is a machine identity that sees only the folders shared to it, zero-knowledge, decrypted on the client. No PHP SDK exists, so WordPress cannot read Keeper directly (3, 4, 5, 6). | Add-on to the business plan, licensed per user per year. **No published price; sales quote** (7, 8). | Not enabled. Victoria: it is "an entire different aspect of Keeper that we don't have". |
| **GitHub Actions** (the courier) | The fleet automation already runs here with its credentials in repository secrets. Keeper's own action reads secrets into a job and masks them in logs (9). The KSM config blob is the bootstrap credential and stays a GitHub secret; Keeper protects everything except itself (`docs/SECRETS.md`). | $0 | Live, six scanners. |
| **Pantheon Secrets** (the delivery on 52 sites) | Free on every plan, built into Terminus 4.2+. A secret is set per site or per organisation with an environment override, lives outside the database and the files, and is read in PHP with `pantheon_get_secret()`. Pantheon's own WordPress guide recommends exactly this for licence keys, and its own example defines a plugin constant in `wp-config.php` from a secret (10, 11, 12, 13, 14). | $0 | Available. Not in use. |
| **The plugin** (the consumer) | A plugin that reads its key from a PHP constant takes it from `wp-config.php`, which is code, which Autopilot does not sync. Six of the fleet's fourteen premium products document such a constant. **The Divi family does not.** See section 4. | $0 | Per plugin. |

Nexcess has no secrets service and no documented environment variables (15).
Its auto-updater copies production to a staging copy and updates there, so a
key in the database carries over; the refresh problem does not exist on
Nexcess (16). Only the eyes-on-the-key problem does. See section 6.

---

## 3. The flow

**Today.** Zach reads a key from Keeper or a vendor account, pastes it into
Plugin Settings on Live and on Dev. The value is on his screen and in his
clipboard. Autopilot syncs Live's database to Dev, clones Dev to its own
Multidev, updates there with WP-CLI, merges back to Dev and deploys on to
Test and Live (1, 17, 18).

**Proposed, for a plugin that reads a constant.**

1. The key is a record in Keeper, in a folder shared to one KSM Application
   named for the CI job. A person puts it there once, in the vault, where it
   already lives today.
2. A GitHub Actions job reads it with Keeper's action, masked, and runs
   `terminus secret:org:set` for a key shared across the fleet (Gravity
   Forms' unlimited licence, for one) or `terminus secret:site:set` for a
   per-site key (10, 19).
3. Each site's `wp-config.php` carries one guarded line per plugin, committed
   once:
   `if (function_exists('pantheon_get_secret')) define('GF_LICENSE_KEY', pantheon_get_secret('gf_license_key'));`
4. The plugin reads the constant. The settings field goes read-only or
   disappears. The value is never in the database, so Sync Environment cannot
   remove it, and every environment (Dev, Test, Live, the Autopilot
   Multidev) sees it, because site and org secrets are visible to every
   environment (20).
5. Autopilot updates as before. Nothing in its path changes.

Nobody types the value after step 1, and step 1 is into the vault, which is
the one place it is supposed to be.

**For the suite's own credentials** (the Pantheon machine token, the SSH keys,
the Nexcess API token, the Cloudflare token, the Wordfence key, the Teams
webhook): the same Keeper Application feeds the same jobs, replacing the six
GitHub secrets set by hand today. `docs/SECRETS.md` section 2 has the exact
YAML; it was written for this and needs no change.

---

## 4. Which plugins can take a key from code

Measured against the fleet's component catalogue, latest scan per site,
68 sites inventoried. "Sites" is sites, not installs.

| plugin | sites | key from code | how | source |
|---|---|---|---|---|
| Gravity Forms | 9 | **yes, documented** | `GF_LICENSE_KEY` in wp-config; field goes read-only; also `wp gf license update` | 21, 22 |
| ACF PRO | 4 | **yes, documented** | `ACF_PRO_LICENSE`; the plugin activates the site itself | 23 |
| Object Cache Pro | 20 | **yes, documented** | `token` in `WP_REDIS_CONFIG`; on Pantheon the recommended config reads it from an environment variable already | 24, 25 |
| WP Activity Log (premium tier only) | 65 installs | yes, documented | `WP__WSAL_FREEMIUS_LICENSE_KEY` plus a snippet; free tier needs no key | 26 |
| Elementor Pro | 1 | WP-CLI | `wp elementor license activate`; no constant | 27 |
| UpdraftPlus Premium | 10 | WP-CLI | connects with account credentials, not a key | 28 |
| WPMU DEV Dashboard / Smush Pro | 1 | in source, undocumented | `WPMUDEV_APIKEY`; confirmed in a plugin mirror, not in vendor docs | 29 |
| Formidable Pro | 2 | in source, undocumented | `FRM_PRO_LICENSE` (the call's `FRM_LICENSE` was wrong) | 30 |
| **Divi** | **65** | **no** | username and API key typed into Theme Options; one key may serve many sites | 31 |
| **Divi Booster** | **37** | **no** | key typed into its settings page | 32 |
| **Divi Overlays** | **17** | **no** | key typed in; licences count activations per site | 33 |
| PDF Embedder Premium | 13 | no | settings field only | 34 |
| TablePress (paid tiers) | 10 | no | Freemius; key typed in after upload | 35 |
| Yoast SEO Premium | 1 | no key exists | activated from the MyYoast account | 36 |

Two things this table settles.

**The constant route covers the plugins that break Autopilot updates most
often and misses the one that is on nearly every site.** Gravity Forms, ACF
and Object Cache Pro are the documented cases and the pilot candidates. The
Divi family, on 65, 37 and 17 sites, has no code path at all. For Divi the
answer stays what Zach found: the key on Live, carried down by the sync. Two
possible code paths exist for it and **both are untested**: WordPress core's
`pre_option_` filter, which can supply any option from code (37), and a
Quicksilver hook after `clone_database` that re-writes the option from a
Pantheon secret (38). Either would be our code, and each plugin would need a
test of whether it re-reads the injected value or a separately stored
activation flag.

**A constant removes the typing. It does not remove the activation.** Every
one of these plugins still calls its vendor to activate the site. Divi
Overlays and the Freemius products count activations per site, so Dev, Test
and the Autopilot Multidev may each consume one. Pantheon says a licence must
be active on Dev before the Autopilot Multidev is created, and that some
plugins need activating on each environment (1).

---

## 5. Cost

| item | cost | basis |
|---|---|---|
| Keeper Secrets Manager add-on | **quote required**; per user per year | Keeper publishes no number (7, 8). Nick to ask the Keeper account rep how many seats need the add-on: every vault user, or only the one who creates Applications. |
| Pantheon Secrets | $0 | free on every plan (10) |
| GitHub Actions | $0 | already running |
| Autopilot | already paid | Gold, Platinum, Diamond or Agency plans only (39) |
| Alternatives, for the record | 1Password Business $8.99 per user per month, Secrets Automation included, no PHP SDK either (40, 41). HashiCorp HCP Vault Dedicated from $0.62 per cluster per hour plus $73 per client per month on the paid tiers (42): for a fleet of sites it is the wrong shape and the wrong price. | The company already pays for Keeper; a second vault needs a reason. |
| Effort | one `wp-config.php` commit per Pantheon site per plugin, scriptable; one `terminus secret` call per key, scriptable; a Keeper folder and Application, once | a day of Zach's time for the three documented plugins across their 33 sites, if the two tests in section 7 pass |

---

## 6. Nexcess, and one control this touches

Nexcess Managed WordPress has no secrets service and documents no
per-site environment variables (15). Its own updater copies production to a
staging copy every four days and updates there, so a key in the database is
not lost the way it is on Pantheon (16). The only path to a constant is
editing `wp-config.php` over SSH, which WP-CLI can do with `wp config set`
(43).

**That path changes a security control.** This repo reaches Nexcess with one
account-level SSH key that can write to every site, and Nexcess has confirmed
no read-only SSH user exists. The list of commands the scan runs is the only
thing making the tool read-only, and Doug approved that list as such. Adding
a write command to it is a decision, not a configuration. The honest option
for the 22 Nexcess sites is to leave licence keys as Zach's process until
someone decides that.

---

## 7. Assumptions and known challenges

In the order they would stop the concept.

1. **Can a person with site access read a Pantheon secret back?** The goal is
   that nobody sees the value. Whether `terminus secret:site:list` or the
   dashboard's Secrets tab prints values to any team member is **unverified**.
   `terminus secret:site:local-generate` writes them to a JSON file on a
   laptop by design (19). If any team member can list values, Pantheon
   Secrets still beats the clipboard, but "nobody sees it" becomes "only
   people with Pantheon site access see it". Ten minutes on one site.
2. **Does WP-CLI on the Autopilot Multidev see the secret?** Pantheon says
   web-scope secrets are for the application runtime, that Quicksilver can
   read them, and that cron needs a different scope. WP-CLI is not mentioned
   anywhere (12, 20). If Autopilot's update process cannot see the constant,
   the plugin is unlicensed at exactly the moment it updates. **Unverified.**
   One `terminus wp` call on one Multidev settles it.
3. **The Divi family has no code path.** 65 sites. Section 4.
4. **Per-site activation counts.** Section 4.
5. **Is Sync Environment on?** It is a per-site dashboard setting and the
   ledger does not record it (2). If it is off on a site, that site's key loss
   was not Autopilot's doing.
6. **The Keeper cost is unknown** and the seat model matters more than the
   rate.
7. **GitHub runners have changing addresses.** A KSM Application is IP-locked
   by default and must be created unlocked for hosted runners (44).
8. **Nexcess.** Section 6.

---

## 8. What to do before presenting

1. Ask the Keeper admin two questions: is the Secrets Manager add-on enabled,
   and what is the quote for our seat count. Doug's four questions in
   `docs/SECRETS.md` section 4 still stand.
2. Run the two tests in items 1 and 2 above on one Pantheon site. Both take
   minutes and both change the pitch.
3. Pick Gravity Forms as the pilot: documented constant, WP-CLI path, one
   unlimited key shared across nine sites, so an org-level secret covers all
   of them.
4. Bring the plugin table. It is the slide that answers "does this fix
   Divi", and the answer is no, and saying so first is what keeps the room.

---

## Sources

Read 2026-09-03. Each was fetched and checked by a second reader; the four
marked *inferred* are consistent with the pages but not stated on them.

1. https://docs.pantheon.io/guides/autopilot/enable-autopilot (Sync Environment copies database and files, not code; licence active on Dev first; per-environment activation; WP-CLI updates)
2. https://docs.pantheon.io/guides/autopilot/autopilot-faq (Sync Environment is opt-in; Multidev cloned from Dev)
3. https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library (SDK list, no PHP)
4. https://docs.keeper.io/keeperpam/privileged-access-manager/getting-started/applications (an Application is a machine identity)
5. https://docs.keeper.io/keeperpam/secrets-manager/about/security-encryption-model (zero-knowledge)
6. https://docs.keeper.io/keeperpam/secrets-manager/integrations (no PHP or WordPress integration)
7. https://www.keepersecurity.com/secrets-manager.html (add-on, per user per year, contact sales)
8. https://www.keepersecurity.com/pricing/business-and-enterprise.html (no price printed)
9. https://docs.keeper.io/keeperpam/secrets-manager/integrations/github-actions (ksm-action, masked)
10. https://docs.pantheon.io/guides/secrets (free on all plans, Terminus 4.2+)
11. https://docs.pantheon.io/guides/secrets/overview (types, scopes, site and org, overrides, 16 KB)
12. https://docs.pantheon.io/guides/secrets/php (`pantheon_get_secret()`, web scope, 15-minute cache, Quicksilver)
13. https://docs.pantheon.io/guides/wordpress-developer/wordpress-secrets-management (recommends Secrets for licence keys)
14. https://docs.pantheon.io/plugins-known-issues (WPML: a constant beats the database value, so pushes do not lose it)
15. Nexcess documentation searched for environment variables, 2026-09-03: nothing found. *Absence, not a page.*
16. https://docs.nexcess.com/sites-stores/managed-wordpress/plugin-management/visual-comparison/ (every 4 days, staging copy)
17. https://docs.pantheon.io/guides/autopilot/troubleshoot-autopilot (updates via WP-CLI; Multidev to Dev to Test to Live)
18. https://docs.pantheon.io/pantheon-workflow (a files clone is wp-content/uploads; code writable only on Dev and Multidev)
19. https://docs.pantheon.io/guides/secrets/create and https://docs.pantheon.io/terminus/commands (`secret:site:set`, `secret:org:set`, `local-generate`)
20. https://docs.pantheon.io/guides/secrets/overview (site secrets visible to every environment; cron needs `ic` scope; WP-CLI unmentioned)
21. https://docs.gravityforms.com/gf_license_key/ and https://docs.gravityforms.com/wp-config-options/
22. https://docs.gravityforms.com/manage-gravity-forms-license-key-with-wpcli/
23. https://www.advancedcustomfields.com/resources/how-to-activate/ (`ACF_PRO_LICENSE`, since 5.11)
24. https://objectcache.pro/docs/configuration-options (`token` in `WP_REDIS_CONFIG`)
25. https://docs.pantheon.io/object-cache/wordpress (Pantheon's recommended config reads the token from an environment variable)
26. https://melapress.com/support/kb/activate-melapress-plugin-license-programmatically/
27. https://developers.elementor.com/docs/cli/license-activate
28. https://teamupdraft.com/documentation/updraftplus/premium-features/how-to-operate-updraftplus-from-the-wp-cli/
29. https://github.com/ORCA-WPMU/wpmudev-updates/blob/master/includes/class-wpmudev-dashboard-site.php (plugin source mirror, version 4.4; vendor docs silent)
30. https://github.com/Strategy11/formidable-forms/blob/master/classes/models/FrmAddon.php (`FRM_<SLUG>_LICENSE` pattern; vendor KB silent)
31. https://help.elegantthemes.com/en/articles/9502180-how-to-manage-api-keys-and-activate-your-license
32. https://divibooster.com/how-to-install-the-divi-booster-plugin/
33. https://divilife.com/downloads/divi-overlays/ (per-site activation count)
34. https://wp-pdf.com/docs/premium-instructions/
35. https://tablepress.org/pricing/
36. https://yoast.com/help/activate-premium-license/
37. https://developer.wordpress.org/reference/hooks/pre_option_option/
38. https://docs.pantheon.io/guides/quicksilver/hooks (`clone_database` hook)
39. https://docs.pantheon.io/guides/autopilot (eligible plans; pricing via Sales)
40. https://1password.com/pricing/business
41. https://www.1password.dev/sdks (Go, JavaScript, Python)
42. https://www.hashicorp.com/en/products/vault/pricing (rendered in a browser; the tab prints the figures)
43. https://developer.wordpress.org/cli/commands/config/set/
44. https://docs.keeper.io/keeperpam/secrets-manager/about/one-time-token (IP-locked by default; `--unlock-ip`)
