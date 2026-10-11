"""mcp_compat.py — jembatan MCP Python SDK 1.x <-> 2.x.

LATAR (TASK 2, 11 Okt 2026)
---------------------------
MCP Python SDK 2.0.0 (PyPI, 2026-07-28) membawa breaking change besar. Yang
terverifikasi langsung dari paket 2.3.0 (lihat `_mcp2_probe/`, gitignored):

  1. ``mcp.server.fastmcp.FastMCP`` -> ``mcp.server.mcpserver.MCPServer``.
     Paket 2.x bahkan menaikkan ModuleNotFoundError berisi instruksi migrasi.
  2. ``mcp.client.streamable_http.streamablehttp_client`` ->
     ``streamable_http_client(url, *, http_client=<httpx2.AsyncClient>)``.
     Context manager 1.x men-``yield`` **3-tuple** ``(read, write, get_session_id)``;
     2.x men-``yield`` **2-tuple** ``(read, write)``.
  3. Parameter koneksi (``timeout``/``sse_read_timeout``/``headers``) DILARANG
     sebagai kwarg transport; harus di set pada ``httpx2.AsyncClient`` eksplisit.
  4. Model Pydantic berpindah camelCase -> snake_case: ``tool.inputSchema`` ->
     ``input_schema``, ``result.isError`` -> ``is_error``, ``nextCursor`` ->
     ``next_cursor``, ``structuredContent`` -> ``structured_content``.
     Wire format JSON-RPC tetap camelCase (alias), jadi hanya kode Python yang
     pecah.
  5. SDK 2.x memakai paket ``httpx2`` (bukan ``httpx``).

Modul ini membuat kode Katalir **jalan di kedua versi** tanpa cabang di
call-site. Deteksi versi memakai nomor major dari metadata distribusi
(bukan nama fungsi: 1.x terbaru juga punya alias ``streamable_http_client``,
sehingga deteksi berbasis nama TIDAK andal).
"""

from __future__ import annotations

import contextlib
import functools
from typing import Any, AsyncIterator, Callable, Iterable

#: Kwarg yang hanya dikenal FastMCP (1.x). Dibuang saat membangun MCPServer (2.x).
_V1_ONLY_SERVER_KWARGS = frozenset({
    "stateless_http", "streamable_http_path", "transport_security",
    "sse_path", "message_path", "json_response", "event_store",
    "retry_interval", "host", "port", "mount_path",
})


class McpCompatError(RuntimeError):
    """Lingkungan MCP tidak dikenali."""


# --------------------------------------------------------------------------
# Deteksi versi
# --------------------------------------------------------------------------
def mcp_version() -> str:
    """Versi distribusi ``mcp`` yang terpasang."""
    try:
        from importlib.metadata import version
        return version("mcp")
    except Exception:  # noqa: BLE001 - metadata tak tersedia
        try:
            import mcp
            return str(getattr(mcp, "__version__", "") or "")
        except Exception:  # noqa: BLE001
            raise McpCompatError("paket 'mcp' tidak terpasang")


