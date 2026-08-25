#!/usr/bin/env python3
"""
fleet-nexcess.py - read-only Nexcess control-plane discovery.

Phase 1 of docs/NEXCESS-ARCHITECTURE.md. 21 clevermethod sites are on Nexcess
and no scan of any kind has ever reached them: they are most of the dashboard's
UNKNOWN count, and every blank cell in the audit workbook's
`wp2shell Security Flaw Remedied?` column is one of them.

WHAT THIS IS NOT
----------------
It is not the SSH deep scan. It asks the hosting control plane what it believes
about each site. That is weaker evidence than `wp core version` read off the
filesystem, and the ledger stores it under its own `nexcess_*` fact names for
exactly that reason -- so that when Phase 2 (read-only SSH) lands, a
disagreement between the two shows up as a finding instead of one silently
overwriting the other.

READ-ONLY, ENFORCED HERE
------------------------
Only GET is ever issued. The Nexcess API has write endpoints (site:add,
change-php-version, purge-caches) and this tool must never reach them, so the
request helper refuses any method other than GET rather than relying on nobody
passing one. cm-automation does not change client sites.

THE BASE URL, AND THE CLOUDFLARE CHALLENGE
-----------------------------------------
The vendor's own API docs write every example against `$PORTAL_API_URL` and
never say what it resolves to. Established 2026-08-19 by watching the portal
SPA's own traffic:

    https://portal.nexcess.net/api

That host answers a browser with JSON and answers this client with a
Cloudflare managed challenge, so the token is never read. That is the open
problem, and it is a Nexcess support question, not a URL question.

`probe` judges the RESPONSE BODY, not the status code. That is a correction:
the first version called a 200 "ok, site list returned" without looking, the
body was a web page, and `discover` crashed on it. A status code is not an
answer.

Subcommands
  probe      which base URL actually answers, and does the token work
  discover   GET /v1/site (+ /v1/site/{id}) -> reports/fleet-nexcess-<stamp>.json
  report     read a scan file back and print the findings

Usage
  export NEXCESS_PORTAL_API_TOKEN=...
  ./scripts/fleet-nexcess.py probe
  ./scripts/fleet-nexcess.py discover \\
      --inventory data/fleet-inventory.json --out reports \\
      --stamp "$(date -u +%Y-%m-%d_%H%M)"
  ./scripts/fleet-nexcess.py report --scan reports/fleet-nexcess-*.json
"""

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UNKNOWN = "unknown"

# THE API BASE URL, ESTABLISHED 2026-08-19:
#
#     https://portal.nexcess.net/api
#
# Not from documentation -- no Nexcess page anywhere defines $PORTAL_API_URL.
# Established by watching what the portal's own single-page app calls:
# `/api/v1/user/self` and `/api/v1/client/self` on that host. Confirmed by
# requesting `https://portal.nexcess.net/api/v1/site` in a browser, which
# returns `{"message":"Unauthorized"}` -- JSON from the application, not a
# challenge page and not a 404.
#
# THE REMAINING BLOCKER IS NOT THE URL. The same host serves a Cloudflare
# managed challenge ("Just a moment...") to this Python client while answering
# a browser normally, so the request never reaches the application and the
# token is never read. See `looks_like_challenge`.
#
# The earlier probe runs, for the record, because two of them were misread:
#   sites-portal.nexcess.com/api   200 with the SPA's HTML. Catch-all route.
#                                  Reported as "ok, site list returned" on the
#                                  status code alone. It was the web UI.
#   portal.nexcess.net/api         403 Cloudflare challenge. Reported as "token
#                                  rejected". The token was never read.
#   api.nexcess.net                does not resolve.
#
# There is still deliberately no default-constant wired into `discover`. The
# base URL being known does not make guessing safe, and `probe` costs one
# request.
CANDIDATE_BASES = (
    # Established. Ordered first so a re-probe is one request in the good case.
    "https://portal.nexcess.net/api",
    "https://portal.nexcess.net",
    # The portal web UI, not the API. Kept so that a future reader who wonders
    # about it finds the answer in the probe output rather than re-deriving it.
    "https://sites-portal.nexcess.com/api",
    # Does not resolve. One DNS lookup per probe to notice if that changes.
    "https://api.nexcess.net",
)

