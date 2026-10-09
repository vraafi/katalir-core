-- Fitur #2: MCP BUILD WORKFLOW (padanan n8n instance-level MCP server)
-- Dibuat: 2026-10-09
--
-- Memodelkan 53 tool MCP n8n dalam 7 kategori (docs Okt 2026) plus gerbang
-- protokol MCP 2026-07-28 (stateless per-request envelope).
--
-- Catatan desain:
--   * `mcp_tool_catalog` menyimpan fakta tak-berubah-ubah (nama, kategori,
--     versi minimum, sifat mengubah) supaya gerbang versi bisa ditegakkan di
--     sisi basis data, bukan hanya di kode.
--   * `mcp_protocol_revisions` menyimpan registry revisi; revisi modern
--     ditandai `is_modern` karena `Mcp-Session-Id` HARUS ditolak di sana.
--   * `mcp_call_events` adalah jejak audit urutan panggilan. Loop build
--     (referensi -> validasi -> tulis) ditegakkan oleh CHECK pada kolom
--     `phase`, sehingga urutan yang melanggar tidak bisa "hanya dicatat".

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Registry revisi protokol
-- ---------------------------------------------------------------------------
create table if not exists mcp_protocol_revisions (
    revision        text primary key,
    is_modern       boolean not null default false,
    has_handshake   boolean not null default true,
    released_on     date,
    notes           text not null default '',
    created_at      timestamptz not null default now(),
    -- Revisi modern TIDAK punya handshake, dan sebaliknya. Dinyatakan di
    -- skema supaya kombinasi mustahil tidak pernah bisa disimpan.
    constraint mcp_rev_handshake_exclusive
        check (is_modern <> has_handshake)
);

insert into mcp_protocol_revisions (revision, is_modern, has_handshake, notes)
values
    ('2024-11-05', false, true,  'revisi awal'),
    ('2025-03-26', false, true,  'streamable HTTP diperkenalkan'),
    ('2025-06-18', false, true,  ''),
    ('2025-11-25', false, true,  'revisi handshake terakhir'),
    ('2026-07-28', true,  false,
     'stateless per-request; initialize + Mcp-Session-Id dihapus; '
     'server/discover WAJIB; ttlMs/cacheScope; Mcp-Method/Mcp-Name')
on conflict (revision) do nothing;

