"""HTTP adapter for an externally deployed agentgateway."""
from __future__ import annotations
import os
import httpx
class GatewayClient:
    def __init__(self, base_url=None, api_key=None, timeout=10.0):
        self.base_url=(base_url or os.getenv('AGENTGATEWAY_URL') or '').rstrip('/')
        self.api_key=api_key or os.getenv('AGENTGATEWAY_API_KEY') or ''
        self.timeout=timeout
    def _headers(self): return {'Authorization':f'Bearer {self.api_key}'} if self.api_key else {}
    def _get(self,path):
        if not self.base_url: raise RuntimeError('AGENTGATEWAY_URL belum dikonfigurasi')
        r=httpx.get(self.base_url+path,headers=self._headers(),timeout=self.timeout,follow_redirects=False); r.raise_for_status(); return r.json()
    def health(self): return self._get('/health')
    def list_servers(self): return self._get('/servers')
    def list_tools(self,server_id: str):
        from urllib.parse import quote
        return self._get('/servers/' + quote(server_id, safe='') + '/tools')
    def call_tool(self,server_id,tool,args):
        if not self.base_url: raise RuntimeError('AGENTGATEWAY_URL belum dikonfigurasi')
        r=httpx.post(self.base_url+'/call',headers={**self._headers(),'Content-Type':'application/json'},json={'server_id':server_id,'tool':tool,'arguments':args},timeout=self.timeout,follow_redirects=False); r.raise_for_status(); return r.json()
