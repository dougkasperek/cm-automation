# Security event log

**Copied out of the manual workbook on 2026-08-23, verbatim except where marked.**
Source: `wordpress-security-email-audit.xlsx`, `Security Event Log` sheet, in
SharePoint at `/sites/Projects/Shared Documents/General/`, last modified
2026-08-20 21:10 UTC.

**Why this file exists.** The event log was the only part of the workbook that
had never been extracted: `extract-audit-workbook.py` reads the `Sites` and
`Security Plugins` sheets and nothing else. Three incidents, one of them still
open, existed in exactly one place: a spreadsheet that had already silently
changed shape underneath our importer. It is in git now.

**This is a record, not a feature.** Nothing reads it. A dashboard feature for
capturing security events was discussed on 2026-08-23 and deliberately deferred
until the team has been through the Pods incident and can say what it needs. The
open design questions are at the bottom of this file.

**It is not automatically synced.** If the workbook's event log gains a fourth
incident, this file does not know. Whoever adds it there should add it here, or
this becomes the same stale snapshot the workbook already is.

---

## 1. Malicious reCAPTCHA, and shared admin passwords

| | |
|---|---|
| **Identified** | 2026-04-03 |
| **Remediation complete** | Yes |
| **References** | none recorded |

`packagedesignsupply.com` presented a malicious reCAPTCHA to Windows users. One
of two admin accounts was compromised, which one is unclear, and the attacker
used it to add malicious code to the site.

**The investigation found that almost all clevermethod admin accounts used the
same password**, so every account was potentially compromised.

Remediation recorded:

- Removed the malicious reCAPTCHA code from `packagedesignsupply.com`
- Changed passwords for all cm admin accounts and confirmed entries in Keeper
- Added and configured the WP 2FA plugin on all sites, where applicable
- Added and configured the WP Activity Log plugin on all sites, where applicable
- Added and configured the WPS Hide Login plugin on all sites, where applicable

This incident is where four of the seven attestations in `fleet-inventory.json`
come from: `keeper_password`, `single_cm_user`, `wp_2fa`, `activity_log`,
`hide_login`.

---

## 2. wp2shell: unauthenticated RCE in WordPress core

| | |
|---|---|
| **Identified** | 2026-07-17 |
| **Remediation complete** | Yes |
| **Affected core versions** | 6.9.0–6.9.4 and 7.0.0–7.0.1 |
| **Fixed in** | 7.0.2 |

A critical vulnerability allowing an unauthenticated attacker to take control of
an affected site. It combines two flaws into remote code execution, so an
attacker could create administrator accounts or install malicious code:

- **CVE-2026-63030**: route confusion in the WordPress REST API batch endpoint,
  `/wp-json/batch/v1`
- **CVE-2026-60137**: SQL injection in the `WP_Query` author parameter layer

Remediation recorded:

- Upgraded core to 7.0.2 on all sites
- Checked all sites for suspicious admin users and removed any found
- Checked all sites for suspicious plugins and removed any found

