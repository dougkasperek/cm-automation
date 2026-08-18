# The manual security audit sheet: what can be automated, and how Nexcess fits

**2026-08-17.** Analysis of `wordpresssecurityemailaudit.xlsx`, the workbook the
clevermethod team maintains by hand. Nothing was built or changed to produce
this. Findings are grounded in the workbook joined against the two real fleet
health runs, plus live DNS lookups and vendor documentation.

---

## 1. What the workbook actually is

78 site rows, 28 columns, three sheets. It is **not** a host health check. The
`Security Event Log` sheet explains why it exists:

- **2026-04-03.** `packagedesignsupply.com` served a malicious reCAPTCHA to
  Windows users. One of two admin accounts was compromised. The investigation
  found that almost all clevermethod admin accounts shared one password.
- **2026-07-17.** `wp2shell`, an unauthenticated RCE chain in WordPress core
  6.9.0-6.9.4 and 7.0.0-7.0.1 (CVE-2026-63030 route confusion in the REST batch
  endpoint, CVE-2026-60137 SQL injection in `WP_Query`). Remediation was a core
  upgrade to 7.0.2 plus a sweep for injected admin users and plugins.

So this is a **security posture attestation record**, built in response to two
real incidents. That framing matters, because a record of "a human verified this
control on this date" has value that a live status check does not replace.

### It is doing three jobs at once

| job | columns | who should own it |
|---|---|---|
| **Inventory** | domain, hosted, DNS | human, permanently |
| **Observable state** | PHP, WP version, themes, plugins, xmlrpc, plugin presence, SPF/DKIM/DMARC | machine |
| **Attestation** | single CM user, Keeper password, wp2shell remedied, 2FA configured | human, but dated and expiring |

**This is the reason the sheet is expensive.** A person retypes observable facts
in order to keep the attestation record credible. Automation should take the
observable block entirely, leave inventory human, and convert attestation into a
dated claim with an expiry so a stale "Yes" is visibly stale.

### Fleet composition

| host | sites |
|---|---|
| CM Pantheon | 47 |
| CM Nexcess | 21 |
| Azure | 4 |
| Pressable | 3 |
| Flywheel | 2 |
| WP Engine | 1 |

---

## 2. The workbook resolves the 52-vs-54 site count

The long-standing open question is answered, and it produces two new specific
findings.

Domain and Pantheon machine name are unrelated strings (`kraftnaturalcheese.com`
is `kraftcheese`, `local92afm.com` is `l92`, `packagedesignsupply.com` is
`pdsci`). **Nothing on disk maps them.** That absent join key is precisely what a
human currently supplies from memory. Mapping it by hand:

```
sheet CM Pantheon domains        47
  mapped to a scanned site       46
  in the sheet, not in the scan   1   hoosierfeeder.com
scan sites                       52
  in the scan, not in the sheet   6
46 + 6 = 52   reconciled
```

The six scanned sites absent from the sheet:

| site | status | plan |
|---|---|---|
| cm-whitelabel | CRIT | Sandbox |
| clevermethod-forward | SKIP | Sandbox |
| moorseville-nc | SKIP | Sandbox |
| nc-moorseville | FROZEN | Sandbox |
| pfannenbergsales | SKIP | Sandbox |
| **hoffmanscheese** | **CRIT** | **Sandbox** |

**Finding A: `hoffmanscheese` is in no row of the team's own audit.** Three
documents guess that it "looks client-named." It is a site the authoritative
human inventory does not track. Either it is an orphan to decommission or a
client site missing from the audit. Either way it is now a specific question with
a specific answer path, not a guess.

**Finding B: `hoosierfeeder.com` is listed as CM Pantheon and attested across
every security column, and the Pantheon account does not return it.** This is the
more serious direction: a site being attested to that is not being observed.
Possible causes are a decommission the sheet has not caught up with, a different
machine name, or a different Pantheon organization.

Both findings are exactly the `INVENTORY` change class from the design revisit,
firing on real data. Neither is visible today because the two sources have never
been joined.

---

## 3. Question 1: replacing the manual process for the Pantheon fleet

Column by column, for the 46 reconciled Pantheon sites.

### Already collected by the scan, needs only joining and rendering

| column | source | note |
|---|---|---|
| PHP Version (16) | `env:info`, api-only | **The two sources already agree exactly**: sheet says 45 on 8.2, 1 on 8.1, 1 on 8.3; the scan says the same. That agreement is the validation that the join is correct. |

The scan also produces backup age and upstream drift, which the sheet does not
track at all. That is net new information, not a replacement.

