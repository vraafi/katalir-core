#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brief 7 TASK 1 — lapisan LLM-as-a-Judge di atas hasil 420 check.

Tujuan: membandingkan penilaian DETERMINISTIK (aturan pasti, 420/420 PASS)
dengan penilaian SEMANTIK (LLM judge atas bukti yang sama). Deterministik
menjawab "apakah kode berperilaku sesuai kontrak?", judge menjawab "apakah
bukti itu benar-benar membuktikan fitur bekerja, lengkap, dan aman?".

Menjalankan judge lewat gateway NYATA dari `.env` (LLM_GATEWAY_URL/KEY).
Bila gateway tidak tersedia -> SKIP jujur (tidak dihitung lulus).

Jalankan:
    python tests/judge_layer.py            # 21 fitur
    python tests/judge_layer.py --per-check 21   # + sampel 21 check individual
Hasil: tests/_october_2026_judge.json + tabel di konsol.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from judge_harness import LLMJudge  # noqa: E402

RESULTS = ROOT / "tests" / "_october_2026_results.json"
OUT = ROOT / "tests" / "_october_2026_judge.json"
THRESHOLD = 0.8

#: Kontrak ringkas tiap fitur (dipakai sebagai bagian "task" untuk judge).
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


def _evidence_text(rows: list[dict], limit: int = 20) -> str:
    lines = []
    for r in rows[:limit]:
        f = r.get("fault") or {}
        lines.append(
            f"- [{r.get('method')}] {r.get('name')}: {r.get('verdict')} | "
            f"{str(r.get('detail'))[:110]} | fault={f.get('result')}"
        )
    return "\n".join(lines)


def _task_for(feature: str) -> str:
    return ("Evaluasi BUKTI HARD TEST untuk fitur Katalir berikut. Jawab apakah "
            "bukti ini benar-benar membuktikan fitur bekerja benar, lengkap, dan "
            f"aman. Fitur '{feature}': {FEATURE_TASK.get(feature, '')}")


def main() -> int:
    per_check = 0
    if "--per-check" in sys.argv:
        i = sys.argv.index("--per-check")
        try:
            per_check = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            per_check = 21

    if not RESULTS.exists():
        print(f"FATAL: {RESULTS} tidak ada — jalankan dulu tests/october_2026_suite.py")
        return 2
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    rows = data["results"]
    features: dict[str, list[dict]] = {}
    for r in rows:
        features.setdefault(r["feature"], []).append(r)

    judge = LLMJudge()
    print("=" * 78)
    print("BRIEF 7 — TASK 1: LLM-AS-A-JUDGE atas 420 hard test")
    print("=" * 78)
    print(f"gateway tersedia : {judge.available}")
    print(f"kandidat model   : {judge.candidates[:4]}")
    print()

    t0 = time.perf_counter()
    per_feature: dict[str, dict] = {}
    scores: list[float] = []
    for feat in sorted(features):
        task = _task_for(feat)
        resp = _evidence_text(features[feat])
        res = judge.score(task, resp, threshold=THRESHOLD)
        det = features[feat]
        det_pass = sum(1 for x in det if x["verdict"] == "PASS")
        per_feature[feat] = {
            "deterministic_pass": f"{det_pass}/{len(det)}",
            "judge_ok": res.ok,
            "judge_overall": res.scores.get("overall"),
            "judge_detail": res.detail,
            "judge_model": judge.model,
        }
        if res.scores.get("overall") is not None:
            scores.append(res.scores["overall"])
        flag = ("PASS" if res.ok else "SKIP" if res.ok is None else "FAIL")
        ov = res.scores.get("overall")
        print(f"  {feat:<24} det={det_pass:>2}/{len(det)}  judge="
              f"{('%.2f' % ov) if ov is not None else ' n/a'}  [{flag}]")

    # --- sampel per-check (opsional) ------------------------------------
    check_sample: list[dict] = []
    if per_check > 0:
        print()
        print(f"-- sampel {per_check} check individual --")
        step = max(1, len(rows) // per_check)
        for r in rows[::step][:per_check]:
            res = judge.score(
                f"Apakah bukti check ini membuktikan perilaku BENAR dan AMAN? "
                f"Check: {r['name']}",
                f"verdict={r['verdict']} detail={r['detail']} "
                f"evidence={json.dumps(r.get('evidence'), default=str)[:400]}",
                threshold=THRESHOLD)
            ov = res.scores.get("overall")
            check_sample.append({"feature": r["feature"], "name": r["name"],
                                 "verdict": r["verdict"], "judge_overall": ov,
                                 "judge_ok": res.ok})
            if ov is not None:
                scores.append(ov)

    mean = round(statistics.fmean(scores), 3) if scores else None
    below = [f for f, v in per_feature.items()
             if v["judge_overall"] is not None and v["judge_overall"] < THRESHOLD]
    payload = {
        "threshold": THRESHOLD,
        "judge_available": judge.available,
        "judge_candidates": judge.candidates,
        "n_feature_scores": len(per_feature),
        "semantic_mean": mean,
        "deterministic": {"pass": data["pass"], "total": data["total"]},
        "features_below_threshold": below,
        "per_feature": per_feature,
        "per_check_sample": check_sample,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print()
    print("-" * 78)
    print(f"deterministik : {data['pass']}/{data['total']} PASS")
    print(f"semantik mean : {mean} (ambang {THRESHOLD})  n_skor={len(scores)}")
    print(f"fitur < ambang: {below or 'tidak ada'}")
    print(f"durasi        : {time.perf_counter() - t0:.1f}s")
    print(f"hasil         : {OUT}")
    return 0 if (mean is not None and mean >= THRESHOLD) else 1


if __name__ == "__main__":
    sys.exit(main())
