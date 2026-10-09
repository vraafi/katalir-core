# tests/test_metrics_eval.py — Fitur #7: Metric-based Evaluations
# ======================================================================
# 16 tes. Semua MURNI (tanpa DB/jaringan/LLM) supaya deterministik.
# Setiap tes dirancang GAGAL bila metrik dihitung salah (bukan sekadar
# "tidak melempar").
# ======================================================================

from __future__ import annotations

import json

import pytest

import metrics_eval as M


def _mk(expected, actual, latency=100.0, score=None, tokens=(100, 50)):
    try:
        sc = float(score)
    except (TypeError, ValueError):
        sc = 1.0 if expected == actual else 0.0
    return {
        "id": f"c-{expected}-{actual}",
        "expected": expected,
        "actual": actual,
        "score": sc,
        "passed": sc >= 0.8,
        "latency_ms": latency,
        "cost_usd": 0.001,
        "tokens_in": tokens[0],
        "tokens_out": tokens[1],
        "error": "" if actual else "boom",
    }


# 1. Basic — akurasi dihitung benar pada campuran benar/salah
def test_accuracy_basic():
    rows = [_mk("yes", "yes"), _mk("yes", "yes"),
            _mk("no", "no"), _mk("no", "yes")]
    rep = M.classification_report(rows)
    assert rep["total"] == 4
    assert rep["correct"] == 3
    assert rep["accuracy"] == 0.75


# 2. Basic — precision/recall/F1 kelas tunggal (nilai eksak)
def test_precision_recall_f1_exact():
    # expected "spam": actual spam (TP) x2, ham (FN) x1
    # expected "ham" : actual spam (FP) x1, ham (TN) x1
    rows = [_mk("spam", "spam"), _mk("spam", "spam"),
            _mk("spam", "ham"), _mk("ham", "spam"), _mk("ham", "ham")]
    rep = M.classification_report(rows)
    spam = rep["per_class"]["spam"]
    assert spam["tp"] == 2 and spam["fn"] == 1 and spam["fp"] == 1
    assert spam["precision"] == round(2 / 3, 4)
    assert spam["recall"] == round(2 / 3, 4)
    assert spam["f1"] == round(2 / 3, 4)


# 3. Basic — support & macro dihitung dari kelas yang punya support
def test_macro_and_support():
    rows = [_mk("a", "a"), _mk("a", "b"), _mk("b", "b"), _mk("b", "b"),
            _mk("c", "c")]
    rep = M.classification_report(rows)
    assert rep["total"] == 5
    assert rep["per_class"]["c"]["support"] == 1
    assert rep["macro"]["f1"] > 0
    assert 0 <= rep["macro"]["f1"] <= 1


# 4. Edge — actual kosong jadi kelas "__error__", TIDAK dianggap benar
def test_empty_actual_counts_as_error_class():
    rows = [_mk("ok", ""), _mk("ok", "ok")]
    rep = M.classification_report(rows)
    assert "__error__" in rep["labels"]
    assert rep["accuracy"] == 0.5
    assert rep["confusion_matrix"]["ok"]["__error__"] == 1


# 5. Edge — expected kosong jadi "__empty__" (tidak crash)
def test_empty_expected_label():
    rows = [_mk("", ""), _mk("", "")]
    rep = M.classification_report(rows)
    assert rep["labels"] == ["__empty__"]
    assert rep["accuracy"] == 1.0


# 6. Edge — dataset kosong tidak membagi nol
def test_empty_dataset_no_zero_division():
    rep = M.classification_report([])
    assert rep["total"] == 0 and rep["accuracy"] == 0.0
    lat = M.latency_metrics([])
    assert lat["count"] == 0 and lat["p99"] == 0.0
    cost = M.cost_metrics([])
    assert cost["total_usd"] == 0.0 and cost["mean_usd"] == 0.0


# 7. Latency p50/p95/p99 (nilai eksak pada 1..100)
def test_latency_percentiles():
    rows = [_mk("x", "x", latency=float(i)) for i in range(1, 101)]
    lat = M.latency_metrics(rows)
    assert lat["count"] == 100
    assert lat["min"] == 1.0 and lat["max"] == 100.0
    assert lat["p50"] == 50.0
    assert lat["p95"] == 95.0
    assert lat["p99"] == 99.0


# 8. Cost — total, mean, dan tokens dijumlahkan
def test_cost_metrics_totals():
    rows = [_mk("x", "x", tokens=(1000, 500)) for _ in range(4)]
    cost = M.cost_metrics(rows)
    assert cost["tokens_in"] == 4000
    assert cost["tokens_out"] == 2000
    assert cost["total_usd"] == pytest.approx(0.004, abs=1e-6)
    assert cost["mean_usd"] == pytest.approx(0.001, abs=1e-6)


