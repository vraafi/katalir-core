-- ===========================================================================
-- Fitur #6 — End-user credentials (berbasis trigger)
-- 9 Okt 2026
--
-- Padanan n8n "End-user credentials" (Enterprise/Preview, docs Okt 2026):
-- sebuah kredensial TEMPLATE dibuat sekali oleh admin; setiap pengguna
-- menghubungkan AKUNNYA SENDIRI. Saat runtime kredensial di-resolve ke akun
-- milik PENGGUNA YANG MEMICU workflow.
--
-- Keamanan token mengikuti RFC 9700 §4.14 (OAuth 2.0 Security BCP):
--   * refresh token WAJIB rahasia saat disimpan (di sini: ciphertext Fernet);
--   * rotasi refresh token + retensi relasi token lama;
--   * deteksi reuse -> cabut seluruh grant.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1) Template kredensial end-user (metadata saja, TIDAK ada token pengguna)
-- ---------------------------------------------------------------------------
create table if not exists public.end_user_credential_templates (
    template_id     text primary key,
    name            text        not null default '',
    -- n8n: hanya tipe berbasis OAuth yang didukung
    kind            text        not null default 'oauth2',
    provider        text        not null default '',
    owner_project   text        not null default '',
    -- Project personal tidak boleh (n8n: team projects only) -> dijaga app layer
    scopes          jsonb       not null default '[]'::jsonb,
    allowed_modes   jsonb       not null default '["manual","chat-hub","mcp-server","form","chat"]'::jsonb,
    client_id       text        not null default '',
    -- required=true -> trigger GAGAL bila pengguna belum menghubungkan akun
    required        boolean     not null default false,
    created_by      text        not null default '',
    deleted         boolean     not null default false,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint euc_template_kind_chk check (kind in ('oauth2', 'oauth1')),
    constraint euc_template_id_chk check (char_length(template_id) between 1 and 128)
);

comment on table public.end_user_credential_templates is
    'Fitur #6: template kredensial end-user (padanan n8n). Metadata saja — token pengguna ada di end_user_credential_connections.';
comment on column public.end_user_credential_templates.allowed_modes is
    'Mode trigger yang boleh me-resolve: manual/chat-hub/mcp-server/form/chat. Form & Chat tambahan butuh n8n User Auth.';
comment on column public.end_user_credential_templates.required is
    'true = trigger gagal bila pengguna pemicu belum menghubungkan akunnya.';

-- ---------------------------------------------------------------------------
-- 2) Koneksi pengguna (satu per pengguna per template) — token TERENKRIPSI
-- ---------------------------------------------------------------------------
create table if not exists public.end_user_credential_connections (
    template_id         text        not null
                        references public.end_user_credential_templates(template_id)
                        on delete cascade,
    user_id             uuid        not null,
    account_label       text        not null default '',
    -- Fernet ciphertext. NILAI MENTAH TIDAK PERNAH disimpan di sini.
    token_blob          text        not null default '',
    scopes              jsonb       not null default '[]'::jsonb,
    -- Naik setiap rotasi (RFC 9700 §4.14.2).
    generation          int         not null default 1,
    -- SHA-256 refresh token yang BERLAKU. Nilai mentah tidak disimpan.
    refresh_fingerprint text        not null default '',
    revoked             boolean     not null default false,
    created_at          timestamptz not null default now(),
    last_used_at        timestamptz,
    updated_at          timestamptz not null default now(),
    primary key (template_id, user_id),
    constraint euc_conn_generation_chk check (generation >= 1)
);

comment on table public.end_user_credential_connections is
    'Fitur #6: koneksi satu pengguna ke satu template. Satu baris per (template_id,user_id) = aturan "one connection per user" n8n.';
comment on column public.end_user_credential_connections.token_blob is
    'Ciphertext Fernet. RFC 9700 §4.14.1 mewajibkan kerahasiaan refresh token saat disimpan.';
comment on column public.end_user_credential_connections.refresh_fingerprint is
    'SHA-256 refresh token aktif, untuk deteksi reuse TANPA menyimpan nilai mentahnya.';

create index if not exists idx_euc_conn_user
    on public.end_user_credential_connections (user_id) where revoked = false;
create index if not exists idx_euc_conn_template
    on public.end_user_credential_connections (template_id) where revoked = false;

