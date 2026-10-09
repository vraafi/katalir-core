# metrics_eval.py — Fitur #7: Metric-based Evaluations (9 Okt 2026)
# ======================================================================
# Melengkapi `evaluation.py` (Fitut #15 Evaluation & Testing) dengan
# METRIK KLASIFIKASI penuh + visualisasi + perbandingan baseline:
#   accuracy, precision, recall, F1 (macro & per-kelas), confusion matrix,
#   latency p50/p95/p99, cost, dan ekspor laporan.
#
# Riset Okt 2026 (docs/n8n-gap-closure-log.md §7):
#   - n8n "Evaluations" (Pro) memakai metrik + panel, bukan hanya lulus/gagal.
#   - Best practice LLM eval 2026: rubrik deterministik untuk metrik
#     terhitung (precision/recall/F1) + LLM-as-judge untuk kualitas terbuka;
#     JANGAN campur keduanya dalam satu angka tanpa menyebut mode.
#   - Confusion matrix butuh LABEL KELAS, bukan skor kontinu -> karena itu
#     klasifikasi label diturunkan dari `expected`/`actual` apa adanya
#     (bukan dari skor fuzzy). Laporkan `mode` secara jujur di laporan.
#
# DESAIN (kenapa murni & tanpa jaringan):
#   Semua perhitungan = fungsi murni atas daftar hasil dari `Evaluator.run`.
#   Tidak menyentuh DB/LLM -> bisa di-hard-test presisi tanpa flake.
#   Persistensi memakai kembali backend `evaluation.save_run` (Supabase/
#   memori) sehingga tidak ada jalur penyimpanan kedua.
# ======================================================================

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from typing import Any, Iterable, Optional

import evaluation as _eval

#: Ambang default untuk menurunkan label kelas dari skor kontinu.
DEFAULT_LABEL_THRESHOLD = 0.5

#: Metrik yang didukung (dipakai untuk validasi permintaan).
SUPPORTED_METRICS = (
    "accuracy", "precision", "recall", "f1",
    "latency", "cost", "confusion",
)


# ---------------------------------------------------------------------------
# Perhitungan metrik klasifikasi (murni)
# ---------------------------------------------------------------------------

def _binary_counts(pairs: Iterable[tuple[str, str]], positive: str) -> dict:
    """TP/FP/FN/TN untuk satu kelas positif (one-vs-rest)."""
    tp = fp = fn = tn = 0
    for expected, actual in pairs:
        exp_pos = expected == positive
        act_pos = actual == positive
        if exp_pos and act_pos:
            tp += 1
        elif not exp_pos and act_pos:
            fp += 1
        elif exp_pos and not act_pos:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return round(precision, 4), round(recall, 4), round(f1, 4)


def labelize(results: list[dict],
             threshold: float = DEFAULT_LABEL_THRESHOLD) -> list[tuple[str, str]]:
    """Turunkan pasangan label (expected, actual) dari hasil evaluasi.

    Aturan jujur:
      - Bila `expected` dan `actual` adalah teks non-kosong DAN cocok/beda
        persis, pakai teks itu apa adanya sebagai label kelas.
      - Bila `actual` kosong (runner gagal), label aktual = "__error__".
      - Untuk teks bebas yang tidak identik, label aktual dianggap sama
        dengan expected bila skor >= threshold (koreksi fuzzy), karena
        membandingkan string bebas sebagai kelas akan meledakkan kardinalitas.
        `mode` melaporkan bahwa koreksi ini dipakai.
    """
    out: list[tuple[str, str]] = []
    for r in results:
        exp_raw = str(r.get("expected") or "").strip()
        act = str(r.get("actual") or "").strip()
        exp_label = exp_raw or "__empty__"
        # Dataset tanpa ground truth (expected kosong) BUKAN kegagalan:
        # labelnya __empty__ di kedua sisi. Runner yang benar-benar gagal
        # (tidak menghasilkan apa pun padahal expected ada) = __error__.
        if not act:
            act_label = "__empty__" if not exp_raw else "__error__"
        elif not exp_raw or act == exp_raw:
            act_label = exp_label
        else:
            score = float(r.get("score") or 0.0)
            act_label = exp_label if score >= threshold else act
        out.append((exp_label, act_label))
    return out


