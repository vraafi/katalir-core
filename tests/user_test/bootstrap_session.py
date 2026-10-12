"""Bootstrap sesi user NYATA untuk pengujian UI.

Sesi di `.autonomous_session.json` sudah kedaluwarsa, tetapi refresh_token-nya
masih ada. Kita refresh lewat Supabase (grant_type=refresh_token) memakai
publishable key publik, lalu menanam sesi itu ke localStorage dengan kunci yang
dibaca supabase-js v2: `sb-<project-ref>-auth-token`.

Ini BUKAN akun palsu: ini sesi asli yang diterbitkan backend untuk user asli
`otonom-test@katalir-internal.dev`. Yang tidak bisa kita lakukan otomatis
adalah klik-consent Google OAuth - itu dilaporkan terpisah sebagai BLOCKED.

Keluaran: tests/user_test/_session.json (untuk dipakai harness utama).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

import httpx

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "tests" / "user_test"
ENV = ROOT / ".env"


def env_get(name: str) -> str:
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == name:
            return v.strip().strip('"').strip("'").strip()
    return ""


sess = json.loads((ROOT / ".autonomous_session.json").read_text(encoding="utf-8"))
sb_url = env_get("SUPABASE_URL")
sb_key = env_get("SUPABASE_PUBLISHABLE_KEY") or env_get("SUPABASE_KEY")
ref = re.sub(r"^https://([a-z0-9]+)\.supabase\.co.*$", r"\1", sb_url)

print(f"supabase url : {sb_url}")
print(f"ref          : {ref}")
print(f"publishable  : {'ADA' if sb_key else 'TIDAK ADA'} ({len(sb_key)} char)")
if not (sb_url and sb_key):
    print("GAGAL: konfigurasi Supabase tidak lengkap")
    sys.exit(2)

# ---- refresh -------------------------------------------------------------
r = httpx.post(
    f"{sb_url}/auth/v1/token?grant_type=refresh_token",
    headers={"apikey": sb_key, "Content-Type": "application/json"},
    json={"refresh_token": sess["refresh_token"]}, timeout=45.0)
print(f"\nrefresh      : HTTP {r.status_code}")
if r.status_code != 200:
    print(f"  body: {r.text[:300]}")
    sys.exit(3)

fresh = r.json()
session_obj = {
    "access_token": fresh["access_token"],
    "token_type": fresh.get("token_type", "bearer"),
    "expires_in": fresh.get("expires_in", 3600),
    "expires_at": fresh.get("expires_at"),
    "refresh_token": fresh.get("refresh_token", sess["refresh_token"]),
    "user": fresh.get("user", sess["user"]),
}
print(f"  access_token : {len(session_obj['access_token'])} char")
print(f"  expires_at   : {session_obj['expires_at']}")
print(f"  user         : {session_obj['user'].get('email')}")

(OUT / "_session.json").write_text(json.dumps({
    "storage_key": f"sb-{ref}-auth-token",
    "session": session_obj,
    "supabase_url": sb_url,
    "anon_key": sb_key,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nbukti -> {OUT / '_session.json'}")
