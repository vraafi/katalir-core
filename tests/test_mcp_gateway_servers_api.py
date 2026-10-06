"""Endpoint `GET /mcp/gateway/servers`: cache + fallback stale, BUKAN 503.

REGRESI YANG DIKUNCI
Terbukti di produksi 2026-10-06: saat guard VPS me-restart agentgateway
(01:26:59), `GET /mcp/gateway/servers` membalas **HTTP 503** — pemilih tool MCP
di UI langsung mati, padahal daftar 44 tool nyaris tidak pernah berubah.
Sekarang: bila gateway gagal TETAPI ada cache, endpoint tetap membalas 200
dengan `source="stale"` + `warning`. 503 hanya bila memang belum ada data.
"""
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api_server  # noqa: E402
import mcp_tool_cache  # noqa: E402

client = TestClient(api_server.app, raise_server_exceptions=False)
H = {"Authorization": "Bearer uji-jwt"}


@pytest.fixture(autouse=True)
def _auth_and_cache(monkeypatch):
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"id": "u-mcp", "email": "mcp@katalir.test"})
    mcp_tool_cache.invalidate()
    with mcp_tool_cache._lock:
        mcp_tool_cache._state["refreshing"] = False
    yield
    mcp_tool_cache.invalidate()


def _patch_gateway(monkeypatch, *, tools=None, boom=False):
    calls = {"n": 0}

    class _Fake:
        def list_tools_sync(self):
            calls["n"] += 1
            if boom:
                raise RuntimeError("Gateway tidak tersedia")
            return [{"name": n} for n in (tools or [])]

    import mcp_gateway.client as gwc
    monkeypatch.setattr(gwc, "GatewayClient", _Fake)
    return calls


def test_cache_kosong_gateway_ok(monkeypatch):
    _patch_gateway(monkeypatch, tools=["everything_echo", "fetch_fetch"])
    r = client.get("/mcp/gateway/servers", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "gateway"
    assert [t["name"] for t in body["tools"]] == ["everything_echo", "fetch_fetch"]


def test_cache_segar_tidak_memanggil_gateway(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo"])
    client.get("/mcp/gateway/servers", headers=H)
    r = client.get("/mcp/gateway/servers", headers=H)
    assert r.status_code == 200
    assert r.json()["source"] == "cache"
    assert calls["n"] == 1


def test_gateway_gagal_dengan_cache_lama_tetap_200_bukan_503(monkeypatch):
    """INTI perbaikan: data lama > 503."""
    mcp_tool_cache.store([{"name": "everything_echo"}])
    with mcp_tool_cache._lock:
        mcp_tool_cache._state["at"] = time.time() - mcp_tool_cache.TTL_S - 10
    _patch_gateway(monkeypatch, boom=True)

    r = client.get("/mcp/gateway/servers", headers=H)
    assert r.status_code == 200, f"masih {r.status_code}, harusnya 200 stale"
    body = r.json()
    assert body["source"] == "stale"
    assert body["warning"], "warning kosong padahal datanya basi"
    assert [t["name"] for t in body["tools"]] == ["everything_echo"]


def test_gateway_gagal_tanpa_cache_baru_503(monkeypatch):
    _patch_gateway(monkeypatch, boom=True)
    r = client.get("/mcp/gateway/servers", headers=H)
    assert r.status_code == 503
    assert "Gateway tidak tersedia" in r.json()["detail"]


def test_refresh_param_memaksa_ambil_ulang(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo"])
    client.get("/mcp/gateway/servers", headers=H)
    r = client.get("/mcp/gateway/servers?refresh=1", headers=H)
    assert r.status_code == 200
    assert r.json()["source"] == "gateway"
    assert calls["n"] == 2


def test_endpoint_tetap_menerima_tools_tanpa_field_tambahan(monkeypatch):
    """Kompatibilitas: klien lama hanya membaca `tools`."""
    _patch_gateway(monkeypatch, tools=["everything_echo"])
    body = client.get("/mcp/gateway/servers", headers=H).json()
    assert "tools" in body and isinstance(body["tools"], list)
