#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Penjaga KONSISTENSI DEPLOY: situs produksi vs `nexus-frontend/out/`.

KENAPA ADA (insiden 11 Okt 2026):
Chat di katalir.de5.net mati total karena bundle yang BENAR sudah ada di
`out/` tetapi BELUM di-upload ke Cloudflare Pages. Yang tersaji masih build
lama yang memanggil backend Railway yang sudah mati. Tidak ada satu pun test
yang menangkap ini — semua test hijau, semua infra sehat, tapi yang dilayani
ke browser adalah kode yang salah.

Skrip ini membandingkan ARSIP YANG DISAJIKAN dengan ARSIP LOKAL, jadi
"lupa `wrangler pages deploy out`" langsung ketahuan.

Yang diperiksa:
  A. Setiap chunk `/_next/static/**.js` yang direferensikan HTML produksi
     HARUS ada di `out/` dengan isi (md5) yang SAMA PERSIS.
  B. Tidak ada chunk produksi yang menyebut host backend MATI (`railway.app`).
  C. Setidaknya satu chunk produksi menyebut host backend AKTIF
     (`gateway.katalir.de5.net`).
  D. Header CSP yang benar-benar dikirim Cloudflare memuat host backend aktif
     dan TIDAK memuat host mati.

Jalankan dari root repo:
    python scripts/verify_deploy_consistency.py
Exit code 0 = konsisten, 1 = DRIFT (perlu `wrangler pages deploy out`).
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import urllib.error
import urllib.request

SITE = "https://katalir.de5.net"
ROUTES = ["/", "/chat"]
OUT = pathlib.Path(__file__).resolve().parent.parent / "nexus-frontend" / "out"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

ACTIVE_HOST = "gateway.katalir.de5.net"
DEAD_HOSTS = ["web-production-dc90b.up.railway.app", "railway.app"]

CHUNK_RE = re.compile(r'/_next/static/[A-Za-z0-9_\-./]+\.js')

problems: list[str] = []
notes: list[str] = []


def get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


def main() -> int:
    if not OUT.is_dir():
        print(f"FATAL: {OUT} tidak ada — jalankan `next build` dulu.")
        return 2

    # ---- A/C: kumpulkan chunk yang direferensikan produksi ----------------
    refs: set[str] = set()
    html_ok = 0
    csp_seen: str | None = None
    for route in ROUTES:
        try:
            status, body, headers = get(SITE + route)
        except Exception as exc:  # noqa: BLE001
            print(f"FATAL: GET {SITE + route} gagal: {exc!r}")
            return 2
        if status != 200:
            print(f"FATAL: {SITE + route} -> HTTP {status}")
            return 2
        html_ok += 1
        text = body.decode("utf-8", "replace")
        refs.update(CHUNK_RE.findall(text))
        # Header CSP diterapkan Cloudflare dari `_headers` (static export).
        csp_seen = headers.get("content-security-policy") or csp_seen
        print(f"  GET {route:8} HTTP {status}  chunk direferensikan: "
              f"{len(CHUNK_RE.findall(text))}")

    refs = {r.split("?")[0] for r in refs}
    print(f"\nA. membandingkan {len(refs)} chunk produksi dengan `out/`...")

    active_found = False
    dead_found: list[str] = []
    identical = 0
    for ref in sorted(refs):
        rel = ref.lstrip("/")
        local = OUT / rel
        try:
            _, remote_bytes, _ = get(SITE + ref)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{ref}: gagal diunduh dari produksi ({exc!r})")
            continue
        # Pemeriksaan marker host dijalankan pada BYTES PRODUKSI lebih dulu,
        # SELALU. (Bug v1 penjaga ini: `continue` saat berkas lokal tidak ada
        # membuat chunk yang belum ter-deploy justru lolos dari pemeriksaan
        # host — persis kasus yang harus ditangkap.)
        text = remote_bytes.decode("utf-8", "replace")
        if ACTIVE_HOST in text:
            active_found = True
        for dead in DEAD_HOSTS:
            if dead in text:
                dead_found.append(f"{rel} menyebut host MATI: {dead}")
        if not local.is_file():
            problems.append(
                f"{ref}: ADA di produksi tapi TIDAK ADA di out/ -> deploy "
                f"menyajikan berkas asing (build lama?)")
            continue
        rm = hashlib.md5(remote_bytes).hexdigest()
        lm = hashlib.md5(local.read_bytes()).hexdigest()
        if rm != lm:
            problems.append(
                f"{rel}: ISI BERBEDA (produksi md5={rm[:12]} vs lokal "
                f"md5={lm[:12]}) -> out/ belum di-deploy")
            continue
        identical += 1

    print(f"   {identical}/{len(refs)} chunk identik byte-per-byte")
    notes.append(f"chunk identik: {identical}/{len(refs)}")

    # ---- B/C: marker host -------------------------------------------------
    print("\nB/C. memeriksa host backend di bundle produksi...")
    if dead_found:
        problems.extend(dead_found[:5])
    if not active_found:
        problems.append(
            f"tidak ada chunk produksi yang menyebut host AKTIF {ACTIVE_HOST} "
            f"-> bundle memanggil backend lain (cek NEXT_PUBLIC_API_URL)")
    print(f"   host aktif {ACTIVE_HOST}: "
          f"{'DITEMUKAN' if active_found else 'TIDAK DITEMUKAN'}")
    print(f"   host mati: {'DITEMUKAN -> ' + str(len(dead_found)) if dead_found else 'tidak ada'}")

    # ---- D: CSP ----------------------------------------------------------
    print("\nD. memeriksa CSP yang benar-benar dikirim...")
    if csp_seen is None:
        problems.append("respons produksi tidak membawa header Content-Security-Policy")
        print("   TIDAK ADA header CSP di respons")
    else:
        if ACTIVE_HOST not in csp_seen:
            problems.append(f"CSP tidak memuat {ACTIVE_HOST} -> API diblokir SENYAP")
        for dead in DEAD_HOSTS:
            if dead in csp_seen:
                problems.append(f"CSP masih memuat host mati {dead}")
        print(f"   connect-src memuat {ACTIVE_HOST}: "
              f"{'ya' if ACTIVE_HOST in csp_seen else 'TIDAK'}")

    # ---- Ringkasan -------------------------------------------------------
    print("\n" + "=" * 74)
    if problems:
        print(f"HASIL: DRIFT TERDETEKSI — {len(problems)} masalah")
        for p in problems:
            print(f"  - {p}")
        print("\nPERBAIKAN: cd nexus-frontend && npx wrangler pages deploy out "
              "--project-name=proyek-agent")
        print("=" * 74)
        return 1
    print("HASIL: KONSISTEN — produksi == out/ (chunk, host backend, CSP)")
    for n in notes:
        print(f"  {n}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
