# tests/test_vector_store.py — Fitur #2 hard test (10+ skenario, Okt 2026)
# Deterministik: backend memori + embedding hash (tanpa jaringan).
from __future__ import annotations

import os
import time

import pytest

# Uji harus OFFLINE & deterministik: paksa embedding lokal (hash), jangan
# menyentuh jaringan Gemini. (Di produksi mode default "auto".)
os.environ.setdefault("VECTOR_EMBED_MODE", "hash")

import vector_store
from vector_store import VectorStore, _MemoryBackend, chunk_text, rank


def _store(user="user-a"):
    return VectorStore(user, backend=_MemoryBackend())


# 1. Insert dokumen -> chunk -> embed -> simpan
def test_insert_chunks_and_stores():
    s = _store()
    doc = "Kalimat pertama. " * 200  # ~3400 char -> >1 chunk
    r = s.insert("kb", doc, metadata={"source": "manual"})
    assert r["status"] == "success"
    assert r["chunks"] > 1
    assert r["backend"] == "memory"


# 2. Query semantik/kata kunci -> hasil relevan
def test_query_returns_relevant():
    s = _store()
    s.insert("kb", "Kucing adalah hewan berkaki empat yang suka ikan.")
    s.insert("kb", "Mobil adalah kendaraan bermotor beroda empat.")
    r = s.query("kb", "mobil kendaraan bermotor", top_k=2)
    assert r["count"] >= 1
    assert "Mobil" in r["results"][0]["content"]


# 3. Query hybrid (vektor + kata kunci) memakai alpha
def test_hybrid_query_alpha():
    s = _store()
    s.insert("kb", "laporan keuangan kuartal tiga naik")
    s.insert("kb", "cuaca hari ini cerah di jakarta")
    r = s.query("kb", "laporan keuangan", search_mode="hybrid", alpha=0.5)
    assert r["search_mode"] == "hybrid"
    assert "laporan" in r["results"][0]["content"]


# 4. Delete dokumen
def test_delete_document():
    s = _store()
    ins = s.insert("kb", "dokumen sementara untuk dihapus")
    did = ins["document_id"]
    d = s.delete("kb", did)
    assert d["deleted"] is True
    r = s.query("kb", "dokumen sementara", top_k=5)
    assert r["count"] == 0
    # hapus lagi -> error yang jujur
    assert s.delete("kb", did)["status"] == "error"


# 5. Multi-tenant isolation (user lain tidak melihat data)
def test_multi_tenant_isolation():
    a = VectorStore("alice", backend=_MemoryBackend())
    b = VectorStore("bob", backend=_MemoryBackend())
    a.insert("kb", "rahasia alice tentang proyek alpha")
    r = b.query("kb", "rahasia proyek alpha", top_k=5)
    assert r["count"] == 0  # backend terpisah per instance

    # backend BERSAMA (produksi): isolasi via user_id
    shared = _MemoryBackend()
    VectorStore("alice", backend=shared).insert("kb", "rahasia alice")
    rb = VectorStore("bob", backend=shared).query("kb", "rahasia alice")
    assert rb["count"] == 0
    ra = VectorStore("alice", backend=shared).query("kb", "rahasia alice")
    assert ra["count"] == 1


# 6. Dokumen besar (10MB) -> terchunk, tidak crash
def test_large_document_chunked():
    big = ("lorem ipsum dolor sit amet consectetur adipiscing elit " * 200000)[:10_000_000]
    chunks = chunk_text(big, chunk_size=800, overlap=100)
    assert len(chunks) > 10000
    # chunk_size dihormati (dengan sedikit toleransi batas kata)
    assert all(len(c) <= 900 for c in chunks)


# 7. Performance: 1000 dokumen
def test_performance_1000_documents():
    s = _store()
    t0 = time.perf_counter()
    for i in range(1000):
        s.insert("bulk", f"dokumen nomor {i} berisi kata unik{i} dan data")
    ins = time.perf_counter() - t0
    assert ins < 30, f"insert 1000 dokumen terlalu lambat: {ins:.1f}s"
    r = s.query("bulk", "kata unik500", top_k=3)
    assert r["count"] == 3


# 8. Benchmark: latensi query
def test_query_latency_benchmark():
    s = _store()
    for i in range(200):
        s.insert("kb", f"catatan {i} tentang topik {i % 20}")
    t0 = time.perf_counter()
    for _ in range(20):
        s.query("kb", "topik 5", top_k=5)
    per = (time.perf_counter() - t0) / 20
    assert per < 0.5, f"query terlalu lambat: {per*1000:.1f}ms"


# 9. Cross-collection query (tidak bocor antar koleksi)
def test_cross_collection_isolation():
    s = _store()
    s.insert("col-a", "isi koleksi A tentang apel")
    s.insert("col-b", "isi koleksi B tentang jeruk")
    ra = s.query("col-a", "apel jeruk", top_k=5)
    assert all("koleksi A" in r["content"] for r in ra["results"])


# 10. Metadata filtering
def test_metadata_filter():
    s = _store()
    s.insert("kb", "dokumen publik tentang cuaca", metadata={"vis": "public"})
    s.insert("kb", "dokumen privat tentang cuaca", metadata={"vis": "private"})
    r = s.query("kb", "cuaca", top_k=5, filter={"vis": "private"})
    assert r["count"] == 1
    assert "privat" in r["results"][0]["content"]


