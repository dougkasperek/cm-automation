#!/usr/bin/env bash
#
# pantheon-fleet-healthcheck.sh
# CleverMethod - Pantheon fleet health check (WordPress-first). CI-hardened.
#
# READ-ONLY. It never deploys, updates, clears caches destructively, or changes
# anything on any site. The only write it performs is to its own output dir.
#
# WHAT IT REPORTS PER SITE
#   PHP version, newest DB backup age, pending upstream (platform) commits,
#   and - unless running API-only - WP core/plugin/theme updates available.
#   Severity: CRIT / WARN / OK / FROZEN / SKIP / ERROR.
#
# TWO MODES, AND WHY
#   --api-only   Uses ONLY the Pantheon API (site:list, env:list, env:info,
#                backup:list, upstream:updates:list). NO SSH, NO WP-CLI.
#                This is the mode to run first on a new CI runner: it proves
#                the runner can authenticate and reach Pantheon before an SSH
#                key is anywhere near the pipeline. It still produces real
#                severity data (backup age and upstream drift), just not the
#                WP core/plugin/theme leg.
#   (default)    Full scan, including `terminus remote:wp`, which is SSH and
#                therefore requires an SSH private key registered with Pantheon.
#
# EXIT CODES
#   0  completed; no CRIT findings (or --no-fail-on-crit was set)
#   1  hard failure (bad auth, no tools, no sites returned)
#   2  completed; at least one CRIT finding
#   Exit 2 is the signal a scheduler or CI job should alert on. During the
#   testing phase, pass --no-fail-on-crit so runs stay green and you read the
#   artifact instead of chasing red builds.
#
# ENVIRONMENT
#   PANTHEON_MACHINE_TOKEN   required unless already `terminus auth:login`-ed
#
# PORTABILITY: bash 3.2 compatible (macOS) and bash 5.x (Linux CI). See
# scripts/lib/common.sh for the full contract. Do not introduce mapfile,
# `date -d`, or the `timeout` binary.
#
# Usage:
#   ./scripts/pantheon-fleet-healthcheck.sh \
#       [--env live] [--org "My Org"] [--out ./reports] \
#       [--api-only] [--sites a,b,c] [--limit N] \
#       [--backup-age 2] [--no-fail-on-crit]
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

# ---------- defaults ----------
TARGET_ENV="live"
ORG_FILTER=""
OUT_DIR="./reports"
BACKUP_MAX_AGE_DAYS=2
SLEEP_BETWEEN=0.3
API_ONLY=0
FAIL_ON_CRIT=1
SITE_FILTER=""
SITE_LIMIT=0
ENV_CHECK_TIMEOUT=20    # API call, should be fast
API_CALL_TIMEOUT=45     # backup:list / upstream:updates:list
WP_CLI_TIMEOUT=60       # SSH + WP-CLI bootstrap, slowest of the three

while [ $# -gt 0 ]; do
  case "$1" in
    --env)             TARGET_ENV="$2"; shift 2 ;;
    --org)             ORG_FILTER="$2"; shift 2 ;;
    --out)             OUT_DIR="$2"; shift 2 ;;
    --backup-age)      BACKUP_MAX_AGE_DAYS="$2"; shift 2 ;;
    --sites)           SITE_FILTER="$2"; shift 2 ;;
    --limit)           SITE_LIMIT="$2"; shift 2 ;;
    --api-only)        API_ONLY=1; shift ;;
    --no-fail-on-crit) FAIL_ON_CRIT=0; shift ;;
    -h|--help)         grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) err "Unknown option: $1"; exit 1 ;;
  esac
done

# ---------- preflight ----------
require_tools terminus jq || exit 1
pantheon_login || exit 1

mkdir -p "$OUT_DIR" || { err "cannot create output dir: $OUT_DIR"; exit 1; }
# UTC, not local. The ledger derives a run's observed_at from this stamp and
# orders runs by it to pick the pair it diffs. A laptop stamping Eastern and a
# CI runner stamping UTC put the same timeline four hours out of step, so a
# local run and a CI run can sort into the wrong order and the diff compares
# the wrong pair. Harmless while only one machine writes; wrong the moment CI
# does too.
STAMP="$(date -u +%Y-%m-%d_%H%M)"
JSON_OUT="$OUT_DIR/fleet-health-$STAMP.json"
CSV_OUT="$OUT_DIR/fleet-health-$STAMP.csv"
MD_OUT="$OUT_DIR/fleet-health-$STAMP.md"