def classification_report(results: list[dict],
                          threshold: float = DEFAULT_LABEL_THRESHOLD
                          ) -> dict:
    """Accuracy + precision/recall/F1 (macro) + per-kelas + confusion matrix."""
    pairs = labelize(results, threshold)
    total = len(pairs)
    labels = sorted({e for e, _ in pairs} | {a for _, a in pairs})
    correct = sum(1 for e, a in pairs if e == a)
    accuracy = round(correct / total, 4) if total else 0.0

    per_class: dict[str, dict] = {}
    matrix: dict[str, dict[str, int]] = {
        lab: {a: 0 for a in labels} for lab in labels
    }
    for expected, actual in pairs:
        matrix[expected][actual] += 1

    f1s: list[float] = []
    for lab in labels:
        c = _binary_counts(pairs, lab)
        p, r, f1 = _prf(c["tp"], c["fp"], c["fn"])
        support = c["tp"] + c["fn"]
        per_class[lab] = {
            "precision": p, "recall": r, "f1": f1,
            "support": support, **c,
        }
        if support:
            f1s.append(f1)

    macro = {
        "precision": round(sum(v["precision"] for v in per_class.values())
                           / len(per_class), 4) if per_class else 0.0,
        "recall": round(sum(v["recall"] for v in per_class.values())
                        / len(per_class), 4) if per_class else 0.0,
        "f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
    }
    weighted_f1 = 0.0
    if total:
        weighted_f1 = round(
            sum(per_class[l]["f1"] * per_class[l]["support"] for l in labels
                if per_class[l]["support"]) / total, 4)
    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "macro": macro,
        "weighted_f1": weighted_f1,
        "per_class": per_class,
        "labels": labels,
        "confusion_matrix": matrix,
    }


# ---------------------------------------------------------------------------
# Metrik latensi & biaya
# ---------------------------------------------------------------------------

def latency_metrics(results: list[dict]) -> dict:
    lat = [float(r.get("latency_ms") or 0.0) for r in results]
    if not lat:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                "min": 0.0, "max": 0.0}
    return {
        "count": len(lat),
        "mean": round(sum(lat) / len(lat), 2),
        "p50": _eval._percentile(lat, 50),
        "p95": _eval._percentile(lat, 95),
        "p99": _eval._percentile(lat, 99),
        "min": round(min(lat), 2),
        "max": round(max(lat), 2),
    }


def cost_metrics(results: list[dict], price_in: float = _eval.DEFAULT_PRICE_IN,
                 price_out: float = _eval.DEFAULT_PRICE_OUT) -> dict:
    total = 0.0
    tin = tout = 0
    for r in results:
        c = r.get("cost_usd")
        if c is None:
            c = _eval.estimate_cost(r.get("tokens_in"), r.get("tokens_out"),
                                    price_in, price_out)
        total += float(c)
        tin += int(r.get("tokens_in") or 0)
        tout += int(r.get("tokens_out") or 0)
    n = len(results) or 1
    return {
        "total_usd": round(total, 8),
        "mean_usd": round(total / n, 8),
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_per_1k_cases_usd": round(total / n * 1000, 6),
    }


# ---------------------------------------------------------------------------
# Visualisasi (data chart siap-render — TIDAK menggambar di server)
# ---------------------------------------------------------------------------

