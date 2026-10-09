-- ===========================================================================
-- Fitur #8 — Distributed tracing (OpenTelemetry / LangSmith)
-- 9 Okt 2026
--
-- Menyimpan konfigurasi tracing per-pemilik (padanan Settings > OpenTelemetry
-- di n8n 2.27.0) + cache konteks trace per-eksekusi supaya propagasi antar
-- proses (worker/webhook) tetap bekerja — sama seperti n8n yang membaca
-- parent trace context dari database di queue mode.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1) Konfigurasi tracing per-pemilik
-- ---------------------------------------------------------------------------
create table if not exists public.tracing_config (
    owner           uuid primary key,
    config          jsonb       not null default '{}'::jsonb,
    -- enabled, endpoint, protocol, headers, path, service_name,
    -- service_version, instance_role, sample_rate, production_only,
    -- include_node_spans, inject_traceparent, agents_tracing_enabled
    enabled         boolean     not null default false,
    endpoint        text        not null default '',
    protocol        text        not null default 'http/protobuf',
    sample_rate     numeric(4,3) not null default 1.000,
    updated_by      text        not null default '',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint tracing_config_protocol_chk
        check (protocol in ('http/protobuf', 'grpc')),
    constraint tracing_config_sample_chk
        check (sample_rate >= 0 and sample_rate <= 1)
);

comment on table public.tracing_config is
    'Fitur #8: konfigurasi OTLP tracing per-pemilik (endpoint, sampling, opsi span).';
comment on column public.tracing_config.config is
    'Konfigurasi lengkap; nilai rahasia (headers) TIDAK disimpan di kolom ini — lihat tracing_config_secrets.';

-- ---------------------------------------------------------------------------
-- 2) Rahasia header OTLP (mis. x-api-key LangSmith) — tabel terpisah
--    supaya tidak ikut terbaca endpoint konfigurasi biasa.
-- ---------------------------------------------------------------------------
create table if not exists public.tracing_config_secrets (
    owner           uuid primary key
                    references public.tracing_config(owner) on delete cascade,
    headers_enc     text        not null default '',
    -- Terenkripsi Fernet (vault). TIDAK pernah dikirim ke klien.
    updated_at      timestamptz not null default now()
);

comment on table public.tracing_config_secrets is
    'Fitur #8: header OTLP (kunci API backend) terenkripsi di rest. Tanpa policy RLS apa pun untuk klien.';

-- ---------------------------------------------------------------------------
-- 3) Konteks trace per-eksekusi (propagasi lintas proses, gaya n8n)
-- ---------------------------------------------------------------------------
create table if not exists public.execution_trace_context (
    execution_id    text primary key,
    workflow_id     text,
    trace_id        char(32)    not null,
    span_id         char(16)    not null,
    parent_span_id  char(16),
    traceparent     text        not null default '',
    span_links      jsonb       not null default '[]'::jsonb,
    -- [{trace_id, span_id, reason}] untuk resume setelah `wait`
    sampled         boolean     not null default true,
    mode            text        not null default 'manual',
    reconstructed   boolean     not null default false,
    created_at      timestamptz not null default now(),
    ended_at        timestamptz,
    constraint execution_trace_ctx_trace_chk
        check (trace_id ~ '^[0-9a-f]{32}$' and trace_id <> repeat('0', 32)),
    constraint execution_trace_ctx_span_chk
        check (span_id ~ '^[0-9a-f]{16}$' and span_id <> repeat('0', 16))
);

create index if not exists execution_trace_ctx_workflow_idx
    on public.execution_trace_context (workflow_id, created_at desc);
create index if not exists execution_trace_ctx_trace_idx
    on public.execution_trace_context (trace_id);
create index if not exists execution_trace_ctx_open_idx
    on public.execution_trace_context (ended_at)
    where ended_at is null;

comment on table public.execution_trace_context is
    'Fitur #8: konteks span root per-eksekusi, dibaca worker/proses lain agar span tetap satu trace (n8n queue mode).';

-- ---------------------------------------------------------------------------
-- 4) Ringkasan span yang diekspor (untuk halaman jejak di UI)
-- ---------------------------------------------------------------------------
create table if not exists public.tracing_spans (
    id              bigserial primary key,
    owner           uuid        not null,
    execution_id    text,
    workflow_id     text,
    trace_id        char(32)    not null,
    span_id         char(16)    not null,
    parent_span_id  char(16),
    name            text        not null,
    kind            smallint    not null default 1,
    status_code     smallint    not null default 0,
    duration_ms     numeric(12,3),
    attributes      jsonb       not null default '{}'::jsonb,
    links           jsonb       not null default '[]'::jsonb,
    exported        boolean     not null default false,
    export_error    text        not null default '',
    started_at      timestamptz not null default now(),
    ended_at        timestamptz,
    unique (trace_id, span_id)
);

create index if not exists tracing_spans_owner_idx
    on public.tracing_spans (owner, started_at desc);
create index if not exists tracing_spans_trace_idx
    on public.tracing_spans (trace_id);
create index if not exists tracing_spans_execution_idx
    on public.tracing_spans (execution_id);
create index if not exists tracing_spans_attrs_idx
    on public.tracing_spans using gin (attributes);

comment on table public.tracing_spans is
    'Fitur #8: ringkasan span untuk UI. Sumber kebenaran tetap backend OTLP.';

-- ---------------------------------------------------------------------------
-- 5) Trigger updated_at
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end $$;

drop trigger if exists tracing_config_touch on public.tracing_config;
create trigger tracing_config_touch
    before update on public.tracing_config
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- 6) Row Level Security
--    tracing_config + tracing_spans: hanya pemilik.
--    tracing_config_secrets: TIDAK ada policy -> tidak dapat diakses klien.
--    execution_trace_context: hanya service role (tanpa policy klien).
-- ---------------------------------------------------------------------------
alter table public.tracing_config         enable row level security;
alter table public.tracing_config_secrets enable row level security;
alter table public.tracing_spans          enable row level security;
alter table public.execution_trace_context enable row level security;

drop policy if exists tracing_config_owner_all on public.tracing_config;
create policy tracing_config_owner_all on public.tracing_config
    for all
    using (auth.uid() = owner)
    with check (auth.uid() = owner);

drop policy if exists tracing_spans_owner_read on public.tracing_spans;
create policy tracing_spans_owner_read on public.tracing_spans
    for select
    using (auth.uid() = owner);

-- tracing_config_secrets: sengaja tanpa policy (service role saja).
-- execution_trace_context: sengaja tanpa policy (service role saja).

-- ---------------------------------------------------------------------------
-- 7) Hak akses
-- ---------------------------------------------------------------------------
grant select, insert, update, delete on public.tracing_config to authenticated;
grant select, insert, update, delete on public.tracing_spans  to authenticated;
grant usage, select on sequence public.tracing_spans_id_seq to authenticated;
