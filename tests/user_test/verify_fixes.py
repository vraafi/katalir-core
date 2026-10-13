"""Verifikasi perbaikan BUG-01 & BUG-02 (proof-first-testing: red -> green).

Dijalankan terhadap build LOKAL (`RUS_FRONTEND=http://127.0.0.1:4321`) memakai
proksi backend agar CORS tidak memblokir. Bisa juga diarahkan ke produksi
setelah deploy (tanpa proksi) untuk verifikasi akhir.

BUG-01 — prompt 8.000 karakter tidak pernah dibalas
  RED  : area percakapan tetap 8.000 char (hanya pesan user), bubble asisten
         kosong (content "…" -> <TypingDots/>), tanpa kartu galat.
  GREEN: balasan asisten muncul (panjang area percakapan > panjang prompt).

BUG-02 — refresh saat AI bekerja -> chat kosong
  RED  : setelah reload, area percakapan kosong & URL tanpa ?s=
  GREEN: setelah reload, percakapan dipulihkan (URL mendapat ?s=<sid> dan
         penanda prompt terlihat di area percakapan).

Keluaran: tests/user_test/_verify_fixes.json
"""
from __future__ import annotations

import json
import uuid
import os
import pathlib
import sys
import time

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from playwright.sync_api import sync_playwright  # noqa: E402

from rus_core import (COMPOSER, FRONTEND, dismiss_onboarding, goto, login,  # noqa: E402
                      msglist_text, new_ctx, proxy_backend, shot, visible_error_card)

LOCAL = "127.0.0.1" in (os.environ.get("RUS_FRONTEND") or "")
out: dict = {"frontend": FRONTEND, "lokal": LOCAL, "checks": {}}


def _login_ready(b):
    ctx = new_ctx(b)
    if LOCAL:
        proxy_backend(ctx)
    pg = ctx.new_page()
    login(pg)
    return ctx, pg


