/**
 * cm-fleet-worker.js
 * CleverMethod - serves the fleet scan dashboard from R2.
 *
 * DELIBERATELY SMALL. It has no idea what a Pantheon site is, does no
 * classification, and holds no business logic. It reads two objects out of R2
 * and returns them. Everything that decides what a site's state means lives in
 * scripts/lib/severity.py, so the dashboard is identical whether it is opened
 * as a local file or served from here.
 *
 * NOTHING IN THIS FILE CHANGED on 2026-08-19, and that is the point: the
 * dashboard moved from a single-scan render to a ledger-backed one, and the
 * Worker did not need to know. It serves bytes.
 *
 * Routes
 *   GET /                  -> R2 fleet/dashboard.html
 *   GET /components        -> R2 fleet/components.html   (added 2026-08-23)
 *   GET /consent           -> R2 fleet/consent.html      (added 2026-08-27)
 *   GET /api/fleet-scan    -> R2 fleet/latest.json
 *                             {"schema":"fleet-dashboard/2", ...} since
 *                             2026-08-19. The old {stamp, kind, rows} shape is
 *                             gone; consumers should check `schema`.
 *   GET /healthz           -> plain "ok", for uptime checks
 *
 * READ-ONLY. There is no write route. A PUT /api/publish/<key> existed until
 * 2026-08-19; publishing now writes to the bucket directly with
 * `wrangler r2 object put`, from scripts/publish-dashboard.sh.
 *
 * Why it went: the route sat behind a hostname that is behind Cloudflare
 * Access, so a machine publishing had to clear Access with a service token AND
 * a correctly ordered Service Auth policy, just to reach a bearer-token check
 * it would then also have to pass. Two auth layers, one of which a machine
 * cannot satisfy without extra configuration, guarding an operation the R2 API
 * already authenticates on its own.
 *
 * Deleting it removed a class of problem rather than solving one, and left
 * this Worker with no write endpoint on a public hostname at all. Do not add
 * one back without a reason that survives that sentence.
 *
 * Binding required:  R2 bucket binding named FLEET  (point it at dash-data)
 * No secrets.
 *
 * ACCESS: this hostname is behind Cloudflare Access with a policy that
 * includes the developers. Do NOT reuse the deck's policy - the deck is
 * partner-confidential and its allowlist is Doug/Matt/Brian only.
 */

const PREFIX = "fleet/";

const SEC = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "same-origin",
};

// The dashboard is regenerated on every scan, so it must never be served stale.
const NOCACHE = { "Cache-Control": "no-store, max-age=0" };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/healthz") {
      return new Response("ok", { headers: { "Content-Type": "text/plain", ...SEC } });
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405, headers: SEC });
    }

    if (path === "/api/fleet-scan") {
      return serve(env, PREFIX + "latest.json", "application/json; charset=utf-8");
    }

    if (path === "/" || path === "/index.html") {
      return serve(env, PREFIX + "dashboard.html", "text/html; charset=utf-8");
    }

    // The component catalogue. The fleet page's plugin count links here, so
    // this route and fleet/components.html must both exist or that link is
    // dead. Adding a route to this file changes NOTHING until someone runs
    // `wrangler deploy` from ci/cloudflare -- on 2026-08-20 an audit found the
    // deployed Worker a full day behind this file.
    if (path === "/components" || path === "/components.html") {
      return serve(env, PREFIX + "components.html", "text/html; charset=utf-8");
    }

    // The consent page. Added 2026-08-27, and the day it shipped it was
    // UPLOADED AND UNREACHABLE: publish-dashboard.sh put fleet/consent.html in
    // R2, the fleet page linked to /consent from the Consent column header,
    // and this Worker 404'd it. The test written that day asserted the upload
    // and not the route, which is exactly half the contract.
    //
    // A page in R2 that no route serves is invisible, and it looks identical
    // to a page that was never rendered. test-worker-exposure.py now asserts
    // every HTML file publish-dashboard.sh uploads has a route here.
    if (path === "/consent" || path === "/consent.html") {
      return serve(env, PREFIX + "consent.html", "text/html; charset=utf-8");
    }

    // The vulnerability page. Added 2026-08-31 IN THE SAME CHANGE as the
    // publisher upload and the exposure test, because the consent page
    // shipped uploaded and unreachable when those three were split up: R2 had
    // the file, the fleet page linked to it, and this Worker 404'd it.
    //
    // Adding a route here changes NOTHING until someone runs `wrangler
    // deploy` from ci/cloudflare. On 2026-08-20 an audit found the deployed
    // Worker a full day behind this file.
    if (path === "/vulnerabilities" || path === "/vulnerabilities.html") {
      return serve(env, PREFIX + "vulnerabilities.html", "text/html; charset=utf-8");
    }

    return new Response("Not found", { status: 404, headers: SEC });
  },
};

async function serve(env, key, contentType) {
  if (!env.FLEET) {
    return new Response(
      "R2 binding FLEET is not configured on this Worker.",
      { status: 500, headers: { "Content-Type": "text/plain", ...SEC } }
    );
  }
  const obj = await env.FLEET.get(key);
  if (!obj) {
    // A missing dashboard is a setup problem, so say so rather than 404ing
    // silently and leaving someone guessing.
    // This message names the CURRENT command on purpose. It pointed at
    // render-fleet-dashboard.py until 2026-08-19, which would have talked
    // whoever hit this page into publishing the wrong dashboard - a
    // single-scan snapshot instead of the ledger view.
    const msg = key.endsWith(".html")
      ? "No dashboard published yet. From the cm-automation repo:\n\n" +
        "  CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... \\\n" +
        "      ./scripts/publish-dashboard.sh\n\n" +
        "It renders from the ledger in history/ and takes no scan file, and\n" +
        "uploads straight to R2 rather than through this Worker.\n" +
        "Use --dry-run first to look at the page before it goes live.\n"
      : "No fleet data published yet at " + key + "\n";
    return new Response(msg, { status: 404, headers: { "Content-Type": "text/plain", ...SEC } });
  }
  return new Response(obj.body, {
    headers: {
      "Content-Type": contentType,
      "ETag": obj.httpEtag,
      ...NOCACHE,
      ...SEC,
    },
  });
}

