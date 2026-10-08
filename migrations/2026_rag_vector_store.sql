-- migrations/2026_rag_vector_store.sql
-- Fitur #2: RAG / Vector Store (8 Okt 2026)
-- ======================================================================
-- Tabel dokumen + chunk untuk pipeline RAG (n8n parity: Vector Store +
-- Document Loader + Embeddings). Embedding Gemini 1536-dim, sama dengan
-- memory_manager.py (gemini-embedding-001, output_dimensionality=1536).
--
-- Isolasi multi-tenant DUA LAPIS:
--   1. RLS: user hanya melihat baris user_id = auth.uid().
--   2. Aplikasi: SETIAP query di vector_store.py memfilter user_id.
-- ======================================================================

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Dokumen (induk). Satu baris per dokumen yang di-ingest.
-- ---------------------------------------------------------------------------
create table if not exists rag_documents (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null,
    collection  text not null default 'default',
    title       text default '',
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists rag_documents_user_col_idx
    on rag_documents (user_id, collection);

-- ---------------------------------------------------------------------------
-- Chunk (anak). Vektor 1536-dim + konten + metadata (untuk filter).
-- ---------------------------------------------------------------------------
create table if not exists rag_chunks (
    id          uuid primary key default gen_random_uuid(),
    document_id uuid not null references rag_documents(id) on delete cascade,
    user_id     uuid not null,
    collection  text not null default 'default',
    chunk_index int  not null default 0,
    content     text not null,
    embedding   vector(1536),
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists rag_chunks_user_col_idx
    on rag_chunks (user_id, collection);
create index if not exists rag_chunks_doc_idx
    on rag_chunks (document_id);

-- HNSW (cosine) — pilihan 2026 untuk recall tinggi & latensi rendah.
create index if not exists rag_chunks_embedding_hnsw
    on rag_chunks using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
alter table rag_documents enable row level security;
alter table rag_chunks    enable row level security;

drop policy if exists rag_documents_owner on rag_documents;
create policy rag_documents_owner on rag_documents
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists rag_chunks_owner on rag_chunks;
create policy rag_chunks_owner on rag_chunks
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- RPC pencarian vektor (opsional, dipakai bila ingin push-down ke DB).
-- vector_store.py melakukan ranking di aplikasi agar hybrid/BM25 memakai
-- kode yang SAMA dengan backend memori; RPC ini disediakan untuk klien SQL.
-- ---------------------------------------------------------------------------
create or replace function match_rag_chunks(
    query_embedding vector(1536),
    match_count     int default 5,
    filter_collection text default null,
    filter_user     uuid default null
)
returns table (
    id uuid, document_id uuid, chunk_index int, content text,
    metadata jsonb, similarity float
)
language sql stable
as $$
    select c.id, c.document_id, c.chunk_index, c.content, c.metadata,
           1 - (c.embedding <=> query_embedding) as similarity
    from rag_chunks c
    where c.user_id = coalesce(filter_user, auth.uid())
      and (filter_collection is null or c.collection = filter_collection)
    order by c.embedding <=> query_embedding
    limit greatest(1, least(match_count, 50));
$$;
