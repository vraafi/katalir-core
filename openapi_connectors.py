"""FASE 4 — generate connector MCP dari katalog APIs.guru.

MEMAKAI ULANG `scripts/openapi_to_mcp.py` (bukan menulis generator baru):
fungsi `fetch_spec`, `extract_operations`, `resolve_base`, `security_schemes`,
dan `sanitize` diimpor langsung dari sana. Modul ini hanya menambahkan:

  * penemuan spec massal dari APIs.guru (`list.json`, 2.529 entri),
  * konversi hasil -> entri katalog bergaya `openapi-generated` yang sudah
    dipakai `mcp_registry` (id `openapi/<slug>`), dan
  * penulisan lewat `mcp_dedup` supaya tidak menduplikasi konektor.

Aturan kejujuran (diwarisi dari skrip aslinya):
  * `call_verified` SELALU False — belum ada satu pun yang dieksekusi;
  * `tools_listed` True hanya karena spec-nya terbaca;
  * `no_auth` diturunkan dari `security_schemes`, bukan diasumsikan.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
from typing import Any, Iterable

import httpx

ROOT = pathlib.Path(__file__).resolve().parent
GURU_LIST = "https://api.apis.guru/v2/list.json"


def _load_generator():
    """Impor `scripts/openapi_to_mcp.py` sebagai modul (nama berkas ada digit)."""
    path = ROOT / "scripts" / "openapi_to_mcp.py"
    spec = importlib.util.spec_from_file_location("openapi_to_mcp", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"tidak bisa memuat {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def slug_for(api_name: str) -> str:
    """`ably.io:platform` -> `ably-io-platform` (aman untuk id & tool name)."""
    s = api_name.lower()
    s = re.sub(r"[^0-9a-z]+", "-", s).strip("-")
    return s[:80] or "api"


def discover_guru_specs(*, limit: int | None = None,
                        client: httpx.Client | None = None) -> list[dict]:
    """Ambil daftar spec dari APIs.guru -> [{name, url, title, version}]."""
    own = client is None
    cli = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        data = cli.get(GURU_LIST).json()
    finally:
        if own:
            cli.close()
    rows: list[dict] = []
    for name, meta in data.items():
        pref = meta.get("preferred")
        ver = (meta.get("versions") or {}).get(pref) or {}
        url = ver.get("swaggerUrl") or ver.get("openapiUrl")
        if not url:
            continue
        info = ver.get("info") or {}
        rows.append({"name": name, "url": url,
                     "title": info.get("title") or name,
                     "version": ver.get("version") or pref,
                     "slug": slug_for(name)})
    rows.sort(key=lambda r: r["name"])
    return rows[:limit] if limit else rows


def build_entry(api: str, spec: dict, spec_url: str, *,
                max_per_api: int = 220, gen=None) -> dict | None:
    """Ubah satu spec OpenAPI -> entri katalog `openapi-generated`.

    Mengembalikan None bila spec tidak punya operasi yang layak (jujur: lebih
    baik tidak ada entri daripada entri kosong).
    """
    g = gen or _load_generator()
    ops = g.extract_operations(spec, api)
    ops = [o for o in ops if not o.get("deprecated")][:max_per_api]
    if not ops:
        return None
    schemes = g.security_schemes(spec)
    base, how = "", ""
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as cli:
            base, how = g.resolve_base(cli, spec, spec_url)
    except Exception:  # noqa: BLE001
        pass
    info = spec.get("info") or {}
    slug = slug_for(api)
    # PENTING: `scripts/openapi_to_mcp.py` menghasilkan tool dengan kunci
    # `tool` (mis. "dep.io_new"), sedangkan entri katalog yang sudah ada
    # (`openapi/kubernetes`, `openapi/stripe`) memakai kunci `name` + `id`.
    # Normalisasi di sini supaya `mcp_registry` & UI tetap membacanya.
    tools = []
    for t in ops:
        name = t.get("name") or t.get("tool") or ""
        tools.append({
            **t,
            "name": name,
            "id": t.get("id") or name,
            "description": t.get("description") or t.get("summary") or "",
            "call_verified": False,
            "verification": {"discovered": True, "tools_listed": True,
                             "call_verified": False},
        })
    return {
        "id": f"openapi/{slug}",
        "slug": slug,
        "name": info.get("title") or api,
        "description": (info.get("description") or
                        f"{len(ops)} tools generated from the public {api} OpenAPI specification.")[:500],
        "category": "mcp-openapi",
        "repo_url": "",
        "spdx_license": "",
        "source": "openapi-generated",
        "source_url": spec_url,
        "attribution_required": False,
        "endpoint_base_url": base,
        "base_url_evidence": how,
        "security_schemes": schemes,
        "no_auth": not bool(schemes),
        "tools": tools,
        "validated": True,
        "verification": {"discovered": True, "tools_listed": True,
                         "call_verified": False},
        "runtime_verified": False,
    }


def generate(spec_rows: Iterable[dict], *, max_per_api: int = 220,
             client: httpx.Client | None = None,
             progress: bool = True) -> dict:
    """Fetch + generate untuk banyak spec. Mengembalikan {entries, skipped}."""
    rows = list(spec_rows)
    gen = _load_generator()
    own = client is None
    cli = client or httpx.Client(timeout=30.0, follow_redirects=True)
    entries: list[dict] = []
    skipped: dict[str, str] = {}
    try:
        for i, row in enumerate(rows, 1):
            try:
                spec, err = gen.fetch_spec(cli, row["url"])
                if spec is None:
                    skipped[row["name"]] = err or "fetch gagal"
                    continue
                entry = build_entry(row["name"], spec, row["url"],
                                    max_per_api=max_per_api, gen=gen)
                if entry is None:
                    skipped[row["name"]] = "no operations"
                    continue
                entries.append(entry)
            except Exception as exc:  # noqa: BLE001
                skipped[row["name"]] = f"{type(exc).__name__}: {exc}"[:200]
            if progress and i % 25 == 0:
                print(f"  ... {i}/{len(rows)} (ok={len(entries)} skip={len(skipped)})",
                      flush=True)
    finally:
        if own:
            cli.close()
    return {"entries": entries, "skipped": skipped}


def describe() -> dict:
    return {
        "guru_list": GURU_LIST,
        "reuses": "scripts/openapi_to_mcp.py",
        "id_prefix": "openapi/",
        "category": "mcp-openapi",
        "call_verified_policy": "always False",
    }
