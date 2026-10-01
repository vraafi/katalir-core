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
        import httpx
        payload={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"health","version":"1"}}}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response=await client.post(self.mcp_url,json=payload,headers={**_headers(),"Content-Type":"application/json","Accept":"application/json, text/event-stream"})
                return response.status_code in (200, 202)
        except Exception:
            return False
