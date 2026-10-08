-- ======================================================================
-- Fitur #5: Parallel Fan-Out / Fan-In
-- Migrasi idempoten. Aman dijalankan berulang.
--
-- Yang ditambahkan:
--   1. execution_branches  -> satu baris per cabang (fan-out) beserta
--      status, output, error, dan waktu. Ini yang membuat merge bisa
--      "tunggu semua" secara tahan-restart: keadaan cabang ada di DB,
--      bukan di memori proses.
--   2. executions.parallel_policy -> kebijakan merge (all_success |
--      all_settled | quorum). Disimpan agar resume tahu cara menilai.
--   3. execution_steps.timeout_seconds -> timeout per cabang.
--   4. RPC branch_summary(execution_id) -> hitung agregat cabang tanpa
--      menarik semua baris ke aplikasi (dipakai merge & endpoint status).
-- ======================================================================

-- ---------------------------------------------------------------------
-- 1. Kolom pendukung pada executions
-- ---------------------------------------------------------------------
alter table public.executions
    add column if not exists parallel_policy text not null default 'all_success';

comment on column public.executions.parallel_policy is
    'Kebijakan merge fan-in: all_success | all_settled | quorum';

-- ---------------------------------------------------------------------
-- 2. Kolom timeout pada execution_steps
-- ---------------------------------------------------------------------
alter table public.execution_steps
    add column if not exists timeout_seconds numeric;

comment on column public.execution_steps.timeout_seconds is
    'Batas detik cabang ini. NULL = pakai default global.';

-- ---------------------------------------------------------------------
-- 3. Tabel execution_branches
-- ---------------------------------------------------------------------
create table if not exists public.execution_branches (
    id              uuid        primary key default gen_random_uuid(),
    execution_id    uuid        not null references public.executions(id) on delete cascade,
    split_step_id   text        not null,     -- step node SPLIT pemilik cabang
    branch_key      text        not null,     -- identitas cabang (mis. "0", "alamat")
    merge_step_id   text,                     -- step node MERGE yang menunggu
    status          text        not null default 'pending',
                    -- pending|running|success|failed|timeout|skipped|cancelled
    attempt         integer     not null default 1,
    input           jsonb,
    output          jsonb,
    error           text,
    started_at      timestamptz,
    finished_at     timestamptz,
    created_at      timestamptz not null default now()
);

-- Idempotensi: satu cabang tidak boleh punya dua baris hidup.
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'branch_split_key'
    ) then
        alter table public.execution_branches
            add constraint branch_split_key
            unique (execution_id, split_step_id, branch_key);
    end if;
end $$;

create index if not exists idx_branches_exec_status
    on public.execution_branches (execution_id, status);

create index if not exists idx_branches_merge
    on public.execution_branches (execution_id, merge_step_id);

comment on table public.execution_branches is
    'Fitur #5: status per cabang fan-out. Merge memakai tabel ini untuk '
    'menunggu semua cabang; keadaan tahan restart karena ada di Postgres.';

-- ---------------------------------------------------------------------
-- 4. RLS
-- ---------------------------------------------------------------------
alter table public.execution_branches enable row level security;

drop policy if exists branches_owner_read on public.execution_branches;
create policy branches_owner_read on public.execution_branches
    for select using (
        exists (
            select 1
              from public.executions e
              join public.workflows w on w.id = e.workflow_id
             where e.id = execution_branches.execution_id
               and w.user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------
-- 5. RPC branch_summary
--    Hitung agregat cabang untuk satu eksekusi. Dipakai merge fan-in
--    dan endpoint status. Mengembalikan jsonb supaya PostgREST tidak
--    mengembalikan objek semua-NULL yang truthy di Python.
-- ---------------------------------------------------------------------
drop function if exists public.branch_summary(uuid);

create or replace function public.branch_summary(p_execution_id uuid)
returns jsonb
language sql
stable
as $$
    select jsonb_build_object(
        'execution_id', p_execution_id,
        'total',    count(*),
        'success',  count(*) filter (where status = 'success'),
        'failed',   count(*) filter (where status = 'failed'),
        'timeout',  count(*) filter (where status = 'timeout'),
        'skipped',  count(*) filter (where status = 'skipped'),
        'cancelled',count(*) filter (where status = 'cancelled'),
        'running',  count(*) filter (where status in ('running', 'pending')),
        'settled',  count(*) filter (where status in
                       ('success', 'failed', 'timeout', 'skipped', 'cancelled'))
    )
    from public.execution_branches
    where execution_id = p_execution_id;
$$;

comment on function public.branch_summary(uuid) is
    'Fitur #5: agregat status cabang (total/success/failed/timeout/running).';

grant execute on function public.branch_summary(uuid) to authenticated;

-- ---------------------------------------------------------------------
-- 6. RPC bulk_update_branches
--    Perbarui BANYAK cabang dalam SATU perjalanan bolak-balik.
--
--    Kenapa: satu panggilan PostgREST memakan ~110-125 ms. Menulis 8 cabang
--    satu-per-satu >0.9 s hanya untuk pembukuan — membuat fan-out paralel
--    justru LEBIH LAMBAT daripada seri (terukur 8x0.1 s -> 1.06 s).
--    `upsert` PostgREST tidak bisa dipakai (payload parsial dianggap INSERT
--    sehingga kolom NOT NULL jadi NULL -> 23502). Jadi satu fungsi SQL yang
--    menerima array jsonb dan meng-UPDATE baris yang sudah ada.
--
--    p_updates: [{"branch_key":"a","status":"success",
--                 "output":{...},"error":null}, ...]
--    Return: jumlah baris yang benar-benar diperbarui.
-- ---------------------------------------------------------------------
drop function if exists public.bulk_update_branches(uuid, text, jsonb);

create or replace function public.bulk_update_branches(
    p_execution_id  uuid,
    p_split_step_id text,
    p_updates       jsonb
) returns integer
language plpgsql
as $$
declare
    v_item      jsonb;
    v_status    text;
    v_key       text;
    v_hit       integer;
    v_total     integer := 0;
begin
    for v_item in select * from jsonb_array_elements(p_updates)
    loop
        v_key    := v_item ->> 'branch_key';
        v_status := v_item ->> 'status';

        update public.execution_branches b
           set status      = v_status,
               attempt     = coalesce((v_item ->> 'attempt')::integer, b.attempt),
               output      = case when v_item ? 'output'
                                  then v_item -> 'output' else b.output end,
               error       = case when v_item ? 'error'
                                  then v_item ->> 'error' else b.error end,
               started_at  = case when v_status = 'running'
                                  then now() else b.started_at end,
               finished_at = case when v_status in
                                  ('success','failed','timeout','skipped','cancelled')
                                  then now() else b.finished_at end
         where b.execution_id  = p_execution_id
           and b.split_step_id = p_split_step_id
           and b.branch_key    = v_key
           -- cabang yang sudah final TIDAK dihidupkan ulang
           and not (b.status in
                    ('success','failed','timeout','skipped','cancelled')
                    and v_status = 'running');

        get diagnostics v_hit = row_count;
        v_total := v_total + v_hit;
    end loop;
    return v_total;
end;
$$;

comment on function public.bulk_update_branches(uuid, text, jsonb) is
    'Fitur #5: perbarui banyak cabang dalam satu round trip (hindari I/O per cabang).';

grant execute on function public.bulk_update_branches(uuid, text, jsonb)
    to authenticated;
