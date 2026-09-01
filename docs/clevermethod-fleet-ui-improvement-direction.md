# clevermethod fleet UI Improvement Direction

## Objective

Improve the Fleet dashboard so it is easier to scan, understand, and act on quickly without removing the underlying operational detail.

The primary design principle should be:

> **Overview tells me where to look. Sites lets me work the problem. Site detail tells me why. Components tells me whether the issue is isolated or fleet-wide.**

The current system already captures useful data. The biggest UI opportunity is not adding more visualization. It is improving **information hierarchy, progressive disclosure, exception-first presentation, and consistent drill-down behavior**.

## 1. Simplify the Primary Information Architecture

Use only navigation that is supported by the current product.

Recommended primary areas:

- **Overview**
- **Sites**
- **Components**

A secondary **Run / Coverage** utility can exist if needed for scan timestamps, source coverage, methodology, and system limitations.

Do not add speculative primary sections such as Reports or Settings unless the product later requires them.

Concepts such as:

- Needs a Decision
- Changed
- Reconciliation
- Fleet Health
- Cookie Consent
- Email DNS

should generally remain **views, filters, or drill-downs within Overview and Sites**, rather than becoming separate top-level navigation items.

## 2. Redesign Overview as an Action Center

The first screen should answer three questions within a few seconds:

1. **Is anything wrong?**
2. **What changed?**
3. **What requires a human decision?**

The top of the page should emphasize exception-oriented portfolio metrics rather than raw system totals.

Suggested structure:

| Metric | Purpose |
|---|---|
| Needs Attention | Sites with active issues |
| Needs Decisions | Sites requiring human input |
| Changed Since Last Run | Meaningful changes since the previous sweep |
| Healthy | Sites with no current issues detected |

Each metric should be clickable.

Example drill-down:

**Needs Attention → issue category → affected sites → site detail/evidence**

Avoid combining unlike concepts into one number such as:

> 36 changing / needing a decision

Changes and decisions are operationally different and should remain separate.

## 3. Keep the Suite Cards, but Make Them Summary-First

The existing Fleet Health, Cookie Consent, and Email DNS sections are useful concepts, but the cards should carry less explanatory prose.

Each card should primarily show:

- high-level state counts
- 2–4 important exceptions
- a clear drill-down action

Example:

### Fleet Health

- **2 Critical**
- **51 Warning**
- **27 Healthy**

Key exceptions:

- 11 sites have no current health evidence
- 2 sites missing recent backups
- 32 sites behind on WordPress

`View details →`

Methodology, thresholds, and explanations should move behind an:

`ⓘ How this is calculated`

or into Run / Coverage details.

## 4. Move System Documentation Out of the Main Scan Path

Sections such as:

- What this page knows, and what it does not
- source coverage explanations
- scan timestamps
- methodology
- thresholds
- system limitations

are valuable, but they should not dominate the main operational dashboard.

Move them into one of these:

- compact **Run details** panel
- expandable coverage section
- secondary **Run / Coverage** view
- contextual `ⓘ` help

The main dashboard should prioritize exceptions and decisions.

## 5. Make Sites the Canonical Working View

Several current sections are really different filtered views of the same underlying entity: **site**.

Examples:

- Needs a Decision
- What Changed
- Still Open
- Sites That Do Not Reconcile
- Every Site

Instead of presenting these as independent long reports, use a canonical Sites interface with saved views or tabs.

Suggested tabs:

- **All Sites**
- **Attention**
- **Changed**
- **Decisions**
- **Reconcile**

Example:

| Site | Health | Consent | DNS | WP Version | Changes | Last Check |
|---|---|---|---|---|---:|---|
| example.com | Warning | Passing | OK | 7.1 | 3 | Aug 25 |

Clicking a site should open a detail view or side panel.

## 6. Create a Consistent Site Detail Pattern

A site should have one canonical detail view.

Suggested structure:

### Site Summary

- overall state
- health
- consent
- DNS
- hosting
- production status
- ownership
- last scan

### Detail Tabs

