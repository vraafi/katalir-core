# vector_store.py — Fitur #2: RAG / Vector Store (8 Okt 2026)
# ======================================================================
# Menutup gap vs n8n "Vector Store" + "Document Loader" + "Embeddings".
# Riset Okt 2026 (docs/feature-gap-closure-2026-10-08.md §2):
#   - penyimpanan: Supabase pgvector (vektor 0.8.2 aktif; pola sama dengan
#     memory_manager.py, embedding Gemini 1536-dim);
#   - chunking: ukuran 800 char / tumpang-tindih 100 (praktik 2026);
#   - pencarian: hybrid (vektor + BM25) — murni vektor mentok ~0.75 recall;
#   - isolasi multi-tenant: SETIAP query difilter user_id (tanpa kecuali).
#
# DUA BACKEND
#   - Supabase pgvector (produksi) bila `database.is_configured()`.
#   - Memori proses (dev/uji) sebagai fallback deterministik. Uji TIDAK
#     menyentuh jaringan; backend produksi dipilih otomatis.
#
# EMBEDDING
#   Memakai `memory_manager.generate_embedding` (pool Gemini) bila tersedia.
#   Bila tidak (tanpa kunci / offline), jatuh ke `_hash_embed` — embedding
#   bag-of-words deterministik (L2-normalized). Ini BUKAN sihir semantik,
#   tetapi membuat pipeline tetap berjalan & bisa diuji tanpa jaringan;
#   status backend dilaporkan jujur di output (`embedding_backend`).
# ======================================================================

from __future__ import annotations

import hashlib
import math
import os
import re
import time
import uuid
from typing import Any, Optional

import database as db

EMBED_DIM = 1536
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_TOP_K = 5
MAX_TOP_K = 50
SEARCH_MODES = ("hybrid", "vector", "keyword")
OPERATIONS = ("insert", "query", "delete")

_WORD_RE = re.compile(r"[a-z0-9_]+")


class VectorStoreUnavailable(RuntimeError):
    """Backend vector store tidak siap (mis. DDL belum diterapkan)."""


# ---------------------------------------------------------------------------
# Pure helpers (diuji langsung)
# ---------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Pecah teks jadi chunk berukuran `chunk_size` dengan tumpang-tindih.

    Memotong di batas kata bila memungkinkan (hindari potongan di tengah kata).
    `overlap` dijepit < chunk_size supaya selalu maju (tidak loop tak berujung).
    """
    text = (text or "").strip()
    if not text:
        return []
    chunk_size = max(1, int(chunk_size or DEFAULT_CHUNK_SIZE))
    overlap = max(0, int(overlap or 0))
    if overlap >= chunk_size:
        overlap = chunk_size // 4
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # mundur ke batas kata terdekat (maks 40 char)
            cut = text.rfind(" ", start + int(chunk_size * 0.6), end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _bm25(query: str, docs: list[str], k1: float = 1.5,
          b: float = 0.75) -> list[float]:
    """Skor BM25 klasik (keyword) untuk setiap dokumen terhadap query."""
    q = _tokens(query)
    if not q or not docs:
        return [0.0] * len(docs)
    doc_tokens = [_tokens(d) for d in docs]
    n = len(doc_tokens)
    avgdl = sum(len(d) for d in doc_tokens) / n if n else 0.0
    df: dict[str, int] = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    scores: list[float] = []
    for toks in doc_tokens:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        dl = len(toks) or 1
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            num = tf[t] * (k1 + 1)
            den = tf[t] + k1 * (1 - b + b * dl / (avgdl or 1))
            s += idf * num / den
        scores.append(s)
    return scores


def _normalize(scores: list[float]) -> list[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [0.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def rank(query: str, docs: list[str], doc_vecs: list[list[float]],
         query_vec: Optional[list[float]] = None,
         mode: str = "hybrid", alpha: float = 0.5) -> list[tuple[int, float]]:
    """Kembalikan [(index_dokumen, skor)] terurut menurun.

    mode "vector"  : kosinus(query_vec, doc_vec)
    mode "keyword" : BM25 (dinormalisasi 0..1)
    mode "hybrid"  : alpha*vektor_norm + (1-alpha)*keyword_norm
    """
    mode = mode if mode in SEARCH_MODES else "hybrid"
    alpha = max(0.0, min(1.0, float(alpha)))
    vec = [_cosine(query_vec or [], v) for v in doc_vecs] if query_vec else [0.0] * len(docs)
    kw = _bm25(query, docs)
    if mode == "vector":
        combined = vec
    elif mode == "keyword":
        combined = _normalize(kw)
    else:
        vn, kn = _normalize(vec), _normalize(kw)
        combined = [alpha * v + (1 - alpha) * k for v, k in zip(vn, kn)]
    order = sorted(range(len(docs)), key=lambda i: combined[i], reverse=True)
    return [(i, round(combined[i], 6)) for i in order]


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _hash_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Embedding bag-of-words deterministik (fallback tanpa jaringan)."""
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest()[:8], 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


