#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# nexcess-fleet-healthcheck.sh
#
# WordPress health for the Nexcess estate, over SSH + WP-CLI. Read-only.
#
# It is the Pantheon scanner with a different transport, deliberately. Same
# five WP-CLI calls, same fact names, same `health` source in the ledger. The
# fact-name collision guard in fleet-ledger.py REFUSES a second source
# claiming wp_version, and that is the right answer: WP-CLI on Nexcess and
# WP-CLI on Pantheon are the same evidence, so they belong on one timeline.
#
# ---------------------------------------------------------------------------
# THE COMMAND LIST IS A SECURITY CONTROL. READ IT AS ONE.
# ---------------------------------------------------------------------------
# Nexcess confirmed 2026-08-24 that no read-only or command-restricted SSH user
# exists on Managed WordPress. Every SSH identity has read AND WRITE on the
# site filesystem, and they said restricting one to `wp core version` is not
# possible.
#
# So the credential this script holds can change client sites. The only thing
# preventing that is the list below. Every command is enumerated here, in one
# place, and nothing builds a command string from data returned by a site.
#
#   test -d ~/public_html -- reachability probe, so "cannot log in" and "runs
#                            nothing" are never the same row
#   cd ~/public_html      -- a symlink Nexcess maintains to the WordPress root
#   wp core version
#   wp core check-update --format=json
#   wp plugin list --fields=... --format=json
#   wp plugin list --status=must-use --fields=... --format=json
#   wp theme list --fields=... --format=json
#   wp option get postman_options --format=json
#
# All seven are reads. If you add one, it needs the same review as a firewall
# rule, not the same review as a scan tweak.
#
# REVIEWED AND APPROVED 2026-08-25 by Doug Kasperek, before the first
# fleet-wide run. The approval says a person read these commands, confirmed
# every one is a read, and confirmed nothing else in this file runs anything
# on a site.
#
# CORRECTION, same day, after the first run: the list approved was INCOMPLETE.
# `test -d ~/public_html` was running as the reachability probe and was not
# written down. It is a read and changes nothing, but an approved list that
# does not match what the script runs is not an approval of anything. It is
# listed above now, and this note stays as the record that the list drifted
# from the code within hours of being signed off.
#
# SEVENTH COMMAND ADDED AND RE-APPROVED 2026-08-26 by Doug Kasperek:
# `wp option get postman_options --format=json`. He confirmed it is a read.
# It returns one row of the WordPress options table and writes nothing, and
# the identical call had already run on 39 Pantheon sites and two diagnostic
# sites before this approval was sought.
#
# What it buys: the SENDING DOMAIN, measured off the site instead of taken
# from the audit workbook. 20 of the 21 Nexcess sites run post-smtp, so this
# takes fleet coverage from 39 of 75 to 59 of 75, and closes
# hitsfoundation.org -- the only site with no recorded sending domain that any
# version of this measurement can reach.
#
# **A change to this list invalidates that approval.** Adding an eighth command
# is not a scan tweak, and nothing in the system will stop you: there is no
# permission error to hit, because the credential can already write. Get it
# re-reviewed and record the new approval here.
# ---------------------------------------------------------------------------
#
# VERIFIED ON A REAL SITE 2026-08-25 (eamusicfest.com):
#   - the account-level key authenticates; the portal's `_1` username suffix is
#     correct
#   - `~/public_html` is a symlink to the WordPress root. The site directory is
#     named after a DOMAIN, and the API gives us the TEMP domain for 18 of 22
#     sites, so deriving the path from a domain would fail on most of the
#     fleet. The symlink sidesteps it.
#   - output is CLEAN. `wp core version` returns exactly "7.1\n", and all three
#     list calls return JSON with no banner, no deprecation notice, nothing
#     before the `[`. Cleaner than Pantheon, whose mu-plugin noise caused item
#     22. strip_noise still runs, because "clean on one site today" is not a
#     property of the fleet.
#
# WHAT THIS CANNOT MEASURE: backup age. On Pantheon that comes from
# `terminus backup:list`, an API call, not from WP-CLI. Nexcess has no
# equivalent we can reach, so db_backup_age_days stays unknown for these sites
# and `backup_stale` cannot score them. They will read WARN with a named gap
# rather than reaching OK. That is correct and must not be papered over.
#
#   ./scripts/nexcess-fleet-healthcheck.sh --stamp "$(date -u +%Y-%m-%d_%H%M)"
#   ./scripts/nexcess-fleet-healthcheck.sh --sites eamusicfest.com --dry-run
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$HERE/lib/common.sh"

