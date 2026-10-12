"""Verifikasi: sesi Supabase asli membuka /chat untuk user nyata."""
from __future__ import annotations

import json
import os
import pathlib

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
S = json.loads((ROOT / "tests" / "user_test" / "_session.json").read_text(
    encoding="utf-8"))
SHOTS = ROOT / "docs" / "evidence" / "user-test"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONTEND = "https://katalir.de5.net"

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="id-ID")
    pg = ctx.new_page()
    pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
    pg.evaluate(
        "([k,v]) => { try { localStorage.setItem(k, v); } catch(e){} }",
        [S["storage_key"], json.dumps(S["session"])])
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(5000)
    ph = pg.locator("textarea").first.get_attribute("placeholder")
    print("placeholder :", ph)
    print("terkunci    :", "masuk" in (ph or "").lower())
    print("buttons     :", [(x.inner_text() or "").strip()[:34]
                            for x in pg.locator("button").all() if x.is_visible()])
    body = pg.inner_text("body")
    print("body head   :", body[:300].replace("\n", " | "))
    pg.screenshot(path=str(SHOTS / "probe-session-chat.png"), full_page=True)
    b.close()
