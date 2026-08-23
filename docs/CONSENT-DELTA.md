# Cookie consent: manual process vs the sweep

**Written 2026-08-20.** Inputs: Nick Federico's Teams thread with Doug
(2026-08-17 09:13 ET through 2026-08-20 12:34 ET), `onetrust-audit.xlsx`
(SharePoint, last modified 2026-08-11), `OneTrust Implementation
Documentation.docx` (2026-07-13), and the latest consent run in the ledger,
`consent-2026-08-20_1457` (54 of 78 loaded). Every count below was measured
this session from those files.

**No code was changed.** This is findings and proposed next steps.

---

## 1. What the manual process is

Two artifacts and one monthly routine.

**`onetrust-audit.xlsx`** is a configuration record for the 15 sites whose
OneTrust lives in clevermethod's tenant. Nick: *"the scan results are just in
the onetrust platform, this spreadsheet is more of a 'current state' of each
site, so we know how they're configured."* It is updated by hand as work is
done (*"definitely requires some discipline"*). Sheets:

| sheet | what it holds |
|---|---|
| Sites (15) | per site: geolocation rule, all cookies categorized, default consent script, 3rd-party scripts managed in GTM, scripts fire w/ respect to consent, privacy policy detected, cookie policy detected, dated change notes |
| Geolocation Rules (10) | per client org: consent model (opt-in / opt-out), GCM and Microsoft consent mode mapping, banner behaviours, status Active/Draft |
| Templates (10) | banner template, publish status, opt-out-signal (GPC) handling |
| Cookies (410) | OneTrust tenant-wide cookie export: 388 from scan, 22 manual; **9 still `Unknown`** |
| Domain Level Cookies | per-domain cookie export with first/third party, category, hostname |

**The implementation doc** is the onboarding runbook: determine the model
with the client, configure the OneTrust org, put the `gtag('consent','default')`
snippet above GTM (denied for opt-in, granted for opt-out), import the
OneTrust GTM workspace, and re-trigger every non-Google tag on the
`cEvent - OneTrust - <Category> Cookies Updated` event. Post-launch rules:
every new GTM tag gets its consent configured, and **monthly** someone reads
the OneTrust scan report (emailed to [removed]@ and systems@) and
categorizes any new `Unknown` cookies.

**Nick's nuances from the thread**, in order:

- OneTrust scans run monthly per site, but a person still has to look for
  new or uncategorized cookies.
- OneTrust scanning is effectively included; the per-domain cost is for
  publishing the banner. Nick scans before the domain licence is bought.
- Cookie scans do not take the consent model into account. Whether a script
  respects consent depends on how the person configured its GTM trigger.
- On an opt-out site trackers fire before any click by design; on an opt-in
  site they should not. The model is needed to judge a pre-consent hit.
- Sites without a banner yet take longer because every third-party script has
  to be found and moved into GTM with a consent trigger.
- `animatics.com`: OneTrust present, GA4 and DoubleClick fire before consent,
  but *"we dont control that sites OneTrust, its not in our tenant."*

---

## 2. What the sweep measures today

Homepage only, US locale, headless Chromium, 9-second settle, no banner
interaction. Per site: did the page load (2xx), CMP vendor (7 named vendors
or a generic banner heuristic), whether any banner is visible, which of 9
tracker patterns fired before consent, whether GA hits carried a
consent-mode-denied `gcs`, HTTP status, final URL. Severity: WARN for
pre-consent trackers, WARN for no tooling, nothing for a page that would not
load. It never says compliant or non-compliant.

---

## 3. The delta

### 3a. Coverage: the sites Nick manages are mostly the ones we cannot see

Of Nick's 15 sites, the latest sweep loaded **6**, got **HTTP 403 on 6**,
and **3 are not in the inventory at all**.

| site | sweep result | Nick's sheet |
|---|---|---|
| ciminelli.com | OneTrust, 0 pre-consent, consent-mode denied | all Yes |
| cottrillspharmacy.com | OneTrust, 0, denied | all Yes |
| icegame.com | OneTrust, 0, denied | scripts-respect-consent **No**; Klaviyo TODO |
| newmarkciminelli.com | OneTrust, 0, denied | all Yes |
| runtalnorthamerica.com | OneTrust, 0, **no GA ping seen at all** | all Yes |
| zehnder-rittling.com | OneTrust, 0, denied | all Yes |
| actioncarting.com | **403** | scripts-respect-consent **No** (cookie-script.js TODO) |
| choosechq.com | **403** | all Yes |
| gmroot.com | **403** | all Yes, but rule and template are **Draft** |
| interstatewaste.com | **403** | all Yes |
| lifebreath.com | **403** | all Yes |
| zehnderamerica.com | **403** | all Yes |
| buffalowebsitedevelopment.com | **not in inventory** | clevermethod's own site |
| homearcadegames.com | **not in inventory** | "We do not manage this site"; Shopify cookies |
| mightytaco.com | **not in inventory** | Shopify store cookies |

