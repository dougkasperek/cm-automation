#!/usr/bin/env python3
"""
serve-dashboard.py
CleverMethod - watch a reports directory and serve the fleet dashboard live.

    ./scripts/serve-dashboard.py                 # watches ./reports, serves :8787
    ./scripts/serve-dashboard.py --dir reports --port 8787 --open

WHY THIS EXISTS
The scan scripts rewrite their JSON after EVERY site, not just at the end. That
means a running scan is watchable. This server picks up the newest scan JSON in
the directory, re-renders whenever the file changes, and the page polls every 3
seconds. Start the server, start a scan in another terminal, and the dashboard
fills in site by site while people watch.

That is the demo: no Cloudflare, no Access policy, no CI, no deploy. One command
on the machine that can actually reach Pantheon, and a browser on a projector.

Python 3 standard library only. No pip install, nothing to set up.

Routes
    /                 the dashboard
    /api/fleet-scan   {stamp, kind, rows, scanning} - what the page polls
    /healthz          "ok"
"""

import argparse
import importlib.util
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

# The renderer's filename has hyphens, so it cannot be imported normally.
_spec = importlib.util.spec_from_file_location(
    "render_fleet_dashboard", os.path.join(HERE, "render-fleet-dashboard.py")
)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

# How a finished scan is distinguished from a running one.
#
# PRIMARY SIGNAL: the scan scripts write their .json after every site, but write
# the .md digest ONCE, at the very end. So a .md sitting beside the .json with
# the same stamp means that scan completed. That is exact, and it is why the
# page stops saying SCAN RUNNING the moment the run ends rather than after a
# timeout.
#
# FALLBACK: if no .md exists, fall back to "was the .json touched recently".
# A single slow site can take up to the script's per-call timeout, so this needs
# headroom or a live scan would flicker to "finished" mid-run.
RUNNING_WINDOW_S = 75


class State:
    def __init__(self, watch_dir):
        self.watch_dir = watch_dir
        self.lock = threading.Lock()
        self.html = None
        self.payload = None
        self.src = None
        self.src_mtime = 0
        self.error = None

    def newest_scan(self):
        """Newest *.json in the watch dir that looks like a scan, or None."""
        best, best_m = None, -1
        try:
            names = os.listdir(self.watch_dir)
        except OSError as exc:
            self.error = f"cannot read {self.watch_dir}: {exc}"
            return None
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.watch_dir, name)
            try:
                m = os.path.getmtime(path)
            except OSError:
                continue
            if m > best_m:
                best, best_m = path, m
        return best

    def refresh(self, force=False):
        path = self.newest_scan()
        if not path:
            with self.lock:
                self.html, self.payload = None, None
                self.error = f"no scan JSON found in {self.watch_dir}"
            return
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        if not force and path == self.src and mtime == self.src_mtime:
            return

        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (json.JSONDecodeError, OSError):
            # A scan mid-write can hand us a truncated file. That is normal and
            # transient: keep serving the last good render rather than flashing
            # an error at whoever is watching.
            return
        if isinstance(rows, dict):
            rows = rows.get("rows") or list(rows.values())
        if not rows:
            return

        try:
            kind, table, states, title, sub, detail_col = R.model_for(rows)
        except SystemExit as exc:
            with self.lock:
                self.error = str(exc)
            return

        html = R.build_html(
            table=table, states=states, kind=kind, title=title, sub=sub,
            detail_col=detail_col, stamp=R.stamp_from_filename(path),
            src_name=os.path.basename(path), live_url="/api/fleet-scan",
        )
        with self.lock:
            self.src, self.src_mtime = path, mtime
            self.html = html
            self.payload = {"stamp": R.stamp_from_filename(path), "kind": kind, "rows": table}
            self.error = None
        print(f"  rendered {len(table):>3} sites from {os.path.basename(path)}", flush=True)

    def scanning(self):
        if not self.src or not self.src_mtime:
            return False
        # Exact signal first: a sibling .md means the run reached its end.
        digest = self.src[:-5] + ".md" if self.src.endswith(".json") else None
        if digest and os.path.exists(digest):
            return False
        return (time.time() - self.src_mtime) < RUNNING_WINDOW_S


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass  # the watcher prints what matters; request spam helps nobody

        def _send(self, code, body, ctype):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            state.refresh()

            if path == "/healthz":
                return self._send(200, "ok", "text/plain; charset=utf-8")

            if path == "/api/fleet-scan":
                with state.lock:
                    payload = dict(state.payload) if state.payload else None
                if not payload:
                    return self._send(404, json.dumps({"error": state.error or "no data"}),
                                      "application/json; charset=utf-8")
                payload["scanning"] = state.scanning()
                return self._send(200, json.dumps(payload), "application/json; charset=utf-8")

            if path in ("/", "/index.html"):
                with state.lock:
                    html = state.html
                    err = state.error
                if not html:
                    return self._send(200, WAITING.replace("__ERR__", err or ""),
                                      "text/html; charset=utf-8")
                return self._send(200, html, "text/html; charset=utf-8")

            return self._send(404, "Not found", "text/plain; charset=utf-8")

    return Handler


WAITING = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Waiting for a scan | clevermethod</title>
<meta http-equiv="refresh" content="3">
<style>
body{margin:0;background:#f5f0e8;color:#2a3540;font:15px/1.6 Inter,system-ui,-apple-system,sans-serif;
     display:flex;align-items:center;justify-content:center;min-height:100vh}
.b{max-width:600px;padding:36px 40px;background:#fff;border-radius:16px;box-shadow:0 0 0 1px rgba(11,11,11,.09)}
h1{font-family:Georgia,serif;font-size:24px;margin:0 0 12px;color:#17212b}
code{background:#f5f0e8;padding:2px 6px;border-radius:5px;font:13px Consolas,ui-monospace,monospace}
p{margin:0 0 12px}.m{color:#68737e;font-size:13px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#eb6834;margin-right:8px;
     animation:p 1.1s ease-in-out infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
</style></head><body><div class="b">
<h1><span class="dot"></span>Waiting for a scan</h1>
<p>This page refreshes every 3 seconds and will render itself the moment a scan
writes its first results.</p>
<p>In another terminal:</p>
<p><code>./scripts/pantheon-fleet-healthcheck.sh --api-only --no-fail-on-crit</code></p>
<p class="m">__ERR__</p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="./reports", help="directory to watch for scan JSON")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 keeps it on this machine. Use 0.0.0.0 only on a trusted network.")
    ap.add_argument("--open", action="store_true", help="open a browser once serving")
    args = ap.parse_args()

    watch = os.path.abspath(args.dir)
    os.makedirs(watch, exist_ok=True)

    state = State(watch)
    state.refresh(force=True)

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    except OSError as exc:
        print(f"ERROR: cannot bind {args.host}:{args.port} - {exc}", file=sys.stderr)
        print("Another copy may already be running. Try --port 8788.", file=sys.stderr)
        return 1

    url = f"http://{'localhost' if args.host == '127.0.0.1' else socket.gethostname()}:{args.port}/"
    print("")
    print("  clevermethod fleet dashboard, live")
    print(f"  watching : {watch}")
    print(f"  serving  : {url}")
    print("")
    print("  Start a scan in another terminal and this page fills in as it runs.")
    print("  Ctrl-C to stop.")
    print("")

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
