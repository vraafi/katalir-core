"""Verifikasi browser produksi v4 — #3 (refresh saat generasi) + #9 (footer model).

Sekaligus PROBE B-09: menghitung permintaan RSC prefetch (`*.txt?_rsc=`) yang
404, untuk membuktikan penyebab kegagalan B-09 di regresi (dua galat konsol)
alih-alih menebak.

Keluaran: docs/evidence/prod-verify-v4-2026-10-14/prod_browser.json + .png
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tests" / "user_test"))

from rus_core import (REF, dismiss_onboarding, drop_user, goto,  # noqa: E402
                      inject_session, make_user, msg_text, new_ctx,
                      sb_session_payload, send_measured, settle,
                      visible_error_card)

OUT = HERE / "docs" / "evidence" / "prod-verify-v4-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

PROMPT = "Berapa hasil 111+222? Jawab hanya angkanya."
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def buka_chat_bersih(pg, session_obj, timeout=25000):
    """Buka /chat dan pastikan wizard onboarding tertutup (modal z-50
    mengintersepsi klik composer -> pesan tidak pernah terkirim)."""
    goto(pg, "/chat", ms=2500)
    inject_session(pg, session_obj)
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    settle(pg, 3000)
    modal = '[data-testid="onboarding-flow"]'
    try:
        pg.wait_for_selector('[data-testid="onboarding-skip"]', timeout=timeout)
        pg.locator('[data-testid="onboarding-skip"]').first.click(timeout=8000)
    except Exception:  # noqa: BLE001
        dismiss_onboarding(pg)
    for _ in range(3):
        if pg.locator(modal).count() == 0:
            break
        try:
            pg.locator('[data-testid="onboarding-skip"]').first.click(timeout=5000)
        except Exception:  # noqa: BLE001
            pg.keyboard.press("Escape")
        settle(pg, 1200)
    return pg.locator(modal).count()


u = make_user("probe-prodbrowser")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
print(f"akun uji: {u['email']}")

from playwright.sync_api import sync_playwright  # noqa: E402

hasil: dict = {"user": u["email"], "prompt": PROMPT, "default_model": DEFAULT_MODEL}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = new_ctx(b)
    pg = ctx.new_page()

    # --- probe prefetch RSC (.txt?_rsc=) ----------------------------------
    rsc_404: list[str] = []

    def _on_resp(resp):
        u_ = resp.url
        if ".txt" in u_ and "_rsc=" in u_ and resp.status == 404:
            rsc_404.append(u_)

    pg.on("response", _on_resp)

    konsol: list[str] = []
    pg.on("console", lambda m: konsol.append(f"{m.type}: {m.text[:160]}")
          if m.type == "error" else None)

    sisa = buka_chat_bersih(pg, sb_session_payload(u["session"], REF))
    print(f"modal onboarding tersisa: {sisa}")

    # --- #9 footer model ---------------------------------------------------
    r = send_measured(pg, PROMPT, max_wait=100)
    body = msg_text(pg)
    err = visible_error_card(pg)

    # Baris metadata bubble AI: <span class="font-mono tracking-tight">.
    footers = pg.evaluate("""() => Array.from(document.querySelectorAll('span.font-mono'))
        .map(e => e.textContent.trim()).filter(Boolean)""")

    png = OUT / "prod_browser.png"
    pg.screenshot(path=str(png), full_page=True)

    hasil["check9_footer"] = {
        "status": r["status"],
        "footers": footers,
        "footer_menyebut_model_default": any(DEFAULT_MODEL in f for f in footers),
        "jawaban_333": "333" in body,
        "error_card": err,
        "spanduk_fallback": ("Kuota harian" in body or "tidak bisa dipakai" in body
                             or "tidak tersedia" in body or "Beralih ke" in body),
        "reply_tail": r["reply_tail"][-300:],
    }

    # --- #3 refresh saat generasi -----------------------------------------
    ctx2 = new_ctx(b)
    pg2 = ctx2.new_page()
    buka_chat_bersih(pg2, sb_session_payload(u["session"], REF))
    pg2.locator('[data-testid="composer-input"], textarea').first.fill(
        "Tulis satu paragraf pendek tentang kopi.")
    pg2.locator('[data-testid="composer-input"], textarea').first.press("Enter")
    settle(pg2, 3000)          # biarkan generasi berjalan
    pg2.reload(wait_until="domcontentloaded", timeout=60000)
    settle(pg2, 6000)          # beri waktu riwayat dimuat ulang
    body2 = msg_text(pg2)
    png2 = OUT / "prod_refresh.png"
    pg2.screenshot(path=str(png2), full_page=True)
    hasil["check3_refresh"] = {
        "prompt_masih_ada": "kopi" in body2.lower(),
        "ada_balasan": len(body2.strip()) > 120,
        "panjang_teks": len(body2),
        "ada_kartu_galat": "Gagal mengirim" in body2,
        "screenshot": str(png2),
    }

    # --- probe B-09 --------------------------------------------------------
    hasil["probe_prefetch_rsc"] = {
        "jumlah_404_txt_rsc": len(rsc_404),
        "contoh": rsc_404[:5],
        "galat_konsol": konsol[:6],
    }

    hasil["screenshot"] = str(png)
    ctx.close()
    ctx2.close()
    b.close()

drop_user(u["id"])
print(json.dumps(hasil, ensure_ascii=False, indent=1))
(OUT / "prod_browser.json").write_text(
    json.dumps(hasil, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {OUT / 'prod_browser.json'}")
