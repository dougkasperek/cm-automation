#!/usr/bin/env python3
"""Is any Worker on this account reachable without Cloudflare Access?

WHY THIS EXISTS
---------------
Cloudflare Access cannot protect a `*.workers.dev` URL. Access applications
attach to hostnames in a zone you control, and workers.dev is not one. So a
Worker sitting behind Access on its custom domain is still served,
unauthenticated, on its workers.dev URL to anyone who knows it.

That is not hypothetical here. On 2026-07-28 `[removed]` served its client list,
staff emails and pricing publicly from a workers.dev URL nobody knew was on.

Four of the five Workers pin `workers_dev = false` in a config. `[removed]` does
not and deliberately cannot: it is dashboard-managed, its bindings and secrets
live on the Worker, and a config declaring an incomplete set would drop one on
the next deploy. Its toggle is held by nothing but a manual click in the
dashboard.

So this is DETECTION, not prevention. You cannot pin a dashboard-managed
Worker from a repo. You can notice within minutes when it opens.

It matters most for `[removed]` and `[removed]`, because neither has authentication
of its own worth the name. `[removed]` gates `analytics.html` and `/api/stats` on
`Cf-Access-Authenticated-User-Email` starting with "doug", and `/api/harvest`
and `/api/asana` check nothing. That header is trustworthy ONLY while Access is
the sole route in. On a workers.dev URL the client simply sends it.

WHAT IT CHECKS
--------------
Both halves of the perimeter, because either one failing is an exposure:

  1. Every workers.dev URL must NOT serve the Worker.
  2. Every custom hostname must redirect to an Access login.

Needs no credentials. It is an outside-in check by design: it sees what an
anonymous visitor sees, which is the only view that answers the question.

  ./scripts/check-worker-exposure.py
  ./scripts/check-worker-exposure.py --json

Exit 0 clear, 1 EXPOSED, 2 could not determine. See the note on exit 2.

WHAT THIS CANNOT CATCH
----------------------
One case, stated plainly rather than left for someone to discover. If
SUBDOMAIN is set to a workers.dev subdomain that RESOLVES but belongs to a
different account, every Worker name here is absent there, every lookup
returns 1042, and the run prints a clean bill of health for an account it
never touched. The negative control does not help: a wrong-but-real subdomain
refuses the control too.

A subdomain that does not resolve at all IS caught, as a DNS failure, which
classifies UNKNOWN rather than CLOSED.

So the residual risk is a plausible typo, not a random one. After the
clevermethod migration, confirm the new subdomain against the Cloudflare
dashboard once, by hand. Nothing in here can do it for you.
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

# The account's workers.dev subdomain. This CHANGES if the Workers move to the
# clevermethod, Inc. account, and a stale value here would make every check
# return "no such Worker", which this file would otherwise read as good news.
# That is why an all-1042 result is not enough on its own -- see `--json` output
# and the sanity note in main().
SUBDOMAIN = "doug-kasperek.workers.dev"

# A script name that must NOT exist. It is the negative control: if a made-up
# name answers with anything other than the same refusal the real Workers give,
# then this harness is not reaching Cloudflare's workers.dev edge at all and no
# verdict below can be trusted. A captive portal, a corporate proxy or a DNS
# wildcard that answers everything would otherwise produce a page of CLOSED and
# read as good news.
CONTROL_NAME = "cm-automation-negative-control-do-not-create"

# Worker script name -> the custom hostname it is meant to be reached on.
# Adding a Worker to this account means adding it here. A Worker absent from
# this map is not checked, and nothing will tell you.
WORKERS = {
    "[removed]":       "[removed]",
    "[removed]":       "[removed]",
    "cm-fleet":      "fleet.thudstaff.com",
    "[removed]":        "[removed]",
    "[removed]": "[removed]",
}

TIMEOUT = 15
ATTEMPTS = 2          # one transient blip should not turn into a red build

# Verdicts. UNKNOWN is a first-class value and is NEVER folded into a pass.
CLOSED, OPEN, UNKNOWN = "CLOSED", "OPEN", "UNKNOWN"
PROTECTED, UNPROTECTED = "PROTECTED", "UNPROTECTED"

ACCESS_HOST = "cloudflareaccess.com"


def fetch(url):
    """Return (status, body_prefix, location, error).

    `error` is not None when the request never completed. A request that never
    completed tells us NOTHING about whether the door is open, and the callers
    below must not treat it as though it did. That distinction is the whole
    reason this function returns four things instead of raising.
    """
    req = urllib.request.Request(url, headers={
        # Identify honestly. This check has no reason to look like a browser.
        "User-Agent": "cm-automation/check-worker-exposure (read-only)",
    })
    # Do not follow the redirect: the redirect ITSELF is the evidence we want.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect,
                                         urllib.request.HTTPSHandler(
                                             context=ssl.create_default_context()))
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.status, r.read(400).decode("utf-8", "replace"), \
                   r.headers.get("Location"), None
    except urllib.error.HTTPError as e:            # 4xx/5xx are ANSWERS, not errors
        body = ""
        try:
            body = e.read(400).decode("utf-8", "replace")
        except Exception:                          # noqa: BLE001 - body is optional
            pass
        return e.code, body, e.headers.get("Location"), None
    except Exception as e:                         # noqa: BLE001 - reported, never swallowed
        return None, "", None, "%s: %s" % (type(e).__name__, e)


def classify_workers_dev(status, body, error):
    """Does this workers.dev URL serve the Worker?

    Cloudflare answers a DISABLED workers.dev route with HTTP 404 and a short
    `error code: 1042` body of its own. That is the edge speaking, not the
    Worker. The distinction matters: a Worker that is live and happens to
    return 404 for `/` looks identical on the status line alone, and reading
    one as the other is exactly how "the back door is closed" gets written
    down about a door that is open.
    """
    if error:
        return UNKNOWN, error
    if status is None:
        return UNKNOWN, "no response and no error, which should be impossible"
    if "error code: 1042" in body:
        return CLOSED, "1042, the route is disabled at the edge"
    if status == 404:
        # 404 without 1042 is ambiguous on purpose. It may be Cloudflare using
        # a different code, or it may be the Worker itself answering, which
        # would mean the route is LIVE.
        return UNKNOWN, "404 but no 1042 body; cannot tell edge from Worker"
    if 200 <= status < 400:
        return OPEN, "HTTP %d, the Worker is answering here" % status
    return UNKNOWN, "HTTP %d, unrecognised" % status


def classify_hostname(status, location, error):
    """Is Access actually in front of this hostname?

    An unauthenticated request must be bounced to the Access login. A 200 means
    the page is being served to anybody.
    """
    if error:
        return UNKNOWN, error
    if status is None:
        return UNKNOWN, "no response and no error, which should be impossible"
    loc = location or ""
    if status in (301, 302, 303, 307, 308):
        if ACCESS_HOST in loc:
            return PROTECTED, "302 to the Access login"
        return UNKNOWN, "redirects, but not to Access: %s" % (loc[:80] or "no Location")
    if 200 <= status < 300:
        return UNPROTECTED, "HTTP %d, content served with no Access challenge" % status
    return UNKNOWN, "HTTP %d, unrecognised" % status


def probe(url, classifier):
    """Fetch with one retry, so a single blip is not a finding.

    Retries only on UNKNOWN. A definite OPEN is not retried away.
    """
    verdict = detail = None
    for _ in range(ATTEMPTS):
        status, body, location, error = fetch(url)
        if classifier is classify_workers_dev:
            verdict, detail = classify_workers_dev(status, body, error)
        else:
            verdict, detail = classify_hostname(status, location, error)
        if verdict not in (UNKNOWN,):
            break
    return verdict, detail


def run():
    rows = []
    for name, host in sorted(WORKERS.items()):
        wd_url = "https://%s.%s/" % (name, SUBDOMAIN)
        hv, hd = probe("https://%s/" % host, classify_hostname)
        wv, wd = probe(wd_url, classify_workers_dev)
        rows.append({
            "worker": name,
            "workers_dev_url": wd_url,
            "workers_dev": wv, "workers_dev_detail": wd,
            "hostname": host,
            "access": hv, "access_detail": hd,
        })
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--subdomain", default=os.environ.get("WORKER_SUBDOMAIN"),
                   help="workers.dev subdomain to test against. Overrides the "
                        "built-in default, which is tied to one account and "
                        "WILL be wrong after a migration. Also read from "
                        "$WORKER_SUBDOMAIN.")
    p.add_argument("--targets",
                   help="path to a JSON object of {worker: hostname} to check "
                        "instead of the built-in map. Lets this run against "
                        "any account without editing the script.")
    a = p.parse_args()

    global SUBDOMAIN, WORKERS
    if a.subdomain:
        SUBDOMAIN = a.subdomain.strip().lstrip(".")
    if a.targets:
        with open(a.targets) as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict) or not loaded:
            print("--targets must be a non-empty JSON object of "
                  "{worker: hostname}", file=sys.stderr)
            return 2
        WORKERS = loaded

    # The control runs FIRST. If the harness cannot be trusted, the per-Worker
    # verdicts are noise and printing them would be worse than printing nothing.
    cv, cd = probe("https://%s.%s/" % (CONTROL_NAME, SUBDOMAIN),
                   classify_workers_dev)
    if cv == OPEN:
        print("HARNESS UNTRUSTWORTHY: a Worker name that cannot exist is being "
              "served at\n  https://%s.%s/\n  (%s)\n"
              % (CONTROL_NAME, SUBDOMAIN, cd))
        print("  Something between here and Cloudflare is answering every "
              "request.\n  Every verdict this script could print would be "
              "meaningless, so it printed none.")
        return 2

    rows = run()
    exposed = [r for r in rows
               if r["workers_dev"] == OPEN or r["access"] == UNPROTECTED]
    unknown = [r for r in rows
               if r["workers_dev"] == UNKNOWN or r["access"] == UNKNOWN]

    if a.json:
        print(json.dumps({"subdomain": SUBDOMAIN,
                          "negative_control": {"verdict": cv, "detail": cd},
                          "results": rows,
                          "exposed": len(exposed), "unknown": len(unknown)},
                         indent=2))
    else:
        print("Checking %d Worker(s) on %s\n" % (len(rows), SUBDOMAIN))
        for r in rows:
            print("  %-14s  %-30s  workers.dev %-8s  access %s"
                  % (r["worker"], r["hostname"], r["workers_dev"], r["access"]))
            if r["workers_dev"] != CLOSED:
                print("       workers.dev: %s" % r["workers_dev_detail"])
            if r["access"] != PROTECTED:
                print("       access:      %s" % r["access_detail"])
        print()

    if exposed:
        print("EXPOSED: %d Worker(s) reachable without Access.\n" % len(exposed))
        for r in exposed:
            if r["workers_dev"] == OPEN:
                print("  %s is being served at %s" % (r["worker"], r["workers_dev_url"]))
                print("  Turn it off: Workers & Pages -> %s -> Domains,"
                      % r["worker"])
                print("  set Production AND Preview to off.")
            if r["access"] == UNPROTECTED:
                print("  %s serves content with no Access challenge."
                      % r["hostname"])
        return 1

    if unknown:
        # Deliberately not exit 0. A check that could not see must never report
        # success -- that is the single bug this repo keeps making, and a
        # security check is the worst place to make it.
        print("COULD NOT DETERMINE for %d Worker(s). This is not a pass.\n"
              % len(unknown))
        print("  Most likely a transient network failure, in which case re-run.")
        print("  If it persists, check the subdomain is still correct:")
        print("    %s" % SUBDOMAIN)
        print("  A subdomain that does not resolve lands here, which is the")
        print("  safe outcome. A subdomain that resolves but belongs to another")
        print("  account would instead print CLEAR, and nothing here can tell.")
        return 2

    print("Clear. No Worker is reachable without Access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
