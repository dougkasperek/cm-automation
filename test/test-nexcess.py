#!/usr/bin/env python3
"""
Self-check for the Nexcess workflow: scripts/fleet-nexcess.py, its ledger
source, and its severity rules.

NOTHING HERE TOUCHES THE NETWORK. Every API response is a fixture built from
the shapes in docs/NEXCESS-ARCHITECTURE.md, which is imported research that
this codebase has never executed against. That is exactly why the fixtures
include a MALFORMED and a HALF-EMPTY response as well as the documented one:
the documented shape is the case least likely to be the one that breaks us.

The cases that matter most are the absences. A Nexcess site whose version the
API would not report must not be able to reach OK, because "OK" over a site
whose wp2shell status is still unknown is every row in CLAUDE.md's table.

Run: ./test/test-nexcess.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N = _load("fleet_nexcess", os.path.join(ROOT, "scripts", "fleet-nexcess.py"))
L = _load("fleet_ledger", os.path.join(ROOT, "scripts", "fleet-ledger.py"))
S = _load("severity", os.path.join(ROOT, "scripts", "lib", "severity.py"))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("  <- " + detail) if (detail and not cond) else ""))


# ---------------------------------------------------------------------------
# Fixtures. Field names follow the vendor docs; nothing has verified them.
# ---------------------------------------------------------------------------

LISTING_FULL = {
    "id": 1091,
    "domain": "42northbrewing.com",
    "temp_domain": "39869b24b8.1700.lwdns.dev",
    "ip": "192.190.222.73",
    "nickname": "42 North",
    "state": "stable",
    "app": "wordpress",
    "is_dev_account": False,
    "is_staging_account": False,
    "package": {"name": "Managed WordPress 100"},
}

DETAIL_FULL = {
    "id": 1091,
    "domain": "42northbrewing.com",
    "unix_username": "a405fd09",
    "environment": {
        "software": {
            "php": {"version": "8.2"},
            "app": {"type": "wordpress", "version": "7.0.4"},
        }
    },
}

# The same site as the control plane might actually answer: listed, but the
# detail call returns a body with none of the fields the docs promise.
DETAIL_EMPTY = {"id": 1091, "domain": "42northbrewing.com"}


# ---------------------------------------------------------------------------
# 1. The scanner never invents a value
# ---------------------------------------------------------------------------
print("\n--- normalisation: an absent field is absent ---")

full = N.normalise(LISTING_FULL, DETAIL_FULL)
check("reads the WordPress version out of the documented nesting",
      full["app_version"] == "7.0.4", repr(full["app_version"]))
check("reads the PHP version out of the documented nesting",
      full["php_version"] == "8.2", repr(full["php_version"]))
check("reads the unix username, which is the Phase 2 SSH join key",
      full["unix_username"] == "a405fd09", repr(full["unix_username"]))
check("reads the package name whether it is a string or an object",
      full["package"] == "Managed WordPress 100"
      and N.normalise(dict(LISTING_FULL, package="MWP 100"), {})["package"]
      == "MWP 100")
check("lowercases the domain so it joins the inventory key",
      N.normalise(dict(LISTING_FULL, domain="42NorthBrewing.com"),
                  {})["domain"] == "42northbrewing.com")

empty = N.normalise(LISTING_FULL, DETAIL_EMPTY)
check("a detail call with no software block yields NO version, not a blank one",
      empty["app_version"] is None and empty["php_version"] is None)
check("...and no unix username rather than an empty string",
      empty["unix_username"] is None)

nodetail = N.normalise(LISTING_FULL, None)
check("skipping the detail call is recorded, not hidden",
      nodetail["detail_ok"] is False and full["detail_ok"] is True)

# env: the tempting default is "production" and it would be a guess.
check("env is production only when the API says both flags are false",
      full["env"] == "production")
check("env is dev when the dev flag is set",
      N.normalise(dict(LISTING_FULL, is_dev_account=True), {})["env"] == "dev")
check("env is staging when the staging flag is set",
      N.normalise(dict(LISTING_FULL, is_staging_account=True),
                  {})["env"] == "staging")
check("env stays UNSET when the API reports neither flag, rather than "
      "defaulting to production",
      N.normalise({"id": 1, "domain": "x.com"}, {})["env"] is None)

# A field the docs describe two ways.
check("app is read whether the API returns a string or an object",
      N.normalise(dict(LISTING_FULL, app={"name": "WordPress"}), {})["app"]
      == "wordpress")

check("dig() returns None for a path that does not exist, never a default",
      N.dig(DETAIL_FULL, "environment", "software", "nope", "version") is None)
check("dig() survives a scalar where the docs promised an object",
      N.dig({"environment": "n/a"}, "environment", "software") is None)


# ---------------------------------------------------------------------------
# 2. Read-only is enforced, not just intended
# ---------------------------------------------------------------------------
print("\n--- read-only ---")

try:
    N._request("https://example.invalid", "/v1/site", "tok", method="POST")
    _refused = False
except ValueError:
    _refused = True
except Exception:
    _refused = False
check("the request helper refuses any method other than GET",
      _refused)

_src = open(os.path.join(ROOT, "scripts", "fleet-nexcess.py")).read()

# Strip the module docstring and every comment before looking. The docstring
# NAMES the write endpoints on purpose, to say they are off limits; a grep that
# cannot tell prose from code would either fail on that sentence or force the
# sentence out of the file, and the sentence is worth more than the grep.
_code = _src.split('"""', 2)[2]
_code = "\n".join(l.split("#")[0] for l in _code.splitlines())
check("no write endpoint is reachable from the code, only named in the prose "
      "that forbids them",
      not any(w in _code for w in ("purge-caches", "change-php-version",
                                   "/site/add", "toggle-app-update")))
