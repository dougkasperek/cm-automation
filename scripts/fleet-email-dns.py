#!/usr/bin/env python3
"""
fleet-email-dns.py - email authentication posture for the whole fleet, from DNS.

Why this runs first, ahead of every other piece of fleet automation: it needs
NO host credentials, NO SSH key, NO API token and no platform decision. Public
DNS answers all of it, for every site, on every host. It is also the only part
of the fleet audit that runs anywhere, including a cloud sandbox that cannot
reach Pantheon at all.

DESIGN NOTE, read before changing anything here.

This script does not decide Pass or Fail on its own authority. The team's
workbook holds a year of Pass/Fail judgements and the rule behind them was
never written down. Inventing a different rule would silently disagree with
that history and nobody would know which side was right. So this records
FACTS, then evaluates CANDIDATE RULES against them, and `compare` scores each
candidate against the workbook. The rule that predicts the humans is the rule
the humans are using.

RECOVERED 2026-08-17, by exactly that method:

  DMARC "Pass" in the workbook means a DMARC record exists at
  `_dmarc.<sending_domain>`, NOT at the site's own domain.

That is a "provider setup completed" check, not a "brand protected" check.
Both facts are recorded here, separately and on purpose, because they answer
different questions and the difference is itself a finding.

DKIM has no discovery mechanism in DNS. A selector must already be known.
Missing therefore means UNKNOWN, never Fail. Record the real selector in the
inventory once (`dkim_selector`) and this verifies it forever after.

Subcommands
  check    live DNS for every site  ->  reports/email-dns-<stamp>.json
  compare  score candidate rules against the workbook's recorded verdicts
  report   human-readable digest of a check run

Dependency: dnspython. The rest of cm-automation is stdlib only; hand-parsing
DNS compression pointers inside a security tool is a bad trade. dnspython is
pure Python and behaves identically on macOS and a Linux runner, so the
portability contract's intent holds.
"""
import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time

try:
    import dns.resolver
    import dns.exception
except ImportError:
    sys.exit("needs dnspython:  pip install -r requirements.txt")

UNKNOWN = "unknown"

# Multi-label public suffixes relevant to organizational-domain math. Not the
# full Public Suffix List; this fleet is .com/.org/.net/.gov/.us where a
# two-label default is correct. Listed so the approximation is visible.
MULTI_SUFFIX = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "com.au", "co.nz",
    "com.br", "co.za", "com.mx",
}

# Probed in order; first hit wins. Grouped by provider so additions have an
# obvious home. Every one of these was needed by at least one real site except
# where noted as defensive.
DKIM_SELECTORS = [
    "mailo", "pic", "mx", "smtp", "k1", "krs", "mailgun", "mg", "k2", "k3",  # Mailgun
    "s1", "s2", "sendgrid",                                                  # SendGrid (CNAME)
    "selector1", "selector2",                                                # Microsoft 365
    "google", "20230601", "20210112",                                        # Google Workspace
    "pm", "postmark", "mandrill", "zoho", "fm1",                             # other ESPs
    "default", "dkim", "mail", "key1", "sig1",                               # generics
]

_cache = {}
_lock = threading.Lock()
_stats = {"queries": 0, "cache_hits": 0}


def org_domain(fqdn):
    if not fqdn:
        return None
    parts = fqdn.lower().strip(".").split(".")
    if len(parts) < 2:
        return fqdn.lower()
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_SUFFIX:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domain_of(addr):
    if not addr or "@" not in addr:
        return None
    return addr.rsplit("@", 1)[1].strip().lower()


