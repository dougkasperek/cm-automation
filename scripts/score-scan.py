#!/usr/bin/env python3
"""Score a scan's rows with severity.py, the ONE scorer.

WHY THIS EXISTS
---------------
`pantheon-fleet-healthcheck.sh` carried its own severity model in bash, and it
was the model severity.py replaced on 2026-08-19. On 2026-08-27 the two were
measured against the same 52 rows:

    the scanner said   33 CRIT / 15 WARN /  0 OK
    severity.py said    3 CRIT / 34 WARN / 11 OK

The scanner's rules were `core update available -> CRIT`, `plugin_updates > 0
-> WARN` and `upstream_pending > 0 -> WARN`. All three are the pre-2026-08-19
model. The last one is the rule that made OK unreachable for the entire fleet,
which is why the scanner printed zero OK on a fleet where a quarter of sites
have nothing pending.

None of this reached the dashboard -- severity is recomputed at render time and
the row's own status is deliberately ignored -- so the page was always right.
What was wrong was everything a HUMAN reads: the console summary, the markdown
report, the CSV, and the EXIT CODE. The script's own header says exit 2 is "the
signal a scheduler or CI job should alert on", so the alert contract was wired
to a model three weeks out of date. CI passes --no-fail-on-crit, which is the
only reason it never fired 33 times a day.

CLAUDE.md: "Severity is scripts/lib/severity.py, and NOWHERE ELSE. A second
scorer is two answers." This is the fix for the second scorer -- not a third
copy of the thresholds, but a call into the same module the renderer uses.

CONTRACT
--------
Reads a JSON array of scan rows on stdin. Writes the same array on stdout with
`status` and `notes` replaced by severity.py's answer. Exits 0 always -- the
CALLER decides what a CRIT is worth, because --no-fail-on-crit is its flag.

The count line goes to stderr so stdout stays parseable.
"""

import importlib.util
import json
import os
import sys
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "severity", os.path.join(_HERE, "lib", "severity.py"))
SEV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SEV)


def score_rows(rows, today=None):
    """Replace each row's status and notes with severity.py's verdict.

    The row is passed to evaluate() as-is. It carries the fact names severity
    reads -- php_version, db_backup_age_days, wp_core_update, plugin_updates,
    wp_version, wp_checked, frozen -- because the scanner and the ledger were
    built against the same vocabulary.

    `production` is deliberately NOT injected here. The scanner has no
    inventory, and severity treats a missing ruling as production, which is
    the fail-safe direction. A scan-time status is a rough local answer; the
    authoritative one is computed at render time against the inventory.
    """
    today = today or datetime.date.today()
    out = []
    for row in rows:
        r = dict(row)
        ev = SEV.evaluate(r, today)
        r["status"] = ev["status"]
        # ALL reasons, not just the health axis. The scanner's notes field is
        # read by a person looking at one report, and hiding a consent or
        # email finding because it is on another axis would make the report
        # disagree with the dashboard about the same site.
        reasons = ev.get("all_reasons") or ev.get("reasons") or []
        parts = [x["text"] for x in reasons if x.get("text")]
        # Informational lines when there is no finding. A row that scores OK
        # still has things worth printing -- a PHP deadline, pending upstream
        # commits -- and they are exactly the facts the OLD model wrongly
        # scored as WARN. They belong in the note, not in the status.
        if not parts:
            parts = list(ev.get("info") or [])
        # NO FALLBACK TO THE INCOMING NOTE. It was written by the model this
        # script exists to replace, and keeping it "when severity has nothing
        # to say" is precisely when the two disagree: a FROZEN row carried
        # `written by the old bash model` straight through the first cut of
        # this function, because severity gives a frozen site no reasons and
        # no info. A stale verdict surviving in the one place nothing
        # overwrites is this project's recurring bug. Caught by a test.
        r["notes"] = "; ".join(parts)
        out.append(r)
    return out


def summarise(rows):
    counts = {}
    for r in rows:
        counts[r.get("status") or "UNKNOWN"] = counts.get(r.get("status") or "UNKNOWN", 0) + 1
    return counts


def main():
    try:
        rows = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as exc:
        # A scorer that cannot read its input must not emit an empty array:
        # downstream that reads as "the scan found nothing", which is this
        # project's oldest bug pointed at its own tooling.
        sys.stderr.write("score-scan: could not parse scan JSON: %s\n" % exc)
        return 1
    if not isinstance(rows, list):
        sys.stderr.write("score-scan: expected a JSON array, got %s\n"
                         % type(rows).__name__)
        return 1
    scored = score_rows(rows)
    json.dump(scored, sys.stdout)
    c = summarise(scored)
    sys.stderr.write("score-scan: %s\n" % " / ".join(
        "%d %s" % (c[k], k) for k in sorted(c)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
