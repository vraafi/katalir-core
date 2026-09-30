"""Probe endpoint sensitif di host produksi.

Tujuan: memastikan file konfigurasi/rahasia tidak diekspos lewat static hosting
maupun API. Setiap path dicek di frontend (Cloudflare Pages) dan backend
(Railway). Hasil yang diharapkan: 404/403/401 - BUKAN 200.

Hanya path dan status code yang dicetak, tidak ada body (body 200 bisa saja
berisi secret).
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

FRONTEND = "https://katalir.de5.net"
BACKEND = "https://web-production-dc90b.up.railway.app"

PATHS = [
    "/.env", "/.env.local", "/.env.production", "/.git/config", "/.git/HEAD",
    "/config.json", "/secrets.json", "/api/keys", "/debug", "/actuator/env",
    "/server-status", "/wp-admin", "/.aws/credentials",
]


def probe(base: str, path: str, timeout: float = 10.0) -> tuple[int | str, int]:
    url = base + path
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "katalir-security-audit"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, len(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, 0
    except Exception as exc:  # timeout, DNS, TLS
        return type(exc).__name__, 0


def main() -> int:
    report: dict = {"frontend": {}, "backend": {}}
    for label, base in (("frontend", FRONTEND), ("backend", BACKEND)):
        for path in PATHS:
            code, size = probe(base, path)
            report[label][path] = {"code": code, "body_len": size}
            print(f"{label:9} {path:24} -> {code} len={size}")

    exposed = [
        f"{label}:{path}" for label in ("frontend", "backend")
        for path, v in report[label].items() if v["code"] == 200
    ]
    report["exposed_200"] = exposed
    print("\nEXPOSED_200=" + json.dumps(exposed))

    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
