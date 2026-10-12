"""Probe cepat pasca-perbaikan: burst 32 dan 100 pada rantai penuh.

Membuktikan lockout `no_key_available` (akibat guard RPM yang membekukan
SELURUH kunci 60 s) sudah hilang setelah perbaikan pair-scoped + TTL presisi.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import gemini_llm as G  # noqa: E402

G.ensure_env()


def burst(n, workers, deadline):
    def one(i):
        r = G.chat_with_fallback(f"Balas angka {i}", level="minimal",
                                 deadline_s=deadline)
        kinds = [a.get("kind") for a in r["attempts"]]
        return r["ok"], r["model"], kinds

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(one, range(n)))
    ok = sum(1 for o in out if o[0])
    fails = [o for o in out if not o[0]]
    return {"n": n, "workers": workers, "ok": ok, "fail": n - ok,
            "rate": round(ok / n, 3) if n else 0.0,
            "elapsed_s": round(time.time() - t0, 2),
            "sample_fail_kinds": [f[2][:6] for f in fails[:2]]}


res = []
for n, w, dl in [(32, 20, 90.0), (100, 40, 120.0)]:
    r = burst(n, w, dl)
    res.append(r)
    print(f"burst n={n:<4} workers={w:<3} -> {r['ok']}/{r['n']} "
          f"rate={r['rate']} {r['elapsed_s']}s", flush=True)
    if r["fail"]:
        print("   contoh kegagalan:", json.dumps(r["sample_fail_kinds"],
                                                ensure_ascii=False), flush=True)

out = pathlib.Path(__file__).resolve().parent / "_gem_burst_probe.json"
out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
print("bukti ->", out)
