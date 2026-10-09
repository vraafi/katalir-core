"""FASE 3 — auto-fix connector (connector_repair).

Metodologi dari skill `opencli-autofix`. Tes memakai prober palsu (tanpa
jaringan) dan `sleep` no-op supaya cepat.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import connector_repair as cr  # noqa: E402


NOOP = lambda *_a, **_k: None  # noqa: E731


# --------------------------------------------------------------------------
# B — BASIC
# --------------------------------------------------------------------------

def test_b1_diagnose_alive_is_noop():
    d = cr.diagnose({"verdict": "ALIVE", "http_status": 200})
    assert d["repairable"] is False
    assert d["cause"] == "healthy"


def test_b2_diagnose_server_error_repairable():
    d = cr.diagnose({"verdict": "DEAD", "http_status": 502})
    assert d["repairable"] is True
    assert d["cause"] == "server_error"


# --------------------------------------------------------------------------
# E — EDGE
# --------------------------------------------------------------------------

def test_e1_auth_is_hard_stop():
    d = cr.diagnose({"verdict": "AUTH", "http_status": 401})
    assert d["repairable"] is False
    assert d["cause"] == "auth_required"


def test_e2_payment_required_hard_stop():
    d = cr.diagnose({"verdict": "UNKNOWN", "http_status": 402})
    assert d["repairable"] is False
    assert d["cause"] == "payment_required"


def test_e3_endpoint_moved_repairable():
    d = cr.diagnose({"verdict": "DEAD", "http_status": 404})
    assert d["cause"] == "endpoint_moved"
    assert d["repairable"] is True


# --------------------------------------------------------------------------
# X — ERROR
# --------------------------------------------------------------------------

def test_x1_repair_refuses_auth():
    rec = cr.repair_one({"connector_id": "a/1", "verdict": "AUTH",
                         "http_status": 401}, sleep=NOOP)
    assert rec["status"] == "refused"
    assert "kredensial" in rec["reason"]


def test_x2_repair_fixed_on_second_probe():
    state = {"n": 0}

    def probe(url, timeout=12.0):
        state["n"] += 1
        return {"verdict": "ALIVE", "http_status": 200, "tools_count": 4,
                "endpoint_url": url, "latency_ms": 10}
    rec = cr.repair_one({"connector_id": "a/2", "verdict": "DEAD",
                         "endpoint_url": "https://x/mcp", "http_status": 502},
                        probe=probe, sleep=NOOP)
    assert rec["status"] == "fixed"
    assert rec["after"] == "ALIVE"
    assert state["n"] >= 1


def test_x3_repair_unfixable_after_max_rounds():
    def probe(url, timeout=12.0):
        return {"verdict": "DEAD", "http_status": 502, "tools_count": None,
                "error": "ProxyError: 502"}
    rec = cr.repair_one({"connector_id": "a/3", "verdict": "DEAD",
                         "endpoint_url": "https://x/mcp", "http_status": 502},
                        probe=probe, sleep=NOOP)
    assert rec["status"] == "unfixable"
    assert len(rec["rounds"]) == cr.MAX_ROUNDS


def test_x4_probe_exception_does_not_raise():
    def probe(url, timeout=12.0):
        raise RuntimeError("boom")
    rec = cr.repair_one({"connector_id": "a/4", "verdict": "UNKNOWN",
                         "endpoint_url": "https://x/mcp"}, probe=probe, sleep=NOOP)
    assert rec["status"] in ("unfixable", "refused", "noop")


def test_x5_auth_after_reprobe_is_refused():
    def probe(url, timeout=12.0):
        return {"verdict": "AUTH", "http_status": 401, "tools_count": None}
    rec = cr.repair_one({"connector_id": "a/5", "verdict": "DEAD",
                         "endpoint_url": "https://x/mcp", "http_status": 502},
                        probe=probe, sleep=NOOP)
    assert rec["status"] == "refused"


# --------------------------------------------------------------------------
# P — PERFORMANCE
# --------------------------------------------------------------------------

def test_p1_repair_many_skips_non_repairable():
    calls = {"n": 0}

    def probe(url, timeout=12.0):
        calls["n"] += 1
        return {"verdict": "DEAD", "http_status": 502, "tools_count": None}
    results = [{"connector_id": f"a/{i}", "verdict": "AUTH", "http_status": 401}
               for i in range(20)]
    out = cr.repair_many(results, probe=probe, sleep=NOOP)
    assert calls["n"] == 0          # AUTH = hard stop, tidak diprobe
    assert len(out["records"]) == 0


def test_p2_repair_many_counts_statuses():
    def probe(url, timeout=12.0):
        return {"verdict": "DEAD", "http_status": 502, "tools_count": None}
    results = [{"connector_id": f"b/{i}", "verdict": "DEAD",
                "endpoint_url": "https://x/mcp", "http_status": 502}
               for i in range(5)]
    out = cr.repair_many(results, probe=probe, sleep=NOOP)
    assert out["status"]["unfixable"] == 5


# --------------------------------------------------------------------------
# S — SECURITY
# --------------------------------------------------------------------------

def test_s1_repair_never_deletes_catalog_entry():
    src = pathlib.Path(cr.__file__).read_text(encoding="utf-8")
    assert "pop(" not in src
    assert "del " not in src.replace("delete the", "")


def test_s2_hard_stops_declared():
    assert "AUTH" in cr.HARD_STOPS
    assert cr.MAX_ROUNDS == 3


# --------------------------------------------------------------------------
# I — INTEGRATION
# --------------------------------------------------------------------------

def test_i1_log_is_append_only_jsonl(tmp_path):
    log = tmp_path / "repair.jsonl"
    cr.repair_one({"connector_id": "a/1", "verdict": "AUTH", "http_status": 401},
                  log_path=log, sleep=NOOP)
    cr.repair_one({"connector_id": "a/2", "verdict": "AUTH", "http_status": 401},
                  log_path=log, sleep=NOOP)
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["connector_id"] == "a/1"


def test_i2_apply_fixes_marks_unfixable_unhealthy(monkeypatch):
    import mcp_registry as mr
    fake = {"c/1": {"id": "c/1", "healthy": True, "install_config": {}}}
    monkeypatch.setattr(mr, "load_cached", lambda: fake)
    seen = {}
    monkeypatch.setattr(cr.cs, "record_health",
                        lambda rows, **k: seen.setdefault("rows", rows) or {"written": len(rows)})
    repairs = {"records": [{"connector_id": "c/1", "status": "unfixable",
                            "rounds": [{"http_status": 502}], "reason": "mati"}]}
    cr.apply_fixes(repairs)
    assert fake["c/1"]["healthy"] is False
    assert seen["rows"][0]["verdict"] == "DEAD"


def test_i3_describe_contract():
    d = cr.describe()
    assert d["max_rounds"] == 3
    assert set(d["statuses"]) == {"fixed", "refused", "unfixable", "noop"}
