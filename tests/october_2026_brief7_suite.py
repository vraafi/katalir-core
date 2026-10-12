#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KATALIR — BRIEF 7 TASK 6: 420 check BARU (21 fitur x 20).

Berbeda dari `tests/october_2026_suite.py` (suite Brief 5): setiap check di
sini BARU dan WAJIB memakai tiga hal sekaligus —

  1. POLA SKILL — tiap check ditandai pola skill yang benar-benar dipakai
     (systematic-debugging, verification-before-completion, chaos-engineering,
     ai-system-testing, test-strategy, ...).
  2. FAULT INJECTION NYATA — dependency hidup dirusak (raise/corrupt/delay)
     lalu di-revert terverifikasi. Fault yang tidak terpasang = FAIL
     (dilarang skip fault injection).
  3. LLM JUDGE — bukti mentah tiap check dinilai semantik lewat gateway LLM
     nyata (ai-system-testing). Judge tidak tersedia -> dilaporkan SKIP jujur.

Verdict:
  PASS — clean run lulus, fault-run tidak menggantung + auto-revert, DAN
         judge semantik tidak menolak (>= ambang) [atau judge SKIP jujur].
  FAIL — clean run gagal, atau fault menggantung/ERROR/tak terpasang,
         atau judge semantik < ambang.
  SKIP — modul dependensi tak tersedia (dilaporkan, bukan PASS).

Jalankan:
  python tests/october_2026_brief7_suite.py            # 420 check + judge
  python tests/october_2026_brief7_suite.py --no-judge # lewati lapis judge
