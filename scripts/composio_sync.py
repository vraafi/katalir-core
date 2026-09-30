"""Sync Composio toolkits (project API key) and verify tool listing.

Read-only against Composio. Writes composio_toolkits.json and a verification
report. Never prints the API key.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import httpx
from dotenv_loader import load_repo_env

load_repo_env()
BASE = "https://backend.composio.dev/api/v3.1"
KEY = (os.environ.get("COMPOSIO_API_KEY") or "").strip()
TARGETS = ["whatsapp","slack","gmail","github","notion","linear","stripe","googlesheets","telegram","discord","twitter","linkedin","hubspot","salesforce","airtable","dropbox","googledrive","googlecalendar","trello","asana"]

def client():
    if not KEY:
        raise SystemExit("COMPOSIO_API_KEY missing")
    return httpx.Client(headers={"x-api-key": KEY}, timeout=40)

def sync() -> dict:
    out={}; cursor=None
    with client() as c:
        while True:
            params={"limit":"100"}
            if cursor: params["cursor"]=cursor
            r=c.get(f"{BASE}/toolkits",params=params); r.raise_for_status()
            d=r.json()
            for t in d.get("items",[]):
                slug=str(t.get("slug") or "")
                if not slug: continue
                out[slug]={"id":f"composio/{slug}","slug":slug,"name":t.get("name") or slug,"description":((t.get("meta") or {}).get("description") or ""),"install_config":{"transport":"composio-remote","package":"","install_method":"composio"},"tenant_scope":"user","validated":True,"tools":[],"tools_count":int((t.get("meta") or {}).get("tools_count") or 0),"auth_schemes":t.get("auth_schemes") or [],"no_auth":bool(t.get("no_auth")),"source":"composio"}
            cursor=d.get("next_cursor")
            if not cursor: break
    Path("composio_toolkits.json").write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding="utf-8")
    return out

def verify(targets=TARGETS) -> list[dict]:
    results=[]
    with client() as c:
        for slug in targets:
            try:
                r=c.get(f"{BASE}/tools",params={"limit":"1","toolkit_slug":slug})
                if r.status_code!=200:
                    results.append({"slug":slug,"status":"fail","error":f"HTTP {r.status_code}"}); continue
                n=int((r.json() or {}).get("total_items") or 0)
                results.append({"slug":slug,"status":"ok" if n>0 else "fail","tools":n})
            except Exception as exc:  # noqa: BLE001
                results.append({"slug":slug,"status":"fail","error":type(exc).__name__})
    return results

if __name__=="__main__":
    toolkits=sync(); print(f"COMPOSIO_TOOLKITS_SYNCED={len(toolkits)}")
    results=verify(); Path("composio-verify.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    ok_slugs={r["slug"] for r in results if r["status"]=="ok"}
    for slug in ok_slugs:
        if slug in toolkits:
            toolkits[slug]["runtime_verified"]=True
            toolkits[slug]["tools"]=[{"name":"list_tools","description":f"verified tool listing ({next((x['tools'] for x in results if x['slug']==slug),0)} tools)"}]
    Path("composio_toolkits.json").write_text(json.dumps(toolkits,indent=2,ensure_ascii=False),encoding="utf-8")
    ok=sum(1 for r in results if r["status"]=="ok")
    print(f"TESTED={len(results)} OK={ok} FAIL={len(results)-ok}")
    for r in results:
        print(r)
    if ok < 15: sys.exit(1)
