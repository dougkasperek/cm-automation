#!/usr/bin/env python3
"""
fleet-vuln.py - read-only Wordfence Intelligence V3 feed client.

Step 3 of docs/VULN-INTEL-REVIEW.md. It fetches the vulnerability feed and
reports what is in it. It does NOT match versions, does not score, and does
not write to the ledger; that is step 4, and it is built offline against the
fixture this script extracts.

WHY THE PROBE CLASSIFIES ITS OWN FAILURES
-----------------------------------------
`fleet-nexcess.py probe` printed one word for a DNS failure, a TLS trust
failure and a dead host alike, and sent a week of work at the wrong vendor.
Then a CI step ended in `|| true`, printed "unauthorised", went green, and
failed three steps later as a traceback. Both rows are in CLAUDE.md's table.

So: every outcome below is distinct, `probe` returns a non-zero exit code for
anything that is not `ok`, and 401 and 403 are never collapsed. On this vendor
that distinction is load-bearing -- 401 is Wordfence's application rejecting
the key, 403 is an edge refusing the request before the key is ever read.

THE SPEC THIS IS WRITTEN AGAINST
--------------------------------
https://www.wordfence.com/help/wordfence-intelligence/v3-accessing-and-consuming-the-vulnerability-data-feed/
read 2026-08-30. Three facts in VULN-INTEL-REVIEW.md are wrong against it and
are corrected here rather than repeated:

  - The rate limit is NOT "1 per 30 minutes". The vendor states no number, only
    a 429 when requesting too often. So this backs off on 429; it does not
    schedule around a cadence nobody published.
  - The feed size is NOT "~120 MB". The vendor states no size. `probe` measures
    it, which is why the number it prints is the first real one we will have.
  - Wordfence V3 carries NO exploitation flag. The review's table said it did.
    KEV is the only exploitation signal in this design.

PRODUCTION, NOT SCANNER
-----------------------
Two feeds exist. `scanner` carries enough to match and nothing else; the
severity mapping in docs/SEVERITY.md needs `cvss` and `cwe`, which are
production-only fields. Both are fetchable here so the difference stays
visible, but production is the default.

ATTRIBUTION IS A REQUIREMENT, NOT A FOOTNOTE
--------------------------------------------
Defiant's licence grants reuse provided any copy carries a hyperlink to the
vulnerability record plus their copyright notice and licence text. MITRE
separately requires its copyright shown for any MITRE record displayed to an
end user. A page behind Cloudflare Access is still displaying it. `copyrights`
is therefore carried through every extraction here rather than stripped.

READ-ONLY. Only GET is ever issued.
"""

import argparse
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://www.wordfence.com/api/intelligence/v3/vulnerabilities"
FEEDS = ("production", "scanner")

# Verdicts. Distinct on purpose; see the header.
OK = "ok"
UNAUTHORISED = "unauthorised"
FORBIDDEN = "forbidden"
RATE_LIMITED = "rate-limited"
BAD_BODY = "bad-body"
UNREACHABLE = "unreachable"
HTTP_ERROR = "http-error"

RUN_ID = re.compile(r"^(?P<kind>.+)-(?P<stamp>\d{4}-\d{2}-\d{2}_\d{4})$")


# ---------------------------------------------------------------------------
# the catalogue we are matching against
# ---------------------------------------------------------------------------

def catalogue(path):
    """Current lowercase slugs per site, from history/components.jsonl.

    Grouped by COHORT and merged, never "the latest run". `health` and
    `health-nexcess` are two transports over disjoint sites, and taking one
    latest run wiped 52 Pantheon sites off the dashboard once already.

    Returns (slug -> set of sites, run_ids used). Lowercase because Wordfence
    publishes lowercase slugs and WP-CLI reports the on-disk directory name:
    a case-sensitive match on `pdfembedder-premium` hits 2 of our 12 sites.
    """
    if not os.path.exists(path):
        return {}, []
    latest = {}
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        rows.append(r)
        m = RUN_ID.match(r.get("run_id") or "")
        if not m:
            continue
        kind, stamp = m.group("kind"), m.group("stamp")
        if kind not in latest or stamp > latest[kind][1]:
            latest[kind] = (r["run_id"], stamp)
    keep = {v[0] for v in latest.values()}
    slugs = {}
    for r in rows:
        if r.get("run_id") not in keep:
            continue
        s = (r.get("slug") or "").lower()
        if not s:
            continue
        slugs.setdefault(s, set()).add(r.get("site"))
    return slugs, sorted(keep)


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def fetch(feed, key, timeout=180):
    """GET one feed. Returns (verdict, detail, status, raw_bytes).

    Never raises for an expected failure; the caller decides the exit code.
    """
    url = "%s/%s" % (BASE, feed)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer %s" % key)
    # The feed is large and the vendor publishes no size. Ask for gzip rather
    # than discovering the cost on a metered runner.
    req.add_header("Accept-Encoding", "gzip")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            return OK, None, resp.status, raw
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()[:400]
        except Exception:                              # noqa: BLE001
            pass
        detail = body.decode("utf-8", "replace").strip() or None
        if e.code == 401:
            # The application read the key and refused it. Regenerate it, or
            # check the secret has no trailing whitespace.
            return UNAUTHORISED, detail, e.code, b""
        if e.code == 403:
            # NOT the same thing. An edge refused the request before the key
            # was read -- on Nexcess this exact distinction cost five days.
            return FORBIDDEN, detail, e.code, b""
        if e.code == 429:
            return RATE_LIMITED, detail, e.code, b""
        return HTTP_ERROR, detail, e.code, b""
    except Exception as e:                             # noqa: BLE001 - reported
        return UNREACHABLE, "%s: %s" % (type(e).__name__, e), None, b""


