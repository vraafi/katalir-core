#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hard test backend Katalir — 20 skenario Fase 3 + 4 skenario Fase 4.

Dijalankan DI VPS (butuh akses DB + `systemctl`):
    /root/katalir-core/venv/bin/python3 ops/backend_hard_test.py

Prinsip:
  * Bukti mentah untuk SETIAP klaim: tiap baris mencetak status, latensi, dan
    potongan body/exception apa adanya.
  * 429 dipisahkan dari kegagalan. Batas `CHAT_RATE_LIMIT` (default 10/menit
    per akun) adalah perilaku BY DESIGN; mencampurnya dengan 5xx akan
    menyamarkan kegagalan nyata.
  * Klien memakai User-Agent browser. Tanpa itu Cloudflare menjawab
    `403 error code: 1010` (Browser Integrity Check) dan hasilnya palsu.
"""
from __future__ import annotations

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

API = os.environ.get("HARD_TEST_API", "https://gateway.katalir.de5.net/katalir-api")
FRONT = "https://katalir.de5.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
CHEAP_MODEL = "gemini-2.5-flash-lite"
RESULTS: list[dict] = []


def env_load() -> dict:
    out = {}
    for line in open("/root/katalir-core/.env", encoding="utf-8", errors="replace"):
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


ENV = env_load()


def http(url, data=None, headers=None, method=None, timeout=120, ua=UA):
    h = dict(headers or {})
    if ua:
        h.setdefault("User-Agent", ua)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)[:300], time.time() - t0


def record(n, name, ok, detail):
    RESULTS.append({"n": n, "name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print(f"[{n:02d}] {'PASS' if ok else 'FAIL'} | {name} | {str(detail)[:300]}")


def make_user(tag: str) -> str:
    """Buat user uji + kembalikan JWT. Pakai kunci service LAMA (JWT).

    CATATAN: `SUPABASE_SECRET_KEY` format baru (`sb_secret_…`) DITOLAK oleh
    Supabase Auth (`401 Forbidden use of secret API key in browser`), jadi
    sengaja memakai `SUPABASE_SERVICE_KEY` (JWT) yang memang dipakai
    `database.py` di produksi.
    """
    su = ENV["SUPABASE_URL"].rstrip("/")
    svc = ENV.get("SUPABASE_SERVICE_KEY") or ENV.get("SUPABASE_SERVICE_ROLE_KEY")
    anon = ENV.get("SUPABASE_KEY") or ENV.get("SUPABASE_PUBLISHABLE_KEY")
    email = f"hardtest-{tag}-{int(time.time())}-{uuid.uuid4().hex[:6]}@test.dev"
    pw = "Hard!" + uuid.uuid4().hex[:16]
    s, b, _ = http(f"{su}/auth/v1/admin/users",
                   {"email": email, "password": pw, "email_confirm": True},
                   {"apikey": svc, "Authorization": "Bearer " + svc,
                    "Content-Type": "application/json"}, "POST", 60)
    if s != 200:
        raise RuntimeError(f"admin create gagal {s}: {b[:200]}")
    s, b, _ = http(f"{su}/auth/v1/token?grant_type=password",
                   {"email": email, "password": pw},
                   {"apikey": anon, "Content-Type": "application/json"}, "POST", 60)
    if s != 200:
        raise RuntimeError(f"signin gagal {s}: {b[:200]}")
    return json.loads(b)["access_token"]


def hdr(jwt):
    return {"Authorization": "Bearer " + jwt, "Content-Type": "application/json",
            "Origin": FRONT}


def chat(jwt, prompt, crid=None, model=CHEAP_MODEL, timeout=200):
    return http(f"{API}/chat",
                {"prompt": prompt, "model": model,
                 "client_request_id": crid or str(uuid.uuid4())},
                hdr(jwt), "POST", timeout)


def main() -> int:
    import database as db

    print("=" * 78)
    print("HARD TEST BACKEND KATALIR — 11 Okt 2026")
    print(f"API   = {API}")
    print(f"FRONT = {FRONT}")
    print("=" * 78)

    jwt = make_user("main")
    print(f"[setup] JWT diperoleh (len={len(jwt)})")

    # ---------------- TEST SET 1: BACKEND BASIC ----------------
    s, b, t = http(f"{API}/health", timeout=30)
    ok = s == 200 and json.loads(b).get("persistence", {}).get("status") == "persisted"
    record(1, "GET /health -> 200 + persistence OK", ok, f"status={s} t={t:.2f}s body={b[:180]}")

    s, b, t = http(f"{API}/workflows", timeout=30)
    record(2, "GET /workflows tanpa auth -> 401", s == 401, f"status={s} body={b[:160]}")

    s, b, t = http(f"{API}/workflows", headers=hdr(jwt), timeout=60)
    record(3, "GET /workflows dengan JWT -> 200", s == 200, f"status={s} t={t:.2f}s body={b[:200]}")

    s, b, t = http(f"{API}/version", timeout=30)
    try:
        j = json.loads(b)
        commit = j.get("build", {}).get("commit")
        feats = j.get("features_present")
        tot = j.get("features_total")
    except Exception:  # noqa: BLE001
        commit = feats = tot = None
    record(4, "GET /version -> 200 + commit + fitur",
           s == 200 and bool(commit) and commit != "unknown",
           f"status={s} commit={commit!r} fitur={feats}/{tot}")

    # ---------------- TEST SET 2: CHAT E2E ----------------
    crid_simple = str(uuid.uuid4())
    s, b, t = chat(jwt, "Balas persis: PING-SIMPLE", crid_simple)
    sid = None
    try:
        j = json.loads(b)
        sid = j.get("session_id")
        reply = j.get("reply")
    except Exception:  # noqa: BLE001
        reply = None
    record(5, "POST /chat prompt sederhana -> 200 & <30s",
           s == 200 and t < 30 and bool(reply), f"status={s} t={t:.2f}s reply={reply!r}")

    long_prompt = ("Kamu adalah asisten teknis. " * 40 +
                   "Tulis SATU kalimat pendek yang menyebut kata LANTAI-7.")
    s2, b2, t2 = chat(jwt, long_prompt)
    reply2 = None
    sid2 = None
    try:
        j2 = json.loads(b2)
        reply2 = j2.get("reply")
        sid2 = j2.get("session_id")
    except Exception:  # noqa: BLE001
        pass
    record(6, "POST /chat prompt panjang -> 200 & <120s",
           s2 == 200 and t2 < 120 and bool(reply2),
           f"status={s2} t={t2:.2f}s reply={str(reply2)[:90]!r}")

    # 7 & 8: persistensi
    c = db._get_write_client()
    rows = []
    if sid:
        r = c.table("chat_messages").select("id,role,content").eq("session_id", sid).execute()
        rows = r.data or []
    record(7, "chat_messages berisi baris user+assistant",
           len(rows) >= 2 and {x.get("role") for x in rows} >= {"user", "assistant"},
           f"session={sid} rows={len(rows)} roles={[x.get('role') for x in rows]}")

    sess = []
    if sid:
        r = c.table("chat_sessions").select("id,title,user_id").eq("id", sid).execute()
        sess = r.data or []
    record(8, "chat_sessions berisi sesi baru",
           len(sess) == 1, f"session={sid} row={json.dumps(sess, ensure_ascii=False)[:180]}")

    # ---------------- TEST SET 3: INTEGRATIONS ----------------
    try:
        r = c.table("users").select("id", count="exact").limit(1).execute()
        record(9, "Supabase SELECT OK", r.count is not None,
               f"users count={r.count}")
    except Exception as e:  # noqa: BLE001
        record(9, "Supabase SELECT OK", False, f"{type(e).__name__}: {e}")

    # INSERT diuji lewat jalur aplikasi (bukan tulis langsung) supaya yang
    # terbukti adalah jalur PRODUKSI, bukan kredensial skrip.
    before = c.table("chat_messages").select("id", count="exact").limit(1).execute().count
    s3, b3, t3 = chat(jwt, "Balas: INSERT-OK")
    after = c.table("chat_messages").select("id", count="exact").limit(1).execute().count
    record(10, "Supabase INSERT (via /chat) OK",
           s3 == 200 and after > before,
           f"status={s3} count {before} -> {after}")

    gw_url = ENV.get("LLM_GATEWAY_URL", "").rstrip("/")
    gw_key = ENV.get("LLM_GATEWAY_KEY", "")
    s, b, t = http(f"{gw_url}/v1/models",
                   headers={"Authorization": "Bearer " + gw_key}, timeout=40)
    nmodels = None
    try:
        nmodels = len(json.loads(b).get("data") or [])
    except Exception:  # noqa: BLE001
        pass
    record(11, "LLM gateway /v1/models -> 200", s == 200 and bool(nmodels),
           f"status={s} t={t:.2f}s models={nmodels}")

    models = (ENV.get("LLM_GATEWAY_MODELS") or CHEAP_MODEL).split(",")
    s, b, t = http(f"{gw_url}/v1/chat/completions",
                   {"model": models[0], "messages": [{"role": "user", "content": "Say OK"}],
                    "max_tokens": 64},
                   {"Authorization": "Bearer " + gw_key,
                    "Content-Type": "application/json"}, "POST", 90)
    record(12, "LLM chat completion -> 200", s == 200, f"status={s} t={t:.2f}s body={b[:180]}")

    # ---------------- TEST SET 4: FRONTEND E2E ----------------
    s, b, t = http(f"{FRONT}/", timeout=30)
    record(13, "GET https://katalir.de5.net -> 200", s == 200, f"status={s} t={t:.2f}s bytes={len(b)}")

    s, b, t = http(f"{FRONT}/chat", timeout=30)
    chunks = [x for x in b.split('"') if "/_next/static/chunks/" in x]
    api_ok = False
    detail = ""
    for ch in chunks[:40]:
        u = ch if ch.startswith("http") else f"{FRONT}{ch}"
        sc, bc, _ = http(u, timeout=30)
        if sc == 200 and "gateway.katalir.de5.net/katalir-api" in bc:
            api_ok = True
            detail = f"chunk={ch} memuat gateway.katalir.de5.net"
            break
    record(14, "/chat 200 + bundle memakai API gateway (BUKAN railway)",
           s == 200 and api_ok, f"status={s} chunks={len(chunks)} {detail}")

    s, b, t = http(f"{API}/chat",
                   headers={"Origin": FRONT, "Access-Control-Request-Method": "POST",
                            "Access-Control-Request-Headers": "authorization,content-type",
                            "Content-Type": "text/plain"}, method="OPTIONS", timeout=30)
    # urllib tidak mengembalikan header; cek lewat curl agar header terlihat.
    cp = subprocess.run(
        ["curl", "-sS", "-D", "-", "-o", "/dev/null", "-X", "OPTIONS", f"{API}/chat",
         "-H", f"Origin: {FRONT}", "-H", "Access-Control-Request-Method: POST",
         "-H", "Access-Control-Request-Headers: authorization,content-type"],
        capture_output=True, text=True, timeout=40)
    allow = "access-control-allow-origin: " + FRONT in cp.stdout.lower().replace("  ", " ")
    record(15, "CORS preflight -> allow-origin katalir.de5.net",
           allow, " | ".join(x for x in cp.stdout.splitlines()
                             if "access-control" in x.lower())[:300])

    record(16, "Chat via frontend E2E (Playwright)", None,
           "dijalankan terpisah: ops/frontend_e2e_playwright.py")

    # ---------------- TEST SET 5: LOAD ----------------
    def run_batch(n, users):
        """n request /chat paralel, disebar ke `users` agar tidak kena
        CHAT_RATE_LIMIT (10/menit/akun)."""
        codes: list[int] = []
        lat: list[float] = []

        def one(i):
            jw = users[i % len(users)]
            s, _b, t = chat(jw, f"Balas angka {i}", timeout=200)
            return s, t

        with ThreadPoolExecutor(max_workers=min(n, 32)) as ex:
            for s, t in ex.map(one, range(n)):
                codes.append(s)
                lat.append(t)
        n200 = sum(1 for x in codes if x == 200)
        n429 = sum(1 for x in codes if x == 429)
        n5xx = sum(1 for x in codes if 500 <= x < 600)
        return n200, n429, n5xx, codes, lat

    extra = [make_user(f"load{i}") for i in range(11)]
    users = [jwt] + extra
    print(f"[setup] {len(users)} akun uji untuk load test")

    n200, n429, n5xx, codes, lat = run_batch(10, users)
    record(17, "10 /chat konkuren -> 100% 200",
           n200 == 10, f"200={n200} 429={n429} 5xx={n5xx} p50={statistics.median(lat):.2f}s")

    n200, n429, n5xx, codes, lat = run_batch(50, users)
    record(18, "50 /chat konkuren -> >=90% 200",
           n200 >= 45, f"200={n200}/50 ({n200/50:.0%}) 429={n429} 5xx={n5xx} "
                       f"p50={statistics.median(lat):.2f}s")

    n200, n429, n5xx, codes, lat = run_batch(100, users)
    record(19, "100 /chat konkuren -> >=80% 200 & tidak crash",
           n200 >= 80, f"200={n200}/100 ({n200}%) 429={n429} 5xx={n5xx} "
                       f"p50={statistics.median(lat):.2f}s")

    # 20: recovery
    s, b, _ = http(f"{API}/health", timeout=20)
    t0 = time.time()
    subprocess.run(["systemctl", "restart", "katalir-backend.service"],
                   capture_output=True, text=True, timeout=120)
    recovered = None
    for _ in range(60):
        time.sleep(2)
        sc, _, _ = http(f"{API}/health", timeout=10)
        if sc == 200:
            recovered = time.time() - t0
            break
    s_chat, b_chat, t_chat = chat(jwt, "Balas: SETELAH-RESTART")
    ok20 = recovered is not None and s_chat == 200
    record(20, "Recovery: restart backend -> chat tetap jalan",
           ok20, f"pulih dalam {recovered and round(recovered,1)}s; "
                 f"chat status={s_chat} t={t_chat:.2f}s")

    # ---------------- FASE 4 HARD TEST ----------------
    def wd_log():
        try:
            return open("/var/log/katalir-watchdog.log", encoding="utf-8").read()
        except OSError:
            return ""

    # 21: auto-restart < 30s (restart backend, tunggu watchdog memulihkan)
    marker = len(wd_log())
    t0 = time.time()
    subprocess.run(["systemctl", "kill", "--signal=SIGKILL", "katalir-backend.service"],
                   capture_output=True, text=True, timeout=60)
    auto = None
    for _ in range(40):
        time.sleep(2)
        sc, _, _ = http(f"{API}/health", timeout=10)
        if sc == 200:
            auto = time.time() - t0
            break
    nrestart = subprocess.run(["systemctl", "show", "katalir-backend", "-p", "NRestarts"],
                              capture_output=True, text=True).stdout.strip()
    record(21, "Kill backend -> pulih otomatis <30s",
           auto is not None and auto < 30,
           f"pulih {auto and round(auto,1)}s; {nrestart}")

    # 22: watchdog hidup & mencatat
    act = subprocess.run(["systemctl", "is-active", "katalir-watchdog"],
                         capture_output=True, text=True).stdout.strip()
    log = wd_log()
    record(22, "Watchdog aktif + mencatat event ke file",
           act == "active" and "watchdog mulai" in log,
           f"is-active={act} log_bytes={len(log)}")

    # 23: /status deep health
    s, b, t = http(f"{API}/status", timeout=40)
    try:
        j = json.loads(b)
        ch = j.get("checks", {})
        allok = all(v.get("ok") for v in ch.values())
    except Exception:  # noqa: BLE001
        allok = False
        ch = {}
    record(23, "GET /status -> agregat backend+supabase+gateway",
           s == 200 and allok, f"status={s} t={t:.2f}s checks={json.dumps(ch)[:260]}")

    # 24: start limit terpasang
    show = subprocess.run(["systemctl", "show", "katalir-backend",
                           "-p", "Restart", "-p", "RestartSec", "-p", "StartLimitBurst"],
                          capture_output=True, text=True).stdout
    record(24, "systemd: Restart=always/RestartSec/StartLimitBurst terpasang",
           "Restart=always" in show and "RestartSec=10" in show and "StartLimitBurst=5" in show,
           " ".join(show.split()))

    # ---------------- RINGKASAN ----------------
    tot = sum(1 for r in RESULTS if r["ok"] is not None)
    good = sum(1 for r in RESULTS if r["ok"] is True)
    print("=" * 78)
    print(f"RINGKASAN: {good}/{tot} PASS"
          f"   ({sum(1 for r in RESULTS if r['ok'] is False)} FAIL,"
          f" {sum(1 for r in RESULTS if r['ok'] is None)} DILEWATI)")
    print("=" * 78)
    with open("/root/katalir-core/_hard_test_result.json", "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=2, ensure_ascii=False)
    return 0 if good == tot else 1


if __name__ == "__main__":
    sys.exit(main())
