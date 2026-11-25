"""Read-only local HTTP dashboard. No DNS lookups or external requests."""

import hmac
import ipaddress
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from .store import dashboard, csv_export


def is_loopback(bind):
    try:
        return ipaddress.ip_address(bind).is_loopback
    except ValueError:
        return bind.lower() == "localhost"


def make_handler(db, bind, token=None):
    loopback = is_loopback(bind)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # Query strings may contain private device addresses or domains.
            pass

        def send_body(self, status, body, content_type, download=False):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="dns-queries.csv"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Local dashboards must reject hostile DNS rebinding Host headers.
            try:
                host = urlsplit("http://" + self.headers.get("Host", "")).hostname
            except ValueError:
                host = None
            if loopback and host not in {bind.lower(), "127.0.0.1", "localhost", "::1"}:
                return self.send_body(403, "Unrecognized host", "text/plain; charset=utf-8")
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")}:
                return self.send_body(403, "Cross-origin request rejected", "text/plain; charset=utf-8")
            path = urlsplit(self.path)
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path.path in assets:
                filename, mimetype = assets[path.path]
                return self.send_body(200, files("queryconfessional").joinpath("static", filename).read_bytes(), mimetype)
            if path.path not in {"/api/dashboard", "/api/export.csv"}:
                return self.send_body(404, "Not found", "text/plain; charset=utf-8")
            if token and not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
                return self.send_body(401, json.dumps({"error": "Access token required"}), "application/json")
            try:
                params = {key: values[-1] for key, values in parse_qs(path.query, max_num_fields=20).items()}
                if path.path.endswith(".csv"):
                    return self.send_body(200, csv_export(db, params), "text/csv; charset=utf-8", download=True)
                return self.send_body(200, json.dumps(dashboard(db, params)), "application/json")
            except ValueError as exc:
                return self.send_body(400, json.dumps({"error": str(exc)}), "application/json")
            except Exception:
                return self.send_body(500, json.dumps({"error": "Unable to read the local database"}), "application/json")

    return Handler


def serve(db, bind, port, token=None):
    if not is_loopback(bind) and not token:
        raise ValueError("Non-loopback listening requires QUERYCONFESSIONAL_TOKEN; prefer an SSH tunnel")
    if token and len(token) < 24:
        raise ValueError("Access token must contain at least 24 characters")
    server_type = ThreadingHTTPServer
    if ":" in bind:
        class IPv6HTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        server_type = IPv6HTTPServer
    server = server_type((bind, port), make_handler(db, bind, token))
    display_bind = f"[{bind}]" if ":" in bind else bind
    print(f"Query Confessional: http://{display_bind}:{server.server_port}/ (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

