#!/usr/bin/env python
"""enterprise_queue_endpoints.py — Verifikasi endpoint /queue/* Fitur #6.

Membuktikan bahwa jalur PRODUKSI (HTTP API, bukan unit test) benar-benar
terhubung ke Redis nyata:

  1. Nyalakan `api_server:app` dengan KATALIR_REDIS_URL + QUEUE_WORKERS=4.
  2. Ambil JWT nyata (Supabase password grant) untuk melewati get_current_user.
  3. Panggil /queue/workers, /queue/enqueue, /queue/stats, /queue/reclaim,
     /queue/dlq/replay, /queue/ui — cetak RAW RESPONSE.
  4. Cek ulang lewat Redis langsung (ZCARD/HLEN) bahwa job BENAR-BENAR ada
     di server, bukan hanya di memori proses API.
  5. Verifikasi endpoint yang sama di URL produksi.

Pakai:
    python scripts/enterprise_queue_endpoints.py
    python scripts/enterprise_queue_endpoints.py --prod https://katalir.de5.net
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


def _opener():
    # Proxy lokal di env bisa mencegat request localhost -> matikan.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(op, url, method="GET", token=None, body=None, timeout=30):
    h = {"User-Agent": "KatalirQueueVerify/1.0", "Accept": "application/json"}
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
         "User-Agent": "KatalirQueueVerify/1.0"}
    req = urllib.request.Request(url + "/auth/v1/signup", data=body, headers=h)
    try:
        op.open(req, timeout=30).read()
    except Exception:  # noqa: BLE001 - sudah terdaftar = tidak masalah
        pass
    req = urllib.request.Request(
        url + "/auth/v1/token?grant_type=password", data=body, headers=h)
    r = op.open(req, timeout=30)
    tok = json.loads(r.read())["access_token"]
    return tok


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
    ap.add_argument("--url", default="redis://127.0.0.1:6379/0")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--prod", default="https://katalir.de5.net")
    ap.add_argument("--skip-prod", action="store_true")
    ap.add_argument("--no-workers", action="store_true",
                    help="QUEUE_WORKERS=0 -> job menumpuk (untuk screenshot UI)")
    args = ap.parse_args()

    op = _opener()
    hasil: dict = {}

    print("# VERIFIKASI ENDPOINT /queue/* — Fitur #6")
    print(f"# redis = {args.url}\n")

    tok = mint_jwt(op)
    print(f"JWT diperoleh: prefix={tok[:12]}... len={len(tok)}\n")

    env = dict(os.environ)
    env["KATALIR_REDIS_URL"] = args.url
    env["QUEUE_WORKERS"] = "0" if args.no_workers else "4"
    env["PYTHONUNBUFFERED"] = "1"
    log = open(os.path.join(HERE, "docs", "evidence", "f06-server.log"), "w",
               encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
        cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://localhost:{args.port}"
    try:
        if not tunggu_sehat(op, base):
            print("!! server tidak sehat; log:")
            print(open(os.path.join(HERE, "docs", "evidence", "f06-server.log"),
                       encoding="utf-8").read()[-3000:])
            return 1
        print(f"server siap di {base} (PID {proc.pid})\n")

        # 1. health
        st, b = _call(op, base + "/queue/workers", token=tok)
        print(f"### GET /queue/workers -> HTTP {st}\n{b}\n")
        hasil["workers_before"] = json.loads(b) if st == 200 else {}

        # 2. enqueue 25 job (prioritas campur)
        ids = []
        for i in range(25):
            st, b = _call(op, base + "/queue/enqueue", method="POST", token=tok,
                          body={"workflow_id": "demo-queue",
                                "flow_data": {"n": i},
                                "trigger_input": {},
                                "priority": 10 if i < 5 else 0})
            if st == 200:
                ids.append(json.loads(b)["job"]["id"])
        print(f"### POST /queue/enqueue x25 -> HTTP {st}, {len(ids)} job dibuat")
        print(f"    id contoh: {ids[:3]} … {ids[-2:]}\n")

        # 2b. beri worker waktu memproses, lalu lihat status worker
        time.sleep(3.0)
        st, b = _call(op, base + "/queue/workers", token=tok)
        print(f"### GET /queue/workers (setelah 3s) -> HTTP {st}\n{b}\n")
        try:
            hasil["workers_after"] = json.loads(b)
        except Exception:  # noqa: BLE001
            pass

        # 3. bukti di REDIS langsung (bukan memori proses API)
        import redis as _redis
        r = _redis.Redis.from_url(args.url, decode_responses=True)
        zc = r.zcard("katalir:q:ready")
        keys = [k for k in r.scan_iter(match="katalir:q:job:*", count=500)]
        print("### BUKTI LANGSUNG DI REDIS (server, bukan memori API)")
        print(f"    ZCARD katalir:q:ready       = {zc}")
        print(f"    jumlah HASH katalir:q:job:* = {len(keys)}")
        print(f"    INFO server                 = {r.info('server').get('valkey_version')}")
        print(f"    HGETALL {keys[0] if keys else '-'} = "
              f"{r.hgetall(keys[0]) if keys else {}}\n")

        # 4. stats
        st, b = _call(op, base + "/queue/stats", token=tok)
        print(f"### GET /queue/stats -> HTTP {st}\n{b}\n")

        # 5. reclaim + dlq replay
        st, b = _call(op, base + "/queue/reclaim", method="POST", token=tok)
        print(f"### POST /queue/reclaim -> HTTP {st}\n{b}\n")
        st, b = _call(op, base + "/queue/dlq/replay", method="POST", token=tok)
        print(f"### POST /queue/dlq/replay -> HTTP {st}\n{b}\n")

        # 6. UI
        st, b = _call(op, base + "/queue/ui")
        print(f"### GET /queue/ui -> HTTP {st}, {len(b)} byte "
              f"(judul: {'Queue Mode Scaling' in b})\n")

        # 7. auth wajib
        st, b = _call(op, base + "/queue/workers")
        print(f"### GET /queue/workers TANPA token -> HTTP {st} (wajib 401)\n{b}\n")
        hasil["no_token_status"] = st

        hasil["local_ok"] = True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()
        log.close()

    # ---- PRODUKSI -------------------------------------------------------
    if not args.skip_prod:
        print("=" * 78)
        print(f"# VERIFIKASI PRODUKSI: {args.prod}")
        print("=" * 78)
        for path in ("/queue/workers", "/queue/stats", "/queue/ui", "/version"):
            st, b = _call(op, args.prod + path, token=tok, timeout=60)
            show = b if len(b) <= 600 else b[:600] + " …"
            print(f"\n### GET {args.prod}{path} -> HTTP {st}\n{show}")
            if path == "/version":
                try:
                    d = json.loads(b)
                    hasil["prod_version"] = d.get("features", d)
                except Exception:  # noqa: BLE001
                    pass

    with open(os.path.join(HERE, "docs", "evidence", "f06-endpoints.json"),
              "w", encoding="utf-8") as fh:
        json.dump(hasil, fh, indent=2, ensure_ascii=False)
    print("\nJSON -> docs/evidence/f06-endpoints.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
