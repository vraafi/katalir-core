"""TASK 4 — VERIFIKASI PRODUKSI setelah perbaikan API URL + CSP.

Membuktikan (bukan mengklaim) bahwa bundle produksi yang BARU benar-benar
menghubungi gateway.katalir.de5.net dan chat berhasil:

  4a. buka https://katalir.de5.net/chat (Playwright, sesi nyata)
  4b. kirim "halo"
  4c. ukur waktu sampai balasan muncul (target < 30 s)
  4d. refresh -> riwayat masih ada
  4e. screenshot
  +   bukti tambahan: host API yang benar-benar dipanggil (dari request log)
      dan host apa pun yang diblokir CSP

Keluaran: tests/user_test/_prod_verify.json + docs/evidence/user-test/prod-*.png
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

out: dict = {"frontend": FRONTEND, "prompt": "halo"}
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="id-ID")
    pg = ctx.new_page()

    console: list = []
    requests: list = []
    csp_blocked: list = []
    failed: list = []
    pg.on("console", lambda m: console.append({"t": m.type, "x": m.text[:220]})
          if m.type in ("error", "pageerror") else None)
    pg.on("pageerror", lambda e: console.append({"t": "pageerror", "x": str(e)[:220]}))
    pg.on("request", lambda r: requests.append(r.url[:180])
          if ("katalir" in r.url or "railway" in r.url) else None)
    pg.on("requestfailed", lambda r: failed.append(
        {"u": r.url[:170], "f": (r.failure or "")[:130]}))

    # 4a
    pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
    pg.evaluate("([k,v]) => { try { localStorage.setItem(k,v); } catch(e){} }",
                [SESS["storage_key"], json.dumps(SESS["session"])])
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    for lbl in ("Lewati", "Tutup"):
        try:
            el = pg.get_by_role("button", name=lbl, exact=False)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=3000)
                pg.wait_for_timeout(800)
                break
        except Exception:  # noqa: BLE001
            pass
    pg.screenshot(path=str(SHOTS / "prod-01-chat-terbuka.png"), full_page=True)

    ta = pg.locator("textarea").first
    out["composer_ada"] = ta.count() > 0
    before = pg.inner_text("body")

    # 4b + 4c
    t0 = time.time()
    ta.click(timeout=10000)
    ta.fill("halo")
    ta.press("Enter")
    reply_s = None
    deadline = time.time() + 40
    while time.time() < deadline:
        pg.wait_for_timeout(1000)
        body = pg.inner_text("body")
        # balasan = teks bertambah selain kata "halo" yang kita kirim
        if len(body) > len(before) + 60 and "Gagal mengirim" not in body:
            reply_s = round(time.time() - t0, 2)
            break
        if "Gagal mengirim" in body:
            break
    out["balasan_s"] = reply_s
    out["body_after_len"] = len(pg.inner_text("body"))
    out["gagal_mengirim"] = "Gagal mengirim" in pg.inner_text("body")
    out["body_tail"] = pg.inner_text("body")[-900:]
    pg.screenshot(path=str(SHOTS / "prod-02-chat-balasan.png"), full_page=True)

    # 4d — refresh, riwayat masih ada?
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(5000)
    body2 = pg.inner_text("body")
    out["history_after_refresh"] = ("halo" in body2.lower())
    out["history_body_len"] = len(body2)
    # kandidat item riwayat di sidebar
    items = pg.locator("[data-testid*='history'], aside li, aside button")
    out["sidebar_items"] = items.count()
    pg.screenshot(path=str(SHOTS / "prod-03-setelah-refresh.png"), full_page=True)

    # bukti host
    out["api_hosts_dipanggil"] = sorted({u.split("/katalir-api")[0] + "/katalir-api"
                                         for u in requests if "/katalir-api" in u}) or \
        sorted({u.split("?")[0] for u in requests})[:6]
    out["ada_railway_dipanggil"] = any("railway" in u for u in requests)
    out["csp_diblokir"] = [c["x"][:200] for c in console
                           if "Content Security Policy" in c.get("x", "")
                           or "Refused to connect" in c.get("x", "")][:5]
    out["console_errors"] = console[:8]
    out["request_failed"] = failed[:8]
    b.close()

out["gate_4a"] = bool(out.get("composer_ada"))
out["gate_4b"] = bool(out.get("balasan_s"))
out["gate_4c"] = bool(out.get("balasan_s") and out["balasan_s"] < 30)
out["gate_4d"] = bool(out.get("history_after_refresh"))
out["verdict"] = ("PASS" if all(out[k] for k in
                                ("gate_4a", "gate_4b", "gate_4c", "gate_4d"))
                  else "FAIL")

print("=" * 74)
print("VERIFIKASI PRODUKSI")
print("=" * 74)
for k in ("composer_ada", "balasan_s", "gagal_mengirim", "history_after_refresh",
          "sidebar_items", "ada_railway_dipanggil"):
    print(f"  {k:<24} : {out.get(k)}")
print(f"  api host dipanggil     : {out.get('api_hosts_dipanggil')}")
print(f"  diblokir CSP           : {len(out.get('csp_diblokir') or [])}")
print(f"  request gagal          : {len(out.get('request_failed') or [])}")
print(f"  body tail              : {out.get('body_tail','')[-260:]!r}")
print("-" * 74)
print(f"  4a composer   : {'PASS' if out['gate_4a'] else 'FAIL'}")
print(f"  4b balasan    : {'PASS' if out['gate_4b'] else 'FAIL'}")
print(f"  4c < 30s      : {'PASS' if out['gate_4c'] else 'FAIL'} ({out.get('balasan_s')}s)")
print(f"  4d riwayat    : {'PASS' if out['gate_4d'] else 'FAIL'}")
print(f"  VERDICT       : {out['verdict']}")
print("=" * 74)

(UT / "_prod_verify.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
print(f"bukti -> {UT / '_prod_verify.json'}")
