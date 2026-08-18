#!/usr/bin/env python3
"""
Self-check for fleet-email-dns.py.

No network. Every DNS call is stubbed, so this runs in CI, offline, and gives
the same answer every time. The point is to pin the parsing and the RECOVERED
RULE, because both were arrived at empirically and both are easy to break by
accident later.

Run: ./test/test-email-dns.py
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("edns", os.path.join(ROOT, "scripts", "fleet-email-dns.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name, ("  <- " + detail) if (detail and not cond) else ""))


# ---------------------------------------------------------------- DNS stubbing
ZONE = {}


def stub_resolve(name, rdtype, timeout=0):
    return ZONE.get((rdtype, name.lower()), {"status": "nxdomain", "records": []})


E._resolve = stub_resolve


def zone(**kw):
    ZONE.clear()
    for k, v in kw.items():
        pass


def put(rdtype, name, records):
    ZONE[(rdtype, name.lower())] = {"status": "ok", "records": records}


# ------------------------------------------------------------- org domain math
print("\n-- organizational domain --")
check("two-label domain is its own org", E.org_domain("example.com") == "example.com")
check("subdomain reduces to org", E.org_domain("app.galbani.com") == "galbani.com")
check("deep subdomain reduces to org", E.org_domain("a.b.c.example.com") == "example.com")
check(".gov behaves like a two-label tld", E.org_domain("email.lancastervillageny.gov") == "lancastervillageny.gov")
check("multi-label suffix is respected", E.org_domain("shop.example.co.uk") == "example.co.uk")
check("None in, None out", E.org_domain(None) is None)
check("address domain extracted", E.domain_of("a@b.example.com") == "b.example.com")
check("address with no @ is None", E.domain_of("nonsense") is None)
check("None address is None", E.domain_of(None) is None)

# ------------------------------------------------------------------ SPF parse
print("\n-- SPF parsing --")
s = E.parse_spf(["v=spf1 include:mailgun.org ~all"])
check("spf detected", s["present"] is True)
check("include extracted", s["includes"] == ["mailgun.org"])
check("qualifier extracted", s["all_qualifier"] == "~all")
s = E.parse_spf(["v=spf1 redirect=_spf.google.com"])
check("redirect-style SPF is still present", s["present"] is True)
check("redirect-style SPF has no all qualifier", s["all_qualifier"] is None,
      "this is exactly why the adopted rule is presence, not qualifier")
check("non-spf TXT ignored", E.parse_spf(["google-site-verification=abc"])["present"] is False)
check("two SPF records flagged as an RFC violation",
      E.parse_spf(["v=spf1 a ~all", "v=spf1 mx ~all"])["multiple_spf_records"] is True)

# ---------------------------------------------------------------- DMARC parse
print("\n-- DMARC parsing --")
d = E.parse_dmarc(["v=DMARC1; p=reject; rua=mailto:x@y.com; adkim=s"])
check("dmarc detected", d["present"] is True)
check("policy extracted", d["policy"] == "reject")
check("rua extracted", d["rua"] == "mailto:x@y.com")
check("explicit adkim honoured", d["adkim"] == "s")
check("adkim defaults to relaxed when absent", E.parse_dmarc(["v=DMARC1; p=none"])["adkim"] == "r")
check("absent dmarc is not present", E.parse_dmarc([])["present"] is False)
check("an SPF record is not mistaken for DMARC", E.parse_dmarc(["v=spf1 ~all"])["present"] is False)

# ------------------------------------------------------------------ DKIM find
print("\n-- DKIM discovery --")
ZONE.clear()
put("TXT", "mailo._domainkey.web.example.com", ["v=DKIM1; k=rsa; p=MIIB"])
r = E.find_dkim(["web.example.com", "example.com"])
check("TXT key found", r["present"] is True and r["selector"] == "mailo" and r["via"] == "txt")

ZONE.clear()
put("CNAME", "s1._domainkey.example.com", ["s1.domainkey.u1.sendgrid.net"])
r = E.find_dkim(["em1.example.com", "example.com"])
check("CNAME-delegated key found (SendGrid pattern)", r["present"] is True and r["via"] == "cname",
      json.dumps(r))
check("CNAME key found on the ORG domain, not the sending subdomain", r["at"] == "example.com")

ZONE.clear()
r = E.find_dkim(["nothing.example.com", "example.com"])
check("no key found is UNKNOWN, never False", r["present"] == E.UNKNOWN, str(r["present"]))
check("unknown result explains why", "cannot be enumerated" in r.get("reason", ""))

ZONE.clear()
put("TXT", "weird-custom._domainkey.example.com", ["v=DKIM1; p=AAA"])
r = E.find_dkim(["example.com"], override="weird-custom")
check("an inventory selector override is honoured", r["present"] is True and r["selector"] == "weird-custom")
check("the override is tried first", r["probes"] == 1, str(r["probes"]))

# ----------------------------------------------- the recovered rule, end to end
print("\n-- the recovered DMARC rule --")


def site(provider, sending, from_addr, dmarc_at=None):
    ZONE.clear()
    put("TXT", sending, ["v=spf1 include:mailgun.org ~all"])
    if dmarc_at:
        put("TXT", "_dmarc." + dmarc_at, ["v=DMARC1; p=none"])
    return E.check_site({"domain": "site.example", "provider": provider,
                         "sending_domain": sending, "from_address": from_addr,
                         "envelope_from": from_addr})


R6 = E.CANDIDATES["dmarc"]["R6_strict_for_own_mailgun_else_fallback"]

s = site("CM Mailgun", "app.acme.com", "x@acme.com", dmarc_at="app.acme.com")
check("own Mailgun, record at the exact subdomain -> Pass", R6(s) == "Pass")

s = site("CM Mailgun", "app.acme.com", "x@acme.com", dmarc_at="acme.com")
check("own Mailgun, record only at the org domain -> Fail", R6(s) == "Fail",
      "this is the galbanicheese case; the org record exists but the setup is incomplete")
check("  and both facts are still recorded separately",
      s["dmarc"]["at_sending_domain"]["present"] is False
      and s["dmarc"]["at_sending_org_domain"]["present"] is True)

s = site("SendGrid", "em1.acme.com", "x@acme.com", dmarc_at="acme.com")
check("client-managed provider, org fallback -> Pass", R6(s) == "Pass",
      "this is the morrison-chs case")

s = site("SendGrid", "em1.acme.com", "x@acme.com", dmarc_at=None)
check("client-managed provider, nothing anywhere -> Fail", R6(s) == "Fail")

s = site("CM Mailgun", "app.galbani.com", "x@galbanicheese.com", dmarc_at="app.galbani.com")
check("cross-org sending is detected as unaligned", s["alignment"]["relaxed_aligned"] is False)
check("  but alignment does not change the adopted verdict", R6(s) == "Pass",
      "alignment is reported as its own finding, not folded into the rule")

# --------------------------------------------------------- unknown handling
print("\n-- unknown is never folded into yes or no --")
ZONE.clear()
s = E.check_site({"domain": "x.example", "provider": "CM Mailgun",
                  "sending_domain": None, "from_address": None, "envelope_from": None})
check("no sending domain -> SPF unknown, not False", s["spf"]["present"] == E.UNKNOWN)
check("no sending domain -> DMARC unknown, not False",
      s["dmarc"]["at_sending_domain"]["present"] == E.UNKNOWN)
check("no sending domain -> DKIM unknown, not False", s["dkim"]["present"] == E.UNKNOWN)

# ------------------------------------------------------------- real scan file
print("\n-- against the real 78-site scan --")
scans = sorted(f for f in os.listdir(os.path.join(ROOT, "reports")) if f.startswith("fleet-email-dns-") or f.startswith("email-dns-"))
if scans:
    scan = json.load(open(os.path.join(ROOT, "reports", scans[-1])))
    sites = scan["sites"]
    check("78 sites in the scan", len(sites) == 78, str(len(sites)))
    check("no site errored", not [s for s in sites if "error" in s])
    check("every site records both DMARC readings",
          all("at_sending_domain" in s["dmarc"] and "at_sending_org_domain" in s["dmarc"]
              for s in sites if "error" not in s))
    check("cache saved most of the work",
          scan["cache_hits"] > scan["dns_queries"] * 0.5,
          "%d hits vs %d queries" % (scan["cache_hits"], scan["dns_queries"]))
    inv_p = os.path.join(ROOT, "data", "fleet-email-inventory.json")
    if os.path.exists(inv_p):
        inv = {s["domain"]: s for s in json.load(open(inv_p))["sites"]}
        scored = [(d, inv[d]["recorded"]["dmarc"]) for d in (s["domain"] for s in sites)
                  if d in inv and inv[d]["recorded"]["dmarc"] in ("Pass", "Fail")]
        by_dom = {s["domain"]: s for s in sites}
        agree = sum(1 for d, v in scored if R6(by_dom[d]) == v)
        check("the adopted DMARC rule still reproduces the workbook at >= 97%",
              agree / float(len(scored)) >= 0.97, "%d/%d" % (agree, len(scored)))
else:
    print("  (no scan file present, skipping)")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