def _resolve(name, rdtype, timeout):
    key = (rdtype, name.lower())
    with _lock:
        if key in _cache:
            _stats["cache_hits"] += 1
            return _cache[key]
    r = dns.resolver.Resolver(configure=True)
    # A timeout is not an answer, and most timeouts here are SELF-INFLICTED.
    # This tool fires ~960 queries through several workers and saturates the
    # local resolver; six domains that answer in 0.0s standalone came back as
    # timeouts mid-scan. Escalating the deadline in place does NOT help, because
    # the other workers are still hammering while the retry runs. Measured: it
    # tripled the wall clock and fixed nothing.
    #
    # So the fast path stays fast with one cheap retry for genuine blips, and
    # the real repair is `repair_failed_lookups()`, a serial second sweep over
    # just the failures once the burst has finished.
    out = None
    for attempt in (1, 2):
        r.timeout = timeout
        r.lifetime = timeout * 2
        try:
            ans = r.resolve(name, rdtype)
            if rdtype == "TXT":
                vals = ["".join(s.decode() if isinstance(s, bytes) else s for s in rr.strings)
                        for rr in ans]
            else:
                vals = [str(rr.target).rstrip(".") for rr in ans]
            out = {"status": "ok", "records": vals}
            break
        except dns.resolver.NXDOMAIN:
            out = {"status": "nxdomain", "records": []}
            break
        except dns.resolver.NoAnswer:
            out = {"status": "noanswer", "records": []}
            break
        except dns.resolver.NoNameservers:
            out = {"status": "nonameservers", "records": []}
            break
        except dns.exception.Timeout:
            out = {"status": "timeout", "records": [], "attempts": attempt}
            continue
        except Exception as e:                          # noqa: BLE001 record, never guess
            out = {"status": "error:" + type(e).__name__, "records": []}
            break
    with _lock:
        _cache[key] = out
        _stats["queries"] += 1
    return out


def txt(name, timeout=5.0):
    return _resolve(name, "TXT", timeout)


def cname(name, timeout=5.0):
    return _resolve(name, "CNAME", timeout)


# A lookup that did not complete is NOT an answer. These two statuses mean the
# resolver reached an authoritative answer of "there is nothing here", which is
# a real fact. Anything else (timeout, SERVFAIL, no reachable nameserver) means
# we do not know, and the difference has to survive into the report.
RESOLVED = ("ok", "nxdomain", "noanswer")


def repair_failed_lookups(timeout=6.0, budget_seconds=45.0):
    """Re-query, serially, the names whose lookup did not complete.

    Most in-scan failures are self-inflicted: everything was in flight at once
    and the resolver dropped packets. Six domains that answered in 0.0s
    standalone timed out mid-scan. Retrying them one at a time afterwards
    recovers them in seconds.

    Two things keep this from blowing up, both learned the hard way:

    1. **Per-zone short circuit.** If a domain's nameservers are genuinely
       unreachable, EVERY name under it fails, including all ~112 DKIM selector
       probes. Retrying each serially at 6s is minutes of nothing. So the zones
       are probed one name each first; a zone that fails again is abandoned and
       its remaining names are not retried.
    2. **A wall-clock budget**, and what it skipped is REPORTED, never silently
       dropped. A cap you cannot see reads as "we checked everything".

    Mutates the cache in place. Callers re-derive from the warm cache, so no
    site is re-queried over the network.
    """
    with _lock:
        failed = sorted(k for k, v in _cache.items() if v["status"] not in RESOLVED)

    by_zone = {}
    for key in failed:
        by_zone.setdefault(org_domain(key[1]), []).append(key)

    started = time.time()
    recovered, dead_zones, skipped = 0, [], 0

    def attempt(rdtype, name):
        r = dns.resolver.Resolver(configure=True)
        r.timeout = timeout
        r.lifetime = timeout * 2
        try:
            ans = r.resolve(name, rdtype)
            if rdtype == "TXT":
                vals = ["".join(s.decode() if isinstance(s, bytes) else s for s in rr.strings)
                        for rr in ans]
            else:
                vals = [str(rr.target).rstrip(".") for rr in ans]
            return {"status": "ok", "records": vals, "via": "repair"}
        except dns.resolver.NXDOMAIN:
            return {"status": "nxdomain", "records": [], "via": "repair"}
        except dns.resolver.NoAnswer:
            return {"status": "noanswer", "records": [], "via": "repair"}
        except Exception:                               # noqa: BLE001 still unknown
            return None

    for zone, keys in sorted(by_zone.items()):
        if time.time() - started > budget_seconds:
            skipped += len(keys)
            continue
        # Probe the zone once, on its shortest name, before spending time on
        # the rest of it.
        probe = min(keys, key=lambda k: len(k[1]))
        res = attempt(*probe)
        if res is None:
            dead_zones.append(zone)
            skipped += len(keys) - 1
            continue
        with _lock:
            _cache[probe] = res
        recovered += 1
        for key in keys:
            if key == probe:
                continue
            if time.time() - started > budget_seconds:
                skipped += 1
                continue
            res = attempt(*key)
            if res is not None:
                with _lock:
                    _cache[key] = res
                recovered += 1

    return {"retried": len(failed), "recovered": recovered,
            "unreachable_zones": sorted(dead_zones), "skipped": skipped,
            "seconds": round(time.time() - started, 1)}


