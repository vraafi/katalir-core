"""Apakah sesi user nyata (JWT dari .autonomous_jwt) membuka /chat?

Menguji persis seperti user yang sudah login: token disimpan di localStorage
(kunci yang sama dipakai E2E sebelumnya), lalu reload dan periksa composer.
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
SHOTS = ROOT / "docs" / "evidence" / "user-test"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONTEND = "https://katalir.de5.net"

TOK = (ROOT / ".autonomous_jwt").read_text(encoding="utf-8").strip()

from playwright.sync_api import sync_playwright  # noqa: E402

out: dict = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="id-ID")
    pg = ctx.new_page()
    errs: list = []
    pg.on("console", lambda m: errs.append({"t": m.type, "x": m.text[:200]})
          if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errs.append({"t": "pageerror", "x": str(e)[:200]}))
    calls: list = []
    pg.on("response", lambda r: calls.append(
        {"u": r.url[:150], "s": r.status})
        if "/_next/" not in r.url and "cdn-cgi" not in r.url else None)

    pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
    pg.evaluate(
        "t => { try { localStorage.setItem('token', t);"
        " localStorage.setItem('access_token', t);"
        " localStorage.setItem('sb-access-token', t); } catch(e){} }", TOK)
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)

    ph = pg.locator("textarea").first.get_attribute("placeholder")
    out["placeholder"] = ph
    out["composer_locked"] = "masuk" in (ph or "").lower()
    out["buttons"] = [ (x.inner_text() or "").strip()[:40]
                       for x in pg.locator("button").all() if x.is_visible() ]
    out["body_head"] = pg.inner_text("body")[:500]
    pg.screenshot(path=str(SHOTS / "probe-logged-in-chat.png"), full_page=True)
    out["console"] = errs[:10]
    out["calls"] = calls[:14]
    b.close()

print(json.dumps(out, ensure_ascii=False, indent=1)[:2600])