SSH_KEY="${NEXCESS_SSH_KEY_PATH:-$HOME/.ssh/nexcess_ci}"
HISTORY_DIR="./history"
INVENTORY="data/fleet-inventory.json"
OUT_DIR="./reports"
STAMP=""
ONLY_SITES=""
DRY_RUN=0
WP_TIMEOUT=60
SSH_TIMEOUT=20
KNOWN_HOSTS="${NEXCESS_KNOWN_HOSTS:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --key)         SSH_KEY="$2"; shift 2 ;;
    --history)     HISTORY_DIR="$2"; shift 2 ;;
    --inventory)   INVENTORY="$2"; shift 2 ;;
    --out)         OUT_DIR="$2"; shift 2 ;;
    --stamp)       STAMP="$2"; shift 2 ;;
    --sites)       ONLY_SITES="$2"; shift 2 ;;
    --known-hosts) KNOWN_HOSTS="$2"; shift 2 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    -h|--help)     sed -n '2,58p' "$0"; exit 0 ;;
    *) err "unknown argument: $1"; exit 2 ;;
  esac
done

[ -n "$STAMP" ] || STAMP="$(date -u +%Y-%m-%d_%H%M)"
JSON_OUT="$OUT_DIR/fleet-health-nexcess-$STAMP.json"

require_tools ssh jq python3

if [ ! -f "$SSH_KEY" ]; then
  err "No SSH key at $SSH_KEY."
  err "Generate one (RSA, no passphrase, dedicated to automation):"
  err "  ssh-keygen -t rsa -b 4096 -C 'cm-automation Nexcess CI' -f ~/.ssh/nexcess_ci -N ''"
  err "then add the .pub half at the Nexcess portal under User Menu -> SSH Keys."
  exit 2
fi

# ---------------------------------------------------------------------------
# Targets come from the LEDGER, via the control-plane scan. Not from a list in
# this file, and not from reports/, which is gitignored and absent on a runner.
# ---------------------------------------------------------------------------
TARGETS="$(mktemp)"; trap 'rm -f "$TARGETS"' EXIT
"$HERE/nexcess-ssh-targets.py" --history "$HISTORY_DIR" \
    --inventory "$INVENTORY" --format tsv > "$TARGETS" || {
  err "Could not resolve any SSH targets. Run the control-plane scan first."
  exit 2
}

TOTAL="$(grep -c . "$TARGETS" || true)"
log "Nexcess SSH health scan: $TOTAL target(s), key $SSH_KEY"

# StrictHostKeyChecking: `accept-new` trusts a host the first time and pins it
# afterwards. It is NOT `no`, which would accept a changed key silently and
# hand a write-capable credential to whatever answered. Pass --known-hosts with
# a pre-populated file in CI, where trust-on-first-use is not good enough.
# StrictHostKeyChecking APPEARS EXACTLY ONCE. ssh takes the FIRST value it is
# given for an option, not the last, so appending `=yes` after `=accept-new`
# left accept-new in force and the pin enforcing nothing. The negative control
# caught it: removing a host from the pinned file and scanning it anyway
# succeeded, and accept-new then WROTE the host into the file it had been told
# to treat as authoritative.
#
# A control that is present, looks correct and enforces nothing is worse than
# no control, because it is the one nobody re-tests.
if [ -n "$KNOWN_HOSTS" ]; then
  # Pinned. A host not in this file is refused, and the file is never written
  # to, so a run cannot quietly widen its own trust.
  SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT"
            -o StrictHostKeyChecking=yes
            -o UserKnownHostsFile="$KNOWN_HOSTS")
else
  # Trust on first use. Fine on a laptop where a person sees the fingerprint.
  # NOT fine on a runner: this credential can write to client sites. CI passes
  # --known-hosts data/nexcess-known-hosts.
  SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT"
            -o StrictHostKeyChecking=accept-new)
fi

# ---------------------------------------------------------------------------
# run_wp: one WP-CLI call on one site.
#
# `< /dev/null` is load-bearing. ssh reads stdin, and inside a `while read`
# loop it swallows the REST OF THE TARGET LIST. That is how a Pantheon scan of
# ten sites silently scanned one, and it is line 5 of CLAUDE.md's bug table.
# ---------------------------------------------------------------------------
run_wp() {
  local user_host="$1" wp_args="$2"
  run_with_timeout "$WP_TIMEOUT" ssh "${SSH_OPTS[@]}" "$user_host" \
      "cd ~/public_html && wp $wp_args" < /dev/null 2>/dev/null
}

