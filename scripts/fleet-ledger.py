#!/usr/bin/env python3
"""
fleet-ledger.py - history store and change detector for fleet scans.

PROTOTYPE, 2026-08-17. Built to answer a design question with real output
rather than argument: given that two runs 14h apart differed by one integer,
what should a human actually receive?

Design contract, matching the rest of cm-automation:
  - stdlib only, no pip, no services
  - runs identically on macOS and a Linux CI runner
  - append-only: it never rewrites or deletes a prior observation
  - unknown is a value, never folded into yes or no
  - diffs operate on OBSERVED FACTS, never on rendered strings

Subcommands
  ingest   reports/*.json -> history/observations.jsonl   (idempotent)
  diff     compare two runs, fact level, with change classification
  digest   the delta-first report a human should receive
  timeline per-site or per-fact history across all ingested runs

Usage
  ./scripts/fleet-ledger.py ingest  --reports ./reports --history ./history
  ./scripts/fleet-ledger.py diff    --history ./history
  ./scripts/fleet-ledger.py digest  --history ./history
  ./scripts/fleet-ledger.py timeline --history ./history --site hoffmanscheese
"""

import argparse
import datetime
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Fact model
# --------------------------------------------------------------------------
# OBSERVED facts come from Pantheon. They are what we diff.
# DERIVED values are computed by the scanner from observed facts. We diff them
# too, but separately and labelled, because a derived change with no observed
# change means OUR RULES changed, not the fleet. That distinction is the whole
# reason this is split.

OBSERVED = (
    "framework",
    "plan",
    "env",
    "frozen",
    "php_version",
    "db_backup_age_days",
    "upstream_pending",
    "wp_checked",
    "wp_version",
    "wp_core_update",
    "plugin_updates",
    "theme_updates",
)

DERIVED = ("status",)

# `notes` is a rendered sentence that embeds observed numbers. Diffing it
# double-reports every numeric change. Excluded on purpose. Do not add it back.
RENDERED = ("notes",)

# Facts whose absence is meaningful (site was not deep-scanned) rather than
# missing data. Absent -> the literal token "unknown".
UNKNOWN = "unknown"


# Facts that only exist if the site was deep-scanned over SSH. In api-only mode
# the scanner currently writes 0 / 0 / "n/a" for these on every site. A 0 there
# is a FABRICATED NEGATIVE: it renders as "no plugin updates pending" in the CSV
# and the digest when the truth is "nobody looked". The ledger refuses to store
# it. This is settled principle 5 (unknown is never folded into negative)
# applied to the data rather than only to the display.
# wp_version joined this list on 2026-08-18. It is the fact the whole project
# was built to establish: the workbook asserts 7.0.2 on all 78 sites and nothing
# had ever verified it on any of them. Until that date the scan recorded only
# wp_core_update, which reports the version AVAILABLE and reads "up-to-date"
# when none is, so a fleet on any version at all looked identical to a fleet on
# 7.0.2. Belongs here because reading it needs SSH, so on an api-only run it
# must be unknown and never a value.
DEEP_ONLY = ("wp_version", "wp_core_update", "plugin_updates", "theme_updates")


def fact(row, key):
    """Observed value, or UNKNOWN. Never None, never coerced to a falsy default."""
    if key in DEEP_ONLY and row.get("wp_checked") is not True:
        return UNKNOWN
    if key not in row or row[key] is None:
        return UNKNOWN
    return row[key]


# --------------------------------------------------------------------------
# PHP support calendar - php.net/supported-versions, verified 2026-08-17
# --------------------------------------------------------------------------
# Kept as data, not as an if-chain, so it is reviewable and updatable without
# touching logic. Dates are the END of security support.
PHP_SECURITY_EOL = {
    "8.0": "2023-11-26",
    "8.1": "2025-12-31",
    "8.2": "2026-12-31",
    "8.3": "2027-12-31",
    "8.4": "2028-12-31",
    "8.5": "2029-12-31",
}


