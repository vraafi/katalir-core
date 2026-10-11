#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repro bug: session_id non-UUID bocor ke kolom `uuid` Postgres.

Temuan (uji konkurensi 11 Okt 2026): saat `db.create_session()` jatuh ke
fallback memori, ia mengembalikan id `local_<n>` (database.py:315). Id itu
lalu dipakai `db.add_message()` -> `chat_sessions.own_check` (database.py:500)
yang mem-`filter` kolom `uuid` dengan string non-UUID -> PostgREST 22P02 ->
HTTP 503 "Supabase error saat chat_sessions.own_check [22P02]".

Skrip ini membuktikan bug itu REPRODUCIBLE dari klien mana pun, karena
`session_id` di body `/chat` sepenuhnya dikendalikan klien
(api_server.py:2219 `session_id = req.session_id or prior_session`).

Jalankan di VPS:
    /root/katalir-core/venv/bin/python3 -u ops/repro_uuid_bug.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/root/katalir-core")
ENV_PATH = "/root/katalir-core/.env"
API = "https://gateway.katalir.de5.net/katalir-api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def env_load():
    out = {}
    for line in open(ENV_PATH, encoding="utf-8", errors="replace"):
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
    email = f"uuidbug-{tag}-{int(time.time())}-{uuid.uuid4().hex[:6]}@test.dev"
    pw = "U!" + uuid.uuid4().hex[:16]
    s, b, _ = http(f"{su}/auth/v1/admin/users",
                   {"email": email, "password": pw, "email_confirm": True},
                   {"apikey": svc, "Authorization": "Bearer " + svc,
                    "Content-Type": "application/json"}, "POST", 60)
    if s != 200:
        raise RuntimeError(f"create user {s}: {b[:160]}")
    s, b, _ = http(f"{su}/auth/v1/token?grant_type=password",
                   {"email": email, "password": pw},
                   {"apikey": anon, "Content-Type": "application/json"}, "POST", 60)
    if s != 200:
        raise RuntimeError(f"signin {s}: {b[:160]}")
    return json.loads(b)["access_token"]


ROWS = []


def record(label, expect, status, body):
    ok = expect(status)
    ROWS.append((label, "PASS" if ok else "FAIL", status, body[:200].replace("\n", " ")))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} -> HTTP {status}: {body[:200]}")


def main():
    print("=" * 78)
    print("REPRO: session_id non-UUID -> 22P02 pada chat_sessions.own_check")
    print("=" * 78)
    jwt = make_user("main")
    hdr = {"Authorization": "Bearer " + jwt, "Content-Type": "application/json",
           "Origin": "https://katalir.de5.net"}
    print(f"  akun uji siap ({jwt[:12]}...)\n")

    # K1 — session_id sintetis "local_2" (persis yang muncul di produksi)
    s, b, _ = http(f"{API}/chat",
                   {"prompt": "Balas: OK", "session_id": "local_2",
                    "model": "gemini-2.5-flash-lite",
                    "client_request_id": str(uuid.uuid4())}, hdr, "POST", 200)
    record("K1 /chat session_id='local_2' (sintetis)", lambda x: x in (200, 403), s, b)

    # K2 — session_id sembarang (klien jahat/buggy)
    s, b, _ = http(f"{API}/chat",
                   {"prompt": "Balas: OK", "session_id": "bukan-uuid",
                    "model": "gemini-2.5-flash-lite",
                    "client_request_id": str(uuid.uuid4())}, hdr, "POST", 200)
    record("K2 /chat session_id='bukan-uuid'", lambda x: x in (200, 403), s, b)

    # K3 — session_id UUID acak yang TIDAK ada -> 403 (perilaku BENAR)
    s, b, _ = http(f"{API}/chat",
                   {"prompt": "Balas: OK", "session_id": str(uuid.uuid4()),
                    "model": "gemini-2.5-flash-lite",
                    "client_request_id": str(uuid.uuid4())}, hdr, "POST", 200)
    record("K3 /chat session_id=<uuid acak tak ada>", lambda x: x == 403, s, b)

    # K4 — tanpa session_id -> 200 (baseline jalur normal)
    s, b, _ = http(f"{API}/chat",
                   {"prompt": "Balas HANYA: PONG", "model": "gemini-2.5-flash-lite",
                    "client_request_id": str(uuid.uuid4())}, hdr, "POST", 200)
    record("K4 /chat tanpa session_id (baseline)", lambda x: x == 200, s, b)

    # K5 — GET /messages/{non-uuid}
    s, b, _ = http(f"{API}/messages/local_2",
                   None, {"Authorization": "Bearer " + jwt}, "GET", 60)
    record("K5 GET /messages/local_2", lambda x: x in (200, 404), s, b)

    # K6 — DELETE /sessions/{non-uuid}
    s, b, _ = http(f"{API}/sessions/local_2",
                   None, {"Authorization": "Bearer " + jwt}, "DELETE", 60)
    record("K6 DELETE /sessions/local_2", lambda x: x in (200, 404), s, b)

    print("\n" + "=" * 78)
    nfail = sum(1 for r in ROWS if r[1] == "FAIL")
    print(f"RINGKASAN: {len(ROWS) - nfail}/{len(ROWS)} sesuai harapan; {nfail} FAIL")
    print("=" * 78)
    for r in ROWS:
        print(f"  {r[1]:4} {r[0]:42} HTTP {r[2]}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
