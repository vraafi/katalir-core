"""TASK 5 - LOAD TEST dengan user concurrent (Katalir, 12 Okt 2026).

Target brief:
  1 user  -> ukur latency
  5  concurrent -> semua 200
  10 concurrent -> >=9/10 sukses
  20 concurrent -> >=18/20 sukses
  50 concurrent -> >=45/50 sukses
  p95 latency < 5 s ; error rate < 5 %

Endpoint NYATA (backend VPS produksi): POST {API}/chat
Auth: JWT user asli (hasil refresh di bootstrap_session.py).

BATASAN YANG DILAPORKAN APA ADANYA: kita hanya punya SATU akun user uji, jadi
semua "user" concurrent memakai JWT yang sama. Ini mengukur kapasitas jalur
LLM/backend, BUKAN isolasi multi-tenant. Dinyatakan eksplisit di laporan.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
API = "https://gateway.katalir.de5.net/katalir-api"
UA = "Katalir-UserTest/1.0"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SESS = json.loads((UT / "_session.json").read_text(encoding="utf-8"))
TOK = SESS["session"]["access_token"]


def one_call(i: int) -> dict:
    body = json.dumps({"message": f"ping {i}", "prompt": f"ping {i}"}).encode()
    req = urllib.request.Request(
        f"{API}/chat", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOK}", "User-Agent": UA})
    t0 = time.time()
    try:
        with OPENER.open(req, timeout=90) as r:
            txt = r.read().decode("utf-8", "replace")
            return {"i": i, "status": r.status, "ms": round((time.time()-t0)*1000),
                    "body": txt[:160]}
    except urllib.error.HTTPError as e:
        return {"i": i, "status": e.code, "ms": round((time.time()-t0)*1000),
                "body": e.read().decode("utf-8", "replace")[:160]}
    except Exception as exc:  # noqa: BLE001
        return {"i": i, "status": -1, "ms": round((time.time()-t0)*1000),
                "body": f"{type(exc).__name__}: {str(exc)[:120]}"}


def pct(vals: list[int], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return float(s[k])


def level(n: int, workers: int) -> dict:
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(one_call, range(n)))
    ok = [o for o in out if o["status"] == 200]
    lats = [o["ms"] for o in ok]
    return {
        "n": n, "workers": workers,
        "ok": len(ok), "fail": n - len(ok),
        "wall_s": round(time.time() - t0, 2),
        "err_rate": round((n - len(ok)) / n, 4) if n else 0.0,
        "p50_ms": round(pct(lats, 50)), "p95_ms": round(pct(lats, 95)),
        "max_ms": max(lats) if lats else 0,
        "mean_ms": round(statistics.mean(lats)) if lats else 0,
        "statuses": {str(s): sum(1 for o in out if o["status"] == s)
                     for s in {o["status"] for o in out}},
        "sample_fail": [o["body"] for o in out if o["status"] != 200][:3],
    }


PLAN = [(1, 1), (5, 5), (10, 10), (20, 20), (50, 50)]
GATES = {1: None, 5: 5, 10: 9, 20: 18, 50: 45}

res: list[dict] = []
print(f"endpoint : POST {API}/chat")
print(f"token    : {len(TOK)} char (user {SESS['session']['user'].get('email')})")
print("=" * 74)
for n, w in PLAN:
    r = level(n, w)
    need = GATES[n]
    verdict = "n/a" if need is None else ("PASS" if r["ok"] >= need else "FAIL")
    r["gate"] = need
    r["gate_verdict"] = verdict
    res.append(r)
    print(f"  n={n:<3} workers={w:<3} ok={r['ok']}/{n} "
          f"err={r['err_rate']*100:.1f}%  p50={r['p50_ms']}ms "
          f"p95={r['p95_ms']}ms max={r['max_ms']}ms  wall={r['wall_s']}s  "
          f"[{verdict}]", flush=True)
    if r["sample_fail"]:
        print(f"      contoh gagal: {r['sample_fail'][0][:110]}")

all_ok = [r for r in res if r["n"] > 1]
p95_overall = max((r["p95_ms"] for r in all_ok), default=0)
err_overall = max((r["err_rate"] for r in all_ok), default=0)
print("=" * 74)
print(f"p95 tertinggi (n>1) : {p95_overall} ms  (target < 5000 ms)")
print(f"error rate tertinggi: {err_overall*100:.1f}%  (target < 5%)")
gate_ok = all(r["gate_verdict"] in ("PASS", "n/a") for r in res)
verdict = ("PASS" if (gate_ok and p95_overall < 5000 and err_overall < 0.05)
           else "FAIL")
print(f"VERDICT LOAD TEST   : {verdict}")

(UT / "_load_test_results.json").write_text(json.dumps({
    "endpoint": f"{API}/chat",
    "limitation": ("satu akun uji dipakai untuk semua koneksi concurrent; "
                   "mengukur kapasitas backend, bukan isolasi multi-tenant"),
    "levels": res, "p95_ms_max": p95_overall,
    "err_rate_max": err_overall, "verdict": verdict,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {UT / '_load_test_results.json'}")