def php_support(version, today):
    """Return (tier, days_left). tier in eol | expiring | supported | unknown."""
    if version == UNKNOWN or version not in PHP_SECURITY_EOL:
        return (UNKNOWN, None)
    eol = datetime.date.fromisoformat(PHP_SECURITY_EOL[version])
    days = (eol - today).days
    if days < 0:
        return ("eol", days)
    if days <= 180:
        return ("expiring", days)
    return ("supported", days)


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
# The whole point of this layer: three tools key on three different identifiers
# (Pantheon machine name, domain, sending domain) and none of them agreed. Every
# source is normalised onto the inventory's site_id (the domain) before anything
# is stored, so one site has ONE history no matter which tool observed it.
#
# Fact names must not collide across sources; ingest asserts it rather than
# trusting it, because a silent collision would merge two unrelated measurements
# into one timeline and the diff would report changes that never happened.

EMAIL_OBSERVED = (
    "spf_present", "spf_all_qualifier", "spf_checked_at",
    "dkim_present", "dkim_selector",
    "dmarc_at_sending_present", "dmarc_at_sending_policy",
    "dmarc_at_from_present", "dmarc_at_from_policy", "dmarc_via_org_fallback",
    "relaxed_aligned",
)

RUN_RE = re.compile(r"fleet-(health|plugin-scan|email-dns|[a-z0-9-]+)-(\d{4}-\d{2}-\d{2})_(\d{4})\.json$")


def parse_run_id(path):
    """Run identity comes from the filename stamp the scanners already write."""
    m = RUN_RE.search(os.path.basename(path))
    if not m:
        return None
    kind, day, hhmm = m.groups()
    return {
        "run_id": "%s-%s_%s" % (kind, day, hhmm),
        "kind": kind,
        "observed_at": "%sT%s:%s:00" % (day, hhmm[:2], hhmm[2:]),
    }


def load_inventory(path):
    """site_id lookups. Returns (by_host_site_name, by_domain, records).

    A MISSING inventory is an ERROR here, not an empty result. Accepting it
    silently is exactly how the ledger written on 2026-08-16 came to key its
    health rows on Pantheon machine names: the inventory did not exist yet,
    every lookup fell back to the raw key, nothing complained, and the damage
    was only visible a day later when the dashboard reported 130 sites for an
    84-site fleet. The store is append-only, so it could not be corrected in
    place; it had to be rebuilt from reports/ that happened to still exist.

    Pass path=None to mean "deliberately no inventory". That is now a decision
    the caller states out loud, rather than what a wrong path quietly gets you.
    """
    if path is None:
        return {}, {}, {}
    if not os.path.exists(path):
        raise SystemExit(
            "inventory not found: %s\n"
            "Ingesting without it keys every row on whatever identifier its own\n"
            "tool happens to use, and this ledger is append-only, so the result\n"
            "cannot be corrected afterwards. Point --inventory at the real file,\n"
            "or pass --no-inventory if you genuinely mean unnormalised keys."
            % path
        )
    inv = json.load(open(path))
    by_host, by_domain, recs = {}, {}, {}
    for s in inv["sites"]:
        recs[s["site_id"]] = s
        if s.get("host_site_name"):
            by_host[s["host_site_name"]] = s["site_id"]
        if s.get("domain"):
            by_domain[s["domain"].lower()] = s["site_id"]
    return by_host, by_domain, recs


def _health_rows(payload, by_host):
    """Pantheon health scan: a list of rows keyed on the machine name."""
    if not isinstance(payload, list):
        return None
    out = []
    for r in payload:
        name = r["site"]
        rec = {"site_id": by_host.get(name, name), "host_site_name": name,
               "source": "health"}
        for k in OBSERVED:
            rec[k] = fact(r, k)
        for k in DERIVED:
            rec["derived_" + k] = fact(r, k)
        out.append(rec)
    return out


