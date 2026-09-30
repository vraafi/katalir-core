"""Uji otorisasi backend produksi dengan/request TANPA kredensial.

Regex analisis source tidak bisa dibuktikan; yang bisa dibuktikan adalah
respons nyata. Setiap endpoint sensitif dipanggil tanpa header Authorization.
Harapan: 401/403. Kalau ada yang 200, itu temuan severity tinggi karena
data user terekspos tanpa login.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

BASE = "https://web-production-dc90b.up.railway.app"
UA = {"User-Agent": "katalir-security-audit"}

# (method, path, body) - body hanya untuk endpoint POST/PUT/PATCH.
CHECKS = [
    ("GET", "/me", None),
    ("GET", "/preferences", None),
    ("GET", "/quota", None),
    ("GET", "/analytics", None),
    ("GET", "/sessions", None),
    ("GET", "/api/vault/list", None),
    ("GET", "/workflows", None),
    ("GET", "/integrations", None),
    ("GET", "/community/my-earnings", None),
    ("GET", "/mcp/my-instances", None),
    ("GET", "/mcp/gateway/servers", None),
    ("POST", "/chat", {"message": "authz probe"}),
    ("POST", "/api/vault/save", {"provider": "probe", "api_key": "probe"}),
    ("POST", "/workflows", {"name": "probe"}),
    ("POST", "/integrations", {"provider": "probe"}),
    ("POST", "/mcp/install", {"server_id": "probe"}),
    # Endpoint yang HARUS publik (baseline: harus 200 tanpa auth).
    ("GET", "/models", None),
]


def call(method: str, path: str, body: dict | None) -> tuple[int | str, int, str]:
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(UA)
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read()
            return r.status, len(raw), ""
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, len(raw), ""
    except Exception as exc:
        return type(exc).__name__, 0, ""


def main() -> int:
    results = []
    unauth_ok = []
    for method, path, body in CHECKS:
        code, size, _ = call(method, path, body)
        results.append({"method": method, "path": path, "code": code, "body_len": size})
        flag = ""
        if code == 200 and path not in ("/models",):
            flag = "  <== NO_AUTH_REQUIRED"
            unauth_ok.append(f"{method} {path}")
        print(f"{method:6} {path:34} -> {code} len={size}{flag}")

    print("\nUNAUTHENTICATED_200=" + json.dumps(unauth_ok))
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"results": results, "unauthenticated_200": unauth_ok}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