# Identifies the client honestly by default. Overridable with --user-agent
# because Nexcess's own edge served a bot challenge to this string on an
# endpoint their documentation tells customers to call programmatically. That
# is a misclassification of a legitimate token-authenticated client, and trying
# a conventional UA is a diagnostic: if a plain browser string gets through,
# the finding is "their WAF fingerprints on User-Agent", which is a concrete
# thing to tell support. If the challenge persists, no amount of header-fiddling
# is the answer and the question goes to Nexcess.
USER_AGENT = "cm-automation/fleet-nexcess (read-only)"

# A conventional desktop UA, offered as `--user-agent browser` so nobody has to
# paste one in. Not the default: this tool should say what it is.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 "
              "Safari/537.36")
TIMEOUT = 30
PAGE_SIZE = 100

# Ceiling on pagination. The site count is 21 today; 50 pages of 100 is three
# orders of magnitude of headroom and still terminates if the API ignores the
# page parameter and returns page 1 forever, which is a real failure mode for
# an endpoint whose pagination behaviour the vendor docs list under "verify
# before production".
MAX_PAGES = 50


def _ssl_context():
    """A verifying SSL context, using certifi's CA bundle when it is available.

    There is deliberately no way to turn verification off. The failure this
    handles is a macOS one: a python.org build ships its own trust store and
    does NOT read the system keychain, so every HTTPS call fails with
    CERTIFICATE_VERIFY_FAILED until `Install Certificates.command` has been
    run. certifi, if present, is a correct CA bundle and fixes it properly.
    Disabling verification would also "fix" it, by turning a credentialed
    call to a hosting control plane into an unauthenticated one. Not an option.
    """
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    # THIS LINE IS WHY THE "BOT CHALLENGE" HAPPENED. Isolated 2026-08-25.
    #
    # `http.client._create_https_context()` sets `post_handshake_auth = True`
    # on the context it builds for you. A context built by hand does NOT, and
    # that flag changes the TLS 1.3 ClientHello. Cloudflare fingerprints on the
    # ClientHello, and a hello with no post-handshake-auth extension does not
    # look like any browser, so it is challenged.
    #
    # Measured, same machine, same second, same headers, same invalid token:
    #
    #   context=None (urllib builds its own)   -> 401 {"message":"Unauthorized"}
    #   create_default_context(), by hand      -> 403 cf-mitigated: challenge
    #   ...with post_handshake_auth = True     -> 401 {"message":"Unauthorized"}
    #   ...with ALPN set but no PHA            -> 403, so ALPN is NOT the factor
    #
    # So the challenge was OURS. Supplying a context to fix macOS certificate
    # verification silently dropped a flag urllib would have set, and the tool
    # then reported the consequence as a vendor blocking us. Five days of
    # support tickets came from this line.
    #
    # Do not "simplify" this away by dropping the context: a python.org build
    # ships its own trust store and every HTTPS call fails without certifi.
    # Both things have to be true at once.
    if ctx.post_handshake_auth is not None:
        ctx.post_handshake_auth = True
    return ctx


def classify_error(exc):
    """(verdict, detail) for a failed request.

    These are four different problems with four different fixes, and the first
    version of this tool printed "unreachable" for all of them. That is the
    same mistake the rest of this repo is a list of: a single confident-looking
    word standing in for causes that are not the same. Doug's first real probe
    run hit exactly this -- a local trust-store problem was reported as though
    Nexcess were down.

    Note what a TLS verification failure PROVES: DNS resolved and the server
    presented a certificate. The host exists and is listening. That is a
    stronger result than "unreachable", not a weaker one.
    """
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    if isinstance(reason, ssl.SSLCertVerificationError) or \
            "CERTIFICATE_VERIFY_FAILED" in text:
        return ("tls-untrusted",
                "host exists and served a certificate; THIS machine could not "
                "verify it")
    if isinstance(reason, socket.gaierror) or \
            "nodename nor servname" in text or \
            "Name or service not known" in text or \
            "Temporary failure in name resolution" in text:
        return ("dns-unknown", "no such host")
    if isinstance(reason, socket.timeout) or "timed out" in text:
        return ("timeout", "host did not answer in %ds" % TIMEOUT)
    if isinstance(reason, ConnectionRefusedError) or "refused" in text:
        return ("refused", "host answered and closed the connection")
    return ("unreachable", "%s: %s" % (type(exc).__name__, exc))