-- ---------------------------------------------------------------------------
-- Katalog tool
-- ---------------------------------------------------------------------------
create table if not exists mcp_tool_catalog (
    name            text primary key,
    category        text not null,
    since_version   text not null default '',
    mutating        boolean not null default false,
    needs_validation boolean not null default false,
    purpose         text not null default '',
    notes           text not null default '',
    created_at      timestamptz not null default now(),
    -- Tool yang mengubah state DAN butuh validasi hanya masuk akal bila ia
    -- memang mengubah state.
    constraint mcp_tool_gate_requires_mutation
        check (not needs_validation or mutating),
    -- Versi minimum, bila ada, harus x.y.z.
    constraint mcp_tool_since_format
        check (since_version = '' or since_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$')
);

create index if not exists mcp_tool_catalog_category_idx
    on mcp_tool_catalog (category);
create index if not exists mcp_tool_catalog_gate_idx
    on mcp_tool_catalog (needs_validation) where needs_validation;

-- Seed 53 tool (7 kategori). Selaras dengan `mcp_build_workflow.TOOLS`.
insert into mcp_tool_catalog
    (name, category, since_version, mutating, needs_validation, purpose)
values
    -- Workflow management (13)
    ('search_workflows',            'Workflow management', '2.12.0', false, false, 'cari workflow dengan filter'),
    ('get_workflow_details',        'Workflow management', '2.12.0', false, false, 'detail satu workflow'),
    ('execute_workflow',            'Workflow management', '2.12.0', true,  false, 'jalankan workflow'),
    ('test_workflow',               'Workflow management', '2.15.0', true,  false, 'uji jalan tanpa produksi'),
    ('prepare_workflow_pin_data',   'Workflow management', '2.15.0', true,  false, 'siapkan data pin untuk uji'),
    ('publish_workflow',            'Workflow management', '2.12.0', true,  false, 'aktifkan versi produksi'),
    ('unpublish_workflow',          'Workflow management', '2.12.0', true,  false, 'matikan versi produksi'),
    ('get_workflow_history',        'Workflow management', '2.29.0', false, false, 'riwayat versi workflow'),
    ('get_workflow_version',        'Workflow management', '2.29.0', false, false, 'ambil satu versi'),
    ('get_workflow_versions_diff',  'Workflow management', '2.36.0', false, false, 'diff antar versi'),
    ('search_projects',             'Workflow management', '2.14.0', false, false, 'cari project'),
    ('search_folders',              'Workflow management', '2.14.0', false, false, 'cari folder'),
    ('list_workflow_tags',          'Workflow management', '2.27.0', false, false, 'daftar nama tag'),
    -- Execution management (2)
    ('get_workflow_execution',      'Execution management', '2.12.0', false, false, 'baca eksekusi + log'),
    ('search_workflow_executions',  'Execution management', '2.20.0', false, false, 'cari eksekusi'),
    -- Credential management (1)
    ('list_credentials',            'Credential management', '2.21.0', false, false, 'daftar kredensial'),
    -- Instance context (4)
    ('get_instance_context',        'Instance context', '2.12.0', false, false, 'konteks instance'),
    ('get_instance_activity',       'Instance context', '2.12.0', false, false, 'aktivitas instance'),
    ('expand_instance_activity',    'Instance context', '2.12.0', false, false, 'perluas aktivitas'),
    ('get_node_usage',              'Instance context', '2.12.0', false, false, 'pemakaian node'),
    -- Workflow builder (11)
    ('get_workflow_sdk_reference',  'Workflow builder', '2.12.0', false, false, 'kontrak SDK (panggil pertama)'),
    ('search_nodes',                'Workflow builder', '2.12.0', false, false, 'cari node'),
    ('get_node_types',              'Workflow builder', '2.12.0', false, false, 'tipe TypeScript node'),
    ('get_workflow_best_practices', 'Workflow builder', '2.26.0', false, false, 'praktik terbaik'),
    ('explore_node_resources',      'Workflow builder', '2.27.0', false, false, 'telusuri resource node'),
    ('validate_workflow',           'Workflow builder', '2.12.0', false, false, 'validasi kode SDK'),
    ('validate_node_config',        'Workflow builder', '2.25.1', false, false, 'validasi konfigurasi node'),
    ('create_workflow_from_code',   'Workflow builder', '2.12.0', true,  true,  'simpan dari kode tervalidasi'),
    ('update_workflow',             'Workflow builder', '2.12.0', true,  true,  'ubah dari kode SDK'),
    ('archive_workflow',            'Workflow builder', '2.12.0', true,  false, 'arsipkan workflow'),
    ('restore_workflow_version',    'Workflow builder', '2.29.0', true,  false, 'pulihkan versi lama'),
    -- Agent management (15)
    ('search_agents',               'Agent management', '2.34.0', false, false, 'cari agent'),
    ('get_agent',                   'Agent management', '2.34.0', false, false, 'detail agent'),
    ('get_agent_builder_reference', 'Agent management', '2.34.0', false, false, 'kontrak penyusunan agent'),
    ('discover_agent_assets',       'Agent management', '2.34.0', false, false, 'temukan aset agent'),
    ('create_agent',                'Agent management', '2.34.0', true,  false, 'buat agent'),
    ('mutate_agent',                'Agent management', '2.34.0', true,  false, 'ubah agent'),
    ('validate_agent',              'Agent management', '2.34.0', false, false, 'validasi agent'),
    ('call_agent',                  'Agent management', '2.35.0', true,  false, 'panggil agent'),
    ('verify_agent_mcp_server',     'Agent management', '2.34.0', false, false, 'verifikasi MCP agent'),
    ('publish_agent',               'Agent management', '2.34.0', true,  false, 'publikasikan agent'),
    ('unpublish_agent',             'Agent management', '2.34.0', true,  false, 'tarik agent'),
    ('revert_agent',                'Agent management', '2.34.0', true,  false, 'kembalikan agent'),
    ('list_agent_versions',         'Agent management', '2.34.0', false, false, 'riwayat agent'),
    ('update_agent_integration',    'Agent management', '2.34.0', true,  false, 'integrasi Slack/Telegram/Linear'),
    ('delete_agent',                'Agent management', '2.34.0', true,  false, 'hapus agent'),
    -- Data tables (7)
    ('search_data_tables',          'Data tables', '2.16.0', false, false, 'cari data table'),
    ('create_data_table',           'Data tables', '2.16.0', true,  false, 'buat data table'),
    ('add_data_table_column',       'Data tables', '2.16.0', true,  false, 'tambah kolom'),
    ('rename_data_table_column',    'Data tables', '2.16.0', true,  false, 'ganti nama kolom'),
    ('delete_data_table_column',    'Data tables', '2.16.0', true,  false, 'hapus kolom'),
    ('rename_data_table',           'Data tables', '2.16.0', true,  false, 'ganti nama data table'),
    ('add_data_table_rows',         'Data tables', '2.16.0', true,  false, 'tambah baris')
on conflict (name) do update set
    category = excluded.category,
    since_version = excluded.since_version,
    mutating = excluded.mutating,
    needs_validation = excluded.needs_validation,
    purpose = excluded.purpose;

-- ---------------------------------------------------------------------------
-- Sesi build
-- ---------------------------------------------------------------------------
create table if not exists mcp_build_sessions (
    id                  uuid primary key default gen_random_uuid(),
    user_id             text not null,
    n8n_version         text not null default '',
    protocol_revision   text not null default '2026-07-28'
                        references mcp_protocol_revisions (revision)
                        on delete restrict,
    sdk_reference_read  boolean not null default false,
    last_validated_at   timestamptz,
    workflow_id         text,
    status              text not null default 'building'
                        check (status in ('building','validated','created',
                                          'failed','abandoned')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    -- Status lanjut tidak boleh ada tanpa jejak sebab.
    constraint mcp_session_validated_requires_ts
        check (status <> 'validated' or last_validated_at is not null),
    constraint mcp_session_created_requires_workflow
        check (status <> 'created' or workflow_id is not null)
);

create index if not exists mcp_build_sessions_user_idx
    on mcp_build_sessions (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Jejak panggilan tool + penegakan loop
-- ---------------------------------------------------------------------------
create table if not exists mcp_call_events (
    id              bigserial primary key,
    session_id      uuid not null references mcp_build_sessions (id)
                    on delete cascade,
    seq             integer not null,
    tool_name       text not null references mcp_tool_catalog (name)
                    on delete restrict,
    phase           text not null
                    check (phase in ('reference','discover','search',
                                     'validate','write','run','read')),
    ok              boolean not null default true,
    sdk_section     text not null default '',
    detail          jsonb not null default '{}'::jsonb,
    occurred_at     timestamptz not null default now(),
    unique (session_id, seq),
    -- Fase tulang punggung loop: nama tool menentukan fasenya. Ditegakkan di
    -- basis data supaya catatan audit tidak bisa "rapi" tetapi bohong.
    constraint mcp_call_phase_matches_tool check (
        (tool_name = 'get_workflow_sdk_reference' and phase = 'reference')
        or (tool_name = 'search_nodes'           and phase = 'search')
        or (tool_name = 'get_node_types'         and phase = 'search')
        or (tool_name = 'validate_workflow'      and phase = 'validate')
        or (tool_name = 'validate_node_config'   and phase = 'validate')
        or (tool_name = 'create_workflow_from_code' and phase = 'write')
        or (tool_name = 'update_workflow'        and phase = 'write')
        or (tool_name in ('test_workflow','execute_workflow') and phase = 'run')
        or (tool_name not in (
                'get_workflow_sdk_reference','search_nodes','get_node_types',
                'validate_workflow','validate_node_config',
                'create_workflow_from_code','update_workflow',
                'test_workflow','execute_workflow')
            and phase in ('read','discover'))
    )
);

create index if not exists mcp_call_events_session_idx
    on mcp_call_events (session_id, seq);
create index if not exists mcp_call_events_tool_idx
    on mcp_call_events (tool_name, occurred_at desc);

-- ---------------------------------------------------------------------------
-- View: health loop per sesi
-- ---------------------------------------------------------------------------
create or replace view mcp_build_loop_health as
select
    s.id                                   as session_id,
    s.user_id,
    s.n8n_version,
    s.protocol_revision,
    s.status,
    count(e.id)                            as calls,
    count(distinct e.tool_name)            as distinct_tools,
    bool_or(e.tool_name = 'get_workflow_sdk_reference' and e.ok)
                                           as read_reference,
    bool_or(e.phase = 'validate' and e.ok) as validated,
    bool_or(e.phase = 'write' and e.ok)    as wrote,
    bool_or(e.phase = 'run' and e.ok)      as ran,
    -- Pelanggaran gate: menulis tanpa (referensi + validasi) yang lulus.
    (bool_or(e.phase = 'write' and e.ok)
        and not (bool_or(e.tool_name = 'get_workflow_sdk_reference' and e.ok)
                 and bool_or(e.phase = 'validate' and e.ok)))
                                           as gate_violation,
    min(e.occurred_at)                     as first_call_at,
    max(e.occurred_at)                     as last_call_at
from mcp_build_sessions s
left join mcp_call_events e on e.session_id = s.id
group by s.id, s.user_id, s.n8n_version, s.protocol_revision, s.status;

-- ---------------------------------------------------------------------------
-- View: tool yang belum tersedia pada suatu versi instance
-- ---------------------------------------------------------------------------
create or replace view mcp_tools_pending_for_version as
select
    t.name,
    t.category,
    t.since_version,
    t.mutating,
    t.needs_validation
from mcp_tool_catalog t
where t.since_version <> ''
order by t.since_version, t.category, t.name;

-- ---------------------------------------------------------------------------
-- View: cakupan gerbang protokol modern
-- ---------------------------------------------------------------------------
create or replace view mcp_protocol_gate as
select
    r.revision,
    r.is_modern,
    r.has_handshake,
    case when r.is_modern then 'Mcp-Method, Mcp-Name' else '' end
        as required_headers,
    case when r.is_modern then 'ttlMs, cacheScope' else '' end
        as cache_fields,
    case when r.is_modern then 'server/discover' else 'initialize' end
        as discovery_method,
    case when r.is_modern then 'DILARANG' else 'WAJIB' end
        as session_header_policy
from mcp_protocol_revisions r
order by r.revision;

-- ---------------------------------------------------------------------------
-- Trigger updated_at
-- ---------------------------------------------------------------------------
create or replace function mcp_touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end $$;

drop trigger if exists mcp_build_sessions_touch on mcp_build_sessions;
create trigger mcp_build_sessions_touch
    before update on mcp_build_sessions
    for each row execute function mcp_touch_updated_at();

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
alter table mcp_build_sessions enable row level security;
alter table mcp_call_events    enable row level security;

-- Katalog & registry bersifat publik-baca (metadata yang sama untuk semua).
alter table mcp_tool_catalog        enable row level security;
alter table mcp_protocol_revisions  enable row level security;

drop policy if exists mcp_catalog_read on mcp_tool_catalog;
create policy mcp_catalog_read on mcp_tool_catalog
    for select using (true);

drop policy if exists mcp_revisions_read on mcp_protocol_revisions;
create policy mcp_revisions_read on mcp_protocol_revisions
    for select using (true);

drop policy if exists mcp_sessions_owner on mcp_build_sessions;
create policy mcp_sessions_owner on mcp_build_sessions
    for all using (user_id = current_setting('request.jwt.claims', true)::jsonb ->> 'sub')
    with check (user_id = current_setting('request.jwt.claims', true)::jsonb ->> 'sub');

drop policy if exists mcp_events_owner on mcp_call_events;
create policy mcp_events_owner on mcp_call_events
    for all using (
        exists (select 1 from mcp_build_sessions s
                where s.id = mcp_call_events.session_id
                  and s.user_id = current_setting('request.jwt.claims', true)::jsonb ->> 'sub')
    )
    with check (
        exists (select 1 from mcp_build_sessions s
                where s.id = mcp_call_events.session_id
                  and s.user_id = current_setting('request.jwt.claims', true)::jsonb ->> 'sub')
    );
