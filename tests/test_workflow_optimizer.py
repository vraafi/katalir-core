# tests/test_workflow_optimizer.py — Fitur #9 hard test (12 skenario, Okt 2026)
# Deterministik, murni: tanpa model/DB/jaringan.
from __future__ import annotations

import time

import pytest

import workflow_optimizer as opt


def _flow(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def _n(nid, kind, **cfg):
    return {"id": nid, "kind": kind, "config": cfg}


def _e(a, b):
    return {"source": a, "target": b}


# 1. Analyze 5 node -> rekomendasi
def test_01_analyze_5_nodes():
    flow = _flow(
        [_n("t", "trigger"), _n("a", "mcp", action="http", target="api/x"),
         _n("b", "code"), _n("c", "agent", prompt="ringkas"),
         _n("d", "code")],
        [_e("t", "a"), _e("a", "b"), _e("b", "c"), _e("c", "d")])
    hasil = opt.analyze(flow)
    assert hasil["node_count"] == 5
    assert hasil["cost_usd"] > 0 and hasil["latency_ms"] > 0
    assert isinstance(hasil["recommendations"], list)


# 2. Duplicate HTTP calls -> sarankan cache
def test_02_duplicate_cache():
    flow = _flow(
        [_n("t", "trigger"),
         _n("a", "mcp", action="http", url="https://api/x"),
         _n("b", "mcp", action="http", url="https://api/x")],
        [_e("t", "a"), _e("a", "b")])
    dup = opt.detect_duplicate_calls(flow)
    assert len(dup) == 1 and dup[0]["count"] == 2
    recs = opt.analyze(flow)["recommendations"]
    assert any(r["type"] == "cache" for r in recs)


# 3. Sequential -> sarankan parallel
def test_03_parallel():
    flow = _flow(
        [_n("t", "trigger"), _n("a", "mcp", url="x"), _n("b", "mcp", url="y"),
         _n("c", "code")],
        [_e("t", "a"), _e("t", "b"), _e("a", "c"), _e("b", "c")])
    par = opt.detect_sequential_parallelizable(flow)
    assert any(set(p["nodes"]) == {"a", "b"} for p in par)
    recs = opt.analyze(flow)["recommendations"]
    assert any(r["type"] == "parallel" and r["risk"] == "medium" for r in recs)


# 4. Akurasi estimasi biaya
def test_04_cost_accuracy():
    flow = _flow([_n("a", "agent"), _n("b", "mcp")], [])
    assert opt.estimate_cost(flow) == pytest.approx(0.0105, abs=1e-6)
    flow2 = _flow([_n("a", "code"), _n("b", "trigger")], [])
    assert opt.estimate_cost(flow2) == 0.0


# 5. Akurasi prediksi latensi (paralel = max, bukan jumlah)
def test_05_latency_accuracy():
    seq = _flow([_n("t", "trigger"), _n("a", "mcp"), _n("b", "code")],
                [_e("t", "a"), _e("a", "b")])
    # 1 + 300 + 20
    assert opt.estimate_latency(seq) == pytest.approx(321.0, abs=0.5)
    par = _flow([_n("t", "trigger"), _n("a", "mcp"), _n("b", "mcp")],
                [_e("t", "a"), _e("t", "b")])
    # level 0 = trigger(1); level 1 = max(300,300) = 300 -> total 301
    assert opt.estimate_latency(par) == pytest.approx(301.0, abs=0.5)


# 6. Auto-optimize: output tetap valid (workflow sama struktur inti)
def test_06_auto_optimize():
    flow = _flow(
        [_n("t", "trigger"), _n("a", "mcp", url="x"), _n("b", "mcp", url="x")],
        [_e("t", "a"), _e("a", "b")])
    out = opt.apply_safe(flow)
    assert out["applied"]
    baru = out["flow"]
    assert len(baru["nodes"]) == 3          # struktur node dipertahankan
    assert baru["nodes"][1]["config"]["cache"] is True
    # workflow asli TIDAK dimutasi
    assert "cache" not in flow["nodes"][1]["config"]


# 7. Tolak optimasi berisiko (parallel medium tidak diterapkan default)
def test_07_reject_risky():
    flow = _flow([_n("t", "trigger"), _n("a", "mcp", url="x"),
                  _n("b", "mcp", url="y")], [_e("t", "a"), _e("t", "b")])
    recs = opt.analyze(flow)["recommendations"]
    out = opt.apply(flow, recs, max_risk="low")
    # 'parallel' (medium) harus di-skip
    assert any(s["id"].startswith("parallel") for s in out["skipped"])
    assert not any(r.startswith("parallel") for r in out["applied"])
    # kalau diterima eksplisit -> baru diterapkan
    pid = [r["id"] for r in recs if r["type"] == "parallel"][0]
    out2 = opt.apply(flow, recs, accept_ids=[pid])
    assert pid in out2["applied"]


# 8. Performa: analisis 100 workflow
def test_08_performance_100():
    flows = []
    for i in range(100):
        flows.append(_flow(
            [_n("t", "trigger"), _n(f"a{i}", "mcp", url=f"x{i}"),
             _n(f"b{i}", "agent", prompt="p"), _n(f"c{i}", "code")],
            [_e("t", f"a{i}"), _e(f"a{i}", f"b{i}"), _e(f"b{i}", f"c{i}")]))
    t0 = time.perf_counter()
    for f in flows:
        opt.analyze(f)
    dt = time.perf_counter() - t0
    assert dt < 5.0, f"100 analisis terlalu lambat: {dt:.3f}s"


# 9. Multi-model support
def test_09_multi_model():
    flow = _flow([_n("a", "agent", model="gemini-3.8-pro"),
                  _n("b", "agent", model="gpt-5.1")], [])
    # 0.02 + 0.015
    assert opt.estimate_cost(flow) == pytest.approx(0.035, abs=1e-6)
    lat = opt.estimate_latency(flow)
    assert lat == pytest.approx(max(2200.0, 1800.0), abs=1.0)
    assert "gemini-3.8-pro" in opt.MODEL_PRICING


# 10. Loop umpan balik pengguna
def test_10_feedback_loop():
    fb = opt.FeedbackStore()
    fb.record("cache-a-b", accepted=True)
    fb.record("parallel-a-b", accepted=False, note="ubah urutan berisiko")
    fb.record("retry-a", accepted=True)
    assert len(fb.all()) == 3
    assert fb.acceptance_rate() == pytest.approx(2 / 3, abs=1e-4)


# 11. Benchmark: pengurangan biaya
def test_11_cost_reduction():
    flow = _flow(
        [_n("t", "trigger"), _n("a", "agent", prompt="p", model="gpt-5.1"),
         _n("b", "agent", prompt="p", model="gpt-5.1")],
        [_e("t", "a"), _e("a", "b")])
    sebelum = opt.estimate_cost(flow)
    hasil = opt.analyze(flow)
    assert hasil["potential_saving_cost"] > 0
    sesudah = sebelum - hasil["potential_saving_cost"]
    assert sesudah < sebelum


# 12. Keamanan: tidak bocorkan isi workflow
def test_12_no_content_leak():
    flow = _flow(
        [_n("t", "trigger"),
         _n("a", "mcp", url="https://api/x",
            password="secret://vault/db#pass", token="sk-abcdef123456")],
        [])
    hasil = opt.analyze(flow)
    blob = str(hasil)
    assert "secret://" not in blob
    assert "sk-abcdef123456" not in blob
    assert "password" not in blob
