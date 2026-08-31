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
    a 429 when requesting too often. MEASURED 2026-08-30 across three runs:

        9 seconds apart   -> 429 refused
        22.5 minutes      -> 429 refused
        36.5 minutes      -> 200 allowed

    So the window is somewhere BETWEEN 22.5 and 36.5 minutes. That is
    consistent with the "1 per 30 minutes" figure the write-ups gave and still
    does not prove it; the honest statement is the bracket, not a number.
    The consequence is what matters: one fetch per run, cached between runs,
    and `--allow-stale` so a re-run inside the window reports on the copy it
    has rather than failing.
  - The feed size is NOT "~120 MB". MEASURED 2026-08-30: **153,806,638 bytes
    decoded, 39,455 records**, of which 11,823 have `patched=false`.

ONE FETCH PER RUN. THIS COST A CI RUN ON 2026-08-30.
----------------------------------------------------
The first version of this script fetched inside BOTH `probe` and `fixture`, so
the workflow pulled 147 MB twice in nine seconds and the second call was
refused. The feed is expensive and rate-limited, so it is fetched ONCE by
`fetch` and every other subcommand reads that file. `--feed-file` is how they
do it; passing no file still fetches, which keeps a one-off laptop run to one
command.
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
import datetime
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import vercmp                                              # noqa: E402

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


def installs(path):
    """Every current install as a dict: site, slug, version, type, status.

    Same cohort merge as `catalogue`. One row per install, so a site carrying a
    component twice appears twice -- `hoffmanscheese` has pdfembedder-premium
    at 3.2 inactive beside 5.1.4 active, and the inactive copy is still files
    on disk. Counting per SITE happens afterwards, so both views stay possible.
    """
    if not os.path.exists(path):
        return []
    latest, rows = {}, []
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
    return [{"site": r.get("site"), "slug": (r.get("slug") or "").lower(),
             "version": r.get("version"), "type": r.get("type"),
             "status": r.get("status")}
            for r in rows if r.get("run_id") in keep]


def by_slug(feed):
    """slug -> [(vuln_id, record, software_entry)], lowercased.

    Wordfence publishes lowercase slugs; WP-CLI reports the on-disk directory
    name, whose casing differs per site. A case-sensitive match on
    `pdfembedder-premium` would hit 2 of our 13 sites and call the other 11
    clean.
    """
    idx = {}
    for vid, rec in feed.items():
        for sw in rec.get("software") or []:
            sl = (sw.get("slug") or "").lower()
            if sl:
                idx.setdefault(sl, []).append((vid, rec, sw))
    return idx


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


def _meta_path(path):
    return path + ".meta.json"


