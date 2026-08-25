#!/usr/bin/env python3
"""Offline tests for nexcess-ssh-targets.py. No network, no key, no ledger.

The rule under test: a target is either fully known or it is skipped by name.
Nothing here may assemble an SSH destination out of parts, because the failure
mode is not a failed connection, it is a successful one to the wrong host.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "scripts", "nexcess-ssh-targets.py")
spec = importlib.util.spec_from_file_location("nst", SRC)
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

passed = failed = 0


def ok(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("ok    %s" % label)
    else:
        failed += 1
        print("FAIL  %s" % label)


INV = {"sites": [
    {"site_id": "real.com", "domain": "real.com", "host": "CM Nexcess"},
    {"site_id": "other.com", "domain": "other.com", "host": "CM Nexcess"},
]}


def row(site_id, host="abc.nxcli.net", user="a1b2c3d4"):
    return {site_id: {"site_id": site_id,
                      "nexcess_temp_domain": host,
                      "nexcess_unix_username": user}}


print("-" * 67)
print("a target is fully known, or it is not a target")
print("-" * 67)

t, s = T.resolve(row("real.com"), INV)
ok(len(t) == 1 and not s, "a complete row resolves to one target")
ok(t[0]["host"] == "abc.nxcli.net", "the SSH host is nexcess_temp_domain")
ok(t[0]["user"] == "a1b2c3d4_1",
   "the SSH user is the API username plus the portal's _1 suffix")
ok(t[0]["site_id"] == "real.com",
   "the target carries the inventory site_id, so the ledger row keys correctly")

t, s = T.resolve(row("real.com"), INV, user_suffix="_2")
ok(t[0]["user"] == "a1b2c3d4_2",
   "the suffix is overridable, since it is verified on one site only")

print()
print("-" * 67)
print("missing parts are skipped by name, never assembled")
print("-" * 67)

for field, label in (("nexcess_temp_domain", "host"),
                     ("nexcess_unix_username", "user")):
    r = row("real.com")
    r["real.com"][field] = None
    t, s = T.resolve(r, INV)
    ok(t == [] and len(s) == 1 and label in s[0]["why"],
       "a row with no SSH %s is skipped and says so" % label)

# The ledger's absence sentinel is the STRING "unknown". A falsiness test lets
# it through, and this repo has already rendered `unknown` into a page as if it
# were a hostname.
for bad in ("unknown", "UNKNOWN", " unknown ", ""):
    r = row("real.com", host=bad)
    t, s = T.resolve(r, INV)
    ok(t == [] and len(s) == 1,
       "host %r is an absence, not a hostname" % bad)

r = row("ghost.com")
t, s = T.resolve(r, INV)
ok(t == [] and "no inventory row" in s[0]["why"],
   "a site with no inventory row is skipped, not keyed on itself")

print()
print("-" * 67)
print("the set")
print("-" * 67)

rows = {}
rows.update(row("real.com"))
rows.update(row("other.com", host="def.nxcli.io", user="e5f6g7h8"))
rows.update(row("ghost.com"))
t, s = T.resolve(rows, INV)
ok(len(t) == 2 and len(s) == 1,
   "a bad row does not stop the good ones")
ok(sorted(x["site_id"] for x in t) == ["other.com", "real.com"],
   "...and the good ones are exactly the resolvable set")
ok(len({(x["user"], x["host"]) for x in t}) == 2,
   "each site gets its own user and host, not a shared one")

src = open(SRC).read()
ok("--user-suffix" in src, "the _1 suffix is a flag, not a buried literal")
ok("reports/" not in src.split('"""')[2] if src.count('"""') > 2 else True,
   "the resolver reads the committed ledger, not gitignored reports/")

print()
print("-" * 67)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
