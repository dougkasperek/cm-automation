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
DEEP_ONLY = ("wp_core_update", "plugin_updates", "theme_updates")


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

RUN_RE = re.compile(r"fleet-(health|plugin-scan|[a-z0-9-]+)-(\d{4}-\d{2}-\d{2})_(\d{4})\.json$")


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


def ingest(reports_dir, history_dir):
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

    files = sorted(
        os.path.join(reports_dir, n)
        for n in os.listdir(reports_dir)
        if n.endswith(".json")
    )

    added_runs, added_obs, skipped = 0, 0, 0
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
                rows = json.load(fh)
            if not isinstance(rows, list):
                print("  skip (not a row array): %s" % os.path.basename(path), file=sys.stderr)
                continue

            # Coverage is a property of the RUN, derived from the rows, and it is
            # the thing that makes an OK trustworthy or not. Store it once here
            # so no later reader has to re-infer it.
            deep = sum(1 for r in rows if r.get("wp_checked") is True)
            meta.update(
                {
                    "source_file": os.path.basename(path),
                    "site_count": len(rows),
                    "deep_scanned": deep,
                    "mode": "full" if deep else "api-only",
                }
            )
            runs_fh.write(json.dumps(meta, sort_keys=True) + "\n")
            added_runs += 1

            for r in rows:
                rec = {
                    "run_id": meta["run_id"],
                    "observed_at": meta["observed_at"],
                    "site": r["site"],
                }
                for k in OBSERVED:
                    rec[k] = fact(r, k)
                for k in DERIVED:
                    rec["derived_" + k] = fact(r, k)
                obs_fh.write(json.dumps(rec, sort_keys=True) + "\n")
                added_obs += 1

    return {
        "runs_added": added_runs,
        "runs_skipped": skipped,
        "observations_added": added_obs,
        "ledger": obs_path,
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
    if v == UNKNOWN:
        return False  # unknown is not bad; it is unknown. See principle 5.
    return v > BACKUP_CRIT_DAYS


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
        for k in OBSERVED:
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
                observed_moved = any(p.get(x) != c.get(x) for x in OBSERVED)
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
    groups = []

    upstream = sorted(s for s, r in curr_rows.items() if r.get("upstream_pending") not in (UNKNOWN, 0))
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
                "sites": ["%s (%dd, %s)" % (s, d, curr_rows[s].get("plan")) for s, d in nobackup],
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
                "sites": ["%s (PHP %s, %s)" % (s, v, p) for s, v, p in sorted(eol)],
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
                "sites": ["%d sites" % len(expiring)],
                "action": "Fleet-wide deadline, not a per-site alert. Schedule the upgrade wave now; it is the only finding here with a fixed date.",
            }
        )

    unknown_deep = sorted(s for s, r in curr_rows.items() if r.get("wp_checked") is False)
    if unknown_deep:
        groups.append(
            {
                "cause": "WordPress core, plugin and theme status not observed",
                "axis": "COVERAGE",
                "sites": ["%d sites" % len(unknown_deep)],
                "action": "API-only mode cannot see these. Any OK on these sites means clean-on-what-we-looked-at, not clean.",
            }
        )

    order = {"RISK": 0, "COVERAGE": 1, "PLANNING": 2, "DRIFT": 3}
    groups.sort(key=lambda g: order.get(g["axis"], 9))
    return groups


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

    if len(runs) >= 2:
        prev = runs[-2]
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
        out.append("")
        out.append("| Observed | Status | Plan | PHP | Backup age | Upstream | Deep scanned |")
        out.append("|---|---|---|---|---|---|---|")
        for r in recs:
            out.append(
                "| %s | %s | %s | %s | %s | %s | %s |"
                % (
                    r["observed_at"].replace("T", " "),
                    r.get("derived_status"),
                    r.get("plan"),
                    r.get("php_version"),
                    r.get("db_backup_age_days"),
                    r.get("upstream_pending"),
                    r.get("wp_checked"),
                )
            )
    else:
        out.append("# Runs in the ledger")
        out.append("")
        out.append("| Run | Observed | Sites | Mode | Deep scanned |")
        out.append("|---|---|---|---|---|")
        for r in runs:
            out.append(
                "| %s | %s | %d | %s | %d |"
                % (r["run_id"], r["observed_at"].replace("T", " "), r["site_count"], r["mode"], r["deep_scanned"])
            )
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ingest", "diff", "digest", "timeline"])
    ap.add_argument("--reports", default="./reports")
    ap.add_argument("--history", default="./history")
    ap.add_argument("--site")
    ap.add_argument("--today", help="override today (YYYY-MM-DD) for deterministic tests")
    ap.add_argument("--out", help="write output to this file as well as stdout")
    a = ap.parse_args()

    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()

    if a.command == "ingest":
        res = ingest(a.reports, a.history)
        print(
            "ingested %d run(s), %d observation(s); %d run(s) already present -> %s"
            % (res["runs_added"], res["observations_added"], res["runs_skipped"], res["ledger"])
        )
        return 0

    runs, obs = load_ledger(a.history)
    if not runs:
        print("ledger is empty; run `ingest` first", file=sys.stderr)
        return 1

    if a.command == "diff":
        if len(runs) < 2:
            print("only one run in the ledger; nothing to diff")
            return 0
        prev_rows = rows_for(obs, runs[-2]["run_id"])
        curr_rows = rows_for(obs, runs[-1]["run_id"])
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