# Same command, stderr KEPT. See the framework note below for why.
#
# The `2>&1` is INSIDE the quoted remote command, and it has to be.
# `run_with_timeout` redirects its child's stderr to /dev/null unconditionally,
# so stderr must become stdout on the REMOTE side before the helper ever sees
# it. Redirecting on this side does nothing, which cost two wrong fixes.
run_wp_stderr() {
  local user_host="$1" wp_args="$2"
  run_with_timeout "$WP_TIMEOUT" ssh "${SSH_OPTS[@]}" "$user_host" \
      "cd ~/public_html && wp $wp_args 2>&1" < /dev/null
}

# A DRY RUN TOUCHES NOTHING. It resolves targets, prints them and stops, so it
# is safe to point at anything. Deciding this AFTER opening the output file
# meant a dry run still wrote, which is a small lie about what --dry-run means.
if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY RUN: resolving targets only. No connection, no file written."
  while IFS=$'\t' read -r site_id ssh_user ssh_host; do
    [ -n "$site_id" ] || continue
    if [ -n "$ONLY_SITES" ] && [[ ",$ONLY_SITES," != *",$site_id,"* ]]; then
      continue
    fi
    log "  would scan $site_id via $ssh_user@$ssh_host"
  done < "$TARGETS"
  log "Dry run complete. Nothing connected to, nothing written."
  exit 0
fi

# `reports/` IS GITIGNORED, so it does not exist on a fresh clone or a CI
# runner. CLAUDE.md says so in the data-model section and this script wrote
# into it anyway: the first real CI run died on
# `./reports/...json.tmp: No such file or directory`, AFTER resolving all 22
# targets correctly. mkdir was there, at the END, which is no use to a redirect
# on line 188.
mkdir -p "$OUT_DIR"

echo "[" > "$JSON_OUT.tmp"
first=1; scanned=0; unreachable=0; nowp=0

