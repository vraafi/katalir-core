"""Cache katalog tool MCP + penyuntikan ke system prompt (2026-10-06).

KENAPA TEST INI ADA
1. Permintaan "Buat workflow yang pakai MCP tool echo" dijawab model dengan node
   mcp ber-provider `http` + URL karangan (`https://echo.free.beeceptor.com`),
   padahal ada 44 tool MCP sungguhan di balik agentgateway. Jembatannya sudah
   berfungsi; model tidak tahu katalognya ada.
2. `GET /mcp/gateway/servers` butuh 8-13 detik dan membalas **503** saat gateway
   tidak bisa dihubungi. Terbukti di produksi: saat guard VPS me-restart
   agentgateway (01:26:59), panggilan langsung 503 — padahal daftar tool nyaris
   tidak pernah berubah.

Sifat yang DIKUNCI:
* pembacaan katalog tidak pernah memblokir request (refresh di thread latar);
* cache segar dipakai ulang (tidak menghajar gateway tiap request);
* gateway gagal + ada cache lama -> sajikan STALE, jangan 503;
* gateway gagal + tidak ada cache -> `source="none"` (baru boleh 503);
* gateway mati tidak boleh mematikan chat.
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api_server  # noqa: E402
import mcp_tool_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_cache():
    mcp_tool_cache.invalidate()
    with mcp_tool_cache._lock:
        mcp_tool_cache._state["refreshing"] = False
    yield
    mcp_tool_cache.invalidate()
    with mcp_tool_cache._lock:
        mcp_tool_cache._state["refreshing"] = False


def _patch_gateway(monkeypatch, *, tools=None, delay=0.0, boom=False):
    """Ganti GatewayClient dengan fake; tidak ada jaringan."""
    calls = {"n": 0}

    class _Fake:
        def list_tools_sync(self):
            calls["n"] += 1
            if delay:
                time.sleep(delay)
            if boom:
                raise RuntimeError("gateway mati")
            return [{"name": n} for n in (tools or [])]

    import mcp_gateway.client as gwc
    monkeypatch.setattr(gwc, "GatewayClient", _Fake)
    return calls


# ---------------------------------------------------------------------------
# Cache: penyajian & fallback
# ---------------------------------------------------------------------------
def test_cache_kosong_mengambil_dari_gateway(monkeypatch):
    _patch_gateway(monkeypatch, tools=["everything_echo", "fetch_fetch"])
    out = mcp_tool_cache.get_tools()
    assert out["source"] == "gateway"
    assert [t["name"] for t in out["tools"]] == ["everything_echo", "fetch_fetch"]


def test_cache_segar_dipakai_ulang_tanpa_gateway(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo"])
    mcp_tool_cache.get_tools()
    for _ in range(4):
        out = mcp_tool_cache.get_tools()
        assert out["source"] == "cache"
    assert calls["n"] == 1, "cache segar masih memanggil gateway"


def test_force_refresh_menembus_cache(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo"])
    mcp_tool_cache.get_tools()
    out = mcp_tool_cache.get_tools(force_refresh=True)
    assert out["source"] == "gateway"
    assert calls["n"] == 2


def test_gateway_gagal_tapi_ada_cache_lama_disajikan_stale(monkeypatch):
    """INI yang menghilangkan 503: data lama tetap dilayani."""
    mcp_tool_cache.store([{"name": "everything_echo"}])
    with mcp_tool_cache._lock:                 # buat cache dianggap basi
        mcp_tool_cache._state["at"] = time.time() - mcp_tool_cache.TTL_S - 10
    _patch_gateway(monkeypatch, boom=True)

    out = mcp_tool_cache.get_tools()
    assert out["source"] == "stale"
    assert [t["name"] for t in out["tools"]] == ["everything_echo"]
    assert "gateway mati" in out["error"]


def test_gateway_gagal_tanpa_cache_menghasilkan_none(monkeypatch):
    _patch_gateway(monkeypatch, boom=True)
    out = mcp_tool_cache.get_tools()
    assert out["source"] == "none"
    assert out["tools"] == []


def test_gateway_membalas_daftar_kosong_tidak_menimpa_cache(monkeypatch):
    mcp_tool_cache.store([{"name": "everything_echo"}])
    with mcp_tool_cache._lock:
        mcp_tool_cache._state["at"] = time.time() - mcp_tool_cache.TTL_S - 10
    _patch_gateway(monkeypatch, tools=[])
    out = mcp_tool_cache.get_tools()
    assert out["source"] == "stale"
    assert [t["name"] for t in out["tools"]] == ["everything_echo"]


def test_cache_age_dan_is_fresh():
    assert mcp_tool_cache.cache_age_s() == float("inf")
    assert mcp_tool_cache.is_fresh() is False
    mcp_tool_cache.store([{"name": "x"}])
    assert mcp_tool_cache.cache_age_s() < 2
    assert mcp_tool_cache.is_fresh() is True


# ---------------------------------------------------------------------------
# Refresh latar (tidak boleh memblokir)
# ---------------------------------------------------------------------------
def test_refresh_async_tidak_memblokir(monkeypatch):
    _patch_gateway(monkeypatch, tools=["everything_echo"], delay=3.0)
    t0 = time.time()
    assert mcp_tool_cache.refresh_async() is True
    assert time.time() - t0 < 1.0, "refresh_async memblokir"
    for _ in range(80):
        if mcp_tool_cache.cached_tools():
            break
        time.sleep(0.05)
    assert [t["name"] for t in mcp_tool_cache.cached_tools()] == ["everything_echo"]


def test_refresh_async_tidak_menumpuk_thread(monkeypatch):
    _patch_gateway(monkeypatch, tools=["a"], delay=1.0)
    assert mcp_tool_cache.refresh_async() is True
    assert mcp_tool_cache.refresh_async() is False, "thread refresh menumpuk"
    for _ in range(60):
        if not mcp_tool_cache._state["refreshing"]:
            break
        time.sleep(0.05)


def test_refresh_async_gateway_mati_tidak_melempar(monkeypatch):
    _patch_gateway(monkeypatch, boom=True)
    mcp_tool_cache.refresh_async()
    for _ in range(60):
        if not mcp_tool_cache._state["refreshing"]:
            break
        time.sleep(0.05)
    assert mcp_tool_cache.cached_tools() == []


# ---------------------------------------------------------------------------
# Penyuntikan ke system prompt
# ---------------------------------------------------------------------------
def test_katalog_text_memuat_nama_tool(monkeypatch):
    mcp_tool_cache.store([{"name": "everything_echo"}, {"name": "fetch_fetch"}])
    text = api_server.mcp_gateway_catalog_text()
    assert "everything_echo" in text
    assert "fetch_fetch" in text
    assert "2 tool" in text


def test_katalog_text_kosong_bila_belum_ada_data(monkeypatch):
    """Jangan tulis '0 tool tersedia' — itu menyesatkan model."""
    assert api_server.mcp_gateway_catalog_text() == ""


def test_katalog_text_tidak_memblokir_saat_cache_basi(monkeypatch):
    _patch_gateway(monkeypatch, tools=["everything_echo"], delay=3.0)
    t0 = time.time()
    api_server.mcp_gateway_catalog_text()      # cache kosong -> picu refresh latar
    assert time.time() - t0 < 1.0, "system prompt menunggu gateway secara sinkron"


def test_prompt_memuat_aturan_tool_mcp():
    """Regresi: tanpa aturan ini model kembali memakai provider http + URL karangan."""
    prompt = api_server._AGENT_SYSTEM
    assert "4a. TOOL MCP" in prompt
    assert 'provider: "gateway"' in prompt
    assert "JANGAN memakai provider" in prompt