def parse_spf(res):
    if res["status"] not in RESOLVED:
        return {"present": UNKNOWN, "lookup_status": res["status"],
                "reason": "DNS lookup did not complete, so absence of a record "
                          "is not established"}
    records = res["records"]
    spf = [r for r in records if r.lower().startswith("v=spf1")]
    if not spf:
        return {"present": False}
    rec = spf[0]
    toks = rec.split()
    qualifier = None
    for t in toks:
        if t.lower().endswith("all"):
            qualifier = t
    return {
        "present": True, "record": rec,
        "includes": [t.split(":", 1)[1] for t in toks if t.lower().startswith("include:")],
        "all_qualifier": qualifier,
        "multiple_spf_records": len(spf) > 1,      # RFC violation, receivers may permerror
    }


def parse_dmarc(res):
    if res["status"] not in RESOLVED:
        return {"present": UNKNOWN, "lookup_status": res["status"],
                "reason": "DNS lookup did not complete, so absence of a record "
                          "is not established"}
    records = res["records"]
    d = [r for r in records if r.lower().startswith("v=dmarc1")]
    if not d:
        return {"present": False}
    rec = d[0]
    tags = {}
    for part in rec.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip().lower()] = v.strip()
    return {
        "present": True, "record": rec, "policy": tags.get("p"),
        "subdomain_policy": tags.get("sp"), "pct": tags.get("pct"),
        "adkim": tags.get("adkim", "r"), "aspf": tags.get("aspf", "r"),
        "rua": tags.get("rua"), "multiple_dmarc_records": len(d) > 1,
    }


def find_dkim(base_domains, override=None):
    """Locate a DKIM key.

    Two things this gets right that a naive version does not:
      1. A DKIM key may be published as a CNAME delegating to the provider.
         SendGrid does exactly this, so a TXT-only probe reports nothing on a
         perfectly configured site.
      2. The selector may live on the organizational domain rather than the
         sending subdomain, again SendGrid's pattern.

    Returns present True with the selector, or present UNKNOWN. Never False:
    DNS has no way to enumerate selectors, so absence is not evidence.
    """
    sels = ([override] if override else []) + [s for s in DKIM_SELECTORS if s != override]
    tried, unresolved = 0, 0
    for base in [b for b in base_domains if b]:
        for sel in sels:
            name = "%s._domainkey.%s" % (sel, base)
            tried += 1
            t = txt(name)
            if t["status"] not in RESOLVED:
                unresolved += 1
            hit = [r for r in t["records"] if "p=" in r or r.lower().startswith("v=dkim1")]
            if hit:
                return {"present": True, "selector": sel, "at": base,
                        "via": "txt", "record": hit[0][:200], "probes": tried}
            c = cname(name)
            if c["records"]:
                return {"present": True, "selector": sel, "at": base,
                        "via": "cname", "target": c["records"][0], "probes": tried}
    return {"present": UNKNOWN, "selector": None, "probes": tried,
            "unresolved_probes": unresolved,
            "reason": "no key at %d probed selector/domain combinations (%d of those "
                      "lookups did not complete); DKIM selectors cannot be enumerated "
                      "from DNS, so this is unknown, not a failure" % (tried, unresolved)}


