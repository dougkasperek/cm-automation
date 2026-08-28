#!/usr/bin/env python3
"""build-fleet-inventory.py must REFUSE to overwrite an existing inventory.

The generator seeds data/fleet-inventory.json once; after that the file is
human-owned and carries rulings the generator knows nothing about --
consent_managed on all 85 sites, consent_model, the nexcess_site_id join key
ingest refuses rows without, production and decommission rulings. Until
2026-08-28 its write was unconditional, so a rerun per its own Usage block
erased all of them and exited 0: a silent destructive success on the one file
in this repo a person maintains by hand.

Tested in the REFUSING direction, offline, via subprocess. A control tested
only in the permitting direction is the --known-hosts bug: present, looks
correct, enforces nothing.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "scripts", "build-fleet-inventory.py")

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok    " + name)
    else:
        FAIL += 1
        print("FAIL  " + name + (("  <- " + str(detail)[:200]) if detail else ""))


with tempfile.TemporaryDirectory() as td:
    existing = os.path.join(td, "inventory.json")
    marker = {"sites": [], "hand_ruling_that_must_survive": True}
    with open(existing, "w") as fh:
        json.dump(marker, fh)

    # The inputs deliberately do not exist: the refusal must fire BEFORE any
    # input is read, or a rerun with valid inputs still destroys the file.
    r = subprocess.run(
        [sys.executable, SCRIPT,
         "--email-inventory", os.path.join(td, "no-such-input.json"),
         "--pantheon-scan", os.path.join(td, "no-such-scan.json"),
         "--out", existing],
        capture_output=True, text=True)

    check("an existing --out is REFUSED, not overwritten", r.returncode == 2,
          "exit %d, stderr: %s" % (r.returncode, r.stderr[:150]))
    check("...and the refusal says so, naming the file",
          "REFUSED" in r.stderr and "inventory.json" in r.stderr, r.stderr[:200])
    check("...before any input is read",
          "no-such-input" not in r.stderr and "Traceback" not in r.stderr,
          r.stderr[:200])
    check("the existing file is untouched, byte for byte",
          json.load(open(existing)) == marker)

    # The permitting direction still exists: a FRESH --out gets past the
    # guard (and then fails on the missing inputs, which is a different,
    # loud error -- a traceback, not a refusal).
    fresh = os.path.join(td, "fresh.json")
    r2 = subprocess.run(
        [sys.executable, SCRIPT,
         "--email-inventory", os.path.join(td, "no-such-input.json"),
         "--pantheon-scan", os.path.join(td, "no-such-scan.json"),
         "--out", fresh],
        capture_output=True, text=True)
    check("a fresh --out is not refused (it fails later, on its real inputs)",
          "REFUSED" not in r2.stderr and r2.returncode != 0, r2.stderr[:150])
    check("...and nothing was written to it", not os.path.exists(fresh))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
