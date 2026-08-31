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

# NOT `len(cwe.WORKERS) == 5`, which is what this said until 2026-08-31. That
# is the fleet-count anti-pattern CLAUDE.md warns about, and it broke the day
# the map was correctly narrowed. Assert the property: this repo owns cm-fleet
# and checks cm-fleet.
ok("cm-fleet" in cwe.WORKERS,
   "cm-fleet is covered: it is the Worker this repo owns")

# The map was narrowed when the repo moved to the clevermethod org. Unrelated
# Workers on the same account are not this project's to check, and after the
# Cloudflare migration they are not even in the same account. This asserts the
# narrowing holds, so re-adding one is a red test rather than a quiet leak of
# what else exists.
ok(not (set(cwe.WORKERS) - {"cm-fleet"}),
   "the map holds no Worker this repo does not own")

# A single target cannot produce a collision, so shared_access_apps() returns
# {} -- which reads identically to "checked, and clean". main() must say the
# check was INAPPLICABLE instead of printing it as a pass. Verified to fail by
# deleting the guard.
ok(cwe.shared_access_apps([{"hostname": "fleet.thudstaff.com",
                            "access_app": "a7da487e"}]) == {},
   "one target yields no collision, which is why a bare pass would mislead")
_cwe_src = open(os.path.join(HERE, "..", "scripts",
                             "check-worker-exposure.py")).read()
ok("len(rows) < 2" in _cwe_src and "inapplicable" in _cwe_src,
   "main() declares the shared-application check inapplicable, not passed")
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
print("portability and the negative control")
print("-" * 67)

ok(hasattr(cwe, "CONTROL_NAME") and cwe.CONTROL_NAME not in cwe.WORKERS,
   "the negative control name is not a real Worker")
ok(cwe.classify_workers_dev(200, "anything", None)[0] == cwe.OPEN,
   "a control that SERVES means the harness is reaching something it should not")
ok(cwe.classify_workers_dev(404, "error code: 1042", None)[0] == cwe.CLOSED,
   "a control that is refused is the healthy case")

# The trap this override exists to close: the built-in subdomain is tied to one
# Cloudflare account and WILL be wrong after the clevermethod migration. A wrong
# subdomain makes every real Worker look absent, which would otherwise print as
# a clean bill of health.
src = open(SRC).read()
ok("--subdomain" in src and "WORKER_SUBDOMAIN" in src,
   "the subdomain is overridable by flag and by environment")
ok("--targets" in src,
   "the worker/hostname map is overridable, so this runs on any account")
ok("global SUBDOMAIN" in src,
   "the override actually rebinds the module constant rather than being ignored")

print()
print("-" * 67)
print("Access application separation")
print("-" * 67)

A = "https://x.cloudflareaccess.com/cdn-cgi/access/login/h?kid=" + "a" * 64
B = "https://x.cloudflareaccess.com/cdn-cgi/access/login/h?kid=" + "b" * 64

ok(cwe.access_app_id(A) == "a" * 64, "the application tag is read out of kid=")
ok(cwe.access_app_id("https://x/?aud=" + "c" * 32) == "c" * 32,
   "aud= is accepted as well as kid=")
ok(cwe.access_app_id(None) is None, "no Location yields no tag")
ok(cwe.access_app_id("https://x.cloudflareaccess.com/nothing/here") is None,
   "a redirect with no tag yields None rather than a guess")
ok(cwe.access_app_id("https://x/?kid=short") is None,
   "a too-short value is not accepted as a tag")

def rows(*pairs):
    return [{"hostname": h, "access_app": a} for h, a in pairs]

ok(cwe.shared_access_apps(rows(("fleet.x", "a" * 64), ("cm.x", "b" * 64))) == {},
   "two hostnames on DIFFERENT applications do not collide")
shared = cwe.shared_access_apps(rows(("fleet.x", "a" * 64), ("cm.x", "a" * 64)))
ok(list(shared) == ["a" * 64] and sorted(shared["a" * 64]) == ["cm.x", "fleet.x"],
   "two hostnames on the SAME application are reported together")

# The one that would quietly ruin the check: two unreadable tags are not a
# match. Folding None into None would report a shared policy that is not there,
# and worse, would hide that nothing was actually established.
ok(cwe.shared_access_apps(rows(("a.x", None), ("b.x", None))) == {},
   "two UNREADABLE tags do not collide with each other")
ok(cwe.shared_access_apps(rows(("a.x", None), ("b.x", "a" * 64))) == {},
   "an unreadable tag never matches a readable one")

src = open(SRC).read()
ok("--allow-shared-access-app" in src,
   "sharing can be allowed explicitly, since it is an assumption about this account")
ok("access_app" in src and "shared_access_apps" in src,
   "the collision check is wired into the run, not just defined")


# ---------------------------------------------------------------------------
# EVERY PAGE THE PUBLISHER UPLOADS MUST HAVE A ROUTE THAT SERVES IT.
#
# Added 2026-08-27, the day the consent page shipped uploaded and unreachable.
# publish-dashboard.sh put fleet/consent.html into R2, the fleet page linked to
# /consent, and the Worker 404'd it. The test written that day asserted the
# UPLOAD and not the ROUTE, which is half a contract.
#
# A page in R2 that no route serves is invisible, and it looks exactly like a
# page that was never rendered -- so nothing complains and nobody can tell the
# difference from the outside.
# ---------------------------------------------------------------------------
print()
print("-- every published page is reachable --")
import re as _re_route
_pub_src = open(os.path.join(HERE, "..", "scripts", "publish-dashboard.sh")).read()
_wrk_src = open(os.path.join(HERE, "..", "ci", "cloudflare", "cm-fleet-worker.js")).read()

# The upload loop names each object as "<name>:<content-type>".
_uploaded = _re_route.findall(r'"([a-z0-9-]+\.html):text/html"', _pub_src)
ok(len(_uploaded) >= 2,
   "the publisher uploads more than one page (found %s)" % (_uploaded or "none"))
for _name in _uploaded:
    _key = 'PREFIX + "%s"' % _name
    ok(_key in _wrk_src,
       "the Worker serves %s, which the publisher uploads" % _name)

# And the reverse: a route pointing at an object nobody uploads is a 404 with
# extra steps, and it reads as a page that exists.
_served = _re_route.findall(r'PREFIX \+ "([a-z0-9-]+\.html)"', _wrk_src)
for _name in set(_served):
    ok(_name in _uploaded,
       "the publisher uploads %s, which the Worker serves" % _name)

# THE ROUTE FILE IS NOT THE DEPLOYED WORKER. This asserts the source is
# correct; it cannot assert what is running. CLAUDE.md, and an audit on
# 2026-08-20 that found the deployed Worker a full day behind this file.
ok("wrangler deploy" in _wrk_src,
   "the source says out loud that editing it changes nothing until deploy")

print()
print("-" * 67)
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
