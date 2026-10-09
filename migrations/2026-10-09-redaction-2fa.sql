-- 2026-10-09-redaction-2fa.sql
-- Fitur #11a: kebijakan redaksi eksekusi per-workflow (model n8n 2.16.0/2.26.0)
-- Fitur #11b: kredensial 2FA (TOTP + WebAuthn) + recovery codes + epoch sesi
--
-- Jalankan di Supabase SQL Editor. Idempoten (IF NOT EXISTS / DROP POLICY IF EXISTS).

-- ===========================================================================
-- 1. KEBIJAKAN REDAKSI PER WORKFLOW
-- ===========================================================================
-- `policy` menyimpan bentuk yang sama dengan `execution_redaction.RedactionPolicy.to_dict()`:
--   {"level":"off|production|all","pii_types":[...],
--    "custom_patterns":[{"name","pattern","placeholder"}],
--    "enabled_at":<unix>,"updated_by":"<email>"}
-- Kolom terpisah untuk `level` disediakan supaya bisa di-QUERY/diindeks
-- (laporan kepatuhan: "workflow produksi mana yang masih 'off'?").
CREATE TABLE IF NOT EXISTS public.workflow_redaction (
    workflow_id     uuid PRIMARY KEY REFERENCES public.workflows(id) ON DELETE CASCADE,
    owner           uuid,
    level           text NOT NULL DEFAULT 'off',
    policy          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT workflow_redaction_level_chk
        CHECK (level IN ('off', 'production', 'all'))
);

CREATE INDEX IF NOT EXISTS workflow_redaction_owner_idx
    ON public.workflow_redaction (owner);
CREATE INDEX IF NOT EXISTS workflow_redaction_level_idx
    ON public.workflow_redaction (level);

-- Trigger `updated_at` otomatis.
CREATE OR REPLACE FUNCTION public.touch_workflow_redaction()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS workflow_redaction_touch ON public.workflow_redaction;
CREATE TRIGGER workflow_redaction_touch
    BEFORE UPDATE ON public.workflow_redaction
    FOR EACH ROW EXECUTE FUNCTION public.touch_workflow_redaction();

-- RLS: hanya pemilik workflow yang boleh membaca/menulis kebijakannya.
-- Penegakan instance-wide dibaca dari env server, bukan dari tabel ini,
-- supaya tidak bisa dinaikkan/diturunkan oleh user biasa.
ALTER TABLE public.workflow_redaction ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "redaction_owner_all" ON public.workflow_redaction;
CREATE POLICY "redaction_owner_all" ON public.workflow_redaction
    FOR ALL TO authenticated
    USING (owner = auth.uid())
    WITH CHECK (owner = auth.uid());


-- ===========================================================================
-- 2. KREDENSIAL 2FA
-- ===========================================================================
-- `totp_secret` disimpan TERENKRIPSI (`fernet:<token>`) atau, bila vault
-- belum dikonfigurasi, `plain:<base32>` (dev). Kolom TIDAK boleh dibaca
-- klien: tidak ada policy SELECT untuk `authenticated`.
CREATE TABLE IF NOT EXISTS public.user_2fa (
    user_id             uuid PRIMARY KEY,
    email               text NOT NULL DEFAULT '',
    totp_secret         text NOT NULL DEFAULT '',
    totp_enabled_at     timestamptz,
    webauthn            jsonb NOT NULL DEFAULT '[]'::jsonb,
    recovery_salt       text NOT NULL DEFAULT '',
    recovery_hashes     jsonb NOT NULL DEFAULT '[]'::jsonb,
    recovery_used       jsonb NOT NULL DEFAULT '{}'::jsonb,
    webauthn_challenge  text NOT NULL DEFAULT '',
    webauthn_rp_id      text NOT NULL DEFAULT '',
    webauthn_origins    jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_2fa_enabled_idx
    ON public.user_2fa (totp_enabled_at) WHERE totp_enabled_at IS NOT NULL;

CREATE OR REPLACE FUNCTION public.touch_user_2fa()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS user_2fa_touch ON public.user_2fa;
CREATE TRIGGER user_2fa_touch
    BEFORE UPDATE ON public.user_2fa
    FOR EACH ROW EXECUTE FUNCTION public.touch_user_2fa();

-- RLS aktif TANPA policy apa pun untuk `authenticated`: tabel hanya bisa
-- diakses lewat service role (backend). Ini yang mencegah token/salt/hash
-- kode cadangan bocor ke klien walau anon key dipakai.
ALTER TABLE public.user_2fa ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "user_2fa_no_client_access" ON public.user_2fa;


-- ===========================================================================
-- 3. KEBIJAKAN KEAMANAN INSTANCE
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.security_policy (
    id                  int PRIMARY KEY DEFAULT 1,
    enforced            boolean NOT NULL DEFAULT false,
    allow_webauthn      boolean NOT NULL DEFAULT true,
    enforce_for_sso     boolean NOT NULL DEFAULT false,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    updated_by          text NOT NULL DEFAULT '',
    CONSTRAINT security_policy_singleton CHECK (id = 1)
);

INSERT INTO public.security_policy (id) VALUES (1)
    ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.security_policy ENABLE ROW LEVEL SECURITY;

-- Semua user terautentikasi boleh MELIHAT apakah 2FA diwajibkan (dipakai UI
-- untuk menampilkan banner "siapkan 2FA"), tetapi hanya service role yang
-- bisa mengubahnya.
DROP POLICY IF EXISTS "security_policy_read" ON public.security_policy;
CREATE POLICY "security_policy_read" ON public.security_policy
    FOR SELECT TO authenticated USING (true);


-- ===========================================================================
-- 4. EPOCH SESI (pencabutan token tanpa daftar token)
-- ===========================================================================
-- Token yang terbit SEBELUM `epoch` dianggap tidak sah. Saat 2FA direset/
-- dimatikan, epoch naik -> semua sesi lama gugur sekaligus.
CREATE TABLE IF NOT EXISTS public.user_session_epoch (
    user_id     uuid PRIMARY KEY,
    epoch       double precision NOT NULL DEFAULT 0,
    reason      text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.user_session_epoch ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "session_epoch_read_own" ON public.user_session_epoch;
CREATE POLICY "session_epoch_read_own" ON public.user_session_epoch
    FOR SELECT TO authenticated USING (user_id = auth.uid());
