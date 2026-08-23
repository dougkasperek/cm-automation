#!/usr/bin/env python3
"""
Self-check for scripts/diagnose-wp-calls.sh.

Two jobs, and the first matters more than the second.

1. THE DRIFT GUARD. The diagnostic exists to answer a question about the
   SCANNER. If it runs even slightly different commands, it answers a different
   question while looking like it answered this one -- and the answer gets
   written into the handoff as settled. This repo has already deleted one
   mirror (`ci/github-actions/`) that diverged from the thing it mirrored, and
   the copy that loses is always the one nobody is looking at. So the four
   WP-CLI calls and the timeout are compared against the scanner by a test
   rather than by memory.

2. THE VERDICTS. Runs the real script against test/mock/terminus, which now
   models the three ways a call fails while the scanner records a clean value.
   No network, no Pantheon account, no SSH key.

Run: ./test/test-wp-calls.py
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCANNER = os.path.join(ROOT, "scripts", "pantheon-fleet-healthcheck.sh")
DIAG = os.path.join(ROOT, "scripts", "diagnose-wp-calls.sh")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- " + detail) if (detail and not cond) else ""))


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. The drift guard
# ---------------------------------------------------------------------------
print("-- the diagnostic runs the SAME calls as the scanner --")

# Every `terminus remote:wp "$se" -- <args>` in the scanner. The args run to
# the end of the command: a pipe, a redirect, a line continuation, or a closing
# `)"`. Parsed rather than hardcoded here, so this test cannot itself drift
# into being a third copy of the list.
scanner_src = read(SCANNER)
found = re.findall(r'remote:wp\s+"\$se"\s+--\s+(.+)$', scanner_src, re.M)
scanner_calls = set()
for raw in found:
    arg = re.split(r'\s*(?:\||2>|>|\\\s*$|\)")', raw)[0].strip()
    if arg:
        scanner_calls.add(arg)

check("the scanner's remote:wp calls were found at all",
      len(scanner_calls) == 4, str(sorted(scanner_calls)))

diag_src = read(DIAG)
m = re.search(r"^WP_CALLS='(.*?)'$", diag_src, re.M | re.S)
check("the diagnostic declares WP_CALLS", m is not None)
diag_calls = set(x.strip() for x in (m.group(1).splitlines() if m else []) if x.strip())

check("the diagnostic runs exactly the scanner's four calls, no more, no less",
      diag_calls == scanner_calls,
      "only in diagnostic: %s | only in scanner: %s"
      % (sorted(diag_calls - scanner_calls), sorted(scanner_calls - diag_calls)))

# The timeout is part of the question. A diagnostic that waits longer than the
# scanner reports a call as slow-but-fine that the scanner would have killed
# and recorded as clean -- which is the exact failure being investigated.
sc_to = re.search(r"^WP_CLI_TIMEOUT=(\d+)", scanner_src, re.M)
dg_to = re.search(r'^WP_CLI_TIMEOUT="\$\{WP_CLI_TIMEOUT_OVERRIDE:-(\d+)\}"',
                  diag_src, re.M)
check("both declare a WP-CLI timeout", bool(sc_to) and bool(dg_to))
check("the diagnostic's DEFAULT timeout is the scanner's",
      bool(sc_to) and bool(dg_to) and sc_to.group(1) == dg_to.group(1),
      "scanner=%s diagnostic=%s" % (sc_to and sc_to.group(1),
                                    dg_to and dg_to.group(1)))

# It must never grow a write. The scanner's first hard boundary is that this
# tool never changes a client site, and a diagnostic is exactly the kind of
# thing someone later adds a `wp plugin update` to "while we are in there".
for verb in ("plugin update", "theme update", "core update", "db ", "eval",
             "option update", "user create"):
    check("the diagnostic contains no %r" % verb.strip(),
          verb not in " ".join(sorted(diag_calls)))


# ---------------------------------------------------------------------------
# 2. The verdicts, against the mock
# ---------------------------------------------------------------------------
print("\n-- verdicts, offline against test/mock/terminus --")

env = dict(os.environ)
env["PATH"] = os.path.join(HERE, "mock") + os.pathsep + env["PATH"]
env["MOCK_LOGGED_IN"] = "1"


def run(*sites, **kw):
    e = dict(env)
    if kw.get("timeout_override"):
        e["WP_CLI_TIMEOUT_OVERRIDE"] = str(kw["timeout_override"])
    if kw.get("agent_keys"):
        e["MOCK_SSH_AGENT_KEYS"] = "1"
    p = subprocess.run([DIAG] + list(sites), capture_output=True, text=True,
                       env=e, cwd=ROOT, timeout=180)
    return p.returncode, p.stdout + p.stderr


rc, out = run("normalsite")
check("a site whose calls all succeed reports MEASURED throughout",
      "FABRICATED" not in out and out.count("MEASURED") == 4, out[-400:])
check("...and exits 0", rc == 0, "exit %d" % rc)
check("an empty [] is called a real measurement, not silence",
      "genuinely nothing pending" in out)

# The heart of item 22: the scanner records a clean value off a failed call.
rc, out = run("wpclifail")
check("a non-zero exit is FABRICATED, never a clean value", "FABRICATED" in out)
check("...and it names the exit code", "exit 1" in out, out[-500:])
check("...and it surfaces the stderr the scanner throws away",
      "Could not establish a connection" in out)
check("...and it says what the scanner would have written",
      "wp_core_update=up-to-date" in out and "plugin_updates=0" in out)
check("...and exits 2 so a caller can act on it", rc == 2, "exit %d" % rc)

# The nastiest case: exit 0, output on stdout, and none of it is JSON.
rc, out = run("wpclijunk")
check("exit 0 with non-JSON output is still FABRICATED", "FABRICATED" in out)
check("...and it says json_or_empty is what rejected it",
      "NOT JSON" in out, out[-500:])
check("...and exits 2", rc == 2, "exit %d" % rc)

rc, out = run("wpclihang", timeout_override=2)
check("a hung call is FABRICATED and named as a timeout",
      "FABRICATED" in out and "TIMED OUT" in out, out[-400:])
check("...and exits 2", rc == 2, "exit %d" % rc)
check("the shell's own job-control noise is not in the report",
      "Terminated" not in out, out[-400:])

# The control call. `core version` and `core check-update` share one SSH
# session, so a site that answers the first and not the second is telling us
# the session worked -- which is the whole basis for reading an empty
# check-update as a real answer rather than as silence.
rc, out = run("coredrift")
check("the control call reports the INSTALLED version, not the available one",
      "6.8.1" in out and "MEASURED" in out, out[-600:])
check("a site with a real pending core update is not called clean",
      "wp_core_update=<the available version>" in out, out[-600:])

# A run must be able to distinguish itself from a broken run. If every site in
# a batch reads clean, that is either good news or a dead SSH path, so at least
# one site with known pending updates belongs in every batch.
rc, out = run("plugindrift")
check("a site with pending plugin updates reports a count, not 0",
      "plugin_updates=<count>" in out, out[-600:])

# Bad input must fail loudly rather than reporting a clean fleet.
rc, out = run()
check("no sites given is an error, not an empty clean report",
      rc == 1 and "no sites given" in out, "exit %d" % rc)

# ---------------------------------------------------------------------------
# 3. The tool classifies its OWN failures
# ---------------------------------------------------------------------------
# The first real run of this script stopped at "Enter passphrase for key
# ~/.ssh/id_rsa". ssh reads that prompt from /dev/tty, so the `< /dev/null` in
# run_capture does not stop it; the prompt sits unanswered until the timeout
# kills it, and the call is reported as failed. That verdict is true of the
# scanner too, but it is a fact about one laptop's ssh-agent wearing a fleet
# finding's clothes -- the `probe` mistake, where a missing CA bundle was
# reported as four unreachable hosts.
print("\n-- it distinguishes a local fault from a fleet finding --")

rc, out = run("wpclihang", timeout_override=2)
check("an empty ssh-agent is warned about before any call runs",
      "ssh-agent holds no identities" in out, out[:500])
check("a timeout with an empty agent is flagged as possibly LOCAL",
      "BUT READ THIS FIRST" in out and "not a site" in out, out[-700:])
check("...and it names the one command that fixes it",
      "ssh-add --apple-use-keychain" in out)
check("...but the verdict is still FABRICATED and the exit is still 2",
      "FABRICATED" in out and rc == 2, "exit %d" % rc)

# The warning must not fire on every failure, or it becomes noise that hides
# the real ones. A loaded agent means a timeout is a genuine finding.
rc, out = run("wpclihang", timeout_override=2, agent_keys=True)
check("with keys loaded, a timeout is NOT excused as a local fault",
      "BUT READ THIS FIRST" not in out, out[-500:])
check("...and no agent warning is printed at all",
      "ssh-agent holds no identities" not in out)

# A non-zero exit is not a passphrase prompt. Only timeouts are ambiguous.
rc, out = run("wpclifail")
check("a non-timeout failure is never blamed on the ssh-agent",
      "BUT READ THIS FIRST" not in out, out[-500:])

# ---------------------------------------------------------------------------
# 4. An input error is not a fleet finding
# ---------------------------------------------------------------------------
# The first real run was given `sgroilawley` -- the domain minus its TLD --
# where the PANTHEON SITE NAME was wanted. Terminus said "A site named
# sgroilawley was not found" and the script scored all four calls FABRICATED,
# putting a typo in the same column as a site whose plugin count is a lie.
#
# Four of the five sites worth diagnosing have a Pantheon name that differs
# from their domain (sgroilawley.com -> sgroifinancial, lifebreath.com ->
# life-breath), so this was never going to be a one-off slip.
print("\n-- a name that is not a site is an input error, not a finding --")

rc, out = run("notasite", agent_keys=True)
check("an unknown site name is NOT-A-SITE, never FABRICATED",
      "NOT-A-SITE" in out and "FABRICATED" not in out, out[-600:])
check("...and it exits 1 (input error), not 2 (fleet finding)",
      rc == 1, "exit %d" % rc)
check("...and it does not invent a consequence for the scanner",
      "the scanner records" not in out.split("NOT-A-SITE")[-1].split("=====")[0],
      out[-600:])
check("...and the summary explains the domain/site-name split",
      "PANTHEON SITE NAMES" in out and "sgroifinancial" in out)

# The fix that stops it happening: take the domain everyone actually uses.
inv = os.path.join(ROOT, "data", "fleet-inventory.json")
if os.path.exists(inv):
    rc, out = run("sgroilawley.com", agent_keys=True)
    check("a DOMAIN is resolved to the Pantheon site name from the inventory",
          "sgroifinancial.live" in out, out[:400])
    check("...and it says it did the translation, rather than doing it silently",
          "the inventory calls it" in out, out[:400])
    check("...so passing a domain never reads as NOT-A-SITE",
          "NOT-A-SITE" not in out, out[-400:])
    # A name in neither column must still reach Pantheon as typed, or a site
    # missing from the inventory becomes undiagnosable.
    rc, out = run("normalsite", agent_keys=True)
    check("a name the inventory does not know is passed through unchanged",
          "normalsite.live" in out and "the inventory calls it" not in out,
          out[:300])
else:
    print("skip  inventory-resolution checks (data/fleet-inventory.json missing)")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
