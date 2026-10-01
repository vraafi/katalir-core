from mcp_gateway.client import GatewayClient, auth_configured
import pytest


@pytest.fixture(autouse=True)
def _clear_auth(monkeypatch):
    """Setiap test mulai dari kondisi 'tanpa kredensial'."""
    for env in ("AGENTGATEWAY_TOKEN", "GATEWAY_API_KEY", "CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_SECRET", "MCP_GATEWAY_ALLOW_ANON"):
        monkeypatch.delenv(env, raising=False)


def test_client_requires_url(monkeypatch):
    monkeypatch.delenv("AGENTGATEWAY_URL", raising=False)
    with pytest.raises(RuntimeError):
        GatewayClient(url="")


def test_client_gagal_tutup_tanpa_kredensial():
    """Jaring pengaman: gateway tidak boleh diprobe anonim tanpa sengaja."""
    with pytest.raises(RuntimeError, match="AGENTGATEWAY_TOKEN"):
        GatewayClient(url="https://gateway.example.com")


def test_client_boleh_tanpa_kredensial_bila_anon_diizinkan(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_ALLOW_ANON", "1")
    assert GatewayClient(url="https://gateway.example.com").mcp_url == "https://gateway.example.com/mcp"


def test_token_masuk_header_bukan_url(monkeypatch):
    monkeypatch.setenv("AGENTGATEWAY_TOKEN", "secret-token")
    c = GatewayClient(url="https://gateway.example.com")
    assert c.mcp_url == "https://gateway.example.com/mcp"
    assert "secret-token" not in c.mcp_url
    assert auth_configured() is True


def test_cloudflare_access_header_terkirim(monkeypatch):
    from mcp_gateway.client import _headers
    monkeypatch.setenv("AGENTGATEWAY_TOKEN", "tok")
    monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "cid")
    monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "csecret")
    h = _headers()
    assert h["Authorization"] == "Bearer tok"
    assert h["CF-Access-Client-Id"] == "cid"
    assert h["CF-Access-Client-Secret"] == "csecret"


def test_gateway_api_key_alias_juga_dipakai(monkeypatch):
    """Env name GATEWAY_API_KEY (dipakai di Railway) harus sama-sama honoured."""
    from mcp_gateway.client import _headers
    monkeypatch.setenv("GATEWAY_API_KEY", "alias-key")
    h = _headers()
    assert h["Authorization"] == "Bearer alias-key"
    assert h["x-api-key"] == "alias-key"
    assert "alias-key" not in GatewayClient(url="https://gateway.example.com").mcp_url


def test_token_tidak_pernah_di_query_string(monkeypatch):
    """Key tidak boleh bocor ke URL (masuk log proxy / access log)."""
    monkeypatch.setenv("AGENTGATEWAY_TOKEN", "leakme")
    c = GatewayClient(url="https://gateway.example.com")
    assert "leakme" not in c.mcp_url
    assert "?" not in c.mcp_url
