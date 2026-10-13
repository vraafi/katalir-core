#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy `nexus-frontend/out` ke Cloudflare Pages (proyek `proyek-agent`).

Token Cloudflare dibaca dari `.env` dan diteruskan HANYA sebagai environment
variable ke proses `wrangler` — tidak pernah dicetak ke stdout/log.

Alasan ada skrip ini (bukan perintah manual): insiden 11 Okt 2026 terjadi
karena `out/` sudah benar tapi TIDAK di-deploy. Menjadikannya satu perintah
yang bisa diulang + dipasangkan dengan
`scripts/verify_deploy_consistency.py` menutup celah itu.

Jalankan dari root repo:
    python ops/deploy_pages.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
OUT = ROOT / "nexus-frontend" / "out"
FE = ROOT / "nexus-frontend"
PROJECT = "proyek-agent"


def env_load() -> dict:
    out: dict = {}
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def run_gate(script: str, label: str) -> int:
    """Jalankan gerbang Node sebelum deploy. 0 = lolos.

    Insiden 12 Okt 2026: `out/` sudah ada, CSP sudah benar, tapi bundle masih
    menunjuk host mati -> deploy "sukses" tapi produksi rusak. Gerbang ini
    menolak deploy bila sumber ATAU hasil build tidak konsisten.
    """
    node = os.environ.get("NODE_BIN") or "node"
    p = FE / "scripts" / script
    if not p.exists():
        print(f"FATAL: gerbang {p} tidak ada")
        return 2
    print(f"$ node scripts/{script}   [{label}]")
    r = subprocess.run([node, str(p)], cwd=str(FE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    sys.stdout.write((r.stdout or "") + (r.stderr or ""))
    if r.returncode != 0:
        print(f"FATAL: gerbang '{label}' GAGAL (exit={r.returncode}) — deploy dibatalkan.")
    return r.returncode


def main() -> int:
    if not OUT.is_dir():
        print(f"FATAL: {OUT} tidak ada — jalankan `next build` dulu.")
        return 2

    # --- GERBANG WAJIB: jangan pernah deploy tanpa keduanya lolos ----------
    if run_gate("check-api-url-csp.mjs", "sumber: env vs CSP") != 0:
        return 3
    if run_gate("check-bundle-hosts.mjs", "hasil: isi bundle out/") != 0:
        return 3
    # FASE 7: pembayaran ditutup -> URL checkout HARAM ada di bundle. Gerbang ini
    # menangkap berkas env yang terlewat (mis. .env.local yang menang atas
    # .env.production) — kesalahan yang TIDAK terlihat dari sumber mana pun.
    if run_gate("check-payment-hidden.mjs", "hasil: pembayaran tertutup") != 0:
        return 3

    e = env_load()
    token = e.get("CLOUDFLARE_API_TOKEN")
    account = e.get("CLOUDFLARE_ACCOUNT_ID")
    if not token:
        print("FATAL: CLOUDFLARE_API_TOKEN tidak ada di .env")
        return 2

    env = dict(os.environ)
    env["CLOUDFLARE_API_TOKEN"] = token
    if account:
        env["CLOUDFLARE_ACCOUNT_ID"] = account

    exe = FE / "node_modules" / ".bin" / ("wrangler.cmd" if os.name == "nt" else "wrangler")
    if not exe.exists():
        print(f"FATAL: wrangler tidak ada di {exe}")
        return 2

    cmd = [str(exe), "pages", "deploy", str(OUT),
           f"--project-name={PROJECT}", "--commit-dirty=true"]
    print(f"$ wrangler pages deploy out --project-name={PROJECT}")
    r = subprocess.run(cmd, env=env, cwd=str(FE),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    # Sabuk pengaman: jangan pernah mencetak token walau wrangler menggemanya.
    if token:
        out = out.replace(token, "<CLOUDFLARE_API_TOKEN>")
    print(out[-5000:])
    print(f"exit={r.returncode}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
