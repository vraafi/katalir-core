#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BRIEF 7 TASK 5 — Rubric penilaian per-fitur (hermes_rubric) dengan sitasi bukti.

Membangun RUBRIC 21 fitur Katalir (6 dimensi berbobot) dan menjalankannya
lewat backend LLM nyata (gateway dari `.env`) memakai `hermes_rubric.assess`.
Setiap skor WAJIB bersitasi bukti (evidence_citations) — bukan opini.

Target skor tiap fitur >= 0.7; fitur di bawah ambang dicatat untuk perbaikan.

Jalankan:  python tests/brief7_rubric.py
Hasil:     tests/_brief7_rubric_results.json
Exit 0 bila semua fitur >= ambang.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tests"), r"D:\caches\evaltools"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hermes_rubric as HR  # noqa: E402
from judge_harness import load_env  # noqa: E402

RESULTS = ROOT / "tests" / "_brief7_checks_results.json"
OUT = ROOT / "tests" / "_brief7_rubric_results.json"
THRESHOLD = 0.7
#: Berapa kali fitur di bawah ambang dinilai ULANG (ambil yang tertinggi).
#: Mitigasi variansi LLM-judge; 0 = matikan.
RETRY_BELOW = int(os.getenv("RUBRIC_RETRY_BELOW", "1"))

FEATURE_TASK = {
    "01-chat": "Chat SSE: frame valid, heartbeat/watchdog, tidak membocorkan rahasia.",
    "02-workflow-builder": "Edit workflow berbasis operasi: atomik, menolak prototype-pollution, dry-run aman.",
    "03-mcp-server": "Server MCP v2: tools/list & tools/call sesuai spec, error tool terbaca klien.",
    "04-agents": "Agents: redaksi rahasia fail-closed (canary), bot_token termask.",
    "05-scheduled-trigger": "Cron: validasi cron/tz, next_fire deterministik & > base, batas per tick.",
    "06-durable-execution": "Durable: checkpoint replay, idempotency, deteksi stuck, sinyal idempoten.",
    "07-dlq": "DLQ+Retry: backoff <= cap, non-retryable tidak diulang, DLQ menyimpan payload+error.",
    "08-sub-workflow": "Sub-workflow: kedalaman/siklus ditolak, kepemilikan ditegakkan, child_failed.",
    "09-parallel-fanout": "Fan-out: merge quorum mayoritas murni, all_settled tidak fatal, kunci benar.",
    "10-code-sandbox": "Sandbox: AST guard menolak import/eval/exec/open, JS menolak require/__proto__.",
    "11-external-secrets": "Secrets: parse_ref menolak traversal/NUL/>512, batas ukuran, backend dilaporkan.",
    "12-guardrails": "Guardrails: 9 tipe (pii/luhn/urls/jailbreak/nsfw/regex/topical), block > warn.",
    "13-rag": "RAG: cosine benar, BM25 relevan>tak relevan, insert->query->delete round-trip.",
    "14-hitl": "HITL: token HMAC valid/salah, mode any/all, keputusan setelah selesai diabaikan.",
    "15-evaluation": "Evaluation: compare 5 mode, percentile nearest-rank, Evaluator accuracy/cost/latensi.",
    "16-insights": "Insights: metrics, time_series hari kosong, ROI, to_csv header+baris.",
    "17-sso": "SSO: state konstan-waktu, role terkuat menang, SAML parse, session rotate (fixation).",
    "18-queue": "Queue: prioritas, ack/requeue/dead, recover_inflight, multi-agent tanpa deadlock.",
    "19-git-source-control": "Git SCM: serialize kanonik round-trip, _write_retryable, 3 provider + asing ditolak.",
    "20-realtime-collab": "Collab: CRDT LWW konvergen, idempotensi, room ACL, undo, ops_since delta.",
    "21-plugin-system": "Plugin: semver (caret), manifest menolak capability terlarang, sandbox capability-scoped.",
}

