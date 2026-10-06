"""MCP Streamable HTTP client for agentgateway v1.5.0.

Auth: the gateway sits behind Cloudflare Access / a bearer gate, so every
request carries `Authorization: Bearer $AGENTGATEWAY_TOKEN` (and optional
`CF-Access-Client-Id` / `CF-Access-Client-Secret`). The token is only ever sent
as a header — never embedded in the URL, so it cannot leak into logs.
"""
from __future__ import annotations
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TOKEN_ENV = "AGENTGATEWAY_TOKEN"

# `initialize` is fanned out by the gateway to every registered stdio target,
# and those are npx/uvx processes that cold-start. Measured against the live
# gateway: 13.2s for a cold `initialize`, and >5s even when warm. The old
# hard-coded 5s budget therefore reported a perfectly healthy gateway as
# "unreachable" (regression observed on production /mcp/gateway/health while
# list_tools/call_tool kept working). Overridable for tests and tuning.
HEALTH_TIMEOUT_ENV = "MCP_GATEWAY_HEALTH_TIMEOUT"
DEFAULT_HEALTH_TIMEOUT = 30.0


def health_timeout() -> float:
    """Timeout (detik) untuk probe health gateway; default 30s."""
    raw = (os.getenv(HEALTH_TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_HEALTH_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_HEALTH_TIMEOUT
    return value if value > 0 else DEFAULT_HEALTH_TIMEOUT

def _headers() -> dict[str, str]:
    """Auth headers for the agentgateway native apiKey policy.

    The gateway enforces `mcp.policies.apiKey` with mode `strict`, so an
    unauthenticated request gets 401. The key is accepted either as
    `Authorization: Bearer <key>` or `x-api-key: <key>`; we send the bearer form
    plus the x-api-key header for compatibility. Values are sent as headers only,
    never embedded in the URL, so they cannot leak into logs.
    """
    h: dict[str, str] = {}
    key = (os.getenv(TOKEN_ENV) or os.getenv("GATEWAY_API_KEY") or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
        h["x-api-key"] = key
    for env, header in (
        ("CF_ACCESS_CLIENT_ID", "CF-Access-Client-Id"),
        ("CF_ACCESS_CLIENT_SECRET", "CF-Access-Client-Secret"),
    ):
        val = (os.getenv(env) or "").strip()
        if val:
            h[header] = val
    return h

def auth_configured() -> bool:
    return bool((os.getenv(TOKEN_ENV) or os.getenv("GATEWAY_API_KEY") or "").strip()
                or (os.getenv("CF_ACCESS_CLIENT_SECRET") or "").strip())

class GatewayClient:
    def __init__(self, url: str | None = None):
        base=(url or os.getenv('AGENTGATEWAY_URL') or '').rstrip('/')
        if not base: raise RuntimeError('AGENTGATEWAY_URL belum dikonfigurasi')
        # Fail closed: a credentialed gateway must never be probed anonymously,
        # otherwise we would silently downgrade to an open request.
        if not auth_configured() and os.getenv('MCP_GATEWAY_ALLOW_ANON', '').strip() not in ('1', 'true', 'yes'):
            raise RuntimeError(
                f'{TOKEN_ENV} (atau CF_ACCESS_CLIENT_ID/SECRET) wajib; '
                'set MCP_GATEWAY_ALLOW_ANON=1 hanya untuk debugging lokal'
            )
        self.mcp_url=base+'/mcp'
    def _session(self):
        return streamablehttp_client(self.mcp_url, headers=_headers())
    async def list_tools(self):
        async with streamablehttp_client(self.mcp_url, headers=_headers()) as (r,w,_):
            async with ClientSession(r,w) as s:
                await s.initialize(); result=await s.list_tools(); return [x.model_dump() for x in result.tools]
    async def call_tool(self, name, args):
        async with streamablehttp_client(self.mcp_url, headers=_headers()) as (r,w,_):
            async with ClientSession(r,w) as s:
                await s.initialize(); result=await s.call_tool(name,args); return result.model_dump()
    def list_tools_sync(self): return asyncio.run(self.list_tools())
    def call_tool_sync(self,name,args): return asyncio.run(self.call_tool(name,args))
    async def health(self):
        """True bila gateway menjawab `initialize` (200/202).

        Timeout sengaja longgar (lihat DEFAULT_HEALTH_TIMEOUT): gateway
        meneruskan `initialize` ke SEMUA target stdio (npx/uvx) yang cold-start,
        dan itu terukur 13,2 detik di produksi. Dengan budget lama 5 detik,
        gateway yang sehat dilaporkan "unreachable" — regresi yang tertangkap
        di /mcp/gateway/health sementara list_tools/call_tool tetap normal.
        Nilai bisa diatur via MCP_GATEWAY_HEALTH_TIMEOUT.

        SESI WAJIB DITUTUP (perbaikan 2026-10-06). Terukur di produksi:
        setiap `GET /mcp/gateway/health` menambah **tepat 13 proses** target
        stdio yang tidak pernah direap, dan ~330 MB memori (3 pemeriksaan:
        mcp_procs 26 -> 65, mem_available 1211 -> 303 MB). Sebabnya: probe ini
        mengirim `initialize` lalu selesai tanpa `DELETE`, sedangkan gateway
        men-spawn satu set target PER SESI dan hanya mereapnya saat sesi
        ditutup. Karena endpoint kesehatan biasanya dipanggil berkala (load
        balancer / uptime monitor), kebocorannya menumpuk tanpa ada pengguna
        yang menyentuh MCP — dan guard VPS lalu me-restart gateway (yang
        menyebabkan 503). Sekarang sesi ditutup eksplisit.
        """
        import httpx
        payload={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"health","version":"1"}}}
        headers={**_headers(),"Content-Type":"application/json","Accept":"application/json, text/event-stream"}
        session_id = None
        ok = False
        try:
            async with httpx.AsyncClient(timeout=health_timeout()) as client:
                response=await client.post(self.mcp_url,json=payload,headers=headers)
                ok = response.status_code in (200, 202)
                hdrs = getattr(response, "headers", None) or {}
                session_id = hdrs.get("mcp-session-id") or hdrs.get("Mcp-Session-Id")
        except Exception:
            return False

        if ok and session_id:
            # Tutup sesi supaya gateway mereap target stdio-nya. Hanya dilakukan
            # bila `initialize` BERHASIL: probe yang gagal (401/503) tidak
            # membuat sesi, jadi DELETE hanya menambah trafik tepat saat gateway
            # sedang bermasalah. Kegagalan di sini TIDAK boleh mengubah hasil
            # probe: status kesehatan sudah ditentukan jawaban `initialize`.
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.request(
                        "DELETE", self.mcp_url,
                        headers={**headers, "Mcp-Session-Id": session_id},
                    )
            except Exception:
                pass
        return ok