-- ---------------------------------------------------------------------------
-- 3) Refresh token yang sudah dipensiunkan -> retensi relasi + deteksi reuse
--    RFC 9700 §4.14.2: "information about the relationship is retained".
-- ---------------------------------------------------------------------------
create table if not exists public.end_user_credential_retired_tokens (
    fingerprint   text primary key,       -- sha256(refresh_token lama)
    template_id   text        not null,
    user_id       uuid        not null,
    generation    int         not null default 1,
    retired_at    timestamptz not null default now()
);

comment on table public.end_user_credential_retired_tokens is
    'Fitur #6: relasi refresh token lama (RFC 9700 §4.14.2). Dipakai untuk mendeteksi reuse -> cabut grant.';

create index if not exists idx_euc_retired_owner
    on public.end_user_credential_retired_tokens (template_id, user_id,
                                                  retired_at desc);

-- ---------------------------------------------------------------------------
-- 4) Peristiwa keamanan token (reuse, expiring, revocation) — audit
-- ---------------------------------------------------------------------------
create table if not exists public.end_user_credential_events (
    id            bigserial primary key,
    template_id   text        not null,
    user_id       uuid,
    event         text        not null,
    detail        jsonb       not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    constraint euc_event_chk check (
        event in ('connected', 'disconnected', 'rotated', 'reuse_detected',
                  'idle_expired', 'scope_denied', 'template_deleted'))
);

comment on table public.end_user_credential_events is
    'Fitur #6: audit peristiwa kredensial end-user. detail TIDAK boleh memuat nilai token.';

create index if not exists idx_euc_events_owner
    on public.end_user_credential_events (template_id, created_at desc);

-- ---------------------------------------------------------------------------
-- 5) Trigger updated_at
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end $$;

drop trigger if exists trg_euc_template_touch
    on public.end_user_credential_templates;
create trigger trg_euc_template_touch
    before update on public.end_user_credential_templates
    for each row execute function public.touch_updated_at();

drop trigger if exists trg_euc_conn_touch
    on public.end_user_credential_connections;
create trigger trg_euc_conn_touch
    before update on public.end_user_credential_connections
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- 6) RLS
--    Token pengguna hanya boleh dibaca oleh: (a) pengguna itu sendiri, dan
--    (b) service_role (backend, yang melakukan resolusi). Admin INSTANCE
--    hanya melihat agregat lewat view di bawah — bukan baris koneksi.
-- ---------------------------------------------------------------------------
alter table public.end_user_credential_templates
    enable row level security;
alter table public.end_user_credential_connections
    enable row level security;
alter table public.end_user_credential_retired_tokens
    enable row level security;
alter table public.end_user_credential_events
    enable row level security;

-- Template: setiap pengguna terautentikasi boleh MELIHAT template (dibagikan
-- lewat mekanisme project), tetapi hanya service_role yang boleh mengubah.
drop policy if exists p_euc_tpl_read on public.end_user_credential_templates;
create policy p_euc_tpl_read on public.end_user_credential_templates
    for select using (auth.uid() is not null and deleted = false);

-- Koneksi: pengguna hanya melihat/mengubah koneksinya SENDIRI.
-- Admin TIDAK punya policy -> tidak bisa membaca baris orang lain.
drop policy if exists p_euc_conn_own on public.end_user_credential_connections;
create policy p_euc_conn_own on public.end_user_credential_connections
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Token pensiun: hanya pemiliknya (backend memakai service_role).
drop policy if exists p_euc_retired_own
    on public.end_user_credential_retired_tokens;
create policy p_euc_retired_own
    on public.end_user_credential_retired_tokens
    for select using (user_id = auth.uid());

-- Peristiwa: pemiliknya saja.
drop policy if exists p_euc_events_own on public.end_user_credential_events;
create policy p_euc_events_own on public.end_user_credential_events
    for select using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- 7) View AGREGAT untuk admin — jumlah koneksi saja, TANPA identitas/rahasia.
--    Meniru perilaku n8n: "An admin can see that a template exists and that it
--    has connections attached. That count is all they see."
-- ---------------------------------------------------------------------------
create or replace view public.end_user_credential_admin_summary as
select t.template_id,
       t.name,
       t.provider,
       t.kind,
       t.required,
       t.deleted,
       count(c.user_id) filter (where c.revoked = false) as connection_count
  from public.end_user_credential_templates t
  left join public.end_user_credential_connections c
         on c.template_id = t.template_id
 group by t.template_id, t.name, t.provider, t.kind, t.required, t.deleted;

comment on view public.end_user_credential_admin_summary is
    'Fitur #6: agregat untuk admin — jumlah koneksi saja. Tidak memuat user_id, token, atau label akun.';
