# WordPress vulnerability intelligence: review and feasibility

**Written 2026-08-20.** Inputs: `wordpressvulnerabilityintelligencefleethealthv2.md`
(the research doc), the Pods advisory and its CVE record, Wordfence's V3 API
change notices, Patchstack pricing, the Matt/Doug Teams thread from this
afternoon, and the cm-automation scanner, ledger and CLAUDE.md as they are
tonight. Nothing was built.

**Caveat on sources.** wordfence.com pages did not render for my fetch tool
(blank body), so the advisory facts below come from NVD, OpenCVE and
Patchstack, and the V3 API facts from two third-party write-ups of Wordfence's
2026-02-02 notice plus the V2 schema I already know. Two items are marked
*verify* where the live V3 response is the only authority.

---

## 1. The incident

| | |
|---|---|
| Plugin | Pods – Custom Content Types and Fields (slug `pods`), ~100k installs |
| CVE | CVE-2026-19598, CWE-863, CVSS 3.1 **9.8** (AV:N/AC:L/PR:N/UI:N) |
| Flaw | `pods_admin` AJAX router routes every access check through `pods_error()`, which on one code path only logs and returns false. Every guard is bypassed; an unauthenticated visitor can reach admin methods (reset passwords, create admins). |
| Affected | 2.8–2.8.23.3, 2.9–2.9.19.3, 3.0–3.0.10.3, 3.1–3.1.4.1, 3.2–3.2.8.2, 3.3–3.3.9 (**six branches**) |
| Fixed | 3.3.9.1, 3.2.8.3, 3.1.4.2, 3.0.10.4, 2.9.19.4, 2.8.23.4 |
| Disclosed | 2026-08-15 (Wordfence is the CNA); patches ~36 hours later |
| Exploited | Patchstack marks it "Known to be exploited". **Not in CISA KEV** as of today. |

Matt, 19:36 ET: *"PODS. need a better way to monitor the WordPress CVEs"*, then
*"so then we'd know the total catalog of plugins we're using and if any hit
against here."* Which site was hit and how it was found is not in the thread.
That is question 1 below.

Two things about this incident shape the design:

- **There was a ~36 hour window with no patch.** During it, the only useful
  output is "these N sites run Pods, here are the versions, here is the
  workaround." Update-availability monitoring cannot see that window at all.
- **Six patched branches.** Any version matcher has to handle multiple
  disjoint affected ranges per record. The Pods record is the test fixture.
- **KEV lags.** Patchstack flagged exploitation; CISA has not listed it five
  days on. KEV cannot be the only exploitation signal.

---

## 2. What we have today

**The scanner runs the right command and throws the answer away.**
`pantheon-fleet-healthcheck.sh` line 309 runs
`wp plugin list --update=available --format=json`, then stores
`jq 'length'`. The ledger holds `plugin_updates` (a count) and
`theme_updates` (a count). No slug, no name, no version, no status. Line 1 of
CLAUDE.md's bug table is `plugin_updates: 0` standing in for "nobody looked".

So the doc's Phase 1, *"confirm inventory quality"*, understates it. **There
is no component inventory to confirm.** Nothing in the repo can answer "which
of our sites run Pods?" tonight, and that is the question Matt asked.

What exists that a vulnerability engine can use:

| asset | state |
|---|---|
| `wp_version` per site | measured, 48 of 52 Pantheon sites |
| PHP version | measured (Pantheon), claimed (Nexcess) |
| `production` flag | in the inventory, load-bearing |
| `attestations` per site | in the inventory, with source and date |
| append-only ledger, per-source fact families, collision guard | built |
| severity module, one scorer, per-axis | built; CRIT means security tier |
| CI on GitHub Actions with secrets, scheduled workflows | built |
| Pantheon deep scan (SSH + WP-CLI) | live, 48 sites |
| Nexcess deep scan | not built; blocked on the SSH-key question |

Coverage is the hard limit: a component inventory built on the existing
deep scan reaches **48 of 84 sites**. The 21 Nexcess sites and the 10 sites on
Azure, Pressable, Flywheel and WP Engine stay dark until their SSH paths exist. The page has to say so per site,
or "no vulnerable component" reads as clean on a site nobody inventoried.

---

## 3. The doc: agree, disagree, adjust

### Agree

- **Intersection, not a news feed** (§1, §29). Correct framing. Matt said the
  same thing in his own words.
