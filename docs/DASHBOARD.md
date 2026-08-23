# Fleet dashboard: live demo, then hosting

**Updated 2026-08-20.** The publish path and the Access section were rewritten
from what is actually configured, checked in the Cloudflare dashboard that day.
Before 2026-08-20 this document still described a `PUBLISH_TOKEN` HTTP publish
route that had been deleted on 2026-08-19.

There are **two renderers, deliberately**, and confusing them is how this
document was wrong for a month:

| renderer | input | used for |
|---|---|---|
| `render-fleet-dashboard.py` (v1) | one scan JSON | the **live local view** that fills in site by site while a scan runs |
| `render-dashboard.py` (v2) | the **ledger** in `history/` | the **published** dashboard: all 84 sites, both tools, change detection |

Until 2026-08-19 `publish-dashboard.sh` called **v1**, so running it would have
published a single-run snapshot -- 52 sites instead of 84, no change detection,
no email/DNS data -- to a hostname people were about to be sent to. It now
renders from the ledger.

**Do not delete `render-fleet-dashboard.py`.** `serve-dashboard.py` imports it,
and the live view is the thing that makes a scan watchable on a screen share.
See `docs/DASHBOARD-V2.md` for why the two were never merged.

---

## Showing people a scan live (start here)

Two terminals on the machine that can reach Pantheon, which today means your Mac.

```bash
# terminal 1 - the dashboard, watching for results
./scripts/serve-dashboard.py --dir ./reports --open

# terminal 2 - the scan
export PANTHEON_MACHINE_TOKEN=...
./scripts/pantheon-fleet-healthcheck.sh --api-only --no-fail-on-crit
```

The page fills in site by site as the scan walks the fleet. The header reads
`SCAN RUNNING - 23 sites so far` with a pulsing dot, the composition bar and
tiles re-render on every update, and when the run ends it flips to a normal
timestamped read.

This works because the scan scripts rewrite their JSON after **every site**, not
just at the end. That behavior was originally added so a killed run would not
lose its results; it also happens to make a run watchable.

**How "finished" is detected.** The scripts write the `.json` continuously but
the `.md` digest exactly once, at the end. A `.md` sitting beside the `.json`
with the same stamp is an exact completion signal, so the page stops saying
SCAN RUNNING the moment the run ends rather than after some timeout guess.
A staleness window is only the fallback for when no digest exists.

Nothing else is required. No Cloudflare, no Access policy, no CI, no deploy,
no secrets beyond the machine token you already have. It binds to `127.0.0.1`,
so it is your machine only, which is what you want on a screen share.

If you would rather the devs load it on their own machines over the office
network, `--host 0.0.0.0` does that, but only do it on a trusted network. The
hosted path below is the better answer for anything beyond a live demo.

---

## The pieces

| File | Job |
|---|---|
| `scripts/render-dashboard.py` | **the ledger in, page + JSON feed out. This is what gets published** |
| `scripts/lib/severity.py` | decides CRIT/WARN/OK. The only place that does. See `docs/SEVERITY.md` |
| `scripts/render-fleet-dashboard.py` | one scan JSON in, HTML out. Feeds the LIVE view only |
| `scripts/serve-dashboard.py` | watches a reports dir, re-renders on change, serves it. Stdlib only |
| `scripts/publish-dashboard.sh` | render from the ledger, then upload both artifacts straight to R2 with `wrangler r2 object put` |
| `ci/cloudflare/cm-fleet-worker.js` | serves the page and the feed out of R2. No business logic |

```bash
# the published page, locally
./scripts/render-dashboard.py --out fleet.html
open fleet.html

# exactly what CI publishes, without publishing it
./scripts/publish-dashboard.sh --dry-run
```

`--dry-run` writes both artifacts under `reports/publish-preview/` and stops.
**Use it.** Six of the ten bugs this project has found were caught by a person
reading a rendered page, not by a passing test.

### The two artifacts come from one render

`--emit-data` writes the JSON feed from the **same model object** that produced
the HTML. The v1 pair was built by two code paths, which is how a live JSON
endpoint ends up disagreeing with the page beside it. `test/test-severity.py`
asserts every count in the feed appears in the rendered HTML, so drift fails a
test rather than waiting for someone to open both.

### What `/api/fleet-scan` returns now

`{"schema": "fleet-dashboard/2", ...}` -- **not** the v1 `{stamp, kind, rows}`
shape. The version is there so a consumer written against v1 breaks loudly
instead of quietly reading fields that no longer mean what they meant.

