-- ============================================================================
-- 2026-10-08-workflow-templates.sql
-- Fitur #10 — Workflow Templates (kustom per user)
-- ============================================================================
-- Template BAWAAN tidak disimpan di sini: ia konstanta Python di
-- `workflow_templates.py` (selalu tersedia walau Supabase mati).
-- Tabel ini HANYA menyimpan template KUSTOM yang dibuat user.
--
-- Idempoten: aman dijalankan berulang (IF NOT EXISTS / DROP POLICY IF EXISTS).
--
-- Cara menjalankan: Supabase Dashboard -> SQL Editor -> tempel -> Run.
-- (Agen juga bisa menerapkan via koneksi Postgres langsung, lihat
--  `_ddl_apply.py`; verifikasi skema via information_schema.)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS public.workflow_templates (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL,
    name         text NOT NULL,
    description  text NOT NULL DEFAULT '',
    category     text NOT NULL DEFAULT 'ops',
    tags         text[] NOT NULL DEFAULT '{}',
    flow_data    jsonb NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT workflow_templates_name_not_blank CHECK (length(btrim(name)) > 0)
);

-- Daftar template milik user (sidebar galeri) — terbaru dulu.
CREATE INDEX IF NOT EXISTS idx_templates_user_created
    ON public.workflow_templates (user_id, created_at DESC);

-- Filter kategori.
CREATE INDEX IF NOT EXISTS idx_templates_category
    ON public.workflow_templates (category);

-- Pencarian tag (GIN).
CREATE INDEX IF NOT EXISTS idx_templates_tags
    ON public.workflow_templates USING gin (tags);

-- ---------------------------------------------------------------------------
-- RLS: user hanya boleh melihat/mengubah template miliknya.
-- ---------------------------------------------------------------------------
ALTER TABLE public.workflow_templates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS wt_select_own ON public.workflow_templates;
CREATE POLICY wt_select_own ON public.workflow_templates
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS wt_insert_own ON public.workflow_templates;
CREATE POLICY wt_insert_own ON public.workflow_templates
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS wt_update_own ON public.workflow_templates;
CREATE POLICY wt_update_own ON public.workflow_templates
    FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS wt_delete_own ON public.workflow_templates;
CREATE POLICY wt_delete_own ON public.workflow_templates
    FOR DELETE USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- updated_at otomatis
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.touch_workflow_templates()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_touch_workflow_templates ON public.workflow_templates;
CREATE TRIGGER trg_touch_workflow_templates
    BEFORE UPDATE ON public.workflow_templates
    FOR EACH ROW EXECUTE FUNCTION public.touch_workflow_templates();

-- ============================================================================
-- SELESAI. Verifikasi cepat:
--   SELECT column_name, data_type FROM information_schema.columns
--    WHERE table_name = 'workflow_templates' ORDER BY ordinal_position;
-- ============================================================================
