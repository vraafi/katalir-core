-- 2026-10-09-custom-rbac.sql
-- Fitur #10: RBAC kustom dua tingkat (project + instance).
--
-- Padanan n8n "Custom roles" (Enterprise, docs Okt 2026):
--   * peran project  -> berlaku HANYA di project tempat ia ditetapkan
--   * peran instance -> berlaku di seluruh instance (satu per pengguna)
--   * kosakata scope persis n8n (42 project + 10 instance)
--   * peran yang masih dipakai TIDAK boleh dihapus (FK RESTRICT)
--
-- Idempoten: seluruh pernyataan memakai IF NOT EXISTS / DROP ... IF EXISTS.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Helper trigger updated_at (dipakai juga oleh migrasi fitur lain)
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- roles — peran bawaan (builtin) + kustom
-- ---------------------------------------------------------------------------
create table if not exists public.rbac_roles (
    id           uuid primary key default gen_random_uuid(),
    name         text not null unique
                 check (name ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    level        text not null check (level in ('project', 'instance')),
    description  text not null default '',
    --: nama peran bawaan n8n yang menjadi basis (kosong = murni kustom)
    preset_of    text not null default '',
    --: scope eksplisit SAJA (implikasi dihitung di aplikasi, lihat rbac.py)
    granted      text[] not null default '{}',
    builtin      boolean not null default false,
    --: kombinasi berisiko privilege escalation (peringatan docs n8n)
    escalation_risks text[] not null default '{}',
    created_by   text not null default '',
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    --: peran bawaan tidak boleh diubah/dihapus (ditegakkan juga di app layer)
    constraint rbac_roles_builtin_immutable_chk
        check (not builtin or preset_of = name)
);

create index if not exists rbac_roles_level_idx
    on public.rbac_roles (level, builtin);

drop trigger if exists rbac_roles_touch on public.rbac_roles;
create trigger rbac_roles_touch
    before update on public.rbac_roles
    for each row execute function public.touch_updated_at();

-- Seed peran bawaan (idempoten). `granted` sengaja memuat SELURUH scope
-- efektif supaya basis data dapat diperiksa tanpa harus menjalankan Python.
insert into public.rbac_roles (name, level, description, preset_of, granted,
                               builtin)
values
    ('project:admin', 'project', 'bawaan n8n: project:admin', 'project:admin',
     array[
       'project:read','project:update','project:delete',
       'workflow:create','workflow:read','workflow:update','workflow:execute',
       'workflow:publish','workflow:delete','workflow:move',
       'workflow:enableRedaction','workflow:disableRedaction',
       'credential:create','credential:read','credential:update',
       'credential:delete','credential:move','credential:share',
       'credential:unshare',
       'folder:create','folder:read','folder:update','folder:delete',
       'folder:move','execution:reveal',
       'externalSecretsProvider:create','externalSecretsProvider:read',
       'externalSecretsProvider:update','externalSecretsProvider:delete',
       'externalSecretsProvider:sync','externalSecret:list',
       'dataTable:create','dataTable:read','dataTable:update',
       'dataTable:delete','dataTable:readRow','dataTable:writeRow',
       'projectVariable:create','projectVariable:read',
       'projectVariable:update','projectVariable:delete',
       'sourceControl:push'
     ], true),
    ('project:editor', 'project', 'bawaan n8n: project:editor', 'project:editor',
     array[
       'project:read',
       'workflow:create','workflow:read','workflow:update','workflow:execute',
       'workflow:delete',
       'credential:create','credential:read','credential:update',
       'credential:delete',
       'folder:create','folder:read','folder:update','folder:delete'
     ], true),
    ('project:viewer', 'project', 'bawaan n8n: project:viewer', 'project:viewer',
     array['project:read','workflow:read','credential:read','folder:read'],
     true),
    ('instance:owner', 'instance', 'bawaan n8n: instance:owner', 'instance:owner',
     array[
       'instanceSettings:manage','members:manage','roles:manageAll',
       'roles:manageProject','apiKeys:manageOthers','apiKeys:manageOwn',
       'tags:read','tags:manage','projects:create','insights:read'
     ], true),
    ('instance:admin', 'instance', 'bawaan n8n: instance:admin', 'instance:admin',
     array[
       'instanceSettings:manage','members:manage','roles:manageAll',
       'roles:manageProject','apiKeys:manageOthers','apiKeys:manageOwn',
       'tags:read','tags:manage','projects:create','insights:read'
     ], true),
    ('instance:member', 'instance', 'bawaan n8n: instance:member', 'instance:member',
     array['apiKeys:manageOwn','tags:read','tags:manage'], true)
on conflict (name) do nothing;

--: Isi ulang `escalation_risks` untuk peran bawaan (turunan, bukan masukan).
--: CATATAN: `array_remove(arr, null)` TIDAK pernah cocok di Postgres, jadi
--: baris null harus disaring dengan subquery + `where x is not null`.
update public.rbac_roles r
   set escalation_risks = coalesce((
        select array_agg(x)
          from (values
            (case when 'roles:manageAll' = any(r.granted) then
              'roles:manageAll: dapat mengubah peran sendiri untuk menambah izin yang tidak diberikan semula'
            end),
            (case when 'roles:manageProject' = any(r.granted) then
              'roles:manageProject: dapat mengubah peran project yang dipegang sendiri untuk menambah izin'
            end),
            (case when 'members:manage' = any(r.granted) then
              'members:manage: dapat mengundang akun yang dikendalikan lalu memberinya akses tingkat Admin'
            end)
          ) as t(x)
         where x is not null
       ), '{}'::text[])
 where r.builtin = true;

-- ---------------------------------------------------------------------------
-- project_role_assignments — peran per pengguna per project
-- ---------------------------------------------------------------------------
create table if not exists public.rbac_project_assignments (
    id          uuid primary key default gen_random_uuid(),
    project_id  text not null,
    user_id     text not null,
    role_name   text not null references public.rbac_roles (name)
                on delete restrict,
    assigned_by text not null default '',
    assigned_at timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (project_id, user_id)
);

create index if not exists rbac_proj_assign_user_idx
    on public.rbac_project_assignments (user_id);
create index if not exists rbac_proj_assign_role_idx
    on public.rbac_project_assignments (role_name);

drop trigger if exists rbac_proj_assign_touch
    on public.rbac_project_assignments;
create trigger rbac_proj_assign_touch
    before update on public.rbac_project_assignments
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- instance_role_assignments — satu peran instance per pengguna
-- ---------------------------------------------------------------------------
create table if not exists public.rbac_instance_assignments (
    user_id     text primary key,
    role_name   text not null references public.rbac_roles (name)
                on delete restrict,
    assigned_by text not null default '',
    assigned_at timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists rbac_inst_assign_role_idx
    on public.rbac_instance_assignments (role_name);

drop trigger if exists rbac_inst_assign_touch
    on public.rbac_instance_assignments;
create trigger rbac_inst_assign_touch
    before update on public.rbac_instance_assignments
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- audit — setiap mutasi peran/penetapan
-- ---------------------------------------------------------------------------
create table if not exists public.rbac_audit (
    id         bigserial primary key,
    event      text not null,
    actor_id   text not null default '',
    project_id text not null default '',
    target_id  text not null default '',
    role_name  text not null default '',
    detail     jsonb not null default '{}'::jsonb,
    at         timestamptz not null default now()
);

create index if not exists rbac_audit_at_idx on public.rbac_audit (at desc);
create index if not exists rbac_audit_role_idx
    on public.rbac_audit (role_name, at desc);

-- ---------------------------------------------------------------------------
-- View bantu: jumlah pemakaian tiap peran (untuk gerbang "role in use")
-- ---------------------------------------------------------------------------
create or replace view public.rbac_role_usage as
select r.name as role_name,
       r.level,
       r.builtin,
       (select count(*) from public.rbac_project_assignments a
         where a.role_name = r.name) as project_uses,
       (select count(*) from public.rbac_instance_assignments a
         where a.role_name = r.name) as instance_uses,
       (select count(*) from public.rbac_project_assignments a
         where a.role_name = r.name)
       + (select count(*) from public.rbac_instance_assignments a
           where a.role_name = r.name) as total_uses
  from public.rbac_roles r;

-- ---------------------------------------------------------------------------
-- View bantu: matriks scope efektif per pengguna per project.
--
-- PENTING: view ini memakai scope EKSPLISIT (`granted`) saja, bukan himpunan
-- efektif. Implikasi (`read -> list`, `publish -> unpublish`,
-- `manageAll -> manageProject`, `manageOthers -> manageOwn`) dihitung di
-- aplikasi oleh `rbac.expand_scopes()`; menduplikasi logika itu di SQL akan
-- membuat dua sumber kebenaran yang bisa menyimpang. Untuk penegakan
-- otorisasi produksi, pakai `rbac.py` (atau panggil endpoint `/rbac/authorize`).
-- ---------------------------------------------------------------------------
create or replace view public.rbac_effective_scopes as
select a.project_id,
       a.user_id,
       a.role_name,
       'project'::text as role_level,
       s.scope
  from public.rbac_project_assignments a
  join public.rbac_roles r on r.name = a.role_name
  cross join lateral unnest(r.granted) as s(scope)
union all
select ''::text as project_id,
       a.user_id,
       a.role_name,
       'instance'::text as role_level,
       s.scope
  from public.rbac_instance_assignments a
  join public.rbac_roles r on r.name = a.role_name
  cross join lateral unnest(r.granted) as s(scope);

-- ---------------------------------------------------------------------------
-- RLS — hanya service role yang boleh menulis; pengguna membaca penetapan
-- dirinya sendiri (via claim `sub` pada JWT, bila ada).
-- ---------------------------------------------------------------------------
alter table public.rbac_roles enable row level security;
alter table public.rbac_project_assignments enable row level security;
alter table public.rbac_instance_assignments enable row level security;
alter table public.rbac_audit enable row level security;

--: service_role (backend) — akses penuh
drop policy if exists rbac_roles_service on public.rbac_roles;
create policy rbac_roles_service on public.rbac_roles
    for all to service_role using (true) with check (true);

drop policy if exists rbac_proj_assign_service
    on public.rbac_project_assignments;
create policy rbac_proj_assign_service on public.rbac_project_assignments
    for all to service_role using (true) with check (true);

drop policy if exists rbac_inst_assign_service
    on public.rbac_instance_assignments;
create policy rbac_inst_assign_service on public.rbac_instance_assignments
    for all to service_role using (true) with check (true);

drop policy if exists rbac_audit_service on public.rbac_audit;
create policy rbac_audit_service on public.rbac_audit
    for all to service_role using (true) with check (true);

--: pengguna terautentikasi — baca definisi peran (tidak sensitif) + baca
--: penetapan miliknya sendiri saja.
drop policy if exists rbac_roles_read_auth on public.rbac_roles;
create policy rbac_roles_read_auth on public.rbac_roles
    for select to authenticated using (true);

drop policy if exists rbac_proj_assign_read_self
    on public.rbac_project_assignments;
create policy rbac_proj_assign_read_self on public.rbac_project_assignments
    for select to authenticated
    using (user_id = coalesce(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', ''));

drop policy if exists rbac_inst_assign_read_self
    on public.rbac_instance_assignments;
create policy rbac_inst_assign_read_self on public.rbac_instance_assignments
    for select to authenticated
    using (user_id = coalesce(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', ''));

grant select on public.rbac_roles to authenticated;
grant select on public.rbac_project_assignments to authenticated;
grant select on public.rbac_instance_assignments to authenticated;

-- ---------------------------------------------------------------------------
-- Peringatan: peran yang masih dipakai tidak dapat dihapus — dijaga oleh
-- FK `on delete restrict` di atas, sehingga perilaku n8n ditegakkan di
-- tingkat basis data, bukan hanya di aplikasi.
-- ---------------------------------------------------------------------------
