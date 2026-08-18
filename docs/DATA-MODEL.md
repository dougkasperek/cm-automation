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

## The three layers

```
  data/fleet-inventory.json      authoritative, human-owned, edited in a PR
            |
            v
  history/observations.jsonl     append-only facts, every tool, keyed on site_id
            |
            v
  the dashboard                  one view, one site list, one history
```

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
