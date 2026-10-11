#!/usr/bin/env python3
"""Baca / (opsional) set originRequest tunnel Cloudflare tanpa pernah mencetak token.

Pakai:
    python ops/cf_tunnel_config.py probe            # cek scope token + baca konfigurasi
    python ops/cf_tunnel_config.py apply            # set keepAliveTimeout/keepAliveConnections
    python ops/cf_tunnel_config.py apply --dry-run

Tidak pernah menuliskan nilai token ke stdout/stderr.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TUNNEL_ID = "ae3fac5c-cd1c-4f24-9242-be90563d53e5"
API = "https://api.cloudflare.com/client/v4"

# Nilai yang ingin dipasang (lihat docs backend-recovery §6).
#
# keepAliveTimeout SENGAJA lebih pendek dari `--timeout-keep-alive` uvicorn
# (120 s). Aturan yang benar: sisi hulu (cloudflared) harus SELALU yang lebih
# dulu menutup koneksi idle, supaya cloudflared tidak pernah mengirim request
# ke socket yang sudah ditutup origin (penyebab `read: connection reset by
# peer` -> 502). 30 s juga mempersempit jendela socket basi setelah restart.
ORIGIN_REQUEST = {
    "connectTimeout": 30,
    "keepAliveTimeout": 30,
    "keepAliveConnections": 100,
    "tcpKeepAlive": 30,
    "http2Origin": False,
}
# Hanya rule yang menuju backend katalir (8100) yang disentuh.
ONLY_SERVICE_MATCH = "8100"


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def redact(s: str) -> str:
    """Buang kemungkinan kebocoran token dari pesan."""
    env = load_env()
    for key in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        val = env.get(key)
        if val and len(val) > 8:
            s = s.replace(val, f"<{key}:REDACTED>")
    return s


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    dry = "--dry-run" in sys.argv
    env = load_env()
    token = env.get("CLOUDFLARE_API_TOKEN")
    acct = env.get("CLOUDFLARE_ACCOUNT_ID")
    if not token:
        print("GAGAL: CLOUDFLARE_API_TOKEN tidak ada di .env")
        return 2
    if not acct:
        print("GAGAL: CLOUDFLARE_ACCOUNT_ID tidak ada di .env")
        return 2
    print(f"token  : ada ({len(token)} char, prefix {token[:6]}...)")
    print(f"account: {acct}")

    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30, headers=h) as c:
        r = c.get(f"{API}/user/tokens/verify")
        body = r.json()
        print(f"\n[1] verify token -> HTTP {r.status_code} success={body.get('success')}")
        if body.get("success"):
            res = body.get("result") or {}
            print(f"    status={res.get('status')} expires={res.get('expires_on')}")
        else:
            # Token milik AKUN (prefix cfat_) tidak boleh memanggil endpoint
            # /user/* — itu BUKAN bukti token tidak valid. Lanjut ke endpoint
            # account-scoped, di situ validitas sebenarnya terlihat.
            print("    (endpoint /user/* tidak diizinkan untuk token akun — "
                  "dilanjutkan ke endpoint account-scoped)")

        r = c.get(f"{API}/accounts/{acct}/cfd_tunnel/{TUNNEL_ID}")
        print(f"\n[2] GET tunnel -> HTTP {r.status_code}")
        b = r.json()
        if not b.get("success"):
            print("    " + redact(json.dumps(b.get("errors"))[:400]))
            print("    -> token TIDAK punya scope Account:Cloudflare Tunnel:Read")
            return 4
        t = b["result"]
        print(f"    name={t.get('name')} status={t.get('status')} remote={t.get('remote_config')}")

        r = c.get(f"{API}/accounts/{acct}/cfd_tunnel/{TUNNEL_ID}/configurations")
        print(f"\n[3] GET configurations -> HTTP {r.status_code}")
        b = r.json()
        if not b.get("success"):
            print("    " + redact(json.dumps(b.get("errors"))[:400]))
            return 4
        cur = b["result"]
        cfg = cur.get("config") or {}
        print("    konfigurasi sekarang:")
        print("    " + json.dumps(cfg, indent=2)[:1500].replace("\n", "\n    "))

        if mode != "apply":
            print("\n(mode probe — tidak mengubah apa pun)")
            return 0

        # Gabungkan: pertahankan ingress, tambah/perbarui originRequest.
        new_cfg = dict(cfg)
        ingress = new_cfg.get("ingress") or []
        merged_ingress = []
        for rule in ingress:
            rule = dict(rule)
            if rule.get("hostname") and rule.get("service") \
                    and ONLY_SERVICE_MATCH in str(rule.get("service")):
                oreq = dict(rule.get("originRequest") or {})
                oreq.update(ORIGIN_REQUEST)
                rule["originRequest"] = oreq
            merged_ingress.append(rule)
        if not merged_ingress:
            print("GAGAL: ingress kosong — menolak menimpa (takut merusak rute).")
            return 5
        new_cfg["ingress"] = merged_ingress

        print("\n[4] konfigurasi yang akan dipasang:")
        print("    " + json.dumps(new_cfg, indent=2)[:1500].replace("\n", "\n    "))
        if dry:
            print("\n(--dry-run — tidak dikirim)")
            return 0

        r = c.put(
            f"{API}/accounts/{acct}/cfd_tunnel/{TUNNEL_ID}/configurations",
            json={"config": new_cfg},
        )
        print(f"\n[5] PUT configurations -> HTTP {r.status_code}")
        b = r.json()
        if not b.get("success"):
            print("    " + redact(json.dumps(b.get("errors"))[:500]))
            print("    -> token tidak punya scope Account:Cloudflare Tunnel:Edit")
            return 6
        print("    OK. Konfigurasi tunnel diperbarui.")

        r = c.get(f"{API}/accounts/{acct}/cfd_tunnel/{TUNNEL_ID}/configurations")
        got = ((r.json().get("result") or {}).get("config") or {}).get("ingress") or []
        for rule in got:
            if rule.get("hostname"):
                print("    verifikasi originRequest: "
                      + json.dumps(rule.get("originRequest")))
        return 0


if __name__ == "__main__":
    sys.exit(main())
