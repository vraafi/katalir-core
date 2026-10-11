"""test_subworkflow_batch.py — Hard test pola fan-out sub-workflow.

Referensi: SUBWORKFLOW_PATTERNS.md (`mode: all|each` + fire-and-forget).
Brief 11 Okt 2026: >=10 hard test (batas, error, performa, keamanan) 100% lulus.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import subworkflow_batch as sb  # noqa: E402


# 1. mode=all -> SATU run berisi semua item
def test_1_mode_all_single_run():
    p = sb.plan_dispatch([1, 2, 3], mode="all")
    assert p["count"] == 1
    assert p["runs"] == [[1, 2, 3]]
    assert len(p["jobs"]) == 1
    assert p["parallel"] is False


# 2. mode=each -> N run, satu item per run
def test_2_mode_each_n_runs():
    p = sb.plan_dispatch(["a", "b", "c"], mode="each")
    assert p["count"] == 3
    assert p["runs"] == [["a"], ["b"], ["c"]]
    assert [j["job_id"] for j in p["jobs"]] == ["run:0", "run:1", "run:2"]


# 3. each + wait_for=True -> TIDAK paralel
def test_3_each_wait_for_is_sequential():
    p = sb.plan_dispatch([1, 2], mode="each", wait_for=True)
    assert p["parallel"] is False


# 4. each + wait_for=False -> paralel (fire-and-forget)
def test_4_each_fire_and_forget_parallel():
    p = sb.plan_dispatch([1, 2], mode="each", wait_for=False)
    assert p["parallel"] is True


# 5. item kosong -> 0 job (tidak menggantung)
def test_5_empty_items_zero_jobs():
    p = sb.plan_dispatch([], mode="all")
    assert p["count"] == 0 and p["jobs"] == []
    p2 = sb.plan_dispatch([], mode="each")
    assert p2["count"] == 0 and p2["jobs"] == []


# 6. mode tidak dikenal -> galat
def test_6_invalid_mode_rejected():
    with pytest.raises(sb.BatchPlanError):
        sb.plan_dispatch([1], mode="parallel")
    with pytest.raises(sb.BatchPlanError):
        sb.plan_dispatch("bukan-list", mode="each")


# 7. batas job (anti-DoS)
def test_7_max_jobs_enforced():
    with pytest.raises(sb.BatchPlanError):
        sb.plan_dispatch(list(range(5)), mode="each", max_jobs=3)


# 8. semua terminal -> done + agregasi terurut
def test_8_all_terminal_done_aggregate():
    rows = [
        {"run_id": "r", "job_id": "r:1", "status": "success", "output": "B"},
        {"run_id": "r", "job_id": "r:0", "status": "success", "output": "A"},
    ]
    out = sb.evaluate_completion(rows, run_id="r")
    assert out["state"] == "done"
    assert out["terminal"] == 2 and out["pending"] == 0
    assert out["aggregate"] == ["A", "B"], "agregasi harus urut job_id"
    assert out["next_poll_sec"] is None


# 9. ada pending & belum lewat cap -> waiting
def test_9_pending_waiting():
    rows = [
        {"run_id": "r", "job_id": "r:0", "status": "success", "output": 1},
        {"run_id": "r", "job_id": "r:1", "status": "inProgress", "output": None},
    ]
    out = sb.evaluate_completion(rows, run_id="r", elapsed_sec=10,
                                 runtime_cap_sec=900)
    assert out["state"] == "waiting"
    assert out["terminal"] == 1 and out["pending"] == 1
    assert out["next_poll_sec"] == 5


# 10. pending & lewat cap -> timed_out (job mati TIDAK menggantung)
def test_10_cap_exceeded_times_out():
    rows = [
        {"run_id": "r", "job_id": "r:0", "status": "success", "output": 1},
        {"run_id": "r", "job_id": "r:1", "status": "inProgress", "output": None},
    ]
    out = sb.evaluate_completion(rows, run_id="r", elapsed_sec=901,
                                 runtime_cap_sec=900)
    assert out["state"] == "timed_out"
    assert out["timed_out_jobs"] == ["r:1"]
    assert out["next_poll_sec"] is None


# 11. batas PERSIS di cap -> timed_out (>=, bukan >)
def test_11_cap_boundary_inclusive():
    rows = [{"run_id": "r", "job_id": "r:0", "status": "inProgress"}]
    out = sb.evaluate_completion(rows, run_id="r", elapsed_sec=900,
                                 runtime_cap_sec=900)
    assert out["state"] == "timed_out"


# 12. status gagal juga TERMINAL (error tidak dianggap pending)
def test_12_error_is_terminal():
    rows = [
        {"run_id": "r", "job_id": "r:0", "status": "error", "output": None},
        {"run_id": "r", "job_id": "r:1", "status": "timeout", "output": None},
    ]
    out = sb.evaluate_completion(rows, run_id="r")
    assert out["state"] == "done" and out["terminal"] == 2


# 13. baris run lain TIDAK tercampur (isolasi per run_id)
def test_13_run_id_isolation():
    rows = [
        {"run_id": "r1", "job_id": "r1:0", "status": "inProgress"},
        {"run_id": "r2", "job_id": "r2:0", "status": "success", "output": "x"},
    ]
    out = sb.evaluate_completion(rows, run_id="r2")
    assert out["state"] == "done" and out["aggregate"] == ["x"]


# 14. tidak ada baris -> done vakum (bukan menggantung)
def test_14_empty_rows_vacuous_done():
    out = sb.evaluate_completion([], run_id="r")
    assert out["state"] == "done" and out["aggregate"] == []


# 15. determinisme + performa 1000 job
def test_15_deterministic_and_performance():
    items = list(range(1000))
    t0 = time.perf_counter()
    p1 = sb.plan_dispatch(items, mode="each")
    p2 = sb.plan_dispatch(items, mode="each")
    rows = [{"run_id": "run", "job_id": f"run:{i}", "status": "success",
             "output": i} for i in range(1000)]
    out = sb.evaluate_completion(rows, run_id="run")
    dt = time.perf_counter() - t0
    assert p1 == p2, "harus deterministik"
    assert out["state"] == "done" and out["aggregate"] == items
    assert dt < 1.0, f"terlalu lambat: {dt:.3f}s"
    assert sb.describe()["modes"] == ["all", "each"]
