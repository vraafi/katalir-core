#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BRIEF 7 TASK 4 (re-run) — tool_eval_bench dengan provider GEMINI.

Perubahan dari versi gateway lama:
  * Endpoint = Gemini NATIVE (`generativelanguage.googleapis.com`,
    `wire_format="gemini"`), memakai adapter `tool_eval_bench.adapters.gemini`
    (menerjemahkan `systemInstruction`, `functionResponse`, dan
    `thoughtSignature` Gemini 3).
  * Kunci DIROTASI: skenario dipecah menjadi beberapa bagian, setiap bagian
    memakai kunci berbeda dari `gemini_key_pool`. Ini perlu karena kuota Gemini
    bersifat PER (project, model) — satu kunci saja akan kena 429 jauh sebelum
    69+28 skenario selesai.
  * Model default = `gemini-3.5-flash-lite` (terverifikasi hidup & tercepat
    pada matriks FASE 2.1b), dapat diubah lewat `GEMINI_TASK4_MODEL`.

Jalankan:  python tests/brief7_toolbench.py
Hasil:     tests/_brief7_toolbench_results.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tests"), r"D:\caches\evaltools"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from judge_harness import load_env  # noqa: E402
from tool_eval_bench.api import run_benchmark  # noqa: E402
from tool_eval_bench.evals.scenarios import (  # noqa: E402
    ALL_SCENARIOS,
    HARDMODE_SCENARIOS,
)

import gemini_key_pool as gkp  # noqa: E402

OUT = ROOT / "tests" / "_brief7_toolbench_results.json"
GEMINI_BASE = "https://generativelanguage.googleapis.com"
MODEL = os.getenv("GEMINI_TASK4_MODEL", "gemini-3.5-flash-lite")
THRESHOLD = 60.0
MAX_CHUNKS = int(os.getenv("GEMINI_TASK4_CHUNKS", "6"))


def _rotate_keys(model: str) -> list[str]:
    """Kunci mentah untuk rotasi (fingerprint siap -> ambil nilainya).

    `judge_harness.load_env()` hanya mengembalikan dict, jadi `.env` WAJIB
    dimuat ke `os.environ` lebih dulu - kalau tidak, pool terlihat kosong.
    """
    import gemini_llm as G

    G.ensure_env()
    p = gkp.pool()
    fps = p.available(model) or [fp for _, _, fp in p._entries]  # noqa: SLF001
    out = []
    for fp in fps:
        k = p.key_for(fp)
        if k:
            out.append(k)
    return out[:MAX_CHUNKS]


def _split(items: list, n: int) -> list[list]:
    n = max(1, min(n, len(items)))
    return [items[i::n] for i in range(n)]


def _run(label: str, scenarios: list) -> dict:
    keys = _rotate_keys(MODEL)
    print(f"\n-- {label}: {len(scenarios)} skenario, {len(keys)} kunci dirotasi --")
    if not keys:
        print("   TIDAK ADA KUNCI GEMINI")
        return {"label": label, "n": len(scenarios), "final_score": None,
                "rating": None, "category_scores": [], "status": "no_keys",
                "seconds": 0.0, "chunks": []}

    chunks = _split(scenarios, len(keys))
    t0 = time.perf_counter()
    parts, cats_acc = [], {}
    for i, (key, chunk) in enumerate(zip(keys, chunks), 1):
        if not chunk:
            continue
        try:
            res = asyncio.run(run_benchmark(
                model=MODEL, base_url=GEMINI_BASE, api_key=key,
                backend="gemini", wire_format="gemini",
                scenarios=chunk, persist=False, concurrency=1, max_turns=6,
                timeout_seconds=60, probe_engine=False,
            ))
            fs = res.get("final_score")
            print(f"   bagian {i}: n={len(chunk)} final_score={fs} "
                  f"rating={res.get('rating')}")
        except Exception as exc:  # noqa: BLE001
            fs, res = None, {}
            print(f"   bagian {i}: GAGAL {type(exc).__name__}: {str(exc)[:160]}")
        parts.append({"chunk": i, "n": len(chunk), "final_score": fs,
                      "rating": res.get("rating"),
                      "status": res.get("status")})
        for c in ((res.get("scores", {}) or {}).get("category_scores") or []):
            nm = str(c.get("category", c.get("label", "?")))
            cats_acc.setdefault(nm, []).append(c.get("score", c.get("percent")))

    dt = time.perf_counter() - t0
    scored = [p for p in parts if p["final_score"] is not None]
    overall = (round(sum(p["final_score"] * p["n"] for p in scored)
                     / sum(p["n"] for p in scored), 1) if scored else None)
    cats = [{"category": k, "score": round(sum(v) / len(v), 1) if v else None}
            for k, v in cats_acc.items()]
    print(f"   final_score gabungan={overall} ({dt:.0f}s)")
    for c in cats:
        print(f"     {c['category']:<28} {c['score']}")
    return {"label": label, "n": len(scenarios), "final_score": overall,
            "rating": (scored[0]["rating"] if scored else None),
            "category_scores": cats, "status": "ok" if scored else "failed",
            "seconds": round(dt, 1), "chunks": parts}


def main() -> int:
    print("=" * 78)
    print("BRIEF 7 TASK 4 (re-run) — tool_eval_bench via GEMINI NATIVE")
    print("=" * 78)
    print(f"model={MODEL}  base={GEMINI_BASE}  ambang={THRESHOLD}")
    runs = [_run("deterministik (ALL_SCENARIOS)", ALL_SCENARIOS),
            _run("hard mode (HARDMODE_SCENARIOS)", HARDMODE_SCENARIOS)]

    finals = [r["final_score"] for r in runs if r["final_score"] is not None]
    overall = round(sum(finals) / len(finals), 1) if finals else None
    low = [r["label"] for r in runs
           if r["final_score"] is not None and r["final_score"] < THRESHOLD]
    print("\n" + "-" * 78)
    print(f"skor akhir rata-rata : {overall} (ambang {THRESHOLD})")
    print(f"set di bawah ambang  : {low or 'tidak ada'}")

    OUT.write_text(json.dumps({"provider": "gemini", "model": MODEL,
                               "base_url": GEMINI_BASE, "threshold": THRESHOLD,
                               "overall": overall, "below_threshold": low,
                               "runs": runs}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"hasil: {OUT}")
    return 0 if overall is not None and overall >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