- **Lives in Fleet Health, not a fourth module** (§2). In this repo's terms:
  a new fact family in the ledger, new codes in `severity.py`, scored on the
  **health** axis. CRIT is already defined as "act now, security tier", which
  is exactly what an exploited unauthenticated privesc is. No new axis.
- **Do not scrape the Wordfence site; use the feed** (§4). Yes.
- **`vulnerability_id` primary, `cve_id` nullable** (§6). Pods had a CVE at
  disclosure, many do not.
- **KEV as escalation only** (§7). Correct, and the Pods case shows it lags.
- **One feed first** (§8). Yes. Reconciling two feeds is a project in itself.
- **Inventory reuse; do not SSH the fleet on every feed event** (§10, §11).
  Matches how the ledger already works.
- **Match on slug + type + version, never display name** (§12).
- **Read-only; remediation is a separate, later, human-gated decision**
  (§23). This is CLAUDE.md's first hard boundary.
- **Licensing is a requirement, not an afterthought** (§25).

### Disagree or adjust

1. **Phase 1 is the whole first build, and it is small.** The doc treats
   inventory as something to verify. It has to be created: keep the full
   `wp plugin list --format=json` and `wp theme list --format=json` output
   (drop `--update=available`) and write one row per site per component. The
   command already runs inside the existing SSH session; the cost is storage
   shape, not a new scan. Add mu-plugins (`wp plugin list --status=must-use`)
   since `plugin list` omits them by default.

2. **The P1–P4 priority model is a second scoring model.** CLAUDE.md: *"never
   a second scoring model."* Map it onto what exists:
   `component_known_vulnerable` at **CRIT** when unauthenticated, or KEV, or
   RCE/privesc/auth-bypass/file-upload by CWE, or CVSS ≥ 9; **WARN** otherwise;
   a second code `component_vulnerable_no_patch` so "no fix exists yet" is
   visible as its own line. Use the existing `production` flag where the doc
   says "environment". Fleet prevalence ("12 sites run it") is a rendered
   aggregate, not a severity input.

3. **The finding lifecycle (§19) is a workflow state machine; the ledger is
   append-only observations.** `new → confirmed → patched → verified → closed`
   falls out of re-measurement: the next inventory run shows the new version,
   the rule stops firing, the diff records the change. Don't build states.
   `accepted_risk` and `false_positive` are attestations on the inventory
   record (that structure exists, with `by`, `at`, `source`), not ledger rows.

4. **Webhooks (§5, §27) mean a public write endpoint.** The only public
   surface is the `cm-fleet` Worker, which was made read-only with no secrets
   on 2026-08-19 after an audit found drift. A webhook receiver reverses that
   decision. Scheduled polling from GitHub Actions needs no new surface.
   Defer webhooks indefinitely; the polling cadence below is enough.

5. **The rate limit is now known: 1 request per 30 minutes by default**, feed
   size ~120 MB, V2 dead since March 2026, key required, **free** with a
   Wordfence account (per two independent write-ups of the 2026-02-02
   notice). Hourly polling (§11.2) is legal but pointless at that size; the
   disclosure-to-patch window was 36 hours for Pods. Every 6 hours is plenty.
   Do not commit the feed; cache it in the runner and commit only the
   filtered records that touch slugs in our catalog.

6. **Version comparison (§13).** WordPress plugin versions are not semver;
   `3.3.9.1` and `2.9.19.4` are normal. The repo's contract is stdlib Python,
   so no `packaging`. Write a small comparator that mirrors PHP
   `version_compare`, and test it against the six Pods ranges before anything
   else. The feed represents ranges as `{from_version, from_inclusive,
   to_version, to_inclusive}` with `*` for unbounded (*verify against V3*).

7. **The dashboard headline (§17, "74 / 78 Healthy") is the single-status
   page we removed yesterday.** Scoring is per axis now. This is a section
   under the Health card plus the existing site table, not a new headline.

8. **Client-facing exposure (§27) is out of scope.** The page is internal,
   behind Cloudflare Access, read-only. Attribution still has to be right for
   internal use (Wordfence requires its copyright notice to be carried with
   the data; the feed includes a `copyrights` block per record).

9. **§22 on Nexcess is behind the repo.** The challenge finding is already in
   `fleet_nexcess.md` with the exhausted-tests table. Nothing to add, except
   that the inventory coverage gap (21 sites) is exactly this blocker.

10. **Missing from the doc: the catalog is a deliverable on its own.** Before
    any feed, "which plugins does the fleet run, on how many sites, at what
    versions" answers Matt's question and is the audit workbook's missing
    column. Ship that first; it is also how you check the feed integration by
    eye.