def check_site(site):
    domain = site["domain"]
    sending = (site.get("sending_domain") or "").strip().lower() or None
    from_dom = domain_of(site.get("from_address"))
    env_dom = domain_of(site.get("envelope_from"))

    out = {"domain": domain, "hosted": site.get("hosted"), "provider": site.get("provider"),
           "sending_domain": sending, "from_domain": from_dom, "envelope_domain": env_dom}

    # SPF authenticates the ENVELOPE sender, so it is checked on the envelope
    # or sending domain, never on the site's own domain.
    spf_target = sending or env_dom
    if spf_target:
        out["spf"] = parse_spf(txt(spf_target))
        out["spf"]["checked_at"] = spf_target
    else:
        out["spf"] = {"present": UNKNOWN, "checked_at": None,
                      "reason": "no sending or envelope domain recorded"}

    out["dkim"] = find_dkim([spf_target, org_domain(spf_target), from_dom, org_domain(from_dom)],
                            override=site.get("dkim_selector"))

    # DMARC, both readings, recorded separately because they answer different
    # questions:
    #   sending  - is the provider's own setup complete? (the workbook's rule)
    #   from     - is the domain that appears to recipients actually protected?
    dm = {}
    if spf_target:
        p = parse_dmarc(txt("_dmarc." + spf_target))
        p["checked_at"] = "_dmarc." + spf_target
        p["via_org_fallback"] = False
        # Record the exact-subdomain answer and the org-fallback answer as TWO
        # SEPARATE FACTS, never collapsed. DMARC's organizational-domain
        # fallback is part of the spec (mail from em1420.example.com is
        # governed by _dmarc.example.com when the subdomain has none), but the
        # team applies it only to providers it does not control. Collapsing
        # these two into one answer is what made an earlier version of this
        # script disagree with the workbook in both directions at once.
        dm["at_sending_domain"] = p
        org = org_domain(spf_target)
        if p.get("present"):
            dm["at_sending_org_domain"] = p
        elif org and org != spf_target:
            p2 = parse_dmarc(txt("_dmarc." + org))
            p2["checked_at"] = "_dmarc." + org
            p2["via_org_fallback"] = True
            dm["at_sending_org_domain"] = p2
        else:
            dm["at_sending_org_domain"] = p
    else:
        dm["at_sending_domain"] = {"present": UNKNOWN, "reason": "no sending domain recorded"}
        dm["at_sending_org_domain"] = dm["at_sending_domain"]

    dm_target = from_dom or domain
    p = parse_dmarc(txt("_dmarc." + dm_target))
    p["checked_at"] = "_dmarc." + dm_target
    p["via_org_fallback"] = False
    if not p.get("present"):
        org = org_domain(dm_target)
        if org and org != dm_target:
            p2 = parse_dmarc(txt("_dmarc." + org))
            if p2.get("present"):
                p2["checked_at"] = "_dmarc." + org
                p2["via_org_fallback"] = True
                p = p2
    dm["at_from_domain"] = p
    out["dmarc"] = dm

    fo, so = org_domain(from_dom), org_domain(spf_target)
    out["alignment"] = {
        "from_org": fo, "sending_org": so,
        "relaxed_aligned": bool(fo and so and fo == so),
        "strict_aligned": bool(from_dom and spf_target and from_dom == spf_target),
        "envelope_matches_from": bool(env_dom and from_dom and env_dom == from_dom),
    }
    return out


# ---------------------------------------------------------------------------
# Candidate rules. `compare` scores these; none is authoritative by itself.
# ---------------------------------------------------------------------------

def _pf(b):
    return "Pass" if b else "Fail"


