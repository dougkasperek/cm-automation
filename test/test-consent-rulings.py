#!/usr/bin/env python3
"""The consent rulings in the inventory: seeded once, then human-owned.

Offline. Reads the committed inventory; writes only to a temp copy.

WHAT THIS GUARDS
----------------
`consent_model` is the fact that makes a consent finding meaningful, and it
cannot be measured. On 2026-08-27 `interstatewaste.com` was reported as leaking
four trackers; it is an opt-out site outside California behaving exactly as
designed. The scan saw correctly and scored on an absence.

These tests assert the PROPERTIES, not the current membership of the managed
list. That list grows as clients onboard, so pinning its size or its contents
would be the fleet-count mistake CLAUDE.md records three tests making.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INV = os.path.join(ROOT, "data", "fleet-inventory.json")
SEED = os.path.join(ROOT, "scripts", "seed-consent-rulings.py")

spec = importlib.util.spec_from_file_location("seed", SEED)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- " + str(detail)) if (detail and not cond) else ""))


raw = json.load(open(INV))
sites = {r["site_id"]: r for r in raw["sites"]}

# ------------------------------------------------- 1. every site has an answer
print("-- every site carries a consent ruling, including 'not ours' --")
missing = [s for s, r in sites.items() if "consent_managed" not in r]
check("every inventory row has consent_managed", not missing, missing[:5])

# NOT-MANAGED IS RECORDED, NOT LEFT BLANK. Doug, 2026-08-27: unmanaged client
# sites are still reported, flagged as theirs. A blank would be
# indistinguishable from "nobody has ruled", and those are different answers.
check("not-managed is stored as False, never as a missing key",
      all(isinstance(r.get("consent_managed"), bool) for r in sites.values()),
      [s for s, r in sites.items() if not isinstance(r.get("consent_managed"), bool)][:5])

managed = {s: r for s, r in sites.items() if r["consent_managed"]}
check("some sites are managed", len(managed) > 0, len(managed))

# ------------------------------------------------------- 2. the model is usable
print("\n-- consent_model says what the site is SUPPOSED to do --")
BAD = [s for s, r in managed.items()
       if r.get("consent_model") not in ("opt-in", "opt-out")]
check("every managed site has a model severity can read", not BAD, BAD)

# A model on a site we do not manage would be a claim about someone else's
# configuration that nobody here established.
leaked = [s for s, r in sites.items()
          if not r["consent_managed"] and r.get("consent_model") is not None]
check("an unmanaged site claims no model", not leaked, leaked[:5])

check("a managed site names the rule it inherits from",
      all(r.get("consent_rule") for r in managed.values()),
      [s for s, r in managed.items() if not r.get("consent_rule")])

# The whole point: at least one site must be opt-out, or the distinction this
# was built for is not represented and the tests prove nothing.
check("the opt-out case is represented in the data",
      any(r["consent_model"] == "opt-out" for r in managed.values()),
      sorted({r["consent_model"] for r in managed.values()}))

# ---------------------------------------------------- 3. the seed cannot clobber
print("\n-- the inventory is the master, and the seed defers to it --")
tmp = tempfile.mkdtemp()
try:
    copy = os.path.join(tmp, "inv.json")
    shutil.copy(INV, copy)

    def run(*extra):
        return subprocess.run([sys.executable, SEED, "--inventory", copy, *extra],
                              capture_output=True, text=True)

    r = run()
    check("re-running on seeded data writes nothing", "0 field(s)" in r.stdout,
          r.stdout.strip()[:100])
    check("...and exits 0", r.returncode == 0, r.returncode)

    # A person changes a ruling. The seed must lose.
    d = json.load(open(copy))
    target = None
    for rec in d["sites"]:
        if rec.get("consent_managed") and rec.get("consent_model") == "opt-out":
            rec["consent_model"] = "opt-in"
            target = rec["site_id"]
            break
    json.dump(d, open(copy, "w"), indent=2, sort_keys=True)
    check("found an opt-out site to edit", target is not None)

    r = run("--apply")
    check("a human edit is REFUSED, not overwritten", r.returncode == 1, r.returncode)
    check("...and the refusal names the disagreement",
          target and target in r.stdout and "opt-in" in r.stdout, r.stdout[:200])
    after = {x["site_id"]: x for x in json.load(open(copy))["sites"]}
    check("...and the file is untouched",
          after[target]["consent_model"] == "opt-in", after[target]["consent_model"])

    # --force is the deliberate override, and it must actually work or the
    # escape hatch is decoration.
    r = run("--apply", "--force")
    check("--force overwrites deliberately", r.returncode == 0, r.returncode)
    after = {x["site_id"]: x for x in json.load(open(copy))["sites"]}
    check("...restoring the workbook value",
          after[target]["consent_model"] == "opt-out", after[target]["consent_model"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------- 4. the tabled sites stay out
print("\n-- sites on other hosting are not invented into this inventory --")
# buffalowebsitedevelopment.com, homearcadegames.com and mightytaco.com are
# managed by clevermethod and sit on hosting this fleet does not cover. Doug
# tabled them 2026-08-27. Creating inventory rows for sites no scanner reaches
# is the mis-keyed-ledger failure pointed at the inventory instead.
TABLED = ("buffalowebsitedevelopment.com", "homearcadegames.com", "mightytaco.com")
check("the off-fleet managed sites are not in the seed table",
      not any(t in S.WORKBOOK for t in TABLED),
      [t for t in TABLED if t in S.WORKBOOK])
check("...and not in the inventory",
      not any(t in sites for t in TABLED), [t for t in TABLED if t in sites])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
