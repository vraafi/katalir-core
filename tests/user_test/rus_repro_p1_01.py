"""Reproduksi terarah untuk temuan P1-01 (pesan hilang setelah refresh 3 detik).

Tujuan: MEMBEDAKAN dua kemungkinan yang secara gejala identik —
  (A) pesan user TIDAK tersimpan di server (kehilangan data nyata), atau
  (B) pesan tersimpan, tetapi setelah refresh UI membuka chat KOSONG sehingga
      user menyimpulkan pesannya hilang (cacat pemulihan/UX).

Cara membedakan tanpa akses DB: judul item sidebar berasal dari pesan pertama
sesi. Bila setelah refresh muncul item sidebar yang judulnya = penanda kita,
maka pesannya TERSIMPAN (B). Bila tidak ada, kemungkinan (A).

Keluaran: tests/user_test/_rus_repro_p1_01.json + screenshot.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import uuid

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from playwright.sync_api import sync_playwright  # noqa: E402

from rus_core import (COMPOSER, EV, Probe, dismiss_onboarding, goto,  # noqa: E402
                      login, msg_text, msglist_text, new_ctx, shot,
                      sidebar_text)
from rus_personas import session_items  # noqa: E402

MARK = "REPRO-P101-" + uuid.uuid4().hex[:6]
out = {"marker": MARK, "steps": []}


def log(step, **kw):
    out["steps"].append({"step": step, **kw})
    print(f"  {step}: {json.dumps(kw, ensure_ascii=False)[:300]}", flush=True)


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = new_ctx(b)
    pg = ctx.new_page()
    pr = Probe(pg, "repro")
    login(pg)

    goto(pg, "/chat", ms=3000)
    dismiss_onboarding(pg)
    before = session_items(pg)
    log("sidebar_sebelum", n=before["n"])

    ta = pg.locator(COMPOSER).first
    ta.click(timeout=15000)
    ta.fill(f"{MARK} buat workflow inventory")
    ta.press("Enter")
    t_send = time.time()
    log("terkirim", marker=MARK)

    pg.wait_for_timeout(3000)                       # user tidak sabar
    shot(pg, "repro-p101-01-sebelum-refresh")
    url_before = pg.url

    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(6000)
    shot(pg, "repro-p101-02-setelah-refresh")
    # PENTING: pakai msglist_text (area percakapan SAJA), bukan msg_text yang
    # jatuh ke <body>. Judul sesi di sidebar memuat penanda, sehingga fallback
    # itu membuat "pesan tampil di layar" terbaca True padahal area percakapan
    # kosong.
    chat = msglist_text(pg)
    side = sidebar_text(pg)
    after = session_items(pg)
    marker_di_chat = MARK in chat
    marker_in_sidebar = any(MARK in (t or "") for t in after["titles"]) or \
        MARK in side
    log("setelah_refresh", url=pg.url, panjang_area_chat=len(chat),
        marker_di_chat=marker_di_chat, marker_di_sidebar=marker_in_sidebar,
        sidebar_n=after["n"], judul_teratas=after["titles"][:3])

    # bila area percakapan kosong, coba buka percakapan teratas (perilaku user)
    opened = False
    marker_setelah_buka = False
    if not marker_di_chat and after["n"]:
        try:
            pg.evaluate("""() => {
              const as = document.querySelector('aside');
              const bs = [...as.querySelectorAll('button')]
                .filter(b => (b.innerText || '').trim().length > 1);
              if (bs.length) bs[0].click();
            }""")
            pg.wait_for_timeout(7000)
            shot(pg, "repro-p101-03-buka-item-teratas")
            chat2 = msglist_text(pg)
            marker_setelah_buka = MARK in chat2
            opened = True
            log("setelah_buka_item", panjang_area_chat=len(chat2),
                marker_di_chat=marker_setelah_buka)
        except Exception as exc:  # noqa: BLE001
            log("buka_item_gagal", err=f"{type(exc).__name__}: {exc}")

    if not marker_in_sidebar:
        verdict = "A: pesan TIDAK tersimpan di server (kehilangan data)"
    elif marker_di_chat:
        verdict = "C: pesan tersimpan DAN tampil di area percakapan (bukan bug)"
    elif marker_setelah_buka:
        verdict = ("B: pesan tersimpan, tetapi setelah refresh user dibiarkan "
                   "di chat kosong — baru tampil setelah membuka sesi dari sidebar")
    else:
        verdict = ("B: pesan tersimpan di server (terlihat di sidebar), tetapi "
                   "area percakapan tetap kosong setelah refresh maupun setelah "
                   "membuka sesinya")
    out["verdict"] = verdict
    out["elapsed_to_refresh_s"] = round(time.time() - t_send, 2)
    out["url_sebelum_refresh"] = url_before
    out["marker_di_area_chat_setelah_reload"] = marker_di_chat
    out["marker_di_sidebar_setelah_reload"] = marker_in_sidebar
    out["marker_muncul_setelah_buka_sesi"] = marker_setelah_buka
    out["console_errors"] = pr.errs()[:10]
    out["failed_requests"] = pr.netfail[:10]
    print("\nVERDICT:", verdict, flush=True)

    (HERE / "_rus_repro_p1_01.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"bukti -> {HERE / '_rus_repro_p1_01.json'}", flush=True)
    ctx.close()
    b.close()