def mcp_major() -> int:
    """Nomor major versi MCP SDK (1 atau 2). Raise bila tak terbaca."""
    raw = mcp_version().strip()
    if not raw:
        raise McpCompatError("versi 'mcp' tidak terbaca")
    head = raw.split(".")[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        raise McpCompatError(f"versi 'mcp' tidak valid: {raw!r}")
    return int(digits)


def is_v2() -> bool:
    return mcp_major() >= 2


# --------------------------------------------------------------------------
# Transport (client)
# --------------------------------------------------------------------------
def _transport_module():
    import importlib
    return importlib.import_module("mcp.client.streamable_http")


def _pick(module: Any, *names: str) -> Callable:
    for n in names:
        fn = getattr(module, n, None)
        if callable(fn):
            return fn
    raise McpCompatError(f"tidak ada salah satu dari {names} di {module!r}")


def _streams_pair(raw: Any) -> tuple[Any, Any]:
    """Ambil (read, write) dari hasil transport 2-tuple (2.x) atau 3-tuple (1.x)."""
    seq = tuple(raw)
    if len(seq) < 2:
        raise McpCompatError(f"transport mengembalikan {len(seq)} nilai; minimal 2")
    return seq[0], seq[1]


@contextlib.asynccontextmanager
async def _open_v1(module: Any, url: str, *, headers: dict | None = None,
                   timeout: float | None = None,
                   sse_read_timeout: float | None = None) -> AsyncIterator[tuple]:
    fn = _pick(module, "streamablehttp_client", "streamable_http_client")
    kwargs: dict[str, Any] = {}
    if headers:
        kwargs["headers"] = dict(headers)
    if timeout is not None:
        kwargs["timeout"] = timeout
    if sse_read_timeout is not None:
        kwargs["sse_read_timeout"] = sse_read_timeout
    async with fn(url, **kwargs) as raw:
        yield _streams_pair(raw)


@contextlib.asynccontextmanager
async def _open_v2(module: Any, url: str, *, headers: dict | None = None,
                   timeout: float | None = None,
                   sse_read_timeout: float | None = None,
                   http_client_factory: Callable[[dict], Any] | None = None
                   ) -> AsyncIterator[tuple]:
    """2.x: parameter koneksi dipasang pada httpx2.AsyncClient eksplisit."""
    fn = _pick(module, "streamable_http_client", "streamablehttp_client")
    client = None
    if http_client_factory is not None:
        client = http_client_factory(dict(headers or {}))
    else:
        try:
            import httpx2  # type: ignore
        except ImportError as exc:  # pragma: no cover - hanya di lingkungan 2.x
            raise McpCompatError("MCP 2.x butuh paket 'httpx2'") from exc
        kw: dict[str, Any] = {}
        if headers:
            kw["headers"] = dict(headers)
        if timeout is not None:
            kw["timeout"] = timeout
        client = httpx2.AsyncClient(**kw)
    try:
        async with fn(url, http_client=client) as raw:
            yield _streams_pair(raw)
    finally:
        if client is not None:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()


def open_streamable_http(url: str, *, headers: dict | None = None,
                         timeout: float | None = None,
                         sse_read_timeout: float | None = None,
                         module: Any | None = None,
                         major: int | None = None,
                         http_client_factory: Callable[[dict], Any] | None = None):
    """Context manager async -> ``(read, write)`` untuk Streamable HTTP.

    Bekerja di 1.x (3-tuple) maupun 2.x (2-tuple + httpx2). ``module``/``major``
    bisa diinjeksi untuk test.
    """
    mod = module if module is not None else _transport_module()
    ver = major if major is not None else mcp_major()
    if ver >= 2:
        return _open_v2(mod, url, headers=headers, timeout=timeout,
                        sse_read_timeout=sse_read_timeout,
                        http_client_factory=http_client_factory)
    return _open_v1(mod, url, headers=headers, timeout=timeout,
                    sse_read_timeout=sse_read_timeout)


# --------------------------------------------------------------------------
# Model helpers (camelCase 1.x vs snake_case 2.x)
# --------------------------------------------------------------------------
def _as_mapping(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump(by_alias=False))
        except TypeError:
            return dict(dump())
    return dict(getattr(obj, "__dict__", {}) or {})


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def field(obj: Any, *names: str, default: Any = None) -> Any:
    """Ambil field pertama yang ADA — mendukung camelCase (1.x) & snake_case (2.x).

    Menerima objek Pydantic maupun dict. Dipakai di call-site agar tidak ada
    `AttributeError: 'InitializeResult' object has no attribute 'serverInfo'`
    setelah upgrade ke SDK 2.x.
    """
    if isinstance(obj, dict):
        return _first(obj, *names, default=default)
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return default


def tool_input_schema(tool: Any) -> dict:
    """JSON Schema input tool, apa pun versi SDK-nya."""
    d = _as_mapping(tool)
    schema = _first(d, "input_schema", "inputSchema", default={})
    return schema if isinstance(schema, dict) else {}


def tool_name(tool: Any) -> str:
    return str(_first(_as_mapping(tool), "name", default="") or "")


def tool_is_error(result: Any) -> bool:
    """True bila hasil ``tools/call`` menandai error."""
    d = _as_mapping(result)
    return bool(_first(d, "is_error", "isError", default=False))


def tool_next_cursor(page: Any) -> str | None:
    d = _as_mapping(page)
    v = _first(d, "next_cursor", "nextCursor")
    return str(v) if v else None


def tool_structured_content(result: Any) -> Any:
    d = _as_mapping(result)
    return _first(d, "structured_content", "structuredContent")


def normalize_tool(tool: Any) -> dict:
    """Bentuk tool yang seragam lintas versi (kunci selalu snake_case)."""
    d = _as_mapping(tool)
    return {
        "name": tool_name(tool),
        "description": str(_first(d, "description", default="") or ""),
        "input_schema": tool_input_schema(tool),
        "annotations": _first(d, "annotations"),
    }


def dump_wire(obj: Any) -> Any:
    """``model_dump(by_alias=True)`` -> kunci camelCase di KEDUA versi SDK.

    1.x memakai nama field camelCase langsung; 2.x memakai snake_case + alias
    camelCase. ``by_alias=True`` menyatukan keduanya, sehingga bentuk yang
    dikirim ke klien tidak berubah saat SDK di-upgrade.
    """
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump(by_alias=True))
        except TypeError:
            return dict(dump())
    if isinstance(obj, dict):
        return dict(obj)
    return dict(getattr(obj, "__dict__", {}) or {})


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------
def make_server(name: str, *, instructions: str | None = None,
                version: str = "", **kwargs: Any) -> Any:
    """Bangun server MCP lintas versi (FastMCP 1.x / MCPServer 2.x).

    Kwarg khusus FastMCP (mis. ``stateless_http``) otomatis DIBUANG pada 2.x —
    padanan 2.x adalah ``auth``/``token_verifier`` pada level transport.
    """
    if is_v2():
        from mcp.server.mcpserver import MCPServer
        allowed = {k: v for k, v in kwargs.items() if k not in _V1_ONLY_SERVER_KWARGS}
        if version:
            allowed["version"] = version
        return MCPServer(name, instructions=instructions, **allowed)
    from mcp.server.fastmcp import FastMCP
    return FastMCP(name, instructions=instructions, **kwargs)


