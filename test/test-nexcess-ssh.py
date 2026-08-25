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
print("the pinned host keys, and the CI job that requires them")
print("-" * 67)

KH = os.path.join(HERE, "..", "data", "nexcess-known-hosts")
WF = os.path.join(HERE, "..", ".github", "workflows",
                  "nexcess-fleet-healthcheck.yml")
SCAN = os.path.join(HERE, "..", "scripts", "nexcess-fleet-healthcheck.sh")

ok(os.path.exists(KH), "the pinned host-key file is committed, not gitignored")
_kh = [l for l in open(KH) if l.strip() and not l.startswith("#")]
_hosts = {l.split()[0] for l in _kh}
ok(len(_hosts) > 0 and all("." in h for h in _hosts),
   "every pinned line names a real hostname")
ok(len(_kh) > len(_hosts),
   "more key lines than hosts, so several key types are pinned per host")

_scan = open(SCAN).read()
# The bug this pair of assertions exists for: StrictHostKeyChecking appeared
# TWICE, ssh took the first value, and the pin enforced nothing while looking
# correct. Verified by removing a host from the file and watching the scan
# succeed anyway.
ok(_scan.count("StrictHostKeyChecking=yes") == 1
   and _scan.count("StrictHostKeyChecking=accept-new") == 1,
   "each StrictHostKeyChecking value appears exactly once")
ok("StrictHostKeyChecking=accept-new" not in
   _scan.split("if [ -n \"$KNOWN_HOSTS\" ]; then")[1].split("else")[0],
   "the pinned branch never mentions accept-new, since ssh takes the FIRST value")

_wf = open(WF).read()
ok("data/nexcess-known-hosts" in _wf,
   "CI passes the pinned host-key file")
ok("exit 1" in _wf and "nexcess-known-hosts is missing" in _wf,
   "CI REFUSES to run if the pinned file is missing or empty")
ok("rm -f ~/.ssh/nexcess_ci" in _wf,
   "CI removes the private key even when the scan fails")
ok("schedule:" not in _wf,
   "the job is dispatch-only: it carries a credential that can write to "
   "client sites")

# The scan produced an artifact and nothing else until 2026-08-25. A workflow
# that scans and does not persist is a 90-day artifact and then nothing, and
# the ledger is the one asset here that cannot be regenerated.
ok("persist-ledger" in _wf and "persist-ledger.sh" in _wf,
   "the CI job can persist its run into the ledger")
ok("group: fleet-ledger-write" in _wf,
   "...under the same lock as every other workflow, so none can race")
ok("_publish-dashboard.yml" in _wf,
   "...and publishes, so the ledger cannot move while the page does not")

# Persisting DEFAULTS OFF. This writes to the `health` source that every
# severity rule reads, into an append-only ledger where a mis-keyed row cannot
# be corrected in place.
_pl = _wf.split("persist_ledger:")[1].split("publish_dashboard:")[0]
ok("default: false" in _pl,
   "persisting is opt-in, so early runs are read as artifacts first")

# reports/ is gitignored, so it is ABSENT on a fresh clone and on every CI
# runner. CLAUDE.md says so in the data-model section. The scanner wrote into
# it anyway and the first real CI run died on
# "./reports/...json.tmp: No such file or directory" -- after resolving all 22
# targets correctly, so everything that could have been wrong was right.
ok("mkdir -p \"$OUT_DIR\"" in _scan,
   "the scanner creates its output directory before writing into it")
_pre = _scan.split('echo "[" > "$JSON_OUT.tmp"')[0]
ok('mkdir -p "$OUT_DIR"' in _pre,
   "...and creates it BEFORE the first redirect, not at the end")

# A dry run that writes a file is a small lie about what --dry-run means.
_dry = _scan.split('if [ "$DRY_RUN" -eq 1 ]; then')[1].split("exit 0")[0]
ok("JSON_OUT" not in _dry,
   "a dry run names no output file at all")
ok(_scan.count('if [ "$DRY_RUN" -eq 1 ]; then') == 1,
   "the dry-run branch exists once, so it cannot fall through to the scan loop")

print()
print("-" * 67)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
