"""Reproduksi B-09 dan identifikasi DUA galat konsol 404 yang menyebabkannya FAIL.

B-09 memanggil `pr.reset()` lalu `goto(pg, "/chat")` dan mengklik
`[data-testid="theme-toggle"]` 6x; syarat PASS = `len(pr.errs()) == 0`.
Rekaman harness hanya menyimpan TEKS galat ("Failed to load resource: ... 404")
tanpa URL, sehingga penyebabnya harus direproduksi ulang di sini dengan
menangkap URL + status setiap respons.

Keluaran: docs/evidence/prod-verify-v4-2026-10-14/probe_b09.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tests" / "user_test"))

from rus_core import (REF, drop_user, goto, login, make_user,  # noqa: E402
                      new_ctx, sb_session_payload)

OUT = HERE / "docs" / "evidence" / "prod-verify-v4-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

u = make_user("probe-b09")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
print(f"akun uji: {u['email']}")

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = new_ctx(b)
    pg = ctx.new_page()

    bad: list[dict] = []
    konsol: list[dict] = []
    gagal: list[dict] = []

    pg.on("response", lambda r: bad.append({"status": r.status, "url": r.url})
          if r.status >= 400 else None)
    pg.on("console", lambda m: konsol.append({"type": m.type, "text": m.text[:200]})
          if m.type == "error" else None)
    pg.on("requestfailed", lambda r: gagal.append(
        {"url": r.url, "err": (r.failure or "")[:120]}))

    login(pg, sb_session_payload(u["session"], REF))
    goto(pg, "/chat", ms=3000)

    # --- mulai dari sini = setara pr.reset() di B-09 ---
    bad.clear(); konsol.clear(); gagal.clear()

    tg = pg.locator('[data-testid="theme-toggle"]')
    n = 0
    for _ in range(6):
        if tg.count():
            try:
                tg.first.click(timeout=4000)
                n += 1
            except Exception:  # noqa: BLE001
                pass
        pg.wait_for_timeout(300)
    pg.wait_for_timeout(1500)

    bg = pg.evaluate("() => getComputedStyle(document.body).backgroundColor")
    png = OUT / "probe_b09.png"
    pg.screenshot(path=str(png), full_page=True)

    hasil = {
        "user": u["email"],
        "klik_berhasil": n,
        "warna_latar_body": bg,
        "jumlah_galat_konsol": len(konsol),
        "galat_konsol": konsol,
        "respons_4xx_5xx": bad,
        "permintaan_gagal": gagal,
        "screenshot": str(png),
    }
    print(json.dumps(hasil, ensure_ascii=False, indent=1))
    ctx.close()
    b.close()

drop_user(u["id"])
(OUT / "probe_b09.json").write_text(
    json.dumps(hasil, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {OUT / 'probe_b09.json'}")
