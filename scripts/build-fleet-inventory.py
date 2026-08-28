#!/usr/bin/env python3
"""
build-fleet-inventory.py - the one authoritative list of what a "site" is.

This is the join key the whole project has been missing. Until now:
  * the Pantheon scan keys on a machine name  ("kraftcheese")
  * the manual workbook keys on a domain      ("kraftnaturalcheese.com")
  * the email check keys on a sending domain  ("app.galbani.com")
and NOTHING mapped them, so a human supplied the mapping from memory every time.

The inventory fixes the key on the DOMAIN, because it is the only identifier
that exists for all 78 sites across all 6 hosts. Everything else becomes an
attribute, including the Pantheon machine name.

Three things this file is, deliberately:

1. **Authoritative, and human-owned.** Generated once from the workbook, then
   edited by hand and reviewed in a pull request. Nothing regenerates it from a
   scan, because a scan cannot know whether a site is a client or scratch.
2. **The reconciler.** A site the scan sees but the inventory does not is a
   finding, and so is the reverse. That is how `hoffmanscheese` (in Pantheon,
   in nobody's audit) and `hoosierfeeder.com` (in the audit, not in Pantheon)
   surfaced, and keeping both in here makes them a standing check rather than
   something a person has to notice again.
3. **The home for attestations**, which are the columns a dashboard cannot
   derive: a person confirmed a thing on a date. Carried over from the workbook
   with `source: workbook`, so it is obvious which have never been re-confirmed.

Usage:
  ./scripts/build-fleet-inventory.py \
      --email-inventory data/fleet-email-inventory.json \
      --pantheon-scan reports/fleet-health-2026-08-17_0726.json \
      --out data/fleet-inventory.json
"""
import argparse
import json
import os
import re
import sys

# Pantheon machine names that do not derive from the domain by any rule. Worked
# out by hand 2026-08-17 and verified: with these, 46 of 47 workbook Pantheon
# domains map, and the remaining 6 scanned sites are all genuinely absent from
# the workbook. Keep this list here rather than guessing at runtime; a wrong
# guess silently merges two sites' history.
MANUAL_HOST_NAMES = {
    "choosechq.com": "ccida",
    "drspietrantone.com": "pietrantone-health",
    "firstaurorafinancial.com": "firstaurora",
    "kraftnaturalcheese.com": "kraftcheese",
    "lactalisyogurtusa.com": "lactalisyogurt",
    "lancastervillageny.gov": "lancastervillage",
    "live-frontline-construction.pantheonsite.io": "frontline-construction",
    "local92afm.com": "l92",
    "midwestyogurt.com": "lactalismidwestyogurt",
    "newmarkciminelli.com": "ciminelli-newmark",
    "packagedesignsupply.com": "pdsci",
    "sgroilawley.com": "sgroifinancial",
    "zehnderamerica.com": "zehnder-america-zna",
}

# Workbook columns that record a human judgement rather than an observable fact.
# These are what the dashboard will eventually have to capture, because nothing
# can derive them from a scan.
ATTESTATION_COLUMNS = (
    "single_cm_user",
    "activity_log",
    "wp_2fa",
    "hide_login",
    "xmlrpc_disabled",
    "keeper_password",
    "wp2shell_remedied",
)

# Observable columns carried over ONLY as the workbook's last known value, for
# comparison against what the scans actually find. Never treated as truth.
OBSERVABLE_COLUMNS = ("php_version", "wp_version", "themes_utd", "plugins_utd")


def norm(domain):
    s = re.sub(r"^www\.", "", domain.lower())
    s = re.sub(r"\.(com|org|net|us|co|info|biz|dev|gov|io)$", "", s)
    return s.replace(".", "-")