if [ "$API_ONLY" -eq 1 ]; then
  log "MODE: API-only (no SSH, no WP-CLI). WP core/plugin/theme checks skipped."
else
  log "MODE: full scan (includes SSH + WP-CLI via terminus remote:wp)."
fi

# ---------- gather site list ----------
log "Listing sites..."
SITE_LIST_ARGS="site:list --format=json --fields=name,framework,plan_name,frozen"
SITES_JSON=""
if [ -n "$ORG_FILTER" ]; then
  # shellcheck disable=SC2086
  SITES_JSON="$(run_with_timeout "$API_CALL_TIMEOUT" terminus $SITE_LIST_ARGS --org "$ORG_FILTER" | json_or_empty)" || true
else
  # shellcheck disable=SC2086
  SITES_JSON="$(run_with_timeout "$API_CALL_TIMEOUT" terminus $SITE_LIST_ARGS | json_or_empty)" || true
fi

if [ -z "$SITES_JSON" ] || [ "$SITES_JSON" = "[]" ]; then
  # json_or_empty discards stderr, which is correct for parsing and useless for
  # diagnosis: the generic message below offers three guesses where Terminus
  # already knows the answer. Ask it again, plainly, and print what it says.
  err "no sites returned. Terminus said:"
  # shellcheck disable=SC2086
  run_with_timeout "$API_CALL_TIMEOUT" terminus $SITE_LIST_ARGS 2>&1 \
    | strip_noise | tail -5 | sed 's/^/    /' >&2 || true
  err "Check the machine token, the org filter, or network egress to pantheon.io."
  exit 1
fi

# Normalize to a plain list of names. NOTE: `mapfile` was the original
# implementation and is a bash 4+ builtin - it silently failed on macOS bash
# 3.2 and this script never completed a run for weeks. while-read is portable.
SITE_NAMES=""
while IFS= read -r line; do
  [ -n "$line" ] && SITE_NAMES="$SITE_NAMES$line"$'\n'
done <<EOF
$(printf '%s' "$SITES_JSON" | jq -r '.[].name')
EOF

# Optional explicit subset (comma separated), for a small test cohort.
if [ -n "$SITE_FILTER" ]; then
  FILTERED=""
  OLD_IFS="$IFS"; IFS=','
  for want in $SITE_FILTER; do
    want="$(printf '%s' "$want" | tr -d '[:space:]')"
    [ -z "$want" ] && continue
    if printf '%s' "$SITE_NAMES" | grep -qx "$want"; then
      FILTERED="$FILTERED$want"$'\n'
    else
      warn "requested site not found in fleet, ignoring: $want"
    fi
  done
  IFS="$OLD_IFS"
  SITE_NAMES="$FILTERED"
fi

# Optional head-N cap, for a cheap smoke run.
if [ "$SITE_LIMIT" -gt 0 ]; then
  SITE_NAMES="$(printf '%s' "$SITE_NAMES" | head -n "$SITE_LIMIT")"$'\n'
fi

TOTAL="$(printf '%s' "$SITE_NAMES" | grep -c . || true)"
if [ "$TOTAL" -eq 0 ]; then
  err "site list is empty after filtering."
  exit 1
fi
log "Scanning $TOTAL site(s), '$TARGET_ENV' environment on each..."

# ---------- per-site scan ----------
results="[]"
now_epoch="$(date +%s)"
i=0

