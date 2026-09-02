#!/usr/bin/env python3
"""Say something when a NEW critical vulnerability reaches a site.

WHAT IT IS FOR
--------------
Until now the page changed and nobody was told. This is the first thing in the
suite that acts rather than reports, so it is deliberately narrow.

WHAT IT DOES NOT DO. It does not tell you what is outstanding. On 2026-09-02
`ciminelli.com` was the worst site on the fleet, running Divi Form Builder
3.0.3 against two unauthenticated 9.8s, and this would have said nothing about
it, because those advisories had been known to us for days. They belong on the
page and in the backlog. An alert that repeats the backlog every run is one
nobody reads.

WHY THE TRIGGER IS THIS NARROW, measured before it was written. Across the
seven vulnerability runs to 2026-09-02:

    new findings per run:  0, 0, 143, 4, 4, 0
    of those, CVSS 9.0+ :  0, 0,   0, 0, 0, 0

The 143 was Wordfence publishing ten advisories at once. Alerting on new
findings would have sent 143 messages that evening and the channel would have
been muted by morning. There are also 165 distinct site-and-plugin pairs
needing an update right now, so anything broader than "new and critical" is a
backlog dump rather than a work queue.

That it has never fired is the point, and it is also the risk: a check that
only ever stays quiet is unfalsifiable. test/test-fleet-alert.py plants a
critical and requires it to be found.

NEW MEANS NEW TO US, not newly published. A five-year-old advisory reaching a
site we had never inventoried is news to the person who has to act on it.

FIRST RUN SAYS NOTHING. With no previous run to compare against, everything
looks new and the alert would open with the entire backlog. The same trap is
already in the bug table twice.

BOUNDARY. This writes to clevermethod's own systems and never to a client site
or a host. That line is new with this script; see docs/DO-THIS-NEXT.md B12.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CRITICAL_CVSS = 9.0


def _jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load(history_dir):
    return _jsonl(os.path.join(history_dir, "vulnerabilities.jsonl"))


def _run_ids(history_dir, rows):
    """The vulnerability runs, from the RUN RECORDS and not from the findings.

    A run that found nothing writes no findings, so deriving the run list from
    findings makes it invisible and the comparison silently reaches past it to
    an older run. Every finding would then read as new. The same distinction is
    already a rule for components: zero rows and "there is nothing here" are
    different answers.

    Falls back to the findings when runs.jsonl is missing, which is what the
    unit tests drive.
    """
    runs = [r for r in _jsonl(os.path.join(history_dir, "runs.jsonl"))
            if r.get("source") == "vuln-intel" and r.get("run_id")]
    if runs:
        return sorted({r["run_id"] for r in runs})
    return sorted({r["run_id"] for r in rows})


def _key(r):
    return (r["site_id"], (r.get("slug") or "").lower(), r.get("cve"))


def new_criticals(rows, run_ids=None):
    """Findings at CVSS 9.0+ present in the latest run and not the one before.

    Returns (findings, latest_run_id, previous_run_id). An empty list with a
    previous run means nothing new. An empty list with previous_run_id None
    means there was nothing to compare against, which is NOT the same thing and
    the caller must not report it as all clear.
    """
    runs = list(run_ids) if run_ids is not None else sorted({r["run_id"] for r in rows})
    if not runs:
        return [], None, None
    latest = runs[-1]
    if len(runs) < 2:
        return [], latest, None
    prev = runs[-2]
    before = {_key(r) for r in rows if r["run_id"] == prev}
    out = []
    for r in rows:
        if r["run_id"] != latest or _key(r) in before:
            continue
        if (r.get("cvss") or 0) >= CRITICAL_CVSS:
            out.append(r)
    return out, latest, prev


def message(findings, page_url):
    """One Teams message. Grouped by site and plugin, which is the unit of work.

    A person logs into one site and updates one plugin. Three advisories on one
    plugin is one job, not three, so they are collapsed and the highest score is
    what is shown.
    """
    by = {}
    for r in findings:
        k = (r["site_id"], r.get("slug"))
        cur = by.setdefault(k, {"worst": 0, "fix": None, "n": 0,
                                "version": r.get("version")})
        cur["n"] += 1
        if (r.get("cvss") or 0) > cur["worst"]:
            cur["worst"] = r.get("cvss") or 0
        fx = r.get("fix_version")
        if fx and (cur["fix"] is None or fx > cur["fix"]):
            cur["fix"] = fx

    n_sites = len({k[0] for k in by})
    head = ("%d new critical vulnerability%s on %d site%s"
            % (len(by), "" if len(by) == 1 else " findings",
               n_sites, "" if n_sites == 1 else "s"))
    lines = []
    for (site, slug), d in sorted(by.items()):
        fix = ("update to %s" % d["fix"]) if d["fix"] else "NO FIX AVAILABLE"
        lines.append("- **%s** runs `%s` %s, CVSS %s, %s"
                     % (site, slug, d.get("version") or "version unknown",
                        d["worst"], fix))
    body = "\n".join(lines)
    if page_url:
        body += "\n\n[Open the vulnerability page](%s)" % page_url
    return head, body


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history", default=os.path.join(HERE, "..", "history"))
    ap.add_argument("--page-url", default=os.environ.get("FLEET_PUBLIC_URL", ""))
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent and send nothing")
    a = ap.parse_args()

    rows = _load(a.history)
    findings, latest, prev = new_criticals(rows, _run_ids(a.history, rows))

    if latest is None:
        print("no vulnerability runs in the ledger; nothing to compare",
              file=sys.stderr)
        return 0
    if prev is None:
        # NOT "all clear". Everything in a first run is new to us and the alert
        # would open with the whole backlog.
        print("only one vulnerability run (%s); no baseline, staying silent"
              % latest, file=sys.stderr)
        return 0
    if not findings:
        print("no new critical findings in %s (compared against %s)"
              % (latest, prev), file=sys.stderr)
        return 0

    url = a.page_url.rstrip("/")
    head, body = message(findings, (url + "/vulnerabilities") if url else "")
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "d13438",
        "summary": head,
        "sections": [{"activityTitle": head, "text": body, "markdown": True}],
    }
    if a.dry_run:
        print("WOULD SEND:\n  %s\n%s" % (head, body), file=sys.stderr)
        return 0
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
