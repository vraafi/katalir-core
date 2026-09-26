"""F3.4 — remote MCP import: registry entry → gateway-ready connection.

The other three importers take a *description* of an API. This one takes a live
MCP server and actually talks the protocol: `initialize`, then `tools/list`, over
streamable HTTP with the session header the spec requires.

Two things it will not do, both deliberate:

* it will not call a tool. `tools/list` succeeding is `tools_listed`; the moment
  a real `tools/call` returns is `call_verified`, and conflating them is the
  exact error the 4-tier badge exists to prevent. Calling arbitrary
  third-party tools during an *import* would also mean importing an entry could
  mutate somebody's data as a side effect.
* it will not reach a non-public host. The target comes from a registry file,
  which is data — and data that names a URL is the SSRF path.

Streamable HTTP is used rather than the older SSE transport because that is what
current servers implement; the session id returned by `initialize` is echoed on
every follow-up request, which is required and is the part most hand-rolled
clients get wrong.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .ssrf import require_public_url, SsrfError

PROTOCOL_VERSION = "2025-06-18"
TRANSPORTS = ("http", "streamable-http", "sse")
DEFAULT_TIMEOUT = 30


def _resolve_redirect(client: httpx.Client, url: str, max_hops: int = 3) -> tuple[str, str]:
    """Follow redirects by hand, re-running the guard on every hop.

    Simply setting ``follow_redirects=True`` would be a hole: the public URL
    passes the guard, then answers 302 to ``http://169.254.169.254/``, and the
    second request is never checked. Re-validating each hop closes that, and it
    is why a 301 is reported as a redirect rather than as a bare http_301.
    """
    current = url
    for _ in range(max_hops):
        try:
            r = client.get(current, headers={"Accept": "application/json, text/event-stream"})
        except Exception as exc:  # noqa: BLE001
            return current, f"redirect_probe_failed:{type(exc).__name__}"
        if r.status_code not in (301, 302, 307, 308):
            return current, ""
        location = r.headers.get("location") or ""
        if not location:
            return current, "redirect_without_location"
        nxt = str(httpx.URL(current).join(location))
        try:
            require_public_url(nxt)
        except SsrfError as exc:
            # The first hop was public; the second is not. This is the whole point.
            return nxt, f"redirect_blocked:{exc}"
        current = nxt
    return current, "too_many_redirects"


def _rpc(client: httpx.Client, url: str, method: str, params: dict[str, Any] | None, session: str | None) -> tuple[dict, str | None]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session:
        headers["Mcp-Session-Id"] = session
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    r = client.post(url, json=payload, headers=headers)
    session = r.headers.get("Mcp-Session-Id") or session
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200:
        return {"error": f"http_{r.status_code}", "body": r.text[:300]}, session
    if "text/event-stream" in ctype:
        # SSE framing: read data: lines until the first complete JSON payload.
        for line in r.text.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    try:
                        return json.loads(chunk), session
                    except json.JSONDecodeError:
                        continue
        return {"error": "no_json_in_sse", "body": r.text[:300]}, session
    try:
        return r.json(), session
    except json.JSONDecodeError:
        return {"error": "invalid_json", "body": r.text[:300]}, session


def import_remote(entry: dict[str, Any], *, token: str = "", timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Probe one remote MCP server. Returns a result, never raises on failure."""
    entry = entry if isinstance(entry, dict) else {}
    # The official registry puts the endpoint in install_config.package, while a
    # hand-written entry usually uses `url`. Reading only one of them would make
    # this silently probe nothing for half of all real inputs.
    config = entry.get("install_config") if isinstance(entry.get("install_config"), dict) else {}
    raw_url = entry.get("url") or config.get("package") or config.get("url") or ""
    url = str(raw_url).strip()
    name = str(entry.get("id") or entry.get("name") or "unknown")
    transport = str(entry.get("transport") or config.get("transport") or "http").lower()

    out: dict[str, Any] = {
        "id": name,
        "protocol": "mcp",
        "transport": transport,
        "url": url,
        "tools": [],
        "tools_count": 0,
        "ok": False,
        "error": "",
        "requires_auth": bool(token is not None and token != "") or bool(entry.get("needs_credential")),
        # Start pessimistic: a probe that fails proves nothing about the server.
        "verification": {"discovered": True, "tools_listed": False, "call_verified": False},
    }
    if transport not in TRANSPORTS:
        out["error"] = f"transport_not_supported:{transport}"
        return out
    if not url:
        out["error"] = "url_missing"
        return out
    try:
        require_public_url(url)
    except SsrfError as exc:
        out["error"] = f"ssrf_blocked:{exc}"
        return out

    headers = {"User-Agent": "katalir-mcp-import", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            final_url, redirect_note = _resolve_redirect(client, url)
            if redirect_note:
                out["error"] = redirect_note
                out["url"] = final_url
                return out
            if final_url != url:
                # Rebind, or the JSON-RPC calls below would re-request the
                # original URL and see the same 301 again.
                url = final_url
                out["url"] = final_url
                out["redirected"] = True
            init, session = _rpc(
                client, url, "initialize",
                {"protocolVersion": PROTOCOL_VERSION,
                 "capabilities": {},
                 "clientInfo": {"name": "katalir-importer", "version": "1.0"}},
                None,
            )
            if "error" in init:
                out["error"] = f"initialize_failed:{init.get('error')}"
                return out
            out["server_info"] = (init.get("result") or {}).get("serverInfo") or {}
            out["protocol_version"] = (init.get("result") or {}).get("protocolVersion") or ""
            # The spec requires this notification after initialize; servers that
            # reject the call without it are a real failure mode we should not hide.
            _rpc(client, url, "notifications/initialized", {}, session)
            listed, session = _rpc(client, url, "tools/list", {}, session)
            if "error" in listed:
                out["error"] = f"tools_list_failed:{listed.get('error')}"
                return out
            tools = ((listed.get("result") or {}).get("tools") or [])
            out["tools"] = [
                {"name": str(t.get("name") or ""), "description": str(t.get("description") or "")[:400]}
                for t in tools if isinstance(t, dict) and t.get("name")
            ]
            out["tools_count"] = len(out["tools"])
            out["ok"] = True
            # Listed, not called. Nothing here executed a tool.
            out["verification"] = {"discovered": True, "tools_listed": True, "call_verified": False}
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"transport:{type(exc).__name__}"
        return out
    return out


__all__ = ["import_remote", "PROTOCOL_VERSION", "TRANSPORTS"]