#: Mode embedding: "auto" (default) | "gemini" | "hash".
#: "hash" memaksa embedding lokal -> uji/CI sepenuhnya offline & cepat.
_EMBED_MODE = os.getenv("VECTOR_EMBED_MODE", "auto").strip().lower()

#: PEMUTUS SIRKUIT. `memory_manager.generate_embedding` memanggil jaringan
#: (timeout 8s). Pada 1000 chunk itu berarti 1000 panggilan jaringan. Bila
#: panggilan PERTAMA gagal (offline/kunci habis), kita jatuh ke hash untuk
#: SELURUH proses — bukan mengulang timeout 8s per chunk.
_EMBED_STATE = {"gemini_ok": True}


def embed(text: str) -> tuple[list[float], str]:
    """Embedding + label backend. Coba Gemini, jatuh ke hash bila gagal."""
    text = (text or "")[:8000]
    mode = _EMBED_MODE if _EMBED_MODE in ("auto", "gemini", "hash") else "auto"
    if mode == "hash":
        return _hash_embed(text), "hash"
    if text.strip() and (mode == "gemini" or _EMBED_STATE["gemini_ok"]):
        try:
            import memory_manager
            vec = memory_manager.generate_embedding(text)
            _EMBED_STATE["gemini_ok"] = True
            return vec, "gemini"
        except Exception:  # noqa: BLE001 - offline/tanpa kunci -> fallback
            _EMBED_STATE["gemini_ok"] = False
    return _hash_embed(text), "hash"


def reset_embed_circuit() -> None:
    """Untuk uji: buka kembali pemutus sirkuit embedding."""
    _EMBED_STATE["gemini_ok"] = True


# ---------------------------------------------------------------------------
# Backend: memori (dev/uji) & Supabase pgvector (produksi)
# ---------------------------------------------------------------------------