# Verdicts that mean the HOST is real, whatever else went wrong. Used to tell
# "we are asking the wrong server" apart from "this laptop cannot talk to it".
HOST_EXISTS = ("ok", "unauthorised", "forbidden", "wrong-path", "unexpected",
               "tls-untrusted", "refused", "not-api", "not-json",
               "json-unexpected", "bot-challenge")


class ApiError(Exception):
    def __init__(self, status, url, body):
        self.status = status
        self.url = url
        self.body = body
        Exception.__init__(self, "%s %s: %s" % (status, url, body[:300]))


def _request_full(base, path, token, params=None, method="GET"):
    """Issue one GET. Returns (status, parsed_json_or_None, raw_text, content_type).

    Refuses any other method. This tool has no write path and adding one is a
    product decision, not something a caller should be able to do by passing an
    argument.

    `parsed` is None when the body is not JSON, and the raw text is returned
    alongside rather than discarded. That separation exists because probe
    reported `ok` on an HTTP 200 whose body was a web page: a status code is
    not an answer, and a caller that cannot tell "JSON I could not parse" from
    "no JSON at all" will keep making that mistake.
    """
    if method != "GET":
        raise ValueError(
            "fleet-nexcess.py issues GET only; %r was requested" % method)
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", _user_agent())
    ctx = _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            raw = r.read().decode("utf-8", "replace")
            # getcode(), not .status: .status on the response object is 3.9+ and
            # this repo builds against py3.6-compatible source throughout.
            status = r.getcode()
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
    try:
        return status, json.loads(raw), raw, ctype
    except ValueError:
        return status, None, raw, ctype


def _request(base, path, token, params=None, method="GET"):
    """(status, parsed_json_or_text). Thin wrapper; see _request_full."""
    status, parsed, raw, _ctype = _request_full(base, path, token, params, method)
    return status, (raw if parsed is None else parsed)


def looks_like_site_list(parsed):
    """Is this actually a list of sites, or merely valid JSON?

    The vendor documents the site list as a bare array; a `data`-wrapped
    envelope is the other common shape. Anything else is JSON that came from
    somewhere, and calling it a site list because it arrived with a 200 is how
    probe declared success against a web page.
    """
    if isinstance(parsed, list):
        return True
    if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
        return True
    return False


def _snippet(raw, n=110):
    """First non-blank line of a body, for showing WHY a verdict was reached."""
    if not raw:
        return ""
    line = " ".join(raw.split())
    return line[:n] + ("..." if len(line) > n else "")


# Fingerprints of an edge challenge page. Cloudflare's managed challenge is the
# one seen in the wild here; the others are included because the failure mode
# is identical and the remedy is the same conversation with the vendor.
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "checking your browser",
    "__cf_chl",
    "cf-please-wait",
    "attention required! | cloudflare",
    "access denied | ",
)


def looks_like_challenge(raw):
    """Is this body an edge bot-challenge page rather than an API response?

    This matters because it changes WHO can fix it. A 403 carrying a challenge
    page means the request never reached the application: the token was never
    read, so it cannot have been rejected. Reporting it as a credentials
    problem sends someone to rotate a token that was fine.
    """
    if not raw:
        return False
    low = raw[:4000].lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def classify_response(status, parsed, raw, ctype):
    """(verdict, detail) for a response that arrived.

    Pure function of the response, so the reasoning is testable and so that a
    verdict can never again be reached from the status code alone.
    """
    body = _snippet(raw)
    # FIRST, before any status branch. A challenge can arrive with 200, 403 or
    # 503, and what it means -- the request never reached the application --
    # does not change with the status. Checking it after the 200 branch made a
    # 200-wrapped challenge report as "not the API", which is true but names
    # the wrong problem.
    if looks_like_challenge(raw):
        return ("bot-challenge",
                "HTTP %s from an edge bot challenge. The request never reached "
                "the application, so the token was never read: %s"
                % (status, body))
    if status == 200:
        if looks_like_site_list(parsed):
            n = len(parsed) if isinstance(parsed, list) else len(parsed["data"])
            return ("ok", "site list returned (%d entries on this page)" % n)
        if parsed is not None:
            return ("json-unexpected",
                    "200 and valid JSON, but not a site list: %s" % body)
        if "html" in (ctype or "").lower() or body.lstrip()[:1] == "<":
            return ("not-api",
                    "200 with a WEB PAGE, not JSON. This is the portal UI, not "
                    "the API: %s" % body)
        return ("not-json", "200 with a body that is not JSON: %s" % body)
    if status == 401:
        return ("unauthorised", "token rejected by the application: %s" % body)
    if status == 403:
        # Not "token lacks permission". That was asserted once without reading
        # the body and it was wrong: the body was a Cloudflare challenge.
        return ("forbidden", "403 from the application: %s" % body)
    if status == 404:
        return ("wrong-path", "host answers, this path is not there")
    return ("unexpected", "HTTP %s: %s" % (status, body))


