# Nexcess estate discovery

Phase 1 of `docs/NEXCESS-ARCHITECTURE.md`. Read-only. It asks the Nexcess
control plane what it knows about each site, so that the 21 Nexcess sites stop
being the dashboard's largest evidence gap.

**Status, 2026-08-19: BLOCKED on Nexcess.** The API is at
`https://portal.nexcess.net/api`. That host answers a browser with JSON and
answers this client with a Cloudflare challenge, so the token is never read.
User-Agent, TLS stack and IP have all been ruled out — see the table below.
**The next move is a support ticket, drafted in `docs/NEXCESS-SUPPORT.md`.
There is no further code to write until Nexcess answers.**

Everything below about field names remains vendor documentation that nothing
here has executed against.

---

## What it answers, and what it does not

| question | Phase 1 answers it? |
|---|---|
| Which sites does the Nexcess account actually contain? | yes |
| Do those sites match `data/fleet-inventory.json`? | yes |
| What PHP version is each on? | yes, per the control plane |
| What WordPress version is each on — the wp2shell question | yes, per the control plane |
| What is the per-site SSH username (the Phase 2 join key)? | yes |
| How old is the newest database backup? | **no** |
| How many plugin and theme updates are pending? | **no** |

The last two are why a Nexcess site cannot reach OK on discovery evidence. It
reaches WARN with `coverage_partial`, and that rule retires itself for a site
the moment a health scan supplies the missing facts. See `docs/SEVERITY.md`.

## Evidence tiers, and why the fact names are prefixed

The control plane and WP-CLI answer the same two questions by different means,
and the control plane's answer is the weaker of the two. So they are stored
under different names — `nexcess_app_version` and `nexcess_php_version`, never
`wp_version` and `php_version`.

Storing them under one name means whichever ran last wins and any disagreement
disappears. Storing them apart makes the disagreement a fact:
`wp_version_disagreement` reports it, and the WP-CLI reading is what scores.

The dashboard shows three tiers and labels each one:

- plain text — read off the site by WP-CLI
- *per host* — reported by the hosting control plane
- *claimed* — typed into the audit workbook, never verified

## The base URL

```
https://portal.nexcess.net/api
```

**Established 2026-08-19. Not from documentation** — no Nexcess page anywhere
defines `$PORTAL_API_URL`. Checked: the API docs repo, the API-token help page,
the portal guide, the Elasticsearch page. Every one uses the bare variable.

Established instead by watching what the portal's own single-page app calls.
In a logged-in browser at `sites-portal.nexcess.com`:

```js
performance.getEntriesByType('resource')
  .filter(e => e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch')
  .map(e => new URL(e.name).origin + new URL(e.name).pathname)
```

which returned `https://portal.nexcess.net/api/v1/user/self` and
`/api/v1/client/self`. Confirmed by requesting
`https://portal.nexcess.net/api/v1/site` in the browser: it returns
`{"message":"Unauthorized"}` — JSON from the application, not a challenge page
and not a 404.

**This recipe generalises.** When a vendor documents an API against an
undefined variable, their own web console is the documentation. Read its
network traffic rather than guessing hostnames.

## The blocker: a Cloudflare challenge, not the URL

`https://portal.nexcess.net/api/v1/site` serves:

| client | response |
|---|---|
| logged-in browser | `{"message":"Unauthorized"}` — JSON, from the application |
| `scripts/fleet-nexcess.py` | `<title>Just a moment...</title>` — Cloudflare managed challenge |

The challenge is served by the edge, so **the request never reaches the
application and the token is never read.** Rotating or rescoping the token
cannot change it. This tool reported that response as "the token was rejected"
and was wrong — see CLAUDE.md's table.

`probe` now checks for a challenge *before* any status branch, because a
challenge can arrive with 200, 403 or 503 and means the same thing every time.

### What to try, in order

```bash
./scripts/fleet-nexcess.py probe --api-base https://portal.nexcess.net/api \
                                 --user-agent browser
```

### Exhausted, 2026-08-19. Do not re-run these.

| test | result |
|---|---|
| default User-Agent, Python `urllib` | challenged |
| conventional desktop User-Agent | challenged |
| `curl` / OpenSSL, different TLS stack | challenged |
| logged-in browser, same IP | **`{"message":"Unauthorized"}` — served normally** |

Two independent HTTP clients with different TLS stacks are challenged from the
same source IP on which a browser succeeds. That rules out User-Agent, TLS
fingerprint and IP reputation together.