def derive_host_name(domain, scanned):
    """Pantheon machine name for a domain, or None."""
    if domain in MANUAL_HOST_NAMES:
        return MANUAL_HOST_NAMES[domain]
    n = norm(domain)
    if n in scanned:
        return n
    flat = n.replace("-", "")
    for s in scanned:
        if s.replace("-", "") == flat:
            return s
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email-inventory", required=True)
    ap.add_argument("--pantheon-scan", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    # REFUSE an existing output file, before reading anything. This generator
    # seeds the inventory ONCE; the live file is human-owned and carries
    # rulings this script knows nothing about -- consent_managed on every
    # site, consent_model, nexcess_site_id (the join key ingest refuses rows
    # without), production and decommission rulings. A rerun per this file's
    # own Usage block would silently erase all of them and exit 0: the
    # newer seed-consent-rulings.py learned refuse-to-overwrite; the older
    # generator writing the same file had not. test/test-build-inventory.py
    # asserts the refusal, because a control tested only in the permitting
    # direction is the --known-hosts bug.
    if os.path.exists(a.out):
        print("REFUSED: %s already exists." % a.out, file=sys.stderr)
        print("The inventory is human-owned; regenerating it would erase every"
              " ruling recorded since the seed (consent_managed, consent_model,"
              " nexcess_site_id, production, decommission_candidate).",
              file=sys.stderr)
        print("Write to a different --out and diff by hand.", file=sys.stderr)
        return 2

    wb = json.load(open(a.email_inventory))
    scan_rows = json.load(open(a.pantheon_scan))
    scanned = {r["site"] for r in scan_rows}

    sites, used_host_names = [], set()
    for s in wb["sites"]:
        domain = s["domain"]
        host = s.get("hosted")
        host_name = None
        if host == "CM Pantheon":
            host_name = derive_host_name(domain, scanned)
            if host_name:
                used_host_names.add(host_name)

        rec = {
            "site_id": domain,
            "domain": domain,
            "host": host,
            "host_site_name": host_name,
            "dns": s.get("dns"),
            # Human fields, deliberately empty. A scan cannot know these and
            # guessing them is how "hoffmanscheese looks client-named" happened.
            "client": None,
            "owner": None,
            "production": None,
            "decommission_candidate": bool(
                s.get("notes") and "decommission" in s["notes"].lower()),
            "email": {
                "provider": s.get("provider"),
                "smtp_plugin": s.get("smtp_plugin"),
                "sending_domain": s.get("sending_domain"),
                "envelope_from": s.get("envelope_from"),
                "from_address": s.get("from_address"),
                "dkim_selector": None,      # fill in to close the DKIM unknowns
            },
            "attestations": {
                k: {"value": s["recorded_security"].get(k), "by": None,
                    "at": None, "source": "workbook import 2026-08-18"}
                for k in ATTESTATION_COLUMNS
            },
            "workbook_last_known": {k: s["recorded_security"].get(k)
                                    for k in OBSERVABLE_COLUMNS},
            "notes": s.get("notes"),
            "in_workbook": True,
        }
        if host_name is None and host == "CM Pantheon":
            rec["reconciliation"] = (
                "Listed as CM Pantheon in the workbook, but the Pantheon account "
                "does not return a matching site. Attested to but not observed.")
        sites.append(rec)

    # Sites the scan sees that the workbook does not. These are not errors to be
    # suppressed; they are the reconciliation finding, made permanent.
    by_name = {r["site"]: r for r in scan_rows}
    for name in sorted(scanned - used_host_names):
        r = by_name[name]
        sites.append({
            "site_id": name, "domain": None, "host": "CM Pantheon",
            "host_site_name": name, "dns": None,
            "client": None, "owner": None, "production": None,
            "decommission_candidate": False,
            "email": {}, "attestations": {}, "workbook_last_known": {},
            "notes": None, "in_workbook": False,
            "observed_plan": r.get("plan"), "observed_status": r.get("status"),
            "reconciliation": (
                "Present in the Pantheon account, absent from the workbook. "
                "Decide whether this is a client site missing from the audit or "
                "scratch to decommission."),
        })

    out = {
        "schema": "fleet-inventory/1",
        "note": ("Authoritative and human-owned. Edit by hand, review in a PR. "
                 "Nothing regenerates this from a scan."),
        "site_count": len(sites),
        "sites": sorted(sites, key=lambda x: x["site_id"]),
    }
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    pan = [s for s in sites if s["host"] == "CM Pantheon"]
    unmatched = [s["site_id"] for s in pan if s["in_workbook"] and not s["host_site_name"]]
    extra = [s["site_id"] for s in sites if not s["in_workbook"]]
    print("%d sites -> %s" % (len(sites), a.out))
    print("  hosts: %s" % ", ".join(
        "%s=%d" % (h, sum(1 for s in sites if s["host"] == h))
        for h in sorted({s["host"] for s in sites if s["host"]})))
    print("  Pantheon domains mapped to a machine name: %d"
          % sum(1 for s in pan if s["host_site_name"]))
    print("  RECONCILE, in workbook but not in Pantheon (%d): %s" % (len(unmatched), unmatched))
    print("  RECONCILE, in Pantheon but not in workbook (%d): %s" % (len(extra), extra))
    return 0


if __name__ == "__main__":
    sys.exit(main())