check("...and the docstring does still say so",
      "purge-caches" in _src)


# ---------------------------------------------------------------------------
# 2b. A failed request says WHICH failure it was
# ---------------------------------------------------------------------------
# Every string below is copied verbatim from Doug's first real probe run,
# 2026-08-19. That run reported all four candidates as "unreachable" when three
# of them had in fact served a valid TLS certificate and the fault was a
# missing CA bundle on his laptop. One confident word standing in for causes
# that are not the same -- the exact failure this repo keeps a table of.
print("\n--- error classification ---")

import socket as _socket
import ssl as _ssl
import urllib.error as _uerr


def _err(inner):
    return _uerr.URLError(inner)


_tls = _err(_ssl.SSLCertVerificationError(
    1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to "
       "get local issuer certificate (_ssl.c:1081)"))
_dns = _err(_socket.gaierror(8, "nodename nor servname provided, or not known"))
_dns_linux = _err(_socket.gaierror(-2, "Name or service not known"))
_to = _err(_socket.timeout("timed out"))
_ref = _err(ConnectionRefusedError(61, "Connection refused"))
_other = _err(OSError("something else entirely"))

check("a certificate verification failure is NOT reported as unreachable",
      N.classify_error(_tls)[0] == "tls-untrusted",
      repr(N.classify_error(_tls)))
check("...and says the problem is on this machine, not at the far end",
      "THIS machine" in N.classify_error(_tls)[1])
check("a TLS failure counts as PROOF the host exists, because DNS resolved "
      "and a certificate was served",
      "tls-untrusted" in N.HOST_EXISTS)
check("an unresolvable name is its own verdict, on macOS wording",
      N.classify_error(_dns)[0] == "dns-unknown")
check("...and on Linux wording, so CI and a laptop agree",
      N.classify_error(_dns_linux)[0] == "dns-unknown")
check("a name that does not resolve is NOT proof the host exists",
      "dns-unknown" not in N.HOST_EXISTS)
check("a timeout is distinct from a refusal",
      N.classify_error(_to)[0] == "timeout"
      and N.classify_error(_ref)[0] == "refused")
