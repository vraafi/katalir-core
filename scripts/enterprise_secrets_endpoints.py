#!/usr/bin/env python
"""enterprise_secrets_endpoints.py — Verifikasi endpoint /secrets/* Fitur #1.

Membuktikan jalur PRODUKSI (HTTP API) benar-benar terhubung ke provider NYATA:

  1. Nyalakan `api_server:app` dengan env provider (Vault/OpenBao/MiniStack).
  2. Ambil JWT nyata untuk melewati get_current_user.
  3. Panggil /secrets/backends, /secrets/info, /secrets/formats,
     /secrets/resolve (mask & reveal), /secrets/rotate, /secrets/history,
     /secrets/ui — cetak RAW RESPONSE.
  4. Screenshot halaman /secrets/ui (bukti visual).

Pakai:
    python scripts/enterprise_secrets_endpoints.py
    python scripts/enterprise_secrets_endpoints.py --skip-prod --no-shot
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL = "otonom-test@katalir-internal.dev"
PASSWORD = "AutoTestKatalir2026!"

VAULT_ADDR = "http://127.0.0.1:8200"
VAULT_TOKEN = "katalir-dev-root"
OPENBAO_ADDR = "http://127.0.0.1:8210"
OPENBAO_TOKEN = "openbao-dev-root"
AWS_ENDPOINT = "http://127.0.0.1:4566"


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(op, url, method="GET", token=None, body=None, timeout=45):
    h = {"User-Agent": "KatalirSecretsVerify/1.0", "Accept": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        r = op.open(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:250]}"


def mint_jwt(op) -> str:
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    pub = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY") or ""
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    h = {"apikey": pub, "Content-Type": "application/json",
         "User-Agent": "KatalirSecretsVerify/1.0"}
    req = urllib.request.Request(url + "/auth/v1/signup", data=body, headers=h)
    try:
        op.open(req, timeout=30).read()
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(
        url + "/auth/v1/token?grant_type=password", data=body, headers=h)
    return json.loads(op.open(req, timeout=30).read())["access_token"]


def tunggu_sehat(op, base, batas=90) -> bool:
    t0 = time.time()
    while time.time() - t0 < batas:
        st, _ = _call(op, base + "/health")
        if st == 200:
            return True
        time.sleep(1.0)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--prod", default="https://web-production-dc90b.up.railway.app")
    ap.add_argument("--skip-prod", action="store_true")
    ap.add_argument("--no-shot", action="store_true")
    args = ap.parse_args()

    op = _opener()
    hasil: dict = {}
    print("# VERIFIKASI ENDPOINT /secrets/* — Fitur #1 (External Secrets Manager)")
    print(f"# Vault={VAULT_ADDR}  OpenBao={OPENBAO_ADDR}  AWS={AWS_ENDPOINT}\n")

    tok = mint_jwt(op)
    print(f"JWT diperoleh: prefix={tok[:12]}... len={len(tok)}\n")

    env = dict(os.environ)
    env.update({
        "KATALIR_VAULT_ADDR": VAULT_ADDR, "KATALIR_VAULT_TOKEN": VAULT_TOKEN,
        "KATALIR_VAULT_MOUNT": "secret",
        "KATALIR_OPENBAO_ADDR": OPENBAO_ADDR, "KATALIR_OPENBAO_TOKEN": OPENBAO_TOKEN,
        "KATALIR_OPENBAO_MOUNT": "secret",
        "KATALIR_AWS_ENDPOINT_URL": AWS_ENDPOINT, "KATALIR_AWS_REGION": "us-east-1",
        "KATALIR_AWS_ACCESS_KEY_ID": "katalir-local",
        "KATALIR_AWS_SECRET_ACCESS_KEY": "katalir-local",
        "PYTHONUNBUFFERED": "1",
    })
    logpath = os.path.join(HERE, "docs", "evidence", "f01-server.log")
    log = open(logpath, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1",
         "--port", str(args.port), "--log-level", "warning"],
        cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://localhost:{args.port}"
    try:
        if not tunggu_sehat(op, base):
            print("!! server tidak sehat; log:")
            print(open(logpath, encoding="utf-8").read()[-3000:])
            return 1
        print(f"server siap di {base} (PID {proc.pid})\n")

        # 1. backends
        st, b = _call(op, base + "/secrets/backends", token=tok)
        print(f"### GET /secrets/backends -> HTTP {st}\n{b}\n")
        hasil["backends"] = json.loads(b) if st == 200 else {"raw": b}

        # 2. info provider NYATA
        st, b = _call(op, base + "/secrets/info", token=tok)
        print(f"### GET /secrets/info -> HTTP {st}\n{json.dumps(json.loads(b), indent=1)[:900] if st == 200 else b}\n")
        hasil["info"] = json.loads(b) if st == 200 else {"raw": b}

        # 3. seed nilai nyata ke 3 provider via resolve/rotate
        for ref, val in [("secret://hashicorp/demo/db", "vault-pass-2026"),
                         ("secret://openbao/demo/db", "openbao-pass-2026"),
                         ("secret://aws/demo/db", "aws-pass-2026")]:
            st, b = _call(op, base + "/secrets/rotate", method="POST", token=tok,
                          body={"ref": ref, "value": val})
            print(f"### POST /secrets/rotate {ref} -> HTTP {st} {b[:160]}")
        print()

        # 4. resolve MASK (default) vs REVEAL
        for ref in ("secret://hashicorp/demo/db", "secret://openbao/demo/db",
                    "secret://aws/demo/db"):
            st_m, b_m = _call(op, base + "/secrets/resolve", method="POST", token=tok,
                              body={"ref": ref, "reveal": False})
            st_r, b_r = _call(op, base + "/secrets/resolve", method="POST", token=tok,
                              body={"ref": ref, "reveal": True})
            print(f"### POST /secrets/resolve {ref}")
            print(f"    mask   -> HTTP {st_m} {b_m[:130]}")
            print(f"    reveal -> HTTP {st_r} {b_r[:130]}")
            hasil[f"resolve::{ref}"] = {"mask": json.loads(b_m) if st_m == 200 else b_m,
                                        "reveal": json.loads(b_r) if st_r == 200 else b_r}
        print()

        # 5. failover chain lewat HTTP
        st, b = _call(op, base + "/secrets/resolve", method="POST", token=tok,
                      body={"ref": "secret://hashicorp/demo/db", "reveal": True,
                            "chain": ["hashicorp", "openbao"]})
        print(f"### POST /secrets/resolve (chain) -> HTTP {st}\n{b}\n")
        hasil["failover"] = json.loads(b) if st == 200 else {"raw": b}

        # 6. rotate + history
        st, b = _call(op, base + "/secrets/rotate", method="POST", token=tok,
                      body={"ref": "secret://openbao/rotate/db", "value": "rot-1"})
        st2, b2 = _call(op, base + "/secrets/rotate", method="POST", token=tok,
                        body={"ref": "secret://openbao/rotate/db", "value": "rot-2"})
        st3, b = _call(op, base + "/secrets/history?ref=secret://openbao/rotate/db",
                       token=tok)
        print(f"### POST /secrets/rotate x2 -> HTTP {st}/{st2}")
        print(f"### GET  /secrets/history  -> HTTP {st3}\n{b}\n")
        hasil["history"] = json.loads(b) if st3 == 200 else {"raw": b}

        # 7. path traversal lewat HTTP -> 400
        st, b = _call(op, base + "/secrets/resolve", method="POST", token=tok,
                      body={"ref": "secret://openbao//etc/shadow", "reveal": True})
        print(f"### POST /secrets/resolve (traversal) -> HTTP {st} (harus 400)\n{b}\n")
        hasil["traversal"] = {"status": st, "body": b}

        # 8. terlalu besar -> 413
        st, b = _call(op, base + "/secrets/rotate", method="POST", token=tok,
                      body={"ref": "secret://openbao/too/big", "value": "x" * 262145})
        print(f"### POST /secrets/rotate (>256KB) -> HTTP {st} (harus 413)\n{b[:160]}\n")
        hasil["too_large"] = {"status": st, "body": b[:200]}

        # 9. UI + tanpa token
        st, b = _call(op, base + "/secrets/ui")
        print(f"### GET /secrets/ui -> HTTP {st}, {len(b)} byte\n")
        hasil["ui"] = {"status": st, "len": len(b)}
        st, b = _call(op, base + "/secrets/backends")
        print(f"### GET /secrets/backends tanpa token -> HTTP {st} (harus 401)\n")
        hasil["no_token"] = {"status": st}

        # 10. screenshot
        if not args.no_shot:
            try:
                from playwright.sync_api import sync_playwright
                out = os.path.join(HERE, "docs", "evidence", "f01-secrets-admin.png")
                with sync_playwright() as p:
                    br = p.chromium.launch(args=["--no-proxy-server"])
                    ctx = br.new_context(viewport={"width": 1440, "height": 1150},
                                         device_scale_factor=2)
                    ctx.add_init_script(
                        f"try{{localStorage.setItem('katalir_token',"
                        f" {json.dumps(tok)});}}catch(e){{}}")
                    pg = ctx.new_page()
                    pg.goto(base + "/secrets/ui", wait_until="networkidle", timeout=60000)
                    pg.wait_for_function(
                        "() => (document.getElementById('raw').textContent||'')"
                        ".includes('openbao')", timeout=30000)
                    pg.click("text=Uji koneksi provider")
                    pg.wait_for_timeout(1200)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    pg.screenshot(path=out, full_page=True)
                    print(f"### screenshot -> {out}\n")
                    hasil["screenshot"] = out
                    br.close()
            except Exception as exc:  # noqa: BLE001
                print(f"!! screenshot gagal: {type(exc).__name__}: {exc}\n")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()

    out = os.path.join(HERE, "docs", "evidence", "f01-endpoints.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(hasil, fh, indent=2, ensure_ascii=False)
    print(f"# tersimpan: {out}")

    if not args.skip_prod:
        print(f"\n# === PRODUKSI {args.prod} ===")
        for path in ("/secrets/backends", "/secrets/ui"):
            st, b = _call(op, args.prod + path, timeout=60)
            print(f"  GET {path:22s} (tanpa token) -> HTTP {st} "
                  f"({'ok' if st in (200, 401) else str(b)[:120]})")
        st, b = _call(op, args.prod + "/secrets/backends", token=tok, timeout=60)
        print(f"  GET /secrets/backends (token)  -> HTTP {st} {b[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
