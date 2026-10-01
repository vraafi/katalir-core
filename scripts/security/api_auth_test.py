"""Uji endpoint backend Katalir TANPA browser: login Supabase -> panggil API.

Kenapa skrip ini ada: AGENT_PLAYBOOK.md menyebut JWT hasil login kedaluwarsa
sekitar 1 jam. Setiap kali begitu, pengujian endpoint terautentikasi menggantung
menunggu "tolong login dulu". Skrip ini mengambil JWT sendiri lewat Supabase
Auth API (password grant), jadi pengujian bisa diulang kapan saja.

Buat user tes sekali saja (Admin API, butuh service-role/secret key), lalu
seluruh sesi berikutnya cukup password grant.

Pakai:
    python scripts/security/api_auth_test.py             # login + uji semua
    python scripts/security/api_auth_test.py --chat      # + skenario /chat
    python scripts/security/api_auth_test.py --seed      # buat user tes dulu

Nilai credential & JWT tidak pernah dicetak (hanya prefix + panjang).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
API = "https://web-production-dc90b.up.railway.app"
TEST_EMAIL = "test-otonom@katalir.com"
TEST_PASSWORD = "KatalirOtonom2026!"
UA = "python-httpx/0.28.1"   # sb_secret_ MENOLAK User-Agent browser


def load_env() -> dict:
    sys.path.insert(0, str(ROOT))
    from dotenv import dotenv_values
    vals = dotenv_values(ROOT / ".env")
    return {k: v for k, v in vals.items() if v}


def call(method, url, body=None, headers=None, timeout=200):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {str(exc)[:110]}", time.time() - t0


def seed_user(env):
    """Buat user tes lewat Admin API (idempoten; 422 = sudah ada)."""
    sb = env["SUPABASE_URL"].rstrip("/")
    key = env.get("SUPABASE_SECRET_KEY") or env["SUPABASE_SERVICE_ROLE_KEY"]
    admin = {"apikey": key, "Authorization": "Bearer " + key}
    st, body, _ = call("POST", f"{sb}/auth/v1/admin/users",
                       {"email": TEST_EMAIL, "password": TEST_PASSWORD,
                        "email_confirm": True}, admin)
    print(f"  seed user: HTTP {st}")
    if st == 422:
        print("  -> sudah ada, lanjut")
    elif st not in (200, 201):
        print(f"  -> GAGAL: {body[:160]}")
        return False
    return True


def login(env) -> str:
    sb = env["SUPABASE_URL"].rstrip("/")
    st, body, _ = call("POST", f"{sb}/auth/v1/token?grant_type=password",
                       {"email": TEST_EMAIL, "password": TEST_PASSWORD},
                       {"apikey": env["SUPABASE_PUBLISHABLE_KEY"]})
    if st != 200:
        print(f"  LOGIN GAGAL HTTP {st}: {body[:200]}")
        return ""
    jwt = json.loads(body).get("access_token", "")
    print(f"  LOGIN OK  JWT {jwt[:12]}... len={len(jwt)}")
    return jwt


def main() -> int:
    env = load_env()
    print("=== 1. USER TES ===")
    if "--seed" in sys.argv:
        seed_user(env)
    print("\n=== 2. LOGIN (password grant) ===")
    jwt = login(env)
    if not jwt:
        return 1

    auth = {"Authorization": "Bearer " + jwt}
    print("\n=== 3. ENDPOINT TERAUTENTIKASI ===")
    fails = 0
    for method, path in [("GET", "/me"), ("GET", "/quota"), ("GET", "/workflows"),
                         ("GET", "/sessions"), ("GET", "/preferences"),
                         ("GET", "/models"), ("GET", "/analytics")]:
        st, body, dt = call(method, API + path, headers=auth)
        flag = "OK  " if st == 200 else "GAGAL"
        if st != 200:
            fails += 1
        print(f"  {flag} {method:4s} {path:13s} HTTP {st}  {dt:5.2f}s  {body[:96]}")

    print("\n=== 4. KONTROL: tanpa JWT harus 401 ===")
    for path in ("/me", "/workflows", "/sessions"):
        st, body, _ = call("GET", API + path, headers={"Authorization": ""})
        flag = "OK  " if st == 401 else "GAGAL"
        if st != 401:
            fails += 1
        print(f"  {flag} {path:13s} HTTP {st}  {body[:80]}")

    if "--chat" in sys.argv:
        print("\n=== 5. SKENARIO /chat (ngukur waktu) ===")
        for prompt in ["Halo, ini tes otonom.", "Jelaskan workflow 3 langkah."]:
            st, body, dt = call("POST", API + "/chat",
                                {"prompt": prompt}, auth, timeout=220)
            flag = "OK  " if st == 200 else "GAGAL"
            if st != 200:
                fails += 1
            print(f"  {flag} {dt:6.2f}s  HTTP {st}  {body[:130]}")

    print(f"\n  total kegagalan: {fails}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())