#!/usr/bin/env python3
"""Which Nexcess sites can the SSH deep scan reach, and as whom?

The scan needs three things per site: an inventory `site_id` to key the ledger
row on, an SSH host, and an SSH user. None of them are guessable, and getting
any of them wrong is worse than not running.

WHERE THEY COME FROM
--------------------
The Nexcess control-plane scan, via the ledger:

    nexcess_temp_domain   -> the SSH host
    nexcess_unix_username -> the SSH user, before the suffix

`nexcess_temp_domain` really is the SSH hostname. Confirmed 2026-08-25 against
the portal's own Credentials page: it shows `ssh a8ca7a6b_1@61ae96832c.nxcli.net`
for eamusicfest.com, and the API returns `61ae96832c.nxcli.net` as that site's
temp domain. They are the same string.

THE `_1` SUFFIX
---------------
The portal shows the username as `a8ca7a6b_1` while the API returns
`a8ca7a6b`. The suffix looks like a per-site user index, which implies `_2` can
exist. **This has been verified on exactly one site.** So it is a constant here
with a name that says what it is, rather than a silent bit of string
concatenation three functions deep, and `--user-suffix` overrides it without a
code change on the first site that disagrees.

WHY NOT READ THE SCAN FILE DIRECTLY
-----------------------------------
`reports/` is gitignored and absent on a fresh clone or a CI runner, so a tool
that depends on it works on one laptop. The ledger is committed and is the
thing this repo treats as true. It also means the target list carries a
`run_id`: you can say which control-plane run a scan was aimed with.

REFUSING IS THE POINT
---------------------
A site missing a host or a user is REPORTED and SKIPPED, never guessed at. The
alternative is an ssh attempt against a hostname assembled from parts, which
either fails slowly or, much worse, succeeds against something else.

  ./scripts/nexcess-ssh-targets.py --history ./history
  ./scripts/nexcess-ssh-targets.py --history ./history --format tsv
"""

import argparse
import json
import os
import sys

UNKNOWN = "unknown"
# The portal appends this to the API's unix_username. One site confirms it.
DEFAULT_USER_SUFFIX = "_1"


def _blank(v):
    """The ledger's absence sentinel is the STRING "unknown", not None.

    A plain falsiness test let `unknown` through into a rendered cell as if it
    were a hostname once already, on the fleet page. Same trap, same fix.
    """
    return v is None or str(v).strip() == "" or str(v).strip().lower() == UNKNOWN


def latest_nexcess_rows(history_dir):
    """Rows from the most recent `nexcess` run, keyed by site_id.

    Most recent by run_id, not by file position. A debugging run landing
    between two real ones has broken a positional index in this repo before.
    """
    path = os.path.join(history_dir, "observations.jsonl")
    if not os.path.exists(path):
        raise SystemExit(
            "No ledger at %s.\n"
            "The SSH scan is aimed by the control-plane scan. Run:\n"
            "  ./scripts/fleet-nexcess.py discover ...\n"
            "  ./scripts/fleet-ledger.py ingest --reports ./reports "
            "--history ./history" % path)

    runs = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("source") != "nexcess":
                continue
            runs.setdefault(r.get("run_id"), []).append(r)
    if not runs:
        raise SystemExit(
            "The ledger holds no `nexcess` rows, so nothing knows the SSH host "
            "or user for any site.\nRun the control-plane discovery first, then "
            "ingest it.")
    run_id = max(runs)
    return run_id, {r["site_id"]: r for r in runs[run_id]}


def resolve(rows, inventory, user_suffix=DEFAULT_USER_SUFFIX):
    """(targets, skipped). Never guesses a missing part."""
    inv = {s["site_id"]: s for s in inventory["sites"]}
    targets, skipped = [], []
    for site_id, r in sorted(rows.items()):
        host = r.get("nexcess_temp_domain")
        user = r.get("nexcess_unix_username")
        why = []
        if site_id not in inv:
            why.append("no inventory row")
        if _blank(host):
            why.append("no SSH host recorded (nexcess_temp_domain)")
        if _blank(user):
            why.append("no SSH user recorded (nexcess_unix_username)")
        if why:
            skipped.append({"site_id": site_id, "why": "; ".join(why)})
            continue
        targets.append({
            "site_id": site_id,
            "host": str(host).strip(),
            "user": str(user).strip() + user_suffix,
            "domain": inv[site_id].get("domain"),
        })
    return targets, skipped


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--history", default="./history")
    p.add_argument("--inventory", default="data/fleet-inventory.json")
    p.add_argument("--user-suffix", default=DEFAULT_USER_SUFFIX,
                   help="appended to the API's unix_username. Default %s. "
                        "Verified on one site only." % DEFAULT_USER_SUFFIX)
    p.add_argument("--format", choices=("json", "tsv"), default="json")
    a = p.parse_args()

    run_id, rows = latest_nexcess_rows(a.history)
    with open(a.inventory) as fh:
        inventory = json.load(fh)
    targets, skipped = resolve(rows, inventory, a.user_suffix)

    if a.format == "tsv":
        for t in targets:
            print("%s\t%s\t%s" % (t["site_id"], t["user"], t["host"]))
    else:
        print(json.dumps({"run_id": run_id, "targets": targets,
                          "skipped": skipped}, indent=2))

    if skipped:
        print("\n%d site(s) SKIPPED, named rather than counted:" % len(skipped),
              file=sys.stderr)
        for s in skipped:
            print("  %-34s %s" % (s["site_id"], s["why"]), file=sys.stderr)
    print("%d target(s) from control-plane run %s" % (len(targets), run_id),
          file=sys.stderr)
    return 0 if targets else 1


if __name__ == "__main__":
    sys.exit(main())
