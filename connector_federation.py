"""FASE 5 — federation discovery dari registry MCP publik.

Catatan penting: repo `neuronto/agentic-resource-discovery` yang disebut brief
**tidak ada (404)** — lihat `docs/skills-installed.md`. Karena itu modul ini
memakai **registry resmi yang benar-benar hidup**, diverifikasi lewat HTTP:

  * `registry.modelcontextprotocol.io/v0/servers`  -> HTTP 200 (resmi, gratis)
  * `glama.ai/api/mcp/v1/servers`                  -> HTTP 401 (butuh kunci)
  * `smithery.ai/api/servers`                      -> HTTP 404 (endpoint berubah)

Hanya sumber yang benar-benar menjawab yang dipakai; sisanya dilaporkan apa
adanya, bukan diasumsikan.

Aturan dedup: entri baru hanya dihitung bila **slug/nama yang dinormalisasi**
belum ada di katalog yang sudah dimuat (`mcp_dedup.load_registry()` +
`mcp_registry.load_cached()`). Menghitung ulang konektor yang sudah ada akan
menggelembungkan angka — persis yang dihindari `mcp_dedup`.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Iterable

import httpx

OFFICIAL_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
PAGE_LIMIT = 100

SOURCES = {
    "official": {"url": OFFICIAL_REGISTRY, "status": "verified-200", "auth": False},
    "glama": {"url": "https://glama.ai/api/mcp/v1/servers",
              "status": "requires-key-401", "auth": True},
    "smithery": {"url": "https://smithery.ai/api/servers",
                 "status": "not-found-404", "auth": False},
}


def _entry_from_official(item: dict) -> dict | None:
    """Ubah satu item registry resmi -> entri katalog + URL endpoint."""
    srv = item.get("server") or {}
    name = srv.get("name")
    if not name:
        return None
    remotes = srv.get("remotes") or []
    url = None
    transport = None
    for r in remotes:
        u = r.get("url")
        if u:
            url = u
            t = (r.get("type") or "").lower()
            transport = "streamable_http" if "http" in t else (t or None)
            break
    meta = ((item.get("_meta") or {}).get(
        "io.modelcontextprotocol.registry/official") or {})
    return {
        "slug": name,
        "name": srv.get("title") or name,
        "description": (srv.get("description") or "")[:500],
        "version": srv.get("version"),
        "endpoint_url": url,
        "transport": transport,
        "status": meta.get("status"),
        "published_at": meta.get("publishedAt"),
        "remotes": remotes,
    }


def fetch_official(*, pages: int = 5, limit: int = PAGE_LIMIT,
                   client: httpx.Client | None = None,
                   sleep: float = 0.2) -> list[dict]:
    """Ambil server dari registry resmi MCP (paginasi by cursor)."""
    own = client is None
    cli = client or httpx.Client(timeout=30.0, follow_redirects=True)
    out: list[dict] = []
    cursor: str | None = None
    try:
        for _ in range(max(1, pages)):
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            r = cli.get(OFFICIAL_REGISTRY, params=params)
            if r.status_code != 200:
                break
            body = r.json()
            for item in (body.get("servers") or []):
                e = _entry_from_official(item)
                if e:
                    out.append(e)
            cursor = ((body.get("metadata") or {}).get("nextCursor"))
            if not cursor:
                break
            time.sleep(sleep)
    finally:
        if own:
            cli.close()
    return out


def existing_keys() -> set[str]:
    """Semua kunci yang sudah ada di katalog (nama + slug + id)."""
    keys: set[str] = set()
    try:
        import mcp_registry as mr
        for cid, e in mr.load_cached().items():
            keys.add(_norm(cid))
            if isinstance(e, dict):
                for f in ("slug", "name"):
                    if e.get(f):
                        keys.add(_norm(e[f]))
    except Exception as exc:  # noqa: BLE001
        print(f"[federation] katalog tidak terbaca: {exc}")
    return keys


def _norm(text: str) -> str:
    try:
        import mcp_dedup as md
        return md.normalize_name(text)
    except Exception:  # noqa: BLE001
        import re
        return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def dedup_against_catalog(entries: Iterable[dict],
                          known: set[str] | None = None) -> dict:
    """Pisahkan entri baru vs yang sudah ada. Tidak menghapus apa pun."""
    known = existing_keys() if known is None else known
    seen_here: set[str] = set()
    fresh: list[dict] = []
    duplicates: list[dict] = []
    for e in entries:
        k = _norm(e.get("slug") or e.get("name") or "")
        if not k:
            continue
        if k in known or k in seen_here:
            duplicates.append(e)
            continue
        seen_here.add(k)
        fresh.append(e)
    return {"fresh": fresh, "duplicates": duplicates,
            "total": len(fresh) + len(duplicates)}


def discover(*, pages: int = 5, persist: bool = False) -> dict:
    """Jalankan penemuan federasi + dedup. `persist` menulis hasil baru."""
    got = fetch_official(pages=pages)
    res = dedup_against_catalog(got)
    out = {
        "fetched": len(got),
        "fresh": len(res["fresh"]),
        "duplicates": len(res["duplicates"]),
        "with_endpoint": sum(1 for e in res["fresh"] if e.get("endpoint_url")),
        "sources": SOURCES,
        "sample": res["fresh"][:10],
    }
    if persist and res["fresh"]:
        path = pathlib.Path("federation_discovered.json")
        path.write_text(json.dumps(res["fresh"], indent=1, ensure_ascii=False),
                        encoding="utf-8")
        out["written_to"] = str(path)
    return out


def describe() -> dict:
    return {"sources": SOURCES, "official_registry": OFFICIAL_REGISTRY,
            "page_limit": PAGE_LIMIT,
            "missing_from_brief": "neuronto/agentic-resource-discovery (404)"}
