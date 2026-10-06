"""Cache katalog tool MCP gateway (memory, TTL, stale-fallback, refresh latar).

KENAPA MODUL INI ADA (terukur 2026-10-06)
1. `GET /mcp/gateway/servers` butuh **8-13 detik** karena gateway meneruskan
   `initialize` ke semua target stdio (npx/uvx) yang cold-start. Pemilih tool di
   UI memanggilnya, jadi user menunggu belasan detik.
2. Lebih buruk: bila gateway sedang tidak bisa dihubungi, endpoint membalas
   **HTTP 503** — padahal daftar tool nyaris tidak pernah berubah. Terbukti:
   saat guard VPS me-restart agentgateway (01:26:59), satu panggilan produksi
   langsung 503.
3. Setiap panggilan ke gateway membuat SESI baru, dan setiap sesi men-spawn satu
   set target stdio. Mengurangi panggilan = mengurangi churn proses di VPS.

Jadi cache ini bukan sekadar optimasi: ia menghilangkan kelas kegagalan
503 untuk data yang sebenarnya stabil.

KONTRAK
    get_tools(force_refresh=False, allow_stale=True) -> dict
        {"tools": [...], "source": "cache"|"gateway"|"stale"|"none",
         "age_s": float, "error": str}

`source="stale"` berarti gateway GAGAL tetapi cache lama masih disajikan —
pemanggil sebaiknya tetap membalas 200 dan menandai datanya berumur.
`source="none"` berarti tidak ada apa pun untuk disajikan (baru 503).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

TTL_S = float(os.getenv("MCP_TOOLS_CACHE_TTL", "1800"))       # 30 menit
REFRESH_TIMEOUT_S = float(os.getenv("MCP_TOOLS_REFRESH_TIMEOUT", "45"))

_lock = threading.Lock()
_state: dict[str, Any] = {"at": 0.0, "tools": [], "refreshing": False}


def _fetch_from_gateway() -> list[dict]:
    """Ambil katalog langsung dari gateway. Melempar bila gagal."""
    from mcp_gateway.client import GatewayClient
    tools = GatewayClient().list_tools_sync()
    return [t for t in (tools or []) if isinstance(t, dict) and t.get("name")]


def store(tools: list[dict]) -> None:
    with _lock:
        _state["tools"] = list(tools)
        _state["at"] = time.time()


def cached_tools() -> list[dict]:
    with _lock:
        return list(_state["tools"])


def cache_age_s() -> float:
    with _lock:
        at = float(_state["at"])
    return float("inf") if at <= 0 else max(0.0, time.time() - at)


def is_fresh() -> bool:
    return cache_age_s() < TTL_S


def invalidate() -> None:
    with _lock:
        _state["at"] = 0.0
        _state["tools"] = []


def refresh_async() -> bool:
    """Picu refresh di thread latar. True bila thread baru dijalankan.

    Non-blocking: dipakai jalur system prompt yang dibangun pada SETIAP request.
    """
    with _lock:
        if _state["refreshing"]:
            return False
        _state["refreshing"] = True

    def _run() -> None:
        try:
            store(_fetch_from_gateway())
        except Exception:  # noqa: BLE001 - gateway mati tidak boleh mematikan chat
            with _lock:
                _state["at"] = time.time()   # backoff: jangan hajar tiap request
        finally:
            with _lock:
                _state["refreshing"] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def get_tools(*, force_refresh: bool = False, allow_stale: bool = True) -> dict:
    """Katalog dari cache bila segar, selain itu ambil dari gateway.

    Bila gateway gagal DAN ada cache lama, kembalikan cache lama dengan
    `source="stale"` (jangan 503 selama masih ada data untuk disajikan).
    """
    age = cache_age_s()
    if not force_refresh and age < TTL_S and cached_tools():
        return {"tools": cached_tools(), "source": "cache", "age_s": age, "error": ""}

    try:
        tools = _fetch_from_gateway()
        if tools:
            store(tools)
            return {"tools": tools, "source": "gateway", "age_s": 0.0, "error": ""}
        err = "gateway membalas daftar tool kosong"
    except Exception as exc:  # noqa: BLE001
        err = f"[{type(exc).__name__}] {exc}"

    stale = cached_tools()
    if allow_stale and stale:
        return {"tools": stale, "source": "stale", "age_s": cache_age_s(), "error": err}
    return {"tools": [], "source": "none", "age_s": age, "error": err}