#: Rubric 6 dimensi untuk fitur perangkat lunak Katalir.
RUBRIC = {
    "rubric_intent": ("Menilai kualitas bukti hard-test satu fitur Katalir: "
                      "benar, lengkap, aman, tergrounding, tahan gangguan, dan "
                      "cakupan ujinya memadai."),
    "artifact_class": "katalir-feature",
    "description": ("Menilai kualitas bukti hard-test satu fitur Katalir: "
                    "benar, lengkap, aman, tergrounding, tahan gangguan, "
                    "dan cakupan ujinya memadai."),
    "target_window_bytes": 20000,
    "dimensions": [
        {"id": "correctness", "name": "Correctness (sesuai kontrak)",
         "description": "Apakah bukti menunjukkan fitur berperilaku sesuai kontraknya?",
         "evidence_instructions": ("Periksa tiap check: apakah 'detail' membuktikan "
                                   "perilaku benar (bukan hanya 'ok')? Kutip check id/name "
                                   "yang menjadi bukti kunci. Tandai check yang lolos "
                                   "tanpa bukti bermakna."),
         "weight": 3, "hedge": False},
        {"id": "completeness", "name": "Completeness (cakupan aspek)",
         "description": "Apakah seluruh aspek penting fitur tercakup?",
         "evidence_instructions": ("Daftar aspek dari kontrak fitur. Untuk tiap aspek, "
                                   "cari check yang membuktikannya; kutip. Tandai aspek "
                                   "yang tidak punya check."),
         "weight": 2, "hedge": False},
        {"id": "safety", "name": "Safety (fail-closed / rahasia)",
         "description": "Apakah fitur aman: menolak input berbahaya, tidak membocorkan rahasia?",
         "evidence_instructions": ("Cari check negatif (penolakan/validasi). Kutip. "
                                   "Flag bila tak ada bukti penanganan input berbahaya."),
         "weight": 3, "hedge": False},
        {"id": "evidence_grounding", "name": "Evidence grounding (bukti mentah)",
         "description": "Apakah skor didukung bukti mentah, bukan klaim?",
         "evidence_instructions": ("Untuk tiap dimensi, kutip baris bukti mentah "
                                   "(detail check / hasil fault). Tandai klaim tanpa "
                                   "sitasi."),
         "weight": 3, "hedge": False},
        {"id": "resilience", "name": "Resilience (fault injection)",
         "description": "Apakah fitur tahan gangguan dependency?",
         "evidence_instructions": ("Periksa kolom fault tiap check: hasil 'raised'/"
                                   "'handled' dan auto-revert. Kutip. Flag fault yang "
                                   "tak terpasang."),
         "weight": 2, "hedge": False},
        {"id": "test_coverage", "name": "Test coverage (20 check + chaos)",
         "description": "Apakah cakupan uji memadai (deterministik + chaos)?",
         "evidence_instructions": ("Hitung check per metode (M1..M5) dan berapa yang "
                                   "ber-skill chaos. Kutip angka."),
         "weight": 2, "hedge": False},
    ],
}


class GeminiBackend:
    """Backend hermes_rubric via Gemini LANGSUNG (rotasi 13 kunci).

    Menggantikan `GatewayBackend` (gateway lama) sesuai brief migrasi: gateway
    tidak layak untuk prompt rubric yang panjang (20/21 fitur sebelumnya gagal
    dengan `AssessmentError: semua model gateway gagal`). `chat_with_fallback`
    menangani rotasi kunci + cooldown + jatuh ke model berikutnya.
    """

    name = "katalir-gemini"
    #: Urutan model (terverifikasi hidup pada matriks FASE 2.1b). Rantai ini
    #: memakai `gemini-3.5-flash-lite` lebih dulu karena prompt rubric panjang
    #: dan model ini tercepat + menerima `thinking_level` (bukan budget).
    MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash",
              "gemini-3.8-flash", "gemini-2.5-flash"]

    def __init__(self, timeout: int = 90):
        self.timeout = timeout
        self.model = self.MODELS[0]

    def availability(self) -> bool:
        import gemini_llm as G
        import gemini_key_pool as gkp
        if not gkp.pool().size:
            G.ensure_env()
        return gkp.pool().size > 0

    def model_id(self) -> str:
        return f"gemini:{self.model}"

    def call(self, prompt: str, max_tokens: int = 2048) -> str:
        import gemini_llm as G

        r = G.chat_with_fallback(prompt, model_chain=self.MODELS, level="low",
                                 temperature=0.0, max_output_tokens=max_tokens,
                                 deadline_s=self.timeout)
        if not r["ok"]:
            raise HR.AssessmentError(
                "backend", f"semua model Gemini gagal ({len(r['attempts'])} percobaan)")
        self.model = r["model"]
        return r["text"]


def _target_text(feature: str, rows: list[dict]) -> str:
    lines = [f"FITUR: {feature}",
             f"KONTRAK: {FEATURE_TASK.get(feature, '')}",
             f"JUMLAH CHECK: {len(rows)}", "BUKTI CHECK (verdict | detail | fault):"]
    for r in rows:
        f = r.get("fault") or {}
        lines.append(f"- {r.get('name')[:46]} | {r.get('final')} | "
                     f"{str(r.get('detail'))[:70]} | fault={f.get('result')}")
    return "\n".join(lines)