- Overview
- Health
- Consent
- DNS
- Components
- Inventory
- History / Evidence

This eliminates repeated site-level information across multiple sections.

## 7. Group Changes by Site

The current change feed can generate multiple rows for one site because individual facts change independently.

Instead of:

- status changed
- wp_core_update changed
- wp_version changed
- plugin count changed

group those changes into one site-level event.

Example:

### example.com: 3 changes

- WordPress 7.0.4 → 7.1
- Core update available → up to date
- Health Warning → OK

The row can expand if the user wants raw event history.

Also distinguish change direction:

- **Improved**
- **Regressed**
- **Informational**

Example top-level summary:

> **36 changes across 12 sites**  
> 19 improved · 4 regressed · 13 informational

This is more useful than a raw change count.

## 8. Redesign the State Legend

Do not place all labels into one universal “state” system.

`Critical`, `Warning`, and `Healthy` describe **health severity**.

`Unknown` describes **evidence or coverage**.

`Skip` describes **monitoring policy**.

`Frozen` describes **workflow/system behavior**.

These should be separated conceptually.

### Health

| State | Meaning |
|---|---|
| Critical | Action required |
| Warning | Review recommended |
| Healthy | No issue detected |

### Coverage / Monitoring

| State | Meaning |
|---|---|
| Unknown | Insufficient evidence |
| Not Monitored | Intentionally excluded |
| Paused | Monitoring/state intentionally frozen |

Do not rely on color alone. Use:

- icon
- label
- color

Example:

- `● Critical`
- `▲ Warning`
- `✓ Healthy`
- `? Unknown`
- `– Not Monitored`

The large permanent “What the states mean” section can become a compact **Status legend ⓘ** popover.

## 9. Make Exception Counts More Important Than Coverage Math

Coverage bars currently often require the user to mentally calculate what is missing.

Instead of:

> 68 of 74 checked

prefer:

> **68 checked · 6 not checked**

The exception is what matters operationally.

Apply this pattern consistently across:

- Pantheon
- Nexcess
- WordPress
- consent testing
- DNS checks
- inventory coverage

## 10. Consolidate Scan Timestamps

Avoid several large timestamp cards for different systems.

Use one compact sweep summary:

> **Last sweep:** Aug 25, 6:10 PM  
> 4 of 5 sources current · 1 older source  
> `View run details`

Detailed timestamps can live in Run / Coverage.

## 11. Turn Needs a Decision Into an Actionable Queue

Decision items should feel like work items, not just another report.

Each row should identify the required action.

Examples:

- `Set production status`
- `Assign owner`
- `Exclude from monitoring`
- `Confirm host`
- `Investigate discrepancy`

This makes the section operational instead of informational.

## 12. Demote Reconciliation to a Filtered Exception View

“Sites That Do Not Reconcile” should not require a permanent full-page section.

Represent it as:

> **Inventory mismatch · 7**

inside Sites.

Clicking it filters the Sites table to affected records.

## 13. Add Persistent Search and Filters

Use a sticky or consistently placed filter bar.

Suggested controls:

- Search sites
- Client
- Host
- Status
- Monitoring state
- Issues only

Filters should persist as the user moves through the operational views where practical.

## 14. Components Page: Preserve It as a Dedicated Drill-Down

The existing Components page is useful and should remain separate rather than being forced into the main Fleet dashboard.

It serves two valid modes.

### Fleet Components

Entered from the Components navigation or fleet-level coverage link.

Question answered:

> What is installed across the estate?

### Site Components

Entered by clicking the plugin/component count in a site row.

Question answered:

> What is installed on this site?

The same underlying interface can support both modes.

## 15. Make Component Context Obvious

When entering from a site row, show the selected site as the dominant context.

Example:

### 1-800-dumpster.com Components

**37 components · 19 updates pending · 6 multiple-version components**

Tabs:

- All Components
- Updates Pending
- Plugins
- Themes
- MU Plugins

When no site is selected, the page should clearly be the fleet-wide Components view.