check("anything unrecognised falls back to unreachable WITH the raw error, "
      "rather than to a tidy word that hides it",
      N.classify_error(_other)[0] == "unreachable"
      and "something else entirely" in N.classify_error(_other)[1])

# Verification is never optional, whatever the trust store is doing.
check("there is no path that disables certificate verification",
      "_create_unverified_context" not in _src
      and "CERT_NONE" not in _src
      and "--insecure" not in _src)
check("the SSL context prefers certifi when it is installed, and still "
      "verifies when it is not",
      "certifi.where()" in _src and "create_default_context" in _src)


# ---------------------------------------------------------------------------
# 2c. A 200 is not an answer
# ---------------------------------------------------------------------------
# On 2026-08-19 probe reported `ok  authenticated; site list returned` for a
# response whose body was a web page, because it read the status code and
# nothing else. discover then crashed with AttributeError: 'str' object has no
# attribute 'get'. The crash was the lucky part -- a body that happened to be
# JSON-shaped would have produced an empty estate reported as a complete one.
print("\n--- the body decides the verdict, not the status ---")

_orig_request = N._request

_HTML = "<!DOCTYPE html><html><head><title>Nexcess Client Portal</title></head>"

check("a 200 carrying a web page is NOT ok",
      N.classify_response(200, None, _HTML, "text/html; charset=utf-8")[0]
      == "not-api",
      repr(N.classify_response(200, None, _HTML, "text/html")))
check("...and says so in words a reader can act on",
      "portal UI, not the API"
      in N.classify_response(200, None, _HTML, "text/html")[1])
check("a 200 carrying a web page with no content-type header is still caught, "
      "by the shape of the body",
      N.classify_response(200, None, _HTML, "")[0] == "not-api")
check("a 200 carrying valid JSON that is not a site list is NOT ok",
      N.classify_response(200, {"message": "hello"}, '{"message":"hello"}',
                          "application/json")[0] == "json-unexpected")
check("a bare array IS a site list",
      N.classify_response(200, [{"id": 1}], "[]", "application/json")[0] == "ok")
check("a data-wrapped envelope IS a site list",
      N.classify_response(200, {"data": [{"id": 1}]}, "{}",
                          "application/json")[0] == "ok")
check("...and the ok detail states how many entries came back, so an empty "
      "estate cannot read like a full one",
      "0 entries"
      in N.classify_response(200, [], "[]", "application/json")[1])

check("looks_like_site_list rejects a string, a number and None",
      not any(N.looks_like_site_list(v) for v in ("[]", 3, None, {}, {"data": {}})))

# An edge challenge is not a credentials problem, and the difference decides
# WHO can fix it. Doug's 2026-08-19 probe got `Just a moment...` from
# portal.nexcess.net and this tool told him the token had been rejected.
_CF = ('<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
       '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />')

_ch = N.classify_response(403, None, _CF, "text/html")
check("a Cloudflare challenge page is NOT reported as a credentials problem",
      _ch[0] == "bot-challenge", repr(_ch))
check("...and says the token was never read, because the request never "
      "reached the application",
      "never read" in _ch[1])
check("a challenge is recognised whatever status it arrives with",
      N.classify_response(503, None, _CF, "text/html")[0] == "bot-challenge"
      and N.classify_response(200, None, _CF, "text/html")[0] == "bot-challenge")
check("a real 401 from the application is still a credentials problem",
      N.classify_response(401, None, '{"error":"bad token"}',
                          "application/json")[0] == "unauthorised")
check("an ordinary HTML page is not mistaken for a challenge",
      not N.looks_like_challenge(_HTML)
      and N.looks_like_challenge(_CF))
check("the User-Agent is overridable for diagnosis but honest by default",
      "cm-automation" in N.USER_AGENT and N._user_agent() == N.USER_AGENT)

# A 403 is where the first version asserted a cause it had not measured.
_403 = N.classify_response(403, None, "<html>error 1020 access denied</html>",
                           "text/html")
check("a 403 does NOT assert that the token lacks permission",
      "lacks permission" not in _403[1], repr(_403))