# Read the site list from a here-doc rather than a pipe, so the loop body runs
# in THIS shell and `results` survives each iteration. A `| while read` pipeline
# would run in a subshell and silently discard every result.
#
# AND READ IT ON FD 3, NOT STDIN. This is the fix for a bug that made every
# full-mode scan ever run - laptop and CI alike - scan exactly ONE site and
# then report the requested count as though it had scanned them all.
#
# `terminus remote:wp` spawns ssh, and ssh reads stdin. With the here-doc on
# stdin, ssh drained the remaining site names on the first site and the loop
# exited with nothing left to read. api-only runs were unaffected, which is
# why 52-site scans looked healthy and the bug stayed invisible until full
# mode was switched on.
#
# A dedicated descriptor is immune to ANY child that reads stdin, not just the
# ones we currently know about, which is why this is preferred over adding
# </dev/null to each terminus call.
while IFS= read -r site <&3; do
  [ -z "$site" ] && continue
  i=$((i+1))
  log "[$i/$TOTAL] $site"
  se="$site.$TARGET_ENV"

  framework="$(printf '%s' "$SITES_JSON" | jq -r --arg s "$site" '.[] | select(.name==$s) | .framework // "unknown"')"
  plan="$(printf '%s' "$SITES_JSON"      | jq -r --arg s "$site" '.[] | select(.name==$s) | .plan_name // "unknown"')"
  frozen="$(printf '%s' "$SITES_JSON"    | jq -r --arg s "$site" '.[] | select(.name==$s) | (.frozen|tostring) // "false"')"

  # --- frozen sites are dormant; report and skip deep checks ---
  if [ "$frozen" = "true" ]; then
    obj="$(jq -n --arg site "$site" --arg fw "$framework" --arg plan "$plan" --arg env "$TARGET_ENV" \
      '{site:$site,framework:$fw,plan:$plan,env:$env,frozen:true,status:"FROZEN",
        notes:"Site is frozen (dormant); deep checks skipped."}')"
    results="$(jq --argjson o "$obj" '. + [$o]' <<<"$results")"
    printf '%s' "$results" | jq '.' > "$JSON_OUT"
    sleep "$SLEEP_BETWEEN"; continue
  fi

  # --- environment preflight (API only, no SSH) ---
  # This is the fix for the pfannenbergpartners hang: live/test EXISTED on
  # Pantheon but were never initialized, and remote:wp against an uninitialized
  # environment hung forever with no error. Checking env:list first is cheap and
  # catches it. "Check failed" and "confirmed absent" are DELIBERATELY distinct
  # outcomes - collapsing them is what produced the galbanicheese false result.
  envs_json="$(run_with_timeout "$ENV_CHECK_TIMEOUT" terminus env:list "$site" --format=json | json_or_empty)" || envs_json=""
  if [ -z "$envs_json" ]; then
    obj="$(jq -n --arg site "$site" --arg fw "$framework" --arg plan "$plan" --arg env "$TARGET_ENV" \
      '{site:$site,framework:$fw,plan:$plan,env:$env,frozen:false,status:"ERROR",
        notes:"Environment preflight failed (timeout or unparseable response). Status unknown, NOT confirmed absent."}')"
    results="$(jq --argjson o "$obj" '. + [$o]' <<<"$results")"
    printf '%s' "$results" | jq '.' > "$JSON_OUT"
    warn "$site: env preflight failed, status unknown"
    sleep "$SLEEP_BETWEEN"; continue
  fi

  # env:list returns an object keyed by env name in Terminus 3.x, but normalize
  # an array shape too. CAREFUL WITH jq's `//`: it falls through on `false` as
  # well as `null`, so `.initialized // true` would read an UNINITIALIZED
  # environment as initialized. has() is checked explicitly for that reason.
  env_state="$(printf '%s' "$envs_json" | jq -r --arg e "$TARGET_ENV" '
    (if type=="array" then (map({key:(.id//.name//""),value:.}) | from_entries) else . end)
    | [ to_entries[]? | select(.key==$e or ((.value|type=="object") and ((.value.id?)==$e))) ]
    | if length==0 then "missing"
      else (.[0].value) as $v
        | if (($v|type=="object") and ($v|has("initialized")))
          then (if (($v.initialized|tostring)=="true") then "ok" else "uninitialized" end)
          else "ok" end
      end' 2>/dev/null || echo "")"

  if [ "$env_state" != "ok" ]; then
    reason="does not exist"
    [ "$env_state" = "uninitialized" ] && reason="exists but was never initialized"
    [ -z "$env_state" ] && reason="could not be determined from the env list response"
    obj="$(jq -n --arg site "$site" --arg fw "$framework" --arg plan "$plan" --arg env "$TARGET_ENV" --arg reason "$reason" \
      '{site:$site,framework:$fw,plan:$plan,env:$env,frozen:false,status:"SKIP",
        notes:("Environment \($env) \($reason); skipped without attempting SSH.")}')"
    results="$(jq --argjson o "$obj" '. + [$o]' <<<"$results")"
    printf '%s' "$results" | jq '.' > "$JSON_OUT"
    log "$site: $TARGET_ENV $reason, skipping"
    sleep "$SLEEP_BETWEEN"; continue
  fi

  # --- PHP version ---
  php_ver="$(run_with_timeout "$API_CALL_TIMEOUT" terminus env:info "$se" --field=php_version | strip_noise | tr -d '[:space:]')" || php_ver=""
  [ -z "$php_ver" ] && php_ver="unknown"

  # --- newest database backup age ---
  backups_json="$(run_with_timeout "$API_CALL_TIMEOUT" terminus backup:list "$se" --element=database --format=json | json_or_empty)" || backups_json=""
  newest_backup_epoch=0
  if [ -n "$backups_json" ] && [ "$backups_json" != "[]" ]; then
    # tonumber? guards against a string or null date field; floor guards against
    # a float timestamp, either of which would make the `-gt` test below error.
    newest_backup_epoch="$(printf '%s' "$backups_json" | jq -r '[.[].date? // 0 | tonumber? // 0] | (max // 0) | floor' 2>/dev/null || echo 0)"
  fi
  case "$newest_backup_epoch" in ''|*[!0-9]*) newest_backup_epoch=0 ;; esac
  # 9999 is the deliberate "unknown / none found" sentinel: it scores CRIT,
  # which is the safe direction to fail for a backup check.
  if [ "$newest_backup_epoch" -gt 0 ]; then
    backup_age_days=$(( (now_epoch - newest_backup_epoch) / 86400 ))
  else
    backup_age_days=9999
  fi

  # --- pending upstream (platform) updates ---
  run_with_timeout "$API_CALL_TIMEOUT" terminus site:upstream:clear-cache "$site" >/dev/null 2>&1 || true
  upstream_json="$(run_with_timeout "$API_CALL_TIMEOUT" terminus upstream:updates:list "$site.dev" --format=json | json_or_empty)" || upstream_json=""
  upstream_count=0
  if [ -n "$upstream_json" ] && [ "$upstream_json" != "[]" ]; then
    upstream_count="$(printf '%s' "$upstream_json" | jq 'length' 2>/dev/null || echo 0)"
  fi

  # --- WordPress specifics via remote WP-CLI (SSH; skipped in API-only mode) ---
  wp_core_update="n/a"; plugin_updates=0; theme_updates=0; wp_checked="false"
  # null, never []. An empty array would say "we inventoried this site and it
  # runs no plugins", which is never true of a WordPress site and is exactly
  # the fabricated-negative shape the ledger refuses elsewhere.
  components="null"
  component_scan='{"plugin":false,"mu-plugin":false,"theme":false}'
  components_checked="false"
  # "n/a" means this scan did not look. It is NOT the same as "unknown", which
  # means it looked and could not tell. Keeping them distinct is the whole
  # reason the WP columns could be trusted the day full mode came on.
  wp_version="n/a"
  # RESET PER SITE, before the case. These are assigned inside the WordPress
  # branch only, and this loop reuses one shell: without the reset, a
  # non-WordPress site or an --api-only run would inherit the PREVIOUS site's
  # sending domain and publish it as its own. Same trap as every other
  # accumulating variable in this loop.
  smtp_plugin_seen="n/a"
  smtp_from_domain="n/a"
  smtp_relay_host="n/a"
  case "$framework" in
    wordpress*)
      if [ "$API_ONLY" -eq 0 ]; then
        wp_checked="true"
        # The version the site is ACTUALLY ON. check-update below reports only
        # the version available, and yields the string "up-to-date" when there
        # is none, which says nothing about what is installed. The workbook
        # claims 7.0.2 fleet-wide and has never been verified; "up-to-date" can
        # not be compared to "7.0.2", so without this the central question of
        # the project stays unanswered on a scan that looks complete.
        # Plain text, not JSON, so it is matched as a version rather than parsed.
        wp_version="$(run_with_timeout "$WP_CLI_TIMEOUT" terminus remote:wp "$se" -- core version 2>/dev/null \
                      | strip_noise | tr -d '\r' \
                      | grep -Eom1 '[0-9]+(\.[0-9]+)+')" || wp_version=""
        [ -z "$wp_version" ] && wp_version="unknown"

        # ITEM 22, fixed 2026-08-23. AN EMPTY RESULT AND A FAILED CALL ARE
        # DIFFERENT ANSWERS AND MUST NOT SHARE A BRANCH.
        #
        # These three used to fall to "up-to-date", 0 and 0 whenever
        # json_or_empty returned nothing -- which happens on a timeout, on a
        # non-zero exit, AND on output that would not parse. Only a genuine
        # `[]` means "we looked and nothing is pending". Measured, not
        # theorised: on 2026-08-23 diagnose-wp-calls.sh found galbanicheese
        # recording 0 plugin updates while WP-CLI had returned 15, and
        # cm-whitelabel recording up-to-date on a site whose database is not
        # installed at all.
        #
        # `unknown` and JSON null are what the ledger already reads as "nobody
        # established this" (see fact() in fleet-ledger.py), so no ingest
        # change is needed -- and severity's rules all refuse to fire on
        # unknown, which is the whole point.
        core_json="$(run_with_timeout "$WP_CLI_TIMEOUT" terminus remote:wp "$se" -- core check-update --format=json | json_or_empty)" || core_json=""
        if [ -z "$core_json" ]; then
          wp_core_update="unknown"          # the call failed; nobody looked
        elif [ "$core_json" = "[]" ]; then
          wp_core_update="up-to-date"       # measured: nothing pending
        else
          wp_core_update="$(printf '%s' "$core_json" | jq -r '.[0].version // "up-to-date"' 2>/dev/null || echo "unknown")"
        fi
        # FULL INVENTORY, NOT THE UPDATE BACKLOG. Until 2026-08-23 these two
        # calls carried `--update=available`, so they returned only components
        # with a pending update and the scanner kept `jq 'length'`.
        #
        # That is the wrong question for the case this tool exists to answer.
        # When Pods CVE-2026-19598 was disclosed on 2026-08-15 there was no
        # patch for roughly 36 hours. During that window `--update=available`
        # listed nothing for an affected site, because no update existed to
        # report. The only useful output was "these sites run pods, at these
        # versions", and it needed the whole list. See docs/VULN-INTEL-REVIEW.md
        # section 3, item 1.
        #
        # The counts below are derived from the full list, so plugin_updates
        # and theme_updates mean exactly what they meant before and severity
        # is unaffected. Explicit --fields because update_version is not in
        # WP-CLI's default set and it is what a version matcher needs.
        pj="$(run_with_timeout "$WP_CLI_TIMEOUT" terminus remote:wp "$se" -- plugin list --fields=name,status,update,version,update_version --format=json | json_or_empty)" || pj=""
        if [ -z "$pj" ]; then
          plugin_updates="null"             # JSON null -> UNKNOWN at ingest
          pj_ok="false"
        else
          plugin_updates="$(printf '%s' "$pj" | jq '[.[]|select(.update=="available")]|length' 2>/dev/null || echo null)"
          pj_ok="true"
        fi
        # mu-plugins are invisible to `plugin list`: it omits must-use unless
        # asked. They are loaded on every request and cannot be deactivated,
        # so leaving them out would put a silent hole in the inventory exactly
        # where it matters most. Pantheon installs its own here.
        mj="$(run_with_timeout "$WP_CLI_TIMEOUT" terminus remote:wp "$se" -- plugin list --status=must-use --fields=name,status,version --format=json | json_or_empty)" || mj=""
        [ -z "$mj" ] && mj_ok="false" || mj_ok="true"
        tj="$(run_with_timeout "$WP_CLI_TIMEOUT" terminus remote:wp "$se" -- theme list --fields=name,status,update,version,update_version --format=json | json_or_empty)" || tj=""
        if [ -z "$tj" ]; then
          theme_updates="null"
          tj_ok="false"
        else
          theme_updates="$(printf '%s' "$tj" | jq '[.[]|select(.update=="available")]|length' 2>/dev/null || echo null)"
          tj_ok="true"
        fi

        # THE SENDING DOMAIN, MEASURED RATHER THAN READ OFF THE WORKBOOK.
        #
        # SPF, DKIM and DMARC are all queried at the SENDING domain, and that
        # value is a RULING: a person typed it into the audit workbook and
        # nothing has ever checked it. Nothing in DNS reveals where a
        # WordPress site was configured to send from, so it cannot be derived
        # -- but the site itself knows, and this scan is already inside it.
        #
        # A wrong ruling does not fail loudly. It queries _dmarc. at a host
        # nobody sends from and returns a confident PASS about the wrong
        # domain. 7 of 78 sites have no ruling at all and report UNKNOWN.
        #
        # STORED UNDER ITS OWN NAME, never overwriting the workbook's value.
        # That is the `nexcess_php_version` precedent: one name per way of
        # knowing, so a disagreement is a fact rather than a silent
        # resolution in favour of whichever ran last.
        #
        # Gated on the plugin list this run already fetched, so a site with no
        # post-smtp costs no extra WP-CLI call and records WHY there is no
        # measurement instead of a bare unknown.
        smtp_plugin_seen="none"
        smtp_from_domain="n/a"
        smtp_relay_host="n/a"
        if [ "$pj_ok" = "false" ]; then
          # The plugin list itself did not answer. We do not know which mailer
          # is installed, let alone how it is set up. "none" here would read as
          # "this site sends no mail", which is the fabricated negative the
          # whole ledger is built to refuse.
          smtp_plugin_seen="unknown"
          smtp_from_domain="unknown"
          smtp_relay_host="unknown"
        elif printf '%s' "$pj" | jq -e 'any(.[]; (.name|ascii_downcase)=="post-smtp")' >/dev/null 2>&1; then
          smtp_plugin_seen="post-smtp"
          # Present but not yet read: if the option call below fails these stay
          # unknown, which is a different answer from "no mailer installed".
          smtp_from_domain="unknown"
          smtp_relay_host="unknown"
          # `option get` exits non-zero when the option does not exist, so an
          # empty result covers a missing option, a failed call and a timeout
          # alike -- all three are "we could not tell", none is a value.
          po="$(run_with_timeout "$WP_CLI_TIMEOUT" terminus remote:wp "$se" -- option get postman_options --format=json | json_or_empty)" || po=""
          if [ -n "$po" ]; then
            # SEVERAL KEYS, NOT ONE. post-smtp has carried the sender under
            # different names across its Postman-era and post-smtp-era
            # releases, and the option key was never verified against a live
            # site before this shipped. Trying the known spellings and
            # recording `unknown` when none match is the honest failure; a
            # single hardcoded key would silently report "unknown" on whole
            # families of versions and look like a coverage gap instead of a
            # parser that is out of date.
            fe="$(printf '%s' "$po" | jq -r '(.from_email // .envelope_sender // .from_email_address // empty) | tostring' 2>/dev/null)" || fe=""
            case "$fe" in
              *@*.*) smtp_from_domain="$(printf '%s' "${fe##*@}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" ;;
            esac
            rh="$(printf '%s' "$po" | jq -r '(.hostname // .host // empty) | tostring' 2>/dev/null)" || rh=""
            case "$rh" in
              *.*) smtp_relay_host="$(printf '%s' "$rh" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" ;;
            esac
          fi
        elif printf '%s' "$pj" | jq -e 'any(.[]; (.name|ascii_downcase)=="wp-mail-smtp")' >/dev/null 2>&1; then
          # Recorded, not read. Its options live under a different key and no
          # rule for it has been verified against a live site. n/a is right:
          # this scan did not look, which is not the same as could not tell.
          smtp_plugin_seen="wp-mail-smtp"
        fi

        # One array per site, typed. A call that FAILED contributes nothing and
        # is recorded as unknown in component_scan below -- it must never be
        # indistinguishable from a call that succeeded and found none, which is
        # the whole bug table in CLAUDE.md.
        #
        # If EVERY call failed there is no inventory, and that must be null
        # rather than []. The first cut of this used `${pj:-[]}` throughout and
        # dbmissing -- a site whose database is not installed, so every
        # DB-backed call exits 1 -- came out as `components: []`, which reads
        # as "we inventoried it and it runs nothing". Caught by running the
        # mock, not by review.
        if [ "$pj_ok" = "false" ] && [ "$mj_ok" = "false" ] && [ "$tj_ok" = "false" ]; then
          components="null"
        else
          components="$(jq -n \
            --argjson p "${pj:-[]}" --argjson m "${mj:-[]}" --argjson t "${tj:-[]}" \
            '[ ($p[] | .type="plugin"),
               ($m[] | .type="mu-plugin" | .update="none"),
               ($t[] | .type="theme") ]' 2>/dev/null || echo 'null')"
        fi
        component_scan="$(jq -n --arg p "$pj_ok" --arg m "$mj_ok" --arg t "$tj_ok" \
          '{plugin:($p=="true"),"mu-plugin":($m=="true"),theme:($t=="true")}')"
        # The scalar the LEDGER stores. component_scan stays in the report for
        # diagnosis; the ledger needs one boolean it can score and diff.
        components_checked="false"
        [ "$components" != "null" ] && components_checked="true"
      fi
      ;;
  esac

  # --- severity scoring ---
  status="OK"; notes=""
  add_note() { if [ -z "$notes" ]; then notes="$1"; else notes="$notes; $1"; fi; }

  if [ "$backup_age_days" -gt "$BACKUP_MAX_AGE_DAYS" ]; then
    status="CRIT"
    if [ "$backup_age_days" -eq 9999 ]; then
      add_note "No DB backup found at all"
    else
      add_note "No DB backup in ${backup_age_days}d"
    fi
  fi
  if [ "$wp_core_update" != "up-to-date" ] && [ "$wp_core_update" != "n/a" ] && [ "$wp_core_update" != "unknown" ]; then
    status="CRIT"; add_note "WP core update available: $wp_core_update"
  fi
  # "null" is not a number. Guard before the arithmetic test, or bash prints
  # "integer expression expected" once per unmeasured site and evaluates it as
  # false -- which would put an unmeasured site back on the OK path by a
  # different route than the one just closed.
  if [ "$plugin_updates" != "null" ] && [ "$plugin_updates" -gt 0 ]; then
    [ "$status" = "OK" ] && status="WARN"; add_note "$plugin_updates plugin update(s)"
  fi
  if [ "$theme_updates" != "null" ] && [ "$theme_updates" -gt 0 ]; then
    [ "$status" = "OK" ] && status="WARN"; add_note "$theme_updates theme update(s)"
  fi
  # The scanner's own status is superseded by severity.py at render time, but
  # it must still not call an unmeasured site OK in its own JSON and console.
  if [ "$wp_checked" = "true" ] && { [ "$plugin_updates" = "null" ] \
       || [ "$theme_updates" = "null" ] || [ "$wp_core_update" = "unknown" ]; }; then
    [ "$status" = "OK" ] && status="WARN"
    add_note "WP-CLI did not answer for one or more checks; those read unknown"
  fi
  if [ "$upstream_count" -gt 0 ]; then
    [ "$status" = "OK" ] && status="WARN"; add_note "$upstream_count upstream commit(s) pending"
  fi
  if [ "$API_ONLY" -eq 1 ]; then
    add_note "API-only run: WP core/plugin/theme not checked"
  fi
  [ -z "$notes" ] && notes="All checks passed"

  obj="$(jq -n \
    --arg site "$site" --arg fw "$framework" --arg plan "$plan" \
    --arg env "$TARGET_ENV" --arg php "$php_ver" \
    --argjson backup_age "$backup_age_days" \
    --argjson upstream "$upstream_count" \
    --arg core "$wp_core_update" \
    --arg wpver "$wp_version" \
    --argjson plugins "$plugin_updates" --argjson themes "$theme_updates" \
    --argjson wp_checked "$wp_checked" \
    --argjson components "$components" \
    --argjson component_scan "$component_scan" \
    --argjson components_checked "$components_checked" \
    --arg smtp_plugin_seen "$smtp_plugin_seen" \
    --arg smtp_from_domain "$smtp_from_domain" \
    --arg smtp_relay_host "$smtp_relay_host" \
    --arg status "$status" --arg notes "$notes" \
    '{site:$site,framework:$fw,plan:$plan,env:$env,php_version:$php,
      db_backup_age_days:$backup_age,upstream_pending:$upstream,
      wp_checked:$wp_checked,wp_version:$wpver,wp_core_update:$core,
      plugin_updates:$plugins,theme_updates:$themes,
      components:$components,component_scan:$component_scan,
      components_checked:$components_checked,
      smtp_plugin_seen:$smtp_plugin_seen,
      smtp_from_domain:$smtp_from_domain,
      smtp_relay_host:$smtp_relay_host,
      status:$status,notes:$notes,frozen:false}')"
  results="$(jq --argjson o "$obj" '. + [$o]' <<<"$results")"

  # Write after EVERY site, not just at the end, so a killed or timed-out run
  # still leaves behind everything gathered so far.
  printf '%s' "$results" | jq '.' > "$JSON_OUT"

  sleep "$SLEEP_BETWEEN"
