# tests/test_evaluation.py — Fitur #4 hard test (10+ skenario, Okt 2026)
# Deterministik: runner + judge disuntik (tanpa jaringan).
from __future__ import annotations

import time

import pytest

import evaluation
from evaluation import (Evaluator, compare, estimate_cost, load_dataset,
                        _MemoryRuns)


@pytest.fixture()
def runs():
    b = _MemoryRuns()
    evaluation.set_runs_backend(b)
    return b


def _runner_from(mapping):
    def runner(case):
        return mapping.get(case["input"], {"output": "", "latency_ms": 10,
                                           "tokens_in": 100, "tokens_out": 50})
    return runner


# 1. Upload dataset JSON -> run -> hasil
def test_dataset_json_run():
    ds = load_dataset('[{"input":"2+2","expected":"4"},'
                      '{"input":"3+3","expected":"6"}]')
    assert len(ds) == 2
    ev = Evaluator("math")
    out = ev.run(ds, _runner_from({"2+2": {"output": "4"}, "3+3": {"output": "6"}}),
                 compare_mode="exact")
    assert out["summary"]["total"] == 2
    assert out["summary"]["passed"] == 2


# 2. Upload dataset CSV
def test_dataset_csv():
    csv_text = "input,expected\nibukota indonesia,jakarta\nibukota jepang,tokyo\n"
    ds = load_dataset(csv_text, fmt="csv")
    assert len(ds) == 2
    assert ds[0]["input"] == "ibukota indonesia"
    assert ds[0]["expected"] == "jakarta"


# 3. Accuracy metric
def test_accuracy_metric():
    ds = load_dataset('[{"input":"a","expected":"1"},{"input":"b","expected":"2"},'
                      '{"input":"c","expected":"3"},{"input":"d","expected":"4"}]')
    out = Evaluator().run(ds, _runner_from({
        "a": {"output": "1"}, "b": {"output": "2"},
        "c": {"output": "salah"}, "d": {"output": "4"}}), compare_mode="exact")
    assert out["summary"]["accuracy"] == 0.75
    assert out["summary"]["passed"] == 3


# 4. Latency metric (mean/p50/p95)
def test_latency_metric():
    ds = load_dataset('[{"input":"a","expected":"x"},{"input":"b","expected":"x"},'
                      '{"input":"c","expected":"x"}]')
    runner = _runner_from({"a": {"output": "x", "latency_ms": 10},
                           "b": {"output": "x", "latency_ms": 20},
                           "c": {"output": "x", "latency_ms": 30}})
    s = Evaluator().run(ds, runner, compare_mode="exact")["summary"]
    assert s["latency_mean_ms"] == 20.0
    assert s["latency_p50_ms"] == 20.0
    assert s["latency_p95_ms"] >= 20.0


# 5. Cost metric
def test_cost_metric():
    ds = load_dataset('[{"input":"a","expected":"x"}]')
    runner = _runner_from({"a": {"output": "x", "tokens_in": 1000,
                                 "tokens_out": 1000}})
    s = Evaluator().run(ds, runner, compare_mode="exact")["summary"]
    assert s["cost_total_usd"] > 0
    # 1000 in @0.0001/1k + 1000 out @0.0004/1k = 0.0005
    assert abs(s["cost_total_usd"] - 0.0005) < 1e-9


# 6. LLM-as-judge scoring (judge disuntik)
def test_llm_as_judge():
    ds = load_dataset('[{"input":"q","expected":"jawaban benar"}]')
    calls = []

    def judge(inp, out, expected):
        calls.append((inp, out))
        return 0.95

    out = Evaluator(threshold=0.9).run(
        ds, _runner_from({"q": {"output": "jawaban mendekati benar"}}),
        judge=judge, compare_mode="judge")
    assert calls
    assert out["results"][0]["score"] == 0.95
    assert out["results"][0]["passed"] is True


# 7. Regresi: run vs baseline
def test_regression_vs_baseline():
    ds = load_dataset('[{"input":"a","expected":"1"},{"input":"b","expected":"2"}]')
    out = Evaluator().run(ds, _runner_from({"a": {"output": "1"},
                                            "b": {"output": "X"}}),
                          compare_mode="exact", baseline_accuracy=1.0)
    s = out["summary"]
    assert s["accuracy"] == 0.5
    assert s["regression_delta"] == -0.5
    assert s["regression"] == "regressed"


