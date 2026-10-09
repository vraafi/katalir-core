-- 2026-10-09-sandbox-isolation.sql
-- Fitur #5: isolasi sandbox agen (model task runner n8n).
--
-- Padanan n8n "Task Runners" (docs Okt 2026):
--   * mode runner: internal (sub-proses, uid/gid sama -> TIDAK siap produksi)
--     vs external (kontainer sidecar terpisah -> siap produksi)
--   * broker (bagian instance) + runner + requester (Code node)
--   * batas: max_concurrency, task_timeout, heartbeat, request_timeout,
--     max_payload
--   * allowlist modul per runtime (default KOSONG = semua impor ditolak)
--   * hardening: distroless, uid/gid 65532, rootfs read-only, AppArmor
--
-- Konteks: CVE-2026-27495 / GHSA-jjpj-p2wh-qf23 — "Sandbox Escape in
-- JavaScript Task Runner", CVSS 9.4, CWE-94, diperbaiki di n8n
-- 1.123.22 / 2.9.3 / 2.10.1.
--
-- Idempoten: seluruh pernyataan memakai IF NOT EXISTS / DROP ... IF EXISTS.

-- ---------------------------------------------------------------------------
-- Kebijakan per lingkungan — satu baris per scope (instance/project)
-- ---------------------------------------------------------------------------
create table if not exists public.sandbox_policies (
    id                    uuid primary key default gen_random_uuid(),
    --: "" = kebijakan tingkat instance (default global)
    scope_id              text not null default '',
    scope_kind            text not null default 'instance'
                          check (scope_kind in ('instance', 'project')),
    mode                  text not null default 'internal'
                          check (mode in ('internal', 'external')),
    distroless            boolean not null default false,
    uid                   integer not null default 1000,
    gid                   integer not null default 1000,
    read_only_root        boolean not null default false,
    apparmor              boolean not null default false,
    max_concurrency       integer not null default 5 check (max_concurrency > 0),
    task_timeout_s        integer not null default 300 check (task_timeout_s > 0),
    heartbeat_interval_s  integer not null default 30
                          check (heartbeat_interval_s > 0),
    request_timeout_s     integer not null default 60
                          check (request_timeout_s > 0),
    max_payload_bytes     bigint not null default 1073741824
                          check (max_payload_bytes > 0),
    auto_shutdown_s       integer not null default 15
                          check (auto_shutdown_s >= 0),
    allow_builtin         text[] not null default '{}',
    allow_external        text[] not null default '{}',
    allow_stdlib          text[] not null default '{}',
    allow_py_external     text[] not null default '{}',
    block_env_access      boolean not null default true,
    insecure_mode         boolean not null default false,
    allow_prototype_mutation boolean not null default false,
    created_by            text not null default '',
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    --: heartbeat WAJIB < task_timeout (jitter jaringan tidak boleh memicu
    --: restart runner palsu) — ditegakkan juga di lapisan aplikasi.
    constraint sandbox_policies_heartbeat_chk
        check (heartbeat_interval_s < task_timeout_s),
    --: distroless mewajibkan uid/gid 65532 (docs n8n "harden task runners").
    constraint sandbox_policies_distroless_uid_chk
        check (not distroless or uid = 65532),
    unique (scope_kind, scope_id)
);

create index if not exists sandbox_policies_scope_idx
    on public.sandbox_policies (scope_kind, scope_id);

drop trigger if exists sandbox_policies_touch on public.sandbox_policies;
create trigger sandbox_policies_touch
    before update on public.sandbox_policies
    for each row execute function public.touch_updated_at();

--: Baris default tingkat instance (idempoten).
insert into public.sandbox_policies (scope_id, scope_kind, mode)
values ('', 'instance', 'internal')
on conflict (scope_kind, scope_id) do nothing;

