-- ============================================================================
-- migrations/2026-10-08-subworkflow.sql
-- Fitur #4 — SUB-WORKFLOW EXECUTION
-- ============================================================================
-- Satu workflow bisa memanggil workflow lain sebagai anak (pola
-- `ref_workflow_id`), dengan batas kedalaman 3 level.
--
-- RISET (docs/fitur-04-subworkflow.md):
--   Pola `ref_workflow_id` (didi/tg-flow) + rekomendasi resmi
--   "Keep nesting depth ≤3 levels for maintainability".
--   KEKURANGAN referensi itu: kedalaman tak terbatas TANPA deteksi siklus
--   -> A memanggil B, B memanggil A = hang. Kita perbaiki di sini.
--
-- CARA JALANKAN: Supabase Dashboard -> SQL Editor -> tempel -> Run. Idempoten.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Jejak pemanggilan: eksekusi ini adalah anak dari eksekusi mana?
--    `parent_execution_id` sudah ada dari Fitur #2; di sini ditambah
--    kedalaman eksplisit supaya pembatasan 3 level bisa dicek tanpa
--    menelusuri rantai ke atas berulang kali.
-- ---------------------------------------------------------------------------
alter table public.executions
    add column if not exists depth integer not null default 0;

comment on column public.executions.depth is
  'Kedalaman sub-workflow (0 = dipanggil langsung user). Maksimum 3 (Fitur #4).';

create index if not exists idx_executions_parent
    on public.executions (parent_execution_id)
    where parent_execution_id is not null;

-- ---------------------------------------------------------------------------
-- 2. Tabel rantai pemanggilan: satu baris per (anak -> induk).
--    Dipakai untuk deteksi SIKLUS (A->B->A) secara cepat.
-- ---------------------------------------------------------------------------
create table if not exists public.workflow_call_chain (
    id                  uuid        primary key default gen_random_uuid(),
    execution_id        uuid        not null references public.executions(id) on delete cascade,
    child_workflow_id   uuid        not null,
    parent_workflow_id  uuid        not null,
    depth               integer     not null default 0,
    created_at          timestamptz not null default now()
);

comment on table public.workflow_call_chain is
  'Rantai pemanggilan sub-workflow (Fitur #4) — sumber deteksi siklus. '
  'Bila child_workflow_id sudah muncul di rantai leluhur = siklus, tolak.';

create index if not exists idx_call_chain_exec
    on public.workflow_call_chain (execution_id, depth);

-- ---------------------------------------------------------------------------
-- 3. Keunikan: satu eksekusi tidak boleh memanggil workflow anak yang sama
--    dua kali pada step yang sama (anti dobel-invoke saat resume/replay).
-- ---------------------------------------------------------------------------
create table if not exists public.subworkflow_invocations (
    id                  uuid        primary key default gen_random_uuid(),
    parent_execution_id uuid        not null references public.executions(id) on delete cascade,
    step_id             text        not null,
    child_workflow_id   uuid        not null,
    child_execution_id  uuid        references public.executions(id) on delete set null,
    status              text        not null default 'running',  -- running|success|failed
    input               jsonb,
    output              jsonb,
    error               text,
    started_at          timestamptz not null default now(),
    finished_at         timestamptz,
    constraint subwf_invoke_key unique (parent_execution_id, step_id)
);

comment on table public.subworkflow_invocations is
  'Satu baris per pemanggilan sub-workflow (Fitur #4). '
  'unique(parent_execution_id, step_id) mencegah anak dipanggil dua kali '
  'saat eksekusi induk di-resume (replay).';

create index if not exists idx_subwf_parent
    on public.subworkflow_invocations (parent_execution_id, started_at);