# 8. Multiple datasets independen
def test_multiple_datasets():
    d1 = load_dataset('[{"input":"a","expected":"1"}]')
    d2 = load_dataset('[{"input":"b","expected":"2"}]')
    e = Evaluator()
    r1 = e.run(d1, _runner_from({"a": {"output": "1"}}), compare_mode="exact")
    r2 = e.run(d2, _runner_from({"b": {"output": "9"}}), compare_mode="exact")
    assert r1["summary"]["accuracy"] == 1.0
    assert r2["summary"]["accuracy"] == 0.0


# 9. Edge case: dataset kosong
def test_empty_dataset():
    out = Evaluator().run([], _runner_from({}))
    assert out["summary"]["total"] == 0
    assert out["summary"]["accuracy"] == 0.0
    assert out["results"] == []


# 10. Performance: 100 test cases
def test_performance_100_cases():
    ds = load_dataset([{"input": f"i{i}", "expected": f"o{i}"}
                       for i in range(100)])
    runner = _runner_from({f"i{i}": {"output": f"o{i}", "latency_ms": 1}
                           for i in range(100)})
    t0 = time.perf_counter()
    out = Evaluator().run(ds, runner, compare_mode="exact")
    elapsed = time.perf_counter() - t0
    assert out["summary"]["accuracy"] == 1.0
    assert elapsed < 2.0, f"100 kasus terlalu lambat: {elapsed:.2f}s"


# 11. Benchmark: waktu evaluasi dilaporkan
def test_benchmark_duration_reported():
    ds = load_dataset([{"input": "a", "expected": "1"}])
    s = Evaluator().run(ds, _runner_from({"a": {"output": "1"}}),
                        compare_mode="exact")["summary"]
    assert s["duration_ms"] >= 0


# 12. Runner error tidak menggagalkan seluruh eval
def test_runner_error_isolated():
    def bad_runner(case):
        if case["input"] == "boom":
            raise RuntimeError("ledakan")
        return {"output": "1"}

    ds = load_dataset('[{"input":"ok","expected":"1"},'
                      '{"input":"boom","expected":"1"}]')
    out = Evaluator().run(ds, bad_runner, compare_mode="exact")
    assert out["summary"]["total"] == 2
    assert out["summary"]["passed"] == 1
    failed = [r for r in out["results"] if not r["passed"]][0]
    assert "ledakan" in failed["error"]


# 13. compare(): semua mode
def test_compare_modes():
    assert compare("Jakarta", "jakarta", "exact") == 0.0
    assert compare("Jakarta", "jakarta", "contains") == 1.0
    assert compare("100", "105", "numeric") == pytest.approx(0.95238, abs=1e-4)
    assert compare("halo dunia", "halo dunia", "fuzzy") == 1.0


# 14. estimate_cost murni
def test_estimate_cost():
    assert estimate_cost(1000, 0, 0.0001, 0.0004) == 0.0001
    assert estimate_cost(0, 1000, 0.0001, 0.0004) == 0.0004
    assert estimate_cost("x", None) == 0.0


# 15. Simpan + daftar run (persistensi)
def test_save_and_list_runs(runs):
    ds = load_dataset('[{"input":"a","expected":"1"}]')
    out = Evaluator("regresi").run(ds, _runner_from({"a": {"output": "1"}}),
                                   compare_mode="exact")
    row = evaluation.save_run("u@test.dev", out["summary"], out["results"],
                              dataset_name="d1")
    assert row["run_id"]
    listed = evaluation.list_runs("u@test.dev")
    assert len(listed) == 1
    assert listed[0]["accuracy"] == 1.0
    # user lain tidak melihat run ini
    assert evaluation.list_runs("lain@test.dev") == []


# 16. Normalisasi kolom dataset (nama kolom bebas)
def test_column_normalization():
    ds = load_dataset('[{"Question":"q1","Answer":"a1","extra":"x"}]')
    assert ds[0]["input"] == "q1"
    assert ds[0]["expected"] == "a1"
    assert ds[0]["extra"] == "x"


# 17. DDL migrasi evaluasi ada
def test_migration_file_has_ddl():
    import pathlib
    p = (pathlib.Path(__file__).resolve().parent.parent
         / "migrations" / "2026_evaluation.sql")
    sql = p.read_text(encoding="utf-8")
    assert "create table if not exists eval_runs" in sql
    assert "accuracy" in sql
    assert "row level security" in sql
