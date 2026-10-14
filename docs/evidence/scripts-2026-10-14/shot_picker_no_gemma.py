"""Screenshot + bukti DOM: picker model produksi TIDAK lagi menawarkan gemma.

Kenapa lewat browser dan bukan hanya `GET /models`: picker bisa saja masih
menampilkan entri dari daftar fallback lokal, jadi bukti harus dari DOM yang
sudah ter-hydrate. (Aturan proyek: verifikasi rute/DOM tidak sah dari HTML
mentah — payload RSC bisa menyesatkan.)

Keluaran:
  docs/evidence/models-picker-2026-10-14/picker.png
  docs/evidence/models-picker-2026-10-14/picker.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")

HERE = pathlib.Path(__file__).resolve().parent


def _repo_root() -> pathlib.Path:
    for cand in [HERE, *HERE.parents]:
        if (cand / "tests" / "user_test" / "rus_core.py").exists():
            return cand
    raise SystemExit("repo root tidak ditemukan")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "tests" / "user_test"))

from rus_core import (REF, dismiss_onboarding, drop_user, goto, login,  # noqa: E402
                      make_user, new_ctx, sb_session_payload)

OUT = ROOT / "docs" / "evidence" / "models-picker-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

MUST_ABSENT = "gemma"
#: Id/teks yang harus ADA supaya screenshot bermakna (bukan dropdown kosong).
MUST_PRESENT = "flash"

u = make_user("shot-picker")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
print(f"akun uji: {u['email']}")

from playwright.sync_api import sync_playwright  # noqa: E402

hasil: dict = {"email": u["email"]}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = new_ctx(b)
        pg = ctx.new_page()

        # Rekam /models yang benar-benar diterima browser (bukti end-to-end).
        models_payload: list = []

        def _on_resp(r):  # noqa: ANN001
            if "/models" in r.url and r.status == 200:
                try:
                    models_payload.append(r.json())
                except Exception:  # noqa: BLE001
                    pass

        pg.on("response", _on_resp)

        login(pg, sb_session_payload(u["session"], REF))
        goto(pg, "/chat", ms=3500)
        # `login()` sudah menutup wizard, tetapi navigasi KEDUA memunculkannya
        # lagi (wizard muncul per kunjungan /chat pada sesi baru). Tanpa ini,
        # dialog `[data-testid="onboarding-flow"]` menelan klik picker
        # (`intercepts pointer events`) dan skrip mati dengan TimeoutError.
        dismiss_onboarding(pg)
        pg.wait_for_timeout(1200)

        sel = pg.locator('[data-testid="model-selector"]')
        sel.wait_for(state="visible", timeout=20000)
        label_sebelum = (sel.inner_text() or "").strip()

        sel.click()
        pg.wait_for_selector('[role="menuitem"]', timeout=15000)
        pg.wait_for_timeout(1200)

        items = pg.locator('[role="menuitem"]')
        n = items.count()
        names: list[str] = []
        for i in range(n):
            t = (items.nth(i).inner_text() or "").strip().replace("\n", " | ")
            if t:
                names.append(t)

        menu_text = (pg.locator('[data-radix-menu-content]').inner_text() or "")
        shot_path = OUT / "picker.png"
        pg.screenshot(path=str(shot_path), full_page=False)

        hasil.update({
            "label_tombol": label_sebelum,
            "jumlah_item": n,
            "item_texts": names,
            "menu_text": menu_text,
            "gemma_terlihat": MUST_ABSENT in menu_text.lower(),
            "flash_terlihat": MUST_PRESENT in menu_text.lower(),
            "models_payload_count": len(models_payload),
            "models_ids": sorted({m.get("id") for m in (models_payload[-1].get("models") or [])})
            if models_payload else [],
            "not_offered_filtered": (models_payload[-1].get("not_offered_filtered")
                                     if models_payload else None),
            "screenshot": str(shot_path),
        })

        print(f"label tombol       : {label_sebelum!r}")
        print(f"jumlah item picker : {n}")
        for t in names:
            print(f"   - {t}")
        print(f"gemma terlihat     : {hasil['gemma_terlihat']}")
        print(f"flash terlihat     : {hasil['flash_terlihat']}")
        print(f"not_offered_filtered: {hasil['not_offered_filtered']}")

        ok = (not hasil["gemma_terlihat"]) and hasil["flash_terlihat"] and n >= 3
        hasil["ok"] = ok
        print(f"\nHASIL: {'PASS' if ok else 'FAIL'}")
finally:
    (OUT / "picker.json").write_text(
        json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
    if u.get("id"):
        drop_user(u["id"])
        print(f"akun uji dihapus: {u['email']}")

raise SystemExit(0 if hasil.get("ok") else 1)