It carries, per site: the re-derived `status`, `counts_toward_fleet`, the
`reasons` behind that status with machine-readable codes, the observed facts,
and the workbook's claims kept separate from them. Plus the fleet `health`
counts, the review queue, standing findings, changes, and
**`severity_rules`** -- the thresholds the run was scored with, so a consumer
can tell a fleet change from a rules change.

---

## Standing it up on Cloudflare

Existing account resources this reuses: the `dash-data` R2 bucket. It does not
touch `[removed]` or the `[removed]` Worker.

**1. Create the Worker.**

```bash
cd ci/cloudflare
wrangler deploy
```

`ci/cloudflare/wrangler.toml` carries the name (`cm-fleet`), the entry point and
the R2 binding, so this one command covers what used to be steps 1 and 2. It was
added 2026-08-19: this document had said "use wrangler, not hand-pasting" since
it was written, while no wrangler config existed, so the instruction could not
be followed.

This account has two deploy habits and this Worker follows the better one:
`[removed]`'s Worker is pasted into the Cloudflare dashboard by hand, `[removed]`
deploys with wrangler. Hand-pasting means the deployed version can silently
drift from the version in git, which has already bitten this account once.

`main` resolves relative to the toml, which is why the command has a `cd` in it.

**2. R2 is already bound** by the config above: binding `FLEET`, bucket
`dash-data` (verified to exist 2026-08-19, re-checked 2026-08-20). The Worker
only READS, and only under the `fleet/` prefix, so it cannot collide with what
`[removed]` keeps in the same bucket.

**3. Route a hostname.** `fleet.thudstaff.com`. Do not serve this from
`[removed]`.

This is already in `ci/cloudflare/wrangler.toml` as a `[[routes]]` block with
`custom_domain = true`, so `wrangler deploy` attaches it. The hostname lives in
git for the same drift reason as the Worker itself.

**There is no publish secret and no publish route.** Both were removed
2026-08-19. If you find yourself running `wrangler secret put PUBLISH_TOKEN`,
you are following an old version of this document. See "Why the write route
went" below.

**4. Turn off the `workers.dev` URL, and prove it.** `wrangler.toml` sets
`workers_dev = false`. Cloudflare Access protects hostnames in a zone; it
**cannot** protect a `*.workers.dev` URL, so a Worker behind Access on its
custom domain is still served unauthenticated on `cm-fleet.<subdomain>.workers.dev`
to anyone who has the URL. This was demonstrated, not assumed: an external
sandbox with no Cloudflare session fetched the full fleet JSON from the
workers.dev URL while `fleet.thudstaff.com` correctly returned a 302 to the
Access login.

Verify in the dashboard after deploying: Workers & Pages -> cm-fleet ->
Domains. Both the Production and Preview `workers.dev` toggles must be off.
**Checked 2026-08-20: off on all five Workers on this account.**

**5. Put it behind Access.** See the next section for what is actually
configured today.

**6. Publish.** It takes **no scan file** -- it renders from the ledger, and it
writes to R2 directly rather than through the Worker.

```bash
# look at it first
./scripts/publish-dashboard.sh --dry-run
open reports/publish-preview/dashboard.html

# then for real
export CLOUDFLARE_API_TOKEN=<a token with Workers R2 Storage: Edit>
export CLOUDFLARE_ACCOUNT_ID=<see: wrangler whoami>
./scripts/publish-dashboard.sh
```

**7. Let CI do it.** Publishing is the reusable workflow
`.github/workflows/_publish-dashboard.yml`, called by the email, Nexcess and
consent workflows with `secrets: inherit`. The Pantheon workflow still has its
own inline copy. It needs two repo settings:

| where | name | value |
|---|---|---|
| Settings, Secrets and variables, Actions, **Secrets** | `CLOUDFLARE_API_TOKEN` | a token with Workers R2 Storage: Edit, scoped to ONE account |
| Settings, Secrets and variables, Actions, **Variables** | `CLOUDFLARE_ACCOUNT_ID` | the account id |
| Settings, Secrets and variables, Actions, **Variables** | `FLEET_PUBLISH_URL` | `https://fleet.thudstaff.com` (display only, in the run summary) |

Note which is a secret and which is a variable. The workflow's "Check publish
credentials" step fails loudly if either is missing, rather than letting the
script die on an unbound variable ten lines later.

