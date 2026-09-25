
from __future__ import annotations
import json, threading
from pathlib import Path
from typing import Any
import httpx
SOURCE_URL='https://raw.githubusercontent.com/ToolSDK-AI/toolsdk-mcp-registry/main/indexes/packages-list.json'
CACHE_PATH=Path(__file__).with_name('mcp_registry_cache.json'); COMPOSIO_PATH=Path(__file__).with_name('composio_toolkits.json'); _CACHE={}; _LOCK=threading.RLock(); _COMPOSIO_LOADED=False
_ALLOWED_TRANSPORTS={'stdio','http','sse'}


def validate_executable_manifest(item: dict[str, Any]) -> dict[str, Any]:
    """Validate a manifest before any install/runtime claim.

    This intentionally does not execute packages. It returns a signed-by-
    content (not cryptographic) record suitable for review and hashing.
    """
    config=item.get('install_config') if isinstance(item.get('install_config'),dict) else {}
    transport=str(config.get('transport') or '').lower()
    package=str(config.get('package') or '').strip()
    errors=[]
    if transport not in _ALLOWED_TRANSPORTS: errors.append('transport_not_allowed')
    if not package: errors.append('package_missing')
    if not item.get('id'): errors.append('id_missing')
    return {'id':item.get('id'),'status':'valid' if not errors else 'rejected','transport':transport,'package':package,'errors':errors}

def _normalize(i,item):
 tools=item.get('tools') if isinstance(item.get('tools'),dict) else {}
 return {'id':i,'name':i.rsplit('/',1)[-1],'category':str(item.get('category') or 'other'),'description':str(item.get('description') or f'MCP server {i}'),'repo_url':str(item.get('repo') or item.get('repository') or ''),'install_config':{'transport':'metadata-only','package':i},'tenant_scope':'user','validated':bool(item.get('validated')),'tools':[{'name':str(n),'description':str((v or {}).get('description') or '')} for n,v in tools.items()]}
def load_cached():
 global _COMPOSIO_LOADED
 with _LOCK:
  if not _CACHE and CACHE_PATH.exists():
   try:_CACHE.update({str(k):_normalize(str(k),v or {}) for k,v in json.loads(CACHE_PATH.read_text(encoding='utf-8')).items() if isinstance(v,dict)})
   except (OSError,ValueError,TypeError):_CACHE.clear()
  if not _COMPOSIO_LOADED and COMPOSIO_PATH.exists():
   try:
    rows=json.loads(COMPOSIO_PATH.read_text(encoding='utf-8'))
    if isinstance(rows,dict): _CACHE.update({str(k):v for k,v in rows.items() if isinstance(v,dict)})
    _COMPOSIO_LOADED=True
   except (OSError,ValueError,TypeError): pass
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

def executable_servers():
    """Return only registry entries with an explicit executable transport.

    ToolSDK metadata is currently metadata-only; do not treat it as runnable.
    """
    return [x for x in load_cached().values() if isinstance(x, dict) and (x.get('runtime_verified') is True or x.get('install_config', {}).get('transport') in {'stdio','http','sse'})]

def _normalize_official(entry: dict[str, Any]) -> dict[str, Any] | None:
    server=(entry or {}).get('server') if isinstance(entry,dict) else None
    if not isinstance(server,dict) or not server.get('name'): return None
    remotes=server.get('remotes') if isinstance(server.get('remotes'),list) else []
    remote=next((r for r in remotes if isinstance(r,dict) and r.get('url')),None)
    return {'id':str(server['name']),'name':str(server.get('title') or server['name']),'description':str(server.get('description') or ''),'repo_url':str((server.get('repository') or {}).get('url') or ''),'install_config':{'transport':str((remote or {}).get('type') or 'metadata-only'),'package':str((remote or {}).get('url') or ''),'install_method':'remote'},'tenant_scope':'user','validated':True,'tools':[],'source':'official-mcp-registry'}

def sync_official_registry(*,limit=100,timeout=30) -> list[dict[str,Any]]:
    r=httpx.get('https://registry.modelcontextprotocol.io/v0/servers',params={'limit':min(int(limit),100),'offset':'0'},timeout=timeout,follow_redirects=True);r.raise_for_status()
    out=[]
    for e in r.json().get('servers',[]):
        x=_normalize_official(e)
        if x: out.append(x)
    return out

def executable_candidates():
    """Filter entries with enough runtime evidence for a batch test."""
    out = []
    for key, item in load_cached().items():
        cfg = item.get('install_config') or {}
        method = cfg.get('install_method') or cfg.get('method')
        if method in {'npm', 'python', 'docker'} and cfg.get('package') and item.get('tools') and not cfg.get('requires_credentials'):
            out.append({'id': key, 'install_method': method, 'package': cfg['package']})
    return out

def coverage():
    items = [x for x in load_cached().values() if isinstance(x, dict) and x.get('id')]
    composio = [x for x in items if x.get('source') == 'composio']
    official = [x for x in items if x.get('source') == 'official-mcp-registry']
    return {'total': len(items), 'executable': len(executable_servers()), 'metadata_only': len(items) - len(executable_servers()), 'composio_toolkits': len(composio), 'official_remote': len(official)}

def recommend_servers(query: str, limit: int = 5):
    """Return catalog matches for the AI integration picker; metadata only."""
    q=(query or '').strip()
    result=list_servers(page=1,limit=min(max(int(limit),1),20),search=q)
    return result['items']