What remains: **Cloudflare challenges any client that has not solved its
JavaScript challenge and so holds no `cf_clearance` cookie.** That is blanket
bot protection over a documented API surface, and only Nexcess can change it.

**Stop writing code here.** Nothing in this repo attempts to solve or work
around a bot challenge, and nothing should. `docs/NEXCESS-SUPPORT.md` is the
drafted ticket, carrying this table so nobody re-treads it.

One optional data point, if a second opinion is wanted before sending: run the
CI workflow with `probe_only: true`. A GitHub runner is a different source
network. Expect the same result — a browser and curl differing on one IP points
at the challenge cookie, not the network — but it costs one click and makes the
ticket harder to deflect.

The scanner still has **no default base URL constant**. `probe` re-confirms it
in one request, and a stale base URL fails in a way that looks exactly like a
credentials problem.


## Running it

Local, on Doug's Mac. Nothing in this repo ever stores the token.

```bash
export NEXCESS_PORTAL_API_TOKEN='...'        # portal -> User Menu -> API Tokens

./scripts/fleet-nexcess.py probe             # confirms the base still returns a site list
export NEXCESS_PORTAL_API_URL=https://portal.nexcess.net/api

./scripts/fleet-nexcess.py discover \
    --inventory data/fleet-inventory.json \
    --out reports \
    --stamp "$(date -u +%Y-%m-%d_%H%M)" \
    --raw-out /tmp/nexcess-raw.json          # keep this on the FIRST run
```

`--raw-out` writes the unparsed API responses. Worth having the first time:
every field name the scanner reads comes from docs nothing has executed
against, so if a column comes back empty the raw file is what says whether the
API omitted the field or the scanner looked in the wrong place.

Then, only once the output has been read by a person:

```bash
./scripts/fleet-ledger.py ingest --reports ./reports --history ./history
./scripts/render-dashboard.py --out fleet.html
```

**Ingest is append-only. A mis-keyed row cannot be corrected in place.** Read
the reconciliation section of the report before ingesting the first run.

## In CI

`ci/github-actions/fleet-nexcess.yml`, copied to `.github/workflows/` by hand
because the file bridge cannot write there. **Diff the two before telling
anyone to run it.**

Manual dispatch only, and `persist_ledger` defaults to **off** for this
workflow while the other two default to on. Same reason: the first runs get
looked at as artifacts before any of it becomes permanent history.

Secrets: `NEXCESS_PORTAL_API_TOKEN`. The base URL is not a secret — pass it as
the `api_base` input, or set `NEXCESS_PORTAL_API_URL` if you prefer.

**Run `probe_only: true` in CI before anything else.** A GitHub runner has a
different IP reputation to a laptop, so it is a genuinely different test of the
Cloudflare challenge and costs nothing.

## What the first live run has to establish

Ordered by how much depends on it.

1. ~~Which base URL.~~ **Done: `https://portal.nexcess.net/api`.** What
   remains is getting past the Cloudflare challenge.
2. **Whether `GET /v1/site/{id}` returns an application version.** If it does,
   the wp2shell question is answered for 21 sites without SSH, which is the
   single biggest thing in this phase. If it does not, every Nexcess site
   scores WARN `nexcess_app_version_unknown` and Phase 2 becomes urgent rather
   than merely next.
3. **Whether `unix_username` is present.** It is the Phase 2 join key. Without
   it the SSH scan cannot be built at all, regardless of how the account-level
   SSH key question is answered.
4. **How many sites the API returns, against the inventory's 21.** Every tool
   that has arrived with its own roster has disagreed with the inventory, and
   the disagreement was always a finding. On Pantheon this same check surfaced
   the two worst-maintained sites in the fleet.
5. **What values `state` actually takes.** No rule is written against it yet,
   deliberately: a rule against a guessed enum either never fires or fires on
   everything.

## Still open, and blocking Phase 2

**Does one SSH public key added at the Nexcess user level authorise every
Managed WordPress site that user can reach, existing and future?**

True: one credential for 21 sites. False: 21 credentials and a different
design. Section 19 of `NEXCESS-ARCHITECTURE.md` is a ready-made support email.
Sending it is a human task. Do not build fleet-wide SSH on the assumption.

Nexcess has **no read-only SSH user**, so even a scan that only runs
`wp core version` holds a write-capable credential. Dedicated automation
identity, never an employee key, private key only in GitHub secrets.
