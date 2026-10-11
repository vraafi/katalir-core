"""Hard test TASK 2 — mcp_compat: jembatan MCP SDK 1.x <-> 2.x.

12 skenario: deteksi versi, transport 1.x (3-tuple), transport 2.x (2-tuple),
passthrough header/timeout, http_client factory, model camelCase vs snake_case,
is_error/next_cursor/structured_content lintas versi, make_server 1.x & 2.x,
streamable_http_app, dan regresi bentuk tak dikenal.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
import types

import pytest

import mcp_compat as mc


def _run(coro):
    return asyncio.run(coro)


# --- fake transport modules ------------------------------------------------
class FakeV1:
    """Meniru SDK 1.x: 3-tuple, kwarg langsung."""

    def __init__(self):
        self.calls = []

    @contextlib.asynccontextmanager
    async def streamablehttp_client(self, url, **kw):
        self.calls.append((url, kw))
        yield ("READ", "WRITE", "SESSION-ID")


class FakeV2:
    """Meniru SDK 2.x: 2-tuple, http_client eksplisit."""

    def __init__(self):
        self.calls = []

    @contextlib.asynccontextmanager
    async def streamable_http_client(self, url, *, http_client=None, **kw):
        self.calls.append((url, http_client, kw))
        yield ("READ", "WRITE")


class FakeClient:
    def __init__(self, headers):
        self.headers = headers
        self.closed = False

    async def aclose(self):
        self.closed = True


# 1. Deteksi versi ---------------------------------------------------------
def test_01_version_detection(monkeypatch):
    monkeypatch.setattr(mc, "mcp_version", lambda: "1.28.1")
    assert mc.mcp_major() == 1 and mc.is_v2() is False
    monkeypatch.setattr(mc, "mcp_version", lambda: "2.3.0")
    assert mc.mcp_major() == 2 and mc.is_v2() is True
    monkeypatch.setattr(mc, "mcp_version", lambda: "")
    with pytest.raises(mc.McpCompatError):
        mc.mcp_major()


# 2. Transport 1.x (3-tuple) -> (read, write) ------------------------------
def test_02_transport_v1_three_tuple():
    mod = FakeV1()

    async def go():
        async with mc.open_streamable_http("http://x/mcp", module=mod, major=1) as (r, w):
            return r, w
    r, w = _run(go())
    assert (r, w) == ("READ", "WRITE")
    assert mod.calls[0][0] == "http://x/mcp"


# 3. Transport 2.x (2-tuple) -> (read, write) ------------------------------
def test_03_transport_v2_two_tuple():
    mod = FakeV2()

    async def go():
        async with mc.open_streamable_http(
                "http://x/mcp", module=mod, major=2,
                http_client_factory=FakeClient) as (r, w):
            return r, w
    r, w = _run(go())
    assert (r, w) == ("READ", "WRITE")


# 4. Passthrough header/timeout (1.x) -------------------------------------
def test_04_v1_headers_and_timeout():
    mod = FakeV1()

    async def go():
        async with mc.open_streamable_http(
                "http://x/mcp", headers={"Authorization": "Bearer t"},
                timeout=30, sse_read_timeout=300, module=mod, major=1):
            pass
    _run(go())
    _, kw = mod.calls[0]
    assert kw["headers"] == {"Authorization": "Bearer t"}
    assert kw["timeout"] == 30 and kw["sse_read_timeout"] == 300


# 5. Passthrough header via http_client factory (2.x) ----------------------
def test_05_v2_http_client_factory():
    mod = FakeV2()
    made = {}

    def factory(headers):
        made["c"] = FakeClient(headers)
        return made["c"]

    async def go():
        async with mc.open_streamable_http(
                "http://x/mcp", headers={"x-api-key": "k"},
                module=mod, major=2, http_client_factory=factory):
            pass
    _run(go())
    _, client, _kw = mod.calls[0]
    assert client is made["c"]
    assert client.headers == {"x-api-key": "k"}
    assert client.closed is True          # ditutup setelah konteks keluar


# 6. tool_input_schema camelCase (1.x) vs snake_case (2.x) -----------------
def test_06_tool_input_schema_both():
    v1 = {"name": "t", "inputSchema": {"type": "object"}}
    v2 = {"name": "t", "input_schema": {"type": "object"}}
    assert mc.tool_input_schema(v1) == {"type": "object"}
    assert mc.tool_input_schema(v2) == {"type": "object"}
    assert mc.tool_input_schema({}) == {}


# 7. tool_is_error lintas versi -------------------------------------------
def test_07_tool_is_error_both():
    assert mc.tool_is_error({"isError": True}) is True
    assert mc.tool_is_error({"is_error": True}) is True
    assert mc.tool_is_error({"isError": False}) is False
    assert mc.tool_is_error({}) is False


# 8. next_cursor / structured_content lintas versi ------------------------
def test_08_cursor_and_structured():
    assert mc.tool_next_cursor({"nextCursor": "c1"}) == "c1"
    assert mc.tool_next_cursor({"next_cursor": "c2"}) == "c2"
    assert mc.tool_next_cursor({}) is None
    assert mc.tool_structured_content({"structuredContent": {"a": 1}}) == {"a": 1}
    assert mc.tool_structured_content({"structured_content": {"b": 2}}) == {"b": 2}


# 9. normalize_tool + objek Pydantic-like ---------------------------------
def test_09_normalize_tool_and_model_object():
    class Tool:  # meniru model pydantic 2.x
        def model_dump(self, by_alias=False):
            return {"name": "x", "description": "d", "input_schema": {"type": "object"}}

    out = mc.normalize_tool(Tool())
    assert out["name"] == "x" and out["description"] == "d"
    assert out["input_schema"] == {"type": "object"}

    out2 = mc.normalize_tool({"name": "y", "inputSchema": {"type": "object"}})
    assert out2["input_schema"] == {"type": "object"}


# 10. make_server 1.x -> FastMCP ------------------------------------------
def test_10_make_server_v1(monkeypatch):
    monkeypatch.setattr(mc, "is_v2", lambda: False)
    srv = mc.make_server("Katalir", instructions="halo", stateless_http=True,
                         streamable_http_path="/mcp")
    assert srv.__class__.__name__ == "FastMCP"
    assert mc.server_class_name() == "FastMCP"


# 11. make_server 2.x -> MCPServer, kwarg 1.x dibuang ----------------------
def test_11_make_server_v2_filters_kwargs(monkeypatch):
    captured: dict = {}

    class FakeMCPServer:
        def __init__(self, name, **kw):
            captured["name"] = name
            captured.update(kw)

    mod = types.ModuleType("mcp.server.mcpserver")
    mod.MCPServer = FakeMCPServer
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", mod)
    monkeypatch.setattr(mc, "is_v2", lambda: True)

    srv = mc.make_server("Katalir", instructions="halo", version="1.2.3",
                         stateless_http=True, transport_security="TS",
                         streamable_http_path="/mcp", debug=True)
    assert isinstance(srv, FakeMCPServer)
    assert captured["name"] == "Katalir"
    assert captured["instructions"] == "halo"
    assert captured["version"] == "1.2.3"
    assert captured["debug"] is True
    # Kwarg khusus FastMCP TIDAK diteruskan ke MCPServer.
    for bad in ("stateless_http", "transport_security", "streamable_http_path"):
        assert bad not in captured, f"{bad} seharusnya dibuang"
    assert mc.server_class_name() == "MCPServer"


def test_11b_dropped_server_kwargs(monkeypatch):
    monkeypatch.setattr(mc, "is_v2", lambda: True)
    assert set(mc.dropped_server_kwargs(
        ["stateless_http", "debug", "transport_security"])) == {
        "stateless_http", "transport_security"}
    monkeypatch.setattr(mc, "is_v2", lambda: False)
    assert mc.dropped_server_kwargs(["stateless_http"]) == []


# 12. streamable_http_app + regresi bentuk tak dikenal ---------------------
def test_12_app_and_regressions():
    class FakeServer:
        def streamable_http_app(self):
            return "ASGI-APP"

    assert mc.streamable_http_app(FakeServer()) == "ASGI-APP"
    with pytest.raises(mc.McpCompatError):
        mc.streamable_http_app(object())

    # tuple dengan < 2 elemen -> error jelas
    from mcp_compat import _streams_pair
    with pytest.raises(mc.McpCompatError):
        _streams_pair(("hanya-satu",))

    # modul tanpa fungsi transport -> error jelas
    empty = types.ModuleType("empty")
    async def go():
        async with mc.open_streamable_http("http://x", module=empty, major=1):
            pass
    with pytest.raises(mc.McpCompatError):
        _run(go())
