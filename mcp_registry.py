
from __future__ import annotations
import json, threading
from pathlib import Path
from typing import Any
import httpx
SOURCE_URL='https://raw.githubusercontent.com/ToolSDK-AI/toolsdk-mcp-registry/main/indexes/packages-list.json'
CACHE_PATH=Path(__file__).with_name('mcp_registry_cache.json'); COMPOSIO_PATH=Path(__file__).with_name('composio_toolkits.json'); OPENCONNECTOR_PATH=Path(__file__).with_name('openconnector_actions.json'); GLAMA_PATH=Path(__file__).with_name('glama_servers.json'); GLAMA_CONNECTOR_PATH=Path(__file__).with_name('glama_connectors.json'); OPENAPI_PATH=Path(__file__).with_name('openapi_apis.json'); NANGO_PATH=Path(__file__).with_name('nango_providers.json'); METORIAL_PATH=Path(__file__).with_name('metorial_integrations.json'); _CACHE={}; _LOCK=threading.RLock(); _COMPOSIO_LOADED=False; _OC_LOADED=False; _GLAMA_LOADED=False; _OPENAPI_LOADED=False; _OAUTH_LOADED=False
GLAMA_SOURCES={'glama','glama-connector'}
def _slim_glama(v):
 """Project a Glama record down to what search/UI actually needs.

 The raw file is ~18 MB; keeping the full records in RAM for 20k entries is
 wasteful, so only the fields the marketplace renders are retained. The
 attribution fields are deliberately included: the Glama API Data License
 requires the source link and credit to survive into the UI.
 """
 return {'id':v.get('id'),'name':v.get('name') or v.get('id'),'source':v.get('source') or 'glama','description':str(v.get('description') or '')[:120],'category':v.get('category') or 'mcp','repo_url':v.get('repo_url') or '','source_url':v.get('source_url') or '','attribution_required':True,'tools_count':int(v.get('tools_count') or 0),'tools':[],'no_auth':bool(v.get('no_auth')),'install_config':{'transport':'metadata-only','package':'','install_method':'glama'},'tenant_scope':v.get('tenant_scope') or 'public','validated':bool(v.get('validated',True)),'runtime_verified':bool(v.get('runtime_verified')),'verification':v.get('verification') or {'discovered':True,'tools_listed':False,'call_verified':False}}
def _slim_glama_connector(v):
 d=_slim_glama(v)
 d.update({'endpoint_url':v.get('endpoint_url') or '','auth_type':v.get('auth_type') or '','healthy':bool(v.get('healthy')),'no_auth':bool(v.get('no_auth')),'namespace':v.get('namespace') or '','thumbnail_url':v.get('thumbnail_url') or '','install_config':{'transport':v.get('transport') or 'streamable_http','package':v.get('endpoint_url') or '','install_method':'glama-remote'}})
 return d
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
 global _COMPOSIO_LOADED, _OC_LOADED, _GLAMA_LOADED, _OPENAPI_LOADED, _OAUTH_LOADED
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
  if not _OC_LOADED and OPENCONNECTOR_PATH.exists():
   try:
    rows=json.loads(OPENCONNECTOR_PATH.read_text(encoding='utf-8'))
    if isinstance(rows,dict):
     _CACHE.update({f'openconnector/{k}':v for k,v in rows.items() if isinstance(v,dict)})
    _OC_LOADED=True
   except (OSError,ValueError,TypeError): pass
  if not _GLAMA_LOADED:
   if GLAMA_PATH.exists():
    try:
     rows=json.loads(GLAMA_PATH.read_text(encoding='utf-8'))
     if isinstance(rows,dict):
      _CACHE.update({str(k):_slim_glama(v) for k,v in rows.items() if isinstance(v,dict)})
    except (OSError,ValueError,TypeError): pass
   if GLAMA_CONNECTOR_PATH.exists():
    try:
     rows=json.loads(GLAMA_CONNECTOR_PATH.read_text(encoding='utf-8'))
     if isinstance(rows,dict):
      _CACHE.update({str(k):_slim_glama_connector(v) for k,v in rows.items() if isinstance(v,dict)})
    except (OSError,ValueError,TypeError): pass
   _GLAMA_LOADED=True
  if not _OPENAPI_LOADED:
   if OPENAPI_PATH.exists():
    try:
     rows=json.loads(OPENAPI_PATH.read_text(encoding='utf-8'))
     if isinstance(rows,dict): _CACHE.update({str(k):v for k,v in rows.items() if isinstance(v,dict)})
    except (OSError,ValueError,TypeError): pass
   _OPENAPI_LOADED=True
  if not _OAUTH_LOADED:
   # Nango (OAuth layer) and Metorial (managed MCP). Loaded verbatim like the
   # other sources - they are not tools catalogues, and `kind` says so, so the
   # marketplace can label them instead of counting them as tools.
   for path in (NANGO_PATH, METORIAL_PATH):
    if not path.exists(): continue
    try:
     rows=json.loads(path.read_text(encoding='utf-8'))
     if isinstance(rows,dict): _CACHE.update({str(k):v for k,v in rows.items() if isinstance(v,dict)})
    except (OSError,ValueError,TypeError): pass
   _OAUTH_LOADED=True
  return _CACHE
