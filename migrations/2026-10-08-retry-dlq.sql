-- ============================================================================
-- migrations/2026-10-08-retry-dlq.sql
-- Fitur #3 — RETRY + EXPONENTIAL BACKOFF + DLQ + CIRCUIT BREAKER
-- ============================================================================
-- Tujuan: node workflow yang gagal TIDAK hilang begitu saja. Ia dicoba ulang
-- dengan backoff, dan bila tetap gagal masuk Dead Letter Queue (DLQ) supaya
-- bisa diperiksa / dijalankan ulang secara manual.
--
-- Riset (docs/fitur-03-retry-dlq.md):
--   tenacity 9.2.1  (update 7 Okt 2026) -> retry + backoff + jitter
--   pybreaker 1.4.1                     -> circuit breaker
--   keduanya diverifikasi API + perilakunya, bukan diasumsikan.
--
-- CARA JALANKAN: Supabase Dashboard -> SQL Editor -> tempel -> Run. Idempoten.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. DLQ — satu baris per kegagalan node yang menyerah
-- ---------------------------------------------------------------------------
create table if not exists public.dead_letter_queue (
    id            uuid        primary key default gen_random_uuid(),
    execution_id  uuid        not null references public.executions(id) on delete cascade,
    workflow_id   uuid        references public.workflows(id) on delete cascade,
    user_id       uuid        not null,
    step_id       text        not null,
    node_type     text,
    attempts      integer     not null default 0,
    last_error    text,
    payload       jsonb,
    status        text        not null default 'pending',   -- pending|retried|discarded
    retried_at    timestamptz,
    retried_execution_id uuid,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

comment on table public.dead_letter_queue is
  'Dead Letter Queue (Fitur #3): node yang gagal setelah semua retry dicoba. '
  'Bisa dilihat, dijalankan ulang, atau dibuang secara manual.';

create index if not exists idx_dlq_user_status
    on public.dead_letter_queue (user_id, status, created_at desc);
create index if not exists idx_dlq_execution
    on public.dead_letter_queue (execution_id);

-- Cegah node yang sama masuk DLQ dua kali dalam satu eksekusi.
-- CATATAN (BUG 42P10, 8 Okt): versi pertama memakai PARTIAL unique index
-- (`where execution_id is not null`). Postgres MENOLAK index parsial sebagai
-- target `ON CONFLICT (execution_id, step_id)` -> error 42P10
-- "there is no unique or exclusion constraint matching the ON CONFLICT
-- specification", sehingga upsert DLQ selalu gagal secara senyap
-- (11 tes lolos, 5 gagal, tanpa error yang terlihat).
-- Perbaikan: constraint UNIK BIASA + execution_id NOT NULL.
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'dlq_exec_step_key'
          and conrelid = 'public.dead_letter_queue'::regclass
    ) then
        alter table public.dead_letter_queue
            add constraint dlq_exec_step_key unique (execution_id, step_id);
    end if;
end $$;

-- bersihkan index parsial lama bila ada (digantikan constraint di atas)
drop index if exists public.uq_dlq_exec_step;

-- ---------------------------------------------------------------------------
-- 2. State circuit breaker — disimpan supaya tahan restart
--    (in-memory saja tidak cukup: Railway restart -> sirkuit "lupa")
-- ---------------------------------------------------------------------------
create table if not exists public.circuit_breakers (
    name            text        primary key,
    state           text        not null default 'closed',  -- closed|open|half_open
    fail_count      integer     not null default 0,
    fail_max        integer     not null default 5,
    reset_timeout   integer     not null default 60,
    opened_at       timestamptz,
    last_failure_at timestamptz,
    last_error      text,
    updated_at      timestamptz not null default now()
);

comment on table public.circuit_breakers is
  'State circuit breaker persisten (Fitur #3) — tahan restart/deploy.';

-- ---------------------------------------------------------------------------
-- 3. RLS — user hanya melihat DLQ miliknya
-- ---------------------------------------------------------------------------
alter table public.dead_letter_queue enable row level security;

drop policy if exists dlq_owner_read on public.dead_letter_queue;
create policy dlq_owner_read on public.dead_letter_queue
    for select using (user_id = auth.uid());

drop policy if exists dlq_owner_update on public.dead_letter_queue;
create policy dlq_owner_update on public.dead_letter_queue
    for update using (user_id = auth.uid());

-- circuit_breakers hanya untuk service role (tanpa policy = tertutup untuk user)
alter table public.circuit_breakers enable row level security;

-- ---------------------------------------------------------------------------
-- 4. RPC: klaim item DLQ untuk dijalankan ulang secara atomik
--    (anti dobel-retry bila dua admin menekan tombol bersamaan)
-- ---------------------------------------------------------------------------
-- DROP dulu: Postgres menolak CREATE OR REPLACE yang mengubah tipe kembalian
-- (fungsi lama returns dead_letter_queue, yang baru returns jsonb).
drop function if exists public.claim_dlq_item(uuid, uuid);

create or replace function public.claim_dlq_item(p_id uuid, p_user_id uuid)
returns jsonb
language sql
security definer
set search_path = public
as $function$
    with klaim as (
        update public.dead_letter_queue d
           set status = 'retried',
               retried_at = now(),
               updated_at = now()
         where d.id = p_id
           and d.user_id = p_user_id      -- WAJIB: cegah akses lintas-user
           and d.status = 'pending'
        returning d.*
    )
    select to_jsonb(k) from klaim k;
$function$;

comment on function public.claim_dlq_item(uuid, uuid) is
  'Klaim satu item DLQ milik user untuk dijalankan ulang (Fitur #3). '
  'status harus pending -> idempoten, anti dobel-retry. '
  'Mengembalikan jsonb ATAU NULL (BUKAN baris berisi NULL semua) — '
  'penting: `returns public.dead_letter_queue` membuat PostgREST '
  'mengembalikan dict semua-NULL saat tidak ada baris cocok, dan dict itu '
  'truthy di Python -> user asing tampak berhasil mengklaim (BUG keamanan '
  '8 Okt). to_jsonb() menghilangkan ambiguitas itu.';

revoke all on function public.claim_dlq_item(uuid, uuid) from public;
grant execute on function public.claim_dlq_item(uuid, uuid) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 5. RPC: statistik DLQ per user (untuk dashboard)
-- ---------------------------------------------------------------------------
create or replace function public.dlq_stats(p_user_id uuid)
returns table (status text, jumlah bigint)
language sql
security definer
set search_path = public
as $function$
    select d.status, count(*)::bigint
      from public.dead_letter_queue d
     where d.user_id = p_user_id
     group by d.status;
$function$;

revoke all on function public.dlq_stats(uuid) from public;
grant execute on function public.dlq_stats(uuid) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- VERIFIKASI:
--   select column_name from information_schema.columns
--    where table_name='dead_letter_queue' order by ordinal_position;
--   select public.dlq_stats('00000000-0000-0000-0000-000000000000'::uuid);
-- ----------------------------------------------------------------------------
