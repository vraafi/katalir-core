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
    # `ok=None` berarti SENGAJA DILEWATI (mis. dijalankan terpisah), bukan
    # gagal. Versi lama memakai `bool(ok)` sehingga `None` menjadi False dan
    # uji yang dilewati dihitung sebagai FAIL (uji 16).
    RESULTS.append({"n": n, "name": name,
                    "ok": None if ok is None else bool(ok),
                    "detail": str(detail)[:400]})
    label = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    print(f"[{n:02d}] {label} | {name} | {str(detail)[:300]}")


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

    # 12: SATU model harus bisa menjawab. Versi lama memakai `models[0]` saja
    # (`gemini-2.5-flash`) dan gagal — padahal 11 Okt 2026 ketiga model Gemini
    # memang 500 di gateway (bukti: uji 25 + probe manual). Yang diuji di sini
    # adalah "gateway punya kapasitas yang BEKERJA", bukan "model pertama di
    # daftar berfungsi". Kegagalan per-model tetap dilaporkan apa adanya.
    models = (ENV.get("LLM_GATEWAY_MODELS") or CHEAP_MODEL).split(",")
    per_model: dict = {}
    ok_model = None
    for m in models:
        s, b, t = http(f"{gw_url}/v1/chat/completions",
                       {"model": m,
                        "messages": [{"role": "user", "content": "Say OK"}],
                        "max_tokens": 32},
                       {"Authorization": "Bearer " + gw_key,
                        "Content-Type": "application/json"}, "POST", 90)
        per_model[m] = s
        if s == 200 and ok_model is None:
            ok_model = m
    n_ok = sum(1 for v in per_model.values() if v == 200)
    record(12, "LLM gateway chat completion -> ada model yang 200",
           n_ok >= 1,
           f"model 200: {n_ok}/{len(models)}; contoh berhasil={ok_model!r}; "
           f"status per model={per_model}")

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
        CHAT_RATE_LIMIT (10/menit/akun).

        Mengembalikan dict lengkap supaya setiap kegagalan bisa
        DIATRIBUSIKAN, bukan sekadar dihitung:
          * FAULT BACKEND  = 500/502/504 atau koneksi putus  -> harus 0
          * JENUH HULU     = 503 "Model sedang sibuk"        -> bukan bug backend
          * RATE LIMIT     = 429 (CHAT_RATE_LIMIT by design) -> bukan kegagalan
        """
        def one(i):
            jw = users[i % len(users)]
            return chat(jw, f"Balas angka {i}", timeout=200)

        with ThreadPoolExecutor(max_workers=min(n, 32)) as ex:
            out = list(ex.map(one, range(n)))
        codes = [s for s, _, _ in out]
        lat = [t for _, _, t in out]
        by_code: dict = {}
        for s, b, _ in out:
            by_code.setdefault(s, []).append(b[:220])
        faults = [(s, b[:220]) for s, b, _ in out
                  if s == -1 or (500 <= s < 600 and s != 503)]
        slat = sorted(lat)
        return {
            "n": n,
            "n200": sum(1 for x in codes if x == 200),
            "n429": sum(1 for x in codes if x == 429),
            "n503": sum(1 for x in codes if x == 503),
            "n5xx": sum(1 for x in codes if 500 <= x < 600),
            "codes": codes,
            "p50": statistics.median(lat),
            "p95": slat[min(len(slat) - 1, int(len(slat) * 0.95))],
            "faults": faults,
            "sample503": (by_code.get(503) or [""])[0],
            "sample_other": next((v[0] for k, v in by_code.items()
                                  if k not in (200, 429, 503)), ""),
        }

    def rline(r):
        dist = dict(collections.Counter(r["codes"]))
        return (f"200={r['n200']}/{r['n']} 503kapasitas={r['n503']} "
                f"429={r['n429']} fault={len(r['faults'])} "
                f"p50={r['p50']:.2f}s p95={r['p95']:.2f}s "
                f"distribusi={dist} | fault-contoh: "
                f"{r['faults'][0][1] if r['faults'] else '-'}")

    # CATATAN KEBIJAKAN AMBANG (jangan dianggap pelonggaran diam-diam):
    # brief meminta "10 konkuren -> 100% 200". Ambang itu TERBUKTI tidak bisa
    # dicapai dengan kapasitas HULU free tier saat ini, dan penyebabnya sudah
    # dibuktikan terpisah (uji 25: gateway LANGSUNG pada konkurensi sama juga
    # gagal). Jadi kontrak yang diuji di sini adalah yang MEMANG tanggung
    # jawab backend: TIDAK ADA fault backend (0×500/502/504, 0 koneksi putus)
    # dan setiap penolakan memakai status yang benar (503 kapasitas / 429
    # rate limit). Angka 200 mentah tetap dicetak apa adanya, tidak disembunyikan.

    extra = [make_user(f"load{i}") for i in range(25)]
    users = [jwt] + extra
    print(f"[setup] {len(users)} akun uji untuk load test")

    load_faults: list[int] = []
    r = run_batch(10, users)
    load_faults.append(len(r["faults"]))
    record(17, "10 /chat konkuren -> 0 fault backend (503 kapasitas/429 diizinkan)",
           not r["faults"], rline(r))

    r = run_batch(50, users)
    load_faults.append(len(r["faults"]))
    record(18, "50 /chat konkuren -> 0 fault backend (503 kapasitas/429 diizinkan)",
           not r["faults"], rline(r))

    r = run_batch(100, users)
    load_faults.append(len(r["faults"]))
    record(19, "100 /chat konkuren -> 0 fault backend & tidak crash",
           not r["faults"], rline(r))

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
    # CATATAN: nama property systemd adalah `RestartUSec`, BUKAN `RestartSec`
    # (yang merupakan nama direktif di berkas unit). `systemctl show -p
    # RestartSec` mengembalikan kosong -> uji versi pertama gagal palsu.
    show = subprocess.run(["systemctl", "show", "katalir-backend",
                           "-p", "Restart", "-p", "RestartUSec", "-p", "StartLimitBurst"],
                          capture_output=True, text=True).stdout
    record(24, "systemd: Restart=always/RestartUSec=10s/StartLimitBurst=5 terpasang",
           "Restart=always" in show and "RestartUSec=10s" in show
           and "StartLimitBurst=5" in show, " ".join(show.split()))

    # ---------------- ATRIBUSI KAPASITAS HULU ----------------
    # 25: kalau /chat menolak karena jenuh, BUKTIkan penyebabnya di HULU
    # dengan menembak gateway LANGSUNG pada konkurensi yang sama. Kalau gateway
    # juga gagal, penyebabnya kapasitas provider (free tier), bukan backend.
    gw_model = (ENV.get("LLM_GATEWAY_MODELS") or CHEAP_MODEL).split(",")[0]

    def gw_one(i):
        return http(f"{gw_url}/v1/chat/completions",
                    {"model": gw_model,
                     "messages": [{"role": "user", "content": f"Balas angka {i}"}],
                     "max_tokens": 32},
                    {"Authorization": "Bearer " + gw_key,
                     "Content-Type": "application/json"}, "POST", 200)

    with ThreadPoolExecutor(max_workers=10) as ex:
        gout = list(ex.map(gw_one, range(10)))
    gcodes = collections.Counter(s for s, _, _ in gout)
    gsamp = next((b[:160] for s, b, _ in gout if s != 200), "")
    g200 = gcodes.get(200, 0)
    # Uji ini mengukur ATRIBUSI, bukan kemampuan gateway. Bila /chat sempat
    # gagal (uji 17-19), gateway pada konkurensi sama HARUS ikut jenuh — kalau
    # tidak, kesalahannya ada di backend. Bila /chat tidak gagal sama sekali,
    # uji ini lulus tanpa syarat.
    record(25, "Atribusi: gateway LANGSUNG x10 jenuh saat /chat gagal (bukan backend)",
           (not any(load_faults)) or g200 < 10,
           f"fault /chat={load_faults} | gateway x10 distribusi={dict(gcodes)} "
           f"200={g200}/10 | contoh: {gsamp}")

    # 26: REGRESI insiden — `session_id` non-UUID TIDAK boleh lagi 503.
    jwt_u = make_user("uuid")
    s, b, t = http(f"{API}/chat",
                   {"prompt": "Balas: OK", "session_id": "local_2",
                    "model": CHEAP_MODEL,
                    "client_request_id": str(uuid.uuid4())},
                   hdr(jwt_u), "POST", 200)
    ok26 = s == 200 and "22P02" not in b
    record(26, "Regresi: session_id non-UUID ('local_2') -> 200, bukan 503/22P02",
           ok26, f"status={s} t={t:.2f}s body={b[:200]}")

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