def sync_from_public(*,timeout=30):
 r=httpx.get(SOURCE_URL,timeout=timeout,follow_redirects=True);r.raise_for_status();raw=r.json()
 if not isinstance(raw,dict):raise ValueError('registry must be object')
 with _LOCK:
  _CACHE.clear();_CACHE.update({str(k):_normalize(str(k),v or {}) for k,v in raw.items() if isinstance(v,dict)});tmp=CACHE_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(_CACHE,ensure_ascii=False),encoding='utf-8');tmp.replace(CACHE_PATH)
 return len(_CACHE)
def openapi_coverage():
 """Counts for the OpenAPI-generated source.

 One registry entry per API, not per tool: a generated tool is not a separate
 integration, and counting 889 rows would be exactly the inflation the dedup
 engine exists to remove.
 """
 items=[x for x in load_cached().values() if isinstance(x,dict) and x.get('source')=='openapi-generated']
 return {'apis':len(items),'tools':sum(int(x.get('tools_count') or 0) for x in items),'tools_callable':sum(int(x.get('tools_callable') or 0) for x in items),'tools_call_verified':sum(int(x.get('tools_call_verified') or 0) for x in items)}

def source_counts():
 """Entry counts per source, for the marketplace tabs."""
 items=[x for x in load_cached().values() if isinstance(x,dict) and x.get('id')]
 out={}
 for x in items:
  s=str(x.get('source') or 'toolsdk')
  out[s]=out.get(s,0)+1
 return dict(sorted(out.items(),key=lambda kv:-kv[1]))

CANONICAL_PATH=Path(__file__).with_name('dedup_canonical.json')
def list_canonical(*,page=1,limit=50,search='',category='',source=''):
 '''Dedup-aware listing: one row per canonical integration, not per source row.

 The two views differ by the duplicate rate (~22%), so a marketplace that shows
 only one either hides how much of the catalogue is duplicated or quietly
 inflates its own headline. Both are served, each labelled with its own total.

 Raises if dedup_canonical.json is missing rather than falling back to the raw
 list, because a fallback would report a "unique" total that is not unique.
 '''
 if not CANONICAL_PATH.exists():raise ValueError('unique view unavailable: run mcp_dedup.py to build dedup_canonical.json')
 if page<1 or not 1<=limit<=100:raise ValueError('invalid pagination')
 rows=json.loads(CANONICAL_PATH.read_text(encoding='utf-8'))
 if not isinstance(rows,list):raise ValueError('dedup_canonical.json is not a list; run mcp_dedup.py')
 needle=search.casefold().strip()
 if needle:rows=[r for r in rows if needle in (str(r.get('id') or '')+' '+str(r.get('name') or '')+' '+str(r.get('description') or '')).casefold()]
 if category:rows=[r for r in rows if str(r.get('category') or '').casefold()==category.casefold()]
 if source:
  wanted={s.strip().casefold() for s in source.split(',') if s.strip()}
  # A canonical entry counts for a source when that source contributed a member,
  # so a duplicate present in both glama and composio shows in both tabs - these
  # per-source counts are membership, not disjoint sets.
  rows=[r for r in rows if wanted&{str(s).casefold() for s in (r.get('sources') or [])}]
 total=len(rows);start=(page-1)*limit;page_rows=rows[start:start+limit]
 for r in page_rows:r['member_count']=len(r.get('member_ids') or []) or 1
 return {'items':page_rows,'page':page,'limit':limit,'total':total,'view':'unique','source':'dedup-canonical','raw_total':len(load_cached())}
