<!-- PROVENANCE — this block is the only text on this page that we wrote. -->

> **Verbatim inbound message. Do not edit below the rule.**
>
> | | |
> |---|---|
> | direction | **in** — Nexcess/Liquid Web to clevermethod |
> | received | 2026-08-24 |
> | thread | `thread::sJecUJQ2cS6EeEacWJKo2D0::` |
> | account | clevermethod, Inc. — Nexcess 82607 |
> | in reply to | the ticket sent 2026-08-22, `docs/NEXCESS-SUPPORT.md` |
> | captured from | `liquidWeb-AP-question-response-08242026.md`, Cowork Automation Portfolio (iCloud) |
>
> **What it settles, and where that is recorded:** one account-level SSH key
> reaches every Managed WordPress site, existing and future — recorded in
> `NEXCESS-ARCHITECTURE.md` §3. No read-only SSH user exists — recorded in
> §3 and in CLAUDE.md's hard boundaries. The Cloudflare-challenge question was
> **not** answered; the browser-User-Agent suggestion below was re-tested live
> on 2026-08-24 and is still challenged. See `docs/NEXCESS-SUPPORT.md`,
> "The reply, 2026-08-24".

---

Hello Team,

I appreciate your patience.

Thank you for the detailed information regarding API token creation and the Cloudflare challenge triggered when you attempt programmatic access to the WordPress site's inventory.

At this time, we recommend configuring the API requests to use a custom User-Agent that matches a standard web browser. You can obtain your browser's User-Agent by opening the browser's Developer Console and running:

navigator.userAgent

Once retrieved, please configure your API client or scripted requests to use this User-Agent and test the API request again. This should allow the requests to pass through successfully without triggering the Cloudflare challenge.

You can also find additional information and documentation regarding the Nexcess API token here: https://github.com/nexcess/nexcess-api-docs/tree/master/api-token

Additionally, if the issue persists, please provide more details about how the requests are made.

Regarding your questions about SSH access and permissions for Managed WordPress sites:

A single SSH public key added through the Nexcess Client Portal is managed at the user/account level. This means that the same key can be used to access all Managed WordPress sites that the user is authorized to access, including sites currently associated with the account, as well as any sites added in the future. There is no need to add the same SSH key separately for each individual site.

Regarding your request for a read-only or restricted SSH user, this is not currently supported on Managed WordPress or Nexcess Cloud accounts. SSH users created for Managed WordPress sites have both read and write permissions on the site's filesystem.

Therefore, it would not be possible to create an SSH automation identity that is restricted to running only commands such as wp core version and wp plugin list while preventing all other write operations.

If a dedicated server environment with custom or restricted SSH permissions is an absolute requirement, this may be possible on a bare-metal dedicated server. In that case, we recommend speaking with our Sales team so they can review the specific requirements and verify with our engineering teams whether the requested configuration can be accommodated.

Let us know how you would like to proceed, and please don't hesitate to ask if you have any further queries. We are here to help you 24/7.


[Account #: 82607]
[Account Name: clevermethod, Inc.]

Muhamed M.
Support
Nexcess | Liquid Web
Help Docs

thread::sJecUJQ2cS6EeEacWJKo2D0:: 