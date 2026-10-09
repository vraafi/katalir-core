# memory_provider.py — Fitur #12: External Memory Provider (9 Okt 2026)
# ======================================================================
# Adapter pattern di atas `memory_manager.MemoryManager` (internal, pgvector
# di Supabase). Interface TUNGGAL supaya agent tidak pernah tahu provider
# mana yang aktif:
#
#     remember(content, **scope) -> dict
#     recall(query, top_k, **scope) -> list[dict]
#     forget(memory_id, **scope) -> bool
#     search(query, top_k, **scope) -> list[dict]     (alias semantik recall)
#     health() -> dict
#
# PROVIDER (riset Okt 2026 — docs resmi):
#   - internal    : MemoryManager (Supabase pgvector). DEFAULT + FALLBACK.
#   - supermemory : https://api.supermemory.ai  Bearer sm_...
#       ingest  POST /v3/documents      {content, containerTags:[...]}
#       search  POST /v4/search         {q, containerTags:[...]}
#       forget  DELETE /v3/documents/{id}
#       (v3/v4 DEPRECATED — dimatikan 31 Des 2026; v5 = migrasi. Lihat
#        https://supermemory.ai/docs/api-reference/overview)
#   - mem0        : base OSS `POST /memories` {messages,user_id,agent_id}
#       search POST /search {query,user_id}   delete DELETE /memories/{id}
#       (platform memakai prefix /v1; OSS tidak. Lihat docs.mem0.ai)
#   - zep         : `POST /api/v2/sessions/{sid}/memory` + `GET /memory/search`
#   - letta       : REST /v1/agents/{id}/memory (block-based)
#
# KEPUTUSAN (kenapa TIDAK memakai SDK vendor):
#   SDK Python resmi (supermemory/mem0ai/zep-cloud) menambah 3 dependensi
#   yang saling tidak kompatibel menjelang deploy, sementara kebutuhan kita
#   hanya 4 operasi REST sederhana. Kita pakai `httpx` (SUDAH dipakai
#   memory_manager + secrets_provider) sehingga NOL dependensi baru dan
#   setiap provider bisa diuji terhadap server tiruan (WSGI/ASGI) tanpa
#   jaringan.
#
# KEPUTUSAN (kenapa httpx.Client dengan transport injectable):
#   `httpx.Client(transport=...)` memungkinkan hard test menembak mock
#   in-process — jadi tes BENAR-BENAR memanggil kode provider, bukan
#   men-stub-nya. Pola yang sama dengan secret_provider di repo ini.
#
# ISOLASI MULTI-TENANT: setiap provider WAJIB di-scope per (user_id, agent_id).
# `containerTags`/`user_id` diturunkan dari AUTORITAS PEMANGGIL, bukan dari
# config mentah, sehingga user A tidak bisa membaca memori user B.
# ======================================================================

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

#: Provider yang didukung. `internal` selalu tersedia.
KNOWN_PROVIDERS = ("internal", "supermemory", "mem0", "zep", "letta")

DEFAULT_TIMEOUT_S = float(os.getenv("MEMORY_PROVIDER_TIMEOUT_S", "12"))
MAX_RESULTS = int(os.getenv("MEMORY_PROVIDER_MAX_RESULTS", "50"))


class MemoryProviderError(RuntimeError):
    """Provider eksternal gagal — pemanggil boleh fallback ke internal."""


def _scope_tags(user_id: str, agent_id: str) -> list[str]:
    """Tag container per (user, agent). Dipakai untuk INGEST."""
    return [f"user:{user_id}", f"agent:{agent_id}"]


def _container_tag(user_id: str, agent_id: str) -> str:
    """Satu tag container deterministik — dipakai untuk SEARCH.

    Temuan hard test (server nyata): `POST /v4/search` Supermemory menolak
    >1 containerTag —
      "v4 search is single-space: pass one containerTag, or use /v3/search
       for multi-tag search"
    Karena itu ingest memakai dua tag (user+agent) dan search memakai SATU
    tag gabungan yang unik per (user, agent). Nilai tetap deterministik
    sehingga dokumen bisa ditemukan kembali.
    """
    return f"user:{user_id}:agent:{agent_id}"


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text[:2000]}


# ---------------------------------------------------------------------------
# Interface dasar
# ---------------------------------------------------------------------------

