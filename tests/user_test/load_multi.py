"""LOAD TEST MULTI-USER NYATA (Katalir, 12 Okt 2026).

MASALAH yang dipecahkan: rate limiter produksi (`rate_limit.py`) membatasi
**10 pesan / 60 detik PER AKUN** (key = user_id). Dengan satu akun, gate brief
(5/10/20/50 user bersamaan) MUSTAHIL diuji - yang terukur hanya limitnya.

Solusi: buat N akun uji sementara lewat Supabase Admin API (service role),
login masing-masing untuk mendapat JWT sendiri, jalankan gate, lalu HAPUS
kembali semua akun uji.

Sisi efek produksi dinyatakan terbuka: akun dibuat di Supabase produksi dengan
domain internal `katalir-internal.dev`, lalu dihapus di akhir (diverifikasi).

Keluaran: tests/user_test/_load_multi_results.json
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
API = "https://gateway.katalir.de5.net/katalir-api"
UA = "Katalir-LoadTest/1.0"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def env_get(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8",
                                          errors="replace").splitlines():
        line = line.strip().lstrip("\ufeff")
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'").strip()
    return ""


SB = env_get("SUPABASE_URL")
SVC = env_get("SUPABASE_SERVICE_ROLE_KEY") or env_get("SUPABASE_SERVICE_KEY")
ANON = env_get("SUPABASE_PUBLISHABLE_KEY") or env_get("SUPABASE_KEY")
print(f"supabase     : {SB}")
print(f"service key  : {'ADA' if SVC else 'TIDAK ADA'} ({len(SVC)} char)")
print(f"anon key     : {'ADA' if ANON else 'TIDAK ADA'}")

N_USERS = 50
TAG = "otonom-lt-" + uuid.uuid4().hex[:6]


def admin(method: str, path: str, body=None):
    req = urllib.request.Request(
        f"{SB}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"apikey": SVC, "Authorization": f"Bearer {SVC}",
                 "Content-Type": "application/json"})
    with OPENER.open(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


print(f"\n[1/4] buat {N_USERS} akun uji ({TAG}-*) ...")
created: list[dict] = []
pwd = "Lt-" + uuid.uuid4().hex[:16] + "!9"
for i in range(N_USERS):
    email = f"{TAG}-{i}@katalir-internal.dev"
    try:
        u = admin("POST", "/auth/v1/admin/users",
                  {"email": email, "password": pwd, "email_confirm": True})
        created.append({"id": u.get("id"), "email": email})
    except urllib.error.HTTPError as e:
        print(f"  gagal buat {email}: HTTP {e.code} {e.read()[:120]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  gagal buat {email}: {type(exc).__name__}")
print(f"  dibuat: {len(created)}")

print("\n[2/4] login tiap akun untuk ambil JWT ...")
tokens: list[str] = []


def login(acc):
    req = urllib.request.Request(
        f"{SB}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": acc["email"], "password": pwd}).encode(),
        method="POST",
        headers={"apikey": ANON, "Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=60) as r:
            return json.loads(r.read().decode()).get("access_token")
    except Exception:  # noqa: BLE001
        return None


with ThreadPoolExecutor(max_workers=10) as ex:
    for t in ex.map(login, created):
        if t:
            tokens.append(t)
print(f"  JWT didapat: {len(tokens)}")


def call(tok: str, i: int) -> dict:
    body = json.dumps({"message": f"ping {i}", "prompt": f"ping {i}"}).encode()
    req = urllib.request.Request(
        f"{API}/chat", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {tok}", "User-Agent": UA})
    t0 = time.time()
    try:
        with OPENER.open(req, timeout=120) as r:
            return {"status": r.status, "ms": round((time.time()-t0)*1000),
                    "body": r.read().decode("utf-8", "replace")[:120]}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ms": round((time.time()-t0)*1000),
                "body": e.read().decode("utf-8", "replace")[:120]}
    except Exception as exc:  # noqa: BLE001
        return {"status": -1, "ms": round((time.time()-t0)*1000),
                "body": f"{type(exc).__name__}"}


def pct(v, p):
    if not v:
        return 0.0
    s = sorted(v)
    return float(s[max(0, min(len(s)-1, int(round(p/100*(len(s)-1)))))])


def level(n: int) -> dict:
    """n user BERBEDA, masing-masing 1 pesan (isolasi per-akun)."""
    use = tokens[:n]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(use)) as ex:
        out = list(ex.map(lambda p: call(p[1], p[0]), list(enumerate(use))))
    ok = [o for o in out if o["status"] == 200]
    lats = [o["ms"] for o in ok]
    return {"n": n, "distinct_users": len(use), "ok": len(ok),
            "fail": n - len(ok), "wall_s": round(time.time()-t0, 2),
            "err_rate": round((n-len(ok))/n, 4) if n else 0,
            "p50_ms": round(pct(lats, 50)), "p95_ms": round(pct(lats, 95)),
            "max_ms": max(lats) if lats else 0,
            "statuses": {str(s): sum(1 for o in out if o["status"] == s)
                         for s in {o["status"] for o in out}},
            "sample_fail": [o["body"] for o in out if o["status"] != 200][:2]}


print("\n[3/4] jalankan gate konkurensi ...")
PLAN = [(1, None), (5, 5), (10, 9), (20, 18), (50, 45)]
res: list[dict] = []
print("=" * 74)
for n, need in PLAN:
    if n > len(tokens):
        r = {"n": n, "ok": 0, "fail": n, "gate": need, "gate_verdict": "BLOCKED",
             "note": f"hanya {len(tokens)} akun uji tersedia"}
    else:
        r = level(n)
        r["gate"] = need
        r["gate_verdict"] = "n/a" if need is None else (
            "PASS" if r["ok"] >= need else "FAIL")
    res.append(r)
    print(f"  n={n:<3} users={r.get('distinct_users','-'):<3} "
          f"ok={r['ok']}/{n} err={r.get('err_rate',0)*100:.0f}% "
          f"p50={r.get('p50_ms',0)}ms p95={r.get('p95_ms',0)}ms "
          f"wall={r.get('wall_s',0)}s [{r['gate_verdict']}]", flush=True)
    if r.get("sample_fail"):
        print(f"      gagal: {r['sample_fail'][0][:110]}")

print("\n[4/4] hapus akun uji ...")
deleted = 0
for acc in created:
    try:
        admin("DELETE", f"/auth/v1/admin/users/{acc['id']}")
        deleted += 1
    except Exception:  # noqa: BLE001
        pass
print(f"  dihapus: {deleted}/{len(created)}")

multi = [r for r in res if r.get("distinct_users", 0) > 1]
p95 = max((r["p95_ms"] for r in multi), default=0)
err = max((r["err_rate"] for r in multi), default=0)
gate_ok = all(r["gate_verdict"] in ("PASS", "n/a") for r in res)
verdict = "PASS" if (gate_ok and p95 < 5000 and err < 0.05) else "FAIL"
print("=" * 74)
print(f"p95 tertinggi : {p95} ms (target <5000)")
print(f"error rate    : {err*100:.1f}% (target <5%)")
print(f"VERDICT       : {verdict}")

(UT / "_load_multi_results.json").write_text(json.dumps({
    "endpoint": f"{API}/chat",
    "method": ("N akun uji BERBEDA (Supabase admin, dihapus setelah selesai); "
               "masing-masing 1 pesan -> isolasi per-akun benar-benar teruji"),
    "test_accounts_created": len(created), "test_accounts_deleted": deleted,
    "tag": TAG, "levels": res, "p95_ms_max": p95,
    "err_rate_max": err, "verdict": verdict,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {UT / '_load_multi_results.json'}")
