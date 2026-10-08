# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_scm_shot.py
# Prasyarat: server uvicorn lokal di port 8123; GITHUB_TOKEN NYATA di .env.
"""Screenshot halaman Admin Source Control (bukti visual Fitur #5).

Alur:
  1. buka /source-control/ui di Chromium (Playwright); token disuntik ke
     localStorage SEBELUM skrip halaman berjalan.
  2. isi provider/repo/token GitHub NYATA lalu klik "Hubungkan" -> halaman
     memanggil /source-control/connect yang MEMBACA daftar cabang dari GitHub.
  3. tunggu tabel koneksi terisi, lalu screenshot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://localhost:8123"
OUT = os.path.join(HERE, "docs", "evidence", "f05-scm-admin.png")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = open(os.path.join(HERE, ".autonomous_jwt"), encoding="utf-8").read().strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("KATALIR_SCM_REPO", "vraafi/katalir-scm-verify")


def _call(path, timeout=30):
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Bearer {TOK}", "Accept": "application/json"})
    try:
        r = OPENER.open(req, timeout=timeout)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    if not GITHUB_TOKEN:
        print("!! GITHUB_TOKEN tidak ada"); return 1
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    log = open(os.path.join(HERE, "docs", "evidence", "f05-shot-server.log"),
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
        st, body = _call("/source-control/providers")
        print("providers:", st, body[:200])

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-proxy-server"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 1150},
                                      device_scale_factor=2)
            ctx.add_init_script(
                f"try{{localStorage.setItem('katalir_token', {json.dumps(TOK)});}}"
                f"catch(e){{}}")
            page = ctx.new_page()
            page.goto(BASE + "/source-control/ui", wait_until="networkidle",
                      timeout=60000)
            # 1) hubungkan repo NYATA (baca daftar cabang dari GitHub)
            page.fill("#repo", REPO)
            page.fill("#token", GITHUB_TOKEN)
            page.click("#btn-connect")
            page.wait_for_function(
                "() => (document.getElementById('tbl').textContent||'')"
                f".includes('{REPO}')", timeout=45000)
            print("STEP 1 connect OK (repo terdaftar)")
            # 2) commit workflow NYATA ke GitHub (branch main)
            wf = f"ui-demo-{int(time.time()) % 100000}"
            page.fill("#wf", wf)
            page.click("#btn-commit")
            page.wait_for_function(
                "() => (document.getElementById('out').textContent||'')"
                ".includes('commit')", timeout=45000)
            print("STEP 2 commit OK")
            # 3) buat branch + commit di branch + buka PR NYATA
            br = f"ui/{wf}"
            page.fill("#newname", br)
            page.click("#btn-branch")
            page.wait_for_timeout(3000)
            page.fill("#branch", br)          # commit berikut ke branch baru
            page.fill("#msg", "chore: perubahan di branch (UI)")
            page.click("#btn-commit")
            page.wait_for_function(
                "() => (document.getElementById('out').textContent||'')"
                ".includes('commit')", timeout=45000)
            print("STEP 3 branch+commit OK")
            page.fill("#branch", "main")      # PR: base kembali ke main
            page.click("#btn-pr")
            page.wait_for_function(
                "() => (document.getElementById('out').textContent||'')"
                ".includes('pull_request')", timeout=45000)
            print("STEP 4 PR OK")
            page.wait_for_timeout(900)
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            page.screenshot(path=OUT, full_page=True)
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