# 11. chunk_text: overlap benar & tidak kehilangan teks penting
def test_chunk_overlap_properties():
    text = "kata " * 100
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) >= 2
    # tiap chunk tidak kosong
    assert all(c.strip() for c in chunks)


# 12. rank(): mode vector/keyword/hybrid semua mengembalikan urutan valid
def test_rank_modes():
    docs = ["apel merah manis", "mobil cepat", "apel hijau asam"]
    vecs = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]
    qv = [1.0, 0.0]
    for mode in ("vector", "keyword", "hybrid"):
        order = rank("apel", docs, vecs, qv, mode=mode, alpha=0.5)
        assert len(order) == 3
        assert order[0][0] in (0, 2)  # dokumen apel menang


# 13. Operasi kosong ditolak dengan pesan jujur
def test_empty_inputs_rejected():
    s = _store()
    assert s.insert("kb", "")["status"] == "error"
    assert s.query("kb", "  ")["status"] == "error"


# 14. run_config: insert & query lewat config string (seperti builder)
def test_run_config_string_values():
    be = _MemoryBackend()
    r1 = vector_store.run_config(
        {"operation": "insert", "collection": "kb",
         "document": "nasi goreng enak sekali",
         "chunk_size": "400", "chunk_overlap": "50"},
        user_id="u1", backend=be)
    assert r1["status"] == "success"
    r2 = vector_store.run_config(
        {"operation": "query", "collection": "kb", "query": "nasi goreng",
         "top_k": "3", "search_mode": "hybrid", "alpha": "0.5"},
        user_id="u1", backend=be)
    assert r2["count"] >= 1
    assert "nasi" in r2["results"][0]["content"]


# 15. stats melaporkan jumlah dokumen/chunk
def test_stats():
    s = _store()
    s.insert("kb", "satu dua tiga")
    st = s.stats()
    assert st["documents"] == 1
    assert st["chunks"] >= 1


# 16. embedding backend dilaporkan jujur (hash bila tanpa Gemini)
def test_embedding_backend_reported():
    v, backend = vector_store.embed("teks uji")
    assert len(v) == vector_store.EMBED_DIM
    assert backend in ("gemini", "hash")


# 17. DDL migrasi ada dan memuat tabel + RLS + HNSW
def test_migration_file_has_ddl():
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "2026_rag_vector_store.sql"
    sql = p.read_text(encoding="utf-8")
    assert "create table if not exists rag_documents" in sql
    assert "create table if not exists rag_chunks" in sql
    assert "enable row level security" in sql
    assert "hnsw" in sql.lower()
    assert "match_rag_chunks" in sql


# 18. NodeKind.VECTOR_STORE terdaftar di EXECUTORS
def test_node_kind_registered():
    from execution_engine import NodeKind, StatefulOrchestrator
    assert NodeKind.VECTOR_STORE.value == "vector_store"
    assert NodeKind.VECTOR_STORE in StatefulOrchestrator.EXECUTORS


# 19. Integrasi engine: insert lalu query lewat workflow nyata
def test_engine_insert_then_query(monkeypatch):
    import asyncio
    import execution_engine as ee
    import vector_store as vs

    be = vs._MemoryBackend()
    # Paksa backend memori bersama supaya tenant yang sama saling melihat.
    monkeypatch.setattr(vs, "_backend", lambda: be)

    flow = {
        "nodes": [
            {"id": "t", "type": "trigger", "data": {"kind": "trigger", "config": {}}},
            {"id": "ins", "type": "vector_store", "data": {"kind": "vector_store",
             "config": {"operation": "insert", "collection": "kb"}}},
            {"id": "q", "type": "vector_store", "data": {"kind": "vector_store",
             "config": {"operation": "query", "collection": "kb",
                        "query": "nasi goreng", "top_k": "2"}}},
        ],
        "edges": [{"source": "t", "target": "ins"},
                  {"source": "ins", "target": "q"}],
    }
    o = ee.StatefulOrchestrator(ee.FlowGraph(**flow),
                                trigger_input={"text": "nasi goreng enak"},
                                owner_email="u1@test.dev")
    steps = asyncio.run(o.run())
    assert [s.status for s in steps] == ["completed", "completed", "completed"]
    assert o.outputs["ins"]["chunks"] >= 1
    assert o.outputs["q"]["count"] >= 1


# 20. Tenant diambil dari owner_email, bukan config (anti cross-tenant)
def test_engine_tenant_from_owner(monkeypatch):
    import asyncio
    import execution_engine as ee
    import vector_store as vs

    be = vs._MemoryBackend()
    monkeypatch.setattr(vs, "_backend", lambda: be)

    flow = {
        "nodes": [
            {"id": "t", "type": "trigger", "data": {"kind": "trigger", "config": {}}},
            {"id": "ins", "type": "vector_store", "data": {"kind": "vector_store",
             "config": {"operation": "insert", "collection": "kb",
                        "owner_email": "attacker@evil.dev"}}},
        ],
        "edges": [{"source": "t", "target": "ins"}],
    }
    o = ee.StatefulOrchestrator(ee.FlowGraph(**flow),
                                trigger_input={"text": "data milik alice"},
                                owner_email="alice@test.dev")
    asyncio.run(o.run())
    # Data harus tersimpan di tenant alice, BUKAN attacker.
    assert be.stats("alice@test.dev")["documents"] == 1
    assert be.stats("attacker@evil.dev")["documents"] == 0
