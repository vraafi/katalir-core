"""Sync the Glama MCP directory into a Katalir registry file.

Licence: Glama's **API Data License** - not public domain. Every page that shows
this data must carry a visible "Powered by Glama" credit and every listing must
link back to its Glama page. ``scripts/sync-glama.py`` therefore always records
``source``/``source_url``/``attribution_required`` so the UI is forced to render
both. See docs/distribution/glama-attribution.md.

Read-only. Never prints the API key.

Verified against the live API on 2026-09-25:
  * base          https://glama.ai/api/mcp/v1/servers
  * auth          Authorization: Bearer <GLAMA_API_KEY>
  * response      {"pageInfo": {...}, "servers": [...]}
  * pagination    ?first=<<=100>&after=<endCursor>
  * rate limit    100 req/s/IP, exposed via RateLimit-* headers
  * listing url   the ``url`` field the API returns per server

There is no ``total`` field in the response, so the directory size is never
asserted from this script - only the number actually synced is reported.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import httpx
from dotenv import load_dotenv

BASE = "https://glama.ai/api/mcp/v1/servers"
PAGE = "https://glama.ai"
TRANSIENT = {429, 500, 502, 503, 504, 525}
DESC_LIMIT = 300


def load_key() -> str:
    load_dotenv(override=True)
    key = (os.environ.get("GLAMA_API_KEY") or "").strip()
    if not key:
        raise SystemExit("GLAMA_API_KEY missing")
    return key


class GlamaClient:
    def __init__(self, key: str, timeout: int = 30):
        self.servers_url = BASE
        self.connectors_url = BASE.rsplit("/servers", 1)[0] + "/connectors"
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
        )
        self.requests = 0
        self.transient_retries = 0

    def _pace(self, response: httpx.Response | None) -> None:
        if response is None:
            return
        remaining = response.headers.get("ratelimit-remaining")
        reset = response.headers.get("ratelimit-reset")
        if remaining is not None and int(remaining) <= 5 and reset:
            time.sleep(min(int(reset) + 0.2, 5.0))

    def page_json(self, url: str, first: int, after: str | None, tries: int = 6) -> dict:
        params = {"first": first}
        if after:
            params["after"] = after
        last = "unknown"
        for attempt in range(1, tries + 1):
            try:
                r = self._client.get(url, params=params)
                self.requests += 1
                self._pace(r)
                if r.status_code in TRANSIENT:
                    last = f"HTTP {r.status_code}"
                    self.transient_retries += 1
                    retry_after = r.headers.get("retry-after")
                    wait = float(retry_after) if (retry_after or "").isdigit() else min(2**attempt, 15)
                    time.sleep(wait)
                    continue
                if r.status_code == 401:
                    raise SystemExit("GLAMA_API_KEY rejected (HTTP 401)")
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                if "json" not in ctype:
                    # Glama intermittently answers HTML to a healthy request
                    last = f"non-JSON content-type {ctype!r}"
                    self.transient_retries += 1
                    time.sleep(min(2**attempt, 10))
                    continue
                return r.json()
            except httpx.HTTPError as exc:
                last = type(exc).__name__
                self.transient_retries += 1
                time.sleep(min(2**attempt, 15))
        raise SystemExit(f"glama page failed after {tries} tries: {last}")

    def page(self, first: int, after: str | None, tries: int = 6) -> dict:
        return self.page_json(self.servers_url, first, after, tries)

    def close(self) -> None:
        self._client.close()


def normalize(item: dict) -> dict | None:
    """Map one Glama server onto the Katalir registry shape."""
    if not isinstance(item, dict):
        return None
    sid = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not sid or not name:
        return None
    source_url = str(item.get("url") or f"{PAGE}/mcp/servers/{sid}")
    repo = item.get("repository")
    repo_url = repo.get("url") if isinstance(repo, dict) else (repo if isinstance(repo, str) else "")
    license_obj = item.get("spdxLicense")
    license_name = license_obj.get("name") if isinstance(license_obj, dict) else (license_obj or "")
    raw_tools = item.get("tools")
    tools = raw_tools if isinstance(raw_tools, list) else []
    env_schema = item.get("environmentVariablesJsonSchema")
    env_props = env_schema.get("properties") if isinstance(env_schema, dict) else None
    env_keys = sorted(env_props.keys()) if isinstance(env_props, dict) else []
    return {
        "id": f"glama/{sid}",
        "slug": str(item.get("slug") or sid),
        "glama_id": sid,
        "name": name,
        "namespace": str(item.get("namespace") or ""),
        "description": str(item.get("description") or "")[:DESC_LIMIT],
        "category": "mcp",
        "attributes": [str(a) for a in (item.get("attributes") or [])][:12],
        "repo_url": str(repo_url or ""),
        "spdx_license": str(license_name or ""),
        "thumbnail_url": item.get("thumbnailUrl") or "",
        "install_config": {
            "transport": "metadata-only",
            "package": "",
            "install_method": "glama",
        },
        "tenant_scope": "user",
        "validated": True,
        "tools": [{"name": str((t.get("name") if isinstance(t, dict) else t) or "")} for t in tools[:200]],
        "tools_count": len(tools),
        "auth_schemes": ["env:" + k for k in env_keys[:20]],
        "requires_env_vars": bool(env_keys),
        "no_auth": not env_keys,
        "source": "glama",
        "source_url": source_url,
        "attribution_required": True,
        "quality_score": item.get("qualityScore"),
        "is_boosted": bool(item.get("isBoosted")),
        "runtime_verified": False,
        "verification": {"discovered": True, "tools_listed": False, "call_verified": False},
    }


def sync(client: GlamaClient, max_servers: int, page_size: int) -> tuple[dict, dict]:
    out: dict[str, dict] = {}
    cursor: str | None = None
    has_next = True
    while has_next and len(out) < max_servers:
        data = client.page(page_size, cursor)
        items = data.get("servers") or data.get("data") or data.get("items") or []
        added = 0
        for raw in items:
            rec = normalize(raw)
            if rec is None:
                continue
            if rec["id"] in out:
                continue
            out[rec["id"]] = rec
            added += 1
            if len(out) >= max_servers:
                break
        info = data.get("pageInfo") or {}
        cursor = info.get("endCursor")
        has_next = bool(info.get("hasNextPage")) and bool(cursor)
        print(f"SYNCED={len(out)} added={added} has_next={has_next} requests={client.requests}", flush=True)
    return out, {
        "synced": len(out),
        "max_servers": max_servers,
        "requests": client.requests,
        "transient_retries": client.transient_retries,
        "tools_total": sum(r["tools_count"] for r in out.values()),
        "tools_named": sum(len(r["tools"]) for r in out.values()),
        "with_env_vars": sum(1 for r in out.values() if r["requires_env_vars"]),
        "no_auth": sum(1 for r in out.values() if r["no_auth"]),
        "with_repository": sum(1 for r in out.values() if r["repo_url"]),
        "licenses": sorted({r["spdx_license"] for r in out.values() if r["spdx_license"]})[:20],
    }


def normalize_connector(item: dict) -> dict | None:
    """Map one Glama *connector* (a running remote MCP endpoint) to our shape.

    Connectors are the runtime-relevant half of Glama: unlike servers, they
    carry a live URL, a transport, an auth type and a real toolCount.
    """
    if not isinstance(item, dict):
        return None
    cid = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    conn = item.get("connection") if isinstance(item.get("connection"), dict) else {}
    url = str(conn.get("url") or "").strip()
    if not cid or not name or not url:
        return None
    attributes = [str(a) for a in (item.get("attributes") or [])]
    auth_type = str(conn.get("authType") or ("none" if "auth:none" in attributes else ""))
    return {
        "id": f"glama-connector/{cid}",
        "slug": str(item.get("slug") or cid),
        "glama_id": cid,
        "name": name,
        "namespace": str(item.get("namespace") or ""),
        "description": str(item.get("description") or "")[:DESC_LIMIT],
        "category": "mcp-remote",
        "repo_url": str((item.get("repository") or {}).get("url") or "") if isinstance(item.get("repository"), dict) else "",
        "thumbnail_url": item.get("thumbnailUrl") or "",
        "endpoint_url": url,
        "transport": str(conn.get("transport") or "streamable_http"),
        "auth_type": auth_type,
        "no_auth": auth_type == "none",
        "healthy": bool(item.get("healthy")),
        "quality_score": item.get("qualityScore"),
        "attributes": attributes[:12],
        "install_config": {
            "transport": str(conn.get("transport") or "streamable_http"),
            "package": url,
            "install_method": "glama-remote",
        },
        "tenant_scope": "public",
        "validated": True,
        "tools": [],
        "tools_count": int(item.get("toolCount") or 0),
        "auth_schemes": [auth_type] if auth_type else [],
        "source": "glama-connector",
        "source_url": str(item.get("url") or f"{PAGE}/mcp/connectors/{item.get('namespace')}/{item.get('slug')}"),
        "attribution_required": True,
        "deprecated_at": item.get("deprecatedAt") or None,
        "runtime_verified": False,
        "verification": {"discovered": True, "tools_listed": False, "call_verified": False},
    }


def sync_connectors(client: GlamaClient, max_items: int, page_size: int) -> tuple[dict, dict]:
    out: dict[str, dict] = {}
    cursor: str | None = None
    has_next = True
    while has_next and len(out) < max_items:
        data = client.page_json(client.connectors_url, page_size, cursor)
        items = data.get("connectors") or []
        added = 0
        for raw in items:
            rec = normalize_connector(raw)
            if rec is None or rec["id"] in out:
                continue
            out[rec["id"]] = rec
            added += 1
            if len(out) >= max_items:
                break
        info = data.get("pageInfo") or {}
        cursor = info.get("endCursor")
        has_next = bool(info.get("hasNextPage")) and bool(cursor)
        print(f"CONNECTORS={len(out)} added={added} has_next={has_next} requests={client.requests}", flush=True)
        facets = {f.get("lookupKey"): f.get("count") for f in (data.get("facets") or []) if isinstance(f, dict)}
    return out, {
        "synced": len(out),
        "requests": client.requests,
        "transient_retries": client.transient_retries,
        "tools_total": sum(r["tools_count"] for r in out.values()),
        "no_auth": sum(1 for r in out.values() if r["no_auth"]),
        "healthy": sum(1 for r in out.values() if r["healthy"]),
        "no_auth_healthy": sum(1 for r in out.values() if r["no_auth"] and r["healthy"]),
        "no_auth_healthy_with_tools": sum(
            1 for r in out.values() if r["no_auth"] and r["healthy"] and r["tools_count"] > 0
        ),
        "facets_directory_totals": facets or {},
    }
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-servers", type=int, default=20000)
    ap.add_argument("--max-connectors", type=int, default=20000)
    ap.add_argument("--skip-servers", action="store_true")
    ap.add_argument("--skip-connectors", action="store_true")
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--out", default="glama_servers.json")
    ap.add_argument("--out-connectors", default="glama_connectors.json")
    ap.add_argument("--report", default="glama-sync-report.json")
    args = ap.parse_args()

    client = GlamaClient(load_key())
    report = {"synced_at_note": "generated by scripts/sync-glama.py; counts are what was actually fetched"}
    try:
        if not args.skip_servers:
            registry, server_report = sync(client, args.max_servers, min(args.page_size, 100))
            pathlib.Path(args.out).write_text(json.dumps(registry, indent=1, ensure_ascii=False), encoding="utf-8")
            report["servers"] = server_report
            print("GLAMA_SERVERS=", server_report["synced"], "TOOLS_IN_LIST=", server_report["tools_total"])
        if not args.skip_connectors:
            connectors, connector_report = sync_connectors(client, args.max_connectors, min(args.page_size, 100))
            pathlib.Path(args.out_connectors).write_text(json.dumps(connectors, indent=1, ensure_ascii=False), encoding="utf-8")
            report["connectors"] = connector_report
            print("GLAMA_CONNECTORS=", connector_report["synced"])
            print("GLAMA_CONNECTOR_TOOLS=", connector_report["tools_total"])
            print("GLAMA_CONNECTOR_NO_AUTH=", connector_report["no_auth"])
            print("GLAMA_CONNECTOR_NO_AUTH_HEALTHY=", connector_report["no_auth_healthy"])
            print("GLAMA_CONNECTOR_RUNTIMABLE=", connector_report["no_auth_healthy_with_tools"])
    finally:
        client.close()

    report["requests"] = client.requests
    report["transient_retries"] = client.transient_retries
    pathlib.Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("GLAMA_REQUESTS=", report["requests"], "TRANSIENT_RETRIES=", report["transient_retries"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