class _MemoryBackend:
    """Penyimpanan proses-lokal. Dipakai uji + saat DB tidak dikonfigurasi."""

    name = "memory"

    def __init__(self) -> None:
        # user_id -> collection -> doc_id -> {meta, chunks:[{idx,text,vec}]}
        self._data: dict[str, dict[str, dict[str, dict]]] = {}

    def insert(self, user_id: str, collection: str, doc_id: str,
               title: str, chunks: list[str], vecs: list[list[float]],
               metadata: dict) -> int:
        store = self._data.setdefault(user_id, {}).setdefault(collection, {})
        store[doc_id] = {
            "title": title, "metadata": metadata,
            "chunks": [{"idx": i, "text": c, "vec": v}
                       for i, (c, v) in enumerate(zip(chunks, vecs))],
        }
        return len(chunks)

    def query(self, user_id: str, collection: str, query: str,
              query_vec: list[float], top_k: int, mode: str,
              alpha: float, filter: Optional[dict]) -> list[dict]:
        store = self._data.get(user_id, {}).get(collection, {})
        rows: list[dict] = []
        for doc_id, doc in store.items():
            if filter and not _meta_match(doc.get("metadata") or {}, filter):
                continue
            for ch in doc["chunks"]:
                rows.append({"document_id": doc_id, "chunk_index": ch["idx"],
                             "content": ch["text"], "vec": ch["vec"],
                             "title": doc.get("title", ""),
                             "metadata": doc.get("metadata") or {}})
        if not rows:
            return []
        docs = [r["content"] for r in rows]
        vecs = [r["vec"] for r in rows]
        ranked = rank(query, docs, vecs, query_vec, mode, alpha)[:top_k]
        return [{"document_id": rows[i]["document_id"],
                 "chunk_index": rows[i]["chunk_index"],
                 "content": rows[i]["content"],
                 "title": rows[i]["title"],
                 "metadata": rows[i]["metadata"],
                 "score": score,
                 # `similarity` = kosinus mentah (interpretable walau hanya 1
                 # hasil, di mana skor ternormalisasi bisa jadi 0).
                 "similarity": round(_cosine(query_vec, rows[i]["vec"]), 4)}
                for i, score in ranked]

    def delete(self, user_id: str, collection: str, doc_id: str) -> bool:
        store = self._data.get(user_id, {}).get(collection, {})
        return store.pop(doc_id, None) is not None

    def stats(self, user_id: str) -> dict:
        cols = self._data.get(user_id, {})
        return {"collections": len(cols),
                "documents": sum(len(c) for c in cols.values()),
                "chunks": sum(len(d["chunks"]) for c in cols.values()
                              for d in c.values())}


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_USER_UUID_CACHE: dict[str, str] = {}


def resolve_user_uuid(user_key: str) -> str:
    """Petakan email -> uuid `public.users.id` (kolom rag_*.user_id = uuid).

    Bila `user_key` sudah uuid, dikembalikan apa adanya. Hasil di-cache per
    proses supaya tidak ada SELECT berulang pada tiap node vector_store.
    """
    user_key = str(user_key or "")
    if _UUID_RE.match(user_key):
        return user_key
    if user_key in _USER_UUID_CACHE:
        return _USER_UUID_CACHE[user_key]
    uid = ""
    try:
        row = db.get_or_create_user(user_key)
        uid = str((row or {}).get("id") or "")
    except Exception:  # noqa: BLE001 - biar pemanggil melihat galat asli
        uid = ""
    _USER_UUID_CACHE[user_key] = uid
    return uid


