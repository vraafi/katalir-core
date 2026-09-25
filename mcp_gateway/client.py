"""MCP Streamable HTTP client for agentgateway v1.5.0."""
from __future__ import annotations
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
class GatewayClient:
    def __init__(self, url: str | None = None):
        base=(url or os.getenv('AGENTGATEWAY_URL') or '').rstrip('/')
        if not base: raise RuntimeError('AGENTGATEWAY_URL belum dikonfigurasi')
        self.mcp_url=base+'/mcp'
    async def _session(self):
        return streamablehttp_client(self.mcp_url)
    async def list_tools(self):
        async with streamablehttp_client(self.mcp_url) as (r,w,_):
            async with ClientSession(r,w) as s:
                await s.initialize(); result=await s.list_tools(); return [x.model_dump() for x in result.tools]
    async def call_tool(self, name, args):
        async with streamablehttp_client(self.mcp_url) as (r,w,_):
            async with ClientSession(r,w) as s:
                await s.initialize(); result=await s.call_tool(name,args); return result.model_dump()
    def list_tools_sync(self): return asyncio.run(self.list_tools())
    def call_tool_sync(self,name,args): return asyncio.run(self.call_tool(name,args))
    async def health(self):
        try:
            await self.list_tools()
            return True
        except Exception:
            return False