CANDIDATES = {
    "spf": {
        # ADOPTED. Note the qualifier variant loses on `v=spf1
        # redirect=_spf.google.com`, which is valid and has no `all` token.
        "R1_record_present": lambda s: _pf(s["spf"].get("present") is True),
        "R2_present_and_has_include": lambda s: _pf(
            s["spf"].get("present") is True and bool(s["spf"].get("includes"))),
        "R3_present_and_all_qualifier": lambda s: _pf(
            s["spf"].get("present") is True
            and (s["spf"].get("all_qualifier") or "").lower() in ("~all", "-all")),
    },
    "dkim": {
        "R1_key_found_anywhere": lambda s: _pf(s["dkim"].get("present") is True),
    },
    "dmarc": {
        "R1_present_at_from_domain": lambda s: _pf(
            s["dmarc"]["at_from_domain"].get("present") is True),
        "R2_present_at_SENDING_domain": lambda s: _pf(
            s["dmarc"]["at_sending_domain"].get("present") is True),
        "R5_sending_org_fallback_allowed": lambda s: _pf(
            s["dmarc"]["at_sending_org_domain"].get("present") is True),
        # ADOPTED, recovered from the workbook 2026-08-17 at 66/68.
        # clevermethod holds ITS OWN Mailgun account to a strict standard: the
        # DMARC record must exist at the exact sending subdomain it configured.
        # For a provider the client controls, the spec's org-domain fallback is
        # accepted, because finishing that setup is not clevermethod's call.
        # The two rows this still misses are the two where a human recorded an
        # observed SMTP send failure; no DNS check can reach those.
        "R6_strict_for_own_mailgun_else_fallback": lambda s: _pf(
            (s["dmarc"]["at_sending_domain"].get("present") is True)
            if (s.get("provider") or "").strip().lower() == "cm mailgun"
            else (s["dmarc"]["at_sending_org_domain"].get("present") is True)),
        "R3_enforcing_at_from_domain": lambda s: _pf(
            (s["dmarc"]["at_from_domain"].get("policy") or "none").lower()
            in ("quarantine", "reject")),
        "R4_from_domain_and_aligned": lambda s: _pf(
            s["dmarc"]["at_from_domain"].get("present") is True
            and s["alignment"]["relaxed_aligned"]),
    },
}