### Needs full mode (SSH plus WP-CLI). Written already, blocked only on the runner SSH key

| column | WP-CLI call |
|---|---|
| WordPress Version (17) | `wp core version` |
| Themes Up to Date (18) | `wp theme list --update=available` |
| Plugins Up to Date (19) | `wp plugin list --update=available` |
| WP Activity Log configured (20) | `wp plugin list` |
| WP 2FA configured (21) | `wp plugin list` |
| WPS Hide Login configured (22) | `wp plugin list` |
| xmlrpc.php disabled (23) | `wp plugin list` |
| Single CM User (15) | `wp user list --role=administrator` |

Four observations about this block:

1. **The sheet asserts WordPress 7.0.2 on all 78 sites and the scan cannot
   currently confirm it on any.** One month after a critical RCE whose only fix
   was that upgrade, this is the most safety-critical column in the workbook and
   it is an unverified human claim. Full mode turns it into an observation.
2. **The four plugin-presence columns are one `wp plugin list` call**, not four
   checks. And the `Security Plugins` sheet already documents exact slugs plus
   the acceptable alternates (Defender for 2FA on three named sites, two
   different XML-RPC disablers). That is a machine-readable rule set already
   written down, which is unusual and valuable.
3. **`Single CM User` is the exact control that failed in April.** Automating it
   means the shared-password class of incident becomes continuously monitored
   rather than annually attested.
4. This is also where the **fabricated zeros** live. In api-only mode the scan
   writes `plugin_updates: 0` and `theme_updates: 0` on sites it never checked,
   so those columns currently read as verified-clean when nothing was looked at.
   Fix that before joining anything, or the join will import a false negative
   into a security record.

### Needs no host access at all

| column | method |
|---|---|
| SPF (10) | TXT lookup on the sending domain |
| DKIM (11) | TXT lookup on the selector |
| DMARC (12) | TXT lookup on `_dmarc.<domain>` |

Verified: DNS resolution works from the cloud sandbox, unlike Pantheon. So this
is the one part of the fleet audit that does not require Doug's Mac or a CI
runner.

**And most of it is one check, not 78.** Sixty sites share the sending domain
`smtp.clevermethod.net`. Its SPF is `v=spf1 include:mailgun.org ~all` and its
DMARC is `p=none`. One record governs 60 rows. Cause-grouping again, in a second
independent place.

### Should not be automated

| column | why |
|---|---|
| Generated Password in Keeper (25) | Keeper Secrets Manager can confirm a record exists; it cannot confirm the stored password is the one in use. Keep as a dated attestation. |
| Dev/Test PHP Blocker (24) | Judgment, and 48 of 78 rows are blank. |
| Notes (27) | Judgment, and genuinely useful as written. |

### The caution that matters more than the column list

**The Pass/Fail semantics are not written down anywhere in the workbook.**

Twelve rows read DMARC `Fail`. Live lookups on all twelve show **every one has a
valid DMARC record.** Policies range across `p=none`, `p=quarantine` and
`p=reject`. So `Fail` does not mean "record missing," and it does not map cleanly
to policy strength either. It is the output of some specific tool or rule,
plausibly alignment between the sending domain and the From-header domain, which
would explain `galbanicheese.com` sending from `app.galbani.com`. Whatever the
rule is, it lives in a person's head.

An automation that re-derives Pass/Fail on a different rule will silently
disagree with 78 rows of history, and nobody will know which side is right.
**Capture the rule before automating the column.** This is the same class of
problem as the fabricated zeros: pin the semantics first, then automate.

### What the replacement looks like

1. The three inventory columns become the checked-in inventory file, keyed on
   **both** Pantheon machine name and domain, supplying the join key that does
   not currently exist anywhere.
2. Full-mode scan output flows into the ledger.
3. The digest reports what changed, plus standing exceptions grouped by cause.
4. The workbook becomes a generated view rather than a retyped one. Attestation
   columns stay human, gaining a date and an expiry.

**Single dependency: the runner SSH key** (phase 2, already documented). It
converts eight columns from manual to observed.

---

## 4. Question 2: including Nexcess

### The reason is not tidiness

**All 21 blank cells in the `wp2shell Security Flaw Remedied?` column are Nexcess
sites, and they are the only blanks in that column.** All 47 Pantheon sites say
Yes. All 10 outlier-host sites say Yes. Every Nexcess site is blank.

The event log explains it: "Pantheon provided audit and remediation scripts for
sites hosted on their platform; other sites required manual checks." Pantheon
sites got tooling. Nexcess sites needed a person, and the record shows the person
did not get there.

