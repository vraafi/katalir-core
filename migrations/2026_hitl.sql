-- migrations/2026_hitl.sql
-- Fitur #3: Human-in-the-Loop (8 Okt 2026)
-- ======================================================================
-- Permintaan persetujuan manusia untuk workflow yang dijeda (paritas n8n
-- "Wait" + Slack/Email approval). Menyimpan status, keputusan per-approver,
-- batas waktu, dan audit trail.
--
-- Tipe id sengaja `text` (bukan uuid + FK) supaya permintaan tetap bisa
-- dibuat walau workflow/execution belum punya baris (mis. diuji mandiri),
-- dan agar tidak ada cascading delete yang menghapus jejak audit.
-- ======================================================================

create table if not exists hitl_requests (
    request_id    text primary key,
    workflow_id   text,
    execution_id  text,
    node_id       text,
    owner         text,
    channel       text not null default 'chat',
    message       text not null default '',
    approvers     jsonb not null default '[]'::jsonb,
    approval_mode text not null default 'any',
    on_timeout    text not null default 'resume',
    default_action text not null default 'approve',
    escalate_to   jsonb not null default '[]'::jsonb,
    escalated     boolean not null default false,
    status        text not null default 'pending',
    decisions     jsonb not null default '[]'::jsonb,
    context       jsonb not null default '{}'::jsonb,
    resume_token  text,
    created_at    timestamptz not null default now(),
    timeout_at    timestamptz,
    resolved_at   timestamptz
);

create index if not exists hitl_requests_status_idx
    on hitl_requests (status);
create index if not exists hitl_requests_owner_idx
    on hitl_requests (owner);
create index if not exists hitl_requests_exec_idx
    on hitl_requests (execution_id);

alter table hitl_requests enable row level security;

-- Service role (backend) memakai service key dan melewati RLS; policy ini
-- mengizinkan pemilik membaca permintaannya sendiri lewat anon/JWT.
drop policy if exists hitl_requests_owner on hitl_requests;
create policy hitl_requests_owner on hitl_requests
    for select using (owner = auth.jwt() ->> 'email');