# Set once by the CLI. A module global rather than a threaded parameter
# because every call site is one process making one run's worth of requests,
# and threading it through four functions to support a diagnostic flag is a
# worse trade than this comment.
_UA_OVERRIDE = [None]


def _user_agent():
    return _UA_OVERRIDE[0] or USER_AGENT


def _set_user_agent(value):
    if value == "browser":
        _UA_OVERRIDE[0] = BROWSER_UA
    elif value:
        _UA_OVERRIDE[0] = value


def _token(required=True):
    tok = os.environ.get("NEXCESS_PORTAL_API_TOKEN", "").strip()
    if not tok and required:
        raise SystemExit(
            "NEXCESS_PORTAL_API_TOKEN is not set.\n"
            "Generate one at the Nexcess client portal under User Menu -> API\n"
            "Tokens. Export it in your shell for a local run; in CI it comes\n"
            "from GitHub Actions secrets. It is never written to this repo.")
    return tok


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def probe(token, bases=CANDIDATE_BASES):
    """Which base URL answers, and does the token authenticate?

    Reports four distinct outcomes and never collapses them. `unreachable` and
    `unauthorised` are very different problems and a tool that prints "failed"
    for both sends you looking in the wrong place.
    """
    out = []
    for base in bases:
        rec = {"base": base, "verdict": UNKNOWN, "status": None, "detail": None,
               "content_type": None}
        try:
            status, parsed, raw, ctype = _request_full(
                base, "/v1/site", token, {"page": 1, "pageSize": 1})
            rec["status"] = status
            rec["content_type"] = ctype
            rec["verdict"], rec["detail"] = classify_response(
                status, parsed, raw, ctype)
        except Exception as e:                       # noqa: BLE001 - reported
            rec["verdict"], rec["detail"] = classify_error(e)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------

def dig(obj, *path):
    """Nested lookup returning None rather than raising or defaulting.

    Every field name below comes from vendor documentation that this codebase
    has never executed against. A missing field must read as "the API did not
    tell us", never as a value, so nothing here has a default.
    """
    cur = obj
    for k in path:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int) and k < len(cur):
            cur = cur[k]
        else:
            return None
        if cur is None:
            return None
    return cur


