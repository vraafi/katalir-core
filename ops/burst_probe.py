#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Burst /chat terinstrumentasi: apakah ORIGIN benar-benar menerima semua request?

Pertanyaan yang dijawab: pada 502 dari edge Cloudflare, apakah request sampai ke
uvicorn? Caranya: hitung baris access-log `/chat` SEBELUM dan SESUDAH burst.

  delta == jumlah 200+503 yang dilihat klien  -> origin menerima semuanya
                                                => kehilangan terjadi di transport
                                                   (cloudflared<->uvicorn), bukan app
  delta <  jumlah tersebut                    -> sebagian request tak pernah sampai
                                                => cloudflared gagal mengirim

Jalankan di VPS:
    /root/katalir-core/venv/bin/python3 ops/burst_probe.py 50
    DIAG_API=http://127.0.0.1:8100/katalir-api DIAG_HOST=gateway.katalir.de5.net \
        /root/katalir-core/venv/bin/python3 ops/burst_probe.py 50
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/katalir-core")
os.chdir("/root/katalir-core")

LOG = "/root/api_server.log"
API = os.environ.get("DIAG_API", "https://gateway.katalir.de5.net/katalir-api")
DIAG_HOST = os.environ.get("DIAG_HOST", "")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def env_load():
    out = {}
    for line in open("/root/katalir-core/.env", encoding="utf-8", errors="replace"):
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


ENV = env_load()


def http(url, data=None, headers=None, method=None, timeout=200):
    h = dict(headers or {})
    h.setdefault("User-Agent", UA)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)[:200], time.time() - t0


CACHE = "/root/_burst_tokens.json"


def make_user(tag):
    su = ENV["SUPABASE_URL"].rstrip("/")
    svc = ENV.get("SUPABASE_SERVICE_KEY") or ENV.get("SUPABASE_SERVICE_ROLE_KEY")
    anon = ENV.get("SUPABASE_KEY") or ENV.get("SUPABASE_PUBLISHABLE_KEY")
    email = f"burst-{tag}-{int(time.time())}-{uuid.uuid4().hex[:6]}@test.dev"
    pw = "C!" + uuid.uuid4().hex[:16]
    s, b, _ = http(f"{su}/auth/v1/admin/users",
                   {"email": email, "password": pw, "email_confirm": True},
                   {"apikey": svc, "Authorization": "Bearer " + svc,
                    "Content-Type": "application/json"}, "POST", 60)
    if s != 200:
        raise RuntimeError(f"create {s}: {b[:160]}")
    # Signin bisa kena rate limit Supabase Auth saat puluhan akun dibuat
    # beruntun -> ulangi dengan jeda bertingkat sebelum menyerah.
    last = ""
    for attempt in range(5):
        s, b, _ = http(f"{su}/auth/v1/token?grant_type=password",
                       {"email": email, "password": pw},
                       {"apikey": anon, "Content-Type": "application/json"}, "POST", 60)
        if s == 200:
            try:
                return json.loads(b)["access_token"]
            except Exception:  # noqa: BLE001
                last = b[:200]
        else:
            last = f"{s}: {b[:200]}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"signin gagal: {last}")


def get_users(n):
    """Kumpulkan n token; cache tumbuh bertahap supaya burst berikutnya cepat."""
    cached: list[str] = []
    if os.environ.get("BURST_NO_CACHE") != "1" and os.path.exists(CACHE):
        try:
            d = json.load(open(CACHE))
            if time.time() - d.get("t", 0) < 3600:
                cached = list(d.get("tok") or [])
        except Exception:  # noqa: BLE001
            cached = []
    if len(cached) >= n:
        print(f"[setup] {n} token dari cache ({len(cached)} tersedia)")
        return cached[:n]
    print(f"[setup] cache punya {len(cached)} token; membuat {n - len(cached)} lagi")
    for i in range(len(cached), n):
        cached.append(make_user(f"b{i}"))
        if (i + 1) % 10 == 0:
            print(f"        ... {i + 1}/{n}")
            try:
                json.dump({"n": n, "t": time.time(), "tok": cached}, open(CACHE, "w"))
            except Exception:  # noqa: BLE001
                pass
    try:
        json.dump({"n": n, "t": time.time(), "tok": cached}, open(CACHE, "w"))
    except Exception:  # noqa: BLE001
        pass
    return cached[:n]


def chat_lines():
    """Jumlah baris access-log /chat (tanpa timestamp)."""
    try:
        out = subprocess.run(["grep", "-c", "POST /katalir-api/chat HTTP", LOG],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out or 0)
    except Exception:  # noqa: BLE001
        return -1


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    users = get_users(n)
    print(f"[target] {API} | host_header={DIAG_HOST or '(default)'} | n={n}\n")

    def one(i):
        h = {"Authorization": "Bearer " + users[i % len(users)],
             "Content-Type": "application/json",
             "Origin": "https://katalir.de5.net"}
        if DIAG_HOST:
            h["Host"] = DIAG_HOST
        return http(f"{API}/chat",
                    {"prompt": f"Balas angka {i}",
                     "model": "gemini-2.5-flash-lite",
                     "client_request_id": str(uuid.uuid4())}, h, "POST", 200)

    before = chat_lines()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:      # benar-benar n konkuren
        res = list(ex.map(one, range(n)))
    wall = time.time() - t0
    time.sleep(3)                                      # beri waktu flush log
    after = chat_lines()

    codes = collections.Counter(s for s, _, _ in res)
    lat = [t for _, _, t in res]
    print(f"[/chat x{n}] wall={wall:.1f}s p50={statistics.median(lat):.2f}s "
          f"p95={sorted(lat)[int(len(lat) * 0.95) - 1]:.2f}s")
    print("  distribusi kode:", dict(codes))
    print(f"  access-log /chat: sebelum={before} sesudah={after} delta={after - before}")
    diterima = codes.get(200, 0) + codes.get(503, 0) + codes.get(429, 0)
    print(f"  klien melihat {diterima} respons dari origin "
          f"(200+503+429); origin mencatat {after - before}")
    if after - before >= diterima:
        print("  -> ORIGIN menerima SEMUA request yang dijawab; 502 lahir di transport "
              "cloudflared<->uvicorn (RST), bukan di aplikasi.")
    else:
        print(f"  -> {diterima - (after - before)} request TIDAK pernah dicatat origin "
              "=> cloudflared gagal mengirim.")
    for s, b, t in sorted(res, key=lambda r: r[2]):
        if s not in (200,):
            print(f"  GAGAL kode={s} t={t:.2f}s body={b[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