def write_meta(path, feed, raw, records):
    """When was this feed pulled, and what was in it?

    A cached feed with no age is the same shape as every row in CLAUDE.md's
    table: a value that looks current because nothing says otherwise. Every
    command that reads a cached file prints this.
    """
    meta = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feed": feed,
        "bytes": len(raw),
        "records": records,
    }
    with open(_meta_path(path), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
        fh.write("\n")
    return meta


def feed_age(path):
    """(fetched_at, minutes_old) for a cached feed, or (None, None).

    None is reported as "age unknown", never as fresh.
    """
    mp = _meta_path(path)
    if not os.path.exists(mp):
        return None, None
    try:
        m = json.load(open(mp, encoding="utf-8"))
        t = datetime.datetime.strptime(m["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
        t = t.replace(tzinfo=datetime.timezone.utc)
    except Exception:                                      # noqa: BLE001
        return None, None
    delta = datetime.datetime.now(datetime.timezone.utc) - t
    return m["fetched_at"], int(delta.total_seconds() // 60)


def announce_age(path):
    """Print how old a cached feed is, before any number derived from it."""
    when, mins = feed_age(path)
    if when is None:
        print("  FEED AGE UNKNOWN. %s has no .meta.json beside it, so nothing"
              % os.path.basename(path))
        print("  below can be dated. Treat it as possibly stale.")
    else:
        print("  Feed pulled %s (%d minute(s) ago)." % (when, mins))
    print()


def read_feed(args):
    """The feed bytes, from a file if given and otherwise from the network.

    Every subcommand goes through here so that no code path can issue a second
    fetch by accident -- which is exactly what happened on 2026-08-30.

    Returns (raw_bytes, verdict, detail, status). raw is b"" unless verdict is
    OK.
    """
    path = getattr(args, "feed_file", None)
    if path:
        if not os.path.exists(path):
            return b"", UNREACHABLE, "no such feed file: %s" % path, None
        raw = open(path, "rb").read()
        if not raw:
            # An empty cache file that reads as a successful fetch is the bug
            # this repo keeps making. Refuse it.
            return b"", BAD_BODY, "feed file %s is empty" % path, None
        return raw, OK, None, None
    key = os.environ.get("WF_KEY", "").strip()
    if not key:
        return b"", UNAUTHORISED, "WF_KEY is not set in the environment", None
    verdict, detail, status, raw = fetch(args.feed, key)
    return raw, verdict, detail, status


def report_failure(verdict, detail, status, feed):
    print("%-13s %s  HTTP %s" % (verdict, feed, status))
    if detail:
        print("  body: %s" % detail)
    if verdict == FORBIDDEN:
        print("  NOTE: 403 is an edge refusing the request, not the key being "
              "rejected. 401 would be the key.")
    if verdict == RATE_LIMITED:
        print("  NOTE: measured 2026-08-30, two full-feed requests nine seconds "
              "apart trips this.")
        print("        Fetch ONCE with `fetch --out`, then pass --feed-file to "
              "everything else.")


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
    raw, verdict, detail, status = read_feed(args)
    if verdict != OK:
        report_failure(verdict, detail, status, args.feed)
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
    if getattr(args, "feed_file", None):
        announce_age(args.feed_file)
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
    raw, verdict, detail, status = read_feed(args)
    if verdict != OK:
        report_failure(verdict, detail, status, args.feed)
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


def fetch_cmd(args):
    """Pull the feed once and write it to disk.

    Deliberately dumb: no filtering, no parsing beyond a shape check. Its whole
    job is that everything downstream can run without touching the network.
    """
    key = os.environ.get("WF_KEY", "").strip()
    if not key:
        print("FAIL  WF_KEY is not set in the environment.")
        return 2
    verdict, detail, status, raw = fetch(args.feed, key)

    if verdict == RATE_LIMITED and args.allow_stale and os.path.exists(args.out):
        # Deliberate, announced fallback -- NOT a swallowed error. The limit is
        # measured at somewhere between 22.5 and 36.5 minutes (2026-08-30), so
        # a second run inside that window would otherwise fail outright with a
        # perfectly good feed already on disk. Every downstream command prints
        # the age, and only 429 is eligible: a 401 or a bad body still fails.
        when, mins = feed_age(args.out)
        print("rate-limited  %s  HTTP 429 -- REUSING THE CACHED FEED" % args.feed)
        if when is None:
            print("  Its age is UNKNOWN (no .meta.json). Everything derived from")
            print("  it below may be stale, and nothing here can tell you.")
        else:
            print("  Cached copy was pulled %s, %d minute(s) ago." % (when, mins))
        print("  This is --allow-stale. Without it this step fails.")
        return 0

    if verdict != OK:
        report_failure(verdict, detail, status, args.feed)
        return 1
    d, why = parse(raw)
    if d is None:
        # Refuse to cache a body that is not the feed. A cached web page would
        # look like a successful fetch to every later step.
        print("%-13s %s  HTTP %s  %s bytes" % (BAD_BODY, args.feed, status, len(raw)))
        print("  %s  Nothing written." % why)
        return 1
    with open(args.out, "wb") as fh:
        fh.write(raw)
    write_meta(args.out, args.feed, raw, len(d))
    print("wrote %s  (%s bytes, %s records, %s feed)"
          % (args.out, len(raw), len(d), args.feed))
    return 0


def evaluate(rows, idx):
    """Score installs against a slug index. Pure function, no printing.

    Extracted from the CLI so it can be tested. The gating verdict had to be
    pulled out of its CLI block for the same reason, and until it was, nothing
    could check it.

    Four buckets, and the last two are NOT the same statement:

      affected        a known advisory covers this exact version
      cannot say      the version is unreadable, or a range would not parse
      not affected    an advisory EXISTS and this version is outside it
      no advisory     Wordfence has never published anything for this slug

    Folding `no advisory` into `not affected` would inflate the reassuring
    number with components nobody has ever assessed. Half this catalogue runs
    on exactly one site -- bespoke and white-label code no researcher looks at.
    """
    hits, unsure, n_clean, n_no_advisory = [], [], 0, 0
    for r in rows:
        recs = idx.get(r["slug"])
        if not recs:
            n_no_advisory += 1
            continue
        if vercmp.is_absent(r["version"]):
            unsure.append((r, "no readable version"))
            continue
        verdicts = []
        for vid, rec, sw in recs:
            v = vercmp.is_affected(r["version"], sw.get("affected_versions"))
            if v is True:
                hits.append((r, vid, rec, sw))
            verdicts.append(v)
        if True in verdicts:
            continue
        if None in verdicts:
            # One unevaluable range among clean ones is still "cannot say".
            # A range we failed to parse is not a range we cleared.
            unsure.append((r, "a range could not be evaluated"))
        else:
            n_clean += 1
    # Ranked worst-first here rather than at each call site, so the CLI, the
    # report and any test all see one order.
    findings = sorted((finding(r, vid, rec, sw) for r, vid, rec, sw in hits),
                      key=rank_key)
    n_by_band = {}
    for f in findings:
        n_by_band[f["band"]] = n_by_band.get(f["band"], 0) + 1
    return {
        "sites": {r["site"] for r in rows},
        "findings": findings,
        "n_by_band": n_by_band,
        # None when nothing is affected -- NOT "none", which is a real CVSS
        # band meaning a scored zero.
        "worst_band": findings[0]["band"] if findings else None,
        "hits": hits,
        "unsure": unsure,
        "n_clean": n_clean,
        "n_no_advisory": n_no_advisory,
        # Per SITE, never per install. A site carrying one component twice is
        # one site; the catalogue counted rows as sites once and said 13
        # PDFEmbedder sites where there were 12.
        "hit_sites": {h[0]["site"] for h in hits},
        "nofix": [h for h in hits if h[3].get("patched") is False],
        "fixed": [h for h in hits if h[3].get("patched") is not False],
    }


# ---------------------------------------------------------------------------
# how bad is it, and can it be closed by updating?
# ---------------------------------------------------------------------------

# CVSS v3.1 severity bands, lower bound of each. Validated against the vendor's
# own `cvss.rating` on all 17 real Pods advisories in
# test/fixtures/wf-pods-production.json -- this table is not a belief about
# where the bands sit, it agrees with Wordfence on every record we hold.
#
# The band is derived from the SCORE, not read from `rating`, for two reasons:
# the scanner feed carries no `rating` at all, and two sources for one fact is
# two answers. test-vuln-critical.py asserts the two never disagree.
BANDS = (("critical", 9.0), ("high", 7.0), ("medium", 4.0), ("low", 0.1))

# NOT "low", NOT "none". A score we could not read is an absence, and this
# repo's cardinal bug is an absence rendered as a value in the reassuring
# direction.
UNKNOWN_BAND = "unknown"

# Sort order. UNKNOWN sits directly BELOW critical and ABOVE high on purpose:
# an unreadable score might be a 9.8, and sorting it in with the lows would
# bury the exact case this ranking exists to surface.
BAND_RANK = {"critical": 5, UNKNOWN_BAND: 4, "high": 3,
             "medium": 2, "low": 1, "none": 0}


def band(score):
    """A CVSS score -> the WORD for its severity band.

    The word, not the number, is what a reader understands. Doug, 2026-08-31:
    the first vulnerability page "induced panic" because it led with a bare
    figure -- a `6.4` means nothing to someone who does not know the bands.

    Returns UNKNOWN_BAND for a missing, null, or non-numeric score. Booleans
    are rejected explicitly: `True` is an int in Python and would otherwise
    score as a 1.0 low.
    """
    if isinstance(score, bool):
        return UNKNOWN_BAND
    if isinstance(score, str):
        # The production feed sends numbers. Accept a numeric string rather
        # than calling a readable score unknown, but never invent one.
        try:
            score = float(score.strip())
        except (ValueError, AttributeError):
            return UNKNOWN_BAND
    if not isinstance(score, (int, float)):
        return UNKNOWN_BAND
    for name, lo in BANDS:
        if score >= lo:
            return name
    return "none"


def score_of(rec):
    """The CVSS score off a feed record, or None. Never 0 for absent.

    `match()` used `(rec.get("cvss") or {}).get("score") or 0`, which renders a
    record with no score as a 0.0 -- the bottom of the scale -- in a column
    headed "worst CVSS".
    """
    c = rec.get("cvss")
    if not isinstance(c, dict):
        return None
    s = c.get("score")
    if isinstance(s, bool) or not isinstance(s, (int, float, str)):
        return None
    if isinstance(s, str):
        try:
            return float(s.strip())
        except (ValueError, AttributeError):
            return None
    return s


def fix_version(installed, sw):
    """The version this install must reach to close the finding, or None.

    None means NO FIX: `patched` is false, the list is empty, or every entry
    is at or below what is already installed. A None here is what turns a
    finding from an update into a decision, so it must never stand in for
    "we did not look".

    `patched_versions` is a LIST and is not ordered. The answer is the LOWEST
    entry strictly ABOVE the installed version -- the nearest release that
    closes it, not the newest one the vendor has shipped. A site on 4.27.6
    with fixes at 4.28.0 and 5.0.0 needs 4.28.0.
    """
    if sw.get("patched") is False:
        return None
    if vercmp.is_absent(installed):
        return None
    cands = []
    for pv in sw.get("patched_versions") or []:
        if vercmp.is_absent(pv):
            continue
        try:
            if vercmp.compare(pv, installed) > 0:
                cands.append(pv)
        except ValueError:
            continue
    if not cands:
        return None
    lowest = cands[0]
    for c in cands[1:]:
        if vercmp.compare(c, lowest) < 0:
            lowest = c
    return lowest


def finding(row, vid, rec, sw):
    """One affected install, flattened and ranked-ready.

    Built here rather than in the CLI so it is testable. The gating verdict had
    to be pulled out of its CLI block for exactly this reason, and until it
    was, nothing could check it.
    """
    score = score_of(rec)
    fix = fix_version(row["version"], sw)
    return {
        "site": row["site"],
        "slug": row["slug"],
        "version": row["version"],
        "vuln_id": vid,
        "cve": rec.get("cve"),
        "title": rec.get("title"),
        "score": score,
        "band": band(score),
        "patched": sw.get("patched") is not False,
        "fix_version": fix,
        # What a person does next, in plain words. "no update exists, someone
        # has to choose" is the reader-facing half of this.
        "action": "update" if fix else "decide",
    }


def rank_key(f):
    """Worst first. Band, then score, then slug so the order is stable.

    A missing score sorts to the bottom WITHIN its band and never lifts a
    finding above a band it does not belong to.
    """
    return (-BAND_RANK.get(f["band"], 0),
            -(f["score"] if isinstance(f["score"], (int, float)) else -1.0),
            f["slug"], f["site"], str(f["vuln_id"]))


def build_report(rows, idx, feed, inventory_ids=None, feed_meta=None):
    """The ingestable report: one entry per site, findings nested.

    Every site in the INVENTORY appears, not just the ones with a component
    list. A site we cannot match is written `matched: false` and carries no
    counts -- 17 of 85 on 2026-08-31. Leaving them out entirely would make the
    run look like it covered the whole fleet, and "no findings" is the best
    possible result on this axis, so silence reads as good news.
    """
    per = {}
    for r in rows:
        site = r["site"]
        e = per.setdefault(site, {"domain": site, "matched": True,
                                  "affected": 0, "nofix": 0,
                                  "worst_cvss": None, "findings": []})
        recs = idx.get(r["slug"])
        if not recs:
            continue
        for vid, rec, sw in recs:
            if vercmp.is_affected(r["version"], sw.get("affected_versions")) is not True:
                continue
            # ONE implementation of each fact, shared with evaluate(). The
            # first cut of this function derived the severity word here and
            # joined every patched_version into a string; both are done better
            # by the helpers above and a second copy is a second answer.
            score = score_of(rec)
            patched = sw.get("patched")
            e["findings"].append({
                "slug": r["slug"],
                "version": r["version"],
                "cve": rec.get("cve") or vid,
                "cvss": score,
                # DERIVED from the score, not read from `cvss.rating`. The
                # scanner feed publishes no rating at all, and this page showed
                # "unrated" on every row once already when the field failed to
                # survive ingest. The vendor's own word is kept beside it and
                # test-vuln-critical.py asserts the two never disagree.
                "rating": band(score).capitalize(),
                "vendor_rating": (rec.get("cvss") or {}).get("rating"),
                "patched": patched,
                # The LOWEST patched release strictly above what is installed:
                # the nearest version that closes it, not the newest the vendor
                # has shipped. A site on 4.27.6 with fixes at 4.28.0 and 5.0.0
                # needs 4.28.0, and the old code told it "4.28.0, 5.0.0".
                "fix_version": fix_version(r["version"], sw),
                "remediation": sw.get("remediation"),
                "title": rec.get("title"),
                "published": (rec.get("published") or "")[:10] or None,
            })
            e["affected"] += 1
            if patched is False:
                e["nofix"] += 1
            if score is not None and (e["worst_cvss"] is None
                                      or score > e["worst_cvss"]):
                e["worst_cvss"] = score

    for sid in sorted(inventory_ids or ()):
        # matched: false, and NO counts. See the docstring.
        per.setdefault(sid, {"domain": sid, "matched": False})

    meta = feed_meta or {}
    return {
        "schema": "fleet-vuln-intel/1",
        "feed": feed,
        "feed_fetched_at": meta.get("fetched_at"),
        "feed_records": meta.get("records"),
        "sites": [per[k] for k in sorted(per)],
    }


def inventory_ids(path):
    """Every site the fleet knows about, so unmatched ones are still reported."""
    if not path or not os.path.exists(path):
        return set()
    inv = json.load(open(path, encoding="utf-8"))
    # `site_id`, NOT host_site_name-or-domain. Those are JOIN KEYS the ledger
    # maps FROM; site_id is what it maps TO, and it is what components.jsonl
    # already stores, so both halves of this report speak one identifier.
    # Emitting machine names produced 88 sites against an inventory of 85 --
    # every matched site appeared twice, once under each name. Caught by
    # ingest's "every row resolves to the inventory" guard, which is the only
    # reason it is a comment here and not mis-keyed rows in an append-only
    # ledger. Same failure as the Nexcess nxcli-domain join.
    return {s["site_id"] for s in inv.get("sites", []) if s.get("site_id")}


def match(args):
    """Score every install against the feed. REPORTING ONLY.

    This writes nothing and scores no severity. There is no `vuln-intel` source
    in fleet-ledger.py yet and no severity codes, and CLAUDE.md puts both
    before an ingest. This prints what is true so a person looks first.

    The three-valued answer is carried all the way to the output. CANNOT SAY is
    its own line and is never folded into "not affected", and the sites with no
    component inventory at all are named as absent rather than counted clean.
    """
    raw, verdict, detail, status = read_feed(args)
    if verdict != OK:
        report_failure(verdict, detail, status, args.feed)
        return 1
    feed, why = parse(raw)
    if feed is None:
        print("%-13s %s" % (BAD_BODY, why))
        return 1

    rows = installs(args.components)
    if not rows:
        print("FAIL  no installs read from %s. Nothing to match." % args.components)
        return 1
    idx = by_slug(feed)

    m = evaluate(rows, idx)
    sites, hits, unsure = m["sites"], m["hits"], m["unsure"]
    n_clean, n_no_advisory = m["n_clean"], m["n_no_advisory"]
    hit_sites, nofix, fixed = m["hit_sites"], m["nofix"], m["fixed"]

    print("MATCHED %d installs on %d sites against %d feed records"
          % (len(rows), len(sites), len(feed)))
    print()
    if getattr(args, "feed_file", None):
        announce_age(args.feed_file)
    print("  affected            %4d finding(s) over %d site(s)"
          % (len(hits), len(hit_sites)))
    print("    a fix exists      %4d finding(s) over %d site(s)"
          % (len(fixed), len({h[0]["site"] for h in fixed})))
    print("    NO fix exists     %4d finding(s) over %d site(s)"
          % (len(nofix), len({h[0]["site"] for h in nofix})))
    print("  not affected        %4d install(s)  (an advisory exists; this"
          % n_clean)
    print("                                       version is outside its range)")
    print("  CANNOT SAY          %4d install(s) over %d site(s)"
          % (len(unsure), len({u[0]["site"] for u in unsure})))
    print("  no advisory at all  %4d install(s)  (%d distinct component(s))"
          % (n_no_advisory,
             len({r["slug"] for r in rows if r["slug"] not in idx})))
    print()
    print("  TWO CAVEATS ON THAT LAST LINE. Wordfence never having published an")
    print("  advisory is not evidence a component is sound -- half this catalogue")
    print("  runs on exactly one site, and bespoke or white-label code is not")
    print("  something researchers look at. And a component whose version could")
    print("  not be read lands there too if its slug is unknown to the feed.")
    print()
    print("  This run saw %d sites. Any site with no component inventory is" % len(sites))
    print("  absent from every number above and is NOT 'not affected'.")

    if nofix:
        print()
        print("  --- FINDINGS WITH NO FIX AVAILABLE ---")
        print("  These cannot be closed by updating. Each needs a decision:")
        print("  remove the component, mitigate it, or accept the risk.")
        print()
        agg = {}
        for r, vid, rec, sw in nofix:
            a = agg.setdefault(r["slug"], {"sites": set(), "recs": {}, "vers": set()})
            a["sites"].add(r["site"])
            a["vers"].add(str(r["version"]))
            a["recs"][vid] = rec
        for slug in sorted(agg, key=lambda k: (-len(agg[k]["sites"]), k)):
            a = agg[slug]
            oldest = min((str(x.get("published") or "")[:10]
                          for x in a["recs"].values()), default="?")
            # score_of, not . A record with no score printed as 0.0
            # under a heading reading "worst CVSS" -- the bottom of the scale
            # standing in for an absence.
            scores = [score_of(x) for x in a["recs"].values()]
            known = [x for x in scores if x is not None]
            worst = max(known) if known else None
            # The WORD beside the number. A bare 6.4 means nothing to a reader
            # who does not know the CVSS bands (Doug, 2026-08-31).
            print("    %-32s %2d site(s)  %d advisory  oldest %s  worst %s"
                  % (slug, len(a["sites"]), len(a["recs"]), oldest,
                     "unknown (no score published)" if worst is None
                     else "%s CVSS %s" % (band(worst).upper(), worst)))
            for vid, rec in sorted(a["recs"].items(),
                                   key=lambda kv: str(kv[1].get("published"))):
                print("        %-16s %s  %s"
                      % (rec.get("cve") or vid[:14],
                         str(rec.get("published") or "")[:10],
                         (rec.get("title") or "")[:58]))
            print("        installed at: %s" % ", ".join(sorted(a["vers"])))
    else:
        print()
        print("  No finding lacks a fix. Every affected component can be closed")
        print("  by updating it.")

    out_path = getattr(args, "report", None)
    if out_path:
        meta = {}
        if getattr(args, "feed_file", None):
            when, _ = feed_age(args.feed_file)
            meta = {"fetched_at": when, "records": len(feed)}
        rep = build_report(rows, idx, args.feed,
                           inventory_ids(getattr(args, "inventory", None)),
                           meta)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True)
            fh.write("\n")
        n_unmatched = sum(1 for x in rep["sites"] if not x.get("matched"))
        print()
        print("  wrote %s" % out_path)
        print("    %d site(s): %d matched, %d with no component inventory"
              % (len(rep["sites"]), len(rep["sites"]) - n_unmatched, n_unmatched))
        print("    the %d unmatched carry NO counts. They are unchecked, not clear."
              % n_unmatched)

    if unsure and getattr(args, "show_unsure", False):
        print()
        print("  --- CANNOT SAY ---")
        for r, reason in unsure[:args.show]:
            print("    %-30s %-32s %s" % (r["site"], r["slug"], reason))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    ft = sub.add_parser("fetch", help="pull the feed once and cache it to disk")
    ft.add_argument("--feed", choices=FEEDS, default="production")
    ft.add_argument("--out", required=True)
    ft.add_argument("--allow-stale", dest="allow_stale", action="store_true",
                    help="on 429 ONLY, keep an existing cached feed and carry "
                         "on, printing its age. Any other failure still fails.")
    ft.set_defaults(fn=fetch_cmd)

    pr = sub.add_parser("probe", help="does the key work, and what is in the feed?")
    pr.add_argument("--feed", choices=FEEDS, default="production")
    pr.add_argument("--feed-file", dest="feed_file", default=None,
                    help="read this cached feed instead of fetching. "
                         "The feed is rate-limited; prefer this.")
    pr.add_argument("--components", default="history/components.jsonl")
    pr.add_argument("--show", type=int, default=40)
    pr.set_defaults(fn=probe)

    mt = sub.add_parser("match", help="score every install against the feed (reports only)")
    mt.add_argument("--feed", choices=FEEDS, default="production")
    mt.add_argument("--feed-file", dest="feed_file", default=None,
                    help="read this cached feed instead of fetching.")
    mt.add_argument("--components", default="history/components.jsonl")
    mt.add_argument("--show", type=int, default=40)
    mt.add_argument("--show-unsure", dest="show_unsure", action="store_true",
                    help="list the installs whose exposure could not be decided")
    mt.add_argument("--report", default=None, metavar="PATH",
                    help="write an ingestable fleet-vuln-intel/1 report here.")
    mt.add_argument("--inventory", default="data/fleet-inventory.json",
                    help="so sites with no component list are reported as "
                         "unmatched rather than silently omitted.")
    mt.set_defaults(fn=match)

    fx = sub.add_parser("fixture", help="extract one slug's records as a test fixture")
    fx.add_argument("--slug", required=True)
    fx.add_argument("--feed", choices=FEEDS, default="production")
    fx.add_argument("--feed-file", dest="feed_file", default=None,
                    help="read this cached feed instead of fetching.")
    fx.add_argument("--out", required=True)
    fx.set_defaults(fn=fixture)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