def cmd_check(a):
    inv = json.load(open(a.inventory))
    sites = inv["sites"][: a.limit] if a.limit else inv["sites"]

    # A SITE WITH NO DOMAIN CANNOT BE ASKED THIS QUESTION, and is recorded as
    # skipped rather than dropped. Six Pantheon entries carry `domain: null` --
    # machine names nobody has written a domain for -- and every email fact is
    # a DNS lookup against a domain, so there is nothing to look up.
    #
    # This crashed on 2026-08-23: `results.sort(key=lambda r: r["domain"])`
    # cannot order None against a string, so the run died AFTER doing all 84
    # lookups. It had never been hit because the inventory grew from 78 sites
    # to 84 after the last successful run, and the six it gained are exactly
    # the ones with no domain.
    #
    # Skipping them silently would be the easy fix and the wrong one: the
    # report would say 78 with nothing explaining why, and "we did not check
    # these" would be indistinguishable from "these are fine".
    skipped = [s2.get("site_id") or s2.get("host_site_name") or "?"
               for s2 in sites if not s2.get("domain")]
    sites = [s2 for s2 in sites if s2.get("domain")]
    if skipped:
        print("  skipping %d site(s) with no domain recorded: %s"
              % (len(skipped), ", ".join(sorted(skipped))), file=sys.stderr)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(check_site, s): s["domain"] for s in sites}
        done = 0
        for f in concurrent.futures.as_completed(futs):
            done += 1
            try:
                results.append(f.result())
            except Exception as e:                      # noqa: BLE001
                results.append({"domain": futs[f], "error": "%s: %s" % (type(e).__name__, e)})
            if done % 20 == 0 or done == len(sites):
                print("  %d/%d" % (done, len(sites)), file=sys.stderr)
    # Second sweep: everything that failed, serially, now that nothing else is
    # competing. Then re-derive every site from the warm cache, which costs no
    # network at all.
    # Off by default, and that is a considered choice rather than laziness.
    # Measured: the repair pass cost 50-60s and recovered 0 on a run whose
    # failures were transient, while a clean network (the CI runner) had few
    # failures to begin with. More importantly, this tool is meant to run on a
    # schedule and feed a ledger. A transient timeout resolves itself on the
    # next run and shows up as a lookup-quality trend rather than a finding,
    # which is the whole point of preferring the diff over the snapshot. Use
    # --repair for a one-off run where the answer is needed immediately.
    rep = repair_failed_lookups() if a.repair else {
        "retried": 0, "recovered": 0, "unreachable_zones": [], "skipped": 0,
        "seconds": 0.0, "skipped_reason": "repair pass not requested (--repair)"}
    if rep["retried"]:
        print("  repair pass: %d failed lookup(s), %d recovered, %d skipped, %.1fs"
              % (rep["retried"], rep["recovered"], rep["skipped"], rep["seconds"]),
              file=sys.stderr)
        if rep["unreachable_zones"]:
            print("  zones still unreachable: %s" % ", ".join(rep["unreachable_zones"]),
                  file=sys.stderr)
        if rep["recovered"]:
            results = [check_site(s) for s in sites]

    # Defensive: the filter above means no None should reach here, but an
    # ordering that raises on one is how the whole run was lost once already.
    results.sort(key=lambda r: r.get("domain") or "")
    payload = {"kind": "email-dns", "site_count": len(results),
               "repair": rep,
               # Named, not counted. A reader comparing 78 against an 84-site
               # fleet needs to know which six and why, not just that six are
               # missing.
               "sites_without_domain": sorted(skipped),
               "unresolved_lookups": sum(1 for v in _cache.values()
                                         if v["status"] not in RESOLVED),
               "dns_queries": _stats["queries"], "cache_hits": _stats["cache_hits"],
               "sites": results}
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    path = os.path.join(a.out, "fleet-email-dns-%s.json" % a.stamp)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    print("%d sites, %d unique DNS queries, %d cache hits -> %s"
          % (len(results), _stats["queries"], _stats["cache_hits"], path))
    return 0


def cmd_compare(a):
    inv = {s["domain"]: s for s in json.load(open(a.inventory))["sites"]}
    scan = {s["domain"]: s for s in json.load(open(a.scan))["sites"] if "error" not in s}
    print("# Candidate rules scored against the workbook's recorded cells\n")
    for field, rules in CANDIDATES.items():
        rows = [(d, inv[d]["recorded"].get(field)) for d in scan if d in inv]
        scored = [(d, v) for d, v in rows if v in ("Pass", "Fail")]
        print("## %s   (%d scanned, %d with a recorded verdict, %d blank)\n"
              % (field.upper(), len(rows), len(scored), len(rows) - len(scored)))
        table = []
        for name, fn in rules.items():
            agree, misses = 0, []
            for d, recorded in scored:
                got = fn(scan[d])
                if got == recorded:
                    agree += 1
                else:
                    misses.append("%s (sheet %s, computed %s)" % (d, recorded, got))
            acc = agree / float(len(scored)) if scored else 0.0
            table.append((acc, name, agree, misses))
        table.sort(reverse=True)
        for acc, name, agree, misses in table:
            print("  %-34s %3d/%-3d  %5.1f%%" % (name, agree, len(scored), acc * 100))
        acc, name, agree, misses = table[0]
        print("\n  BEST: %s at %.1f%%" % (name, acc * 100))
        if misses:
            print("  unexplained rows:")
            for m in misses:
                print("    - %s" % m)
        print()
    return 0


