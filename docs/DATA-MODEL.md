# The unified data model

Built 2026-08-18. This is the layer the dashboard reads. Everything else feeds
it.

## The problem it solves

Three tools, three different ideas of what identifies a site, and nothing
mapping them:

| tool | keys on | example |
|---|---|---|
| `pantheon-fleet-healthcheck.sh` | Pantheon machine name | `kraftcheese` |
| the manual workbook | domain | `kraftnaturalcheese.com` |
| `fleet-email-dns.py` | sending domain | `app.galbani.com` |

A person supplied that mapping from memory, every time. It is not derivable:
`local92afm.com` is `l92`, `packagedesignsupply.com` is `pdsci`,
`drspietrantone.com` is `pietrantone-health`. Thirteen of them have no rule at
all.

## The layers

```
  data/fleet-inventory.json      authoritative, human-owned, edited in a PR
            |
            v
  history/observations.jsonl     append-only facts, every tool, keyed on site_id
  history/components.jsonl       append-only inventory OF each site, one row
            |                    per component, same run_id as the facts above
            v
  the dashboard                  one view, one site list, one history
```

**`components.jsonl` is the fourth file and it is not a fourth source.** It is
written by the same `health` run, under the same `run_id`, and holds a LIST
where the observation ledger holds SCALARS. The split is deliberate: the
observation ledger diffs facts between runs, and a 40-element plugin list per
site would either be diffed element-wise -- turning every routine version bump
into fleet news -- or stored as a blob nothing could query. See section 2b.

### 1. Inventory, `data/fleet-inventory.json`

84 sites. **The key is the domain**, because it is the only identifier that
exists for all 78 workbook sites across all 6 hosts. The Pantheon machine name
becomes an attribute (`host_site_name`), not an identity.

It is **human-owned**. Nothing regenerates it from a scan, because a scan cannot
know whether a site is a client or scratch. `scripts/build-fleet-inventory.py`
seeds it once from the workbook; after that it is edited by hand.

It holds three things a scan cannot produce:

- **Identity**: client, owner, production yes/no. All empty on import,
  deliberately. Guessing these is how "hoffmanscheese looks client-named" ended
  up repeated across three documents.
- **Attestations**: the workbook columns that record a person confirming
  something, carried over with `source: workbook import` and empty `by`/`at`
  fields, so it is obvious which have never been re-confirmed by a human here.
- **Reconciliation**: the 6 sites Pantheon returns that the workbook never had,
  and the 1 the workbook has that Pantheon does not return. Keeping both **in**
  the inventory makes the discrepancy a standing check instead of something a
  person has to notice again.

### 2. Ledger, `history/observations.jsonl`

Append-only, one line per site per run per source. Every row is normalised onto
`site_id` before storage, so **one site has one history no matter which tool
observed it**:

```
# galbanicheese.com
## source: health
| 2026-08-16 17:25 | WARN | Performance Large | 8.2 | backup 0d | upstream 1 |
## source: email-dns
| 2026-08-17 15:45 | SPF True | DKIM pic | DMARC@sending False | aligned False |
```

Three rules the code enforces rather than trusts:

1. **Fact names must not collide across sources.** Asserted at import. A silent
   collision would merge unrelated measurements onto one timeline and the diff
   would report changes that never happened.
2. **Diffs compare like with like.** The previous run means the previous run
   *from the same tool*. Without this, ingesting an email scan after a health
   scan compares a Pantheon snapshot to a DNS snapshot and reports the entire
   fleet as changed. A row whose source changed reports **one** change, on the
   fact `source`, not one per field.
3. **A row is only ever read for facts it actually has.** `standing()` splits by
   source before grouping. A row with no backup fact must not read as "backup is
   fine" or as "backup is missing".

Rows that match no inventory entry are recorded per run in
`sites_not_in_inventory` and never silently dropped. An unknown site is the
highest-signal finding there is.

### 2b. Components, `history/components.jsonl`

Added 2026-08-23. One row per site per installed component:

```
site_id, host_site_name, source, slug, type, version, status,
update_available, update_version, run_id, observed_at
```

`type` is `plugin`, `mu-plugin` or `theme`. **Match on `slug` + `type` +
`version`, never the display name** -- advisory feeds key on the directory
slug, which is what WP-CLI's `name` field actually is.