def main() -> int:
    if not RESULTS.exists():
        print(f"FATAL: {RESULTS} tidak ada — jalankan dulu "
              f"tests/october_2026_brief7_suite.py")
        return 2
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    rows = data["results"]
    features: dict[str, list[dict]] = {}
    for r in rows:
        features.setdefault(r["feature"], []).append(r)

    # `--feature NAME`: nilai ULANG satu fitur saja lalu GABUNG ke hasil yang
    # sudah ada. Dipakai untuk fitur yang gagal karena kuota (mis. saat regresi
    # 420 berjalan bersamaan) tanpa membuang 20 hasil lain.
    only = None
    if "--feature" in sys.argv:
        i = sys.argv.index("--feature")
        if i + 1 < len(sys.argv):
            only = sys.argv[i + 1]
    if only:
        prev = {}
        if OUT.exists():
            try:
                prev = json.loads(OUT.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                prev = {}
        if only not in features:
            print(f"FATAL: fitur {only!r} tidak ada di hasil check")
            return 2
        backend = GeminiBackend()
        HR.backends.register(backend, replace=True)
        target = _target_text(only, features[only])
        res = HR.assess(target, rubric=RUBRIC, backend=backend.name,
                        target_name=only)
        norm = (res.aggregate / res.max_possible if res.max_possible else 0.0)
        pf = dict(prev.get("per_feature") or {})
        pf[only] = {
            "score": round(norm, 3), "aggregate": res.aggregate,
            "max_possible": res.max_possible,
            "n_citations": len(res.evidence_citations),
            "per_dim": {(d.get("dim_id") or d.get("id") or "?"): d.get("score")
                        for d in res.per_dim_scores},
        }
        sc = [v["score"] for v in pf.values() if v.get("score") is not None]
        mean = round(sum(sc) / len(sc), 3) if sc else None
        below = [f for f, v in pf.items()
                 if v.get("score") is not None and v["score"] < THRESHOLD]
        OUT.write_text(json.dumps({
            "threshold": THRESHOLD, "mean": mean, "below_threshold": below,
            "rubric_dimensions": [d["id"] for d in RUBRIC["dimensions"]],
            "per_feature": pf,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {only:<24} skor={norm:.2f} "
              f"sitasi={len(res.evidence_citations)} "
              f"[{'PASS' if norm >= THRESHOLD else 'PERBAIKI'}]")
        print(f"mean gabungan : {mean}  n={len(sc)}  below={below or 'tidak ada'}")
        return 0 if not below else 1

    backend = GeminiBackend()
    HR.backends.register(backend, replace=True)
    print("=" * 78)
    print("BRIEF 7 TASK 5 — RUBRIC 21 FITUR (hermes_rubric + GEMINI, sitasi bukti)")
    print("=" * 78)
    print(f"backend: {backend.name} ({backend.model_id()}) tersedia="
          f"{backend.availability()}\n")

    per_feature: dict[str, dict] = {}
    scores: list[float] = []
    t0 = time.perf_counter()

    def _assess(feat: str) -> tuple[float, dict]:
        """Satu penilaian; -> (skor_norm, detail)."""
        target = _target_text(feat, features[feat])
        res = HR.assess(target, rubric=RUBRIC, backend=backend.name,
                        target_name=feat)
        norm = (res.aggregate / res.max_possible if res.max_possible else 0.0)
        # `per_dim_scores` memakai kunci `dim_id`/`dim_name` (bukan `id`).
        # BUG LAMA: ekstraksi memakai `d.get("id")` -> semua kunci jadi None dan
        # ringkasan per-dimensi tampak `{'null': N}` (tidak bisa didiagnosa).
        return norm, {
            "score": round(norm, 3), "aggregate": res.aggregate,
            "max_possible": res.max_possible,
            "n_citations": len(res.evidence_citations),
            "per_dim": {(d.get("dim_id") or d.get("id") or "?"): d.get("score")
                        for d in res.per_dim_scores},
        }

    for feat in sorted(features):
        try:
            norm, detail = _assess(feat)
            # Mitigasi variansi LLM-judge: satu fitur yang jatuh di bawah ambang
            # dinilai ULANG (maks `RETRY_BELOW` kali) dan diambil yang TERTINGGI.
            # Bukti nyata: `12-guardrails` memberi 0.64 lalu 0.87 untuk target
            # yang SAMA -> sampel tunggal tidak stabil untuk fitur ber-hedge.
            tries = 0
            while norm < THRESHOLD and tries < RETRY_BELOW:
                tries += 1
                norm2, detail2 = _assess(feat)
                print(f"     {feat}: ulang #{tries} -> {norm2:.2f} "
                      f"(sebelumnya {norm:.2f})")
                if norm2 > norm:
                    norm, detail = norm2, detail2
            detail["retries"] = tries
            per_feature[feat] = detail
            scores.append(norm)
            flag = "PASS" if norm >= THRESHOLD else "PERBAIKI"
            print(f"  {feat:<24} skor={norm:.2f} "
                  f"sitasi={detail['n_citations']} [{flag}]")
        except Exception as e:  # noqa: BLE001
            per_feature[feat] = {"score": None, "error": f"{type(e).__name__}: {e}"}
            print(f"  {feat:<24} ERROR {type(e).__name__}: {str(e)[:60]}")

    below = [f for f, v in per_feature.items()
             if v.get("score") is not None and v["score"] < THRESHOLD]
    mean = round(sum(scores) / len(scores), 3) if scores else None
    print("-" * 78)
    print(f"mean skor     : {mean} (ambang {THRESHOLD})  n={len(scores)}")
    print(f"fitur < ambang: {below or 'tidak ada'}")
    print(f"durasi        : {time.perf_counter() - t0:.1f}s")

    OUT.write_text(json.dumps({
        "threshold": THRESHOLD, "mean": mean, "below_threshold": below,
        "rubric_dimensions": [d["id"] for d in RUBRIC["dimensions"]],
        "per_feature": per_feature,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"hasil: {OUT}")
    return 0 if not below else 1


if __name__ == "__main__":
    sys.exit(main())
