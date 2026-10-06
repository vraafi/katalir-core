"""Katalog tool MCP di system prompt (2026-10-06).

KENAPA TEST INI ADA
Permintaan "Buat workflow yang pakai MCP tool echo" dijawab model dengan node
mcp ber-provider `http` + URL karangan (`https://echo.free.beeceptor.com`),
padahal ada 44 tool MCP sungguhan di balik agentgateway. Jembatannya sudah
berfungsi (provider `gateway`), tetapi model tidak tahu katalognya ada — jadi
jalur MCP tidak pernah dipakai.

Sifat yang DIKUNCI di sini:
1. Pengambilan katalog TIDAK BOLEH memblokir request (`initialize` gateway
   terukur 8-13 detik, dan system prompt dibangun pada setiap request).
2. Cache diisi thread latar dan dipakai ulang sampai TTL habis.
3. Gateway mati tidak boleh mematikan chat (cukup katalog kosong).
4. Aturan 4a (provider gateway untuk tool MCP) tetap ada di prompt.
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api_server  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_catalog(monkeypatch):
    """Setiap test mulai dari cache kosong + tidak ada refresh berjalan."""
    monkeypatch.setattr(api_server, "_MCP_CATALOG", {"ts": 0.0, "text": ""})
    monkeypatch.setattr(api_server, "_MCP_CATALOG_BUSY", False)


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


def test_panggilan_pertama_tidak_memblokir(monkeypatch):
    """Cache kosong -> kembalikan '' SEGERA, refresh jalan di latar."""
    _patch_gateway(monkeypatch, tools=["everything_echo"], delay=3.0)
    t0 = time.time()
    text = api_server.mcp_gateway_catalog_text()
    elapsed = time.time() - t0
    assert text == ""
    assert elapsed < 1.0, f"memanggil gateway secara sinkron ({elapsed:.2f}s)"


def test_cache_diisi_thread_latar_lalu_dipakai(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo", "fetch_fetch"])
    api_server.mcp_gateway_catalog_text()          # memicu refresh
    for _ in range(50):                            # tunggu thread selesai
        if not api_server._MCP_CATALOG_BUSY and api_server._MCP_CATALOG["text"]:
            break
        time.sleep(0.05)
    text = api_server.mcp_gateway_catalog_text()
    assert "everything_echo" in text
    assert "fetch_fetch" in text
    assert "2 tool" in text
    assert calls["n"] == 1, "cache tidak dipakai ulang"


def test_cache_segar_tidak_memanggil_gateway_lagi(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo"])
    monkeypatch.setattr(api_server, "_MCP_CATALOG",
                        {"ts": time.time(), "text": "KATALOG COBA"})
    for _ in range(3):
        assert api_server.mcp_gateway_catalog_text() == "KATALOG COBA"
    assert calls["n"] == 0, "cache segar masih memanggil gateway"


def test_cache_basi_memicu_refresh_tapi_tetap_mengembalikan_lama(monkeypatch):
    calls = _patch_gateway(monkeypatch, tools=["everything_echo"], delay=0.5)
    monkeypatch.setattr(api_server, "_MCP_CATALOG",
                        {"ts": time.time() - api_server._MCP_CATALOG_TTL - 10,
                         "text": "LAMA"})
    assert api_server.mcp_gateway_catalog_text() == "LAMA"
    time.sleep(0.1)
    assert calls["n"] == 1


def test_gateway_mati_tidak_melempar_dan_katalog_kosong(monkeypatch):
    calls = _patch_gateway(monkeypatch, boom=True)
    assert api_server.mcp_gateway_catalog_text() == ""
    for _ in range(50):
        if not api_server._MCP_CATALOG_BUSY:
            break
        time.sleep(0.05)
    assert api_server._MCP_CATALOG["text"] == ""
    assert calls["n"] == 1
    # ts diperbarui -> tidak menghajar gateway berulang kali dalam TTL
    assert api_server._MCP_CATALOG["ts"] > 0


def test_katalog_kosong_tidak_menghasilkan_header_yang_menyesatkan(monkeypatch):
    """Bila gateway membalas daftar kosong, jangan tulis '0 tool tersedia'."""
    _patch_gateway(monkeypatch, tools=[])
    api_server._refresh_mcp_catalog()
    assert api_server._MCP_CATALOG["text"] == ""


def test_prompt_memuat_aturan_tool_mcp():
    """Regresi: aturan ini pernah hilang -> model kembali memakai provider http."""
    prompt = api_server._AGENT_SYSTEM
    assert "4a. TOOL MCP" in prompt
    assert "provider: \\\"gateway\\\"" in prompt or 'provider: "gateway"' in prompt
    assert "JANGAN memakai provider" in prompt