The publish job runs **after** `persist-ledger` and checks out `main` fresh.
Both matter: publishing first would ship a page rendered from a ledger that does
not yet hold the run that just finished, so the live dashboard would sit one
scan behind forever and nothing on the page would say so.

---

## Why the write route went

Until 2026-08-19 the Worker had a `PUT /api/publish/<key>` route guarded by a
`PUBLISH_TOKEN` bearer check, and `publish-dashboard.sh` uploaded through it.

That route sat on a hostname behind Cloudflare Access, so a machine publishing
had to clear Access with a service token **and** a correctly ordered Service
Auth policy, just to reach a bearer-token check it would then also have to pass.
Two auth layers, one of which a machine cannot satisfy without extra
configuration, guarding an operation the R2 API already authenticates on its
own.

Writing to the bucket directly with `wrangler r2 object put` removed the whole
problem, and left the Worker with **no write endpoint on a public hostname at
all**. Do not add one back without a reason that survives that sentence.

**2026-08-20: the deployed Worker had not caught up.** The repo change landed
after the last `wrangler deploy`, so production still had the `PUT` route and
still had `PUBLISH_TOKEN` set as a secret -- meaning the route answered rather
than returning 503. Nothing was exposed, because Access fronts the hostname and
`workers.dev` is off, but a write path existed that the docs and `CLAUDE.md`
both said did not. **After changing this Worker, re-read the deployed code
(`wrangler deployments view`, or the dashboard's Edit code view) and confirm it
is what you committed.**

---

## House style: the chrome is [removed]'s, the severity colours are not

**Adopted 2026-08-23** so the company's apps read as one product. Taken from
`[removed]/src/form.html`: the paper (`#efefea`), the purple-cast ink
(`#241e31`), the hairlines (`#d9d8d0`), the strong ink (`#1c122d`), the
Helvetica Neue type stack at 14px/1.5, the mono stack at 11.5px, uppercase
letterspaced 800-weight labels, and **square corners everywhere** — [removed]
declares `border-radius` exactly twice and both are `0`. The only round thing
left here is the state dot, because it is a dot.

**The severity colours are deliberately NOT [removed]'s.** `good`, `bad` and
`info` were validated for colourblind separation, and the obvious green-and-
amber pair was rejected at protan delta-E 3.8 — which is why WARN is blue.
[removed]'s `--good #0E7A55` and `--red #B4392F` have not been through that test,
and in [removed] colour is decorative while here it carries the finding. **Do not
unify these two sets by eye.** `test-ledger.py` asserts both halves: that the
chrome matches and that the severity hues are still ours.

**This page is light only.** There was a dark variant and it was removed the
same day: [removed] ships light only, so a dark mode here was the one place the
two apps could not look alike, and it was a second palette to keep in step
with a second set of contrast ratios to re-measure whenever a colour moved.
The page therefore does not consult `prefers-color-scheme` at all, and
`body{background}` is load-bearing rather than decorative — without it the
page inherits the host's ground and renders this ink on someone else's black.

`--strong` is [removed]'s `--navy`, renamed for its ROLE rather than its hue.

**Chips were the one place the two systems could not simply merge.** [removed]'s
`.pill` is solid navy with white text. Filling ours the same way puts white on
the validated green at 2.8:1. So the chip keeps its tint, takes [removed]'s
uppercase 800-weight typography and square corner, and the LABEL is mixed
toward `--ink` for contrast while the DOT keeps the exact validated hue — a
swatch carries no text and has no ratio to meet. Measured after the change:
5.38 to 7.34.

---

## The component catalogue, `/components`

**Added 2026-08-23.** A second page listing every plugin, mu-plugin and theme
installed across the fleet, and which sites run each one. Rendered by the same
script and the same model as the fleet page, so the two cannot disagree:

```bash
./scripts/render-dashboard.py --out fleet.html --components-out components.html
```

**It is plugin-major, and that is the whole point.** A per-site view answers
"what is pending here", which the fleet table's count already answers. The
question a count cannot answer is "which of our sites run this component, at
what versions" -- the one that mattered when Pods CVE-2026-19598 was disclosed
on 2026-08-15 with no patch for about 36 hours. The fleet table's plugin count
links to `/components?site=<domain>`, so the per-site view is still one click
away.

**Linked only where an inventory exists.** A site can carry a plugin count from
a run made before component capture was switched on; a link from that count
would land on a page with nothing to show. Those cells stay plain text. 47 of
84 rows are linked today.

**THE WORKER NEEDS DEPLOYING FOR THE ROUTE TO EXIST.** `/components` was added
to `ci/cloudflare/cm-fleet-worker.js` in the same change, and editing that file
changes nothing until someone runs `wrangler deploy` from `ci/cloudflare`.
Until that happens the link on the live fleet page 404s. Claude cannot deploy.
Read the deployed code back afterwards rather than trusting the source file --
on 2026-08-20 an audit found the deployed Worker a full day behind the repo.

`publish-dashboard.sh` uploads `components.html` in the SAME loop as
`dashboard.html`, deliberately: publishing one without the other leaves the
link dead for however long they are out of step.

---

## Access: what is configured

**This section is the record.** It used to live in project memory as
`fleet_cloudflare_access.md`; that file does not exist and probably never did.
See `CLAUDE.md` for why measured state belongs here instead.

### Re-measured 2026-08-23, from outside, with no Cloudflare session

| what | how it was checked | result |
|---|---|---|
| Every hostname is gated | unauthenticated `curl -I` to each of the five | all 302 to `doug-kasperek.cloudflareaccess.com` |
| They are separate applications | the `kid` in each redirect | five distinct app keys, one per hostname |
| No `workers.dev` back door | `GET /accounts/{id}/workers/scripts/{name}/subdomain` | `enabled: false` on all five, `previews_enabled: false` too |

A visitor authorised for one hostname is therefore **not** authorised for the
others: Access issues an identity session, and each application re-evaluates its
own policy against that identity. With `workers.dev` off everywhere there is no
unauthenticated path to Worker content that skips Access.

### The Access API will lie to you about this

`GET /accounts/{id}/access/apps` with the wrangler OAuth token returns
**`success: true` and an empty list**. There are five applications; the live 302s
above prove it. The token simply carries no Zero Trust scope, and the API
answers with an absence rather than a 403.

This is the project's signature bug wearing a new hat -- a confident-looking
value standing in for "nobody could look". Anything that reads Access config
programmatically must distinguish "zero applications" from "not permitted to
enumerate applications", and the only honest way to check gating from a token
without Zero Trust scope is to request the hostname and look for the redirect.

### What is NOT machine-verified here

**Policy membership.** Who is on `fleet viewers` versus `[removed]` cannot be read
without a token carrying Zero Trust scope, so the lists below are the
2026-08-20 dashboard reading, re-confirmed by Doug in the dashboard on
2026-08-23 but never measured by code. Treat them as a written claim.

The risk that membership guards against: if any application's include rule is a
**domain-wide** selector (`Emails ending in @clevermethod.com`, or the
`all-cm-emails` reusable policy below) rather than a named list, then anyone
added to the fleet page also clears whichever applications share that rule.
Adding a viewer and widening access to the deck would be the same action, in
different screens.

**To add several viewers at once**, build a list rather than editing the policy:
Zero Trust -> Reusable components -> Lists -> Create manual list, type *User
email addresses*, CSV upload (one entry per line, 1,000 entries on Standard
plans, file under 2 MB), then reference it from the policy with the **in list**
operator. Keep any such list referenced by **one** policy; a list is only a set
of values, and all of its containment comes from what points at it.

### The 2026-08-20 dashboard reading

All five Workers on this account have a custom hostname, an Access application,
and `workers.dev` disabled.

| Worker | hostname | Access application | policy |
|---|---|---|---|
| cm-fleet | fleet.thudstaff.com | fleet | `fleet viewers` |
| [removed] | [removed] | dash | `[removed]` |
| [removed] | [removed] | cm | `[removed]` |
| [removed] | [removed] | cm SOWgen | `[removed]` |
| [removed] | [removed] | cmcom | `[removed]` |

- `fleet viewers` -- doug.kasperek, [removed], [removed],
  [removed], [removed].
- `[removed]` -- doug.kasperek, [removed], [removed]. This is the deck's
  policy, and it is correct that the fleet dashboard does **not** reuse it: the
  deck holds [removed], [removed] and the [removed], and the
  developers who need the fleet page must not be added to it.
- Every policy's action is `Allow`. **There are no Bypass policies and no Access
  service tokens**, which is what makes the header check in `[removed]` safe --
  see below.
- The R2 bucket `dash-data` has no custom domain and its Public Development URL
  is disabled, so R2 is not a way around Access either.

A reusable policy named `all-cm-emails` exists and is attached to zero
applications. If you want the fleet page visible to everyone at clevermethod,
that is the rule to attach; the page holds no client-confidential data, only
your own fleet's inventory.

**Why `workers.dev` staying off is load-bearing beyond this Worker.** `[removed]`
authenticates its `/api/save` endpoint solely on the
`Cf-Access-Authenticated-User-Email` header. That header is only trustworthy on
a hostname where Access is the *only* route in -- on a `workers.dev` URL a
client can simply send the header itself. `[removed]/wrangler.toml` does not pin
`workers_dev = false`, so a future `wrangler deploy` of it can re-open that
door.

**Do not create an Access service token for CI.** Nothing in this suite needs
one any more; the publish path talks to the R2 API and never touches the
hostname.

---
---

## Which Cloudflare account, and what it can do

**Measured 2026-08-23** with `GET /memberships` and `GET /zones` against the
wrangler OAuth login (`doug.kasperek@clevermethod.com`).

| account | id | roles held |
|---|---|---|
| Doug.kasperek@clevermethod.com's Account | `8ae22197…2e11` | Super Administrator -- All Privileges |
| clevermethod, Inc. | `856635b4…4d52` | Zone Versioning Read, Billing, **Administrator Read Only** |

Everything in this suite -- all five Workers, the `dash-data` bucket, the
`thudstaff.com` zone and every Access application -- is in the **first** account.

**Moving the dashboard to `fleet.clevermethod.net` is not a route change.**
`clevermethod.net` is a Cloudflare zone, but in the second account, and
Cloudflare will not attach a Worker to a zone its account does not own: *"You
cannot create a Custom Domain on a hostname with an existing CNAME DNS record or
on a zone you do not own."* The Worker has to be deployed **into** clevermethod,
Inc., which means a new R2 bucket, a new API token and new GitHub secrets.

**Two separate things block that, and fixing one does not fix the other:**

1. The wrangler token here is scoped to the first account only, so it cannot
   even *read* clevermethod, Inc. `GET /zones?name=clevermethod.net` returns
   `count: 0` -- again an absence, not a denial. Re-running `wrangler login` and
   ticking the second account at the consent screen clears this.
2. The role there is `Administrator Read Only` -- *"Can access the full account
   in read-only mode."* Every write in the migration fails regardless of token
   scope. It needs **Workers Platform Admin**, **Cloudflare R2 Admin** and
   **Cloudflare Zero Trust** granted by a Super Administrator on that account.

**Access policies do not transfer.** Applications and policies belong to a Zero
Trust organisation, which is per-account, so `fleet viewers` gets rebuilt
against whatever IdP clevermethod, Inc. uses. The login hostname changes with
it: today every one of the five applications sends users to
`doug-kasperek.cloudflareaccess.com`, which reads as a personal side project
rather than company infrastructure. Renaming the team domain is account-wide and
would move all five logins at once, so it is better done as part of the move
than twice.

`scripts/publish-dashboard.sh` already reads `FLEET_R2_BUCKET` (default
`dash-data`) and `FLEET_PUBLIC_URL` (default `https://fleet.thudstaff.com`), so
the repo side of the move is a default change plus documentation. The only
functional hardcoded hostname is the `[[routes]]` block in
`ci/cloudflare/wrangler.toml`.

---

## Design decisions worth not undoing

**The embedded snapshot always renders first.** The page never depends on the
network to show something. If `/api/fleet-scan` is slow, blocked by Access, or
missing, you still get the data that was baked in at render time, and the
freshness line says so rather than pretending. A dashboard that shows a spinner
when its data endpoint is down is worse than one that shows last week's numbers
clearly labelled as last week's.

**Known-bad rows are shown, flagged, not corrected.** The current scan has one
result we know is wrong, `galbanicheese`. It is displayed with a warning tint
and an explanation banner. Hiding it would mean a developer finds it first, and
then reasonably distrusts every other number on the page.

**"Not determined" is its own state, never folded into "no".** 19 of 54 sites
are in it. Collapsing unknown into negative is how a dashboard starts lying.

**The state colors are not the brand colors.** The deck's severity green
`#1a7f37` and amber `#9a6700` were tried first and failed colorblind separation
at protan delta-E 3.8, meaning a red-green colorblind reader cannot tell them
apart. The shipped colors are a validated categorical set, checked against both
this page's light and dark surfaces. Re-run the validator before changing them.

**Every color is backed by a label.** Legend, tile captions, and a full table
that carries the same information with no color at all.