class _SupabaseBackend:
    """Supabase pgvector. Butuh migrasi migrations/2026_rag_vector_store.sql."""

    name = "supabase"

    def _t(self):
        return db.get_write_client()

    def insert(self, user_id: str, collection: str, doc_id: str,
               title: str, chunks: list[str], vecs: list[list[float]],
               metadata: dict) -> int:
        c = self._t()
        uid = resolve_user_uuid(user_id)
        if not uid:
            raise VectorStoreUnavailable(
                f"user_id tidak bisa dipetakan ke uuid untuk {user_id!r}")
        c.table("rag_documents").insert({
            "id": doc_id, "user_id": uid, "collection": collection,
            "title": title, "metadata": metadata or {},
        }).execute()
        rows = [{"id": str(uuid.uuid4()), "document_id": doc_id,
                 "user_id": uid, "collection": collection,
                 "chunk_index": i, "content": ch, "embedding": v,
                 "metadata": metadata or {}}
                for i, (ch, v) in enumerate(zip(chunks, vecs))]
        if rows:
            c.table("rag_chunks").insert(rows).execute()
        return len(rows)

    def query(self, user_id: str, collection: str, query: str,
              query_vec: list[float], top_k: int, mode: str,
              alpha: float, filter: Optional[dict]) -> list[dict]:
        c = self._t()
        uid = resolve_user_uuid(user_id)
        if not uid:
            return []
        # Ambil kandidat (difilter user_id + collection) lalu ranking di sini
        # supaya hybrid/BM25 memakai kode yang SAMA dengan backend memori.
        q = (c.table("rag_chunks")
             .select("id,document_id,chunk_index,content,embedding,metadata")
             .eq("user_id", uid).eq("collection", collection))
        if filter:
            q = q.contains("metadata", filter)
        res = q.limit(2000).execute()
        rows = res.data or []
        if not rows:
            return []
        docs = [r.get("content") or "" for r in rows]
        vecs = [r.get("embedding") or [] for r in rows]
        ranked = rank(query, docs, vecs, query_vec, mode, alpha)[:top_k]
        return [{"document_id": rows[i]["document_id"],
                 "chunk_index": rows[i].get("chunk_index"),
                 "content": rows[i].get("content"),
                 "title": "",
                 "metadata": rows[i].get("metadata") or {},
                 "score": score,
                 "similarity": round(_cosine(query_vec, vecs[i]), 4)}
                for i, score in ranked]

    def delete(self, user_id: str, collection: str, doc_id: str) -> bool:
        c = self._t()
        uid = resolve_user_uuid(user_id)
        if not uid:
            return False
        c.table("rag_chunks").delete().eq("user_id", uid).eq(
            "document_id", doc_id).execute()
        res = (c.table("rag_documents").delete().eq("user_id", uid)
               .eq("id", doc_id).execute())
        return bool(res.data)

    def stats(self, user_id: str) -> dict:
        c = self._t()
        uid = resolve_user_uuid(user_id)
        if not uid:
            return {"collections": None, "documents": 0, "chunks": 0}
        docs = (c.table("rag_documents").select("id", count="exact")
                .eq("user_id", uid).execute())
        chunks = (c.table("rag_chunks").select("id", count="exact")
                  .eq("user_id", uid).execute())
        return {"collections": None,
                "documents": getattr(docs, "count", None) or len(docs.data or []),
                "chunks": getattr(chunks, "count", None) or len(chunks.data or [])}


def _meta_match(meta: dict, flt: dict) -> bool:
    for k, v in flt.items():
        if str(meta.get(k)) != str(v):
            return False
    return True


def _backend():
    if db.is_configured():
        try:
            return _SupabaseBackend()
        except Exception:  # noqa: BLE001
            pass
    return _MemoryBackend()


# ---------------------------------------------------------------------------
# API publik
# ---------------------------------------------------------------------------

