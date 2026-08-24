# Nexcess support: the questions that block automation

Two questions, both blocking, both needing a person at Nexcess rather than more
code here. Send them together — they are the same conversation.

Account: clevermethod, Inc. Nexcess account ID 82607. 21 Managed WordPress
sites.

> **STATUS: SENT 2026-08-22. ANSWERED 2026-08-24.** Both questions went in as
> one ticket and Nexcess replied on 2026-08-24. **Question 2 is settled — see
> "The reply" immediately below.** Question 1 is not: the reply asks us to do
> the one thing this file already recorded as ruled out. This file is now a
> record of what was asked, what came back, and what still needs answering.
> **Do not re-send the original ticket** — reply on the existing thread,
> `thread::sJecUJQ2cS6EeEacWJKo2D0::`, using the draft at the bottom.

---

## The reply, 2026-08-24

**The reply is archived verbatim at
`docs/correspondence/2026-08-24-nexcess-in-ssh-and-api-challenge.md`** — read
it there rather than trusting the summary below. Ticket
`thread::sJecUJQ2cS6EeEacWJKo2D0::`, Muhamed M. Captured from
`liquidWeb-AP-question-response-08242026.md` in the Cowork Automation Portfolio
folder; the archived body was verified byte-identical to that original.

| what we asked | what came back | settled? |
|---|---|---|
| Exempt `/api/v1/*` from the bot challenge | Not addressed. Instead: set a browser User-Agent, taken from `navigator.userAgent` | **no** |
| Is there a different hostname for programmatic access? | Not addressed. Linked the `api-token` docs, which still write `$PORTAL_API_URL` without defining it | **no** |
| Documented client requirements — UA, allowlisted IP, header? | Only the browser-UA suggestion. No IP allowlist or header named | **partly** — see below |
| Does one user-level SSH key reach every Managed WordPress site? | **Yes.** Keys are managed at the user/account level. One key reaches every site that user is authorised for, **including sites added later**. No per-site key needed | **yes** |
| Can we have a read-only SSH user? | **No.** Not supported on Managed WordPress or Nexcess Cloud. SSH users have read *and* write on the site filesystem. Restricting to `wp core version` / `wp plugin list` is not possible. Bare-metal dedicated is the only path they offered, via Sales | **yes** |

### The User-Agent suggestion was re-tested and is still wrong

Support's answer to question 1 is the one thing this file had already ruled
out on 2026-08-22. Re-verified **live on 2026-08-24** rather than quoted from
the earlier pass, because "is it still happening" is the first thing they will
ask:

```
NEXCESS_PORTAL_API_TOKEN=<deliberately invalid> ./scripts/fleet-nexcess.py probe
NEXCESS_PORTAL_API_TOKEN=<deliberately invalid> ./scripts/fleet-nexcess.py probe --user-agent browser
```

Both runs: `https://portal.nexcess.net/api` → HTTP 403, `Just a moment...`,
edge bot challenge. The conventional `Chrome/140.0.0.0` desktop string is
challenged **identically** to `cm-automation/fleet-nexcess (read-only)`. The
token was deliberately invalid in both, and that is the point — the challenge
is served before the token is read, so no credential is needed to reproduce
this and none was used.

`probe` itself now says so on the second run: *"A conventional User-Agent was
already tried on this run and was challenged too, so the fingerprint is not the
header."*

**Why the suggestion cannot work, structurally.** Cloudflare's managed
challenge issues a `cf_clearance` cookie to a client that has executed its
JavaScript. A `curl` or `urllib` request holds no such cookie no matter what
UA string it sends, so copying a browser's `navigator.userAgent` copies the
one part of the browser that is not what got the browser through. This is not
a case of us not having tried hard enough with headers.

### The docs link does not answer question 2

They linked `github.com/nexcess/nexcess-api-docs/tree/master/api-token`. Read
2026-08-24. Every example there is written against `$PORTAL_API_URL` and the
repository defines it nowhere — no root `README.md` exists, and the
`authentication/` folder holds only passphrase helpers. The link restates the
gap we reported rather than closing it, so the "what is the right base URL for
automation" question stands.

### Independent corroboration of the SSH answer

`ssh-key/add.md` in that same repository documents `POST /v1/ssh-key` with
exactly two parameters, `name` and `key`, and **no site parameter** — the
resource is user-scoped by construction. That is a second, documentary line of
evidence for the account-level answer, arrived at separately from support's
statement.

### What the reply did NOT answer, and must not be read as answering

The six sub-questions in section 19 of `NEXCESS-ARCHITECTURE.md` were not all
covered. Still open after this reply:

- **Propagation lag** — is a newly added key usable immediately on all sites?
- **Revocation timing** — when a user loses access to a site, is key access
  removed immediately?
- **Can a user-level key be scoped to selected sites?** They said one key
  reaches everything the user may reach. They did not say whether it can be
  narrowed.
- **SSH concurrency limits** across dozens of simultaneous Actions jobs.

"One key reaches all sites" is a good answer to the question that gates the
design. It is not an answer to the four above, and this file says so here so
that nobody later reads the settled row in the table as covering them.

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

**Done for the 2026-08-24 reply:** section 3 "Confirmed" and section 19 now
carry the answers and their date, and section 18 keeps only what is still open.

---

## Reply to send, 2026-08-24 (question 1 only)

Reply on the existing thread. Question 2 needs no reply, it was answered.

**Deliberately soft, and deliberately leads with the base-URL question. Do not
"restore" a firmer version without reading why.** An earlier draft led with the
rebuttal: a full account of why a User-Agent cannot defeat a challenge gated on
a `cf_clearance` cookie, then a request to exempt the account at the edge. Three
reasons that was the wrong letter.

1. **The stakes are low and we did not know that when it was written.**
   Measured 2026-08-24: the API cannot move the health-coverage scoreboard at
   all, because `coverage_partial` fires on exactly the facts discovery writes.
   The SSH scan is worth 21 of the 32. The API is enumeration and the
   `unix_username` join key, both of which a person can read out of the portal
   once for 21 sites. Spending goodwill at full volume on bookkeeping is a bad
   trade, and support just gave us the answer that unblocked the real work.
2. **The expensive ask can quietly die; the cheap one cannot.** "Exempt our
   account from the bot challenge" needs someone with edge access and is an
   escalation. "What is `$PORTAL_API_URL`?" is answerable by the person reading
   the ticket, in one line. It also might genuinely be the answer: we inferred
   that base URL from portal network traffic, not from documentation, and
   `sites-portal.nexcess.com` exists and serves something else.
3. **It was written past its reader.** The `cf_clearance` explanation is aimed
   at an edge engineer and was going to be read by a support agent working a
   script. Explaining someone's suggestion back to them as structurally naive
   is a poor way to ask that same person to escalate.

What survives: the evidence is still there, it is just offered rather than
presented, and the invalid-token detail stays because it is the one line that
tells an engineer the token is never being read. Nothing was conceded and no
claim was weakened.

**Once sent, archive what was actually sent** as
`docs/correspondence/2026-08-__-nexcess-out-api-challenge.md`. The draft below
is what we intended to say; the archive is what we said, and they diverge as
soon as anyone edits a word before hitting send.

> Hi Muhamed,
>
> Thank you, this is really helpful. The SSH answers settle what we needed to
> know, and we can move forward on that side. We appreciate you checking on the
> read-only user question even though the answer was no.
>
> One thing still open on the API, and it may be a simple one.
>
> The documentation you linked writes every example against `$PORTAL_API_URL`,
> and we cannot find anywhere that variable is defined. We have been using
> `https://portal.nexcess.net/api`, which we worked out by watching the
> portal's own network requests rather than from any documentation. So our
> first question is just: **what is the correct base URL for API token
> requests?** If we have simply been calling the wrong host, that would explain
> everything and we can stop there.
>
> If `https://portal.nexcess.net/api` is the right one, then we do have a
> genuine problem, because requests from a script get a Cloudflare challenge
> page rather than an API response. We did try the browser User-Agent
> suggestion, both before opening this ticket and again today. It returns the
> same challenge, HTTP 403 with `cf-mitigated: challenge`. Worth noting we see
> this even with an intentionally invalid token, which suggests the request is
> being stopped at the edge before the token is checked.
>
> We have logs of the full request and response headers, including `cf-ray`
> values, and are happy to send them over or to work with whoever looks after
> the edge configuration. Just let us know what would be most useful.
>
> For context, this is a small read-only inventory job. We call `GET /v1/site`
> and `GET /v1/site/{id}` and nothing else, no writes. We are not trying to get
> around the protection, we would just like to use the API as documented.
>
> Thanks again for the SSH answers, those were the ones holding us up.
>
> Best,
> Doug

### If they decline both

Then the API is unusable by any automated client and Phase 1 stays blocked
permanently. **That is survivable now, because the SSH answer landed.** The
account-level key makes the Phase 2 SSH scan buildable, and SSH returns
strictly more than the control plane does — backup ages and plugin counts,
which `GET /v1/site/{id}` never had. The API's remaining unique value is site
*enumeration*: which sites the account actually contains, and the per-site Unix
username that the SSH scan needs as its join key. Both can come from the portal
UI by hand for 21 sites. Slow and manual, not blocking.