-- ---------------------------------------------------------------------------
-- 4. RPC: deteksi siklus + kedalaman dalam SATU query (atomik).
--    Menelusuri leluhur dari parent_execution_id ke atas; bila
--    child_workflow_id ditemukan di rantai itu -> SIKLUS.
--    Mengembalikan: {allowed bool, reason text, depth int}
-- ---------------------------------------------------------------------------
create or replace function public.check_subworkflow_allowed(
    p_parent_execution_id uuid,
    p_child_workflow_id   uuid,
    p_max_depth           integer default 3
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $function$
declare
    v_depth     integer;
    v_ancestor  uuid;
    v_cycle     boolean := false;
    v_guard     integer := 0;
begin
    -- Kedalaman induk (0 bila tidak ada)
    select coalesce(depth, 0) into v_depth
      from public.executions where id = p_parent_execution_id;
    if v_depth is null then
        return jsonb_build_object('allowed', false,
            'reason', 'eksekusi induk tidak ditemukan', 'depth', 0);
    end if;

    -- Batas kedalaman: anak akan berada di depth+1
    if v_depth + 1 > p_max_depth then
        return jsonb_build_object('allowed', false,
            'reason', format('kedalaman maksimum %s terlampaui (akan menjadi %s)',
                             p_max_depth, v_depth + 1),
            'depth', v_depth + 1);
    end if;

    -- Telusuri leluhur; bila child sudah ada di rantai -> siklus.
    -- Guard iterasi mencegah loop tak berujung kalau data rusak.
    v_ancestor := p_parent_execution_id;
    while v_ancestor is not null and v_guard < 50 loop
        v_guard := v_guard + 1;

        -- workflow yang menjalankan eksekusi leluhur ini
        if exists (
            select 1 from public.executions e
             where e.id = v_ancestor
               and e.workflow_id = p_child_workflow_id
        ) then
            v_cycle := true;
            exit;
        end if;

        select parent_execution_id into v_ancestor
          from public.executions where id = v_ancestor;
    end loop;

    if v_cycle then
        return jsonb_build_object('allowed', false,
            'reason', 'siklus terdeteksi: workflow anak sudah ada di rantai leluhur',
            'depth', v_depth + 1);
    end if;

    return jsonb_build_object('allowed', true, 'reason', 'ok',
                              'depth', v_depth + 1);
end;
$function$;

comment on function public.check_subworkflow_allowed(uuid, uuid, integer) is
  'Cek kedalaman + siklus SEBELUM memanggil sub-workflow (Fitur #4). '
  'Mengembalikan jsonb {allowed, reason, depth}.';

revoke all on function public.check_subworkflow_allowed(uuid, uuid, integer) from public;
grant execute on function public.check_subworkflow_allowed(uuid, uuid, integer)
    to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 5. RLS untuk tabel baru
-- ---------------------------------------------------------------------------
alter table public.workflow_call_chain       enable row level security;
alter table public.subworkflow_invocations   enable row level security;

-- Pemilik eksekusi (via workflow) boleh membaca jejak pemanggilan
drop policy if exists call_chain_owner_read on public.workflow_call_chain;
create policy call_chain_owner_read on public.workflow_call_chain
    for select using (
        exists (select 1 from public.executions e
                  join public.workflows w on w.id = e.workflow_id
                 where e.id = workflow_call_chain.execution_id
                   and w.user_id = auth.uid()));

drop policy if exists subwf_invoke_owner_read on public.subworkflow_invocations;
create policy subwf_invoke_owner_read on public.subworkflow_invocations
    for select using (
        exists (select 1 from public.executions e
                  join public.workflows w on w.id = e.workflow_id
                 where e.id = subworkflow_invocations.parent_execution_id
                   and w.user_id = auth.uid()));

-- ---------------------------------------------------------------------------
-- VERIFIKASI:
--   select public.check_subworkflow_allowed(
--     '00000000-0000-0000-0000-000000000000'::uuid,
--     '00000000-0000-0000-0000-000000000000'::uuid, 3);
--   -- -> {"allowed": false, "reason": "eksekusi induk tidak ditemukan", ...}
-- ----------------------------------------------------------------------------