-- ---------------------------------------------------------------------------
-- Runner terdaftar — mencerminkan runner yang terhubung ke broker
-- ---------------------------------------------------------------------------
create table if not exists public.sandbox_runners (
    runner_id        text primary key,
    runtime          text not null check (runtime in ('javascript', 'python')),
    policy_id        uuid references public.sandbox_policies (id)
                     on delete set null,
    status           text not null default 'idle'
                     check (status in ('idle', 'busy', 'dead', 'restarting')),
    active_tasks     integer not null default 0,
    completed_tasks  bigint not null default 0,
    failed_tasks     bigint not null default 0,
    rejected_tasks   bigint not null default 0,
    last_heartbeat   timestamptz not null default now(),
    started_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists sandbox_runners_runtime_idx
    on public.sandbox_runners (runtime, status);
create index if not exists sandbox_runners_heartbeat_idx
    on public.sandbox_runners (last_heartbeat);

drop trigger if exists sandbox_runners_touch on public.sandbox_runners;
create trigger sandbox_runners_touch
    before update on public.sandbox_runners
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- Peristiwa penolakan / pemutusan tugas — jejak keamanan & observabilitas
-- ---------------------------------------------------------------------------
create table if not exists public.sandbox_events (
    id          bigserial primary key,
    runner_id   text not null default '',
    task_id     text not null default '',
    runtime     text not null default '',
    event       text not null,
    --: module_not_allowed | payload_too_large | concurrency_exceeded |
    --: task_timeout | heartbeat_expired | request_timeout | auth_rejected
    detail      jsonb not null default '{}'::jsonb,
    at          timestamptz not null default now()
);

create index if not exists sandbox_events_at_idx
    on public.sandbox_events (at desc);
create index if not exists sandbox_events_event_idx
    on public.sandbox_events (event, at desc);
create index if not exists sandbox_events_runner_idx
    on public.sandbox_events (runner_id, at desc);

-- ---------------------------------------------------------------------------
-- CVE yang memotivasi gerbang mode — dipakai UI/audit agar alasannya jelas
-- ---------------------------------------------------------------------------
create table if not exists public.sandbox_known_cves (
    cve_id         text primary key,
    ghsa_id        text not null default '',
    title          text not null default '',
    severity       text not null default 'critical',
    cvss_score     numeric(3, 1) not null default 0,
    cvss_vector    text not null default '',
    cwe            text not null default '',
    affected       text not null default '',
    patched        text[] not null default '{}',
    internal_impact text not null default '',
    external_impact text not null default '',
    created_at     timestamptz not null default now()
);

insert into public.sandbox_known_cves
    (cve_id, ghsa_id, title, severity, cvss_score, cvss_vector, cwe,
     affected, patched, internal_impact, external_impact)
values (
    'CVE-2026-27495', 'GHSA-jjpj-p2wh-qf23',
    'Sandbox Escape in JavaScript Task Runner', 'critical', 9.4,
    'CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H', 'CWE-94',
    '< 1.123.22, >= 2.0.0 < 2.9.3, >= 2.10.0 < 2.10.1',
    array['1.123.22', '2.9.3', '2.10.1'],
    'penguasaan penuh host n8n',
    'akses ke / dampak pada tugas lain di runner'
)
on conflict (cve_id) do nothing;

-- ---------------------------------------------------------------------------
-- View: kesehatan runner (yang heartbeat-nya kedaluwarsa = mati)
-- ---------------------------------------------------------------------------
create or replace view public.sandbox_runner_health as
select r.runner_id,
       r.runtime,
       r.status,
       r.active_tasks,
       r.last_heartbeat,
       extract(epoch from (now() - r.last_heartbeat)) as heartbeat_age_s,
       coalesce(p.heartbeat_interval_s, 30) as heartbeat_interval_s,
       extract(epoch from (now() - r.last_heartbeat))
         > coalesce(p.heartbeat_interval_s, 30) * 2 as is_stale,
       r.completed_tasks,
       r.failed_tasks,
       r.rejected_tasks
  from public.sandbox_runners r
  left join public.sandbox_policies p on p.id = r.policy_id;

-- ---------------------------------------------------------------------------
-- View: temuan hardening per kebijakan (dihitung di SQL, bukan di aplikasi)
-- ---------------------------------------------------------------------------
create or replace view public.sandbox_hardening_findings as
select p.id,
       p.scope_kind,
       p.scope_id,
       p.mode,
       (not (p.mode = 'external' and p.distroless and p.read_only_root
             and p.apparmor and not p.insecure_mode)) as has_findings,
       --: CATATAN: `array_remove(arr, null)` TIDAK pernah cocok di Postgres,
       --: jadi baris null disaring lewat subquery + `where x is not null`.
       coalesce((
         select array_agg(x)
           from (values
             (case when p.mode <> 'external' then
               'mode internal tidak siap produksi' end),
             (case when not p.distroless then 'image bukan distroless' end),
             (case when not p.read_only_root then
               'root filesystem tidak read-only' end),
             (case when not p.apparmor then 'profil AppArmor tidak aktif' end),
             (case when not p.block_env_access then
               'akses lingkungan runner dibuka' end),
             (case when p.insecure_mode then 'insecure_mode aktif' end),
             (case when p.allow_prototype_mutation then
               'mutasi prototipe diizinkan' end)
           ) as t(x)
          where x is not null
       ), '{}'::text[]) as finding_names
  from public.sandbox_policies p;

-- ---------------------------------------------------------------------------
-- RLS — hanya service_role yang menulis; authenticated boleh membaca
-- (kebijakan bukan rahasia; jejak peristiwa tidak memuat payload kode).
-- ---------------------------------------------------------------------------
alter table public.sandbox_policies enable row level security;
alter table public.sandbox_runners enable row level security;
alter table public.sandbox_events enable row level security;
alter table public.sandbox_known_cves enable row level security;

drop policy if exists sandbox_policies_service on public.sandbox_policies;
create policy sandbox_policies_service on public.sandbox_policies
    for all to service_role using (true) with check (true);

drop policy if exists sandbox_runners_service on public.sandbox_runners;
create policy sandbox_runners_service on public.sandbox_runners
    for all to service_role using (true) with check (true);

drop policy if exists sandbox_events_service on public.sandbox_events;
create policy sandbox_events_service on public.sandbox_events
    for all to service_role using (true) with check (true);

drop policy if exists sandbox_cves_service on public.sandbox_known_cves;
create policy sandbox_cves_service on public.sandbox_known_cves
    for all to service_role using (true) with check (true);

drop policy if exists sandbox_policies_read_auth on public.sandbox_policies;
create policy sandbox_policies_read_auth on public.sandbox_policies
    for select to authenticated using (true);

drop policy if exists sandbox_runners_read_auth on public.sandbox_runners;
create policy sandbox_runners_read_auth on public.sandbox_runners
    for select to authenticated using (true);

drop policy if exists sandbox_cves_read_auth on public.sandbox_known_cves;
create policy sandbox_cves_read_auth on public.sandbox_known_cves
    for select to authenticated using (true);

grant select on public.sandbox_policies to authenticated;
grant select on public.sandbox_runners to authenticated;
grant select on public.sandbox_known_cves to authenticated;