class BaseProvider:
    """Kontrak provider. Subclass WAJIB mengisi `name` dan implementasi 4 op."""

    name = "base"
    is_external = False

    def remember(self, content: str, user_id: str, agent_id: str = "default",
                 metadata: Optional[dict] = None,
                 memory_type: str = "semantic", **kw: Any) -> dict:
        raise NotImplementedError

    def recall(self, query: str, user_id: str, agent_id: str = "default",
               top_k: int = 5, **kw: Any) -> list[dict]:
        raise NotImplementedError

    def forget(self, memory_id: str, user_id: str,
               agent_id: str = "default", **kw: Any) -> bool:
        raise NotImplementedError

    def search(self, query: str, user_id: str, agent_id: str = "default",
               top_k: int = 5, **kw: Any) -> list[dict]:
        """Alias semantik untuk recall (LANGKAH 0 brief: search())."""
        return self.recall(query, user_id=user_id, agent_id=agent_id,
                           top_k=top_k, **kw)

    def health(self) -> dict:
        return {"provider": self.name, "ok": True, "external": self.is_external}


# ---------------------------------------------------------------------------
# Internal (Supabase pgvector) — default & fallback
# ---------------------------------------------------------------------------

class InternalProvider(BaseProvider):
    name = "internal"

    def __init__(self, manager_factory: Any = None):
        self._factory = manager_factory

    def _mm(self, user_id: str, agent_id: str):
        if self._factory is not None:
            return self._factory(user_id, agent_id)
        import memory_manager
        return memory_manager.MemoryManager(user_id=user_id, agent_id=agent_id)

    def remember(self, content, user_id, agent_id="default", metadata=None,
                 memory_type="semantic", **kw) -> dict:
        row = self._mm(user_id, agent_id).remember(
            content, memory_type=memory_type, metadata=metadata)
        return {"id": row.get("id"), "provider": self.name,
                "content": content, "raw": row}

    def recall(self, query, user_id, agent_id="default", top_k=5, **kw) -> list[dict]:
        rows = self._mm(user_id, agent_id).recall(query, top_k=top_k)
        return [{"id": r.get("id"), "content": r.get("content"),
                 "score": r.get("similarity"), "provider": self.name}
                for r in rows]

    def forget(self, memory_id, user_id, agent_id="default", **kw) -> bool:
        return bool(self._mm(user_id, agent_id).forget(memory_id))


# ---------------------------------------------------------------------------
# HTTP provider dasar (transport injectable untuk hard test)
# ---------------------------------------------------------------------------