check("...and shows the body instead, because a WAF 403 and a scope 403 look "
      "identical at this layer",
      "1020 access denied" in _403[1])

# And the crash itself must now be an error that names the problem.
try:
    N._request = lambda *a, **k: (200, _HTML)
    try:
        N.list_sites("https://example.invalid", "tok")
        _verdict = "no error"
    except N.ApiError as ex:
        _verdict = str(ex)
    except AttributeError:
        _verdict = "AttributeError"
finally:
    N._request = _orig_request
check("a 200 with a non-JSON body raises a named ApiError, not the "
      "AttributeError traceback this actually produced",
      _verdict not in ("no error", "AttributeError")
      and "not a site list" in _verdict, _verdict)

check("no candidate base URL is presented as established while none has "
      "returned a site list",
      "NEXCESS_PORTAL_API_URL = " not in _src)


# ---------------------------------------------------------------------------
# 3. Pagination terminates, and a truncated estate is never reported as whole
# ---------------------------------------------------------------------------
print("\n--- pagination ---")


def _fake(pages):
    """A stand-in for _request that serves a fixed list of pages."""
    def inner(base, path, token, params=None, method="GET"):
        if path == "/v1/site":
            p = (params or {}).get("page", 1)
            return 200, pages[p - 1] if p <= len(pages) else []
        return 200, DETAIL_FULL
    return inner


try:
    N._request = _fake([[dict(LISTING_FULL, id=i) for i in range(N.PAGE_SIZE)],
                        [dict(LISTING_FULL, id=999)]])
    got = N.list_sites("https://example.invalid", "tok")
    check("a full page is followed by the next one",
          len(got) == N.PAGE_SIZE + 1, str(len(got)))

    N._request = _fake([[dict(LISTING_FULL, id=1)]])
    check("a short page ends the walk without a second request",
          len(N.list_sites("https://example.invalid", "tok")) == 1)

    # The failure mode the vendor docs flag under "verify before production":
    # an endpoint that ignores `page` and serves the first one forever.
    def _stuck(base, path, token, params=None, method="GET"):
        return 200, [dict(LISTING_FULL, id=i) for i in range(N.PAGE_SIZE)]

    N._request = _stuck
    try:
        N.list_sites("https://example.invalid", "tok")
        _raised = False
    except N.ApiError:
        _raised = True
    check("an endpoint that never paginates raises rather than returning a "
          "truncated estate that would read as the whole estate", _raised)
finally:
    N._request = _orig_request


# ---------------------------------------------------------------------------
# 4. Reconciliation against the inventory: the disagreement IS the finding
# ---------------------------------------------------------------------------
print("\n--- reconciliation against data/fleet-inventory.json ---")

INV_PATH = os.path.join(ROOT, "data", "fleet-inventory.json")
_inv = json.load(open(INV_PATH))
_inv_nexcess = sorted(s["domain"].lower() for s in _inv["sites"]
                      if s.get("host") and "nexcess" in str(s["host"]).lower())
check("the inventory is the site list, and it holds 21 Nexcess sites",
      len(_inv_nexcess) == 21, str(len(_inv_nexcess)))

