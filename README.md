# cm-automation

Read-only automation for the clevermethod site fleet: 78 WordPress sites across
Pantheon, Nexcess, Azure, Pressable, Flywheel and WP Engine.

Everything here is read-only. Nothing applies an update, and execution authority
is a ladder rather than a switch. See `docs/DESIGN-REVISIT.md`.

## Start here

| doc | what it holds |
|---|---|
| `docs/DESIGN-REVISIT.md` | the current design and why; supersedes DESIGN-BRIEF section 5 |
| `docs/AUDIT-SHEET-ANALYSIS.md` | the manual workbook, what is automatable, how Nexcess fits |
| `docs/EMAIL-DNS.md` | the email check and the Pass/Fail rule recovered from the workbook |
| `docs/GIT-SETUP.md` | moving this repo into GitHub, and the one open CI decision |
| `docs/RUNBOOK.md` | the Pantheon health check: severity model, running it, failure modes |
| `docs/SECRETS.md` | secret inventory and the Keeper research |
| `docs/DASHBOARD.md` | the live local dashboard and the hosting question |

## What runs today

| script | needs | covers |
|---|---|---|
| `scripts/fleet-email-dns.py` | nothing | SPF, DKIM, DMARC for all 78 sites, any host |
| `scripts/pantheon-fleet-healthcheck.sh` | Pantheon machine token | plan, PHP, backup age, upstream drift; SSH adds WP core/plugin/theme |
| `scripts/fleet-ledger.py` | nothing | history, change detection, the delta digest |
| `scripts/serve-dashboard.py` | nothing | watches `reports/`, fills in live while a scan runs |
| `scripts/render-fleet-dashboard.py` | nothing | scan JSON to self-contained HTML |
| `scripts/extract-audit-workbook.py` | openpyxl | the manual workbook to `data/fleet-email-inventory.json` |

## Design rules

1. **Logic in scripts, CI YAML is a thin wrapper.** If changing *what gets
   checked* means editing a workflow file, the change is in the wrong place.
2. **Portable: macOS bash 3.2 and Linux bash 5.x, unchanged.** No `mapfile`, no
   `date -d`, no `timeout` binary. A `mapfile` call once stopped the health
   check completing for weeks. Python layers are stdlib only, with one
   documented exception (`dnspython`, see `docs/EMAIL-DNS.md`).
3. **Read-only until trust is earned.**
4. **Unknown is never folded into yes or no.** `SKIP` is not `ERROR`, a
   never-checked plugin count is not `0`, and a DKIM key that was not found is
   not a missing DKIM key.
5. **Known-bad markers describe a symptom, never a site name.** Flagging a
   correct row as broken teaches people to ignore the flag.
6. **State colours are validated, not brand-picked.** The deck's own severity
   green and amber fail colourblind separation at protan delta-E 3.8.
7. **Diff facts, never rendered strings.** A digest sentence that embeds a
   number will double-report every change to that number.

## Tests

```bash
python3 test/test-ledger.py        # 43 assertions
python3 test/test-email-dns.py     # 45 assertions, fully offline
./test/run-local-test.sh           # mock terminus, 19 assertions
```

The email and ledger suites both deliberately include assertions proving the
change detectors **catch** changes. A detector that reports "nothing changed" is
worthless until it is shown capable of reporting something.