def source_counts_unique():
 '''Per-source counts over the canonical set (membership, not disjoint).'''
 if not CANONICAL_PATH.exists():return {}
 rows=json.loads(CANONICAL_PATH.read_text(encoding='utf-8'))
 if not isinstance(rows,list):return {}
 out={}
 for r in rows:
  for s in (r.get('sources') or []):out[str(s)]=out.get(str(s),0)+1
 return out

def list_servers(*,page=1,limit=50,search='',category='',source=''):
 if page<1 or not 1<=limit<=100:raise ValueError('invalid pagination')
 items=list(load_cached().values());needle=search.casefold().strip()
 if needle:items=[x for x in items if needle in (x['id']+' '+x['name']+' '+x['description']).casefold()]
 if category:items=[x for x in items if x['category'].casefold()==category.casefold()]
 if source:
  wanted={s.strip().casefold() for s in source.split(',') if s.strip()}
  # Each source is now its own tab, so this must filter on exactly what was
  # asked for. It used to fold glama-connector into glama, which made the "Glama"
  # tab report 20.000 while the grid underneath it held 21.000 rows.
  items=[x for x in items if str(x.get('source') or 'toolsdk').casefold() in wanted]
 items.sort(key=lambda x:x['id']);total=len(items);start=(page-1)*limit
 return {'items':items[start:start+limit],'page':page,'limit':limit,'total':total,'source':'toolsdk-mcp-registry','sources':source_counts()}
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

def openconnector_coverage():
 """Honest numbers for the OpenConnector catalogue.

 ``actions`` counts catalogue rows, ``meta_tools`` is what an MCP client can
 actually see, and ``actions_call_verified`` counts actions proved by a real
 ``tools/call``.
 """
 items=[x for x in load_cached().values() if isinstance(x,dict) and x.get('source')=='openconnector']
 return {'services':len(items),'actions':sum(int(x.get('tools_count') or 0) for x in items),'meta_tools':5,
         'actions_call_verified':sum(1 for x in items for t in (x.get('tools') or []) if isinstance(t,dict) and t.get('call_verified')),
         'services_call_verified':sum(1 for x in items if (x.get('verification') or {}).get('call_verified'))}

def coverage():
    items = [x for x in load_cached().values() if isinstance(x, dict) and x.get('id')]
    composio = [x for x in items if x.get('source') == 'composio']
    official = [x for x in items if x.get('source') == 'official-mcp-registry']
    oc = openconnector_coverage()
    return {'total': len(items), 'executable': len(executable_servers()), 'metadata_only': len(items) - len(executable_servers()), 'composio_toolkits': len(composio), 'official_remote': len(official), 'openconnector_services': oc['services'], 'openconnector_actions': oc['actions'], 'openconnector_actions_call_verified': oc['actions_call_verified'], 'openapi': openapi_coverage(), 'sources': source_counts()}

def recommend_servers(query: str, limit: int = 5):
    """Return catalog matches for the AI integration picker; metadata only."""
    q=(query or '').strip()
    result=list_servers(page=1,limit=min(max(int(limit),1),20),search=q)
    return result['items']