def server_class_name() -> str:
    """Nama kelas server yang dipakai versi terpasang."""
    return "MCPServer" if is_v2() else "FastMCP"


def tool_error_class() -> type:
    """Kelas ``ToolError`` lintas versi (1.x ``fastmcp`` / 2.x ``mcpserver``)."""
    if is_v2():
        from mcp.server.mcpserver.exceptions import ToolError
    else:
        from mcp.server.fastmcp.exceptions import ToolError
    return ToolError


def server_error_class() -> type:
    """Kelas error server lintas versi (``FastMCPError``/``MCPServerError``)."""
    if is_v2():
        from mcp.server.mcpserver.exceptions import MCPServerError
        return MCPServerError
    try:
        from mcp.server.fastmcp.exceptions import FastMCPError
        return FastMCPError
    except ImportError:  # 1.x lama tanpa FastMCPError
        from mcp.server.fastmcp.exceptions import ToolError
        return ToolError


def protocol_versions() -> dict:
    """Versi protokol MCP yang dikenal SDK terpasang.

    Dipakai ``mcp_server.describe()`` supaya ``/mcp/katalir/info`` tidak lagi
    mengiklankan versi basi secara hard-code: SDK 2.3.0 menetapkan
    ``LATEST_PROTOCOL_VERSION = 2026-07-28``, sedangkan nilai lama di kode
    masih ``2025-06-18``.
    """
    try:
        from mcp.types import (DEFAULT_NEGOTIATED_VERSION,
                               LATEST_PROTOCOL_VERSION)
        return {"latest": str(LATEST_PROTOCOL_VERSION),
                "default": str(DEFAULT_NEGOTIATED_VERSION)}
    except Exception:  # noqa: BLE001 - SDK tak terduga
        return {"latest": "2025-06-18", "default": "2025-03-26"}


