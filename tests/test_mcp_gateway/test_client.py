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


# ---------------------------------------------------------------------------
# Regresi /mcp/gateway/health: gateway sehat dilaporkan "unreachable".
#
# Terukur di produksi: `initialize` ke agentgateway butuh 13,2 detik karena
# diteruskan ke semua target stdio (npx/uvx) yang cold-start. Budget keras 5
# detik membuat health() melempar ReadTimeout -> False, padahal list_tools()
# dan call_tool() pada saat yang sama sukses (44 tools, echo OK).
# ---------------------------------------------------------------------------


def test_health_timeout_default_lebih_longgar_dari_5_detik():
    """Nilai 5 detik yang lama TIDAK boleh kembali."""
    from mcp_gateway.client import DEFAULT_HEALTH_TIMEOUT, health_timeout
    assert DEFAULT_HEALTH_TIMEOUT > 5
    assert health_timeout() >= 20


def test_health_timeout_bisa_diatur_via_env(monkeypatch):
    from mcp_gateway.client import health_timeout
    monkeypatch.setenv("MCP_GATEWAY_HEALTH_TIMEOUT", "45")
    assert health_timeout() == 45.0


@pytest.mark.parametrize("bad", ["", "abc", "0", "-3"])
def test_health_timeout_env_tidak_valid_kembali_ke_default(monkeypatch, bad):
    from mcp_gateway.client import DEFAULT_HEALTH_TIMEOUT, health_timeout
    monkeypatch.setenv("MCP_GATEWAY_HEALTH_TIMEOUT", bad)
    assert health_timeout() == DEFAULT_HEALTH_TIMEOUT


class _FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers if headers is not None else {}


class _FakeAsyncClient:
    """Merekam timeout yang dipakai health() dan mengembalikan status buatan.

    `scenario` sengaja disimpan di atribut kelas TERPISAH: `__init__` dipanggil
    di dalam health(), jadi apa pun yang ditulis ke `last` saat menyiapkan test
    akan tertimpa.
    """

    last: dict = {}
    scenario: dict = {}
    calls: list = []

    def __init__(self, timeout=None, **kwargs):
        _FakeAsyncClient.last = {"timeout": timeout, "kwargs": kwargs}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last["url"] = url
        _FakeAsyncClient.last["headers"] = headers or {}
        _FakeAsyncClient.calls.append(("POST", url, headers or {}))
        if _FakeAsyncClient.scenario.get("raise"):
            raise RuntimeError("koneksi ditolak")
        return _FakeResponse(_FakeAsyncClient.scenario.get("status", 200),
                             _FakeAsyncClient.scenario.get("headers"))

    async def request(self, method, url, headers=None, **kwargs):
        _FakeAsyncClient.calls.append((method, url, headers or {}))
        if _FakeAsyncClient.scenario.get("delete_raises"):
            raise RuntimeError("DELETE gagal")
        return _FakeResponse(202)


def _health_with(monkeypatch, status=200, raise_=False, timeout_env=None,
                 resp_headers=None, delete_raises=False):
    import asyncio
    import httpx
    import mcp_gateway.client as mod

    monkeypatch.setenv("AGENTGATEWAY_TOKEN", "tok")
    if timeout_env is not None:
        monkeypatch.setenv("MCP_GATEWAY_HEALTH_TIMEOUT", timeout_env)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.last = {}
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.scenario = {"status": status, "raise": raise_,
                                 "headers": resp_headers,
                                 "delete_raises": delete_raises}
    client = mod.GatewayClient(url="https://gateway.example.com")
    result = asyncio.run(client.health())
    return result, list(_FakeAsyncClient.calls)


def test_health_pakai_timeout_hasil_konfigurasi(monkeypatch):
    """Health WAJIB memakai health_timeout(), bukan angka keras."""
    ok, _ = _health_with(monkeypatch, status=200, timeout_env="42")
    assert ok is True
    assert _FakeAsyncClient.last["timeout"] == 42.0


def test_health_true_untuk_200_dan_202(monkeypatch):
    assert _health_with(monkeypatch, status=200)[0] is True
    assert _health_with(monkeypatch, status=202)[0] is True


def test_health_false_untuk_status_error(monkeypatch):
    assert _health_with(monkeypatch, status=401)[0] is False
    assert _health_with(monkeypatch, status=503)[0] is False


def test_health_false_saat_koneksi_gagal(monkeypatch):
    """Kegagalan transport tetap False - hanya timeout-nya yang diperbaiki."""
    assert _health_with(monkeypatch, raise_=True)[0] is False


def test_health_kirim_kredensial_di_header(monkeypatch):
    _health_with(monkeypatch, status=200)
    headers = _FakeAsyncClient.last["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert "tok" not in _FakeAsyncClient.last["url"]


# ---------------------------------------------------------------------------
# health() WAJIB menutup sesinya (kebocoran proses di gateway)
#
# Terukur di produksi 2026-10-06: setiap `GET /mcp/gateway/health` menambah
# TEPAT 13 proses target stdio yang tidak pernah direap (~330 MB). 3 pemeriksaan
# -> mcp_procs 26 -> 65, mem_available 1211 -> 303 MB. Sebabnya probe ini
# mengirim `initialize` tanpa `DELETE`.
# ---------------------------------------------------------------------------


def test_health_menutup_sesi_bila_gateway_memberi_session_id(monkeypatch):
    ok, calls = _health_with(monkeypatch, status=200,
                             resp_headers={"mcp-session-id": "sess-123"})
    assert ok is True
    methods = [c[0] for c in calls]
    assert "DELETE" in methods, "sesi tidak ditutup -> gateway tidak mereap target stdio"
    delete = next(c for c in calls if c[0] == "DELETE")
    assert delete[2].get("Mcp-Session-Id") == "sess-123"


def test_health_menutup_sesi_untuk_header_title_case(monkeypatch):
    _, calls = _health_with(monkeypatch, status=200,
                            resp_headers={"Mcp-Session-Id": "sess-abc"})
    assert any(c[0] == "DELETE" and c[2].get("Mcp-Session-Id") == "sess-abc"
               for c in calls)


def test_health_tanpa_session_id_tidak_mengirim_delete(monkeypatch):
    _, calls = _health_with(monkeypatch, status=200, resp_headers={})
    assert not any(c[0] == "DELETE" for c in calls)


def test_health_tetap_true_walau_delete_gagal(monkeypatch):
    """Kegagalan menutup sesi tidak boleh mengubah hasil probe."""
    ok, calls = _health_with(monkeypatch, status=200,
                             resp_headers={"mcp-session-id": "s"},
                             delete_raises=True)
    assert ok is True
    assert any(c[0] == "DELETE" for c in calls)


def test_health_false_tidak_mengirim_delete(monkeypatch):
    """Gateway membalas 401 -> tidak ada sesi yang perlu ditutup."""
    ok, calls = _health_with(monkeypatch, status=401,
                             resp_headers={"mcp-session-id": "s"})
    assert ok is False
    assert not any(c[0] == "DELETE" for c in calls)