while IFS=$'\t' read -r site_id ssh_user ssh_host; do
  [ -n "$site_id" ] || continue
  if [ -n "$ONLY_SITES" ] && [[ ",$ONLY_SITES," != *",$site_id,"* ]]; then
    continue
  fi
  target="$ssh_user@$ssh_host"

  log "  $site_id ($target)"

  # THE REACHABILITY PROBE IS SEPARATE FROM THE MEASUREMENT, on purpose.
  # "the site runs no plugins" and "we could not log in" must never be the
  # same row. This project has shipped that bug twice.
  if ! run_with_timeout "$SSH_TIMEOUT" ssh "${SSH_OPTS[@]}" "$target" \
        "test -d ~/public_html" < /dev/null 2>/dev/null; then
    warn "    unreachable, or no ~/public_html. Recorded as UNKNOWN, not empty."
    unreachable=$((unreachable+1))
    row="$(jq -n --arg s "$site_id" \
      '{site:$s, site_id:$s, host_site_name:null, wp_checked:false,
        smtp_plugin_seen:"n/a", smtp_from_domain:"n/a", smtp_relay_host:"n/a",
        smtp_transport:"n/a",
        components_checked:false, scan_error:"ssh failed or ~/public_html missing"}')"
  else
    # STDERR IS KEPT for this one call, deliberately. `wp core version` on a
    # non-WordPress site prints "This does not seem to be a WordPress
    # installation", and that sentence is the only evidence we get that the
    # directory holds something else. Discarding it would leave the site
    # looking like WordPress we failed to measure.
    #
    # NO NEW COMMAND. Reading the error output of a command already on the
    # approved list is not an addition to the list. Testing for wp-config.php
    # would have been, and would have needed re-review.
    # `|| true`, NOT `|| core_raw=""`. `wp core version` EXITS NON-ZERO on a
    # non-WordPress directory, so the second form threw away the one sentence
    # that identifies the site. Caught on app.eastauroracc.com, which came back
    # framework=None when it should have been not-wordpress.
    core_raw="$(run_wp_stderr "$target" "core version" || true)"
    wp_version="$(printf '%s' "$core_raw" | strip_noise | grep -vi "^Error:" | grep -vi "^Pass --path" | head -n1 | tr -d '[:space:]')" || wp_version=""
    framework=""
    case "$core_raw" in
      *"not seem to be a WordPress installation"*) framework="not-wordpress" ;;
      *) [ -n "$wp_version" ] && framework="wordpress" ;;
    esac
    core_json="$(run_wp "$target" "core check-update --format=json" | json_or_empty)" || core_json=""
    pj="$(run_wp "$target" "plugin list --fields=name,status,update,version,update_version --format=json" | json_or_empty)" || pj=""
    mj="$(run_wp "$target" "plugin list --status=must-use --fields=name,status,version --format=json" | json_or_empty)" || mj=""
    tj="$(run_wp "$target" "theme list --fields=name,status,update,version,update_version --format=json" | json_or_empty)" || tj=""
    # THE SENDING DOMAIN. Seventh command, approved 2026-08-26 -- see the
    # header. Gated on post-smtp appearing in the plugin list already fetched,
    # so a site without it costs no extra SSH round trip and records WHY there
    # is no measurement rather than a bare unknown.
    smtp_plugin_seen="none"; smtp_from_domain="n/a"
    smtp_relay_host="n/a";   smtp_transport="n/a"
    if [ -z "$pj" ]; then
      # The plugin list did not answer, so which mailer is installed is
      # unknown too. "none" would read as "this site sends no mail".
      smtp_plugin_seen="unknown"; smtp_from_domain="unknown"
      smtp_relay_host="unknown";  smtp_transport="unknown"
    elif printf '%s' "$pj" | jq -e 'any(.[]; (.name|ascii_downcase)=="post-smtp")' >/dev/null 2>&1; then
      smtp_plugin_seen="post-smtp"; smtp_from_domain="unknown"
      smtp_relay_host="unknown";    smtp_transport="unknown"
      po="$(run_wp "$target" "option get postman_options --format=json" | json_or_empty)" || po=""
      if [ -n "$po" ]; then
        # Same parser as the Pantheon scanner, and the key names are the ones
        # a real site returned on 2026-08-26, not the ones post-smtp looks
        # like it ought to use. envelope_sender first: SPF is evaluated
        # against the envelope sender. jq -- select on non-empty, because "//"
        # falls back on null and false but NOT on the empty string, and
        # post-smtp stores "" in fields it is not using.
        fe="$(printf '%s' "$po" \
              | jq -r '[.envelope_sender, .sender_email, .from_email]
                       | map(select(type == "string" and . != ""))
                       | first // empty' 2>/dev/null)" || fe=""
        case "$fe" in
          *@*.*) smtp_from_domain="$(printf '%s' "${fe##*@}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" ;;
        esac
        tt="$(printf '%s' "$po" | jq -r '.transport_type // empty' 2>/dev/null)" || tt=""
        rh="$(printf '%s' "$po" \
              | jq -r '[.hostname, .host]
                       | map(select(type == "string" and . != ""))
                       | first // empty' 2>/dev/null)" || rh=""
        case "$rh" in
          *.*) smtp_relay_host="$(printf '%s' "$rh" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" ;;
          *)   [ -n "$tt" ] && smtp_relay_host="n/a" ;;
        esac
        [ -n "$tt" ] && smtp_transport="$(printf '%s' "$tt" | tr -d '[:space:]')"
      fi
    elif printf '%s' "$pj" | jq -e 'any(.[]; (.name|ascii_downcase)=="wp-mail-smtp")' >/dev/null 2>&1; then
      # Recorded, not read: its options live under a different key and no rule
      # for it has been verified against a live site.
      smtp_plugin_seen="wp-mail-smtp"
    fi

    # NO `${pj:-[]}` DEFAULTS. A failed call must not become an empty list:
    # that turned four WP-CLI failures into "we inventoried it and it runs
    # nothing" on cm-whitelabel. An absent value stays absent.
    if [ -z "$wp_version" ]; then
      nowp=$((nowp+1))
      warn "    wp core version returned nothing. Not recording a version."
    fi
    # A VENDOR DIFFERENCE, found 2026-08-25 by comparing counts: the scan
    # emitted 32 components and ingest stored 31.
    #
    # On Pantheon, `wp plugin list` OMITS must-use plugins, which is why the
    # Pantheon scanner asks for them separately. On Nexcess it INCLUDES them,
    # with status "must-use". So the two calls overlap here and `nexcess-mapps`
    # arrived twice, once as a plugin and once as a mu-plugin.
    #
    # Ingest de-duplicates and would have stored the right thing anyway. The
    # reason to fix it at the source is `plugin_updates`: a must-use plugin
    # with an update pending would be counted on Nexcess and not on Pantheon,
    # so the same fact would mean two different things depending on transport.
    # One ledger, one meaning.
    pj="$(printf '%s' "$pj" | jq -c '[.[] | select(.status != "must-use")]')" || pj=""

    have_components=false
    [ -n "$pj" ] && [ -n "$tj" ] && have_components=true

    row="$(jq -n \
      --arg s   "$site_id" \
      --arg wv  "$wp_version" \
      --argjson checked "$( [ -n "$wp_version" ] && echo true || echo false )" \
      --argjson comp    "$have_components" \
      --arg fw  "$framework" \
      --arg smtp_plugin_seen "$smtp_plugin_seen" \
      --arg smtp_from_domain "$smtp_from_domain" \
      --arg smtp_relay_host  "$smtp_relay_host" \
      --arg smtp_transport   "$smtp_transport" \
      --argjson core "$( [ -n "$core_json" ] && echo "$core_json" || echo null )" \
      --argjson plugins "$( [ -n "$pj" ] && echo "$pj" || echo null )" \
      --argjson muplugins "$( [ -n "$mj" ] && echo "$mj" || echo null )" \
      --argjson themes  "$( [ -n "$tj" ] && echo "$tj" || echo null )" \
      '{site:$s, site_id:$s, host_site_name:null,
        wp_checked:$checked,
        # THE SENDING DOMAIN IS NOT MEASURED BY THIS TRANSPORT, and these three
        # fields exist to say exactly that. Added 2026-08-26 alongside the
        # Pantheon scan that DOES measure it.
        #
        # They are literals. NOTHING RUNS ON A SITE FOR THEM, so the approved
        # command list at the top of this file is untouched. Reading the
        # post-smtp options here would need a seventh command and a fresh
        # review.
        #
        # Without them the keys are simply absent from the row, and the ledger
        # reads an absent deep-scan fact as UNKNOWN. On this cohort that is a
        # lie of the exact kind this file is full of warnings about: UNKNOWN
        # means we asked and could not tell, so 21 Nexcess sites would report
        # a mailer we had failed to read when the truth is that nothing asked.
        # "n/a" means the scan did not look.
        smtp_plugin_seen:$smtp_plugin_seen,
        smtp_from_domain:$smtp_from_domain,
        smtp_relay_host:$smtp_relay_host,
        smtp_transport:$smtp_transport,
        wp_version:(if $wv == "" then null else $wv end),
        framework:(if $fw == "" then null else $fw end),
        wp_core_update:(if $core == null then null
                        elif ($core|length) == 0 then "up-to-date"
                        else "available" end),
        plugin_updates:(if $plugins == null then null
                        else ([$plugins[]|select(.update=="available")]|length) end),
        theme_updates:(if $themes == null then null
                       else ([$themes[]|select(.update=="available")]|length) end),
        components_checked:$comp,
        components:(if $comp then
                      # Pass the WP-CLI fields through, adding only `type`.
                      # Same shape the Pantheon scanner emits, and it has to
                      # be: ingest reads `update == "available"`, the raw
                      # WP-CLI value. An earlier version here renamed it to
                      # `update_available` and dropped `update`, so ingest saw
                      # no key, read False for every component, and the
                      # components page showed ZERO updates pending on 21 sites
                      # while the fleet table said 187. Caught before
                      # publishing, by comparing the two numbers.
                      # NOTE: no apostrophes in this comment. It sits inside a
                      # single-quoted jq program, and one apostrophe ends the
                      # shell string. That cost a run.
                      ([$plugins[] | .type="plugin"]
                       + (if $muplugins == null then []
                          else [$muplugins[] | .type="mu-plugin" | .update="none"]
                          end)
                       + [$themes[] | .type="theme"])
                    else null end)}')"
    scanned=$((scanned+1))
  fi

  [ "$first" -eq 1 ] || echo "," >> "$JSON_OUT.tmp"
  printf '%s' "$row" >> "$JSON_OUT.tmp"
  first=0
done < "$TARGETS"

echo "" >> "$JSON_OUT.tmp"; echo "]" >> "$JSON_OUT.tmp"
mv "$JSON_OUT.tmp" "$JSON_OUT"
jq empty < "$JSON_OUT" || { err "produced invalid JSON"; exit 1; }

log ""
log "Done. $JSON_OUT"
log "Summary: $scanned scanned / $unreachable unreachable / $nowp answered but reported no WordPress version"
log ""
log "Backup age is NOT measured here and cannot be: Nexcess exposes no"
log "equivalent of terminus backup:list. Those sites stay WARN with a named"
log "gap rather than reaching OK."