def _email_rows(payload, by_domain):
    """Email DNS check: a dict with a `sites` list keyed on the domain."""
    if not isinstance(payload, dict) or payload.get("kind") != "email-dns":
        return None
    out = []
    for s in payload.get("sites", []):
        if "error" in s:
            continue
        d = s["domain"].lower()
        dk, spf = s.get("dkim", {}), s.get("spf", {})
        dm = s.get("dmarc", {})
        at_send, at_from = dm.get("at_sending_domain", {}), dm.get("at_from_domain", {})
        out.append({
            "site_id": by_domain.get(d, d), "host_site_name": None, "source": "email-dns",
            "spf_present": spf.get("present", UNKNOWN),
            "spf_all_qualifier": spf.get("all_qualifier") or UNKNOWN,
            "spf_checked_at": spf.get("checked_at") or UNKNOWN,
            "dkim_present": dk.get("present", UNKNOWN),
            "dkim_selector": dk.get("selector") or UNKNOWN,
            "dmarc_at_sending_present": at_send.get("present", UNKNOWN),
            "dmarc_at_sending_policy": at_send.get("policy") or UNKNOWN,
            "dmarc_at_from_present": at_from.get("present", UNKNOWN),
            "dmarc_at_from_policy": at_from.get("policy") or UNKNOWN,
            "dmarc_via_org_fallback": at_from.get("via_org_fallback", UNKNOWN),
            "relaxed_aligned": s.get("alignment", {}).get("relaxed_aligned", UNKNOWN),
        })
    return out


# Fact-name collision guard. If two sources ever claim the same fact name, the
# ledger would silently merge unrelated measurements onto one timeline.
_overlap = set(OBSERVED) & set(EMAIL_OBSERVED)
assert not _overlap, "fact name collision between sources: %s" % sorted(_overlap)