done 3<<EOF
$SITE_NAMES
EOF

# ---------- outputs ----------
printf '%s' "$results" | jq '.' > "$JSON_OUT"

printf '%s' "$results" | jq -r '
  (["site","framework","plan","env","php_version","db_backup_age_days","upstream_pending","wp_checked","wp_version","wp_core_update","plugin_updates","theme_updates","status","notes"]),
  (.[] | [.site,.framework,.plan,.env,(.php_version//""),(.db_backup_age_days//""),(.upstream_pending//""),(.wp_checked//false),(.wp_version//""),(.wp_core_update//""),(.plugin_updates//""),(.theme_updates//""),.status,.notes])
  | @csv' > "$CSV_OUT"

SCANNED=$(printf '%s' "$results" | jq 'length')
crit=$(printf '%s' "$results"   | jq '[.[]|select(.status=="CRIT")]|length')
warn_n=$(printf '%s' "$results" | jq '[.[]|select(.status=="WARN")]|length')
ok=$(printf '%s' "$results"     | jq '[.[]|select(.status=="OK")]|length')
frozen_n=$(printf '%s' "$results" | jq '[.[]|select(.status=="FROZEN")]|length')
skip_n=$(printf '%s' "$results" | jq '[.[]|select(.status=="SKIP")]|length')
err_n=$(printf '%s' "$results"  | jq '[.[]|select(.status=="ERROR")]|length')

MODE_LABEL="full scan"
[ "$API_ONLY" -eq 1 ] && MODE_LABEL="API-only (no SSH / WP-CLI)"

{
  echo "# Pantheon Fleet Health - $STAMP"
  echo ""
  # Report what was actually SCANNED, not what was requested.
  #
  # This line used to print $TOTAL, the size of the requested list, without
  # ever checking it against the results. On 2026-08-18 it read "Scanned 3
  # site(s)" above a table containing one row and a tally summing to one, and
  # the run was marked a success. The count a reader trusts most was the one
  # number nothing verified.
  echo "Scanned **$SCANNED** site(s), \`$TARGET_ENV\` environment. Mode: **$MODE_LABEL**."
  echo ""
  echo "**$crit critical / $warn_n warning / $ok healthy / $frozen_n frozen / $skip_n skipped / $err_n errored**"
  echo ""
  if [ "$SCANNED" -ne "$TOTAL" ]; then
    echo "> **$((TOTAL - SCANNED)) of $TOTAL requested site(s) produced no row at all.**"
    echo "> They were neither healthy nor skipped nor errored - they are simply"
    echo "> absent, so nothing below says anything about them. Treat this run as"
    echo "> incomplete rather than clean."
    echo ""
  fi
  if [ "$API_ONLY" -eq 1 ]; then
    echo "> API-only run. WordPress core, plugin, and theme update status was NOT"
    echo "> checked on any site. Backup age and upstream drift are complete."
    echo ""
  fi
  echo "## Needs attention"
  echo ""
  echo "| Site | Status | Plan | PHP | Backup age (d) | WP | Core | Plugins | Themes | Notes |"
  echo "|------|--------|------|-----|----------------|----|------|---------|--------|-------|"
  printf '%s' "$results" | jq -r '
    [.[]|select(.status=="CRIT" or .status=="WARN")]
    | sort_by(.status)
    | .[]
    | "| \(.site) | \(.status) | \(.plan // "-") | \(.php_version // "-") | \(.db_backup_age_days // "-") | \(.wp_version // "-") | \(.wp_core_update // "-") | \(.plugin_updates // "-") | \(.theme_updates // "-") | \(.notes) |"'
  echo ""
  if [ "$skip_n" -gt 0 ] || [ "$err_n" -gt 0 ]; then
    echo "## Not scanned"
    echo ""
    echo "| Site | Status | Reason |"
    echo "|------|--------|--------|"
    printf '%s' "$results" | jq -r '
      [.[]|select(.status=="SKIP" or .status=="ERROR")] | .[]
      | "| \(.site) | \(.status) | \(.notes) |"'
    echo ""
  fi
  echo "## Healthy"
  echo ""
  printf '%s' "$results" | jq -r '[.[]|select(.status=="OK")|.site] | join(", ")'
  echo ""
  echo "_Read-only scan. No changes were made to any site._"
} > "$MD_OUT"

log ""
log "Done. Outputs:"
log "  $MD_OUT"
log "  $CSV_OUT"
log "  $JSON_OUT"
log "Summary: $crit CRIT / $warn_n WARN / $ok OK / $frozen_n FROZEN / $skip_n SKIP / $err_n ERROR"
if [ "$SCANNED" -ne "$TOTAL" ]; then
  warn "INCOMPLETE: $SCANNED of $TOTAL requested site(s) produced a row."
fi

if [ "$crit" -gt 0 ] && [ "$FAIL_ON_CRIT" -eq 1 ]; then
  exit 2
fi
exit 0
