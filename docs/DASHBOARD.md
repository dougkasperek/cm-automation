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

Existing account resources this reuses: the `dash-data` R2 bucket. It creates
nothing else and touches no other Worker on the account.

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

This Worker deploys with wrangler, never by hand-pasting into the Cloudflare
dashboard. Hand-pasting means the deployed version can silently drift from the
version in git, which has already bitten this account once -- see "Why the
write route went" below, where production kept a route the repo had removed.

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
**Checked 2026-08-20: off, and re-checked on every push by
`./scripts/check-worker-exposure.py`.**

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
both said did not. **After changing this Worker, re-read the deployed code (the dashboard's Edit
code view, or the Cloudflare MCP `workers_get_worker_code`) and confirm it is
what you committed.** No wrangler command returns the deployed script body:
`wrangler deployments status` and `wrangler versions list` tell you which
version is live and when it went up, not what is in it. (`deployments view` was
this doc's instruction until 2026-08-31; wrangler 4 renamed it, and it never
returned the code.)

---

## House style: the chrome is shared, the severity colours are not

**Adopted 2026-08-23** so the company's apps read as one product. Taken from
the shared house style: the paper (`#efefea`), the purple-cast ink
(`#241e31`), the hairlines (`#d9d8d0`), the strong ink (`#1c122d`), the
Helvetica Neue type stack at 14px/1.5, the mono stack at 11.5px, uppercase
letterspaced 800-weight labels, and **square corners everywhere** — the source
declares `border-radius` exactly twice and both are `0`. The only round thing
left here is the state dot, because it is a dot.

**The severity colours are deliberately NOT from it.** `good`, `bad` and
`info` were validated for colourblind separation, and the obvious green-and-
amber pair was rejected at protan delta-E 3.8 — which is why WARN is blue. The
house `#0E7A55` green and `#B4392F` red have not been through that test, and
there colour is decorative while here it carries the finding. **Do not unify
these two sets by eye.** `test-ledger.py` asserts both halves: that the chrome
matches and that the severity hues are still ours.

**This page is light only.** There was a dark variant and it was removed the
same day: the house style ships light only, so a dark mode here was the one
place the apps could not look alike, and it was a second palette to keep in
step with a second set of contrast ratios to re-measure whenever a colour
moved. The page therefore does not consult `prefers-color-scheme` at all, and
`body{background}` is load-bearing rather than decorative — without it the
page inherits the host's ground and renders this ink on someone else's black.

`--strong` is the house style's structural dark, renamed for its ROLE rather
than its hue.

**Chips were the one place the two systems could not simply merge.** The house
`.pill` is solid navy with white text. Filling ours the same way puts white on
the validated green at 2.8:1. So the chip keeps its tint, takes the house
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

## Verifying a publish without going through Access

**Added 2026-08-24.** "Access blocks Claude, so the published page cannot be
checked" was half true and cost a session's worth of verification. Access
protects the *hostname*. The R2 object behind it can be read straight back:

```bash
wrangler r2 object get dash-data/fleet/dashboard.html --file ./live.html --remote
```

Note the key is `fleet/dashboard.html`, not `dashboard.html`. `R2_PREFIX` is
`fleet/` and the local file is named `dashboard.html`, so neither the repo
filename (`fleet.html`) nor the bare object name is the key.

Then diff it against what was rendered locally. On 2026-08-24 the published
object was byte-identical to the committed `fleet.html`, md5
`a11810c8a68b7a0bfdf848d605e610b7`, which is the strongest form of "what is
published is what you reviewed" available without a browser.

**What this proves and what it does not.** It proves the object in R2 is the
one that was rendered and reviewed. It does NOT prove what a browser receives
at `fleet.thudstaff.com`: the Worker sits between them, and this project has
already been bitten once by a deployed Worker differing from its source. So
this replaces "nobody checked the artifact" and not "nobody opened the page".
Someone with Access should still look at it.

## The wrangler OAuth token publishes to R2, despite what `whoami` lists

**Measured 2026-08-24.** `wrangler whoami` lists 29 scopes and **none of them
is R2**. Both `r2 object put` and `r2 object get --remote` nevertheless
succeed on the `dash-data` bucket. A publish was talked out of on that basis
before someone simply ran it.

