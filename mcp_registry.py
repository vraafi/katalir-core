
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
def list_canonical(*,page=1,limit=50,search='',category='',source='',tier=''):
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
 rows=_apply_tier(rows,tier)
 total=len(rows);start=(page-1)*limit;page_rows=rows[start:start+limit]
 for r in page_rows:
  r['member_count']=len(r.get('member_ids') or []) or 1
  # Same reason as list_servers: the tier is computed once, here, and shipped.
  r['runtime_tier']=runtime_tier(r)
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

def runtime_tier(item: dict) -> str:
    """The one definition of a runtime tier, shared by the badge and the filter.

    F4.3 added a tier *filter*, and a filter that does not agree with the badge
    is worse than no filter: the user clicks "call_verified", sees N rows, and
    N rows are not the ones badged call_verified. So the classification lives
    here, the API ships the result on every item, and the UI renders it instead
    of recomputing it.

    The order is the whole point, and the two edge cases are deliberate:

    * ``no_auth is False`` is an explicit statement that a credential is needed.
    * ``no_auth`` *absent* means unknown, and unknown is NOT auth_required -
      promoting it would invent a claim nobody made.

    Collapsing any two of these is how a marketplace ends up claiming it has
    thousands of working integrations.
    """
    v = item.get('verification') if isinstance(item.get('verification'), dict) else {}
    if v.get('call_verified') or item.get('runtime_verified'):
        return 'call_verified'
    if item.get('no_auth') is False:
        return 'auth_required'
    if v.get('tools_listed'):
        return 'tools_listed'
    return 'discovered'


RUNTIME_TIERS = ('call_verified', 'auth_required', 'tools_listed', 'discovered')


def _apply_tier(items: list, tier: str) -> list:
    wanted = {t.strip() for t in str(tier or '').split(',') if t.strip()}
    if not wanted:
        return items
    bad = wanted - set(RUNTIME_TIERS)
    if bad:
        raise ValueError(f'unknown runtime tier: {sorted(bad)}')
    return [x for x in items if runtime_tier(x) in wanted]


def category_facets(*, source: str = "", limit: int = 40) -> dict:
    """Top categories with counts, for the F4.3 filter.

    Derived from the same rows the grid is built from, so a category shown in
    the dropdown always has a non-zero result. Hardcoding a list of "likely
    categories" would be the same mistake as a hardcoded tab: it would offer
    options that return nothing and hide real ones that return thousands.
    """
    items = load_cached().values()
    if source:
        wanted = {s.strip().casefold() for s in source.split(',') if s.strip()}
        items = [x for x in items if str(x.get('source') or 'toolsdk').casefold() in wanted]
    counts: dict = {}
    for x in items:
        c = str(x.get('category') or '').strip()
        if c:
            counts[c] = counts.get(c, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"total_categories": len(ordered), "categories": [{"category": c, "count": n} for c, n in ordered[:limit]]}


def list_servers(*,page=1,limit=50,search='',category='',source='',tier=''):
 if page<1 or not 1<=limit<=100:raise ValueError('invalid pagination')
 items=list(load_cached().values());needle=search.casefold().strip()
 # `.get`, not `[...]`: 3.112 rows in the catalogue carry no `category` key at
 # all, and this raised KeyError the moment F4.3 first sent a category. A latent
 # bug that sat unreachable precisely because nothing exercised the parameter.
 if needle:items=[x for x in items if needle in (str(x.get('id') or '')+' '+str(x.get('name') or '')+' '+str(x.get('description') or '')).casefold()]
 if category:items=[x for x in items if str(x.get('category') or '').casefold()==category.casefold()]
 if source:
  wanted={s.strip().casefold() for s in source.split(',') if s.strip()}
  # Each source is now its own tab, so this must filter on exactly what was
  # asked for. It used to fold glama-connector into glama, which made the "Glama"
  # tab report 20.000 while the grid underneath it held 21.000 rows.
  items=[x for x in items if str(x.get('source') or 'toolsdk').casefold() in wanted]
 items=_apply_tier(items,tier)
 # Ship the computed tier so the UI never has to re-derive it and drift.
 for x in items:x['runtime_tier']=runtime_tier(x)
 items.sort(key=lambda x:x['id']);total=len(items);start=(page-1)*limit
 return {'items':items[start:start+limit],'page':page,'limit':limit,'total':total,'source':'toolsdk-mcp-registry','sources':source_counts()}
def get_server(server_id):
 x=load_cached().get(server_id)
 if not x:raise KeyError(server_id)
 return x



