#!/usr/bin/env python3
"""Offline tests for check-worker-exposure.py. No network, no credentials.

Everything here drives the two classifiers directly. The point of the check is
that it distinguishes "the door is shut" from "I could not see the door", so
that is what these assert. A test that needed the network could not test the
network-failure case, which is the case most likely to be got wrong.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "scripts", "check-worker-exposure.py")

spec = importlib.util.spec_from_file_location("cwe", SRC)
cwe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cwe)

passed = failed = 0


def ok(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("ok    %s" % label)
    else:
        failed += 1
        print("FAIL  %s" % label)


def wd(status, body="", error=None):
    return cwe.classify_workers_dev(status, body, error)[0]


def hn(status, location=None, error=None):
    return cwe.classify_hostname(status, location, error)[0]


print("-" * 67)
print("workers.dev: is the back door shut")
print("-" * 67)

ok(wd(404, "error code: 1042") == cwe.CLOSED,
   "1042 in the body is the edge refusing, so CLOSED")
ok(wd(200, "<!doctype html><html>the deck</html>") == cwe.OPEN,
   "200 with content means the Worker is answering, so OPEN")
ok(wd(302, "") == cwe.OPEN,
   "a redirect still means the Worker is live on this URL")

# The distinction the whole file exists for.
ok(wd(404, "Not Found") == cwe.UNKNOWN,
   "404 WITHOUT 1042 is ambiguous: edge or Worker, cannot tell")
ok(wd(404, "error code: 1042") != wd(404, "Not Found"),
   "...and those two 404s must not classify the same")

print()
print("-" * 67)
print("workers.dev: a failure to look is never a pass")
print("-" * 67)

ok(wd(None, "", "URLError: timed out") == cwe.UNKNOWN,
   "a timeout is UNKNOWN, never CLOSED")
ok(wd(None, "", "gaierror: no such host") == cwe.UNKNOWN,
   "DNS failure is UNKNOWN, never CLOSED")
ok(wd(None, "", "SSLCertVerificationError") == cwe.UNKNOWN,
   "a TLS failure is UNKNOWN, never CLOSED")
ok(wd(200, "anything", "some error") == cwe.UNKNOWN,
   "an error wins over a status code that arrived alongside it")
ok(wd(None) == cwe.UNKNOWN,
   "no status and no error is UNKNOWN rather than an exception")
ok(wd(503, "") == cwe.UNKNOWN,
   "a 5xx says nothing about the route, so UNKNOWN")

print()
print("-" * 67)
print("hostname: is Access actually in front")
print("-" * 67)

ok(hn(302, "https://doug-kasperek.cloudflareaccess.com/cdn-cgi/access/login")
   == cwe.PROTECTED,
   "302 to the Access login is PROTECTED")
ok(hn(200, None) == cwe.UNPROTECTED,
   "200 means content served to anybody, so UNPROTECTED")
ok(hn(302, "https://example.com/somewhere-else") == cwe.UNKNOWN,
   "a redirect somewhere that is NOT Access is UNKNOWN, not PROTECTED")
ok(hn(302, None) == cwe.UNKNOWN,
   "a redirect with no Location is UNKNOWN")
ok(hn(None, None, "URLError: timed out") == cwe.UNKNOWN,
   "a timeout on the hostname is UNKNOWN, never PROTECTED")
ok(hn(404, None) == cwe.UNKNOWN,
   "404 on the hostname is unrecognised, so UNKNOWN")

print()
print("-" * 67)
print("the target map")
print("-" * 67)

ok(len(cwe.WORKERS) == 5,
   "all five Workers on the account are covered")
ok("[removed]" in cwe.WORKERS,
   "[removed] is covered: it is the one with no config pinning its toggle")
ok("[removed]" in cwe.WORKERS,
   "[removed] is covered: its /api/save trusts a client-suppliable header")
ok(all("." in h for h in cwe.WORKERS.values()),
   "every Worker maps to a real hostname")
ok(cwe.SUBDOMAIN.endswith(".workers.dev"),
   "the subdomain is a workers.dev subdomain")

# Not an assertion about a count of Workers, which is the kind of thing this
# repo has broken three tests on. It asserts the PROPERTY: every Worker named
# in the map is checked on both halves of the perimeter.
ok(cwe.CLOSED != cwe.UNKNOWN and cwe.PROTECTED != cwe.UNKNOWN,
   "CLOSED and PROTECTED are distinct from UNKNOWN")

print()
print("-" * 67)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
