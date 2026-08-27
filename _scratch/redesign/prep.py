#!/usr/bin/env python3
"""Build concept-data.json for the redesign concepts.

Everything here is copied or aggregated from the renderer's own model
(_scratch/fleet-model-full.json = build_model()), the export, the inventory and
the ledger. Nothing is typed in. Where a value is derived, the derivation is a
counting rule stated in a comment, never a weight.
"""
import json, collections, datetime

M = json.load(open('/tmp/fleet/_scratch/fleet-model-full.json'))
X = json.load(open('/tmp/fleet/_scratch/fleet-data.json'))
INV = {s['site_id']: s for s in json.load(open('/tmp/fleet/data/fleet-inventory.json'))['sites']}
OBS = [json.loads(l) for l in open('/tmp/fleet/history/observations.jsonl')]
RUNS = [json.loads(l) for l in open('/tmp/fleet/history/runs.jsonl')]
TODAY = X['generated']

# ---- runs: latest per (source, kind), plus the full list ------------------
runs_sorted = sorted(RUNS, key=lambda r: r['observed_at'])
latest_cohort = {}
for r in runs_sorted:
    latest_cohort[r.get('kind') or r['source']] = r
all_runs = [{'run_id': r['run_id'], 'source': r['source'], 'kind': r.get('kind') or r['source'],
             'mode': r.get('mode'), 'observed_at': r['observed_at'], 'site_count': r.get('site_count'),
             'deep_scanned': r.get('deep_scanned')} for r in runs_sorted]

# ---- history series (health full runs only, per cohort) --------------------
full_ids = {r['run_id']: r['observed_at'] for r in RUNS if r['source'] == 'health' and r.get('mode') == 'full' and (r.get('site_count') or 0) > 3}
hist = collections.defaultdict(lambda: {'plugins': [], 'wp': [], 'backup': [], 'core': []})
for o in sorted(OBS, key=lambda o: o['observed_at']):
    if o['source'] != 'health' or o['run_id'] not in full_ids:
        continue
    h = hist[o['site_id']]
    d = o['observed_at'][:10]
    if isinstance(o.get('plugin_updates'), int): h['plugins'].append([d, o['plugin_updates']])
    if o.get('wp_version') not in (None, 'unknown'): h['wp'].append([d, o['wp_version']])
    if isinstance(o.get('db_backup_age_days'), int): h['backup'].append([d, o['db_backup_age_days']])
    if o.get('wp_core_update') not in (None, 'unknown'): h['core'].append([d, o['wp_core_update']])

# ---- attestation evidence from the component inventory ---------------------
# Rule: an attestation is "checkable" only when it names a plugin family the
# inventory can see. "Yes - Pantheon" / "Yes - CF WAF" are platform controls the
# inventory cannot confirm or deny, so they are reported as "not checkable here".
ATT_SLUGS = {
    'hide_login': {'wps-hide-login'},
    'wp_2fa': {'wp-2fa', 'wp-defender', 'wordfence', 'two-factor'},
    'activity_log': {'wp-security-audit-log'},
    'xmlrpc_disabled': {'disable-xml-rpc', 'disable-xml-rpc-api', 'disable-xmlrpc'},
}
ATT_LABEL = {'hide_login': 'Login URL hidden', 'wp_2fa': '2FA', 'activity_log': 'Activity log',
             'xmlrpc_disabled': 'XML-RPC disabled', 'single_cm_user': 'Single CM user',
             'keeper_password': 'Password in Keeper', 'wp2shell_remedied': 'wp2shell remedied'}
cat = M['components']['catalogue']
inventoried = set(M['components']['sites_inventoried'])
active = collections.defaultdict(set)
for c in cat:
    for i in c['installs']:
        if i['status'] == 'active':
            active[i['site_id']].add(c['slug'].lower())

def att_for(site_id):
    out = []
    for k, v in (INV.get(site_id, {}).get('attestations') or {}).items():
        val = v.get('value')
        ev = 'n/a'
        if k in ATT_SLUGS:
            if isinstance(val, str) and ('Pantheon' in val or 'WAF' in val):
                ev = 'platform'          # not a plugin; inventory cannot check it
            elif site_id not in inventoried:
                ev = 'not-inventoried'
            else:
                seen = bool(active[site_id] & ATT_SLUGS[k])
                yes = isinstance(val, str) and val.startswith('Yes')
                # claim Yes + plugin -> evidence; claim Yes + none -> no-evidence;
                # claim No/blank + plugin -> unclaimed-evidence; claim No/blank + none -> consistent-no
                ev = 'evidence' if (yes and seen) else 'no-evidence' if yes else 'unclaimed-evidence' if seen else 'consistent-no'
        out.append({'key': k, 'label': ATT_LABEL.get(k, k), 'value': val, 'evidence': ev,
                    'source': v.get('source'), 'by': v.get('by'), 'at': v.get('at')})
    return out