def check_bug01(b) -> dict:
    """Prompt 8.000 karakter harus mendapat balasan yang TERLIHAT."""
    ctx, pg = _login_ready(b)
    r: dict = {"nama": "BUG-01 prompt 8000 char dibalas"}
    try:
        goto(pg, "/chat", ms=3000)
        dismiss_onboarding(pg)
        ta = pg.locator(COMPOSER).first
        ta.click(timeout=15000)
        ta.fill("")
        ta.fill("a" * 8000)
        r["panjang_efektif"] = len(ta.input_value())
        t0 = time.time()
        ta.press("Enter")
        shot(pg, "verify-bug01-sebelum")
        r["t_balasan"] = None
        while time.time() - t0 < 90:
            pg.wait_for_timeout(1000)
            teks = msglist_text(pg)
            # BALASAN = area percakapan jauh lebih panjang dari prompt saja.
            # Ambang +80 (bukan +20): baris status "Agen sedang berpikir..."
            # menambah ~20 karakter ke area percakapan dan pernah membuat uji
            # ini melaporkan GREEN palsu (balasan belum tiba).
            if len(teks) > 8000 + 80:
                r["t_balasan"] = round(time.time() - t0, 1)
                break
        teks = msglist_text(pg)
        r["panjang_area_chat"] = len(teks)
        r["kartu_error"] = visible_error_card(pg)
        r["cuplikan_balasan"] = teks[8000:8300] if len(teks) > 8000 else ""
        # Bukti tambahan: apakah balasan benar-benar berada di dalam layar?
        r["posisi_gulir"] = pg.evaluate("""() => {
          const l = document.querySelector('[data-testid="msg-list"]');
          let s = l && l.parentElement;
          while (s && s !== document.body) {
            const st = getComputedStyle(s);
            if (/(auto|scroll)/.test(st.overflowY) && s.scrollHeight > s.clientHeight) break;
            s = s.parentElement;
          }
          return s ? { scrollTop: s.scrollTop, scrollHeight: s.scrollHeight,
                       clientHeight: s.clientHeight,
                       di_dasar: (s.scrollHeight - s.scrollTop - s.clientHeight) < 40 } : null;
        }""")
        r["state"] = "GREEN" if r["t_balasan"] else "RED"
        shot(pg, "verify-bug01-sesudah")
    except Exception as exc:  # noqa: BLE001
        r["state"] = "ERROR"
        r["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        ctx.close()
    print(f"  BUG-01: {r['state']}  t_balasan={r.get('t_balasan')}s "
          f"panjang_area={r.get('panjang_area_chat')} "
          f"err={r.get('kartu_error')}", flush=True)
    return r


def check_bug02(b) -> dict:
    """Refresh saat generasi berjalan harus memulihkan percakapan.

    Uji ini harus BENAR-BENAR menangkap jendela mid-generation. Kalau `?s=` sudah
    terpasang sebelum refresh, yang diuji bukan lagi kasusnya — percobaan itu
    dibuang dan diulang (bukan dilaporkan GREEN palsu).
    """
    ctx, pg = _login_ready(b)
    r: dict = {"nama": "BUG-02 refresh saat generasi memulihkan percakapan",
               "percobaan": []}
    pesan_console: list[str] = []
    pg.on("console", lambda m: pesan_console.append(f"[{m.type}] {m.text[:200]}"))
    try:
        for attempt in range(1, 4):
            # Chat baru supaya giliran sebelumnya tidak mengganggu. Penanda
            # dihapus SEBELUM navigasi: effect pemulihan berjalan saat mount,
            # jadi menghapusnya sesudah navigasi sudah terlambat (effect sudah
            # memulihkan sesi lama) dan percobaan jadi tidak sah.
            pg.evaluate("() => { try { localStorage.removeItem('katalir.pendingTurn.v1'); } catch(e){} }")
            goto(pg, "/chat", ms=2500)
            dismiss_onboarding(pg)
            pg.wait_for_timeout(600)
            url_bersih = "?s=" not in pg.url
            ta = pg.locator(COMPOSER).first
            ta.click(timeout=15000)
            ta.fill("")
            ta.fill(f"VERIFY-B202 percobaan {attempt} tolong sebutkan satu kata saja")
            t_enter = time.time()
            ta.press("Enter")

            # Satu poll 250 ms: kalau sesi sudah terikat -> jendela terlewat.
            pg.wait_for_timeout(250)
            sudah_terikat = "?s=" in pg.url
            percobaan = {"attempt": attempt,
                         "url_bersih_sebelum_kirim": url_bersih,
                         "terikat_dalam_250ms": sudah_terikat,
                         "url": pg.url}
            r["percobaan"].append(percobaan)
            if sudah_terikat or not url_bersih:
                percobaan["hasil"] = "dibuang (jendela mid-generation terlewat)"
                continue

            # Mid-flight terkonfirmasi. Catat keadaan lalu refresh.
            r["url_sebelum_refresh"] = pg.url
            r["ada_sesi_di_url_sebelum"] = False
            r["penanda_ls_sebelum"] = pg.evaluate(
                "() => localStorage.getItem('katalir.pendingTurn.v1')")
            percobaan["penanda_ada"] = bool(r["penanda_ls_sebelum"])
            shot(pg, f"verify-bug02-sebelum-refresh-{attempt}")

            pg.reload(wait_until="domcontentloaded", timeout=60000)
            terpulih = False
            for _ in range(40):
                pg.wait_for_timeout(1000)
                if "VERIFY-B202" in msglist_text(pg):
                    terpulih = True
                    break
            r["url_setelah_refresh"] = pg.url
            r["ada_sesi_di_url_setelah"] = "?s=" in pg.url
            r["penanda_terlihat"] = terpulih
            r["panjang_area_chat"] = len(msglist_text(pg))
            r["penanda_ls_setelah"] = pg.evaluate(
                "() => localStorage.getItem('katalir.pendingTurn.v1')")
            r["console_pemulihan"] = [x for x in pesan_console
                                      if "katalir" in x.lower()][:6]
            percobaan["hasil"] = "GREEN" if terpulih else "RED"
            r["state"] = "GREEN" if terpulih else "RED"
            shot(pg, f"verify-bug02-sesudah-refresh-{attempt}")
            break
        else:
            r["state"] = "NOT_RUN"
            r["catatan"] = ("3 percobaan semuanya melewatkan jendela "
                            "mid-generation (sesi sudah terikat dalam 250 ms)")
    except Exception as exc:  # noqa: BLE001
        r["state"] = "ERROR"
        r["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        ctx.close()
    print(f"  BUG-02: {r.get('state')}  url_setelah={str(r.get('url_setelah_refresh'))[-40:]} "
          f"panjang={r.get('panjang_area_chat')} percobaan={len(r['percobaan'])}", flush=True)
    return r


def check_bug06(b) -> dict:
    """Pesan galat pendaftaran harus bisa ditindaklanjuti (bukan teks mentah).

    Batas 2 email/jam pada pengirim bawaan Supabase TIDAK bisa diubah tanpa
    Management API (`SUPABASE_ACCESS_TOKEN`). Yang diuji di sini adalah lapisan
    yang bisa diperbaiki aplikasi: user tidak boleh melihat pesan mentah
    berbahasa Inggris tanpa jalan keluar.
    """
    ctx = new_ctx(b)
    if LOCAL:
        proxy_backend(ctx)
    pg = ctx.new_page()
    r: dict = {"nama": "BUG-06 pesan galat pendaftaran bisa ditindaklanjuti"}
    try:
        goto(pg, "/", ms=3000)
        cta = pg.locator('[data-testid="landing-signin-trigger"]')
        # Modal kadang belum terbuka pada klik pertama (CTA baru ter-hydrate);
        # coba lagi sebelum menyatakan gagal.
        for _ in range(3):
            try:
                cta.first.click(timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            try:
                pg.wait_for_selector('[data-testid="login-email"]', timeout=12000)
                break
            except Exception:  # noqa: BLE001
                pg.wait_for_timeout(1500)
        pg.wait_for_timeout(800)
        tg = pg.locator('[data-testid="login-toggle-mode"]')
        if tg.count() and tg.first.is_visible():
            tg.first.click(timeout=6000)
            pg.wait_for_timeout(1200)
        email = f"verify.b06.{uuid.uuid4().hex[:8]}@example.com"
        pg.fill('[data-testid="login-email"]', email)
        pg.fill('[data-testid="login-password"]', "Rs-" + uuid.uuid4().hex[:12] + "!7")
        shot(pg, "verify-bug06-form")
        pg.locator('[data-testid="login-submit"]').first.click(timeout=8000)
        pg.wait_for_timeout(9000)
        err = ""
        if pg.locator('[data-testid="login-error"]').count():
            err = pg.locator('[data-testid="login-error"]').first.inner_text().strip()
        notice = ""
        if pg.locator('[data-testid="login-notice"]').count():
            notice = pg.locator('[data-testid="login-notice"]').first.inner_text().strip()
        r["pesan_dilihat_user"] = err or notice
        r["masih_bahasa_inggris_mentah"] = (
            "rate limit" in (err or "").lower()
            or "invalid" in (err or "").lower()
        )
        r["menyebut_jalan_keluar"] = "Google" in (err or "") or "GitHub" in (err or "")
        r["state"] = "GREEN" if (err and not r["masih_bahasa_inggris_mentah"]
                                 and r["menyebut_jalan_keluar"]) else "RED"
        shot(pg, "verify-bug06-sesudah")
    except Exception as exc:  # noqa: BLE001
        r["state"] = "ERROR"
        r["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        ctx.close()
    print(f"  BUG-06: {r['state']}  pesan={r.get('pesan_dilihat_user','')[:90]!r}", flush=True)
    return r


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    print(f"verifikasi terhadap {FRONTEND} (lokal={LOCAL})", flush=True)
    out["checks"]["bug01"] = check_bug01(b)
    out["checks"]["bug02"] = check_bug02(b)
    out["checks"]["bug06"] = check_bug06(b)
    b.close()

out["ringkas"] = {k: v["state"] for k, v in out["checks"].items()}
print("\nRINGKASAN:", json.dumps(out["ringkas"], ensure_ascii=False), flush=True)
(HERE / "_verify_fixes.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {HERE / '_verify_fixes.json'}", flush=True)
