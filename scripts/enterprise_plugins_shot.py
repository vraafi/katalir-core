# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_plugins_live.py
# Prasyarat: server uvicorn lokal di port 8123 + token dari
#   python scripts/autonomous_login.py  (atau mk_session.py)
"""Ambil screenshot UI marketplace plugin (bukti visual fitur #11).

Alur:
  1. seed beberapa plugin + satu pengajuan review lewat API (agar UI berisi)
  2. buka /plugins/ui di Chromium (Playwright) dengan token disuntik ke
     localStorage SEBELUM skrip halaman berjalan
  3. tunggu tabel terisi, lalu screenshot full-page
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8123"
OUT = "docs/evidence/f11-plugins-marketplace.png"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = open(".autonomous_jwt", encoding="utf-8").read().strip()


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOK}"})
    try:
        return OPENER.open(req, timeout=30).status
    except urllib.error.HTTPError as e:
        return e.code


# --- 0. tunggu server siap -------------------------------------------------
for _ in range(90):
    try:
        OPENER.open(BASE + "/health", timeout=3)
        break
    except Exception:  # noqa: BLE001
        time.sleep(1)

# --- 1. seed konten --------------------------------------------------------
seed = [
    ("acme.slack-notify", "1.2.0", ["notify", "log"], "Kirim notifikasi Slack"),
    ("acme.http-enrich", "2.0.1", ["http"], "Pengaya data dari REST API"),
    ("acme.kv-cache", "1.0.4", ["kv", "log"], "Cache key-value antar-node"),
    ("acme.audit-log", "0.9.2", ["log"], "Catat jejak audit workflow"),
]
for name, ver, caps, desc in seed:
    print("seed install", name,
          api("POST", "/plugins/install", {"manifest": {
              "name": name, "version": ver, "entry": "main:run",
              "capabilities": caps, "author": "Acme",
              "description": desc}}))
# satu pengajuan review yang masih pending
print("seed review", api("POST", "/plugins/reviews", {"manifest": {
    "name": "acme.vision-extract", "version": "1.0.0", "entry": "main:run",
    "capabilities": ["http", "kv"], "author": "Acme",
    "description": "Ekstraksi data dari gambar (menunggu review)"}}))
# satu pengajuan yang MELANGGAR (untuk memperlihatkan blokir di UI)
print("seed review pelanggar", api("POST", "/plugins/reviews", {"manifest": {
    "name": "acme.vault-reader", "version": "1.0.0", "entry": "main:run",
    "capabilities": ["secrets"], "author": "unknown"}}))

# --- 2. screenshot ---------------------------------------------------------
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                              device_scale_factor=2)
    ctx.add_init_script(
        f"try{{localStorage.setItem('katalir_token', {json.dumps(TOK)});}}catch(e){{}}")
    page = ctx.new_page()
    page.goto(BASE + "/plugins/ui", wait_until="networkidle", timeout=60000)
    # tunggu sampai tabel plugin benar-benar terisi (bukan placeholder)
    page.wait_for_function(
        "() => document.querySelectorAll('#rows tr').length > 1 && "
        "!document.querySelector('#rows .empty')", timeout=30000)
    page.wait_for_timeout(900)
    os.makedirs("docs/evidence", exist_ok=True)
    page.screenshot(path=OUT, full_page=True)
    print("rows:", page.eval_on_selector_all("#rows tr", "els=>els.length"))
    print("badge:", page.inner_text("#ver"))
    browser.close()

print("SCREENSHOT:", OUT, os.path.getsize(OUT), "bytes")