# ---- sites -----------------------------------------------------------------
FACTS = ['plan', 'framework', 'env', 'php_version', 'wp_version', 'wp_core_update', 'wp_checked',
         'plugin_updates', 'theme_updates', 'upstream_pending', 'db_backup_age_days', 'frozen',
         'components_checked', 'smtp_plugin_seen', 'smtp_from_domain', 'smtp_relay_host', 'smtp_transport',
         'nexcess_app', 'nexcess_app_version', 'nexcess_env', 'nexcess_php_version', 'nexcess_site_id',
         'nexcess_state', 'nexcess_package', 'nexcess_temp_domain',
         'spf_present', 'spf_all_qualifier', 'spf_checked_at', 'dkim_present', 'dkim_selector',
         'dmarc_at_from_present', 'dmarc_at_from_policy', 'dmarc_at_sending_present', 'dmarc_at_sending_policy',
         'dmarc_via_org_fallback', 'relaxed_aligned', 'recorded_from_domain',
         'consent_scan_ok', 'consent_http_status', 'consent_banner_vendor', 'consent_banner_detected',
         'consent_pre_trackers', 'consent_pre_tracker_names', 'consent_mode_denied', 'consent_final_url']
sites = []
for s in M['sites']:
    sev = s['severity']
    inv = INV.get(s['site_id'], {})
    pending = []   # which components are pending on this site, from the catalogue
    for c in cat:
        for i in c['installs']:
            if i['site_id'] == s['site_id'] and i['update_available']:
                pending.append([c['slug'], c['type'], i['version'], i['update_version']])
    sites.append({
        'id': s['site_id'],
        'host': s['host'],
        'hsn': s.get('host_site_name'),
        'production': s['production'],
        'counts': bool(sev.get('production', True)),
        'in_workbook': s['in_workbook'],
        'in_inventory': s.get('in_inventory', True),
        'reconciliation': s.get('reconciliation'),
        'notes': s.get('notes'),
        'sources': s['sources'],
        'health': sev['axes'].get('health', {'status': sev['status'], 'reasons': sev['reasons']}),
        'consent': sev['axes'].get('consent', {'status': 'UNKNOWN', 'reasons': []}),
        'info': sev.get('info', []),
        'f': {k: s.get(k, None) for k in FACTS},   # None = the source never wrote this site
        'claimed': s.get('claimed'),
        'att': att_for(s['site_id']),
        'dns': inv.get('dns'),
        'email_provider': (inv.get('email') or {}).get('provider'),
        'decommission_candidate': bool(inv.get('decommission_candidate')),
        'pending': sorted(pending),
        'hist': hist.get(s['site_id'], {'plugins': [], 'wp': [], 'backup': [], 'core': []}),
    })

# ---- components: compact catalogue -----------------------------------------
comps = []
for c in cat:
    tv = collections.Counter(i['update_version'] for i in c['installs'] if i['update_available'])
    comps.append({
        'slug': c['slug'], 'type': c['type'], 'variants': c.get('variants', []),
        'sites': c['sites'], 'installs_count': c['installs_count'], 'versions': c['versions'],
        'pending': c['pending'], 'inactive': c['inactive'],
        'target': [v for v, n in tv.most_common()],
        'installs': [[i['site_id'], i['version'], i['status'] == 'active', bool(i['update_available']), i['update_version']]
                     for i in c['installs']],
    })

out = {
    'generated': TODAY,
    'inventory_count': M['inventory_count'],
    'counts': M['health']['counts'], 'axes': M['health']['axes'], 'excluded': M['health']['excluded'],
    'excluded_sites': M['health']['excluded_sites'], 'unreviewed': M['health']['unreviewed'],
    'no_health_evidence': X['no_health_evidence'],
    'severity_rules': X['severity_rules'],
    'latest': {k: {'run_id': r['run_id'], 'observed_at': r['observed_at'], 'mode': r.get('mode'),
                   'site_count': r.get('site_count'), 'deep_scanned': r.get('deep_scanned'),
                   'method': r.get('method')} for k, r in latest_cohort.items()},
    'all_runs': all_runs,
    'coverage': X['coverage'],
    'coverage_changes': M['coverage_changes'],
    'coverage_regressions': M['coverage_regressions'],
    'changes': M['changes'],
    'standing': M['standing'],
    'standing_was': M['standing_was'],
    'unreconciled': [{'id': u['site_id'], 'host': u.get('host'), 'why': u.get('reconciliation') or u.get('notes') or ''} for u in M['unreconciled']],
    'sites': sites,
    'components': {'catalogue': comps, 'rows': M['components']['rows'],
                   'sites_inventoried': M['components']['sites_inventoried'],
                   'sites_missing': M['components']['sites_missing'],
                   'expected': M['components']['expected'],
                   'pending_total': M['components']['pending_total']},
}
json.dump(out, open('/tmp/fleet/concept-data.json', 'w'), separators=(',', ':'))
import os
print('sites', len(sites), 'bytes', os.path.getsize('/tmp/fleet/concept-data.json'))
