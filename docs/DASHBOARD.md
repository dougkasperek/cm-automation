# Fleet dashboard: live demo, then hosting

**Updated 2026-08-19. What gets PUBLISHED changed; the live local demo did not.**

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
| `scripts/publish-dashboard.sh` | render from the ledger, then PUT both artifacts to the Worker |
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
`dash-data` (verified to exist 2026-08-19). The Worker reads and writes only
under the `fleet/` prefix, so it cannot collide with what `[removed]` keeps there.

**3. Add the publish secret.**

```bash
cd ci/cloudflare
wrangler secret put PUBLISH_TOKEN     # paste the output of: openssl rand -hex 32
```

It is a secret, so it is set this way and never written into `wrangler.toml`.
Without it the publish route returns 503 and the dashboard is upload-only.

**4. Route a hostname.** Suggested: `fleet.thudstaff.com`. Do not serve this
from `[removed]`.

Prefer doing it in `wrangler.toml` rather than clicking. There is a commented
`[[routes]]` block at the bottom of that file; uncomment it and redeploy, so the
hostname lives in git for the same drift reason as the Worker itself.

**5. Put it behind Access, with the right policy.** See the next section, which
is the part that actually decides whether this works for your purpose.

**6. Publish.** Note it takes **no scan file** -- it renders from the ledger.

```bash
# look at it first
./scripts/publish-dashboard.sh --dry-run
open reports/publish-preview/dashboard.html

# then for real
export FLEET_PUBLISH_URL=https://fleet.thudstaff.com
export FLEET_PUBLISH_TOKEN=<the PUBLISH_TOKEN value>
./scripts/publish-dashboard.sh
```

**7. Let CI do it.** The `Pantheon Fleet Health Check` workflow has a
`publish_dashboard` input, **default off**. Turn it on once the above works by
hand. It needs two repo settings:

| where | name | value |
|---|---|---|
| Settings, Secrets and variables, Actions, **Variables** | `FLEET_PUBLISH_URL` | `https://fleet.thudstaff.com` |
| Settings, Secrets and variables, Actions, **Secrets** | `FLEET_PUBLISH_TOKEN` | the `PUBLISH_TOKEN` value |

The publish job runs **after** `persist-ledger`, and checks out `main` fresh.
Both matter: publishing first would ship a page rendered from a ledger that does
not yet hold the run that just finished, so the live dashboard would sit one
scan behind forever and nothing on the page would say so.

It also requires `persist_ledger` to be on. With no ingest there is nothing new
to publish.

---

## Access: read this before sharing the link

The deck at `[removed]` sits behind a Cloudflare Access allowlist of
three people, Doug, Matt and Brian. That is correct for the deck, which contains
[removed], [removed] and the [removed].

**Your developers are not on that list, and should not be added to it.** If this
dashboard is served from the deck's hostname or reuses the deck's policy, either
Tor cannot open the link, or he can open the partner deck. Both are bad.

So: a separate hostname with its own Access application and its own policy that
includes the dev team. That is a five-minute job in the Zero Trust dashboard,
and it is the actual prerequisite for showing anyone this page.

If you want it visible to the whole company, an Access policy of "emails ending
in @clevermethod.com" is the simplest correct rule. The dashboard contains no
client-confidential data, only your own fleet's plugin inventory, but it is
still internal infrastructure detail and should not be public.

For CI publishing, create an Access **service token** and let the Worker route
bypass Access for it, or skip the HTTP publish path entirely and upload with
`wrangler r2 object put` from the runner instead.

---

## Wiring it into CI

One step at the end of the scan job, after artifacts are uploaded:

```yaml
      - name: Publish dashboard
        if: always()
        env:
          FLEET_PUBLISH_URL: ${{ vars.FLEET_PUBLISH_URL }}
          FLEET_PUBLISH_TOKEN: ${{ secrets.FLEET_PUBLISH_TOKEN }}
        run: |
          SCAN="$(ls -1 reports/*.json | tail -n1)"
          [ -n "$SCAN" ] && ./scripts/publish-dashboard.sh "$SCAN"
```

The Azure DevOps equivalent is the same two env vars and the same one script
call, which is the reason the publishing logic is in a shell script rather than
in the workflow file.

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
