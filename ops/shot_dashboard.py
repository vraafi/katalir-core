#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ambil screenshot dashboard monitoring produksi.

Dashboard = data LIVE dari produksi (bukan mock): `/status`, `/health`,
`/version`. Nilainya diambil lewat HTTP, disuntikkan ke halaman HTML, lalu
dirender Playwright dan disimpan sebagai PNG.

Jalankan dari root repo:
    PLAYWRIGHT_BROWSERS_PATH=D:/caches/playwright \
      "C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe" \
      ops/shot_dashboard.py
"""
from __future__ import annotations

import html
import json
import pathlib
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
API = "https://gateway.katalir.de5.net/katalir-api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
OUT = DOCS / "monitoring-dashboard-2026-10-11.png"


def get(path: str, timeout: int = 25):
    req = urllib.request.Request(f"{API}{path}",
                                 headers={"User-Agent": UA, "Accept": "*/*"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", time.time() - t0


def card(title, status, latency, body, good):
    color = "#16a34a" if good else "#dc2626"
    try:
        pretty = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pretty = body
    return f"""
    <div class="card">
      <div class="head">
        <span class="dot" style="background:{color}"></span>
        <span class="title">{html.escape(title)}</span>
        <span class="meta">HTTP {status} · {latency*1000:.0f} ms</span>
      </div>
      <pre>{html.escape(pretty[:1800])}</pre>
    </div>"""


def main() -> int:
    rows = []
    s_status, b_status, t_status = get("/status")
    s_health, b_health, t_health = get("/health")
    s_ver, b_ver, t_ver = get("/version")
    rows.append(card("GET /status — deep health (backend + supabase + gateway)",
                     s_status, t_status, b_status, s_status == 200))
    rows.append(card("GET /health — liveness + persistence", s_health, t_health,
                     b_health, s_health == 200))
    rows.append(card("GET /version — commit & fitur", s_ver, t_ver, b_ver,
                     s_ver == 200))

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    page_html = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8"><title>Katalir — Monitoring</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0b1020; color:#e5e7eb;
         font-family: "Segoe UI", system-ui, sans-serif; padding:28px 32px; }}
  h1 {{ margin:0 0 4px; font-size:22px; letter-spacing:.2px; }}
  .sub {{ color:#94a3b8; font-size:13px; margin-bottom:22px; }}
  .sub code {{ color:#93c5fd; }}
  .grid {{ display:grid; grid-template-columns:1fr; gap:16px; }}
  .card {{ background:#111a2e; border:1px solid #1f2b45; border-radius:12px;
           padding:14px 16px; }}
  .head {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }}
  .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
  .title {{ font-size:14px; font-weight:600; flex:1; }}
  .meta {{ font-size:12px; color:#94a3b8; font-variant-numeric: tabular-nums; }}
  pre {{ margin:0; background:#0a1120; border:1px solid #1b2740; border-radius:8px;
         padding:12px; font-size:12px; line-height:1.5; color:#cbd5e1;
         white-space:pre-wrap; word-break:break-word; max-height:230px; overflow:hidden; }}
  .foot {{ margin-top:20px; color:#64748b; font-size:12px; }}
</style></head>
<body>
  <h1>Katalir — Dashboard Monitoring</h1>
  <div class="sub">Diambil langsung dari produksi <code>{html.escape(API)}</code>
    pada <b>{stamp}</b> (waktu lokal pengambil).</div>
  <div class="grid">{''.join(rows)}</div>
  <div class="foot">Sumber: <code>/status</code>, <code>/health</code>,
    <code>/version</code> · auto-recovery: systemd <code>Restart=always</code>
    (<code>RestartUSec=10s</code>, <code>StartLimitBurst=5</code>) + watchdog 60 s.</div>
</body></html>"""

    tmp = ROOT / "_dashboard_tmp.html"
    tmp.write_text(page_html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": 1180, "height": 940},
                           device_scale_factor=2).new_page()
        pg.goto(tmp.as_uri(), wait_until="load")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT), full_page=True)
        b.close()
    tmp.unlink(missing_ok=True)

    print(f"status={s_status} health={s_health} version={s_ver}")
    print("screenshot:", OUT, OUT.stat().st_size, "bytes")
    return 0 if s_status == 200 and s_health == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
