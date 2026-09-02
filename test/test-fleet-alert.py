#!/usr/bin/env python3
"""Does the alert FIRE when it should, and stay quiet when it should?

Offline, no network, no webhook.

WHY THIS EXISTS. The trigger has never fired on real data, across all seven
vulnerability runs to 2026-09-02, and that is by design: alerting on new
findings would have sent 143 messages the evening Wordfence published ten
advisories at once. But a check that only ever stays quiet is unfalsified
rather than verified, which is exactly what was wrong with "0 leaking" on the
consent gating sweep until a leak was planted and the test made to find it.

So this plants a critical and requires it to be found, banded, grouped and
carrying its fix version. Every silence below is also asserted, because the
quiet cases are the ones that will actually happen.
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "fleet_alert", os.path.join(HERE, "..", "scripts", "fleet-alert.py"))
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok    %s" % name)
    else:
        FAIL += 1
        print("FAIL  %s%s" % (name, ("  <- " + detail) if detail else ""))


def rows(*runs):
    """runs: (run_id, [findings]) pairs -> flat ledger rows."""
    out = []
    for rid, fs in runs:
        for f in fs:
            out.append(dict(f, run_id=rid))
    return out


def f(site, slug, cve, cvss, version="1.0", fix="2.0"):
    return {"site_id": site, "slug": slug, "cve": cve, "cvss": cvss,
            "version": version, "fix_version": fix,
            "rating": "Critical" if cvss >= 9 else "Medium"}


print("-- a planted critical must be FOUND --")
_planted = rows(
    ("vuln-2026-01-01_0000", [f("a.com", "divi", "CVE-1", 6.4)]),
    ("vuln-2026-01-02_0000", [f("a.com", "divi", "CVE-1", 6.4),
                              f("b.com", "divi-form-builder", "CVE-9", 9.8,
                                version="3.0.3", fix="5.1.9")]),
)
_found, _latest, _prev = A.new_criticals(_planted)
check("a new 9.8 on a site is found", len(_found) == 1, str(_found))
check("...and it is the planted one",
      _found and _found[0]["site_id"] == "b.com", str(_found[:1]))
_head, _body = A.message(_found, "https://example/")
check("the message names the site", "b.com" in _body, _body)
check("...the plugin", "divi-form-builder" in _body, _body)
check("...the version it runs", "3.0.3" in _body, _body)
check("...and the version to update to", "5.1.9" in _body, _body)
check("the headline says how many and where", "1 site" in _head, _head)

print()
print("-- the quiet cases, which are the ones that will actually happen --")
_same = rows(("vuln-2026-01-01_0000", [f("a.com", "divi", "CVE-1", 9.8)]),
             ("vuln-2026-01-02_0000", [f("a.com", "divi", "CVE-1", 9.8)]))
_r, _, _ = A.new_criticals(_same)
# THE ciminelli CASE. A standing critical is not news. It is on the page and in
# the backlog; repeating it every run is how an alert gets muted.
check("a critical carried over from the previous run is NOT new", not _r, str(_r))

_below = rows(("vuln-2026-01-01_0000", []),
              ("vuln-2026-01-02_0000", [f("a.com", "divi", "CVE-2", 8.9)]))
_r, _, _ = A.new_criticals(_below, ["vuln-2026-01-01_0000", "vuln-2026-01-02_0000"])
check("a new 8.9 does not trip the critical threshold", not _r, str(_r))

_first = rows(("vuln-2026-01-01_0000", [f("a.com", "divi", "CVE-9", 9.8)]))
_r, _latest1, _prev1 = A.new_criticals(_first)
# NOT "all clear". With no baseline everything is new and the alert would open
# with the entire backlog, which is the same trap as new_since_last on a first
# run.
check("a first run stays silent", not _r and _prev1 is None,
      "prev=%s" % _prev1)
check("...and says so by returning no baseline, not an empty comparison",
      _latest1 is not None and _prev1 is None)

_none, _l, _p = A.new_criticals([])
check("an empty ledger is not a comparison either", _l is None and _p is None)

print()
print("-- one plugin with three advisories is ONE job, not three --")
_multi = rows(
    ("vuln-2026-01-01_0000", []),
    ("vuln-2026-01-02_0000", [
        f("b.com", "divi-form-builder", "CVE-1", 9.8, version="3.0.3", fix="5.1.3"),
        f("b.com", "divi-form-builder", "CVE-2", 9.8, version="3.0.3", fix="5.1.9"),
        f("b.com", "divi-form-builder", "CVE-3", 9.1, version="3.0.3", fix="5.0.2"),
    ]),
)
# The run ids are passed explicitly, because run 1 found NOTHING and therefore
# wrote no rows. Deriving the list from findings would make it invisible and
# every finding in run 2 would read as new against a run that is not there.
_r, _, _ = A.new_criticals(_multi, ["vuln-2026-01-01_0000", "vuln-2026-01-02_0000"])
_h, _b = A.message(_r, "")
check("three advisories on one plugin are found", len(_r) == 3, str(len(_r)))
check("...and collapse to one line", _b.count("\n") == 0, _b)
# The HIGHEST fix version, or the update does not close every one of them.
check("...carrying the highest fix version needed", "5.1.9" in _b, _b)
check("...and the worst score", "9.8" in _b, _b)

print()
print("-- a run that found NOTHING is still a run --")
# It writes no findings, so it is invisible if the run list comes from them.
# The comparison would then reach past it to an older run and every finding
# would read as new. Same rule the component ledger already has.
_empty_mid = rows(("vuln-2026-01-01_0000", [f("a.com", "divi", "CVE-9", 9.8)]),
                  ("vuln-2026-01-03_0000", [f("a.com", "divi", "CVE-9", 9.8)]))
_r, _l, _p = A.new_criticals(
    _empty_mid, ["vuln-2026-01-01_0000", "vuln-2026-01-02_0000", "vuln-2026-01-03_0000"])
check("the empty middle run is the baseline, not the older one",
      _p == "vuln-2026-01-02_0000", "compared against %s" % _p)
# And the consequence: against an empty run, a carried-over finding IS new.
check("...so a finding absent from it reads as new", len(_r) == 1, str(len(_r)))

print()
print("-------------------------------------------------------------------")
print("%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