def expose_tool_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Pulihkan pesan error tool yang HILANG di SDK 2.x.

    MASALAH (terukur, bukan dugaan)
    -------------------------------
    Pada 1.x ``FastMCP`` menangkap exception apa pun dari badan tool dan
    mengembalikannya sebagai ``ToolError`` **dengan pesan asli utuh** —
    sehingga klien/agen bisa membaca mis. ``"API key MCP wajib..."`` lalu
    memperbaiki sendiri.

    Pada 2.x ``MCPServer`` membungkus exception non-``ToolError`` menjadi
    ``UnexpectedToolError("Error executing tool <nama>")``: **pesan asli
    dibuang**. Terbukti dari probe langsung:

        RAISE: UnexpectedToolError -> Error executing tool execute_code

    Akibatnya setiap error yang SENGAJA dilempar tool (401 auth, 404
    kepemilikan, validasi argumen) menjadi tidak bisa ditindaklanjuti klien —
    regresi perilaku nyata bagi klien yang pindah 1.x -> 2.x.

    SOLUSI
    ------
    Bungkus badan tool: exception yang BUKAN ``ToolError`` diubah menjadi
    ``ToolError(str(exc))``. 2.x mempertahankan pesan ``ToolError`` (hanya
    menambah prefiks ``"Error executing tool <nama>: "``), jadi perilaku
    kembali setara 1.x. ``ToolError`` yang sudah ada diteruskan apa adanya
    (tidak dibungkus dua kali).

    Di 1.x helper ini **no-op** (FastMCP sudah melakukannya), sehingga
    pemakaiannya aman di kedua versi dan tidak mengubah perilaku lama.

    Pemakaian::

        @mcp.tool()
        @mcp_compat.expose_tool_errors
        def tool_saya(...): ...
    """
    if not is_v2():
        return fn
    TE = tool_error_class()

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except TE:
            raise
        except Exception as exc:  # noqa: BLE001 - sengaja: pulihkan perilaku 1.x
            raise TE(str(exc)) from exc

    return wrapper


def streamable_http_app(server: Any) -> Any:
    """ASGI app Streamable HTTP dari server (kedua versi punya metode ini)."""
    fn = getattr(server, "streamable_http_app", None)
    if not callable(fn):
        raise McpCompatError("server tidak menyediakan streamable_http_app()")
    return fn()


def build_streamable_http_app(
    server: Any,
    *,
    path: str | None = None,
    stateless: bool | None = None,
    transport_security: Any | None = None,
    json_response: bool | None = None,
    host: str | None = None,
    **extra: Any,
) -> Any:
    """Bangun ASGI app Streamable HTTP dengan setting transport yang BENAR.

    1.x: ``stateless_http``/``streamable_http_path``/``transport_security``
    hidup di konstruktor FastMCP -> app dibuat tanpa argumen.
    2.x: setting itu DIPINDAH ke ``streamable_http_app(...)``; kalau tetap
    dikirim ke konstruktor MCPServer -> ``TypeError`` saat start.
    """
    fn = getattr(server, "streamable_http_app", None)
    if not callable(fn):
        raise McpCompatError("server tidak menyediakan streamable_http_app()")
    if not is_v2():
        return fn()
    kwargs: dict[str, Any] = {}
    if path is not None:
        kwargs["streamable_http_path"] = path
    if stateless is not None:
        kwargs["stateless_http"] = stateless
    if transport_security is not None:
        kwargs["transport_security"] = transport_security
    if json_response is not None:
        kwargs["json_response"] = json_response
    if host is not None:
        kwargs["host"] = host
    kwargs.update(extra)
    return fn(**kwargs)


def dropped_server_kwargs(kwargs: Iterable[str]) -> list[str]:
    """Kwarg yang akan dibuang bila berjalan di 2.x (untuk log peringatan)."""
    if not is_v2():
        return []
    return [k for k in kwargs if k in _V1_ONLY_SERVER_KWARGS]


__all__ = [
    "McpCompatError",
    "build_streamable_http_app",
    "dropped_server_kwargs",
    "dump_wire",
    "field",
    "is_v2",
    "make_server",
    "mcp_major",
    "mcp_version",
    "normalize_tool",
    "open_streamable_http",
    "server_class_name",
    "server_error_class",
    "streamable_http_app",
    "tool_error_class",
    "tool_input_schema",
    "tool_is_error",
    "tool_name",
    "tool_next_cursor",
    "tool_structured_content",
]