def chart_data(report: dict, lat: dict, cost: dict) -> dict:
    """Bentuk data untuk bar/line/confusion — UI tinggal menggambar."""
    per_class = report.get("per_class", {})
    return {
        "type": "metric_dashboard",
        "bar": {
            "labels": ["accuracy", "precision", "recall", "f1"],
            "values": [report["accuracy"], report["macro"]["precision"],
                       report["macro"]["recall"], report["macro"]["f1"]],
        },
        "per_class": {
            "labels": list(per_class.keys()),
            "precision": [v["precision"] for v in per_class.values()],
            "recall": [v["recall"] for v in per_class.values()],
            "f1": [v["f1"] for v in per_class.values()],
        },
        "line": {
            "labels": ["p50", "p95", "p99"],
            "values": [lat["p50"], lat["p95"], lat["p99"]],
        },
        "confusion": {
            "labels": report.get("labels", []),
            "matrix": [[report["confusion_matrix"][e][a] for a in report["labels"]]
                       for e in report["labels"]],
        },
        "cost": cost,
    }


# ---------------------------------------------------------------------------
# Perbandingan baseline
# ---------------------------------------------------------------------------

def compare_runs(current: dict, baseline: dict) -> dict:
    """Bandingkan dua laporan metrik (baseline vs current)."""
    def _d(a: Any, b: Any) -> Optional[float]:
        if a is None or b is None:
            return None
        return round(float(a) - float(b), 4)

    return {
        "accuracy": {
            "baseline": baseline.get("accuracy"),
            "current": current.get("accuracy"),
            "delta": _d(current.get("accuracy"), baseline.get("accuracy")),
        },
        "f1_macro": {
            "baseline": (baseline.get("macro") or {}).get("f1"),
            "current": (current.get("macro") or {}).get("f1"),
            "delta": _d((current.get("macro") or {}).get("f1"),
                        (baseline.get("macro") or {}).get("f1")),
        },
        "regressed": (_d(current.get("accuracy"), baseline.get("accuracy")) or 0) < 0,
    }


# ---------------------------------------------------------------------------
# Evaluasi lengkap (orchestrator, memakai Evaluator yang ada)
# ---------------------------------------------------------------------------

def evaluate_with_metrics(cases: list[dict], runner: Any,
                          name: str = "metric-eval",
                          threshold: float = _eval.DEFAULT_THRESHOLD,
                          compare_mode: str = "fuzzy",
                          judge: Any = None,
                          baseline: Optional[dict] = None,
                          metrics: Optional[list[str]] = None
                          ) -> dict:
    """Jalankan evaluasi + hitung metrik berbasis angka.

    `baseline` = dict laporan sebelumnya (hasil `classification_report`)
    atau angka accuracy lama. Tidak menjalankan apa pun dua kali:
    `Evaluator.run` dipanggil SEKALI, lalu metrik dihitung dari hasilnya.
    """
    wanted = [m for m in (metrics or SUPPORTED_METRICS) if m in SUPPORTED_METRICS]
    ev = _eval.Evaluator(name=name, threshold=threshold)
    raw = ev.run(cases, runner, judge=judge, compare_mode=compare_mode)
    results = raw["results"]
    summary = raw["summary"]

    report = classification_report(results)
    lat = latency_metrics(results)
    cost = cost_metrics(results)

    if baseline is not None:
        base_report = baseline if "per_class" in baseline else {
            "accuracy": baseline.get("accuracy"),
            "macro": {"f1": baseline.get("f1")},
        }
        comparison = compare_runs(report, base_report)
    else:
        comparison = None

    out = {
        "name": name,
        "summary": summary,
        "metrics_requested": wanted,
        "classification": report if ("accuracy" in wanted
                                     or "precision" in wanted
                                     or "recall" in wanted
                                     or "f1" in wanted) else None,
        "latency": lat if "latency" in wanted else None,
        "cost": cost if "cost" in wanted else None,
        "comparison": comparison,
        "results": results,
    }
    out["charts"] = chart_data(report, lat, cost)
    return out


# ---------------------------------------------------------------------------
# Ekspor laporan (CSV / JSON / Markdown) — deterministik, tanpa PDF binary
# ---------------------------------------------------------------------------

