"""TASK 3 - MOBILE USER TEST (Katalir, 12 Okt 2026).

Viewport wajib: 375x667 (iPhone SE). Tambahan: 320, 768, 1440.

Yang diperiksa (bukan diklaim):
  * composer terlihat dan dapat diklik pada tiap viewport
  * composer TIDAK tertutup elemen lain (dicek lewat elementFromPoint di tengah
    composer - bukan sekadar `is_visible()`)
  * overflow horizontal (apakah ada scrollbar X yang tidak seharusnya)
  * ukuran target sentuh tombol utama (>=44px = pedoman iOS/Android)
  * kirim pesan nyata dari viewport mobile

Keluaran: tests/user_test/_mobile_results.json + screenshot per viewport.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
SHOTS = ROOT / "docs" / "evidence" / "user-test"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONTEND = "https://katalir.de5.net"
SESS = json.loads((UT / "_session.json").read_text(encoding="utf-8"))

from playwright.sync_api import sync_playwright  # noqa: E402

VIEWPORTS = [
    ("320x568", 320, 568, "iPhone 5/SE kecil"),
    ("375x667", 375, 667, "iPhone SE (WAJIB)"),
    ("768x1024", 768, 1024, "iPad portrait"),
    ("1440x900", 1440, 900, "desktop"),
]

results: list[dict] = []

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    for label, w, h, desc in VIEWPORTS:
        ctx = b.new_context(
            viewport={"width": w, "height": h}, locale="id-ID",
            is_mobile=(w < 700), has_touch=(w < 700),
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1")
            if w < 700 else None)
        pg = ctx.new_page()
        errs: list = []
        pg.on("console", lambda m: errs.append({"t": m.type, "x": m.text[:160]})
              if m.type in ("error", "pageerror") else None)
        pg.on("pageerror", lambda e: errs.append({"t": "pageerror", "x": str(e)[:160]}))

        r: dict = {"viewport": label, "w": w, "h": h, "desc": desc}
        try:
            t0 = time.time()
            pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
            pg.evaluate("([k,v]) => { try { localStorage.setItem(k,v); } catch(e){} }",
                        [SESS["storage_key"], json.dumps(SESS["session"])])
            pg.reload(wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(4000)
            r["load_s"] = round(time.time() - t0, 2)

            # tutup wizard bila muncul
            for lbl in ("Lewati", "Tutup"):
                try:
                    el = pg.get_by_role("button", name=lbl, exact=False)
                    if el.count() and el.first.is_visible():
                        el.first.click(timeout=3000)
                        pg.wait_for_timeout(900)
                        break
                except Exception:  # noqa: BLE001
                    pass

            ta = pg.locator("textarea").first
            r["composer_exists"] = ta.count() > 0
            r["composer_visible"] = ta.is_visible() if ta.count() else False

            # Apakah composer benar-benar bisa disentuh (bukan tertutup)?
            if ta.count():
                box = ta.bounding_box()
                r["composer_box"] = box
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    r["composer_in_viewport"] = (
                        0 <= box["y"] and box["y"] + box["height"] <= h + 1)
                    top = pg.evaluate(
                        """([x,y]) => {
                             const e = document.elementFromPoint(x,y);
                             return e ? (e.tagName + '.' + (e.className||'').toString().slice(0,40)) : null;
                           }""", [cx, cy])
                    r["element_at_composer_center"] = top
                    r["composer_clickable"] = bool(
                        top and ("TEXTAREA" in top or "textarea" in top.lower()))

            # overflow horizontal
            r["scroll_w"] = pg.evaluate("document.documentElement.scrollWidth")
            r["client_w"] = pg.evaluate("document.documentElement.clientWidth")
            r["h_overflow_px"] = r["scroll_w"] - r["client_w"]

            # ukuran target sentuh tombol utama
            targets = []
            for el in pg.locator("button").all():
                try:
                    if el.is_visible():
                        bb = el.bounding_box()
                        if bb and bb["width"] > 0:
                            targets.append({"text": (el.inner_text() or "").strip()[:24],
                                            "w": round(bb["width"]),
                                            "h": round(bb["height"])})
                except Exception:  # noqa: BLE001
                    pass
            small = [t for t in targets if t["h"] < 44 and t["w"] < 44]
            r["buttons_total"] = len(targets)
            r["buttons_under_44"] = len(small)
            r["sample_small"] = small[:4]

            # kirim pesan nyata dari viewport ini
            if r.get("composer_visible"):
                try:
                    ta.click(timeout=8000)
                    ta.fill("tes mobile")
                    t1 = time.time()
                    ta.press("Enter")
                    pg.wait_for_timeout(25000)
                    r["send_s"] = round(time.time() - t1, 2)
                    body = pg.inner_text("body")
                    r["send_reply_present"] = "tes mobile" in body and len(body) > 800
                    r["send_body_len"] = len(body)
                except Exception as exc:  # noqa: BLE001
                    r["send_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"

            pg.screenshot(path=str(SHOTS / f"mobile-{label}.png"), full_page=True)
            r["screenshot"] = str(SHOTS / f"mobile-{label}.png")
            r["console_errors"] = errs[:6]
        except Exception as exc:  # noqa: BLE001
            r["fatal"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        results.append(r)
        print(f"  {label:<9} composer={r.get('composer_visible')} "
              f"clickable={r.get('composer_clickable')} "
              f"in_viewport={r.get('composer_in_viewport')} "
              f"hOverflow={r.get('h_overflow_px')}px "
              f"btn<44={r.get('buttons_under_44')}/{r.get('buttons_total')} "
              f"send={r.get('send_s')}s reply={r.get('send_reply_present')}",
              flush=True)
        ctx.close()
    b.close()

(UT / "_mobile_results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {UT / '_mobile_results.json'}")
