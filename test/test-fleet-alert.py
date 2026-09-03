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
print("-- the TEST message: labelled, about nothing real, and the real shape --")
# It reads nothing from the ledger, so it runs against an EMPTY history dir,
# which is also how it cannot leak a real finding into a test.
import subprocess
_script = os.path.join(HERE, "..", "scripts", "fleet-alert.py")
with tempfile.TemporaryDirectory() as _empty:
    _out = subprocess.run([sys.executable, _script, "--test", "--history", _empty,
                           "--page-url", "https://example/", "--sent-by", "me",
                           "--run-url", "https://runs/1"],
                          capture_output=True, text=True)
    _quiet = subprocess.run([sys.executable, _script, "--history", _empty],
                            capture_output=True, text=True)
check("--test exits 0 against an empty ledger", _out.returncode == 0, _out.stderr)
# The title goes to stderr so the CI log shows what was sent without the
# workflow having to parse the payload, which is how the 2026-09-03 send died.
check("--test says on stderr what it is sending", "sending: TEST ALERT" in _out.stderr, _out.stderr[:120])
check("...and stdout is the payload alone", _out.stdout.count("\n") == 1, repr(_out.stdout[:60]))
try:
    _card = json.loads(_out.stdout)
except Exception as e:                                       # pragma: no cover
    _card = {}
    check("--test prints one JSON payload", False, str(e))
# THE SHAPE A WORKFLOWS WEBHOOK ACCEPTS. The first cut sent a MessageCard and
# the endpoint answered 400. An Adaptive Card in `attachments`, or nothing
# renders.
_att = (_card.get("attachments") or [{}])[0]
check("...and it is an Adaptive Card in attachments, the shape a Teams Workflows "
      "webhook renders",
      _card.get("type") == "message"
      and _att.get("contentType") == "application/vnd.microsoft.card.adaptive"
      and (_att.get("content") or {}).get("type") == "AdaptiveCard",
      str(_card)[:160])
_blocks = (_att.get("content") or {}).get("body") or [{}, {}]
_title = _blocks[0].get("text", "")
check("the title starts with TEST", _title.startswith("TEST"), _title)
check("...and says it is not a real finding", "not a real finding" in _title, _title)
_text = _blocks[1].get("text", "") if len(_blocks) > 1 else ""
# Backticks render literally in Adaptive Card markdown.
check("the body uses no backticks", "`" not in _text and "`" not in _title, _text[:120])
check("the body says nothing is wrong", "Nothing is wrong" in _text, _text[:200])
check("...names who sent it", "me" in _text, _text[:200])
check("...and the run that sent it", "https://runs/1" in _text, _text[:200])
check("the planted site is example.invalid", A.TEST_SITE in _text, _text[:200])
# NEVER A REAL SITE. Every domain in the inventory is checked against the body,
# because a test message naming a client site is a false alarm someone acts on.
_inv = os.path.join(HERE, "..", "data", "fleet-inventory.json")
_domains = []
if os.path.exists(_inv):
    _j = json.load(open(_inv))
    _sites = _j.get("sites") if isinstance(_j, dict) else _j
    _domains = [(s.get("domain") or s.get("site_id") or "") for s in
                (_sites.values() if isinstance(_sites, dict) else _sites)]
check("the inventory was read, so the next check is not vacuous", len(_domains) > 50, str(len(_domains)))
_named = [d for d in _domains if d and d in _text]
check("the test message names no real site", not _named, str(_named))
check("...and is not red", _blocks[0].get("color") != A.ALERT_COLOUR, str(_blocks[0].get("color")))
# And the other direction: a REAL alert never carries the label.
_rh, _rb = A.message(_found, "https://example/")
check("a real alert is not labelled TEST", "TEST" not in _rh and "TEST" not in _rb, _rh)
# Reached by .get() so a wrong shape is a FAIL line and not a traceback.
_rp = A.payload(_rh, _rb, A.ALERT_COLOUR)
_real = ((((_rp.get("attachments") or [{}])[0]).get("content") or {}).get("body") or [{}])[0]
check("...and is red", _real.get("color") == "Attention", str(_real.get("color")))
check("...and uses no backticks either", "`" not in _rb, _rb)
check("without --test an empty ledger prints nothing to send",
      _quiet.stdout.strip() == "" and _quiet.returncode == 0, _quiet.stdout[:80])

print()
print("-------------------------------------------------------------------")
print("%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