**The scanner keeps the full inventory, not the update backlog.** Until this
change it ran `plugin list --update=available` and stored only the count. That
answers "what is pending", which is the wrong question during the window that
matters: when Pods CVE-2026-19598 was disclosed on 2026-08-15 there was no
patch for about 36 hours, so an update-backlog list showed *nothing* on the
affected sites. The only useful output was "these sites run pods, at these
versions". `plugin_updates` and `theme_updates` are now derived from the full
list by selecting `update == "available"`, so they mean exactly what they
meant before and severity is unaffected.

**mu-plugins need a second call.** `wp plugin list` omits must-use plugins
unless asked. They load on every request and cannot be deactivated, so leaving
them out would put a hole in the inventory exactly where it matters. Pantheon
installs its own.

**A site that could not be inventoried produces NO ROWS**, and says so on the
observation row via `components_checked`. Zero rows and "this site runs
nothing" must never be the same state. The first cut of the scanner defaulted
each failed call to `[]`, and a site whose database is not installed came out
as `components: []` -- read as "inventoried, runs nothing". Caught by running
the mock, and `run-local-test.sh` now asserts it.

`components_checked` is health's second **coverage** flag, in both
`COVERAGE_FLAGS` and `COVERAGE_DIRECTION`. It moves `False -> True` on every
inventoried site the first time the new scanner runs; without those entries
that one event lands as ~46 rows of fleet news, which is precisely what
`wp_checked` did on the first full-mode run.

Nothing reads this file yet. The component page is the next step; see
`docs/VULN-INTEL-REVIEW.md` section 5.

### 3. The dashboard

Reads the ledger and the inventory. Not built against this yet; the renderer
still special-cases two scan schemas directly. That is the next piece.

## An honest limitation

When the *meaning* of a fact changes, the first diff afterwards reports it as a
fleet change. Real example: `woodmarkpharmacy.com` moved
`spf_present: False -> unknown` between two runs, and nothing about the domain
changed. What changed was this project's own rule about how to treat a DNS
timeout.

The `RULE_CHANGE` class already handles this for *derived* values (a status that
moved with no observed change). It cannot catch a reinterpretation of an
observed fact, because the stored value genuinely differs. The mitigation is
version-stamping the tool that produced a run, which is not built yet. Until
then: after changing measurement semantics, expect one noisy diff and read it
as such.

## Running it

```bash
./scripts/build-fleet-inventory.py \
    --email-inventory data/fleet-email-inventory.json \
    --pantheon-scan reports/fleet-health-2026-08-17_0726.json \
    --out data/fleet-inventory.json          # seed once, then edit by hand

./scripts/fleet-ledger.py ingest             # both sources, idempotent
./scripts/fleet-ledger.py timeline                     # all runs
./scripts/fleet-ledger.py timeline --site galbanicheese.com
./scripts/fleet-ledger.py diff --source email-dns
./scripts/fleet-ledger.py digest
```

`test/test-ledger.py` covers this with 69 assertions, 26 of them on the
unification specifically.

---

## Amendment, 2026-08-18: `wp_version`, and how the ledger got mis-keyed

**`wp_version` is now an observed, deep-only fact.** It is the version the site
reports for itself, read with `wp core version` over SSH. It is not
`wp_core_update`, which reports the version *available* and reads `"up-to-date"`
when there is none — a value that is identical on a fleet on 7.0.2 and a fleet
on anything else. The workbook claims 7.0.2 on all 78 sites, so without the
installed version there was nothing to compare the claim against.

Being in `DEEP_ONLY` means an api-only run stores `unknown`, never a version.

**The join key is not optional.** The first ledger was ingested before
`data/fleet-inventory.json` existed. `load_inventory` accepted the absence and
returned empty lookups, so every row fell back to whatever identifier its own
tool used: machine names from Pantheon, domains from the email check. One site,
two histories, and an 84-site fleet rendering as 130 rows. Nothing failed and
nothing warned.

The store is append-only, so this could not be corrected in place — it had to be
rebuilt from `reports/`, which worked only because those files still existed on
one laptop. Three guards now stand in front of it, listed in `docs/CI-LEDGER.md`.