# ─── Recommended MCP ────────────────────────────────────────────────────────
# Formula dikunci user (2026-09-29), TIDAK diubah di sini:
#   install_count_norm * 0.35 + call_verified * 0.35
#   + freshness * 0.20 + curator_pick * 0.10
#
# PENTING — dua dari empat input BELUM punya sumber data:
#   * install_count : tidak ada di katalog mana pun. Tidak diinventar.
#   * updated_at    : entri disinkron dari file cache, bukan DB bertimestamp.
# Keduanya ditulis 0 dan `signals` mengembalikan mana yang aktif, supaya
# bobot yang tidak terpakai TERLIHAT dan tidak tersembunyi di angka yang
# terlihat meyakinkan. Bobot 0,35 + 0,20 praktisnya diam; peringkat
# digerakkan call_verified (0,35) dan curator_pick (0,10). Rumus tetap utuh
# supaya begitu sumber datanya ada, bobotnya langsung hidup.
CURATOR_SEED = {
    "slack", "github", "notion", "linear", "stripe",
    "google-sheets", "google_sheets", "googlesheets", "gmail", "google-calendar",
    "google_calendar", "googlecalendar", "openai", "anthropic", "gemini",
    "telegram", "discord", "whatsapp", "supabase", "vercel", "cloudflare",
    "openconnector", "composio",
}


def _curator_key(entry: dict) -> str:
    """Kunci pencocokan curator.

    Dicocokkan ke `id` apa adanya (bukan ke `name`), karena `name`
    title case-nya tidak konsisten antar sumber, sedangkan `id` stabil
    walau memuat "@" dan titik (mis. "@toolsdk.ai/aws-ses-mcp").
    """
    return str(entry.get("id") or "").strip().casefold()


def is_curator_pick(entry: dict) -> bool:
    if entry.get("curator_pick") is True:
        return True
    key = _curator_key(entry)
    if key in CURATOR_SEED:
        return True
    # Sebagian id berawalan "@vendor/name"; dicocokkan juga tanpa bagian
    # vendor supaya "slack" tidak hanya lolos lewat vendor tertentu.
    tail = key.rsplit("/", 1)[-1]
    return tail in CURATOR_SEED or tail.replace("-", "_") in CURATOR_SEED


def _is_call_verified(entry: dict) -> bool:
    """Bukti runtime, mengikuti definisi tier yang sudah dipakai UI."""
    if entry.get("call_verified"):
        return True
    v = entry.get("verification")
    if isinstance(v, dict) and v.get("call_verified"):
        return True
    return bool(entry.get("runtime_verified"))


def compute_recommendation_score(entry: dict[str, Any]) -> dict[str, Any]:
    """Skor rekomendasi + rincian komponennya.

    Mengembalikan dict, bukan float, supaya UI dan audit bisa melihat
    komponen mana yang benar-benar contribute.

    REBALANCE (fallback, bukan perubahan rumus utama): kalau `install` dan
    `freshness` sama-sama 0 karena tidak ada datanya, bobot 0,35 + 0,20 itu
    mati dan entri yang punya bukti runtime bisa kalah dari entri yang
    tidak punya apa-apa hanya karena noise. Dalam kasus itu verified dan
    curator diskalakan penuh (0,6 / 0,4) supaya skor tetap informatif.
    Rumus utama TIDAK diubah dan langsung berlaku lagi begitu
    `mcp_signals.json` terisi.
    """
    install_raw = entry.get("install_count")
    # min(x/1000, 1.0) sesuai rumus terkunci.
    install = min(float(install_raw or 0) / 1000.0, 1.0) * 0.35

    updated = entry.get("updated_at")
    fresh = 0.0
    if updated:
        try:
            from datetime import datetime, timezone
            dt = updated if isinstance(updated, datetime) else datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            fresh = max(0.0, 1.0 - (datetime.now(timezone.utc) - dt).days / 180.0) * 0.20
        except Exception:
            fresh = 0.0

    is_verified = _is_call_verified(entry)
    is_curator = is_curator_pick(entry)

    rebalanced = False
    if install == 0.0 and fresh == 0.0:
        rebalanced = True
        verified = 0.6 if is_verified else 0.0
        curator = 0.4 if is_curator else 0.0
    else:
        verified = 0.35 if is_verified else 0.0
        curator = 0.10 if is_curator else 0.0

    return {
        "score": round(install + verified + fresh + curator, 4),
        "components": {
            "install": round(install, 4),
            "call_verified": verified,
            "freshness": round(fresh, 4),
            "curator_pick": curator,
        },
        "signals": {
            "has_install_count": install_raw is not None,
            "has_updated_at": bool(updated),
            "is_curator_pick": is_curator,
            "is_call_verified": is_verified,
            "rebalanced": rebalanced,
        },
    }


_SIGNALS: dict[str, Any] | None = None


