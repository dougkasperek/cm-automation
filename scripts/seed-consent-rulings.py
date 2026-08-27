#!/usr/bin/env python3
"""Seed the inventory's consent rulings from Nick's OneTrust audit workbook.

A SEED, NOT A SYNC. Run once. After that the INVENTORY is the master and this
workbook is history.

WHY THAT DISTINCTION MATTERS HERE
---------------------------------
`onetrust-audit.xlsx` lives in SharePoint, is maintained by hand, and is being
retired. If this script stayed in the loop the two would diverge, and the copy
that loses is always the one nobody is looking at -- this repo has burned that
lesson twice already (the gitignored `ci/github-actions/` mirror, and the
`fleet_cloudflare_access.md` note that turned out not to exist). So the values
land in `data/fleet-inventory.json`, beside `production` and `owner`, which is
where every other human ruling in this system lives.

IT REFUSES TO OVERWRITE A DIFFERENT ANSWER. If a field already holds a value
and this script would write a different one, it stops and prints the
disagreement rather than silently winning. That is what makes the inventory the
master rather than this file: once a person edits a ruling, re-running the seed
cannot undo it.

WHAT IT WRITES, per site:

  consent_managed   true / false   does clevermethod manage consent here
  consent_model     "opt-in" | "opt-out"   what the site is SUPPOSED to do
  consent_rule      the OneTrust geolocation rule name, for traceability
  consent_note      free text where the workbook recorded a caveat

`consent_model` IS THE FIELD SEVERITY NEEDS, and it is the one that cannot be
measured. The consent sweep observes what fired; whether that was correct
depends on what the site was configured to do, and only a person knows that.
Without it the rule scores on an absence -- which is how `interstatewaste.com`
came to be reported as leaking four trackers when it is an opt-out site
behaving exactly as designed outside California.

SOURCE: onetrust-audit.xlsx, SharePoint /sites/Projects/Shared Documents/
General/, as it read on 2026-08-11 (last modified) and was read on 2026-08-27.
"""

import argparse
import json
import os
import sys

# From the workbook's Sites sheet, joined to its Geolocation Rules sheet.
# Transcribed here rather than re-read from SharePoint every run: the workbook
# is being retired, and a seed that depends on a live connection to a dying
# source is a seed that stops working at the worst moment.
#
# THE THREE SITES NICK MANAGES THAT ARE NOT IN THIS FLEET are deliberately
# absent: buffalowebsitedevelopment.com, homearcadegames.com and mightytaco.com
# are on hosting this inventory does not cover. Doug tabled that 2026-08-27.
# Adding them here would create inventory rows for sites no scanner reaches,
# which is the mis-keyed-ledger failure pointed at the inventory instead.
WORKBOOK = {
    "actioncarting.com":       ("opt-out", "Interstate Waste Geolocation Rule",
                                "Workbook records consent NOT fully respected: see the "
                                "landing_page cookie. California opt-in, opt-out elsewhere."),
    "choosechq.com":           ("opt-in",  "CCIDA Geolocation Rule", ""),
    "ciminelli.com":           ("opt-in",  "Ciminelli Geolocation Rule", ""),
    "cottrillspharmacy.com":   ("opt-in",  "Cottrill's Pharmacy Geolocation Rule", ""),
    "gmroot.com":              ("opt-in",  "G.M. Root Geolocation Rule",
                                "Geolocation rule was in Draft status in the workbook."),
    "icegame.com":             ("opt-in",  "ICE Geolocation Rule",
                                "Workbook records consent NOT respected: Klaviyo pixel "
                                "needs investigation; no default consent script found."),
    "interstatewaste.com":     ("opt-out", "Interstate Waste Geolocation Rule",
                                "California opt-in, opt-out elsewhere."),
    "lifebreath.com":          ("opt-in",  "Zehnder Geolocation Rule", ""),
    "newmarkciminelli.com":    ("opt-in",  "Ciminelli Geolocation Rule", ""),
    "runtalnorthamerica.com":  ("opt-in",  "Zehnder Geolocation Rule", ""),
    "zehnderamerica.com":      ("opt-in",  "Zehnder Geolocation Rule", ""),
    "zehnder-rittling.com":    ("opt-in",  "Zehnder Geolocation Rule", ""),
}

FIELDS = ("consent_managed", "consent_model", "consent_rule", "consent_note")


def plan(inv):
    """What this seed would change. Returns (writes, conflicts, missing)."""
    writes, conflicts = [], []
    missing = sorted(k for k in WORKBOOK if k not in inv)
    for site_id, rec in sorted(inv.items()):
        if site_id in WORKBOOK:
            model, rule, note = WORKBOOK[site_id]
            want = {"consent_managed": True, "consent_model": model,
                    "consent_rule": rule, "consent_note": note}
        else:
            # EVERY OTHER SITE IS EXPLICITLY NOT-MANAGED, not left blank.
            # Doug, 2026-08-27: unmanaged client sites still get reported,
            # flagged as theirs. A blank would be indistinguishable from
            # "nobody has ruled", and those are different answers.
            want = {"consent_managed": False, "consent_model": None,
                    "consent_rule": None, "consent_note": ""}
        for k, v in want.items():
            cur = rec.get(k, "\0missing")
            if cur == "\0missing":
                writes.append((site_id, k, v))
            elif cur != v:
                conflicts.append((site_id, k, cur, v))
    return writes, conflicts, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", default="data/fleet-inventory.json")
    ap.add_argument("--apply", action="store_true",
                    help="write the changes; without it, print them and exit")
    ap.add_argument("--force", action="store_true",
                    help="overwrite values that disagree. Use only when the "
                         "workbook is right and the inventory is stale.")
    a = ap.parse_args()

    raw = json.load(open(a.inventory))
    # The inventory is a dict keyed on site_id at the top level, or {"sites": …}.
    container = raw["sites"] if isinstance(raw, dict) and "sites" in raw else raw
    if isinstance(container, list):
        inv = {r["site_id"]: r for r in container}
    else:
        inv = container

    writes, conflicts, missing = plan(inv)

    if missing:
        print("IN THE WORKBOOK, NOT IN THE INVENTORY (%d):" % len(missing))
        for m in missing:
            print("   %s" % m)
        print("   These are managed sites this fleet does not cover. Left alone.\n")

    if conflicts and not a.force:
        print("REFUSING TO WRITE. %d field(s) already hold a different answer:\n"
              % len(conflicts))
        for site, k, cur, want in conflicts:
            print("   %-30s %-18s inventory=%r  workbook=%r" % (site, k, cur, want))
        print("\nThe inventory is the master. If a person changed one of these,")
        print("the workbook is out of date and this seed has nothing to add.")
        print("If the workbook is right, re-run with --force.")
        return 1

    managed = sum(1 for s, k, v in writes if k == "consent_managed" and v)
    print("%d field(s) to write across %d site(s); %d marked managed."
          % (len(writes), len({s for s, _, _ in writes}), managed))
    if not a.apply:
        print("\nDry run. Re-run with --apply to write.")
        for site, k, v in writes[:8]:
            print("   %-30s %-18s -> %r" % (site, k, v))
        if len(writes) > 8:
            print("   ... and %d more" % (len(writes) - 8))
        return 0

    for site, k, v in writes:
        inv[site][k] = v
    for site, k, cur, want in conflicts:
        inv[site][k] = want

    with open(a.inventory, "w") as fh:
        json.dump(raw, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote %s" % a.inventory)
    return 0


if __name__ == "__main__":
    sys.exit(main())