## 16. Convert Component Summary Cards Into Filters

Current component statistics should become interactive.

Suggested cards:

- **362 All Components**
- **649 Updates Pending**
- **175 Shared Components**
- **109 Multiple Versions**

Clicking a card filters the table.

This applies the same system-wide interaction pattern:

> **Summary number → click → supporting records**

## 17. Improve Component Terminology

Prefer plain operational labels.

Recommended changes:

- **Version Spread** → **Multiple Versions**
- **On More Than One Site** → **Shared Components**
- **Pending** → **Sites Needing Update** when the number represents affected sites

Avoid bare numbers when the unit is ambiguous.

## 18. Component Row Nesting

A component row should summarize the fleet impact.

Example:

> **Divi**  
> Theme · 66 sites · 16 versions · 4 sites needing update

Click to expand:

### Version Distribution

| Version | Sites | State |
|---|---:|---|
| 4.27.6 | 43 | Current |
| 4.27.5 | 12 | Update available |
| 4.26.x | 8 | Update available |
| Other | 3 | Investigate |

Then allow the user to expand a version to see the affected sites.

This creates useful cross-navigation:

> **Site → Component → affected sites → Site**

## 19. Prepare the Components Page for Future CVE Intelligence

Do not add unsupported vulnerability data today, but design the page so CVE information can be added naturally later.

Future example:

| Component | Sites | Versions | Updates | Security |
|---|---:|---:|---:|---|
| example-plugin | 44 | 3 | 12 | 1 vulnerability |

Expanded view:

> CVE affects versions below 4.2.7  
> **7 of 44 sites are affected**

`Show affected sites`

On Overview, vulnerability information should only surface as a portfolio exception:

> **3 component vulnerabilities affect 11 sites**

Clicking it should open Components already filtered to vulnerable items.

## 20. Use Consistent Count Vocabulary

Fleet contains several different units:

- sites
- domains
- components
- component installations
- updates
- changes
- trackers
- DNS records
- decisions

Every prominent number should state what it counts.

Prefer:

- **2 Critical sites**
- **8 Warnings**
- **5 Decisions**
- **12 Sites Changed**
- **19 Updates Pending**
- **7 Sites Not Inventoried**
- **109 Multiple-Version Components**

Avoid ambiguous bare counts.

## Recommended Interaction Model

The product should consistently follow this hierarchy:

### Portfolio

Shows exceptions and priorities.

### Filtered List

Shows the affected sites or components.

### Entity Detail

Shows site or component context.

### Evidence

Shows exactly why the system reached the state.

In shorthand:

> **Summary → Filter → Detail → Evidence**

This should become the primary interaction pattern across Fleet.

## Recommended Final Structure

### Overview

- Needs Attention
- Needs Decisions
- Changed Since Last Run
- Healthy
- Fleet Health summary
- Cookie Consent summary
- Email & DNS summary
- Coverage summary
- Top Issues
- Recent Meaningful Changes

### Sites

Tabs:

- All
- Attention
- Changed
- Decisions
- Reconcile

Canonical site table with drill-down to Site Detail.

### Site Detail

- Overview
- Health
- Consent
- DNS
- Components
- Inventory
- History / Evidence

### Components

Fleet-wide or site-scoped component inventory.

Filters:

- All Components
- Updates Pending
- Shared
- Multiple Versions
- eventually Vulnerabilities

### Run / Coverage

Secondary utility view containing:

- last scan times
- source coverage
- inventory coverage
- methodology
- thresholds
- monitoring limitations
- source/API status

## Core Design Principles

1. **Exception first**
2. **Progressive disclosure**
3. **One canonical view per entity**
4. **Summary numbers should be clickable**
5. **Keep health, evidence, and monitoring states conceptually separate**
6. **Always label what a number counts**
7. **Group related changes instead of exposing raw event noise**
8. **Keep methodology available but outside the main scan path**
9. **Avoid adding navigation until the product actually needs it**
10. **Do not add charts merely for visual interest; optimize for operational scanning and action**
