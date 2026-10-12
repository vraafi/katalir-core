"""Ekstrak konfigurasi Supabase publik (URL + anon key) dari bundle produksi.

Anon key MEMANG publik (dipakai browser). Kita hanya membacanya untuk bisa
membangun sesi user nyata di localStorage.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FRONTEND = "https://katalir.de5.net"

from playwright.sync_api import sync_playwright  # noqa: E402

scripts: list[str] = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on("response", lambda r: scripts.append(r.url)
          if r.url.endswith(".js") and "/_next/" in r.url else None)
    pg.goto(f"{FRONTEND}/chat", wait_until="networkidle", timeout=60000)
    pg.goto(f"{FRONTEND}/templates", wait_until="networkidle", timeout=60000)
    pg.goto(f"{FRONTEND}/builder", wait_until="networkidle", timeout=60000)
    b.close()

print(f"[extract] {len(scripts)} script unik")
found = {"supabase_url": None, "anon_key": None, "api_urls": set()}
import httpx  # noqa: E402

with httpx.Client(timeout=45.0, follow_redirects=True) as c:
    for u in dict.fromkeys(scripts):
        try:
            t = c.get(u).text
        except Exception:  # noqa: BLE001
            continue
        for m in re.findall(r"https://[a-z0-9]+\.supabase\.co", t):
            found["supabase_url"] = m
        for m in re.findall(r"(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\."
                            r"[A-Za-z0-9_\-]{10,})", t):
            found["anon_key"] = m
        for m in re.findall(r"https://[a-z0-9.\-]+\.(?:railway\.app|de5\.net|"
                            r"up\.railway\.app|onrender\.com|vercel\.app)", t):
            found["api_urls"].add(m)

found["api_urls"] = sorted(found["api_urls"])
out = {
    "supabase_url": found["supabase_url"],
    "anon_key_len": len(found["anon_key"]) if found["anon_key"] else 0,
    "anon_key_prefix": (found["anon_key"][:12] + "…") if found["anon_key"] else None,
    "api_urls": found["api_urls"],
    "scripts_scanned": len(scripts),
}
print(json.dumps(out, indent=1))
(ROOT / "tests" / "user_test" / "_supabase_cfg.json").write_text(
    json.dumps({"supabase_url": found["supabase_url"],
                "anon_key": found["anon_key"],
                "api_urls": found["api_urls"]}, indent=1), encoding="utf-8")
print("\nbukti -> tests/user_test/_supabase_cfg.json")