def _rows_for_export(report: dict, lat: dict, cost: dict) -> list[list[Any]]:
    rows: list[list[Any]] = [
        ["metric", "value"],
        ["accuracy", report["accuracy"]],
        ["precision_macro", report["macro"]["precision"]],
        ["recall_macro", report["macro"]["recall"]],
        ["f1_macro", report["macro"]["f1"]],
        ["weighted_f1", report["weighted_f1"]],
        ["latency_p50_ms", lat["p50"]],
        ["latency_p95_ms", lat["p95"]],
        ["latency_p99_ms", lat["p99"]],
        ["cost_total_usd", cost["total_usd"]],
        ["cost_mean_usd", cost["mean_usd"]],
    ]
    for lab, v in report.get("per_class", {}).items():
        rows.append([f"class:{lab}:precision", v["precision"]])
        rows.append([f"class:{lab}:recall", v["recall"]])
        rows.append([f"class:{lab}:f1", v["f1"]])
        rows.append([f"class:{lab}:support", v["support"]])
    return rows


def export_report(report: dict, fmt: str = "json",
                  baseline: Optional[dict] = None) -> str:
    """Ekspor laporan metrik. fmt: json | csv | markdown."""
    fmt = (fmt or "json").strip().lower()
    lat = report.get("latency") or {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    cost = report.get("cost") or {"total_usd": 0.0, "mean_usd": 0.0}
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        for row in _rows_for_export(report, lat, cost):
            w.writerow(row)
        return buf.getvalue()
    if fmt in ("md", "markdown"):
        lines = [f"# Evaluation report — {report.get('name', 'eval')}", ""]
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        for k, v in _rows_for_export(report, lat, cost)[1:]:
            lines.append(f"| {k} | {v} |")
        if baseline:
            cmp = compare_runs(report, baseline)
            lines += ["", "## vs baseline", "",
                      f"- accuracy delta: {cmp['accuracy']['delta']}",
                      f"- f1_macro delta: {cmp['f1_macro']['delta']}",
                      f"- regressed: {cmp['regressed']}"]
        return "\n".join(lines) + "\n"
    # default json
    payload = {
        "name": report.get("name"),
        "accuracy": report.get("accuracy"),
        "macro": report.get("macro"),
        "weighted_f1": report.get("weighted_f1"),
        "per_class": report.get("per_class"),
        "confusion_matrix": report.get("confusion_matrix"),
        "latency": lat,
        "cost": cost,
    }
    if baseline:
        payload["comparison"] = compare_runs(report, baseline)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def confusion_summary(report: dict) -> dict:
    """Ringkas confusion matrix: total benar/salah per kelas."""
    matrix = report.get("confusion_matrix") or {}
    labels = report.get("labels") or []
    out: dict[str, dict] = {}
    for lab in labels:
        row = matrix.get(lab, {})
        correct = row.get(lab, 0)
        total = sum(row.values())
        out[lab] = {"correct": correct, "total": total,
                    "accuracy": round(correct / total, 4) if total else 0.0}
    return out


def top_confusions(report: dict, k: int = 5) -> list[dict]:
    """Pasangan (expected, actual) yang paling sering tertukar."""
    matrix = report.get("confusion_matrix") or {}
    pairs: list[tuple[int, str, str]] = []
    for exp, row in matrix.items():
        for act, n in row.items():
            if exp != act and n:
                pairs.append((n, exp, act))
    pairs.sort(reverse=True)
    return [{"count": n, "expected": e, "actual": a}
            for n, e, a in pairs[:max(0, int(k))]]


__all__ = [
    "SUPPORTED_METRICS", "DEFAULT_LABEL_THRESHOLD",
    "labelize", "classification_report", "latency_metrics", "cost_metrics",
    "chart_data", "compare_runs", "evaluate_with_metrics", "export_report",
    "confusion_summary", "top_confusions",
]