def cmd_report(a):
    scan = json.load(open(a.scan))
    sites = [s for s in scan["sites"] if "error" not in s]
    print("# Fleet email authentication, %d sites\n" % len(sites))

    def grp(label, items, note):
        print("**%s: %d**" % (label, len(items)))
        if items:
            print("  " + ", ".join(sorted(items)[:14]) + (" ..." if len(items) > 14 else ""))
        print("  %s\n" % note)

    grp("No SPF record on the sending domain",
        [s["domain"] for s in sites if s["spf"].get("present") is False],
        "Resolver returned an authoritative answer and there is no SPF record.")
    grp("SPF could not be determined (lookup did not complete)",
        [s["domain"] for s in sites if s["spf"].get("present") == UNKNOWN],
        "Not a finding about the domain, a finding about the lookup. Re-run before acting.")
    grp("No DKIM key found at any probed selector",
        [s["domain"] for s in sites if s["dkim"].get("present") is not True],
        "UNKNOWN, not failure. Record the real selector in the inventory to close these.")
    grp("DKIM probing was unreliable (some lookups did not complete)",
        [s["domain"] for s in sites if s["dkim"].get("unresolved_probes")],
        "Selector probing hit DNS failures, so even the unknown is less certain than usual.")
    own = [s for s in sites if (s.get("provider") or "").strip().lower() == "cm mailgun"]
    grp("clevermethod Mailgun setup incomplete (no DMARC at the sending subdomain)",
        [s["domain"] for s in own if s["dmarc"]["at_sending_domain"].get("present") is False],
        "The workbook's own Fail condition, on infrastructure clevermethod controls and can fix.")
    grp("No DMARC on the domain recipients actually see",
        [s["domain"] for s in sites if s["dmarc"]["at_from_domain"].get("present") is False],
        "Nothing protects the brand domain from spoofing.")
    grp("DMARC could not be determined (lookup did not complete)",
        [s["domain"] for s in sites
         if s["dmarc"]["at_from_domain"].get("present") == UNKNOWN
         or s["dmarc"]["at_sending_domain"].get("present") == UNKNOWN],
        "Not a finding about the domain. Re-run before acting.")
    grp("DMARC published but p=none on the From domain",
        [s["domain"] for s in sites
         if s["dmarc"]["at_from_domain"].get("present")
         and (s["dmarc"]["at_from_domain"].get("policy") or "").lower() == "none"],
        "Monitoring only. Instructs receivers to take no action.")
    grp("From domain not aligned with sending domain",
        [s["domain"] for s in sites if not s["alignment"]["relaxed_aligned"]],
        "DMARC fails on unaligned mail even when SPF and DKIM both pass.")
    grp("DMARC inherited from the organizational domain",
        [s["domain"] for s in sites if s["dmarc"]["at_from_domain"].get("via_org_fallback")],
        "Covered, but by a record this site does not control.")
    grp("More than one SPF record",
        [s["domain"] for s in sites if s["spf"].get("multiple_spf_records")],
        "RFC violation; receivers may permerror.")
    return 0


def main():
    # Piping `report` into head or less closes stdout early; without this the
    # tool dies with a BrokenPipeError traceback instead of just stopping.
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass                                # not available on every platform

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--inventory", required=True)
    c.add_argument("--out", default="./reports")
    c.add_argument("--stamp", required=True)
    c.add_argument("--workers", type=int, default=8)
    c.add_argument("--repair", action="store_true",
                   help="after the main pass, serially re-query lookups that did not "
                        "complete. Slower. Off by default: on a scheduled run the next "
                        "run resolves transients for free.")
    c.add_argument("--limit", type=int)
    c.set_defaults(fn=cmd_check)
    p = sub.add_parser("compare")
    p.add_argument("--inventory", required=True)
    p.add_argument("--scan", required=True)
    p.set_defaults(fn=cmd_compare)
    r = sub.add_parser("report")
    r.add_argument("--scan", required=True)
    r.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
