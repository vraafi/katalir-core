
from __future__ import annotations
import json, threading
from pathlib import Path
from typing import Any
import httpx
SOURCE_URL='https://raw.githubusercontent.com/ToolSDK-AI/toolsdk-mcp-registry/main/indexes/packages-list.json'
CACHE_PATH=Path(__file__).with_name('mcp_registry_cache.json'); _CACHE={}; _LOCK=threading.RLock()
def _normalize(i,item):
 tools=item.get('tools') if isinstance(item.get('tools'),dict) else {}
 return {'id':i,'name':i.rsplit('/',1)[-1],'category':str(item.get('category') or 'other'),'description':str(item.get('description') or f'MCP server {i}'),'repo_url':str(item.get('repo') or item.get('repository') or ''),'install_config':{'transport':'metadata-only','package':i},'tenant_scope':'user','validated':bool(item.get('validated')),'tools':[{'name':str(n),'description':str((v or {}).get('description') or '')} for n,v in tools.items()]}
def load_cached():
 with _LOCK:
  if not _CACHE and CACHE_PATH.exists():
   try:_CACHE.update({str(k):_normalize(str(k),v or {}) for k,v in json.loads(CACHE_PATH.read_text(encoding='utf-8')).items() if isinstance(v,dict)})
   except (OSError,ValueError,TypeError):_CACHE.clear()
  return _CACHE
def sync_from_public(*,timeout=30):
 r=httpx.get(SOURCE_URL,timeout=timeout,follow_redirects=True);r.raise_for_status();raw=r.json()
 if not isinstance(raw,dict):raise ValueError('registry must be object')
 with _LOCK:
  _CACHE.clear();_CACHE.update({str(k):_normalize(str(k),v or {}) for k,v in raw.items() if isinstance(v,dict)});tmp=CACHE_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(_CACHE,ensure_ascii=False),encoding='utf-8');tmp.replace(CACHE_PATH)
 return len(_CACHE)
def list_servers(*,page=1,limit=50,search='',category=''):
 if page<1 or not 1<=limit<=100:raise ValueError('invalid pagination')
 items=list(load_cached().values());needle=search.casefold().strip()
 if needle:items=[x for x in items if needle in (x['id']+' '+x['name']+' '+x['description']).casefold()]
 if category:items=[x for x in items if x['category'].casefold()==category.casefold()]
 items.sort(key=lambda x:x['id']);total=len(items);start=(page-1)*limit
 return {'items':items[start:start+limit],'page':page,'limit':limit,'total':total,'source':'toolsdk-mcp-registry'}
def get_server(server_id):
 x=load_cached().get(server_id)
 if not x:raise KeyError(server_id)
 return x
