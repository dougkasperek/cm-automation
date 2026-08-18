# Fleet email authentication check

## What it is

`scripts/fleet-email-dns.py` replaces the SPF, DKIM and DMARC columns of the
manual security workbook, for **all 78 sites across all 6 hosts**, using nothing
but public DNS.

It is the first piece of fleet automation to reach CI on purpose. It needs no
host credentials, no SSH key, no API token and no platform decision, which makes
it both the cheapest thing to ship and the cleanest infrastructure canary.

```bash
pip install -r requirements.txt

./scripts/fleet-email-dns.py check \
    --inventory data/fleet-email-inventory.json \
    --out reports --stamp "$(date -u +%Y-%m-%d_%H%M)"

./scripts/fleet-email-dns.py report  --scan reports/fleet-email-dns-<stamp>.json
./scripts/fleet-email-dns.py compare --inventory data/fleet-email-inventory.json \
                                     --scan reports/fleet-email-dns-<stamp>.json
```

78 sites in about 25 seconds, roughly 950 DNS queries with about 780 served from
cache, because 60 sites share one sending domain.

---

## The rule this uses, and where it came from

The workbook holds a year of Pass and Fail judgements and the rule behind them
was never written down. Twelve rows read DMARC `Fail` while every one of those
domains has a valid DMARC record, so `Fail` plainly did not mean "missing".

Rather than invent a rule and silently disagree with that history, the script
records **facts**, defines several **candidate rules**, and `compare` scores each
candidate against the workbook. The rule that predicts the humans is the rule the
humans are using. Result:

| field | adopted rule | agreement |
|---|---|---|
| SPF | a `v=spf1` record exists on the sending domain | 66/68 (97.1%) |
| DKIM | a key is found at any probed selector, TXT or CNAME | 66/68 (97.1%) |
| DMARC | see below | 66/68 (97.1%) |

**The DMARC rule is conditional on who owns the provider**, which is why simpler
rules all scored worse:

- Provider is **CM Mailgun** (clevermethod's own account): a DMARC record must
  exist at **exactly** `_dmarc.<sending_domain>`. No organizational fallback.
- Any other provider (client controlled): the spec's organizational-domain
  fallback is accepted.

That is a coherent operational standard rather than an inconsistency. The team
holds the infrastructure it owns to a strict standard, and does not fail a client
for a setup clevermethod cannot change.

Scores for the rules that were rejected, on the same 68 rows:

```
R6_strict_for_own_mailgun_else_fallback   66/68   97.1%   <- adopted
R2_present_at_SENDING_domain              63/68   92.6%
R5_sending_org_fallback_allowed           58/68   85.3%
R4_from_domain_and_aligned                54/68   79.4%
R1_present_at_from_domain                 52/68   76.5%
R3_enforcing_at_from_domain               14/68   20.6%
```

### The two rows no DNS check can ever reproduce

`acibg.com` and `lancastervillageny.gov` are marked `Fail` on every field while
DNS looks fine. Both carry a Notes entry recording an observed SMTP failure
(`Could not authenticate`, `From header sender domain not verified`). Those are
**send-test results, not DNS facts**. They are the only two unexplained rows in
the entire comparison, which means the recovered rule accounts for 100% of the
rows where DNS is the evidence.

This is worth keeping as a permanent distinction. A functional send test answers
a question DNS cannot, and if that check matters it deserves its own column
rather than being folded into the DNS ones.

---

## What the workbook's green actually means

The adopted DMARC rule checks the **sending** domain. That answers "is the
provider setup finished", which is a real and useful question and is the one
clevermethod can act on.

It does not answer "is the brand protected from spoofing", which is governed by
DMARC on the **From-header** domain. The script records both, separately and on
purpose, and `report` surfaces the second as its own finding. On the current
fleet the two readings diverge sharply:

- 14 sites have no DMARC at all on the domain recipients actually see
- 49 sites publish `p=none` there, which instructs receivers to take no action
- 9 sites send from a domain that does not align with their From domain, so
  DMARC fails for them even when SPF and DKIM both pass

None of that is a criticism of the workbook, which was measuring something else
deliberately. It is scope that was never in scope, now visible for free.

---

## Two bugs found while building this, both worth remembering

**DKIM keys can be CNAMEs.** SendGrid publishes DKIM as CNAME records delegating
to its own zone. A TXT-only probe reports nothing on a perfectly configured site.
The first version of this script did exactly that and wrongly showed seven sites
as having no DKIM.

**DKIM selectors live on the organizational domain sometimes, not the sending
subdomain.** Same SendGrid pattern. The probe now tries both.

More fundamentally: **DNS provides no way to enumerate DKIM selectors.** A key
that is not found means the selector is unknown, never that DKIM is absent. The
script therefore reports `unknown`, never `Fail`, for DKIM. To close the eight
remaining unknowns permanently, record the real selector once per site as
`dkim_selector` in the inventory and the check verifies it forever after.

---

## A failed lookup is not an answer

Found 2026-08-18, by exactly the CI-versus-local comparison `docs/RUNBOOK.md`
insists on. GitHub reported 8 sites with no SPF record; the same code on a
laptop reported 9. The extra one was `woodmarkpharmacy.com`, whose TXT lookup
**times out** on some resolvers and answers on others.

The code was recording a timeout as `present: false`, which rendered as "No SPF
record on the sending domain." That is a fabricated negative, the same defect
already found in the Pantheon scanner's `plugin_updates: 0`, and it appeared
here in the tool written to avoid it.

Fixed three ways:

1. **A timeout is retried once** before it is believed, so a single slow
   authoritative server does not become a finding.
2. **Only `ok`, `nxdomain` and `noanswer` count as an answer.** Those mean the
   resolver reached an authoritative "there is nothing here", which is a real
   fact. A timeout, SERVFAIL or unreachable nameserver returns `unknown` with
   the failing status attached.
3. **The report separates them.** "No SPF record" and "SPF could not be
   determined" are different sections, because one is a finding about the
   domain and the other is a finding about the lookup.

The correction is large. What read as **9 sites with no SPF** is really **2**,
plus 7 where nothing was established:

| | before | after |
|---|---|---|
| No SPF record (authoritative) | 9 | **2** |
| SPF could not be determined | 0 | **7** |
| No DMARC on the From domain | 14 | 14 |
| DMARC could not be determined | 0 | **6** |

Rule agreement against the workbook is unchanged at 97.1% on all three fields,
so the correction does not disturb the recovered rule.

Six of the seven undetermined domains are in the same group
(`lactalis*`, `eamusicfest`, `hitsfoundation`), which points at one slow or
filtered nameserver rather than seven separate problems. Cause-grouping again.

**This is the argument for keeping the CI-versus-local comparison.** Neither run
was wrong about its own resolver. The disagreement was the finding, and it would
have been invisible if only one of them existed.

---

## Current findings, 78 sites

| finding | count | note |
|---|---|---|
| clevermethod Mailgun setup incomplete | 10 | infrastructure clevermethod controls and can fix |
| No SPF record on the sending domain | 2 | authoritative answer, genuinely absent |
| SPF could not be determined | 7 | lookup failed; re-run before acting |
| No DKIM key at any probed selector | 8 | unknown, not failure; record the selector |
| No DMARC on the From domain | 14 | nothing protects the brand domain |
| DMARC could not be determined | 6 | lookup failed |
| DMARC present but `p=none` on the From domain | 49 | monitoring only |
| From domain not aligned with sending domain | 9 | DMARC fails even when SPF and DKIM pass |
| DMARC inherited from the org domain | 9 | covered, by a record the site does not control |
| More than one SPF record | 0 | clean |

---

## Files

| path | role |
|---|---|
| `scripts/fleet-email-dns.py` | the check, plus `compare` and `report` |
| `scripts/extract-audit-workbook.py` | workbook to `data/fleet-email-inventory.json`, needs openpyxl |
| `data/fleet-email-inventory.json` | 78 sites, declared email config, and the workbook's recorded verdicts |
| `test/test-email-dns.py` | 45 assertions, fully offline, no DNS |
| `ci/github-actions/fleet-email-dns.yml` | the Actions wrapper (move to `.github/workflows/`) |
| `requirements.txt` | dnspython |

**Dependency note.** The rest of cm-automation is stdlib only. This script needs
dnspython, because hand-parsing DNS compression pointers and TXT chunking inside
a security tool is a bad trade. dnspython is pure Python and behaves identically
on macOS and a Linux runner, so the portability contract's intent holds.

---

## Next

- Record `dkim_selector` per site to close the eight DKIM unknowns.
- Feed these runs into the ledger (`scripts/fleet-ledger.py`) so the output
  becomes a delta rather than a snapshot. Output is already named
  `fleet-email-dns-<stamp>.json` to match the ledger's run-id pattern; the
  ledger's ingest needs to learn this file's shape.
- Decide whether a functional send test earns its own column.