All six 403s are CM Pantheon. **CORRECTED 2026-08-22: the blocker is not
Pantheon.** All 20 blocked CM Pantheon sites answer from `server: cloudflare`
with `cf-mitigated: challenge`; none reaches Pantheon at all, so the allowlist
request that was queued would have achieved nothing and has been withdrawn.
These are per-zone Cloudflare bot settings across at least four different DNS
providers, so there is no single owner to ask. Until that is unpicked per
client, the sweep verifies 6 of Nick's 15.

The two sites Nick's sheet marks as known-defective (`actioncarting.com`,
`icegame.com`) are the two most useful tests of whether the sweep catches what
a person already knows. One is blocked; on the other the sweep saw nothing
fire, which is consistent with the Klaviyo question being a cookie-handling
question rather than a pre-consent firing. Not a contradiction, but not a
confirmation either.

### 3b. Tenant: 11 of the sweep's 17 OneTrust sites are not in our tenant

The sweep detects OneTrust on 17 loaded sites. Only 6 are in Nick's sheet.
The other 11 are `animatics.com` and the Lactalis family
(`breakstones.com`, `crackerbarrelcheese.com`, `knudsen.com`,
`kraftnaturalcheese.com`, `lactalisamericangroup.com`,
`lactalisheritagedairy.com`, `lactalisyogurtusa.com`, `midwestyogurt.com`,
`scottishcheddarcheese.com`, `valbresocheese.com`). The dashboard shows
"OneTrust" for all 17 identically. A finding on a CM-tenant site goes to Nick
to fix; a finding on a client-tenant site goes to the account lead to raise
with the client. **The page cannot route that today because nothing records
whose tenant the CMP is in.** `animatics.com` is already the live example:
Doug flagged it, Nick cannot act on it.

### 3c. Model: the WARN rule does not know opt-in from opt-out

`consent_pre_consent_trackers` fires on any pre-consent hit. Nick's sheet
says Interstate Waste (`actioncarting.com`, `interstatewaste.com`) is **opt-in
for California only, opt-out everywhere else**, with a default consent script
of `granted` outside CA. From a New York or GitHub IP those sites *should*
fire trackers before any click. Both are 403 today, so the rule has not
misfired yet; the moment the scanner can load those pages it will WARN on two
sites that are configured exactly as intended. `animatics.com` may be the same
case; Nick raised the model as the open question and it was not settled.

Two sources can supply the model. Nick's sheet gives the *claimed* model per
site (a claim, like the workbook). The wire gives an *observed* default: the
`gcs` parameter on GA hits is `G100` for a denied default and `G111` for
granted, and the scanner already parses it for the denied case only. A claim
and an observation under separate fact names, with disagreement visible, is the
pattern this project already uses for PHP versions.

### 3d. Tracker list: the OneTrust export names vendors the sweep does not watch

The 9 patterns are GA4, DoubleClick, Meta, Clarity, Hotjar, LinkedIn, Bing,
TikTok, Pinterest. Nick's notes and the domain-level cookie export name
StackAdapt, Klaviyo, OptiMonk, ZoomInfo, The Trade Desk, Apollo, Elevar, and
Sourcebuster (WooCommerce Order Attribution). None are watched. The export's
96 third-party targeting cookies with hostnames are a ready-made list to
extend the patterns from, at no credential cost.

### 3e. Columns the sweep could answer and does not

| sheet column | sweep today | feasible read-only? |
|---|---|---|
| Default consent script present, and its values | no | yes: read `window.dataLayer` for the `consent default` entry, or infer from `gcs` |
| Privacy policy detected | no | yes: link scan on the loaded homepage |
| Cookie policy detected | no | yes: same |
| Scripts fire w/ respect to consent | pre-consent half only, 9 patterns, homepage | partly: same observation after a reject click is the other half; the sweep currently never interacts |
| Opt-out signal honoured (Templates sheet) | no | yes: send `Sec-GPC: 1` and compare |
| Geolocation rule / consent model | no | claim only, from Nick's sheet or the OneTrust admin |
| All cookies categorized / Unknown count | no | OneTrust admin data. Needs API or export, see 3f |
| 3rd-party scripts managed in GTM | no | hard from the wire; the script-initiator chain is the only signal |

### 3f. The monthly human step is the one the sweep does not touch

Nick's recurring effort is reading the OneTrust scan report for new or
`Unknown` cookies. The tenant export shows 9 `Unknown` today. The sweep
observes requests, not cookies, and does not read the OneTrust admin. This is
the part of the manual process that stays manual unless the OneTrust tenant
data comes in as its own source (claims, under its own fact names, like the
Nexcess rule says).

### 3g. Onboarding is the use Nick expects

Nick: *"I'd assume we'd only be scanning cookies to eventually implement a
cookie banner."* The sweep's 34 no-tooling sites, with their pre-consent
tracker lists, are the first step of his onboarding runbook (find every
third-party script before moving it into GTM). That output exists today in
`reports/` and is not surfaced as a work list.

---

## 4. Things in the doc that need Nick

1. **`gmroot.com`**: the Sites row reads all Yes, but `G.M. Root Geolocation
   Rule` and `G.M. Root Template` are both **Draft**. Is the banner live on
   the site? The sweep cannot check (403).
