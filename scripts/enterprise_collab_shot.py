# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_collab_shot.py
# Prasyarat: internet (yjs + y-websocket dari esm.sh) & uvicorn lokal port 8123.
"""Screenshot editor kolaboratif (bukti visual Fitur #10).

Alur NYATA:
  1. buka /collab/ui di DUA konteks Chromium (dua user: Andi & Budi) yang
     memakai **Yjs sungguhan** (yjs + y-websocket dari esm.sh).
  2. Andi menambah node + menggerakkan kursor; Budi menambah node.
  3. verifikasi Andi melihat node Budi, badge rekan, DAN kursor Budi.
  4. screenshot halaman Andi (menampilkan kursor rekan + nama).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://localhost:8123"
OUT = os.path.join(HERE, "docs", "evidence", "f10-collab-editor.png")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = open(os.path.join(HERE, ".autonomous_jwt"), encoding="utf-8").read().strip()
ROOM = f"demo-{int(time.time()) % 100000}"


def main() -> int:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["COLLAB_ENABLED"] = "1"
    log = open(os.path.join(HERE, "docs", "evidence", "f10-shot-server.log"),
               "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1",
         "--port", "8123", "--log-level", "warning"],
        cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(90):
            try:
                OPENER.open(BASE + "/health", timeout=3)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1)

        url = f"{BASE}/collab/ui?room={ROOM}&token={TOK}"
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-proxy-server"])
            def new_user(name, w=1440, h=1000):
                ctx = browser.new_context(viewport={"width": w, "height": h},
                                          device_scale_factor=2)
                ctx.add_init_script(
                    f"try{{localStorage.setItem('katalir_token', {json.dumps(TOK)});}}"
                    f"catch(e){{}}")
                pg = ctx.new_page()
                pg.goto(url + f"&name={name}", wait_until="domcontentloaded",
                        timeout=60000)
                pg.wait_for_function(
                    "() => window.__collab && window.__collab.provider.synced",
                    timeout=45000)
                return pg

            andi = new_user("Andi")
            budi = new_user("Budi")

            # Andi: tambah 2 node
            andi.click("#add"); andi.wait_for_timeout(300)
            andi.click("#add"); andi.wait_for_timeout(400)
            # Budi: tambah 1 node
            budi.click("#add"); budi.wait_for_timeout(400)
            # Budi: gerakkan kursor ke tengah papan
            bb = budi.locator("#board").bounding_box()
            budi.mouse.move(bb["x"] + 260, bb["y"] + 180)
            budi.wait_for_timeout(500)
            # Andi: gerakkan kursor juga
            ab = andi.locator("#board").bounding_box()
            andi.mouse.move(ab["x"] + 420, ab["y"] + 300)
            andi.wait_for_timeout(300)

            # verifikasi: Andi melihat 3 node (2 miliknya + 1 milik Budi)
            andi.wait_for_function(
                "() => Object.keys(window.__collab.nodes.toJSON()).length >= 3",
                timeout=20000)
            # verifikasi: Andi melihat badge rekan 'Budi'
            andi.wait_for_function(
                "() => (document.getElementById('peers').textContent||'').includes('Budi')",
                timeout=20000)
            # verifikasi: Andi melihat kursor REKAN (bukan kursornya sendiri)
            andi.wait_for_function(
                "() => document.querySelectorAll('.rcursor').length >= 1",
                timeout=20000)
            andi.wait_for_function(
                "() => [...document.querySelectorAll('.rcursor .tag')]"
                ".every(e => !e.textContent.includes('Andi'))",
                timeout=20000)
            andi.wait_for_timeout(800)
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            andi.screenshot(path=OUT, full_page=True)
            n_nodes = andi.evaluate("() => Object.keys(window.__collab.nodes.toJSON()).length")
            n_cursor = andi.evaluate("() => document.querySelectorAll('.rcursor').length")
            print("room        :", ROOM)
            print("nodes seen  :", n_nodes)
            print("remote cursors seen:", n_cursor)
            print("screenshot ->", OUT)
            browser.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
