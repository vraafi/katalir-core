#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frontend E2E (Playwright) — bukti bahwa chat di katalir.de5.net BERJALAN.

Yang dibuktikan skrip ini (bukan disimulasikan):
  1. Login nyata lewat UI (Supabase email+password) di domain produksi.
  2. Kirim prompt lewat composer, tunggu balasan asisten muncul di thread.
  3. Reload halaman -> riwayat chat muncul (persistensi terlihat oleh user).
  4. SEMUA error console + request gagal dicatat, supaya klaim "tidak ada
     error CORS/CSP" punya bukti, bukan asumsi.

Jalankan dari root repo:
    PLAYWRIGHT_BROWSERS_PATH=D:\\caches\\playwright \
      "C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe" \
      ops/frontend_e2e_playwright.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
FRONT = "https://katalir.de5.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
# PROMPT + EXPECT dipilih supaya pengecekan TIDAK bisa lolos karena gema pesan
# user. Versi pertama memakai kata kunci yang ADA di prompt, sehingga
# `innerText.includes(kata)` bernilai true hanya dari bubble pesan user —
# itu bukti palsu. Di sini prompt memuat "111+222" dan yang dicari adalah
# "333": angka itu hanya bisa datang dari BALASAN model.
PROMPT = "Berapa hasil 111+222? Balas HANYA angkanya."
EXPECT = "333"


def load_env() -> dict:
    out = {}
    p = ROOT / ".env"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def post(url, data, headers, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={**headers, "User-Agent": UA, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def make_user(env):
    """Buat user uji. Kunci service LAMA (JWT) — `sb_secret_…` ditolak Auth."""
    su = env["SUPABASE_URL"].rstrip("/")
    svc = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY")
    anon = env.get("SUPABASE_KEY") or env.get("SUPABASE_PUBLISHABLE_KEY")
    email = f"e2e-ui-{int(time.time())}-{uuid.uuid4().hex[:6]}@test.dev"
    pw = "E2e!" + uuid.uuid4().hex[:16]
    s, b = post(f"{su}/auth/v1/admin/users",
                {"email": email, "password": pw, "email_confirm": True},
                {"apikey": svc, "Authorization": "Bearer " + svc})
    if s != 200:
        raise RuntimeError(f"admin create gagal {s}: {b}")
    return email, pw


def main() -> int:
    env = load_env()
    if not env.get("SUPABASE_URL"):
        print("GAGAL: .env tanpa SUPABASE_URL")
        return 2
    email, pw = make_user(env)
    print(f"[setup] user uji dibuat: {email.split('@')[0]}***@test.dev")

    console_errors: list[str] = []
    failed_requests: list[str] = []
    shots: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 950},
                                  device_scale_factor=2, user_agent=UA)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("requestfailed",
                lambda r: failed_requests.append(f"{r.method} {r.url} :: {r.failure}"))

        print("[1] buka landing")
        # `networkidle` rapuh: halaman dengan aktivitas latar (Cloudflare RUM,
        # polling) tidak pernah benar-benar idle -> timeout 60 s. Yang penting
        # bukan "jaringan sunyi" melainkan elemen siap dipakai, jadi tunggu
        # `load` lalu tunggu selektornya secara eksplisit.
        page.goto(FRONT + "/", wait_until="load", timeout=60_000)
        page.wait_for_selector('[data-testid="landing-signin-trigger"]', timeout=45_000)

        print("[2] buka modal login + isi kredensial")
        page.click('[data-testid="landing-signin-trigger"]', timeout=30_000)
        page.fill('[data-testid="login-email"]', email)
        page.fill('[data-testid="login-password"]', pw)
        page.click('[data-testid="login-submit"]')

        print("[3] tunggu redirect setelah login")
        page.wait_for_timeout(6000)
        print("    url =", page.url)

        print("[4] buka /chat")
        page.goto(FRONT + "/chat", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector('[data-testid="composer-input"]', timeout=45_000)
        # Onboarding menutup seluruh layar dan MENGHALANGI klik composer
        # (terbukti: klik pertama gagal dengan "onboarding-flow intercepts
        # pointer events"). Lewati bila muncul; kalau tidak muncul, lanjut.
        try:
            page.click('[data-testid="onboarding-skip"]', timeout=10_000)
            print("    onboarding dilewati")
        except Exception:  # noqa: BLE001
            print("    onboarding tidak muncul (sudah selesai)")
        page.wait_for_timeout(2500)
        shot0 = DOCS / "chat-e2e-1-kosong.png"
        page.screenshot(path=str(shot0), full_page=False)
        shots.append(str(shot0))

        print("[5] kirim prompt")
        page.fill('[data-testid="composer-input"]', PROMPT)
        page.click('[data-testid="composer-send"]')

        print("[6] tunggu balasan asisten muncul")
        ok_reply = False
        try:
            page.wait_for_function(
                "() => document.body.innerText.includes('" + EXPECT + "')",
                timeout=180_000)
            ok_reply = True
        except Exception as e:  # noqa: BLE001
            print("    TIMEOUT menunggu balasan:", str(e)[:160])
        err_card = page.locator('[data-testid="error-card"]').count()
        print(f"    kartu error di thread: {err_card}")
        page.wait_for_timeout(1500)
        shot1 = DOCS / "chat-e2e-2-sukses.png"
        page.screenshot(path=str(shot1), full_page=False)
        shots.append(str(shot1))

        print("[7] reload -> riwayat harus muncul")
        page.reload(wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        try:
            page.click('[data-testid="onboarding-skip"]', timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(3000)
        ok_hist = EXPECT in page.inner_text("body")
        shot2 = DOCS / "chat-e2e-3-riwayat.png"
        page.screenshot(path=str(shot2), full_page=False)
        shots.append(str(shot2))

        browser.close()

    print("=" * 74)
    print(f"balasan muncul        : {ok_reply}")
    print(f"riwayat setelah reload: {ok_hist}")
    print(f"console error/warning : {len(console_errors)}")
    for e in console_errors[:12]:
        print("   ", e[:180])
    print(f"request gagal         : {len(failed_requests)}")
    for r in failed_requests[:12]:
        print("   ", r[:180])
    for s in shots:
        print("   screenshot:", s, pathlib.Path(s).stat().st_size, "bytes")

    summary = {"reply": ok_reply, "history": ok_hist,
               "console_errors": console_errors, "failed_requests": failed_requests,
               "screenshots": shots, "email_masked": email.split("@")[0][:6] + "***"}
    (ROOT / "_frontend_e2e_result.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if (ok_reply and ok_hist) else 1


if __name__ == "__main__":
    sys.exit(main())
