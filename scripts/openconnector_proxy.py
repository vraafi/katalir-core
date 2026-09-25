"""Local MCP proxy: forwards to OpenConnector and injects the runtime token.

Binds 127.0.0.1:3011 only. The token is read from /root/.openconnector.env and
never logged.
"""
import http.server, json, os, pathlib, urllib.request

UPSTREAM = "http://127.0.0.1:3010"
ENV_PATH = pathlib.Path("/root/.openconnector.env")


def token() -> str:
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("OOMOL_CONNECT_RUNTIME_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "authorization", "connection"}}
        headers["Authorization"] = "Bearer " + token()
        req = urllib.request.Request(UPSTREAM + self.path, data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in {"transfer-encoding", "connection", "content-length"}:
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except Exception as exc:  # noqa: BLE001
            msg = json.dumps({"error": {"code": "proxy_error", "message": type(exc).__name__}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    do_GET = _proxy
    do_POST = _proxy
    do_DELETE = _proxy
    do_PUT = _proxy

    def log_message(self, *args):  # never log request lines (may contain tokens)
        return


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 3011), Handler).serve_forever()
