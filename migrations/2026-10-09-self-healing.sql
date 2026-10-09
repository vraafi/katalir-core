-- ===========================================================================
-- Fitur #3 — Self-healing persistence (execution recovery otonom)
-- 9 Okt 2026
--
-- n8n 2.42.0 hanya MENDETEKSI eksekusi yang crash (5 detektor) lalu berhenti;
-- eksekusi crash TIDAK dioper ke worker lain dan tidak ada checkpoint
-- (retry selalu mulai dari awal). Tabel di bawah ini menambahkan lapisan
-- PEMULIHAN: state eksekusi + kunci idempotensi + riwayat aksi, sehingga
-- restart tidak pernah menggandakan efek samping.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1) State eksekusi yang dipantau supervisor
-- ---------------------------------------------------------------------------
create table if not exists public.execution_recovery_state (
    execution_id    text primary key,
    workflow_id     text        not null default '',
    owner           uuid,
    mode            text        not null default 'manual',
    -- pending | running | success | error | crashed | cancelled | waiting
    status          text        not null default 'pending',
    attempt         int         not null default 0,
    max_attempts    int         not null default 3,
    worker_id       text        not null default '',
    node_id         text        not null default '',
    -- stall | queue-recovery | startup-recovery | start-failure |
    -- workflow-deactivation | ''
    detector        text        not null default '',
    error           text        not null default '',
    error_kind      text        not null default '',
    crash_signalled boolean     not null default false,
    recovered_by    text        not null default '',
    links           jsonb       not null default '[]'::jsonb,
    created_at      timestamptz not null default now(),
    started_at      timestamptz,
    ended_at        timestamptz,
    heartbeat_at    timestamptz,
    updated_at      timestamptz not null default now(),
    constraint execution_recovery_status_chk check (
        status in ('pending', 'running', 'success', 'error',
                   'crashed', 'cancelled', 'waiting')),
    constraint execution_recovery_detector_chk check (
        detector in ('', 'stall', 'queue-recovery', 'startup-recovery',
                     'start-failure', 'workflow-deactivation')),
    constraint execution_recovery_attempt_chk check (
        attempt >= 0 and max_attempts >= 0)
);

comment on table public.execution_recovery_state is
    'Fitur #3: state eksekusi untuk deteksi + pemulihan otonom (padanan 5 detektor crash n8n).';
comment on column public.execution_recovery_state.crash_signalled is
    'true = sinyal crash sudah pernah dikirim; mencegah hook on_crash dijalankan dua kali.';
comment on column public.execution_recovery_state.links is
    'Riwayat {reason, at} setiap kali eksekusi ini dipulihkan (audit trail).';

-- Indeks untuk scan detektor: hanya baris non-terminal yang dipindai.
create index if not exists idx_exec_recovery_active
    on public.execution_recovery_state (status, heartbeat_at)
    where status in ('pending', 'running', 'waiting');
create index if not exists idx_exec_recovery_owner
    on public.execution_recovery_state (owner, created_at desc);

-- ---------------------------------------------------------------------------
-- 2) Kunci idempotensi (IdempotencyGuard) — durability lintas restart
-- ---------------------------------------------------------------------------
create table if not exists public.idempotency_keys (
    key         text primary key,          -- sha256 hex
    state       text        not null default 'claimed',
    meta        jsonb       not null default '{}'::jsonb,
    result      jsonb,
    undo        jsonb,
    undo_error  text        not null default '',
    owner       uuid,
    claimed_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint idempotency_state_chk check (
        state in ('claimed', 'committed', 'compensated'))
);

comment on table public.idempotency_keys is
    'Fitur #3: kunci idempotensi + compensating action. Commit WAJIB dipersist supaya restart tidak mengulang efek samping.';
comment on column public.idempotency_keys.state is
    'claimed -> committed (sukses) atau compensated (di-rollback lewat undo).';
comment on column public.idempotency_keys.undo is
    'Hasil aksi kompensasi (rollback) bila pekerjaan dibatalkan.';

create index if not exists idx_idempotency_owner
    on public.idempotency_keys (owner, claimed_at desc);
-- Pembersihan berkala: kunci lama yang sudah committed tetap disimpan untuk
-- jendela audit, lalu boleh dipangkas oleh job retensi.

-- ---------------------------------------------------------------------------
-- 3) Riwayat aksi pemulihan (audit + replay-safe)
-- ---------------------------------------------------------------------------
create table if not exists public.recovery_actions (
    id              bigserial primary key,
    execution_id    text        not null,
    owner           uuid,
    detector        text        not null default '',
    action          text        not null default '',
    attempt         int         not null default 0,
    max_attempts    int         not null default 0,
    error_kind      text        not null default '',
    applied         boolean     not null default false,
    duplicate       boolean     not null default false,
    result          jsonb,
    recovered_key   text        not null default '',
    created_at      timestamptz not null default now(),
    constraint recovery_action_chk check (action in ('restart', 'quarantine'))
);

comment on table public.recovery_actions is
    'Fitur #3: audit setiap aksi pemulihan. recovered_key = recovery_key(execution_id, attempt) -> idempoten.';

create unique index if not exists uq_recovery_actions_key
    on public.recovery_actions (recovered_key)
    where duplicate = false and applied = true;
create index if not exists idx_recovery_actions_exec
    on public.recovery_actions (execution_id, created_at desc);

-- ---------------------------------------------------------------------------
-- 4) Trigger updated_at
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end $$;

drop trigger if exists trg_exec_recovery_touch on public.execution_recovery_state;
create trigger trg_exec_recovery_touch
    before update on public.execution_recovery_state
    for each row execute function public.touch_updated_at();

drop trigger if exists trg_idempotency_touch on public.idempotency_keys;
create trigger trg_idempotency_touch
    before update on public.idempotency_keys
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- 5) RLS — tiap pemilik hanya melihat datanya sendiri
-- ---------------------------------------------------------------------------
alter table public.execution_recovery_state enable row level security;
alter table public.idempotency_keys       enable row level security;
alter table public.recovery_actions       enable row level security;

drop policy if exists p_exec_recovery_owner on public.execution_recovery_state;
create policy p_exec_recovery_owner on public.execution_recovery_state
    for all using (owner = auth.uid()) with check (owner = auth.uid());

drop policy if exists p_idempotency_owner on public.idempotency_keys;
create policy p_idempotency_owner on public.idempotency_keys
    for all using (owner = auth.uid()) with check (owner = auth.uid());

drop policy if exists p_recovery_actions_owner on public.recovery_actions;
create policy p_recovery_actions_owner on public.recovery_actions
    for all using (owner = auth.uid()) with check (owner = auth.uid());
