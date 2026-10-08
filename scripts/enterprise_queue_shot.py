# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_queue_shot.py
# Prasyarat: server uvicorn lokal di port 8123 DENGAN QUEUE_WORKERS=0
# (supaya job menumpuk di antrian -> depth > 0 terlihat di UI).
"""Screenshot dashboard Queue Mode (bukti visual Fitur #6).

Alur:
  1. seed job ke antrian lewat API (campur prioritas tinggi/normal)
  2. buka /queue/ui di Chromium (Playwright), token disuntik ke localStorage
     SEBELUM skrip halaman berjalan
  3. tunggu angka depth > 0, lalu screenshot full-page
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8123"
OUT = "docs/evidence/f06-queue-dashboard.png"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = open(".autonomous_jwt", encoding="utf-8").read().strip()


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOK}"})
    try:
        r = OPENER.open(req, timeout=30)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# --- 0. tunggu server siap -------------------------------------------------
for _ in range(90):
    try:
        OPENER.open(BASE + "/health", timeout=3)
        break
    except Exception:  # noqa: BLE001
        time.sleep(1)

# --- 1. seed job -----------------------------------------------------------
ok = 0
for i in range(60):
    st, _ = api("POST", "/queue/enqueue", {
        "workflow_id": "demo-queue",
        "flow_data": {"n": i},
        "trigger_input": {},
        "priority": 10 if i % 10 == 0 else 0,
    })
    ok += 1 if st == 200 else 0
print("seed job:", ok, "job masuk antrian")

st, body = api("GET", "/queue/workers")
print("workers:", st, body[:220])

# --- 2. screenshot ---------------------------------------------------------
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 1100},
                              device_scale_factor=2)
    ctx.add_init_script(
        f"try{{localStorage.setItem('katalir_token', {json.dumps(TOK)});}}catch(e){{}}")
    page = ctx.new_page()
    page.goto(BASE + "/queue/ui", wait_until="networkidle", timeout=60000)
    page.wait_for_function(
        "() => parseInt(document.getElementById('s-ready').textContent) > 0",
        timeout=30000)
    page.wait_for_timeout(900)
    os.makedirs("docs/evidence", exist_ok=True)
    page.screenshot(path=OUT, full_page=True)
    print("s-ready  :", page.inner_text("#s-ready"))
    print("s-dlq    :", page.inner_text("#s-dlq"))
    print("s-workers:", page.inner_text("#s-workers"))
    print("backend  :", page.inner_text("#backend"))
    print("server   :", page.inner_text("#server"))
    browser.close()

print("SCREENSHOT:", OUT, os.path.getsize(OUT), "bytes")
