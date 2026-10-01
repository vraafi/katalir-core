"""Verify current exposure of the public gateway endpoint (no credentials)."""
from __future__ import annotations

import httpx

URL = "https://gateway.katalir.de5.net/mcp"
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "exposure-probe", "version": "1"}}}

try:
    r = httpx.post(URL, headers=H, json=INIT, timeout=20)
    print(f"NAKED initialize -> HTTP {r.status_code}")
    if r.status_code == 200:
        sid = r.headers.get("mcp-session-id")
        h2 = dict(H)
        if sid:
            h2["mcp-session-id"] = sid
        httpx.post(URL, headers=h2, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=20)
        r2 = httpx.post(URL, headers=h2, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, timeout=20)
        print(f"NAKED tools/list -> HTTP {r2.status_code} tool_name_count={r2.text.count(chr(34) + 'name' + chr(34))}")
except Exception as exc:  # noqa: BLE001
    print(f"ERR {type(exc).__name__}: {str(exc)[:160]}")