try:
    # The API returns: one inventory Nexcess site, one site nobody wrote down,
    # and one site the inventory says is on Pantheon. Twenty inventory Nexcess
    # sites are missing from the response.
    _api = [dict(LISTING_FULL, id=1, domain=_inv_nexcess[0]),
            dict(LISTING_FULL, id=2, domain="nobody-wrote-this-down.com"),
            dict(LISTING_FULL, id=3, domain="11daypowerplay.com")]
    N._request = _fake([_api])
    scan = N.discover("https://example.invalid", "tok", INV_PATH,
                      with_detail=False, sleep=0)
    check("a site the inventory calls Nexcess and the API did not return is "
          "reported, not dropped",
          len(scan["in_inventory_not_in_api"]) == 20,
          str(len(scan["in_inventory_not_in_api"])))
    check("a site the API returned that is in no inventory row is reported",
          scan["in_api_not_in_inventory"] == ["nobody-wrote-this-down.com"],
          repr(scan["in_api_not_in_inventory"]))
    check("a site whose inventory row names a different host is reported "
          "separately from a missing one",
          scan["in_api_host_mismatch"] == ["11daypowerplay.com"],
          repr(scan["in_api_host_mismatch"]))
    check("the scan records how many Nexcess sites the inventory claims, so a "
          "reader can see coverage without re-deriving it",
          scan["inventory_nexcess_count"] == 21)

    # A detail call that fails must not silently produce a site with no facts.
    def _detail_fails(base, path, token, params=None, method="GET"):
        if path == "/v1/site":
            return 200, [dict(LISTING_FULL, id=7, domain=_inv_nexcess[0])]
        return 403, {"message": "forbidden"}

    N._request = _detail_fails
    scan2 = N.discover("https://example.invalid", "tok", INV_PATH,
                       with_detail=True, sleep=0)
    check("a failed detail call is recorded as an error",
          len(scan2["detail_errors"]) == 1, repr(scan2["detail_errors"]))
    check("...and the site carries no version rather than a zero or a blank",
          scan2["sites"][0]["app_version"] is None
          and scan2["sites"][0]["php_version"] is None)
finally:
    N._request = _orig_request

_rep = N.report(scan2)
check("the report prints 'unknown' for a version it does not have, not an "
      "empty column", "unknown" in _rep)
check("the report leads with coverage: how many of how many were answered",
      "COVERAGE" in _rep and "wp2shell" not in _rep.split("COVERAGE")[0])


# ---------------------------------------------------------------------------
# 5. Ledger: the nexcess source ingests, keyed on the inventory site_id
# ---------------------------------------------------------------------------
print("\n--- ledger ingest ---")

# Asserts the guard WORKS, not which sources happen to exist today. The first
# version enumerated the three sources by name and duly broke the moment a
# fourth arrived -- a test that fails on correct changes teaches people to edit
# tests, which is the opposite of what it is for.
_pairs = [(a, b) for a in sorted(L.FACT_FAMILIES) for b in sorted(L.FACT_FAMILIES) if a < b]
check("the fact-name collision guard covers every pair of sources, not one "
      "hardcoded pair",
      len(L.FACT_FAMILIES) >= 3 and len(_pairs) == len(L.FACT_FAMILIES) * (len(L.FACT_FAMILIES) - 1) // 2,
      repr(sorted(L.FACT_FAMILIES)))
check("...and no two sources share a fact name today",
      all(not (set(L.FACT_FAMILIES[a]) & set(L.FACT_FAMILIES[b])) for a, b in _pairs),
      repr([(a, b, sorted(set(L.FACT_FAMILIES[a]) & set(L.FACT_FAMILIES[b])))
            for a, b in _pairs if set(L.FACT_FAMILIES[a]) & set(L.FACT_FAMILIES[b])]))
check("...and every declared source has facts, so an empty tuple cannot slip "
      "past the guard by colliding with nothing",
      all(len(v) > 0 for v in L.FACT_FAMILIES.values()))
check("no nexcess fact name collides with a health fact name",
      not (set(L.NEXCESS_OBSERVED) & set(L.OBSERVED)))
check("the control plane's WordPress version is NOT stored as wp_version",
      "wp_version" not in L.NEXCESS_OBSERVED
      and "nexcess_app_version" in L.NEXCESS_OBSERVED)

# Run identity comes from the filename. Pinned, never positional.
RUN_ID = "nexcess-2026-08-19_1200"
_meta = L.parse_run_id("reports/fleet-nexcess-2026-08-19_1200.json")
check("a nexcess scan filename parses to its own run kind",
      _meta and _meta["run_id"] == RUN_ID, repr(_meta))

