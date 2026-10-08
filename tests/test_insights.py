# tests/test_insights.py — Fitur #5 hard test (10+ skenario, Okt 2026)
# Deterministik: event sintetis disuntik (tanpa DB).
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

import insights
from insights import (Insight, by_workflow, compute_metrics, roi, time_saved,
                      time_series, to_csv)

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


def _ev(days_ago=0, status="completed", wid="w1", dur=None, hour=10):
    dt = NOW - timedelta(days=days_ago)
    dt = dt.replace(hour=hour)
    e = {"workflow_id": wid, "status": status, "created_at": dt.isoformat()}
    if dur is not None:
        e["duration_ms"] = dur
    return e


def _events(n=100, **kw):
    return [_ev(days_ago=i % 30, status="completed" if i % 4 else "error", **kw)
            for i in range(n)]


# 1. Metrics dasar: success/error rate
def test_metrics_rates():
    m = compute_metrics([_ev(status="completed"), _ev(status="completed"),
                         _ev(status="error"), _ev(status="pending")])
    assert m["total"] == 4
    assert m["success"] == 2 and m["error"] == 1 and m["pending"] == 1
    assert m["success_rate"] == 0.5
    assert m["error_rate"] == 0.25


# 2. Latensi mean/p50/p95
def test_latency_metrics():
    m = compute_metrics([_ev(dur=100), _ev(dur=200), _ev(dur=300)])
    assert m["latency_mean_ms"] == 200.0
    assert m["latency_p50_ms"] == 200.0
    assert m["latency_p95_ms"] == 300.0
    assert m["latency_sample_size"] == 3


# 3. Time series 7 hari (termasuk hari kosong)
def test_time_series_7_days():
    ev = [_ev(days_ago=0), _ev(days_ago=2), _ev(days_ago=2, status="error")]
    s = time_series(ev, 7, NOW)
    assert len(s) == 7
    assert s[-1]["date"] == "2026-10-08"
    assert s[-1]["total"] == 1
    # 2 hari lalu
    assert s[-3]["total"] == 2 and s[-3]["error"] == 1
    # hari tanpa event = 0
    assert s[0]["total"] == 0


# 4. Time series 30 & 365 hari
def test_time_series_long_ranges():
    ev = _events(200)
    assert len(time_series(ev, 30, NOW)) == 30
    assert len(time_series(ev, 365, NOW)) == 365


# 5. Time saved calculation
def test_time_saved():
    ev = [_ev(status="completed")] * 10 + [_ev(status="error")]
    ts = time_saved(ev, minutes_per_run=5)
    assert ts["automated_runs"] == 10
    assert ts["minutes_saved"] == 50.0
    assert ts["hours_saved"] == pytest.approx(0.833, abs=1e-3)


# 6. ROI calculator
def test_roi():
    r = roi(hours_saved=10, hourly_rate=25)
    assert r["money_saved"] == 250.0
    assert r["currency"] == "USD"


# 7. Filter by date range
def test_filter_by_date():
    ev = [_ev(days_ago=0), _ev(days_ago=10), _ev(days_ago=100)]
    assert len(insights.filter_events(ev, 7, now=NOW)) == 1
    assert len(insights.filter_events(ev, 30, now=NOW)) == 2
    assert len(insights.filter_events(ev, 365, now=NOW)) == 3


# 8. Filter by workflow
def test_filter_by_workflow():
    ev = [_ev(wid="w1"), _ev(wid="w2"), _ev(wid="w1")]
    assert len(insights.filter_events(ev, 30, "w1", now=NOW)) == 2
    assert len(insights.filter_events(ev, 30, "w2", now=NOW)) == 1


# 9. Error rate chart data (series punya kolom error)
def test_error_series_column():
    ev = [_ev(days_ago=1, status="error"), _ev(days_ago=1, status="error")]
    s = time_series(ev, 7, NOW)
    assert sum(b["error"] for b in s) == 2


# 10. Export CSV
def test_export_csv():
    ins = Insight("u@test.dev", events=_events(20))
    csv_text = ins.export_csv(days=7)
    lines = [ln for ln in csv_text.strip().splitlines() if ln]
    assert lines[0] == "date,total,success,error,pending"
    assert len(lines) == 8  # header + 7 hari


# 11. Retention 365 hari
def test_retention_365():
    assert insights.RETENTION_DAYS == 365
    old = _ev(days_ago=364)
    assert len(insights.filter_events([old], 365, now=NOW)) == 1
    too_old = _ev(days_ago=400)
    assert len(insights.filter_events([too_old], 365, now=NOW)) == 0


# 12. Performance: 100k execution events
def test_performance_100k_events():
    ev = [_ev(days_ago=i % 365, status="completed" if i % 5 else "error",
              dur=(i % 500)) for i in range(100_000)]
    t0 = time.perf_counter()
    rep = Insight("u@test.dev", events=ev).report(days=30)
    elapsed = time.perf_counter() - t0
    assert rep["metrics"]["total"] > 0
    assert len(rep["series"]) == 30
    assert elapsed < 10.0, f"100k event terlalu lambat: {elapsed:.2f}s"


# 13. Benchmark: laporan dashboard < 2s
def test_benchmark_report_under_2s():
    ev = _events(5000)
    t0 = time.perf_counter()
    Insight("u@test.dev", events=ev).report(days=30)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"laporan terlalu lambat: {elapsed:.2f}s"


# 14. by_workflow agregasi
def test_by_workflow():
    ev = [_ev(wid="a"), _ev(wid="a"), _ev(wid="b", status="error")]
    rows = by_workflow(ev)
    assert rows[0]["workflow_id"] == "a"
    assert rows[0]["total"] == 2
    assert rows[1]["success_rate"] == 0.0


# 15. Laporan lengkap punya semua bagian
def test_report_shape():
    rep = Insight("u@test.dev", events=_events(50)).report(days=30)
    for key in ("range_days", "metrics", "time_saved", "roi", "series",
                "by_workflow", "retention_days"):
        assert key in rep
    assert rep["range_days"] == 30
    assert set(rep["metrics"]) >= {"total", "success_rate", "error_rate"}


# 16. Preset rentang dinormalkan (7/30/365)
def test_range_presets():
    ins = Insight("u@test.dev", events=_events(10))
    assert ins.report(days=7)["range_days"] == 7
    assert ins.report(days=30)["range_days"] == 30
    assert ins.report(days=365)["range_days"] == 365
    # nilai aneh dijepit
    assert ins.report(days=9999)["range_days"] == 365


# 17. to_csv menangani kolom hilang & tipe dict
def test_to_csv_robust():
    out = to_csv([{"a": 1, "b": {"x": 1}}, {"a": 2}], ["a", "b"])
    assert "a,b" in out
    assert '"{""x"": 1}"' in out or '{"x": 1}' in out


# 18. Event tanpa created_at diabaikan (bukan crash)
def test_event_without_timestamp_ignored():
    ev = [{"workflow_id": "w", "status": "completed"}, _ev()]
    assert compute_metrics(ev)["total"] == 2
    assert len(insights.filter_events(ev, 7, now=NOW)) == 1
