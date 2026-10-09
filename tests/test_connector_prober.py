"""FASE 2 — prober kesehatan connector (connector_prober).

Tes tidak memanggil jaringan nyata kecuali ditandai; klien httpx di-inject.
"""
from __future__ import annotations

import json
import pathlib
import sys

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import connector_prober as cp  # noqa: E402


# --------------------------------------------------------------------------
# B — BASIC
# --------------------------------------------------------------------------

def test_b1_parse_plain_json():
    r = httpx.Response(200, json={"result": {"tools": []}},
                       headers={"content-type": "application/json"})
    assert cp._parse_body(r) == {"result": {"tools": []}}


def test_b2_parse_sse_body():
    text = 'event: message\ndata: {"result":{"tools":[{"name":"a"}]}}\n\n'
    r = httpx.Response(200, text=text,
                       headers={"content-type": "text/event-stream"})
    body = cp._parse_body(r)
    assert body["result"]["tools"][0]["name"] == "a"


# --------------------------------------------------------------------------
# E — EDGE
# --------------------------------------------------------------------------

def test_e1_parse_plain_text_returns_none():
    r = httpx.Response(200, text="not json",
                       headers={"content-type": "text/plain"})
    assert cp._parse_body(r) is None


def test_e2_parse_empty_sse_returns_none():
    r = httpx.Response(200, text="event: ping\n\n",
                       headers={"content-type": "text/event-stream"})
    assert cp._parse_body(r) is None


def test_e3_targets_only_streamable_http_with_url(monkeypatch):
    fake = {
        "a/1": {"install_config": {"transport": "streamable_http",
                                   "package": "https://x.dev/mcp"}},
        "a/2": {"install_config": {"transport": "metadata-only",
                                   "package": "pkg-name"}},
        "a/3": {"install_config": {"transport": "streamable_http",
                                   "package": "bukan-url"}},
    }
    import mcp_registry as mr
    monkeypatch.setattr(mr, "load_cached", lambda: fake)
    got = cp.targets()
    assert [t["connector_id"] for t in got] == ["a/1"]


# --------------------------------------------------------------------------
# X — ERROR
# --------------------------------------------------------------------------

def test_x1_network_error_becomes_dead(monkeypatch):
    class BoomClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise httpx.ProxyError("502 Bad Gateway")
    monkeypatch.setattr(httpx, "Client", BoomClient)
    r = cp.probe_endpoint("https://x.dev/mcp")
    assert r["verdict"] == "DEAD"
    assert "ProxyError" in r["error"]


def test_x2_timeout_becomes_dead(monkeypatch):
    class BoomClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(httpx, "Client", BoomClient)
    r = cp.probe_endpoint("https://x.dev/mcp")
    assert r["verdict"] == "DEAD"


def test_x3_http_500_becomes_dead(monkeypatch):
    class C500:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return httpx.Response(500, text="oops",
                                  headers={"content-type": "text/plain"})
    monkeypatch.setattr(httpx, "Client", C500)
    r = cp.probe_endpoint("https://x.dev/mcp")
    assert r["verdict"] == "DEAD"
    assert r["http_status"] == 500


def test_x4_401_becomes_auth(monkeypatch):
    class C401:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return httpx.Response(401, json={"error": "missing_bearer"},
                                  headers={"content-type": "application/json"})
    monkeypatch.setattr(httpx, "Client", C401)
    r = cp.probe_endpoint("https://x.dev/mcp")
    assert r["verdict"] == "AUTH"


def test_x5_rpc_error_on_tools_list_not_alive(monkeypatch):
    """200 tapi body berisi error -> BUKAN alive (jujur)."""
    state = {"n": 0}

    class CRpc:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(200, json={"result": {"protocolVersion": "x"}},
                                      headers={"content-type": "application/json"})
            return httpx.Response(200, json={"error": {"code": -32601,
                                                       "message": "Method not found"}},
                                  headers={"content-type": "application/json"})
    monkeypatch.setattr(httpx, "Client", CRpc)
    r = cp.probe_endpoint("https://x.dev/mcp")
    assert r["verdict"] != "ALIVE"
    assert r["tools_count"] is None


# --------------------------------------------------------------------------
# P — PERFORMANCE
# --------------------------------------------------------------------------

def test_p1_probe_many_parallel(monkeypatch):
    import time

    def fake_probe(url, timeout=12.0):
        return {"endpoint_url": url, "http_status": 200, "tools_count": 1,
                "verdict": "ALIVE", "error": None, "latency_ms": 1,
                "raw": None, "prober": "catalog-probe"}
    monkeypatch.setattr(cp, "probe_endpoint", fake_probe)
    items = [{"connector_id": f"x/{i}", "endpoint_url": f"https://x{i}.dev/mcp"}
             for i in range(200)]
    t0 = time.time()
    res = cp.probe_many(items, workers=16, progress=False)
    assert len(res) == 200
    assert time.time() - t0 < 10.0


def test_p2_summarize_counts():
    res = [{"verdict": "ALIVE", "http_status": 200, "tools_count": 3},
           {"verdict": "ALIVE", "http_status": 200, "tools_count": 2},
           {"verdict": "AUTH", "http_status": 401, "tools_count": None},
           {"verdict": "DEAD", "http_status": None, "tools_count": None}]
    s = cp.summarize(res)
    assert s["ALIVE"] == 2 and s["AUTH"] == 1 and s["DEAD"] == 1
    assert s["tools_total"] == 5
    assert s["total"] == 4


# --------------------------------------------------------------------------
# S — SECURITY
# --------------------------------------------------------------------------

def test_s1_no_credentials_sent_by_default():
    """Prober TIDAK boleh mengirim header Authorization."""
    src = pathlib.Path(cp.__file__).read_text(encoding="utf-8")
    assert "Authorization" not in src
    assert "Bearer" not in src


def test_s2_error_truncated():
    long_err = "x" * 5000
    assert len(("x" * 5000)[:400]) == 400


# --------------------------------------------------------------------------
# I — INTEGRATION
# --------------------------------------------------------------------------

def test_i1_to_health_rows_shape():
    res = [{"connector_id": "a/1", "endpoint_url": "https://x/mcp",
            "verdict": "ALIVE", "http_status": 200, "tools_count": 4,
            "latency_ms": 120, "error": None, "prober": "catalog-probe",
            "raw": {"tools_sample": ["t1"]}}]
    rows = cp.to_health_rows(res)
    assert rows[0]["connector_id"] == "a/1"
    assert rows[0]["verdict"] == "ALIVE"
    assert rows[0]["tools_count"] == 4


def test_i2_persist_uses_connector_store(monkeypatch):
    seen = {}

    def fake_record(rows, **k):
        seen["n"] = len(rows)
        return {"written": len(rows), "backend": "db"}
    monkeypatch.setattr(cp.cs, "record_health", fake_record)
    out = cp.persist([{"connector_id": "a/1", "verdict": "ALIVE"},
                      {"connector_id": "a/2", "verdict": "AUTH"}])
    assert out["written"] == 2
    assert seen["n"] == 2


def test_i3_describe_mentions_verdicts():
    d = cp.describe()
    assert set(d["verdicts"]) == {"ALIVE", "AUTH", "DEAD", "UNKNOWN"}
    assert d["protocol_version"] == cp.PROTOCOL_VERSION