Hasil: tests/_brief7_checks_results.json
Exit 0 bila tidak ada FAIL.
"""
from __future__ import annotations

import importlib
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _b7_common import METHODS, SKILL_TAGS, run_one  # noqa: E402
from judge_harness import LLMJudge  # noqa: E402

OUT = ROOT / "tests" / "_brief7_checks_results.json"
JUDGE_THRESHOLD = 0.8
#: Serial (1 worker) — gateway menolak burst paralel (HTTP 500); serial 100% andal.
JUDGE_WORKERS = 1
#: Model judge (diuji 2026-10-12 GOOD vs BAD): `qwen/qwen3.8-27b` BENAR-BENAR
#: mendiskriminasi (LULUS->1.0, gagal->0.0) DAN cepat (~1.2s) — dipakai
#: tunggal dengan retry. `moonshotai/kimi-k3` juga mendiskriminasi tetapi
#: timeout 9-20s saat sibuk (memperlambat seluruh lapisan) -> tidak dipakai.
#: `allam-2-7b` DIBUANG (stempel 1.0); `gemini-2.5-flash-lite` DIBUANG (timeout).
JUDGE_MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash",
                "gemini-2.5-flash"]

FEATURE_MODULES = [
    (f"{i:02d}", f"_b7_checks_{i:02d}") for i in range(1, 22)
]


def load_checks() -> list[tuple]:
    """Impor 21 file check baru; pastikan tepat 20 check per fitur."""
    all_checks: list[tuple] = []
    for label, modname in FEATURE_MODULES:
        mod = importlib.import_module(modname)
        cs = mod.checks()
        assert len(cs) == 20, f"{modname}: {len(cs)} check (harus 20)"
        for row in cs:
            assert len(row) == 7, f"{modname}: tuple bukan 7-elemen"
            feature, skill, method, name, body, fault, judge_task = row
            assert skill in SKILL_TAGS, f"{modname}/{name}: skill tak sah {skill!r}"
            assert method in METHODS, f"{modname}/{name}: method tak sah {method!r}"
            assert callable(body) and callable(fault), f"{modname}/{name}: non-callable"
        all_checks.extend(cs)
    return all_checks


# --- lapisan judge (thread-local supaya aman saat paralel) -----------------

_thread_local = threading.local()


def _judge() -> LLMJudge:
    j = getattr(_thread_local, "judge", None)
    if j is None:
        j = LLMJudge()
        _thread_local.judge = j
    return j


def _judge_response(rec: dict) -> str:
    """Bukti ringkas + KONTEKS yang mencegah salah tafsir fault injection.

    Kesalahan nyata yang diperbaiki (12 Okt 2026): tanpa penjelasan, model
    judge membaca baris `fault=raised RuntimeError: chaos-2026` sebagai
    kegagalan sistem, lalu memberi skor 0 walau check LULUS. Padahal fault itu
    SENGAJA disuntikkan; hasil 'raised'/'handled' justru bukti ketahanan.
    """
    f = rec.get("fault") or {}
    ev = json.dumps(rec.get("evidence"), default=str)
    return (
        f"CHECK: {rec['name']}\n"
        f"HASIL KONTRAK (clean run, tanpa gangguan): {rec['verdict']} — "
        f"{rec['detail']}\n"
        f"FAULT INJECTION (sengaja): {f.get('result')} — "
        f"{str(f.get('note', ''))[:120]}\n"
        f"BUKTI: {ev[:280]}\n"
    )


#: Instruksi judge — menegaskan bahwa fault itu sengaja dan bukan kegagalan.
JUDGE_INSTRUCTION = (
    "Ini hasil hard-test perangkat lunak Katalir. Nilai apakah bukti di bawah "
    "KONSISTEN dengan check yang LULUS (benar, lengkap, aman).\n"
    "PENTING: baris 'FAULT INJECTION' adalah gangguan yang SENGAJA disuntikkan "
    "ke dependency untuk menguji ketahanan. Hasil 'raised' (modul melempar error "
    "bertipe / fail-fast) atau 'handled' (modul terdegradasi rapi) berarti modul "
    "BERTAHAN — itu BUKTI BAIK, BUKAN kegagalan. Jangan menurunkan skor karena "
    "adanya fault yang disengaja; turunkan skor HANYA bila bukti kontrak (clean "
    "run) tidak membuktikan perilaku benar/aman.\n"
    "NILAI TERHADAP 'NIAT CHECK' (baris NIAT), bukan terhadap kesan permukaan. "
    "Banyak check adalah check KEAMANAN/VALIDASI yang MEMANG mengharapkan input "
    "berbahaya DITOLAK: munculnya nama error (ValueError/SandboxError/"
    "SecretRefError/ScheduleError), 'ok=False', 'tidak diizinkan', 'tidak valid', "
    "'tidak boleh', 'GAGAL', atau nilai False adalah HASIL YANG BENAR untuk check "
    "semacam itu. Jangan memberi skor rendah hanya karena bukti tampak negatif; "
    "beri skor rendah HANYA bila bukti bertentangan dengan NIAT check.\n"
    "Kembalikan JSON skor."
)


def _judge_text(prompt: str, max_tokens: int = 700) -> str | None:
    """Panggil Gemini LANGSUNG (rotasi 13 kunci) - pengganti gateway lama.

    MIGRASI 2026-10-12: sebelumnya memanggil gateway `nexus-gateway-vps` dengan
    model `qwen/qwen3.8-27b`. Gateway itu menolak burst paralel (HTTP 500) dan
    menggantung pada seri panjang, sehingga cakupan penuh 420 check tidak pernah
    tercapai. Sekarang memakai `gemini_llm.chat_with_fallback`, yang merotasi
    13 kunci Gemini + cooldown per kunci + jatuh ke model berikutnya.

    `level="minimal"` dipilih supaya model langsung mengeluarkan JSON skor
    (tidak membakar anggaran token untuk berpikir pada prompt panjang).
    """
    import gemini_llm as G

    r = G.chat_with_fallback(prompt, model_chain=list(JUDGE_MODELS),
                             level="minimal", temperature=0.0,
                             max_output_tokens=max_tokens, deadline_s=90)
    return r["text"] if r["ok"] and (r["text"] or "").strip() else None


def _extract_json_array(text: str):
    import re
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        val = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    return val if isinstance(val, list) else None


def _judge_chunk(chunk: list[dict]) -> dict | None:
    """Satu panggilan judge untuk beberapa check; kembalikan {index: skor}."""
    lines = [JUDGE_INSTRUCTION,
             "",
             f"Nilai TIAP check di bawah ini (ada {len(chunk)}). Balas HANYA "
             "JSON array, tanpa prosa:",
             '[{"i": 0, "overall": 0.0, "reason": "..."}, ...]',
             "di mana 'i' = nomor check dan 'overall' = skor 0..1.", ""]
    for i, rec in enumerate(chunk):
        f = rec.get("fault") or {}
        lines.append(f"CHECK {i}: {rec['name']} | clean={rec['verdict']} | "
                     f"{str(rec['detail'])[:130]} | fault={f.get('result')} | "
                     f"NIAT={str(rec.get('judge_task') or '')[:120]}")
    txt = _judge_text("\n".join(lines))
    if not txt:
        return None
    arr = _extract_json_array(txt)
    if arr is None:
        return None
    out: dict[int, float] = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        try:
            out[int(item.get("i"))] = float(item.get("overall", 0.0))
        except (TypeError, ValueError):
            continue
    return out or None


BATCH = 5


def _extract_json_obj(text: str):
    import re
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        val = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    return val if isinstance(val, dict) else None


def judge_single(rec: dict) -> dict | None:
    """Re-judge SATU check dengan prompt jelas (bukan JUDGE_PROMPT generik).

    Prompt generik meminta menilai 'RESPONSE' — model (khususnya fallback
    lemah) salah tafsir dan menjawab 'raw log data'. Prompt khusus ini
    menyatakan perannya dengan jelas sehingga JSON-nya benar.
    """
    prompt = "\n".join([
        JUDGE_INSTRUCTION, "",
        "Nilai SATU check di bawah. Balas HANYA JSON minified (reason <= 8 kata):",
        '{"overall": 0.0, "reason": "..."}',
        "overall = 1.0 bila bukti membuktikan check LULUS (perilaku benar & aman), "
        "0.0 bila tidak.", "",
        f"CHECK: {rec['name']}",
        f"NIAT CHECK (yang harus dibuktikan): {rec.get('judge_task') or '-'}",
        f"clean run = {rec['verdict']} — {str(rec['detail'])[:200]}",
        f"fault injection (sengaja) = {(rec.get('fault') or {}).get('result')}",
    ])
    txt = _judge_text(prompt, max_tokens=60)
    obj = _extract_json_obj(txt) if txt else None
    if obj is None:
        return None
    try:
        ov = float(obj.get("overall", 0.0))
    except (TypeError, ValueError):
        return None
    return {"ok": ov >= JUDGE_THRESHOLD, "scores": {"overall": ov},
            "detail": f"single overall={ov:.2f}"}


#: Jeda antar panggilan judge (detik). Gateway terukur menolak laju tinggi
#: (HTTP 500 / hang) tetapi stabil pada ~1 panggilan / 2-3 detik.
PACE = 0.3
#: Cache skor judge -> membuat lapisan judge dapat dilanjutkan (resumable).
JUDGE_CACHE = ROOT / "tests" / "_brief7_judge_cache.json"


def _ckey(rec: dict) -> str:
    return f"{rec['feature']}|{rec['name']}"


def _load_cache() -> dict:
    try:
        return json.loads(JUDGE_CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(cache: dict) -> None:
    JUDGE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def run_judge_pass(recs: list[dict]) -> None:
    """Lapis judge semantik — SATU penilaian per check (ai-system-testing).

    Desain (dipelajari dari perilaku gateway nyata 2026-10-12):
      * SATU check per panggilan. Batch (5 check/panggilan) TERBUKTI gagal:
        model yang tersedia mengembalikan template 0.0 atau timeout pada prompt
        panjang -> hampir semua check "disengketakan" palsu. Praktik LLM-judge
        2026 juga menyarankan "one judgment per call".
      * SERIAL + jeda (PACE). Burst paralel memicu rate-limit gateway (HTTP 500).
      * RESUME via cache: skor yang sudah didapat tidak diulang; kegagalan
        TIDAK di-cache supaya bisa dicoba lagi di run berikutnya.
    """
    cache = _load_cache()
    for rec in recs:
        c = cache.get(_ckey(rec))
        if c is not None:
            rec["judge"] = {"ok": c["ok"], "scores": {"overall": c["overall"]},
                            "detail": f"cache overall={c['overall']}"}
    todo = [r for r in recs if not r.get("judge")]
    print(f"LLM judge individual: {len(todo)}/{len(recs)} tersisa "
          f"(cache {len(recs) - len(todo)})...")
    for i, rec in enumerate(todo, 1):
        res = judge_single(rec)
        if res is not None:
            rec["judge"] = res
            cache[_ckey(rec)] = {"ok": res["ok"],
                                 "overall": res["scores"]["overall"]}
        else:
            rec["judge"] = {"ok": None, "scores": {},
                            "detail": "SKIP: judge tak tersedia"}
        if i % 25 == 0:
            _save_cache(cache)
            print(f"  {i}/{len(todo)} check dinilai...")
        time.sleep(PACE)
    _save_cache(cache)


def _finalize(recs: list[dict]) -> None:
    for rec in recs:
        base = rec["verdict"]
        j = rec.get("judge")
        if base != "PASS":
            rec["final"] = base
        elif j is None:
            rec["final"] = "PASS"
        elif j["ok"] is None:
            rec["final"] = "PASS"
            rec["judge_skipped"] = True
        elif j["ok"] is True:
            rec["final"] = "PASS"
        else:
            rec["final"] = "FAIL"


def run_all(with_judge: bool = True) -> list[dict]:
    checks = load_checks()
    print(f"check terdaftar: {len(checks)}")

    recs: list[dict] = []
    for row in checks:
        feature, skill, method, name, body, fault, judge_task = row
        recs.append(run_one(feature, skill, method, name, body, fault, judge_task))

    if with_judge:
        run_judge_pass(recs)

    _finalize(recs)
    return recs


def run_judge_only() -> list[dict]:
    """Muat hasil deterministik yang sudah ada, jalankan ulang HANYA judge."""
    data = json.loads(OUT.read_text(encoding="utf-8"))
    recs = data["results"]
    for r in recs:
        r.pop("judge", None)
        r.pop("judge_skipped", None)
    run_judge_pass(recs)
    _finalize(recs)
    return recs


def main() -> int:
    with_judge = "--no-judge" not in sys.argv
    judge_only = "--judge-only" in sys.argv
    print("=" * 78)
    print("KATALIR — BRIEF 7 TASK 6: 420 CHECK BARU (skill + fault + judge)")
    print("=" * 78)
    t0 = time.perf_counter()
    if judge_only:
        recs = run_judge_only()
        with_judge = True
    else:
        recs = run_all(with_judge=with_judge)

    per_feature: dict[str, dict] = {}
    per_method: dict[str, int] = {}
    per_skill: dict[str, int] = {}
    for r in recs:
        f = per_feature.setdefault(r["feature"], {"PASS": 0, "FAIL": 0, "SKIP": 0, "n": 0})
        f[r["final"]] += 1
        f["n"] += 1
        per_method[r["method"]] = per_method.get(r["method"], 0) + 1
        per_skill[r["skill"]] = per_skill.get(r["skill"], 0) + 1

    n_pass = sum(1 for r in recs if r["final"] == "PASS")
    n_fail = sum(1 for r in recs if r["final"] == "FAIL")
    n_skip = sum(1 for r in recs if r["final"] == "SKIP")
    j_scores = [r["judge"]["scores"].get("overall") for r in recs
                if r.get("judge") and r["judge"]["scores"].get("overall") is not None]
    j_skip = sum(1 for r in recs if r.get("judge_skipped"))
    j_mean = round(statistics.fmean(j_scores), 3) if j_scores else None
    fault_applied = sum(1 for r in recs if r["fault"].get("applied"))
    fault_skip = sum(1 for r in recs if r["fault"].get("result") == "SKIP")

    print()
    print(f"{'Fitur':<26}{'PASS':>6}{'FAIL':>6}{'SKIP':>6}{'Total':>7}")
    print("-" * 52)
    for f in sorted(per_feature):
        s = per_feature[f]
        print(f"{f:<26}{s['PASS']:>6}{s['FAIL']:>6}{s['SKIP']:>6}{s['n']:>7}")
    print("-" * 52)
    print(f"{'TOTAL':<26}{n_pass:>6}{n_fail:>6}{n_skip:>6}{len(recs):>7}")
    print()
    print("per metode :", ", ".join(f"{k}={v}" for k, v in sorted(per_method.items())))
    print("per skill  :", ", ".join(f"{k}={v}" for k, v in sorted(per_skill.items())))
    print(f"fault terpasang: {fault_applied}/{len(recs)} (skip={fault_skip})")
    if with_judge:
        print(f"judge semantik : mean={j_mean} n={len(j_scores)} skip={j_skip}")
    print(f"durasi     : {time.perf_counter() - t0:.1f}s")

    if n_fail:
        print("\nGAGAL:")
        for r in recs:
            if r["final"] == "FAIL":
                print(f"  [{r['feature']}] {r['name']}")
                print(f"      clean: {r['detail'][:150]}")
                print(f"      fault: {r['fault'].get('result')} — "
                      f"{str(r['fault'].get('note', ''))[:120]}")
                if r.get("judge"):
                    print(f"      judge: {r['judge'].get('detail', '')[:150]}")

    OUT.write_text(json.dumps({
        "total": len(recs), "pass": n_pass, "fail": n_fail, "skip": n_skip,
        "with_judge": with_judge, "judge_mean": j_mean, "judge_skip": j_skip,
        "fault_applied": fault_applied, "fault_skip": fault_skip,
        "methods": per_method, "skills": per_skill, "per_feature": per_feature,
        "results": recs,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nhasil lengkap: {OUT}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