**Pantheon supplied audit and remediation scripts for sites on its platform;
other hosts required manual checks.** That single sentence explains the shape of
the evidence gap: all 21 blank cells in the workbook's `wp2shell Security Flaw
Remedied?` column are Nexcess sites, and they are the only blanks in that column.
The check was manual there and the record shows nobody got to it.

References:

- https://businessinsights.bitdefender.com/technical-advisory-wp2shell-unauthenticated-remote-code-execution-full-site-takeover-wordpress-core
- https://github.com/pantheon-systems-ps/wp2shell-audit
- https://github.com/pantheon-systems-ps/wp2shell-cleanup

**This is the origin of `WP_SECURITY_FLOOR = (7, 0, 2)` in
`scripts/lib/severity.py`.** A site below that floor is CRIT, and the rule reads
the version the site is ON rather than whether an update is pending.

---

## 3. Pods plugin: privilege escalation, CVE-2026-19598

| | |
|---|---|
| **Identified** | 2026-08-20 |
| **Remediation complete** | **"Immediate concerns addressed; See outstanding issues tab"** |
| **Affected versions** | all versions up to and including 3.3.9 |
| **Fixed in** | 3.3.9.1 |
| **Reference** | https://nvd.nist.gov/vuln/detail/CVE-2026-19598 |

The Pods plugin is vulnerable to privilege escalation via authorization bypass.
The `pods_admin` AJAX router funnels every access check through `pods_error()`,
which under the JSON meta-box-loader compatibility path only writes failures to
the PHP error log and returns false instead of terminating the request. Every
guard is therefore ineffective.

An unauthenticated attacker can escalate to Administrator, or overwrite the
password of any user account including the site owner's: complete site
takeover.

Remediation recorded:

- Upgraded the Pods plugin to 3.3.9.1
- Checked all sites for suspicious admin users and removed any found

### Three sites had users added

From the workbook's `Pods sites` sheet. Every other row carries a version and
nothing else; these three carry notes:

| Pantheon site | domain | note in the workbook |
|---|---|---|
| `breakstones` | breakstones.com | **new users were added**, salt rotated |
| `frontline-construction` | live-frontline-construction.pantheonsite.io | **news users were added** [sic], salt rotated |
| `zehnder-america-zna` | zehnderamerica.com | **news users were added** [sic], salt rotated |

Doug, 2026-08-23: caught early and believed resolved; the team meets on it
2026-08-24.

### Two open questions on this incident

**The outstanding-issues tab does not exist.** The `Remediation Complete?` cell
points at it. The workbook has five sheets: `Sites`, `Security Plugins`,
`Security Event Log`, `Effected Sites 8-20`, `Pods sites`, and none of them is
it. Either it was never created or it was deleted.

**The two site lists disagree, and neither is wrong.** `Effected Sites 8-20`
holds 17 sites; `Pods sites` holds 32 with their versions. They are answering
different questions, probably "affected" versus "has Pods installed", but the
sheets do not say which is which. Anyone building on this needs to settle it.

### The two lists, reconciled against the fleet inventory

Checked 2026-08-23. **All 32 rows in `Pods sites` resolve to a site in
`data/fleet-inventory.json`.**

Of the 17 in `Effected Sites 8-20`, sixteen resolve. One does not:
`live-gm-root.pantheonsite.io`: the Pantheon platform hostname for `gm-root`,
which is in the inventory as `gmroot.com`. A naming variant, not a missing site.

**`Effected Sites 8-20` (17)**
kraftnaturalcheese.com, breakstones.com, crackerbarrelcheese.com,
actioncarting.com, ciminelliflorida.com, ciminelli.com, newmarkciminelli.com,
live-gm-root.pantheonsite.io, icegame.com, knudsen.com, interstatewaste.com,
lancastervillageny.gov, pfannenbergusa.com, runtalnorthamerica.com,
sgroilawley.com, zehnder-rittling.com, elmanyhistory.org

**`Pods sites` (32, all at 3.3.9.1)**
11daypowerplay, actioncarting, breakstones, ccida, ciminelli, ciminelli-florida,
ciminelli-newmark, clevermethod, clevermethod-forward, cm-whitelabel,
crackerbarrelcheese, eastauroracc, elmanyhistory.org, frontline-construction,
gm-root, icegame, interstatewaste, knudsen, kraftcheese, l92, lancastervillage,
lasershows, ontracksitedevelopment, palmetto-residential-electric,
pfannenbergsales, pfannenbergusa, pietrantone-health, runtalnorthamerica,
seneca-financial-advisors, zehnder-america-zna, zehnder-rittling, life-breath

---

## What this suite would and would not have caught

Stated plainly, because it is the honest answer to "what is this for" and it is
worth saying out loud rather than being asked.

**Would have caught, and did:** version drift. The fleet health scan reads the
installed WordPress version on 48 Pantheon sites and scores anything below the
wp2shell floor as CRIT. It found `cm-whitelabel` at 6.9.4.

**Could NOT have answered "which of our sites run Pods", and still cannot.**
An earlier draft of this file said it would have answered that "in seconds".
That was wrong twice over and is corrected here rather than quietly deleted:

- The ledger holds two plugin fields per site, `plugin_updates` and
  `theme_updates`, and both are integers. No slug, no name, no version. Nothing
  in this suite knows the word "Pods".
- The command it runs would not answer it either.
  `pantheon-fleet-healthcheck.sh` calls `wp plugin list --update=available`,
  which returns only plugins with an update PENDING. A site sitting on Pods
  3.3.9 with nothing newer released would not appear. The question needs
  `wp plugin list` without that flag: a different call, which is what step 0
  of `docs/VULN-INTEL-REVIEW.md` describes and which is not built.

**What step 0 would actually buy, measured 2026-08-23 against
`health-2026-08-23_1321`:** 29 of the 32 sites the workbook listed for this
incident. The three it would miss are `clevermethod-forward` and
`pfannenbergsales` (SKIP, no live environment to scan) and `elmanyhistory.org`
(not on Pantheon). Fleet-wide the ceiling is **48 of 84**: the 21 Nexcess and
10 outlier-host sites have no deep scan at all, so their component inventory
stays manual until those transports exist.

That is still worth building. It is not the same claim as "in seconds", and the
difference is exactly the kind of overstatement this file exists to avoid.

**Would NOT have caught:** the incident itself. Nothing in this suite observes
admin users, so three sites having users added is invisible to it. It is
read-only by design and does not log in.

---

## Deferred: capturing security events in the suite

**THE MEETING HAPPENED, 2026-08-24, and question 4 was answered by Doug in the
room.** This block was written the day before, saying to wait for it. Waiting
was right, and the requirement that came back is narrower and more specific
than anything that would have been designed on 2026-08-23.

Doug, in the regroup: *"if there ever is a security incident where the client
gets involved and they're angry, we have to have some legal posture. And six
months after it happens we're like, oh, all I have is this 13 character note."*
And the shape he asked for: *"what happened, when it happened, what we did."*

So the answer to question 4 is **yes, and that is the primary purpose.** He
described it as a cover-our-backs document first and a client deliverable
second: *"we give him a file... here's your incident report... it becomes a
value add."*

Question 2 is partly answered. Victoria already keeps a **security event log
tab** in the master workbook, so a capture mechanism exists and has an owner.
Brian's proposal was looser: *"maybe we just put a file up in here."* Nobody
settled where the durable copy lives.

**What this changes about the design.** A record written for a legal posture
six months later is a different artifact from a dashboard row. It needs dates,
what was observed, what was done, by whom, and what was ruled out. The Pods
incident is a live demonstration of why: the root cause was never established,
a database comparison **timed out and never completed**, and the rogue accounts
may have been remnants of an earlier incident. A schema with a
`root_cause` field would have forced a guess into a record meant to survive
scrutiny. **Whatever gets built needs a first-class "not established".**

Still deliberately not built. Three incidents is still not a schema, and the
next thing to do is ask Victoria what her tab already holds rather than design
a second one beside it.

The remaining unsettled parts of the original block:

The dashboard is read-only, `CLAUDE.md`, first hard boundary, so it can
display an incident record but cannot collect one. Collection is an edit to a
file in this repo, or it is somewhere else entirely. That is a product decision.

**Questions to settle before any of it is built:**

1. When an incident is open, does an affected site's status change on the
   dashboard, or is the incident shown beside an unchanged status? This decides
   whether it is a severity axis or a display layer.
2. Who writes the entry, and at what point in triage? That decides whether a
   pull request is a workable capture mechanism.
3. Is "affected sites" a judgement someone records, or the output of a scan?
   The Pods sheets are both, and they disagree.
4. ~~Is this record ever shown to a client or an insurer?~~ **ANSWERED
   2026-08-24: yes, and it is the point.** Legal posture first, client
   deliverable second.
5. What was meant to be on the outstanding-issues tab?

6. **NEW.** Where does the durable copy live? Victoria's workbook tab, this
   repo, or somewhere else? Brian said *"maybe we just put a file up in here"*
   and nobody landed it. Two copies is the failure this repo has already made
   twice, so pick one and point the other at it.