11. **Missing: WordPress core.** `wp_version` is already a fact. The same
    matcher covers core vulnerabilities for free.

12. **Missing: the 36-hour window needs a "no patch yet" state**, and a place
    to record the vendor workaround. That is the one moment this tool earns
    its keep, and the doc's model (§14, `patched: true`) only has the
    after-patch case as an example.

---

## 4. Feed choice

| | Wordfence Intelligence V3 | Patchstack Threat Intel API | WPScan API | CISA KEV |
|---|---|---|---|---|
| Cost | Free with account key | Separate product; Developer plan is $69/mo and the API is not listed as included | Free tier is small; paid above | Free, no key |
| Coverage | Largest WordPress-specific DB; Wordfence is a CNA | Comparable; Patchstack is also a CNA and often first to flag exploitation | Smaller | Cross-ecosystem, lags |
| Machine format | JSON feed, affected ranges per slug | JSON API | JSON API | JSON |
| Rate limit | 1 / 30 min default | plan-dependent | plan-dependent | none practical |
| Exploitation signal | in record text/priority | explicit "known exploited" flag | partial | the catalog itself |

Start with Wordfence V3 (free, complete, machine-matchable) plus KEV (free,
one file). Revisit Patchstack only if we want its exploitation flag as a
second signal after the first cycle.

**Human task now:** create the Wordfence account and API key on a
clevermethod-owned login, not Doug's personal one. The Cloudflare token audit
this week found all three API tokens on Doug's personal account; don't add a
fourth.

---

## 5. Feasibility plan

Sized against the repo as it stands. Steps 0–2 need no feed and no new
credential.

| step | what | depends on | size |
|---|---|---|---|
| ~~**0**~~ | ~~Scanner keeps full plugin/theme/mu-plugin JSON per site. New ledger file `history/components.jsonl`...~~ **DONE 2026-08-23.** Built as specified, with one addition: `components_checked` is carried on the observation row and registered in `COVERAGE_FLAGS`/`COVERAGE_DIRECTION`, so a site nobody could inventory is distinguishable from one running nothing, and the first run does not report ~46 rows of fleet news. **No real scan has run yet, so `history/components.jsonl` does not exist and every count below is still 0.** | the existing deep scan | done |
| **1** | Dashboard: "Components" section under Health. Fleet catalog (distinct slugs, site count, version spread), per-site list, search. Per-site line "components not inventoried" where coverage is missing. | 0 | ~half a day |
| **2** | `wp_version` + catalog answer "who runs X at version Y" via a CLI query. This is the Pods question, answerable from the ledger. | 0 | hours |
| **3** | Wordfence V3 fetch in a scheduled workflow (every 6h), key in GitHub secrets. Filter to slugs in the catalog + core, commit only those records as source `vuln-intel`. KEV fetch in the same job. | key, 0 | ~1 day |
| **4** | Matcher + `version_compare` comparator + severity codes (`component_known_vulnerable` CRIT/WARN, `component_vulnerable_no_patch`). Tests: the six Pods ranges, an unbounded range, a non-numeric version, a slug not in the feed. Render and look. | 3 | ~1 day |
| **5** | Asana routing, first real case: a new CRIT component finding on a production site opens a task. This is the shared plumbing already on the list. | 4 | the existing Asana item |
| **6** | Nexcess SSH inventory, when the key question is answered. Same rows, different transport. Coverage 48 → 69. | Nexcess | separate phase |
| — | Webhooks | never, unless polling proves too slow | — |

Effort totals roughly three days of build to step 4, on top of the
already-queued publish, coverage guard and token work.

---

## 6. Questions before building

1. **Which site, which version, how was it found** (Wordfence alert? client
   report? host notice?). The answer tells us whether step 2 alone would have
   caught it.
2. **Are any Pantheon sites composer-managed?** `wp plugin list` still sees
   those plugins, but the fix path differs (composer.json, not a dashboard
   update), and that matters for the remediation note.
3. **Auto-update policy.** Do any sites have plugin auto-updates on? If so
   the inventory will show version drift between scans that is not a person
   acting, and the diff should say so.
4. **Who owns the Wordfence account** (question for Matt).
5. **Is Patchstack already in use anywhere** (Doug pasted its pricing page;
   if a plan exists, its API may be the better first feed).
6. **Do inactive plugins count as exposed?** Many WordPress vulnerabilities
   need the plugin active; some (file-based) do not. Proposal: inactive =
   WARN, never CRIT, and the row says "inactive".