So on a critical unauthenticated RCE remediated a month ago, **Nexcess is exactly
where the evidence is missing, and it is missing because it is the host where the
check was manual.** Automating Nexcess closes the largest open evidence gap in
the workbook.

### The architecture already accommodates it

The scan does three separable things. Only the first two are Pantheon-specific.

| capability | Pantheon | Nexcess |
|---|---|---|
| enumerate sites | `terminus site:list` | Client Portal API token. **Endpoint unverified, see below.** |
| platform facts (PHP, backups, plan) | `env:info`, `backup:list` | portal exposes them; API coverage unverified |
| WordPress facts (core, plugins, themes, admins) | `terminus remote:wp` | **SSH and WP-CLI are available. Same commands.** |
| email and DNS facts | public DNS | public DNS, identical |

**The good news is the third row.** Nexcess Managed WordPress provides SSH and
SFTP access, with credentials in the Site Dashboard and SSH key support. That
means the entire deep-scan half, which is the bulk of the security columns, ports
essentially unchanged. It is the same WP-CLI calls over a different transport.

**The one genuine unknown is enumeration.** Nexcess API tokens are created in the
portal under User Menu, then API Tokens. The endpoint reference lives in the
`nexcess/nexcess-api-docs` GitHub repository, which could not be read from this
environment. Treat the base URL, auth header and site-listing endpoint as
**unverified** until someone with a token spends ten minutes confirming them.
Everything else in this section holds regardless of how that resolves, because
worst case enumeration falls back to the inventory file, which is a human list
anyway.

### Shape of the change

A `providers/` layer with one adapter per host, each answering two questions:
list sites, and get platform facts. A shared WP-CLI module consumes whatever the
adapters return. The Pantheon adapter exists today, embedded in the scan script.
The Nexcess adapter is the new work.

**The ledger, the diff, the digest and the dashboard do not change at all.** They
are keyed on site identity, not on host. That was not planned for, but it is what
the design happens to give.

### The four outlier hosts

Ten sites: Azure 4, Pressable 3, Flywheel 2, WP Engine 1. Do not build adapters.
They are not equally benign:

- **Flywheel's two sites, `shuman-plastics.com` and `dynapurge.com`, are on PHP
  7.4.** Security support for 7.4 ended 28 November 2022, so these have gone
  close to four years without patches. This is the worst finding in the workbook,
  and because the hosting is client-provided it is a client conversation rather
  than a task.
- Pressable's three are on 8.4 and Azure's four on 8.5, both ahead of
  clevermethod's own fleet.

For all ten, the email and DNS checks work for free, and WP-CLI works wherever
SSH exists. Where it does not, the row stays an explicit `unknown` with a named
owner. That is honest, and representing it correctly is what the ledger is built
for.

---

## 5. Recommended sequence

1. **Email and DNS checks first, before either host adapter.** They cover all 78
   sites, need no credentials, no SSH key, no API token and no platform decision,
   and they retire five to seven columns in one step. The only piece with zero
   blockers. Capture the Pass/Fail rule as part of this.
2. **Fix the fabricated zeros** in the scan. Two lines, and it has to precede any
   join into a security record.
3. **Build the inventory file from the workbook's three inventory columns**,
   keyed on machine name and domain. This is where findings A and B get resolved.
4. **Pantheon runner SSH key.** Unlocks eight columns on 46 sites.
5. **Nexcess enumeration**, gated on the ten-minute API verification. Then the
   Nexcess deep scan, which reuses the WP-CLI work from step 4.
6. Outlier hosts stay manual, with email and DNS covered for free and an explicit
   `unknown` everywhere else.

---

## 6. One correction to a previous number

The design revisit noted PHP 8.2 losing security support on 31 December 2026 with
46 of 52 Pantheon sites affected. Fleet-wide the workbook shows **63 of 78 sites
on 8.2**, so the December deadline is larger than stated.

Mitigating: 4 sites already run 8.5 and 3 run 8.4. The upgrade path is proven in
practice, which makes December a scheduling problem rather than an open risk.

---

## Sources

- Workbook: `wordpresssecurityemailaudit.xlsx`, `Sites` / `Security Plugins` /
  `Security Event Log`
- Fleet scans: `reports/fleet-health-2026-08-16_1725.json`,
  `reports/fleet-health-2026-08-17_0726.json`
- PHP support calendar: php.net/supported-versions, checked 2026-08-17
- Nexcess API tokens: docs.nexcess.com, account security, API tokens
- Nexcess SSH: docs.nexcess.com, managed WooCommerce, SSH credentials
- DMARC and SPF values: live DNS TXT lookups, 2026-08-17
