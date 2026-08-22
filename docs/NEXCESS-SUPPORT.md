# Nexcess support: the questions that block automation

Two questions, both blocking, both needing a person at Nexcess rather than more
code here. Send them together — they are the same conversation.

Account: clevermethod, Inc. Nexcess account ID 82607. 21 Managed WordPress
sites.

---

## Question 1: the API is behind a bot challenge (BLOCKING NOW)

**What we need:** API-token requests to `https://portal.nexcess.net/api/v1/*`
to reach the API instead of a Cloudflare managed challenge.

### Re-verified live 2026-08-22

Support's first question is usually "is this still happening?", so this block
is dated and reproducible. Every request below carried a deliberately invalid
token — the challenge is served before the token is read, so no credential is
needed to reproduce this, and none was used.

| base URL | result |
|---|---|
| `https://portal.nexcess.net/api` | HTTP 403, `server: cloudflare`, `cf-mitigated: challenge` |
| `https://portal.nexcess.net` | HTTP 403, same |
| `https://sites-portal.nexcess.com/api` | HTTP 200, but the portal SPA's HTML, not JSON |
| `https://api.nexcess.net` | does not resolve |

The precise signal is the response header **`cf-mitigated: challenge`** with
`server: cloudflare`, which is more specific than the `Just a moment...` body
and is the string your edge team will recognise.

Two facts from the same pass:

- **Not User-Agent fingerprinting.** `cm-automation/fleet-nexcess (read-only)`
  and a conventional `Chrome/140` desktop string received byte-identical
  challenges.
- **Not a single bad edge node.** The two requests were answered by different
  Cloudflare PoPs — `cf-ray` ending `-EWR` and `-ORD`. This is policy, not a
  misbehaving cache.

Both HTTP clients were re-tested from one source IP: Python `urllib` and
`curl`/OpenSSL, challenged identically.

Reproduce with `./scripts/fleet-nexcess.py probe`.

**What this pass did NOT re-test**, so the dated block is not read as covering
more than it does: the comparison against a logged-in browser on the same IP
(`{"message":"Unauthorized"}`) is from the original 2026-08-19 investigation
and was not repeated. It is the one claim below that rests on a browser
session rather than on a scripted request, and if Nexcess disputes it, re-run
that specific check before arguing the point.

### Draft message

> We use a Nexcess Client Portal API token to run a read-only inventory of our
> Managed WordPress sites — `GET /v1/site` and `GET /v1/site/{id}`, nothing
> else, no writes.
>
> Requests from a scripted HTTP client to
> `https://portal.nexcess.net/api/v1/site` receive a Cloudflare managed
> challenge page (`<title>Just a moment...</title>`, HTTP 403) rather than an
> API response. The same URL from a logged-in browser returns
> `{"message":"Unauthorized"}` as expected, so the endpoint is correct and
> reachable — the challenge is served at the edge, before the request reaches
> the application, which means our token is never evaluated.
>
> We have ruled out the obvious client-side causes. The challenge is served
> regardless of User-Agent, and it is served identically to two independent
> HTTP clients with different TLS stacks (Python's `urllib` and `curl`/OpenSSL)
> from the same source IP on which a browser succeeds. So this is not a
> fingerprint we can change from our side.
>
> The response carries `cf-mitigated: challenge` with `server: cloudflare`.
> Re-verified 2026-08-22, and answered by two different Cloudflare PoPs
> (`cf-ray` ending `-EWR` and `-ORD`), so this is a standing policy on the
> zone rather than one misbehaving edge node.
>
> Three questions:
>
> 1. Can API-token requests to `/api/v1/*` be exempted from the bot challenge
>    for our account?
> 2. If not, is there a different hostname or endpoint intended for
>    programmatic access? Your API documentation writes every example against
>    `$PORTAL_API_URL` without defining it, so we established
>    `https://portal.nexcess.net/api` by observing the portal's own traffic. If
>    that is the wrong base URL for automation, please tell us the right one.
> 3. Are there documented requirements for API clients — a required
>    User-Agent, an allowlisted source IP, an additional header — that we are
>    missing?

### Why this matters, if they ask

We are one month past a critical WordPress vulnerability (wp2shell,
unauthenticated RCE). Our remediation record is blank for all 21 Nexcess sites
because nothing can read their WordPress versions. `GET /v1/site/{id}` would
answer that for the whole estate in a single read-only pass.

### What we have already established, so nobody re-treads it

| claim | status |
|---|---|
| `https://portal.nexcess.net/api` is the base URL | **established** — the portal SPA calls `/api/v1/user/self` there; a browser gets `{"message":"Unauthorized"}` from `/api/v1/site` |
| `api.nexcess.net` | does not resolve |
| `sites-portal.nexcess.com/api` | the portal web UI, returns the SPA's HTML |
| the challenge is a User-Agent problem | **ruled out** — a conventional desktop UA is challenged identically |
| the challenge is a TLS-fingerprint problem we can change | **ruled out** — Python `urllib` and `curl`/OpenSSL are challenged identically |
| the challenge is our IP | **unlikely** — a browser on the same IP is served normally |
| the token is bad | **ruled out** — the challenge is served before the token is read |
| a single misbehaving edge node | **ruled out** 2026-08-22 — two Cloudflare PoPs (`-EWR`, `-ORD`) challenge identically |
| the challenge has since cleared | **no** — re-verified live 2026-08-22, still `cf-mitigated: challenge` |

The pattern that remains: **Cloudflare challenges any client that has not
solved its JavaScript challenge and therefore holds no `cf_clearance` cookie.**
That is a blanket bot-protection policy applied to a documented API surface,
which makes the API unusable by any automated client. Only Nexcess can change
it.

We have deliberately not attempted to solve or work around the challenge, and
will not. We are asking for the endpoint to be usable as documented.

---

## Question 2: does one account-level SSH key reach every site? (BLOCKS PHASE 2)

**This is section 19 of `NEXCESS-ARCHITECTURE.md` and it is still unanswered.**
It gates the SSH deep scan, which is what gives us backup ages and plugin
counts for these 21 sites.

### Draft message

> Nexcess Managed WordPress SSH identities are per site (each site has its own
> Unix username), but SSH public keys appear to be managed centrally at the
> user or account level.
>
> If we add one SSH public key at the user level, does it authorise
> connections to every Managed WordPress site that user can reach — including
> sites created later — or does each site need its key added separately?
>
> Related: is there any way to create a read-only SSH user? We want an
> automation identity that can run `wp core version` and `wp plugin list` and
> nothing else, and as far as we can tell every SSH account on Managed
> WordPress is write-capable.

### Why the answer changes the design

- **Yes, one key reaches all:** one credential, one GitHub secret, one
  workflow. Build it.
- **No, per site:** 21 credentials and a different architecture. Do not build
  fleet-wide SSH until this is answered — see `docs/NEXCESS.md`.

The read-only question matters separately. If no read-only user exists, the
scanning identity holds a write-capable credential no matter how carefully the
workflow behaves, and that is worth writing down before it is deployed rather
than after.

---

## When they answer

Record the answers in `docs/NEXCESS-ARCHITECTURE.md` next to the claims they
settle, and mark those claims verified with the date. That file's whole
provenance header exists because it is imported research; an answered question
should stop looking like an open one.