def _first(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None


def _app_name(raw):
    """`app` has been documented as both a string and an object. Take either."""
    if isinstance(raw, str):
        return raw.lower()
    if isinstance(raw, dict):
        v = _first(raw.get("name"), raw.get("type"), raw.get("identity"))
        return v.lower() if isinstance(v, str) else None
    return None


def list_sites(base, token):
    """Every site the token can see, following pagination."""
    sites, page = [], 1
    while page <= MAX_PAGES:
        status, body = _request(base, "/v1/site", token,
                                {"page": page, "pageSize": PAGE_SIZE})
        if status != 200:
            raise ApiError(status, base + "/v1/site",
                           body if isinstance(body, str) else json.dumps(body)[:400])
        if not looks_like_site_list(body):
            # A 200 whose body is not a site list. This crashed with
            # AttributeError on 2026-08-19 because the code assumed a 200 meant
            # JSON; the body was the portal's HTML. Raise something that names
            # the problem instead of a traceback that names a symptom.
            raise ApiError(
                status, base + "/v1/site",
                "HTTP 200 but the body is not a site list. This base URL is "
                "probably the portal UI rather than the API. First bytes: %s"
                % _snippet(body if isinstance(body, str) else json.dumps(body)))
        batch = body if isinstance(body, list) else body["data"]
        if not batch:
            break
        sites.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    else:
        # Fell out of the while by exhausting MAX_PAGES, which means the API
        # kept returning full pages. Say so; do not return a silently
        # truncated estate that would read as the whole estate.
        raise ApiError(0, base + "/v1/site",
                       "pagination did not terminate after %d pages of %d; "
                       "refusing to report a truncated estate as complete"
                       % (MAX_PAGES, PAGE_SIZE))
    return sites


def normalise(listing, detail):
    """One site record from the list entry plus (optionally) the detail call."""
    d = detail or {}
    env = None
    if listing.get("is_dev_account") is True:
        env = "dev"
    elif listing.get("is_staging_account") is True:
        env = "staging"
    elif listing.get("is_dev_account") is False and \
            listing.get("is_staging_account") is False:
        env = "production"
    # env stays None when the API reports neither flag. "production" is the
    # tempting default and it is wrong: it would be a confident value standing
    # in for an absence, and the whole fleet scores AS production anyway via
    # the inventory's tri-state flag, so nothing is gained by guessing.

    domain = _first(listing.get("domain"), d.get("domain"))
    return {
        "domain": (domain or "").lower() or None,
        "nexcess_site_id": _first(listing.get("id"), d.get("id")),
        "nickname": _first(listing.get("nickname"), d.get("nickname")),
        "unix_username": _first(d.get("unix_username"),
                                dig(d, "environment", "unix_username")),
        "ip": _first(listing.get("ip"), d.get("ip")),
        "package": _first(dig(listing, "package", "name"),
                          dig(d, "package", "name"),
                          listing.get("package") if isinstance(
                              listing.get("package"), str) else None),
        "state": _first(listing.get("state"), d.get("state")),
        "app": _app_name(_first(listing.get("app"), d.get("app"),
                                dig(d, "environment", "software", "app"))),
        "app_version": _first(dig(d, "environment", "software", "app", "version"),
                              dig(listing, "app", "version")),
        "php_version": _first(dig(d, "environment", "software", "php", "version"),
                              dig(listing, "php", "version")),
        "env": env,
        "temp_domain": _first(listing.get("temp_domain"), d.get("temp_domain")),
        "detail_ok": detail is not None,
    }


def discover(base, token, inventory_path, with_detail=True, sleep=0.2,
             raw_out=None):
    inv = json.load(open(inventory_path))
    inv_nexcess = sorted(
        s["domain"].lower() for s in inv["sites"]
        if s.get("host") and "nexcess" in str(s["host"]).lower())
    inv_all = set(s["domain"].lower() for s in inv["sites"] if s.get("domain"))

    # THE JOIN IS THE SITE ID, NOT THE DOMAIN. Nexcess reports the nxcli TEMP
    # domain as `domain` for 18 of our 22 sites, because the production domain
    # was never set as primary there. Reconciling on domain therefore reported
    # all 18 as "in the API but in no inventory row" AND all 18 as "in the
    # inventory but absent from the API" -- 36 findings, every one false.
    #
    # A reconciliation that cries wolf 36 times is worse than none: it is the
    # step CLAUDE.md puts FIRST when adding a workflow, and a real disagreement
    # would be invisible in that noise. The ledger was fixed to join on
    # `nexcess_site_id` on 2026-08-25; this block was not, and reported 18 and
    # 18 on the very next run.
    inv_by_nx_id = {}
    for s in inv["sites"]:
        if s.get("nexcess_site_id") is not None:
            inv_by_nx_id[str(s["nexcess_site_id"])] = s

    listings = list_sites(base, token)
    raw = {"list": listings, "detail": {}}

    records, errors = [], []
    for entry in listings:
        sid = entry.get("id")
        detail = None
        if with_detail and sid is not None:
            try:
                status, body = _request(base, "/v1/site/%s" % sid, token)
                if status == 200:
                    detail = body if isinstance(body, dict) else None
                    raw["detail"][str(sid)] = body
                else:
                    errors.append({"nexcess_site_id": sid, "status": status,
                                   "error": str(body)[:200]})
            except Exception as e:                   # noqa: BLE001 - reported
                errors.append({"nexcess_site_id": sid, "status": None,
                               "error": "%s: %s" % (type(e).__name__, e)})
            if sleep:
                time.sleep(sleep)
        records.append(normalise(entry, detail))

    api_domains = set(r["domain"] for r in records if r["domain"])

    # Resolve every API record to an inventory row: by site id first, by domain
    # second. `matched_domains` is what the domain-keyed checks below compare
    # against, so a site matched by id no longer looks missing.
    matched_domains, unmatched_api = set(), []
    for r in records:
        row = inv_by_nx_id.get(str(r.get("nexcess_site_id")))
        if row is None and r.get("domain") in inv_all:
            row = next((s for s in inv["sites"]
                        if (s.get("domain") or "").lower() == r["domain"]), None)
        if row is None:
            unmatched_api.append(r.get("domain") or str(r.get("nexcess_site_id")))
        else:
            matched_domains.add((row.get("domain") or "").lower())

    # Reconciliation. CLAUDE.md's first rule for adding a workflow: reconcile
    # the tool's own roster against the inventory BEFORE anything else, because
    # every tool that arrived with its own site list has disagreed with the
    # inventory and the disagreement was always the finding.
    scan = {
        "kind": "nexcess-estate",
        "schema": "nexcess-estate/1",
        "api_base": base,
        "detail_requested": bool(with_detail),
        "listed": len(listings),
        "sites": records,
        "detail_errors": errors,
        "inventory_nexcess_count": len(inv_nexcess),
        # In the inventory as Nexcess, absent from the API. Either the site
        # moved host, or the token cannot see it. Both are findings.
        "in_inventory_not_in_api": sorted(
            d for d in inv_nexcess if d not in matched_domains),
        # Returned by the API and in no inventory row at all. On Pantheon this
        # exact check surfaced the two worst-maintained sites in the fleet.
        "in_api_not_in_inventory": sorted(set(unmatched_api)),
        # Returned by the API, in the inventory, but the inventory does not say
        # Nexcess. A host disagreement, not a missing site.
        "in_api_host_mismatch": sorted(
            d for d in matched_domains
            if d in inv_all and d not in inv_nexcess),
    }
    if raw_out:
        with open(raw_out, "w") as fh:
            json.dump(raw, fh, indent=2, sort_keys=True)
    return scan


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report(scan):
    lines = []
    sites = scan.get("sites", [])
    known_app = [s for s in sites if s.get("app_version")]
    known_php = [s for s in sites if s.get("php_version")]
    known_user = [s for s in sites if s.get("unix_username")]

    lines.append("Nexcess estate discovery")
    lines.append("  api base           %s" % scan.get("api_base"))
    lines.append("  sites listed       %d" % len(sites))
    lines.append("  inventory says     %d Nexcess sites"
                 % scan.get("inventory_nexcess_count", 0))
    lines.append("")
    lines.append("COVERAGE (a blank here is an unanswered question, not a pass)")
    lines.append("  WordPress version  %d of %d" % (len(known_app), len(sites)))
    lines.append("  PHP version        %d of %d" % (len(known_php), len(sites)))
    lines.append("  unix username      %d of %d  (the Phase 2 SSH join key)"
                 % (len(known_user), len(sites)))

    for key, label in (
            ("in_inventory_not_in_api",
             "IN THE INVENTORY AS NEXCESS, NOT RETURNED BY THE API"),
            ("in_api_not_in_inventory",
             "RETURNED BY THE API, IN NO INVENTORY ROW"),
            ("in_api_host_mismatch",
             "RETURNED BY THE API, BUT THE INVENTORY NAMES ANOTHER HOST")):
        vals = scan.get(key) or []
        lines.append("")
        lines.append("%s: %d" % (label, len(vals)))
        for v in vals:
            lines.append("  %s" % v)

    errs = scan.get("detail_errors") or []
    if errs:
        lines.append("")
        lines.append("DETAIL CALLS THAT FAILED: %d" % len(errs))
        for e in errs[:20]:
            lines.append("  site %s  status=%s  %s"
                         % (e.get("nexcess_site_id"), e.get("status"),
                            e.get("error")))

    lines.append("")
    lines.append("%-38s %-9s %-6s %-10s %s"
                 % ("domain", "wordpress", "php", "state", "unix user"))
    for s in sorted(sites, key=lambda r: r.get("domain") or ""):
        lines.append("%-38s %-9s %-6s %-10s %s"
                     % (s.get("domain") or "?",
                        s.get("app_version") or UNKNOWN,
                        s.get("php_version") or UNKNOWN,
                        s.get("state") or UNKNOWN,
                        s.get("unix_username") or UNKNOWN))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_base(arg):
    base = arg or os.environ.get("NEXCESS_PORTAL_API_URL", "").strip()
    if not base:
        raise SystemExit(
            "No API base URL.\n"
            "No API base URL. Established 2026-08-19, from the portal SPA's\n"
            "own traffic:\n\n"
            "  export NEXCESS_PORTAL_API_URL=https://portal.nexcess.net/api\n\n"
            "It is not a default here on purpose: `probe` re-confirms it in one\n"
            "request, and a stale base URL fails in a way that looks exactly\n"
            "like a credentials problem.")
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("probe", help="which base URL answers, and does the "
                                     "token work")
    p.add_argument("--api-base", action="append",
                   help="try only this base (repeatable)")
    p.add_argument("--user-agent",
                   help="override the User-Agent. Pass 'browser' for a "
                        "conventional desktop string. A diagnostic for edge "
                        "bot challenges, not a default.")

    d = sub.add_parser("discover", help="read-only estate discovery")
    d.add_argument("--api-base")
    d.add_argument("--inventory", default="data/fleet-inventory.json")
    d.add_argument("--out", default="reports")
    d.add_argument("--stamp", required=True,
                   help="UTC stamp, YYYY-MM-DD_HHMM. The ledger takes run "
                        "identity from the filename, so this is not cosmetic.")
    d.add_argument("--no-detail", action="store_true",
                   help="skip GET /v1/site/{id}. Faster, and returns no PHP "
                        "version, no WordPress version and no unix username, "
                        "which is to say almost nothing worth having.")
    d.add_argument("--user-agent",
                   help="override the User-Agent; see probe --user-agent")
    d.add_argument("--raw-out",
                   help="also write the unparsed API responses here. Worth "
                        "doing on the first run: every field name this tool "
                        "reads comes from docs nothing has executed against.")

    r = sub.add_parser("report", help="print findings from a scan file")
    r.add_argument("--scan", required=True)

    a = ap.parse_args()
    _set_user_agent(getattr(a, "user_agent", None))

    if a.cmd == "probe":
        results = probe(_token(), a.api_base or CANDIDATE_BASES)
        for rec in results:
            print("%-40s %-16s %-4s %s"
                  % (rec["base"], rec["verdict"],
                     rec["status"] if rec["status"] else "-",
                     rec["detail"] if rec["detail"] else ""))
        print("")

        # Ordered by what the reader should do next, not by severity. Each
        # branch names ONE cause and ONE fix; nothing collapses two causes into
        # a shared "it did not work".
        ok = [r for r in results if r["verdict"] == "ok"]
        if ok:
            print("Use: export NEXCESS_PORTAL_API_URL=%s" % ok[0]["base"])
            return 0

        chal = [r for r in results if r["verdict"] == "bot-challenge"]
        if chal:
            print("AN EDGE BOT CHALLENGE IS BLOCKING THE REQUEST.")
            print("")
            for r in chal:
                print("  %s" % r["base"])
            print("")
            print("The response is a challenge page, not an API response, so the\n"
                  "request never reached the application and the token was never\n"
                  "read. This is NOT a credentials problem and rotating the token\n"
                  "will not change it.")
            print("")
            # Do not suggest a diagnostic the caller has just run. The first
            # version printed the --user-agent advice unconditionally, so the
            # run that RULED IT OUT ended by recommending it again.
            if _UA_OVERRIDE[0]:
                print("A conventional User-Agent was already tried on this run\n"
                      "and was challenged too, so the fingerprint is not the\n"
                      "header. It is TLS-level or IP reputation.")
                print("")
                print("One test left that costs nothing -- curl uses OpenSSL and\n"
                      "this tool uses Python's own TLS stack, which fingerprint\n"
                      "differently:")
                print('  curl -sS -D- -o /tmp/nx.body \\')
                print('    -H "Authorization: Bearer $NEXCESS_PORTAL_API_TOKEN" \\')
                print('    -H "Accept: application/json" \\')
                print('    "%s/v1/site?pageSize=1" | head -1' % chal[0]["base"])
                print("")
                print("And in CI: run the workflow with probe_only, because a\n"
                      "GitHub runner has different IP reputation to a laptop.")
                print("")
                print("If both are challenged, STOP. This is a Nexcess support\n"
                      "question -- see docs/NEXCESS-SUPPORT.md for the ticket.")
            else:
                print("One diagnostic worth running, because it turns this into a\n"
                      "specific thing to tell Nexcess:")
                print("  ./scripts/fleet-nexcess.py probe --user-agent browser")
                print("")
                print("If that gets through, their edge is fingerprinting on\n"
                      "User-Agent and challenging a token-authenticated client on\n"
                      "an endpoint they document for programmatic use. If it does\n"
                      "not, stop: no header will fix it, and the question is for\n"
                      "Nexcess support (docs/NEXCESS-SUPPORT.md).")
            return 5

        auth = [r for r in results if r["verdict"] == "unauthorised"]
        if auth:
            print("The application at %s read the token and rejected it. That is\n"
                  "a credentials problem, not a URL problem." % auth[0]["base"])
            return 2

        forb = [r for r in results if r["verdict"] == "forbidden"]
        if forb:
            print("The application at %s returned 403 with a non-challenge body.\n"
                  "Read the body above before assuming a cause: it may be token\n"
                  "scope, or this path may simply not be for this account type."
                  % forb[0]["base"])
            return 2

        tls = [r for r in results if r["verdict"] == "tls-untrusted"]
        if tls:
            print("THIS IS A PROBLEM ON THIS MACHINE, NOT AT NEXCESS.")
            print("")
            print("Every host below served a valid TLS certificate, so DNS\n"
                  "resolved and the server is listening. This Python could not\n"
                  "verify the certificate because it has no CA bundle -- the\n"
                  "usual cause is a python.org build on macOS, which ships its\n"
                  "own trust store and does not read the system keychain.")
            for r in tls:
                print("  %s" % r["base"])
            print("")
            print("Fix it, in this order, and re-run probe:")
            print("  1. /Applications/Python*/Install\\ Certificates.command")
            print("  2. python3 -m pip install --upgrade certifi")
            print("     (this tool uses certifi automatically when it is there)")
            print("")
            print("Do NOT work around this by disabling verification. This tool\n"
                  "sends a credential to a hosting control plane.")
            return 3

        wrong = [r for r in results
                 if r["verdict"] in ("not-api", "not-json", "json-unexpected")]
        if wrong:
            print("A host answered HTTP 200 but did NOT return a site list.")
            print("")
            for r in wrong:
                print("  %-40s %s" % (r["base"], r["detail"]))
            print("")
            print("A 200 is not an answer. This is almost certainly the portal\n"
                  "web UI rather than the API, which means the API lives at a\n"
                  "path nobody here has found yet.")
            print("")
            print("Next: ask Nexcess support what $PORTAL_API_URL resolves to.\n"
                  "docs/NEXCESS-ARCHITECTURE.md section 19 is the support email;\n"
                  "add the question to it. Or try a path directly:\n"
                  "  ./scripts/fleet-nexcess.py probe --api-base https://<host>/<path>")
            return 2

        real = [r for r in results if r["verdict"] in HOST_EXISTS]
        if real:
            print("A host answered at %s but not in a way this tool understands.\n"
                  "Re-run with --api-base to try one path at a time."
                  % real[0]["base"])
            return 2

        print("No candidate host exists. Do not pick one and hope; ask Nexcess\n"
              "support for the portal API base URL (docs/NEXCESS-ARCHITECTURE.md\n"
              "section 19 is the support email).")
        return 4

    if a.cmd == "discover":
        base = _resolve_base(a.api_base)
        scan = discover(base, _token(), a.inventory,
                        with_detail=not a.no_detail, raw_out=a.raw_out)
        scan["run_stamp"] = a.stamp
        if not os.path.isdir(a.out):
            os.makedirs(a.out)
        path = os.path.join(a.out, "fleet-nexcess-%s.json" % a.stamp)
        with open(path, "w") as fh:
            json.dump(scan, fh, indent=2, sort_keys=True)
        print(report(scan))
        print("")
        print("-> %s" % path)
        return 0

    if a.cmd == "report":
        print(report(json.load(open(a.scan))))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