def _load_signals() -> dict[str, Any]:
    """Sinyal hasil fetch (install_count / updated_at) per entry id.

    Dibaca dari `mcp_signals.json` yang ditulis `scripts/fetch-install-counts.py`.
    Sengaja dipisah dari cache katalog: cache adalah hasil sync upstream,
    sedangkan ini hasil pengukuran kita, dan keduanya punya tingkat
    freshness yang berbeda. Dicache per proses supaya tidak dibaca ulang
    tiap request.
    """
    global _SIGNALS
    if _SIGNALS is None:
        p = Path(__file__).with_name('mcp_signals.json')
        try:
            _SIGNALS = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        except Exception:
            _SIGNALS = {}
    return _SIGNALS


def get_recommended(*, category: str = "", source: str = "", limit: int = 5) -> dict[str, Any]:
    """Integrasi dengan skor tertinggi, dihitung runtime.

    Tidak ada daftar hardcoded di sini. CURATOR_SEED hanya memberi bonus;
    urutan sebenarnya dihitung dari sinyal, jadi entri non-curator yang punya
    bukti runtime bisa mendahului.
    """
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit must be 1..50")
    items = [x for x in load_cached().values() if isinstance(x, dict)]
    if category:
        c = category.casefold()
        items = [x for x in items if str(x.get("category") or "").casefold() == c]
    if source:
        wanted = {s.strip().casefold() for s in source.split(",") if s.strip()}
        items = [x for x in items if str(x.get("source") or "toolsdk").casefold() in wanted]

    signals = _load_signals()
    scored = []
    for e in items:
        # Sinyal hasil fetch digabung ke SALINAN entri, tidak ditulis ke cache
        # katalog: cache itu milik upstream, dan menulisi field-nya akan hilang
        # diam-diam pada sync berikutnya.
        sig = signals.get(str(e.get("id")))
        if sig:
            merged = dict(e)
            for k in ("install_count", "updated_at"):
                if sig.get(k) is not None and merged.get(k) is None:
                    merged[k] = sig[k]
            e = merged
        r = compute_recommendation_score(e)
        out = dict(e)
        out["recommendation"] = r
        out["is_recommended"] = r["score"] > 0
        scored.append(out)

    # Tie-break by name supaya urutan stabil antar request; tanpa itu
    # "top picks" bergeser tiap sync untuk alasan yang tak terlihat.
    scored.sort(key=lambda x: (-x["recommendation"]["score"], str(x.get("name") or "").casefold()))

    n = len(scored)
    cov_install = sum(1 for x in scored if x["recommendation"]["signals"]["has_install_count"])
    cov_updated = sum(1 for x in scored if x["recommendation"]["signals"]["has_updated_at"])
    cov_verified = sum(1 for x in scored if x["recommendation"]["signals"]["is_call_verified"])
    cov_curator = sum(1 for x in scored if x["recommendation"]["signals"]["is_curator_pick"])
    cov_rebalanced = sum(1 for x in scored if x["recommendation"]["signals"].get("rebalanced"))

    def pct(v):
        return round(v / n * 100, 2) if n else 0.0

    return {
        "items": scored[: int(limit)],
        "total_scored": n,
        "limit": int(limit),
        "category": category,
        "source": source,
        "formula": "install*0.35 + call_verified*0.35 + freshness*0.20 + curator_pick*0.10",
        "formula_note": "Bila install dan freshness keduanya 0 karena belum ada datanya, verified/curator diskalakan ke 0.6/0.4 supaya bobot 0.55 yang mati tidak memalsukan peringkat.",
        "data_coverage": {
            "total": n,
            "with_install_count": cov_install,
            "with_call_verified": cov_verified,
            "with_updated_at": cov_updated,
            "with_curator_pick": cov_curator,
            "using_fallback_weights": cov_rebalanced,
            "coverage_pct": {
                "install": pct(cov_install),
                "verified": pct(cov_verified),
                "freshness": pct(cov_updated),
                "curator": pct(cov_curator),
            },
            "signals_fetched": len(signals),
            # Bobot yang benar-benar berkontribusi saat ini, bukan teaser:
            # 0,35 + 0,20 = 0,55 masih nol sampai mcp_signals.json terisi.
            "max_achievable_score_today": 0.45 if cov_install == 0 and cov_updated == 0 else 1.0,
        },
    }


def executable_servers():
    """Return only registry entries with an explicit executable transport.

    ToolSDK metadata is currently metadata-only; do not treat it as runnable.
    """
    return [x for x in load_cached().values() if isinstance(x, dict) and (x.get('runtime_verified') is True or x.get('install_config', {}).get('transport') in {'stdio','http','sse'})]
