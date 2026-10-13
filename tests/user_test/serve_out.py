"""Server statis untuk `nexus-frontend/out` (export statis Next.js).

Dipakai agar perbaikan bisa diuji LOKAL dulu (menunjuk ke backend produksi)
sebelum dideploy ke Cloudflare Pages.

Next.js `output: "export"` menulis /chat sebagai `chat.html`, jadi server biasa
tidak cukup: di sini path tanpa ekstensi dipetakan ke `<path>.html`, lalu
`<path>/index.html`, terakhir `404.html` (meniru perilaku hosting statis).

Pakai: python tests/user_test/serve_out.py [port]
"""
from __future__ import annotations

import functools
import http.server
import pathlib
import socketserver
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "nexus-frontend" / "out"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4321


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: D102
        # buang query & fragment
        clean = path.split("?", 1)[0].split("#", 1)[0]
        rel = clean.lstrip("/")
        cand = ROOT / rel
        if cand.is_file():
            return str(cand)
        if (ROOT / f"{rel}.html").is_file():
            return str(ROOT / f"{rel}.html")
        if (ROOT / rel / "index.html").is_file():
            return str(ROOT / rel / "index.html")
        if rel == "":
            return str(ROOT / "index.html")
        return str(ROOT / "404.html")

    def log_message(self, fmt, *args):  # noqa: D102
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not ROOT.is_dir():
        raise SystemExit(f"tidak ada folder build: {ROOT}")
    socketserver.TCPServer.allow_reuse_address = True
    with Server(("127.0.0.1", PORT), functools.partial(Handler, directory=str(ROOT))) as httpd:
        print(f"serve {ROOT} -> http://127.0.0.1:{PORT}", flush=True)
        httpd.serve_forever()
