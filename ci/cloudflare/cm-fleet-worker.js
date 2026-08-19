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
 *   GET /api/fleet-scan    -> R2 fleet/latest.json
 *                             {"schema":"fleet-dashboard/2", ...} since
 *                             2026-08-19. The old {stamp, kind, rows} shape is
 *                             gone; consumers should check `schema`.
 *   GET /healthz           -> plain "ok", for uptime checks
 *   PUT /api/publish/<key> -> upload, requires the PUBLISH_TOKEN secret
 *
 * Binding required:  R2 bucket binding named FLEET  (point it at dash-data)
 * Secret required for publishing:  PUBLISH_TOKEN
 *
 * ACCESS: put this hostname behind Cloudflare Access with a policy that
 * includes the developers. Do NOT reuse the deck's policy - the deck is
 * partner-confidential and its allowlist is Doug/Matt/Brian only.
 * The PUT route is bypassed by Access via a service token, or you skip it and
 * upload with wrangler instead.
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

    if (request.method === "PUT" && path.startsWith("/api/publish/")) {
      return publish(request, env, path.slice("/api/publish/".length));
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
        "  FLEET_PUBLISH_URL=<this hostname> FLEET_PUBLISH_TOKEN=<PUBLISH_TOKEN> \\\n" +
        "      ./scripts/publish-dashboard.sh\n\n" +
        "It renders from the ledger in history/ and takes no scan file.\n" +
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

async function publish(request, env, name) {
  const token = env.PUBLISH_TOKEN;
  if (!token) {
    return new Response("Publishing is disabled: PUBLISH_TOKEN is not set.", { status: 503, headers: SEC });
  }
  const given = request.headers.get("Authorization") || "";
  const expected = "Bearer " + token;
  // Constant-time-ish compare. Length check first so we never compare a short
  // guess against a long secret and leak length through timing.
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) {
    return new Response("Unauthorized", { status: 401, headers: SEC });
  }
  if (!/^[a-zA-Z0-9._-]{1,64}$/.test(name)) {
    return new Response("Bad object name", { status: 400, headers: SEC });
  }
  await env.FLEET.put(PREFIX + name, request.body);
  return new Response(JSON.stringify({ ok: true, key: PREFIX + name }), {
    headers: { "Content-Type": "application/json", ...SEC },
  });
}

function timingSafeEqual(a, b) {
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