2. **`homearcadegames.com`**: default consent script is all `granted`
   (opt-out shape) while the ICE rule it is assigned to switched to **opt-in
   on 2026-06-22**. Notes say "We do not manage this site." Is it in scope at
   all, and is the row current?
3. **`icegame.com` and `mightytaco.com`**: "Default consent script not found
   … controlled in the OneTrust CMP tag in GTM." Is that the accepted pattern
   or an open item? The cell is blank rather than Yes/No.
4. **`actioncarting.com`**: scripts-respect-consent is **No** with a TODO on
   `cookie-script.js` setting `landing_page`/UTM cookies into Gravity Forms.
   Undated. Open or resolved?
5. **Cookie export vs notes**: notes say `_leadgenie_session` was categorized
   as targeting (2026-06-18) and `login_with_shop_finalize` as strictly
   necessary, but the Cookies export still lists both as `Unknown` and
   `Domain Category Overrides` is 0 on all 410 rows. Is the export stale (file
   dated 2026-08-11), or do overrides not export?
6. **"Privacy Policy Detected" / "Cookie Policy Detected"**: detected by
   whom, OneTrust's scan or a person? `icegame.com` and
   `homearcadegames.com` read No for cookie policy; is that a TODO?
7. **`runtalnorthamerica.com`**: the sweep saw no GA request at all in 9
   seconds, where the other five CM-tenant sites showed consent-mode-denied
   pings. Notes mention `send_page_view` disabled for the WooCommerce GA
   extension. Expected?
8. **`animatics.com`**: is that site opt-in or opt-out? Unresolved in the
   thread. If opt-in, Matt has something to tell the client; if opt-out, the
   sweep's WARN is wrong by design (3c).
9. **OneTrust API**: does the tenant plan include API access (Cookie Consent
   API: scan results, cookie categories, domain list)? That decides whether
   3f is automatable or stays a monthly export.
10. **Scope of the three non-inventory sites**: `buffalowebsitedevelopment.com`
    is clevermethod's own; the other two have Shopify cookies and may not be
    WordPress. Do they belong in the 84-site inventory, or in a separate
    "CMP-managed" list that the inventory references?
11. **Post-consent behaviour**: does anyone today verify that tags fire after
    *accept* and stay silent after *reject*? The sheet's "Scripts Fire w/
    Respect to Consent" column implies both halves; the doc describes
    configuring it, not testing it.

---

## 5. Proposed next steps, in order

Nothing here is built. Each is sized against what it buys.

1. ~~**Send the Pantheon allowlist request**~~ **WITHDRAWN 2026-08-22 — wrong
   vendor.** The 403s are a Cloudflare bot challenge on the clients' own
   zones, measured from response headers; the request never reached Pantheon.
   The identifying-User-Agent idea is withdrawn with it and inverted: against
   Cloudflare Bot Management a non-browser UA scores worse, not better. What
   would work is a WAF skip rule on a custom header or source IP, agreed per
   zone with whoever administers it. Establishing who that is, for each of the
   20, is the actual first step. See `docs/SESSION-HANDOFF.md`, "The 403s".
2. **Put Nick's 15 rows into the inventory as claims**: `cmp_tenant`
   (clevermethod / client / none), `consent_model_claimed`, geolocation rule,
   with `source: onetrust-audit.xlsx 2026-08-11`. Decide 4.10 first. This is
   the roster reconciliation step CLAUDE.md requires and it answers 3b.
3. **Make the pre-consent rule model-aware** before step 1 lands: no WARN on
   a site whose claimed or observed default is granted; a separate, lower
   finding for "opt-out site, trackers fire, GPC not yet tested." Test first,
   verified failing, per the definition of done.
4. **Record the observed default consent state** as a fact from `gcs` (and
   the dataLayer where present). Claim vs observation disagreement becomes a
   standing finding, same shape as `php_version` vs the workbook.
5. **Extend the tracker patterns** from the OneTrust domain-level export
   (StackAdapt, Klaviyo, OptiMonk, ZoomInfo, Trade Desk, Apollo). Cheap, no
   credentials, and it is the difference between "0 fired" and "0 of the 9
   we watch fired."
6. **Add privacy/cookie policy link detection.** Two sheet columns, one
   DOM query.
7. **Surface the onboarding work list**: no-tooling sites with their
   third-party script list, grouped by client. Matches Nick's stated use
   (3g) and costs a renderer section.
8. **OneTrust tenant data as a source**, gated on 4.9: unknown-cookie count
   and scan date per site. This is what retires the monthly manual step, and
   it is the natural first Asana routing case ("new Unknown cookie on site X"
   to Nick).
9. **Reject-path check and GPC check** last. They need the scanner to
   interact with the banner, which is a per-vendor selector problem, and
   they are the only way to answer the second half of "scripts fire with
   respect to consent."

Steps 2 through 6 are small and credential-free. Step 8 depends on Nick's
answer about API access. Step 9 is the only one that changes what the
scanner does on a page.