# 9. Confusion matrix berbentuk persegi & konsisten dengan total
def test_confusion_matrix_square_and_consistent():
    rows = [_mk("a", "a"), _mk("a", "b"), _mk("b", "a"), _mk("b", "b"),
            _mk("b", "b")]
    rep = M.classification_report(rows)
    labels = rep["labels"]
    mat = rep["confusion_matrix"]
    assert all(set(row.keys()) == set(labels) for row in mat.values())
    assert sum(sum(r.values()) for r in mat.values()) == rep["total"]
    assert sum(mat[l][l] for l in labels) == rep["correct"]


# 10. Chart data bentuknya siap-render dan konsisten dengan laporan
def test_chart_data_shape():
    rows = [_mk("a", "a"), _mk("a", "b"), _mk("b", "b")]
    rep = M.classification_report(rows)
    charts = M.chart_data(rep, M.latency_metrics(rows), M.cost_metrics(rows))
    assert charts["bar"]["values"][0] == rep["accuracy"]
    assert len(charts["confusion"]["matrix"]) == len(rep["labels"])
    assert charts["line"]["labels"] == ["p50", "p95", "p99"]


# 11. Baseline comparison — regresi terdeteksi
def test_compare_runs_detects_regression():
    cur = {"accuracy": 0.7, "macro": {"f1": 0.6}}
    base = {"accuracy": 0.9, "macro": {"f1": 0.85}}
    cmp = M.compare_runs(cur, base)
    assert cmp["regressed"] is True
    assert cmp["accuracy"]["delta"] == -0.2
    assert cmp["f1_macro"]["delta"] == -0.25


# 12. Baseline comparison — perbaikan tidak ditandai regresi
def test_compare_runs_improvement():
    cmp = M.compare_runs({"accuracy": 0.95, "macro": {"f1": 0.9}},
                         {"accuracy": 0.8, "macro": {"f1": 0.7}})
    assert cmp["regressed"] is False
    assert cmp["accuracy"]["delta"] == 0.15


# 13. Awal-ke-akhir: evaluate_with_metrics memanggil runner SEKALI per kasus
def test_evaluate_with_metrics_single_pass():
    calls = {"n": 0}

    def runner(case):
        calls["n"] += 1
        return {"output": case["expected"], "latency_ms": 12.0,
                "tokens_in": 10, "tokens_out": 5}

    cases = [{"id": "1", "input": "q1", "expected": "a"},
             {"id": "2", "input": "q2", "expected": "b"}]
    out = M.evaluate_with_metrics(cases, runner, baseline={"accuracy": 0.5,
                                                           "macro": {"f1": 0.5}})
    assert calls["n"] == 2, "runner tidak boleh dipanggil dua kali per kasus"
    assert out["classification"]["accuracy"] == 1.0
    assert out["comparison"]["regressed"] is False
    assert out["charts"]["type"] == "metric_dashboard"


# 14. Filter metrik: minta hanya latency -> classification/cost = None
def test_metrics_filter():
    def runner(case):
        return {"output": case["expected"], "latency_ms": 5.0}

    out = M.evaluate_with_metrics(
        [{"id": "1", "input": "q", "expected": "a"}], runner,
        metrics=["latency"])
    assert out["latency"] is not None
    assert out["classification"] is None
    assert out["cost"] is None


# 15. Export JSON/CSV/Markdown valid
def test_export_formats():
    rows = [_mk("a", "a"), _mk("b", "b")]
    rep = M.classification_report(rows)
    payload = {"name": "e", **rep, "latency": M.latency_metrics(rows),
               "cost": M.cost_metrics(rows)}
    js = json.loads(M.export_report(payload, "json"))
    assert js["accuracy"] == 1.0
    csv_text = M.export_report(payload, "csv")
    assert "accuracy,1.0" in csv_text
    md = M.export_report(payload, "markdown", baseline={"accuracy": 0.5,
                                                        "macro": {"f1": 0.5}})
    assert "# Evaluation report" in md and "vs baseline" in md


# 16. Performa: 1000 baris < 1 detik (murni, tanpa I/O)
def test_performance_1000_rows_under_1s():
    import time
    rows = [_mk("a" if i % 2 == 0 else "b", "a" if i % 3 else "b",
                latency=float(i % 50) + 1) for i in range(1000)]
    t0 = time.perf_counter()
    rep = M.classification_report(rows)
    lat = M.latency_metrics(rows)
    M.cost_metrics(rows)
    M.chart_data(rep, lat, M.cost_metrics(rows))
    M.top_confusions(rep)
    dt = time.perf_counter() - t0
    assert rep["total"] == 1000
    assert dt < 1.0, f"terlalu lambat: {dt:.3f}s"
