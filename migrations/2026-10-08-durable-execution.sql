-- ============================================================================
-- migrations/2026-10-08-durable-execution.sql
-- Fitur #2 — DURABLE EXECUTION
-- ============================================================================
-- LATAR BELAKANG (terverifikasi 8 Okt 2026):
--   Tabel `executions` saat ini HANYA punya 6 kolom:
--     id, workflow_id, status, result, created_at, updated_at
--   Tidak ada tempat untuk menyimpan progres antar-node, sehingga eksekusi
--   yang mati di tengah (deploy/restart Railway) HILANG dan harus diulang
--   dari nol — termasuk mengulang efek samping yang sudah terjadi.
--
-- RISET (docs/fitur-02-durable-execution.md):
--   dbos 3.2.0 (MIT, 524 rilis) terbukti melakukan resume-dari-checkpoint
--   terhadap Postgres Supabase (uji crash `os._exit(137)` -> LANGKAH-1/2
--   TIDAK diulang). Namun semantiknya diterapkan pada SKEMA KATALIR sendiri
--   supaya engine yang sudah jalan tidak diganti total menjelang launch.
--
-- CARA JALANKAN: Supabase Dashboard -> SQL Editor -> tempel -> Run.
--   Idempoten, aman dijalankan berulang.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Kolom checkpoint pada `executions`
-- ---------------------------------------------------------------------------
alter table public.executions
    add column if not exists state            jsonb       not null default '{}'::jsonb,
    add column if not exists current_step_id  text,
    add column if not exists idempotency_key  text,
    add column if not exists heartbeat_at     timestamptz,
    add column if not exists retry_count      integer     not null default 0,
    add column if not exists resumed_at       timestamptz,
    add column if not exists waiting_for      text,
    add column if not exists parent_execution_id uuid;

comment on column public.executions.state is
  'Checkpoint durable: {node_id: hasil} — sumber replay saat resume (Fitur #2)';
comment on column public.executions.current_step_id is
  'Node terakhir yang sedang/selesai dikerjakan — titik lanjut saat resume';
comment on column public.executions.idempotency_key is
  'Kunci idempotensi eksekusi (mis. dari cron run-key) — cegah eksekusi ganda';
comment on column public.executions.heartbeat_at is
  'Detak terakhir; selisih > 5 menit menandai eksekusi macet -> dipulihkan';
comment on column public.executions.waiting_for is
  'Sinyal eksternal yang ditunggu (mis. approval) — kosong bila tidak menunggu';

-- ---------------------------------------------------------------------------
-- 2. Idempotency: satu eksekusi per (workflow, kunci). Partial index supaya
--    baris tanpa kunci (NULL) tidak saling bentrok.
-- ---------------------------------------------------------------------------
create unique index if not exists uq_executions_idem
    on public.executions (workflow_id, idempotency_key)
    where idempotency_key is not null;

-- ---------------------------------------------------------------------------
-- 3. Pencarian eksekusi macet (pemulihan saat startup)
-- ---------------------------------------------------------------------------
create index if not exists idx_executions_stuck
    on public.executions (status, heartbeat_at)
    where status in ('running', 'pending');

create index if not exists idx_executions_waiting
    on public.executions (status, waiting_for)
    where waiting_for is not null;

-- ---------------------------------------------------------------------------
-- 4. Log per-node — sumber replay
--    unique (execution_id, step_id) = jaminan "satu node dijalankan sekali".
-- ---------------------------------------------------------------------------
create table if not exists public.execution_steps (
    id            uuid        primary key default gen_random_uuid(),
    execution_id  uuid        not null references public.executions(id) on delete cascade,
    step_id       text        not null,
    node_type     text,
    status        text        not null default 'running',  -- running|success|failed|skipped
    attempt       integer     not null default 1,
    input         jsonb,
    output        jsonb,
    error         text,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    unique (execution_id, step_id)
);

comment on table public.execution_steps is
  'Log per-node untuk replay durable (Fitur #2). unique(execution_id, step_id) '
  'menjamin sebuah node tidak pernah dijalankan dua kali pada eksekusi sama.';

create index if not exists idx_exec_steps_exec
    on public.execution_steps (execution_id, started_at);

-- ---------------------------------------------------------------------------
-- 5. RLS: pemilik eksekusi (lewat workflow) boleh membaca step-nya
-- ---------------------------------------------------------------------------
alter table public.execution_steps enable row level security;

drop policy if exists exec_steps_owner_read on public.execution_steps;
create policy exec_steps_owner_read on public.execution_steps
    for select using (
        exists (
            select 1 from public.executions e
            join public.workflows w on w.id = e.workflow_id
            where e.id = execution_steps.execution_id
              and w.user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- 6. RPC: klaim eksekusi macet secara atomik (anti dobel-pemulihan)
--    Dipanggil dengan now() - interval '5 minutes'.
-- ---------------------------------------------------------------------------
create or replace function public.claim_stuck_executions(
    stale_seconds integer default 300,
    max_rows      integer default 50
)
returns setof public.executions
language sql
security definer
set search_path = public
as $function$
    with kandidat as (
        select e.id
        from public.executions e
        where e.status in ('running', 'pending')
          and e.heartbeat_at is not null
          and e.heartbeat_at < now() - make_interval(secs => stale_seconds)
          and e.waiting_for is null          -- yang menunggu sinyal JANGAN diambil
        order by e.heartbeat_at
        limit greatest(least(max_rows, 200), 1)
        for update skip locked              -- anti dobel-pemulihan antar replika
    )
    update public.executions e
       set status = 'interrupted',
           resumed_at = now(),
           updated_at = now()
      from kandidat k
     where e.id = k.id
    returning e.*;
$function$;

comment on function public.claim_stuck_executions(integer, integer) is
  'Klaim eksekusi macet secara atomik untuk dipulihkan (Fitur #2). '
  'for update skip locked mencegah dua replika memulihkan baris yang sama.';

revoke all on function public.claim_stuck_executions(integer, integer) from public;
grant execute on function public.claim_stuck_executions(integer, integer)
    to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- VERIFIKASI:
--   select column_name from information_schema.columns
--    where table_name='executions' order by ordinal_position;
--   -- harus memuat: state, current_step_id, idempotency_key,
--   --               heartbeat_at, retry_count, resumed_at, waiting_for
--
--   select public.claim_stuck_executions(300, 10);   -- tabel kosong = wajar
-- ----------------------------------------------------------------------------
