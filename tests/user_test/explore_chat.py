"""Eksplorasi /chat dari sudut pandang user: apa yang benar-benar terlihat.

Merekam SEMUA request yang gagal (URL, status, alasan) + error konsol +
waktu muat + elemen yang terlihat. Tidak mengarang; hanya mencatat.
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
OUT = ROOT / "tests" / "user_test"
SHOTS = ROOT / "docs" / "evidence" / "user-test"
OUT.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)
FRONTEND = "https://katalir.de5.net"

from playwright.sync_api import sync_playwright  # noqa: E402

rec: dict = {"failed_requests": [], "console_errors": [], "api_calls": []}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="id-ID")
    pg = ctx.new_page()

    def on_resp(r):
        try:
            u = r.url
            if "/_next/" in u or "cloudflareinsights" in u:
                return
            rec["api_calls"].append({"url": u[:180], "status": r.status,
                                     "method": r.request.method})
        except Exception:  # noqa: BLE001
            pass

    def on_fail(r):
        try:
            rec["failed_requests"].append({
                "url": r.url[:180], "method": r.request.method,
                "failure": (r.failure or "")[:200],
            })
        except Exception:  # noqa: BLE001
            pass

    pg.on("response", on_resp)
    pg.on("requestfailed", on_fail)
    pg.on("console", lambda m: rec["console_errors"].append(
        {"type": m.type, "text": m.text[:220]})
        if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: rec["console_errors"].append(
        {"type": "pageerror", "text": str(e)[:220]}))

    print("[chat] buka /chat")
    t0 = time.time()
    pg.goto(f"{FRONTEND}/chat", wait_until="networkidle", timeout=60000)
    rec["load_s"] = round(time.time() - t0, 2)

    pg.wait_for_timeout(3000)
    pg.screenshot(path=str(SHOTS / "explore-chat.png"), full_page=True)

    body = pg.inner_text("body")
    rec["chat_text_head"] = body[:800]
    rec["title"] = pg.title()

    # Inventaris elemen yang bisa dipakai user.
    rec["inputs"] = []
    for el in pg.locator("input, textarea").all():
        try:
            rec["inputs"].append({
                "tag": el.evaluate("e => e.tagName"),
                "type": el.get_attribute("type"),
                "placeholder": el.get_attribute("placeholder"),
                "visible": el.is_visible(),
                "aria": el.get_attribute("aria-label"),
            })
        except Exception:  # noqa: BLE001
            pass

    rec["buttons"] = []
    for el in pg.locator("button").all():
        try:
            if el.is_visible():
                rec["buttons"].append((el.inner_text() or "").strip()[:40])
        except Exception:  # noqa: BLE001
            pass

    rec["login_cta"] = pg.locator(
        "text=/masuk|login|sign in|daftar|sign up/i").count()
    rec["composer_visible"] = any(
        i.get("visible") for i in rec["inputs"])

    b.close()

print(json.dumps({k: v for k, v in rec.items()
                  if k not in ("chat_text_head", "api_calls")},
                 ensure_ascii=False, indent=1)[:2500])
print("\n--- 8 API call pertama ---")
for c in rec["api_calls"][:8]:
    print(f"  {c['status']} {c['method']} {c['url']}")
print(f"\n--- request gagal: {len(rec['failed_requests'])} ---")
for c in rec["failed_requests"][:6]:
    print(f"  {c['method']} {c['url']}  <-- {c['failure']}")

(OUT / "_explore_chat.json").write_text(
    json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nbukti -> {OUT / '_explore_chat.json'}")