So `whoami`'s scope list understates what an OAuth token can do, and **no
`CLOUDFLARE_API_TOKEN` is needed to publish from a logged-in laptop.** Run
`./scripts/publish-dashboard.sh` bare; the script reads the account ID out of
`wrangler whoami` itself. The env vars in its header are the CI path, for a
headless box with no login.

This is the mirror image of the Access-API row in `CLAUDE.md`'s bug table,
where an endpoint answered `success: true` with an empty list because the token
lacked a scope. There, a missing scope read as "nothing is there". Here, a
missing scope reads as "you cannot do this" and the operation works anyway.
**Neither direction can be inferred from a scope listing. Run the command.**

## Access: what is configured

`fleet.thudstaff.com` sits behind a Cloudflare Access application. Anonymous
requests get a 302 to an Access login; nothing reaches the Worker without
clearing it, and `workers_dev` is off so there is no second door.

`./scripts/check-worker-exposure.py` proves both halves on every push, without
credentials -- it is an outside-in check that sees exactly what an anonymous
visitor sees. **It answers AUTHENTICATION only.** Whether a person who has
signed in should be able to open this page is authorisation, decided by the
Access policy, and this repo does not read policies: that tooling and its
expectations file were removed on 2026-08-31 because the expectations named
individuals and applications outside this project's scope.

**What that means in practice.** If you need to know who can currently open
`fleet.thudstaff.com`, read the policy in the Cloudflare Zero Trust dashboard.
Do not infer it from anything in this repo.

Two properties worth carrying into any future change:

- **A policy can admit someone without naming them.** `email_domain`,
  `everyone` and `ip` rules all do. A list of individual emails sitting beside
  one reads as exclusive while granting the opposite, so "I read the member
  list" is not the same as "I know who can get in".
- **An unrecognised rule type is UNKNOWN, never DENIED.** A rule the tooling
  cannot parse is a rule it cannot clear anyone against.

---

## Which Cloudflare account, and what it can do

**Measured 2026-08-23** with `GET /memberships` and `GET /zones` against the
wrangler OAuth login (`doug.kasperek@clevermethod.com`).

| account | id | roles held |
|---|---|---|
| Doug.kasperek@clevermethod.com's Account | `8ae22197…2e11` | Super Administrator -- All Privileges |
| clevermethod, Inc. | `856635b4…4d52` | Zone Versioning Read, Billing, **Administrator Read Only** |

Everything in this suite -- the `cm-fleet` Worker, the `dash-data` bucket, the
`thudstaff.com` zone and the fleet Access application -- is in the **first**
account, which is personal. The account hosts unrelated Workers that are not
this project's concern; see `docs/HANDOVER.md`.

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
Trust organisation, which is per-account, so the fleet policy gets rebuilt
against whatever IdP clevermethod, Inc. uses. The login hostname changes with
it: today it sends users to `doug-kasperek.cloudflareaccess.com`, which reads as
a personal side project rather than company infrastructure. Renaming the team
domain is account-wide, so it is better done as part of the move than twice.

**And the strongest argument for moving is now evidenced rather than
asserted: access here is a hand-maintained list of email addresses, and it has
already drifted.**

Measured 2026-08-25, the first time anyone enumerated it. Someone held access
to an application and appeared in no document describing who could reach it.
Nothing was wrong with the grant, most likely. What was wrong is that nobody
could have told you it existed.

That is not a mistake somebody made. It is what a personal Cloudflare account
with per-application email lists produces over time:

- **No directory behind it.** Membership is typed in per application. There is
  no group to add someone to and no group to remove them from.
- **Offboarding is manual and invisible.** Nobody leaving the company is
  removed from these policies by any process that exists today. The only way
  to notice is to enumerate, which nothing did until this week.
- **The audit has no owner.** It is one person's account, so there is no
  security review that would ever look at it.

Detection was built for this and is worth having, but it is not the same as
access following the directory. On the company account with the company IdP,
the fleet policy becomes a group and membership is a consequence of employment
rather than of somebody remembering. **That is the strongest argument for
completing the Cloudflare move**, and it is the one to put to whoever has to
grant the permissions.

**So the move is not only about the hostname reading as a side project.** It is
about who is accountable for the answer to "who can open this", and today the
honest answer is that nobody was.

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
