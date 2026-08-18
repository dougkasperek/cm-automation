#!/usr/bin/env python3
"""
extract-audit-workbook.py - one-time-ish extractor.

Turns the team's manual workbook into a machine-readable input file. Two jobs:

  1. Supply the domain list and each site's declared email configuration, which
     is what the DNS checker needs as input.
  2. Carry the team's RECORDED Pass/Fail cells forward, so an automated check
     can be compared against a year of human judgement instead of silently
     replacing it. That comparison is the point; see compare mode in
     fleet-email-dns.py.

Requires openpyxl (read-only, one-time). The DNS checker itself does not.

Usage:
  ./scripts/extract-audit-workbook.py --xlsx path/to/audit.xlsx --out data/fleet-email-inventory.json
"""
import argparse
import json
import sys

try:
    import openpyxl
except ImportError:
    sys.exit("needs openpyxl:  pip install openpyxl")

# Column indices in the Sites sheet. Row 1 is a merged group header, row 2 the
# real header, data starts row 3.
C = {
    "domain": 0, "hosted": 1, "dns": 2,
    "smtp_plugin": 3, "provider": 4, "sending_domain": 5,
    "envelope_from": 6, "from_address": 7, "env_from_match": 8, "from_name": 9,
    "spf": 10, "dkim": 11, "dmarc": 12, "tracking": 13, "receiving": 14,
    "single_cm_user": 15, "php_version": 16, "wp_version": 17,
    "themes_utd": 18, "plugins_utd": 19,
    "activity_log": 20, "wp_2fa": 21, "hide_login": 22, "xmlrpc_disabled": 23,
    "php_blocker": 24, "keeper_password": 25, "wp2shell_remedied": 26,
    "notes": 27,
}

# Recorded verdicts we will compare against. Blank stays blank; it is NOT a
# pass and it is NOT a fail. Same rule as the ledger: unknown is a value.
VERDICT_FIELDS = ("spf", "dkim", "dmarc", "tracking", "receiving", "env_from_match")


def cell(row, key):
    i = C[key]
    if i >= len(row):
        return None
    v = row[i]
    if v is None:
        return None
    s = str(v).replace("\n", " ").strip()
    return s if s else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.xlsx, data_only=True)
    rows = list(wb["Sites"].iter_rows(values_only=True))
    sites = []
    for r in rows[2:]:
        d = cell(r, "domain")
        if not d:
            continue
        rec = {"domain": d.lower(), "hosted": cell(r, "hosted"), "dns": cell(r, "dns")}
        for k in ("smtp_plugin", "provider", "sending_domain", "envelope_from",
                  "from_address", "from_name", "notes"):
            rec[k] = cell(r, k)
        rec["recorded"] = {k: cell(r, k) for k in VERDICT_FIELDS}
        # Security columns come along for the ride; they are the seed of the
        # inventory file and cost nothing to carry.
        rec["recorded_security"] = {
            k: cell(r, k) for k in (
                "single_cm_user", "php_version", "wp_version", "themes_utd",
                "plugins_utd", "activity_log", "wp_2fa", "hide_login",
                "xmlrpc_disabled", "keeper_password", "wp2shell_remedied")
        }
        sites.append(rec)

    plugins = []
    if "Security Plugins" in wb.sheetnames:
        for r in list(wb["Security Plugins"].iter_rows(values_only=True))[1:]:
            if r and r[0]:
                plugins.append({"name": str(r[0]).strip(),
                                "url": str(r[1]).strip() if r[1] else None,
                                "role": str(r[2]).strip() if r[2] else None,
                                "notes": str(r[3]).strip() if r[3] else None})

    out = {"source": a.xlsx.split("/")[-1], "site_count": len(sites),
           "sites": sites, "security_plugins": plugins}
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("extracted %d sites, %d security plugins -> %s" % (len(sites), len(plugins), a.out))


if __name__ == "__main__":
    main()