_tmp = tempfile.mkdtemp(prefix="nexcess-test-")
try:
    _reports = os.path.join(_tmp, "reports")
    _history = os.path.join(_tmp, "history")
    os.makedirs(_reports)
    scan_file = {
        "kind": "nexcess-estate",
        "schema": "nexcess-estate/1",
        "api_base": "https://example.invalid/api",
        "inventory_nexcess_count": 21,
        "sites": [
            # measured, current
            {"domain": _inv_nexcess[0], "nexcess_site_id": 1,
             "unix_username": "a1", "ip": "10.0.0.1", "state": "stable",
             "app": "wordpress", "app_version": "7.0.4", "php_version": "8.2",
             "env": "production", "package": "MWP", "temp_domain": None,
             "detail_ok": True},
            # measured, BELOW the wp2shell floor
            {"domain": _inv_nexcess[1], "nexcess_site_id": 2,
             "unix_username": "a2", "ip": "10.0.0.2", "state": "stable",
             "app": "wordpress", "app_version": "6.9.4", "php_version": "8.2",
             "env": "production", "package": "MWP", "temp_domain": None,
             "detail_ok": True},
            # listed but the API said nothing about the application
            {"domain": _inv_nexcess[2], "nexcess_site_id": 3,
             "unix_username": None, "ip": None, "state": "stable",
             "app": None, "app_version": None, "php_version": None,
             "env": None, "package": None, "temp_domain": None,
             "detail_ok": False},
            # PHP past end of security support
            {"domain": _inv_nexcess[3], "nexcess_site_id": 4,
             "unix_username": "a4", "ip": "10.0.0.4", "state": "stable",
             "app": "wordpress", "app_version": "7.0.4", "php_version": "7.4",
             "env": "production", "package": "MWP", "temp_domain": None,
             "detail_ok": True},
        ],
        "detail_errors": [],
        "in_inventory_not_in_api": [],
        "in_api_not_in_inventory": [],
        "in_api_host_mismatch": [],
    }
    with open(os.path.join(_reports,
                           "fleet-nexcess-2026-08-19_1200.json"), "w") as fh:
        json.dump(scan_file, fh)

    res = L.ingest(_reports, _history, inventory=INV_PATH)
    check("the nexcess scan is recognised and ingested",
          res["runs_added"] == 1 and res["observations_added"] == 4,
          json.dumps(res))

    runs, obs = L.load_ledger(_history)
    run = [r for r in runs if r["run_id"] == RUN_ID][0]
    check("the run is stored under the nexcess source",
          run["source"] == "nexcess", repr(run["source"]))
    check("the run's mode says it was control-plane discovery, not a deep scan",
          run["mode"] == "api-estate", repr(run["mode"]))
    check("coverage counts only the sites whose version the API actually gave",
          run["deep_scanned"] == 3, str(run["deep_scanned"]))
    check("every row resolved to an inventory site_id",
          run["sites_not_in_inventory"] == [],
          repr(run["sites_not_in_inventory"]))

    rows = L.rows_for_source(obs, RUN_ID, "nexcess")
    check("rows are keyed on the inventory domain, not on the Nexcess site id",
          _inv_nexcess[0] in rows)
    check("a site the API would not describe stores 'unknown', never 0 or ''",
          rows[_inv_nexcess[2]]["nexcess_app_version"] == "unknown"
          and rows[_inv_nexcess[2]]["nexcess_php_version"] == "unknown")
    check("the diff uses the nexcess fact list for a nexcess row",
          L.facts_for(rows[_inv_nexcess[0]]) is L.NEXCESS_OBSERVED)

    # ------------------------------------------------------------------
    # 6. Severity, scored through the ledger exactly as the dashboard does
    # ------------------------------------------------------------------
    print("\n--- severity ---")
    _invrecs = {s["site_id"]: s for s in _inv["sites"]}
    TODAY = "2026-08-19"
    import datetime
    today = datetime.date.fromisoformat(TODAY)

    def score(domain):
        return L.score(rows[domain], _invrecs, today)

    s0, s1, s2, s3 = (score(_inv_nexcess[i]) for i in range(4))

    check("a Nexcess site that was discovered is no longer UNKNOWN",
          all(s["status"] != "UNKNOWN" for s in (s0, s1, s2, s3)),
          repr([s["status"] for s in (s0, s1, s2, s3)]))
    check("...and is not SKIP either, which would read as nothing to check",
          all(s["status"] != "SKIP" for s in (s0, s1, s2, s3)))

    check("a control-plane version below the wp2shell floor is CRIT",
          s1["status"] == "CRIT"
          and any(r["code"] == "wp_below_floor" for r in s1["reasons"]),
          repr(s1))
    check("...and the reason says the control plane is where it came from",
          any("Nexcess control plane" in r["text"] for r in s1["reasons"]))

    check("PHP past end of security support is CRIT from the control plane too",
          s3["status"] == "CRIT"
          and any(r["code"] == "php_eol" for r in s3["reasons"]), repr(s3))

    check("a site the API would not describe cannot reach OK",
          s2["status"] == "WARN"
          and any(r["code"] == "nexcess_app_version_unknown"
                  for r in s2["reasons"]), repr(s2))

    # The one that matters most. Discovery gives no backup age, no plugin
    # count and no theme count, and those are the facts that make a Pantheon
    # OK mean anything.
    check("a current, supported Nexcess site still cannot reach OK on "
          "discovery evidence alone",
          s0["status"] == "WARN"
          and any(r["code"] == "coverage_partial" for r in s0["reasons"]),
          repr(s0))

    # ...and the rule retires itself once the missing facts arrive.
    _merged = dict(rows[_inv_nexcess[0]])
    _merged.update({"wp_checked": True, "wp_version": "7.0.4",
                    "php_version": "8.2", "db_backup_age_days": 1,
                    "plugin_updates": 0, "theme_updates": 0,
                    "upstream_pending": 0, "wp_core_update": "up-to-date",
                    "frozen": False, "in_workbook": True})
    _after = S.evaluate(_merged, today)
    check("...and reaches OK once a health scan supplies backup and plugin "
          "facts for the same site",
          _after["status"] == "OK", repr(_after))

    # A disagreement between the two readings is a finding, not a coin toss.
    _dis = dict(_merged, wp_version="7.0.4", nexcess_app_version="6.9.4")
    _dr = S.evaluate(_dis, today)
    check("WP-CLI and the control plane disagreeing is reported, and neither "
          "value silently wins",
          any(r["code"] == "wp_version_disagreement" for r in _dr["reasons"]),
          repr(_dr))
    check("...and the WP-CLI reading is what scores, so a stale control-plane "
          "number cannot manufacture a CRIT",
          _dr["status"] == "WARN", repr(_dr["status"]))

    # Nexcess sites are production by default: production is null on all of
    # them and null must count.
    check("a Nexcess site with no production ruling counts toward the fleet",
          all(s["production"] is True for s in (s0, s1, s2, s3)))

    # Ingest is idempotent, like every other source.
    res2 = L.ingest(_reports, _history, inventory=INV_PATH)
    check("re-ingesting the same run adds nothing",
          res2["runs_added"] == 0 and res2["observations_added"] == 0)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 7. The contract the rest of the suite runs under
# ---------------------------------------------------------------------------
print("\n--- contract ---")

check("stdlib only, no third-party imports",
      not any(line.startswith("import ") and line.split()[1].split(".")[0] in
              ("requests", "yaml", "dns", "httpx")
              for line in _src.splitlines()))
check("no f-strings or 3.10+ syntax needed (py3.6 compatible source)",
      'f"' not in _src and "f'" not in _src and " match " not in _src)
check("the API base URL is not hardcoded to a guess",
      "NEXCESS_PORTAL_API_URL" in _src and "_resolve_base" in _src)
check("the token is read from the environment and never from a file in the repo",
      "NEXCESS_PORTAL_API_TOKEN" in _src
      and "open(" not in _src.split("def _token")[1].split("def ")[0])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
