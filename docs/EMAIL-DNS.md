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

**This is the argument for keeping the CI-versus-local comparison.** Neither run
was wrong about its own resolver. The disagreement was the finding, and it would
have been invisible if only one of them existed.

### Most "undetermined" results are self-inflicted, and that is fine

Chasing the undetermined set produced a second, smaller lesson. Six of the seven
domains that timed out mid-scan resolve in **0.0 seconds** when queried one at a
time. The tool fires roughly 960 lookups through a dozen workers and saturates
the local resolver. The domains are fine; the measurement was not.

Two fixes were tried and measured, and both were rejected on the numbers:

- **Escalating the deadline in place** (three attempts, longer timeout each,
  with backoff). Tripled the wall clock to 86 seconds and recovered
  **nothing**, because the other workers are still hammering while the retry
  runs.
- **A serial repair pass after the burst.** Better in principle, and it needs
  per-zone short-circuiting plus a wall-clock budget just to be survivable,
  since a zone whose nameserver is unreachable fails all ~112 of its DKIM
  probes at full timeout each. On one run it spent 49 seconds and recovered
  **zero**.

So `--repair` exists and is **off by default**. That is a considered choice.
This tool runs on a schedule and feeds a ledger, so a transient timeout resolves
itself on the next run and belongs in a lookup-quality trend rather than in the
findings. Preferring the diff over the snapshot pays for itself here: the fix
for a flaky measurement is another measurement, not a slower one.

Which failures are transient is itself visible, because they move between runs.
`woodmarkpharmacy.com` is the one that does not. It times out consistently from
some networks and answers instantly from others, including GitHub's, while its
`_dmarc` record resolves fine either way.

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
| `.github/workflows/fleet-email-dns.yml` | the Actions wrapper |

> **Corrected 2026-08-23.** This line described `ci/github-actions/`, a
> gitignored mirror that was deleted on 2026-08-22 after the two copies
> diverged. `.github/workflows/` is the only copy. Do not recreate a
> second one — see the hard boundary in `CLAUDE.md`.

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

---

## The sending domain, and why it is on the page now

**Victoria asked "what is the sending URL" in the first outside review of the
dashboard, 2026-08-24.** It was the right question and the page could not
answer it: SPF, DKIM and DMARC are all queried at the SENDING domain, and the
page scored 78 sites on a domain it never named.

**It is a RULING, not a measurement.** It comes from the "Email Sending
Domain" column of the audit workbook, via `extract-audit-workbook.py`, and a
person records it. Nothing in DNS reveals where a WordPress site was
configured to send from, so it cannot be derived. Measured spread across the
78 rows:

| pattern | rows |
|---|---|
| `smtp.clevermethod.net`, shared Mailgun | 34 |
| `web.` / `app.` / `e.` prefixed client subdomains | ~30, prefix varies per site with no rule |
| provider-shaped one-offs: `amazonses.icegame.com`, `em1420.morrison-chs.com`, `gmail.com` | a handful |
| **blank** | **7** |

So a wrong value does not fail loudly. It queries `_dmarc.` on a host nobody
sends from and returns a confident answer about the wrong domain.

**Fixed 2026-08-24:** a `Sends from` column on the fleet table showing
`spf_checked_at`, which is the domain the check actually queried rather than a
value re-derived at render time, so the column cannot drift from what was
measured. A site with none recorded reads "not recorded" instead of blank.

**Two defects found while adding it**, both by looking at the page:

- The email card claimed email "has no column in the fleet table below". There
  were already four: SPF, DKIM, DMARC sending, DMARC from. The claim had been
  on the live page since the card was written.
- The absence sentinel is the **string** `"unknown"`, not `None`, so a plain
  falsiness test rendered `unknown` into six cells as though it were a domain.

**Worth building next:** measure it instead of trusting it. `post-smtp` is on
39 sites and stores its host and from-address in WordPress options, so a
`wp option get` on the existing deep scan could turn this ruling into a
measurement for the Pantheon fleet, starting with the 7 blanks where we
currently report UNKNOWN and could report a fact.