class HttpProvider(BaseProvider):
    is_external = True
    base_url = ""

    def __init__(self, api_key: str = "", base_url: str = "",
                 transport: httpx.BaseTransport | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S, extra_headers: Optional[dict] = None):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or self.base_url).rstrip("/")
        self.timeout_s = timeout_s
        self.extra_headers = dict(extra_headers or {})
        client_kw: dict[str, Any] = {"timeout": timeout_s}
        if transport is not None:
            client_kw["transport"] = transport
        self._client = httpx.Client(**client_kw)

    # -- helper -------------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _headers(self) -> dict:
        h = {"Accept": "application/json", "User-Agent": "katalir-memory/1.0"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        h.update(self.extra_headers)
        return h

    def _request(self, method: str, path: str, *, json_body: Any = None,
                 params: Optional[dict] = None) -> Any:
        if not self.configured():
            raise MemoryProviderError(f"{self.name}: kredensial/URL belum diset")
        url = f"{self.base_url}{path}"
        headers = self._headers()
        # Content-Type HANYA saat ada body (pelajaran secret_provider:
        # Cloudflare/proxy menolak GET dengan Content-Type tanpa body).
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            resp = self._client.request(method, url, headers=headers,
                                        json=json_body, params=params)
        except httpx.HTTPError as exc:
            raise MemoryProviderError(f"{self.name}: {type(exc).__name__}: {exc}") from None
        if resp.status_code >= 400:
            raise MemoryProviderError(
                f"{self.name}: HTTP {resp.status_code} {resp.text[:300]}")
        return _safe_json(resp)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Supermemory
# ---------------------------------------------------------------------------

class SupermemoryProvider(HttpProvider):
    name = "supermemory"
    base_url = "https://api.supermemory.ai"

    def remember(self, content, user_id, agent_id="default", metadata=None,
                 memory_type="semantic", **kw) -> dict:
        body = {
            "content": content,
            # Ingest memakai dua tag (user+agent) — sama dengan scope search.
            "containerTags": _scope_tags(user_id, agent_id)
            + [_container_tag(user_id, agent_id)],
            "metadata": {"memory_type": memory_type, **(metadata or {})},
        }
        data = self._request("POST", "/v3/documents", json_body=body)
        return {"id": (data or {}).get("id") or (data or {}).get("documentId"),
                "provider": self.name, "content": content, "raw": data}

    def recall(self, query, user_id, agent_id="default", top_k=5, **kw) -> list[dict]:
        # /v4/search MENERIMA SATU containerTag saja (lihat _container_tag).
        body = {"q": query, "containerTag": _container_tag(user_id, agent_id),
                "limit": max(1, min(int(top_k), MAX_RESULTS))}
        data = self._request("POST", "/v4/search", json_body=body)
        rows = (data or {}).get("results") or (data or {}).get("memories") or []
        out = []
        for r in rows:
            out.append({"id": r.get("id") or r.get("documentId"),
                        "content": r.get("content") or r.get("memory") or "",
                        "score": r.get("score") or r.get("similarity"),
                        "provider": self.name})
        return out

    def forget(self, memory_id, user_id, agent_id="default", **kw) -> bool:
        if not memory_id:
            return False
        self._request("DELETE", f"/v3/documents/{memory_id}")
        return True


# ---------------------------------------------------------------------------
# Mem0 (OSS path tanpa /v1)
# ---------------------------------------------------------------------------

class Mem0Provider(HttpProvider):
    name = "mem0"
    base_url = "https://api.mem0.ai"

    def remember(self, content, user_id, agent_id="default", metadata=None,
                 memory_type="semantic", **kw) -> dict:
        body = {
            "messages": [{"role": "user", "content": content}],
            "user_id": str(user_id),
            "agent_id": str(agent_id),
            "metadata": {"memory_type": memory_type, **(metadata or {})},
        }
        data = self._request("POST", "/memories", json_body=body)
        ids = (data or {}).get("results") or (data or {}).get("ids") or []
        mid = None
        if isinstance(ids, list) and ids:
            first = ids[0]
            mid = first.get("id") if isinstance(first, dict) else first
        return {"id": mid, "provider": self.name, "content": content, "raw": data}

    def recall(self, query, user_id, agent_id="default", top_k=5, **kw) -> list[dict]:
        body = {"query": query, "user_id": str(user_id),
                "agent_id": str(agent_id),
                "limit": max(1, min(int(top_k), MAX_RESULTS))}
        data = self._request("POST", "/search", json_body=body)
        rows = (data or {}).get("results") or (data or {}).get("memories") or []
        if isinstance(data, list):
            rows = data
        return [{"id": r.get("id"), "content": r.get("memory") or r.get("content") or "",
                 "score": r.get("score"), "provider": self.name} for r in rows]

    def forget(self, memory_id, user_id, agent_id="default", **kw) -> bool:
        if not memory_id:
            return False
        self._request("DELETE", f"/memories/{memory_id}")
        return True


# ---------------------------------------------------------------------------
# Zep
# ---------------------------------------------------------------------------

class ZepProvider(HttpProvider):
    name = "zep"
    base_url = "https://api.getzep.com"

    def _session(self, user_id: str, agent_id: str) -> str:
        # Sesi deterministik per (user, agent): tidak perlu panggilan create.
        return f"{user_id}::{agent_id}"

    def remember(self, content, user_id, agent_id="default", metadata=None,
                 memory_type="semantic", **kw) -> dict:
        sid = self._session(user_id, agent_id)
        body = {"messages": [{"role": "user", "content": content,
                              "metadata": metadata or {}}]}
        data = self._request("POST", f"/api/v2/sessions/{sid}/memory",
                             json_body=body)
        return {"id": f"{sid}:{len(str(content))}", "provider": self.name,
                "content": content, "raw": data}

    def recall(self, query, user_id, agent_id="default", top_k=5, **kw) -> list[dict]:
        sid = self._session(user_id, agent_id)
        params = {"text": query, "limit": max(1, min(int(top_k), MAX_RESULTS))}
        data = self._request("GET", f"/api/v2/sessions/{sid}/memory/search",
                             params=params)
        rows = (data or {}).get("results") if isinstance(data, dict) else data
        rows = rows or []
        return [{"id": r.get("uuid") or r.get("id"),
                 "content": r.get("fact") or r.get("content") or r.get("message") or "",
                 "score": r.get("score"), "provider": self.name} for r in rows]

    def forget(self, memory_id, user_id, agent_id="default", **kw) -> bool:
        if not memory_id:
            return False
        self._request("DELETE", f"/api/v2/memory/{memory_id}")
        return True


# ---------------------------------------------------------------------------
# Letta (block-based)
# ---------------------------------------------------------------------------

class LettaProvider(HttpProvider):
    name = "letta"
    base_url = "https://api.letta.com"

    def _agent(self, user_id: str, agent_id: str) -> str:
        return f"{user_id}::{agent_id}"

    def remember(self, content, user_id, agent_id="default", metadata=None,
                 memory_type="semantic", **kw) -> dict:
        aid = self._agent(user_id, agent_id)
        label = (metadata or {}).get("label") or memory_type
        body = {"label": label, "value": content, "description": "katalir memory"}
        data = self._request("POST", f"/v1/agents/{aid}/memory/blocks",
                             json_body=body)
        return {"id": (data or {}).get("id") or f"{aid}:{label}",
                "provider": self.name, "content": content, "raw": data}

    def recall(self, query, user_id, agent_id="default", top_k=5, **kw) -> list[dict]:
        aid = self._agent(user_id, agent_id)
        data = self._request("GET", f"/v1/agents/{aid}/memory/blocks")
        blocks = data if isinstance(data, list) else (data or {}).get("blocks") or []
        q = (query or "").lower()
        hits = []
        for b in blocks:
            val = str(b.get("value") or "")
            if q and q not in val.lower():
                continue
            hits.append({"id": b.get("id"), "content": val, "score": None,
                         "provider": self.name})
        return hits[:max(1, min(int(top_k), MAX_RESULTS))]

    def forget(self, memory_id, user_id, agent_id="default", **kw) -> bool:
        if not memory_id:
            return False
        # Letta blocks diidentifikasi per-agent; hapus nilai lewat PATCH kosong.
        aid = self._agent(user_id, agent_id)
        self._request("DELETE", f"/v1/agents/{aid}/memory/blocks/{memory_id}")
        return True


# ---------------------------------------------------------------------------
# Registry + resolver (config per user, fallback internal)
# ---------------------------------------------------------------------------

_PROVIDER_KEYS = {
    "supermemory": ("SUPERMEMORY_API_KEY", "SUPERMEMORY_BASE_URL"),
    "mem0": ("MEM0_API_KEY", "MEM0_BASE_URL"),
    "zep": ("ZEP_API_KEY", "ZEP_BASE_URL"),
    "letta": ("LETTA_API_KEY", "LETTA_BASE_URL"),
}

_CLASSES = {
    "supermemory": SupermemoryProvider,
    "mem0": Mem0Provider,
    "zep": ZepProvider,
    "letta": LettaProvider,
}


def build_provider(name: str, api_key: str = "", base_url: str = "",
                   transport: httpx.BaseTransport | None = None,
                   manager_factory: Any = None) -> BaseProvider:
    """Bangun provider berdasarkan nama. `internal` selalu bisa."""
    key = (name or "internal").strip().lower()
    if key in ("", "internal", "default", "local"):
        return InternalProvider(manager_factory=manager_factory)
    if key not in _CLASSES:
        raise MemoryProviderError(f"provider tidak dikenal: {name}")
    env_k, env_u = _PROVIDER_KEYS[key]
    return _CLASSES[key](
        api_key=api_key or os.getenv(env_k, ""),
        base_url=base_url or os.getenv(env_u, ""),
        transport=transport)


def resolve_provider(config: Any = None,
                     transport: httpx.BaseTransport | None = None,
                     manager_factory: Any = None) -> BaseProvider:
    """Resolve provider dari konfigurasi user.

    `config` boleh: None, string nama, atau dict {"provider":..., "api_key":...,
    "base_url":..., "enabled": bool}. Bila provider eksternal tidak dikonfigurasi
    (kunci kosong) → JATUH ke `internal` secara diam-diam (fail-safe, agent
    tetap punya memori).
    """
    if config is None:
        return InternalProvider(manager_factory=manager_factory)
    if isinstance(config, str):
        config = {"provider": config}
    if not isinstance(config, dict):
        return InternalProvider(manager_factory=manager_factory)
    if config.get("enabled") is False:
        return InternalProvider(manager_factory=manager_factory)
    name = str(config.get("provider") or "internal")
    try:
        prov = build_provider(name, api_key=str(config.get("api_key") or ""),
                              base_url=str(config.get("base_url") or ""),
                              transport=transport,
                              manager_factory=manager_factory)
    except MemoryProviderError:
        return InternalProvider(manager_factory=manager_factory)
    if prov.is_external and not getattr(prov, "configured", lambda: True)():
        prov.close()
        return InternalProvider(manager_factory=manager_factory)
    return prov


# ---------------------------------------------------------------------------
# Facade: satu objek, provider + fallback + sinkronisasi
# ---------------------------------------------------------------------------

class MemoryService:
    """Provider aktif + fallback internal + sinkronisasi dua arah."""

    def __init__(self, provider: BaseProvider,
                 fallback: Optional[BaseProvider] = None,
                 user_id: str = "", agent_id: str = "default"):
        self.provider = provider or InternalProvider()
        self.fallback = fallback or InternalProvider()
        self.user_id = str(user_id)
        self.agent_id = str(agent_id or "default")

    # -- operasi inti dengan fallback ---------------------------------------
    def remember(self, content: str, metadata: Optional[dict] = None,
                 memory_type: str = "semantic", sync: bool = False) -> dict:
        primary_ok = True
        out: dict = {}
        try:
            out = self.provider.remember(content, user_id=self.user_id,
                                         agent_id=self.agent_id,
                                         metadata=metadata,
                                         memory_type=memory_type)
        except Exception as exc:  # noqa: BLE001
            primary_ok = False
            out = {"provider": self.provider.name, "error": f"{type(exc).__name__}: {exc}"}
        if not primary_ok or sync:
            fb = self.fallback.remember(content, user_id=self.user_id,
                                        agent_id=self.agent_id,
                                        metadata=metadata,
                                        memory_type=memory_type)
            out["fallback"] = fb
        out["primary_ok"] = primary_ok
        return out

    def recall(self, query: str, top_k: int = 5, **kw: Any) -> list[dict]:
        try:
            rows = self.provider.recall(query, user_id=self.user_id,
                                        agent_id=self.agent_id, top_k=top_k, **kw)
            if rows:
                return rows
        except Exception:  # noqa: BLE001
            pass
        try:
            return self.fallback.recall(query, user_id=self.user_id,
                                        agent_id=self.agent_id, top_k=top_k, **kw)
        except Exception:  # noqa: BLE001
            return []

    def search(self, query: str, top_k: int = 5, **kw: Any) -> list[dict]:
        return self.recall(query, top_k=top_k, **kw)

    def forget(self, memory_id: str) -> bool:
        ok = False
        try:
            ok = bool(self.provider.forget(memory_id, user_id=self.user_id,
                                           agent_id=self.agent_id))
        except Exception:  # noqa: BLE001
            ok = False
        if self.provider is not self.fallback:
            try:
                self.fallback.forget(memory_id, user_id=self.user_id,
                                     agent_id=self.agent_id)
            except Exception:  # noqa: BLE001
                pass
        return ok

    # -- sinkronisasi -------------------------------------------------------
    def sync(self, query: str = "", top_k: int = 20) -> dict:
        """Sinkron hasil eksternal -> internal (agar selalu ada salinan lokal).

        Arah satu arah eksternal→internal adalah pilihan sadar: internal adalah
        sumber fallback, jadi harus selalu menjadi superset yang aman.
        """
        try:
            rows = self.provider.recall(query or "*", user_id=self.user_id,
                                        agent_id=self.agent_id, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            return {"synced": 0, "error": f"{type(exc).__name__}: {exc}"}
        n = 0
        for r in rows:
            content = str(r.get("content") or "").strip()
            if not content:
                continue
            try:
                self.fallback.remember(content, user_id=self.user_id,
                                       agent_id=self.agent_id,
                                       metadata={"source_provider": self.provider.name,
                                                 "source_id": r.get("id")})
                n += 1
            except Exception:  # noqa: BLE001
                pass
        return {"synced": n, "total": len(rows)}

    def health(self) -> dict:
        h = {"active": self.provider.name, "user_id": self.user_id,
             "agent_id": self.agent_id}
        try:
            h["provider"] = self.provider.health() if hasattr(
                self.provider, "health") else {"provider": self.provider.name}
        except Exception as exc:  # noqa: BLE001
            h["provider"] = {"provider": self.provider.name,
                             "ok": False, "error": str(exc)[:200]}
        return h


def service_for(config: Any, user_id: str, agent_id: str = "default",
                transport: httpx.BaseTransport | None = None,
                manager_factory: Any = None) -> MemoryService:
    """Bangun MemoryService: provider aktif + fallback internal."""
    provider = resolve_provider(config, transport=transport,
                               manager_factory=manager_factory)
    fallback = InternalProvider(manager_factory=manager_factory)
    return MemoryService(provider, fallback=fallback,
                         user_id=user_id, agent_id=agent_id)


__all__ = [
    "KNOWN_PROVIDERS", "MemoryProviderError", "BaseProvider", "InternalProvider",
    "SupermemoryProvider", "Mem0Provider", "ZepProvider", "LettaProvider",
    "build_provider", "resolve_provider", "MemoryService", "service_for",
]
