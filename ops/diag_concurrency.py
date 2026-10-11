#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnosa 5xx pada uji konkurensi /chat.

Tujuan: menjawab "kenapa 5xx?" dengan BUKTI, bukan dugaan. Tiga kandidat:
  (a) bug backend,
  (b) kapasitas gateway LLM hulu (free tier) -> 5xx diteruskan apa adanya,
  (c) rate limit yang salah kode.

Skrip mencetak KODE + BODY tiap kegagalan, lalu membandingkan dengan
panggilan LANGSUNG ke gateway pada konkurensi yang sama. Kalau gateway juga
5xx pada tingkat yang sama, penyebabnya (b) -- kapasitas hulu, bukan backend.

Jalankan di VPS:
    /root/katalir-core/venv/bin/python3 ops/diag_concurrency.py
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/katalir-core")
os.chdir("/root/katalir-core")

API = os.environ.get("DIAG_API", "https://gateway.katalir.de5.net/katalir-api")
# `DIAG_HOST` mengirim header Host eksplisit. Dipakai untuk menembak ORIGIN
# langsung (`http://127.0.0.1:8100/katalir-api`): `ALLOWED_HOSTS` tidak memuat
# 127.0.0.1, jadi tanpa header ini jawabannya `400 Invalid host header`.
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


def make_user(tag):
    su = ENV["SUPABASE_URL"].rstrip("/")
    svc = ENV.get("SUPABASE_SERVICE_KEY") or ENV.get("SUPABASE_SERVICE_ROLE_KEY")
    anon = ENV.get("SUPABASE_KEY") or ENV.get("SUPABASE_PUBLISHABLE_KEY")
    email = f"conc-{tag}-{int(time.time())}-{uuid.uuid4().hex[:6]}@test.dev"
    pw = "C!" + uuid.uuid4().hex[:16]
    s, b, _ = http(f"{su}/auth/v1/admin/users",
                   {"email": email, "password": pw, "email_confirm": True},
                   {"apikey": svc, "Authorization": "Bearer " + svc,
                    "Content-Type": "application/json"}, "POST", 60)
    if s != 200:
        raise RuntimeError(f"create {s}: {b[:160]}")
    s, b, _ = http(f"{su}/auth/v1/token?grant_type=password",
                   {"email": email, "password": pw},
                   {"apikey": anon, "Content-Type": "application/json"}, "POST", 60)
    return json.loads(b)["access_token"]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    users = [make_user(f"d{i}") for i in range(max(1, n))]
    print(f"[setup] {len(users)} akun uji, mengirim {n} /chat konkuren\n")

    def one(i):
        jw = users[i % len(users)]
        h = {"Authorization": "Bearer " + jw, "Content-Type": "application/json",
             "Origin": "https://katalir.de5.net"}
        if DIAG_HOST:
            h["Host"] = DIAG_HOST
        return http(f"{API}/chat",
                    {"prompt": f"Balas angka {i}", "model": "gemini-2.5-flash-lite",
                     "client_request_id": str(uuid.uuid4())}, h, "POST", 200)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(n, 32)) as ex:
        res = list(ex.map(one, range(n)))
    wall = time.time() - t0

    codes = collections.Counter(s for s, _, _ in res)
    lat = [t for _, _, t in res]
    print(f"[/chat x{n}] wall={wall:.1f}s p50={statistics.median(lat):.2f}s")
    print("  distribusi kode:", dict(codes))
    for s, b, t in res:
        if s != 200:
            print(f"  GAGAL kode={s} t={t:.2f}s body={b[:300]}")

    # Pembanding: gateway LANGSUNG, konkurensi sama.
    gw = ENV["LLM_GATEWAY_URL"].rstrip("/")
    key = ENV["LLM_GATEWAY_KEY"]
    model = (ENV.get("LLM_GATEWAY_MODELS") or "gemini-2.5-flash-lite").split(",")[0]

    def direct(i):
        return http(f"{gw}/v1/chat/completions",
                    {"model": model, "messages": [{"role": "user", "content": f"Balas angka {i}"}],
                     "max_tokens": 64},
                    {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    "POST", 200)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(n, 32)) as ex:
        dres = list(ex.map(direct, range(n)))
    dwall = time.time() - t0
    dcodes = collections.Counter(s for s, _, _ in dres)
    print(f"\n[gateway langsung x{n}] wall={dwall:.1f}s distribusi kode: {dict(dcodes)}")
    for s, b, t in dres:
        if s != 200:
            print(f"  GAGAL kode={s} t={t:.2f}s body={b[:200]}")

    print("\nKESIMPULAN:")
    n_api = codes.get(200, 0)
    n_gw = dcodes.get(200, 0)
    if n_gw < n and n_api <= n_gw + 1:
        print("  Penyebab = KAPASITAS HULU (gateway/provider free tier), bukan backend.")
    elif n_api < n_gw:
        print("  Backend LEBIH BURUK dari gateway langsung -> periksa backend.")
    else:
        print("  Tidak ada perbedaan mencolok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