def parse(raw):
    """The feed is an object keyed by vulnerability UUID.

    A 200 whose body is a web page is the `ok  site list returned` row in
    CLAUDE.md's table. Judge the body, not the status code.
    """
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as e:                             # noqa: BLE001
        return None, "body is not JSON (%s)" % type(e).__name__
    if not isinstance(d, dict) or not d:
        return None, "body is %s, expected a non-empty object" % type(d).__name__
    sample = next(iter(d.values()))
    if not isinstance(sample, dict) or "software" not in sample:
        return None, "records have no `software` key; not the V3 shape"
    return d, None


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def probe(args):
    key = os.environ.get("WF_KEY", "").strip()
    if not key:
        print("FAIL  WF_KEY is not set in the environment.")
        return 2

    verdict, detail, status, raw = fetch(args.feed, key)
    if verdict != OK:
        print("%-13s %s  HTTP %s" % (verdict, args.feed, status))
        if detail:
            print("  body: %s" % detail)
        if verdict == FORBIDDEN:
            print("  NOTE: 403 is an edge refusing the request, not the key "
                  "being rejected. 401 would be the key.")
        if verdict == RATE_LIMITED:
            print("  NOTE: the vendor publishes no rate limit. Back off and "
                  "retry; email wfi-support@wordfence.com for a higher one.")
        return 1

    d, why = parse(raw)
    if d is None:
        print("%-13s %s  HTTP %s  %s bytes" % (BAD_BODY, args.feed, status, len(raw)))
        print("  %s" % why)
        return 1

    slugs, runs = catalogue(args.components)

    # Slug-level only. This is NOT a count of vulnerable sites: no version has
    # been compared. Labelled here so the number cannot be quoted as one.
    feed_slugs = {}
    for vid, rec in d.items():
        for sw in rec.get("software") or []:
            s = (sw.get("slug") or "").lower()
            if s:
                feed_slugs.setdefault(s, set()).add(vid)

    hits = sorted(set(slugs) & set(feed_slugs))
    unpatched = sum(1 for rec in d.values()
                    for sw in (rec.get("software") or [])
                    if sw.get("patched") is False)

    print("%-13s %s  HTTP %s" % (OK, args.feed, status))
    print("  %s bytes decoded, %s vulnerability records" % (len(raw), len(d)))
    print("  %s distinct slugs in the feed; %s records have patched=false"
          % (len(feed_slugs), unpatched))
    print()
    if not slugs:
        print("  catalogue: NOT READ. %s is absent, so the intersection below "
              "is unmeasured, not zero." % args.components)
        return 0
    print("  catalogue: %s slugs over %s sites, from %s"
          % (len(slugs), len({s for v in slugs.values() for s in v}), ", ".join(runs)))
    print("  %s of our slugs appear in the feed at all." % len(hits))
    print("  This is a SLUG intersection. No version has been compared, so it "
          "is an upper bound on\n  exposure and NOT a count of vulnerable "
          "sites. That is step 4.")
    print()
    for s in hits[:args.show]:
        print("    %-40s %2s site(s)  %2s record(s)"
              % (s, len(slugs[s]), len(feed_slugs[s])))
    if len(hits) > args.show:
        print("    ... and %s more (raise --show)" % (len(hits) - args.show))
    return 0


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------

def fixture(args):
    """Extract the records for one slug, verbatim, as a test fixture.

    Verbatim including `copyrights`: the licence requires the notice travel
    with the data, and a fixture is a copy. It is also the only way step 4 is
    testable without a key -- the comparator is developed offline against this
    file, so the feed is fetched once and never again from a laptop.
    """
    key = os.environ.get("WF_KEY", "").strip()
    if not key:
        print("FAIL  WF_KEY is not set in the environment.")
        return 2
    verdict, detail, status, raw = fetch(args.feed, key)
    if verdict != OK:
        print("%-13s %s  HTTP %s  %s" % (verdict, args.feed, status, detail or ""))
        return 1
    d, why = parse(raw)
    if d is None:
        print("%-13s %s" % (BAD_BODY, why))
        return 1

    want = args.slug.lower()
    out = {vid: rec for vid, rec in d.items()
           if any((sw.get("slug") or "").lower() == want
                  for sw in (rec.get("software") or []))}
    if not out:
        # An empty fixture that looks like a successful extraction is exactly
        # the bug this repo keeps making. Refuse instead.
        print("FAIL  no record in the %s feed mentions slug %r. Nothing written."
              % (args.feed, args.slug))
        return 1
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s  (%s record(s) for %r from the %s feed)"
          % (args.out, len(out), args.slug, args.feed))
    for vid, rec in sorted(out.items()):
        for sw in rec.get("software") or []:
            if (sw.get("slug") or "").lower() != want:
                continue
            av = sw.get("affected_versions") or {}
            print("  %s  cve=%s  patched=%s  ranges=%s  fixed=%s"
                  % (vid, rec.get("cve"), sw.get("patched"), len(av),
                     ",".join(sw.get("patched_versions") or []) or "-"))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("probe", help="does the key work, and what is in the feed?")
    pr.add_argument("--feed", choices=FEEDS, default="production")
    pr.add_argument("--components", default="history/components.jsonl")
    pr.add_argument("--show", type=int, default=40)
    pr.set_defaults(fn=probe)

    fx = sub.add_parser("fixture", help="extract one slug's records as a test fixture")
    fx.add_argument("--slug", required=True)
    fx.add_argument("--feed", choices=FEEDS, default="production")
    fx.add_argument("--out", required=True)
    fx.set_defaults(fn=fixture)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