class VectorStore:
    """Vector store per user. Semua method sync (pola memory_manager)."""

    def __init__(self, user_id: str, backend: Optional[Any] = None):
        self.user_id = str(user_id or "anonymous")
        self._backend = backend or _backend()

    def insert(self, collection: str, document: str,
               metadata: Optional[dict] = None, title: str = "",
               chunk_size: int = DEFAULT_CHUNK_SIZE,
               chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> dict:
        document = document or ""
        chunks = chunk_text(document, chunk_size, chunk_overlap)
        if not chunks:
            return {"status": "error", "error": "dokumen kosong"}
        vecs, emb_backend = [], "hash"
        for ch in chunks:
            v, emb_backend = embed(ch)
            vecs.append(v)
        doc_id = str(uuid.uuid4())
        n = self._backend.insert(self.user_id, collection or "default",
                                 doc_id, title or "", chunks, vecs,
                                 metadata or {})
        return {"status": "success", "operation": "insert",
                "document_id": doc_id, "collection": collection or "default",
                "chunks": n, "chars": len(document),
                "embedding_backend": emb_backend,
                "backend": self._backend.name}

    def query(self, collection: str, query: str, top_k: int = DEFAULT_TOP_K,
              search_mode: str = "hybrid", alpha: float = 0.5,
              filter: Optional[dict] = None) -> dict:
        query = query or ""
        if not query.strip():
            return {"status": "error", "error": "kueri kosong"}
        top_k = max(1, min(int(top_k or DEFAULT_TOP_K), MAX_TOP_K))
        qvec, emb_backend = embed(query)
        rows = self._backend.query(self.user_id, collection or "default",
                                   query, qvec, top_k, search_mode,
                                   alpha, filter)
        return {"status": "success", "operation": "query",
                "collection": collection or "default", "query": query,
                "search_mode": search_mode, "results": rows,
                "count": len(rows), "embedding_backend": emb_backend,
                "backend": self._backend.name}

    def delete(self, collection: str, document_id: str) -> dict:
        ok = self._backend.delete(self.user_id, collection or "default",
                                  document_id)
        return {"status": "success" if ok else "error",
                "operation": "delete", "document_id": document_id,
                "deleted": ok,
                "error": None if ok else "dokumen tidak ditemukan"}

    def stats(self) -> dict:
        return {"status": "success", **self._backend.stats(self.user_id),
                "backend": self._backend.name}


def run_config(cfg: dict, user_id: str, text_from_input: str = "",
               backend: Optional[Any] = None) -> dict:
    """Entry point execution_engine: pilih operasi dari config node."""
    op = str(cfg.get("operation") or "insert").strip().lower()
    if op not in OPERATIONS:
        op = "insert"
    collection = str(cfg.get("collection") or "default")
    t0 = time.perf_counter()
    try:
        return _run_op(store=VectorStore(user_id, backend=backend), op=op,
                       cfg=cfg, collection=collection,
                       text_from_input=text_from_input, t0=t0)
    except Exception as exc:  # noqa: BLE001 - laporkan jujur, jangan crash
        msg = str(exc)
        if "PGRST205" in msg or "schema cache" in msg:
            msg = ("Tabel RAG belum ada. Terapkan migrasi "
                   "migrations/2026_rag_vector_store.sql "
                   "(jalankan _ddl_rag.py).")
        return {"status": "error", "operation": op,
                "error": f"{type(exc).__name__}: {msg}",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 3)}


def _run_op(*, store: "VectorStore", op: str, cfg: dict, collection: str,
            text_from_input: str, t0: float) -> dict:
    if op == "insert":
        doc = cfg.get("document")
        if doc is None or str(doc).strip() == "":
            doc = text_from_input
        meta = cfg.get("metadata")
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        res = store.insert(collection, str(doc or ""),
                           metadata=meta if isinstance(meta, dict) else {},
                           title=str(cfg.get("title") or ""),
                           chunk_size=_int(cfg.get("chunk_size"),
                                           DEFAULT_CHUNK_SIZE),
                           chunk_overlap=_int(cfg.get("chunk_overlap"),
                                              DEFAULT_CHUNK_OVERLAP))
    elif op == "query":
        q = cfg.get("query")
        if q is None or str(q).strip() == "":
            q = text_from_input
        flt = cfg.get("filter")
        if isinstance(flt, str):
            import json
            try:
                flt = json.loads(flt)
            except (ValueError, TypeError):
                flt = None
        res = store.query(collection, str(q or ""),
                          top_k=_int(cfg.get("top_k"), DEFAULT_TOP_K),
                          search_mode=str(cfg.get("search_mode") or "hybrid"),
                          alpha=_float(cfg.get("alpha"), 0.5),
                          filter=flt if isinstance(flt, dict) else None)
    else:
        res = store.delete(collection, str(cfg.get("document_id")
                                           or cfg.get("query") or ""))
    res["duration_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return res


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


__all__ = [
    "EMBED_DIM", "DEFAULT_CHUNK_SIZE", "DEFAULT_CHUNK_OVERLAP", "SEARCH_MODES",
    "OPERATIONS", "VectorStore", "VectorStoreUnavailable",
    "chunk_text", "rank", "embed", "reset_embed_circuit", "run_config",
]
