-- FASE 1 + FASE 2 — Persistensi ledger aktivasi & kesehatan connector ke DB
--
-- Masalah yang diselesaikan:
--   `connector_activation.json` ada di .gitignore:126 -> tidak pernah ikut
--   deploy -> `coverage()['executable']` selalu reset ke 23 di setiap
--   lingkungan baru. Ledger harus hidup di DB, bukan di berkas.
--
-- Tabel:
--   1. connector_activation  -> pengganti connector_activation.json
--   2. connector_health      -> hasil probe live (FASE 2), untuk cron (FASE 6)
--
-- Catatan skema (diukur, tidak diasumsikan):
--   * `id` connector BUKAN uuid (mis. 'glama-connector/g3mugvr4is') -> text.
--   * RLS: katalog connector bersifat publik/global (tenant_scope 'public'),
--     jadi baris tidak dimiliki per-user. Tabel ini memakai policy
--     `using (true)` untuk SELECT, dan hanya service_role yang menulis.

-- ============================================================
-- 1. connector_activation
-- ============================================================
create table if not exists public.connector_activation (
    connector_id    text primary key,
    transport       text,
    endpoint_url    text,
    call_verified   boolean not null default false,
    runtime_verified boolean not null default true,
    source          text,
    activated_at    timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists ix_connector_activation_verified
    on public.connector_activation (runtime_verified);
create index if not exists ix_connector_activation_transport
    on public.connector_activation (transport);

alter table public.connector_activation enable row level security;

drop policy if exists connector_activation_select_all on public.connector_activation;
create policy connector_activation_select_all
    on public.connector_activation
    for select
    using (true);

-- ============================================================
-- 2. connector_health  (FASE 2 — probe live deterministik)
-- ============================================================
create table if not exists public.connector_health (
    connector_id     text primary key,
    endpoint_url     text,
    verdict          text not null,          -- ALIVE | AUTH | DEAD | UNKNOWN
    http_status      integer,
    tools_count      integer,
    latency_ms       integer,
    error            text,
    prober           text,                   -- 'mcp-wringer' | 'catalog-probe'
    raw              jsonb,
    checked_at       timestamptz not null default now()
);

create index if not exists ix_connector_health_verdict
    on public.connector_health (verdict);
create index if not exists ix_connector_health_checked
    on public.connector_health (checked_at desc);

alter table public.connector_health enable row level security;

drop policy if exists connector_health_select_all on public.connector_health;
create policy connector_health_select_all
    on public.connector_health
    for select
    using (true);

-- Trigger updated_at untuk connector_activation
create or replace function public.touch_connector_activation()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_touch_connector_activation on public.connector_activation;
create trigger trg_touch_connector_activation
    before update on public.connector_activation
    for each row execute function public.touch_connector_activation();

-- Verifikasi cepat
select 'connector_activation' as tabel, count(*) as baris from public.connector_activation
union all
select 'connector_health', count(*) from public.connector_health;