def ingest(reports_dir, history_dir, inventory=None):
    obs_path = os.path.join(history_dir, "observations.jsonl")
    runs_path = os.path.join(history_dir, "runs.jsonl")
    if not os.path.isdir(history_dir):
        os.makedirs(history_dir)

    seen = set()
    if os.path.exists(runs_path):
        with open(runs_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    seen.add(json.loads(line)["run_id"])

    by_host, by_domain, inv_recs = load_inventory(inventory)

    # reports/ is gitignored, so it legitimately does not exist on a fresh
    # clone, or on a CI runner whose scan died before writing anything. Nothing
    # to ingest is zero runs, not a traceback. This is the same absence that
    # broke CI run #1.
    if os.path.isdir(reports_dir):
        files = sorted(
            os.path.join(reports_dir, n)
            for n in os.listdir(reports_dir)
            if n.endswith(".json")
        )
    else:
        files = []

    added_runs, added_obs, skipped = 0, 0, 0
    # Rows whose identifier matched no inventory entry, accumulated across every
    # run in this ingest. Each run already records its own list, but a value
    # written into a file nobody reads is not a warning. The caller gets a count
    # back and the CLI prints it.
    unresolved_by_run = {}
    with open(obs_path, "a") as obs_fh, open(runs_path, "a") as runs_fh:
        for path in files:
            meta = parse_run_id(path)
            if meta is None:
                print("  skip (unrecognized name): %s" % os.path.basename(path), file=sys.stderr)
                continue
            if meta["run_id"] in seen:
                skipped += 1
                continue
            with open(path) as fh:
                payload = json.load(fh)

            rows = _health_rows(payload, by_host)
            if rows is None:
                rows = _email_rows(payload, by_domain)
            if rows is None:
                print("  skip (unrecognised shape): %s" % os.path.basename(path),
                      file=sys.stderr)
                continue

            source = rows[0]["source"] if rows else "unknown"
            # Coverage is a property of the RUN and is what makes an OK
            # trustworthy or not. Store it once here so no later reader
            # has to re-infer it.
            if source == "health":
                deep = sum(1 for r in payload if r.get("wp_checked") is True)
                mode = "full" if deep else "api-only"
            else:
                deep = sum(1 for r in rows if r["dkim_present"] is True)
                mode = "dns"
            unresolved = [r for r in rows
                          if r.get("site_id") and r["site_id"] not in inv_recs]
            meta.update({
                "source_file": os.path.basename(path),
                "source": source,
                "site_count": len(rows),
                "deep_scanned": deep,
                "mode": mode,
                # Rows that matched no inventory entry. Never silently dropped:
                # an unknown site is the highest-signal finding there is.
                "sites_not_in_inventory": sorted(r["site_id"] for r in unresolved),
            })
            if unresolved:
                unresolved_by_run[meta["run_id"]] = sorted(
                    r["site_id"] for r in unresolved)
            runs_fh.write(json.dumps(meta, sort_keys=True) + "\n")
            added_runs += 1

            for r in rows:
                rec = dict(r)
                rec["run_id"] = meta["run_id"]
                rec["observed_at"] = meta["observed_at"]
                # `site` kept as an alias of site_id so existing readers and the
                # 43 assertions written against the health-only ledger keep
                # working unchanged.
                rec["site"] = r["site_id"]
                obs_fh.write(json.dumps(rec, sort_keys=True) + "\n")
                added_obs += 1

    return {
        "runs_added": added_runs,
        "runs_skipped": skipped,
        "observations_added": added_obs,
        "ledger": obs_path,
        "unresolved_by_run": unresolved_by_run,
        "unresolved_count": sum(len(v) for v in unresolved_by_run.values()),
    }


def load_ledger(history_dir):
    obs_path = os.path.join(history_dir, "observations.jsonl")
    runs_path = os.path.join(history_dir, "runs.jsonl")
    runs, obs = [], []
    if os.path.exists(runs_path):
        with open(runs_path) as fh:
            runs = [json.loads(l) for l in fh if l.strip()]
    if os.path.exists(obs_path):
        with open(obs_path) as fh:
            obs = [json.loads(l) for l in fh if l.strip()]
    runs.sort(key=lambda r: r["observed_at"])
    return runs, obs


def previous_run_of_same_source(runs, idx=-1):
    """The newest run, and the most recent earlier run from the SAME tool.

    Without this, ingesting an email scan after a health scan makes the diff
    compare a Pantheon snapshot against a DNS snapshot and report the entire
    fleet as changed. Comparing like with like is not a nicety here.
    """
    if not runs:
        return None, None
    curr = runs[idx]
    src = curr.get("source")
    for r in reversed(runs[:idx if idx != -1 else len(runs) - 1]):
        if r.get("source") == src:
            return r, curr
    return None, curr


def rows_for(obs, run_id):
    return {o["site"]: o for o in obs if o["run_id"] == run_id}


# --------------------------------------------------------------------------
# Change classification - the actual design proposal
# --------------------------------------------------------------------------
# Five classes, in descending order of how much a human should care. The point
# is that "a field changed" is not one thing, and a digest that treats it as
# one thing is the noise problem.

#   INVENTORY  a site appeared or disappeared. Nothing else can be trusted
#              until this is explained. Currently invisible; this is the class
#              that would have surfaced the 52-vs-54 discrepancy on its own.
#   TRANSITION a site crossed a severity boundary. The classic alert.
#   ONSET      a condition became true that was false. New problem.
#   RESOLVED   a condition became false that was true. Somebody fixed it.
#   DRIFT      a counter on an ALREADY-OPEN finding moved. Not news. This is
#              hoffmanscheese 719 -> 720. Suppressed from push by default,
#              retained in the ledger, still visible in the timeline.

CLASS_ORDER = ["INVENTORY", "TRANSITION", "ONSET", "RESOLVED", "DRIFT"]

# Facts where a monotonic increase on an already-bad row is drift, not onset.
COUNTERS = ("db_backup_age_days",)


def classify(site, key, before, after, prev_row, curr_row, today):
    if key in COUNTERS:
        # Did it cross a threshold that changes the answer? Then it is real.
        # Otherwise it is a clock ticking on something already reported.
        prev_bad = _backup_bad(before)
        curr_bad = _backup_bad(after)
        if prev_bad != curr_bad:
            return "TRANSITION"
        if curr_bad and prev_bad:
            return "DRIFT"
        return "ONSET" if curr_bad else "RESOLVED"

    if key in ("upstream_pending", "plugin_updates", "theme_updates"):
        b = 0 if before == UNKNOWN else before
        a = 0 if after == UNKNOWN else after
        if before == UNKNOWN or after == UNKNOWN:
            return "TRANSITION"  # coverage changed; that is worth saying out loud
        if b == 0 and a > 0:
            return "ONSET"
        if b > 0 and a == 0:
            return "RESOLVED"
        return "DRIFT"

    if key == "php_version":
        return "TRANSITION"
    if key in ("plan", "framework", "env", "frozen", "wp_checked", "wp_core_update"):
        return "TRANSITION"
    return "TRANSITION"


BACKUP_CRIT_DAYS = 2


def _backup_bad(v):
    # None and the UNKNOWN token mean the same thing here: nobody established a
    # backup age. A row from a source that does not measure backups (the email
    # check) carries neither, and must not be read as "backup is fine" OR as
    # "backup is missing".
    if v is None or v == UNKNOWN or not isinstance(v, (int, float)):
        return False
    return v > BACKUP_CRIT_DAYS


FACTS_BY_SOURCE = {"health": OBSERVED, "email-dns": EMAIL_OBSERVED}


def facts_for(row):
    """Which fact names this row actually carries.

    Diffing a health fact against an email row would compare None to None
    forever, and worse, a source changing would look like every fact changing
    at once. So the fact list follows the row's own source.
    """
    return FACTS_BY_SOURCE.get(row.get("source"), OBSERVED)


def rows_for_source(obs, run_id, source=None):
    return {o["site_id"] if "site_id" in o else o["site"]: o
            for o in obs
            if o["run_id"] == run_id and (source is None or o.get("source") == source)}


def diff_runs(prev_rows, curr_rows, today):
    changes = []

    gone = sorted(set(prev_rows) - set(curr_rows))
    new = sorted(set(curr_rows) - set(prev_rows))
    for s in new:
        changes.append({"class": "INVENTORY", "site": s, "fact": "site", "before": "absent", "after": "present"})
    for s in gone:
        changes.append({"class": "INVENTORY", "site": s, "fact": "site", "before": "present", "after": "absent"})

    for s in sorted(set(prev_rows) & set(curr_rows)):
        p, c = prev_rows[s], curr_rows[s]
        if p.get("source") != c.get("source"):
            changes.append({"class": "TRANSITION", "site": s, "fact": "source",
                            "before": p.get("source"), "after": c.get("source")})
            continue
        for k in facts_for(c):
            if p.get(k) != c.get(k):
                changes.append(
                    {
                        "class": classify(s, k, p.get(k), c.get(k), p, c, today),
                        "site": s,
                        "fact": k,
                        "before": p.get(k),
                        "after": c.get(k),
                    }
                )
        # Derived change with no observed change on the same site means the
        # RULES moved, not the fleet. Label it so nobody chases a ghost.
        for k in DERIVED:
            dk = "derived_" + k
            if p.get(dk) != c.get(dk):
                observed_moved = any(p.get(x) != c.get(x) for x in facts_for(c))
                changes.append(
                    {
                        "class": "TRANSITION" if observed_moved else "RULE_CHANGE",
                        "site": s,
                        "fact": k,
                        "before": p.get(dk),
                        "after": c.get(dk),
                    }
                )

    order = {c: i for i, c in enumerate(CLASS_ORDER + ["RULE_CHANGE"])}
    changes.sort(key=lambda c: (order.get(c["class"], 99), c["site"], c["fact"]))
    return changes


# --------------------------------------------------------------------------
# Standing conditions, grouped by cause
# --------------------------------------------------------------------------
# A digest needs two halves: what CHANGED (above) and what is still true. The
# second half is where 36 rows must collapse into 1 fact, because 36 rows of
# one cause reads as a crisis and is one merge.


def standing(curr_rows, today):
    """Grouped by cause, not by site. Only ever reads facts a row actually has."""
    groups = []
    health = {s: r for s, r in curr_rows.items()
              if r.get("source", "health") == "health"}
    email = {s: r for s, r in curr_rows.items() if r.get("source") == "email-dns"}

    groups.extend(_standing_email(email))
    curr_rows = health

    upstream = sorted(s for s, r in curr_rows.items() if r.get("upstream_pending") not in (UNKNOWN, 0, None))
    if upstream:
        groups.append(
            {
                "cause": "One pending Pantheon upstream commit, unmerged",
                "axis": "DRIFT",
                "sites": upstream,
                "action": "One merge decision covers all %d sites." % len(upstream),
            }
        )

    nobackup = sorted(
        (s, r["db_backup_age_days"])
        for s, r in curr_rows.items()
        if _backup_bad(r.get("db_backup_age_days"))
    )
    if nobackup:
        plans = sorted(set(curr_rows[s].get("plan") for s, _ in nobackup))
        groups.append(
            {
                "cause": "No recent DB backup",
                "axis": "RISK",
                "sites": [s for s, _ in nobackup],
                "detail": dict(("%s" % s, "%dd, %s" % (d, curr_rows[s].get("plan")))
                               for s, d in nobackup),
                "action": "All on plan(s) %s. Sandbox plans get no automatic nightly backup, so decide whether these are production before treating as an incident."
                % ", ".join(plans),
            }
        )

    eol, expiring = [], []
    for s, r in curr_rows.items():
        tier, days = php_support(r.get("php_version"), today)
        if tier == "eol":
            eol.append((s, r.get("php_version"), r.get("plan")))
        elif tier == "expiring":
            expiring.append((s, r.get("php_version"), days))
    if eol:
        groups.append(
            {
                "cause": "PHP version past end of security support",
                "axis": "RISK",
                "sites": [s for s, _, _ in sorted(eol)],
                "detail": dict((s, "PHP %s, %s" % (v, p)) for s, v, p in eol),
                "action": "Receiving no security patches. Upgrade path is a Pantheon setting plus a compatibility check.",
            }
        )
    if expiring:
        v = expiring[0][1]
        d = expiring[0][2]
        groups.append(
            {
                "cause": "PHP %s leaves security support in %d days (%s)" % (v, d, PHP_SECURITY_EOL[v]),
                "axis": "PLANNING",
                "sites": sorted(s for s, _, _ in expiring),
                "action": "Fleet-wide deadline, not a per-site alert. Schedule the upgrade wave now; it is the only finding here with a fixed date.",
            }
        )

    unknown_deep = sorted(s for s, r in curr_rows.items() if r.get("wp_checked") is False)
    if unknown_deep:
        groups.append(
            {
                "cause": "WordPress core, plugin and theme status not observed",
                "axis": "COVERAGE",
                "sites": unknown_deep,
                "action": "API-only mode cannot see these. Any OK on these sites means clean-on-what-we-looked-at, not clean.",
            }
        )

    order = {"RISK": 0, "COVERAGE": 1, "PLANNING": 2, "DRIFT": 3}
    groups.sort(key=lambda g: order.get(g["axis"], 9))
    return groups


def _standing_email(rows):
    """Email posture, same grouping discipline: cause first, sites second."""
    if not rows:
        return []
    out = []
    no_spf = sorted(s for s, r in rows.items() if r.get("spf_present") is False)
    if no_spf:
        out.append({"axis": "RISK", "cause": "No SPF record on the sending domain",
                    "sites": no_spf,
                    "action": "Authoritative answer, genuinely absent. Mail from these "
                              "domains cannot pass SPF."})
    undet = sorted(s for s, r in rows.items() if r.get("spf_present") == UNKNOWN)
    if undet:
        out.append({"axis": "COVERAGE", "cause": "SPF could not be determined",
                    "sites": undet,
                    "action": "A finding about the lookup, not the domain. Mostly "
                              "self-inflicted resolver saturation; the next run "
                              "usually resolves it."})
    no_dmarc = sorted(s for s, r in rows.items()
                      if r.get("dmarc_at_from_present") is False)
    if no_dmarc:
        out.append({"axis": "RISK",
                    "cause": "No DMARC on the domain recipients actually see",
                    "sites": no_dmarc,
                    "action": "Nothing protects the brand domain from spoofing. Note "
                              "this is a different question from whether the provider "
                              "setup is complete."})
    monitor = sorted(s for s, r in rows.items()
                     if r.get("dmarc_at_from_policy") == "none")
    if monitor:
        out.append({"axis": "DRIFT", "cause": "DMARC published but p=none",
                    "sites": monitor,
                    "action": "Monitoring only. One policy decision covers all %d."
                              % len(monitor)})
    unaligned = sorted(s for s, r in rows.items() if r.get("relaxed_aligned") is False)
    if unaligned:
        out.append({"axis": "RISK", "cause": "From domain not aligned with sending domain",
                    "sites": unaligned,
                    "action": "DMARC fails on unaligned mail even when SPF and DKIM pass."})
    return out


# --------------------------------------------------------------------------
# Digest
# --------------------------------------------------------------------------


def render_digest(runs, obs, today):
    if len(runs) < 1:
        return "No runs ingested.\n"
    curr = runs[-1]
    curr_rows = rows_for(obs, curr["run_id"])
    out = []
    out.append("# Fleet delta - %s" % curr["observed_at"].replace("T", " "))
    out.append("")

    prev, _ = previous_run_of_same_source(runs)
    if prev is not None:
        prev_rows = rows_for(obs, prev["run_id"])
        changes = diff_runs(prev_rows, curr_rows, today)
        pushable = [c for c in changes if c["class"] != "DRIFT"]
        drift = [c for c in changes if c["class"] == "DRIFT"]

        out.append(
            "Compared with `%s` (%s earlier). %d site(s) both runs."
            % (prev["run_id"], _gap(prev["observed_at"], curr["observed_at"]), len(curr_rows))
        )
        out.append("")
        out.append("## What changed")
        out.append("")
        if not pushable:
            out.append("**Nothing that needs a decision.**")
            if drift:
                out.append("")
                out.append(
                    "%d counter(s) moved on findings already open (suppressed):"
                    % len(drift)
                )
                for c in drift:
                    out.append(
                        "- `%s` %s %s -> %s" % (c["site"], c["fact"], c["before"], c["after"])
                    )
        else:
            out.append("| Class | Site | Fact | Before | After |")
            out.append("|---|---|---|---|---|")
            for c in pushable:
                out.append(
                    "| %s | `%s` | %s | %s | %s |"
                    % (c["class"], c["site"], c["fact"], c["before"], c["after"])
                )
            if drift:
                out.append("")
                out.append("%d counter(s) moved on already-open findings, suppressed." % len(drift))
    else:
        out.append("First ingested run. No delta available; this is the baseline.")

    out.append("")
    out.append("## Still true (grouped by cause, not by site)")
    out.append("")
    for g in standing(curr_rows, today):
        out.append("**%s - %s**" % (g["axis"], g["cause"]))
        out.append("")
        out.append("- Affects: %s" % ", ".join(g["sites"][:6]) + (" ..." if len(g["sites"]) > 6 else ""))
        out.append("- %s" % g["action"])
        out.append("")

    out.append("## Coverage of this run")
    out.append("")
    out.append(
        "Mode `%s`. %d of %d sites deep-scanned. %s"
        % (
            curr["mode"],
            curr["deep_scanned"],
            curr["site_count"],
            "Three of eight fact fields were not observed on any site."
            if curr["mode"] == "api-only"
            else "",
        )
    )
    out.append("")
    return "\n".join(out)


def _gap(a, b):
    da = datetime.datetime.fromisoformat(a)
    db = datetime.datetime.fromisoformat(b)
    h = (db - da).total_seconds() / 3600.0
    if h < 48:
        return "%.0fh" % h
    return "%.0fd" % (h / 24.0)


def render_timeline(runs, obs, site=None):
    out = []
    if site:
        recs = sorted((o for o in obs if o["site"] == site), key=lambda o: o["observed_at"])
        if not recs:
            return "No observations for site %r.\n" % site
        out.append("# Timeline: %s" % site)
        inv_rec = None
        out.append("")
        # One site, several tools, one history. Each source gets its own table
        # because the facts genuinely differ; forcing them into one grid is how
        # you end up with a row of None that reads like missing data.
        for source in sorted(set(r.get("source", "health") for r in recs)):
            block = [r for r in recs if r.get("source", "health") == source]
            out.append("## source: %s" % source)
            out.append("")
            if source == "email-dns":
                out.append("| Observed | SPF | DKIM sel | DMARC@sending | DMARC@from | Aligned |")
                out.append("|---|---|---|---|---|---|")
                for r in block:
                    out.append("| %s | %s | %s | %s | %s | %s |" % (
                        r["observed_at"].replace("T", " "),
                        r.get("spf_present"), r.get("dkim_selector"),
                        r.get("dmarc_at_sending_present"),
                        r.get("dmarc_at_from_present"), r.get("relaxed_aligned")))
            else:
                out.append("| Observed | Status | Plan | PHP | Backup age | Upstream | Deep scanned |")
                out.append("|---|---|---|---|---|---|---|")
                for r in block:
                    out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                        r["observed_at"].replace("T", " "),
                        r.get("derived_status"), r.get("plan"), r.get("php_version"),
                        r.get("db_backup_age_days"), r.get("upstream_pending"),
                        r.get("wp_checked")))
            out.append("")
    else:
        out.append("# Runs in the ledger")
        out.append("")
        out.append("| Run | Observed | Source | Sites | Mode | Deep scanned | Not in inventory |")
        out.append("|---|---|---|---|---|---|---|")
        for r in runs:
            missing = r.get("sites_not_in_inventory") or []
            out.append("| %s | %s | %s | %d | %s | %d | %s |" % (
                r["run_id"], r["observed_at"].replace("T", " "), r.get("source", "?"),
                r["site_count"], r["mode"], r["deep_scanned"],
                ("**%d**" % len(missing)) if missing else "0"))
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ingest", "diff", "digest", "timeline"])
    ap.add_argument("--reports", default="./reports")
    ap.add_argument("--history", default="./history")
    ap.add_argument("--inventory", default="./data/fleet-inventory.json",
                    help="the authoritative site list. Every source is normalised "
                         "onto its site_id before storage, so one site has one "
                         "history regardless of which tool observed it.")
    ap.add_argument("--no-inventory", action="store_true",
                    help="ingest WITHOUT normalising onto site_id. Stores "
                         "whatever key each tool uses, so a site observed by "
                         "two tools gets two histories. Escape hatch for "
                         "tests; not for real data.")
    ap.add_argument("--fail-on-unresolved", action="store_true",
                    help="exit non-zero if any ingested row matched no "
                         "inventory entry. For CI, where nobody is reading "
                         "stdout.")
    ap.add_argument("--site")
    ap.add_argument("--source", help="restrict to one tool: health | email-dns")
    ap.add_argument("--today", help="override today (YYYY-MM-DD) for deterministic tests")
    ap.add_argument("--out", help="write output to this file as well as stdout")
    a = ap.parse_args()

    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()

    if a.command == "ingest":
        res = ingest(a.reports, a.history,
                     inventory=None if a.no_inventory else a.inventory)
        print(
            "ingested %d run(s), %d observation(s); %d run(s) already present -> %s"
            % (res["runs_added"], res["observations_added"], res["runs_skipped"], res["ledger"])
        )
        # An unresolved row is not dropped, it is stored under its own tool's
        # identifier. That is the right call for data, and the wrong thing to
        # do quietly: it is a second history for a site that already has one.
        if res["unresolved_count"]:
            print("", file=sys.stderr)
            print("WARNING: %d row(s) matched no inventory entry and were "
                  "stored under the tool's own key:" % res["unresolved_count"],
                  file=sys.stderr)
            for run_id in sorted(res["unresolved_by_run"]):
                names = res["unresolved_by_run"][run_id]
                shown = ", ".join(names[:8])
                if len(names) > 8:
                    shown += ", ... (%d more)" % (len(names) - 8)
                print("  %s: %s" % (run_id, shown), file=sys.stderr)
            print("Either add them to %s, or map them via host_site_name."
                  % a.inventory, file=sys.stderr)
            if a.fail_on_unresolved:
                return 1
        return 0

    runs, obs = load_ledger(a.history)
    if not runs:
        print("ledger is empty; run `ingest` first", file=sys.stderr)
        return 1

    if a.command == "diff":
        if a.source:
            runs = [r for r in runs if r.get("source") == a.source]
        prev, curr = previous_run_of_same_source(runs)
        if prev is None:
            print("only one run from this source; nothing to diff")
            return 0
        print("# %s vs %s  (source: %s)" % (prev["run_id"], curr["run_id"],
                                            curr.get("source")), file=sys.stderr)
        prev_rows = rows_for(obs, prev["run_id"])
        curr_rows = rows_for(obs, curr["run_id"])
        changes = diff_runs(prev_rows, curr_rows, today)
        print(json.dumps(changes, indent=2, sort_keys=True))
        return 0

    text = render_digest(runs, obs, today) if a.command == "digest" else render_timeline(runs, obs, a.site)
    print(text)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
