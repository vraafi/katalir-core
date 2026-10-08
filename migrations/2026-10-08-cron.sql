-- ============================================================================
-- 2026-10-08-cron.sql
-- Fitur #1 — Scheduled Trigger (cron) untuk workflow Katalir
-- ============================================================================
-- STATUS: tabel ini SUDAH ADA di Supabase produksi (project qmukkphwaajzbqjrcvaz)
-- dan sudah diverifikasi via koneksi Postgres langsung pada 8 Okt 2026.
-- File ini adalah migration idempoten (aman dijalankan berulang) untuk:
--   1. Reproduksi lingkungan baru (staging/dev/test)
--   2. Dokumentasi skema resmi
--
-- Cara menjalankan (jika perlu):
--   Supabase Dashboard -> SQL Editor -> tempel isi file ini -> Run
--   ATAU via psql/psycopg2 dengan connection string project.
--
-- CATATAN AKSES: agen TIDAK memakai dashboard. Verifikasi skema dilakukan via
-- koneksi Postgres langsung (pooler aws-0-ap-southeast-1, port 6543);
-- kredensial tetap di .env dan tidak pernah dicetak.
-- ============================================================================

-- Prasyarat: croniter (pure-python) dipakai di aplikasi untuk menghitung
-- next_fire_at. Tidak ada ekstensi Postgres tambahan yang dibutuhkan.

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Tabel utama: satu jadwal per workflow (UNIQUE workflow_id)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.workflow_schedules (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id       uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    user_id           uuid NOT NULL,
    cron_expression   text NOT NULL,
    timezone          text NOT NULL DEFAULT 'Asia/Jakarta',
    enabled           boolean NOT NULL DEFAULT true,
    last_fired_at     timestamptz,
    last_execution_id uuid,
    next_fire_at      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Index: pemindaian "due" oleh loop scheduler (enabled & next_fire_at <= now)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_schedules_due
    ON public.workflow_schedules (next_fire_at)
    WHERE enabled = true;

-- Satu jadwal per workflow -> upsert(on_conflict="workflow_id") di endpoint.
CREATE UNIQUE INDEX IF NOT EXISTS uq_schedules_workflow
    ON public.workflow_schedules (workflow_id);

-- ---------------------------------------------------------------------------
-- RLS: user hanya boleh melihat/mengubah jadwal miliknya.
-- Loop scheduler memakai service_role (bypass RLS) dan TETAP memverifikasi
-- ownership di level endpoint (defense in depth).
-- ---------------------------------------------------------------------------
ALTER TABLE public.workflow_schedules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ws_select_own ON public.workflow_schedules;
CREATE POLICY ws_select_own ON public.workflow_schedules
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS ws_insert_own ON public.workflow_schedules;
CREATE POLICY ws_insert_own ON public.workflow_schedules
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS ws_update_own ON public.workflow_schedules;
CREATE POLICY ws_update_own ON public.workflow_schedules
    FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS ws_delete_own ON public.workflow_schedules;
CREATE POLICY ws_delete_own ON public.workflow_schedules
    FOR DELETE USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Track kolom next_fire_at diperbarui otomatis
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.touch_workflow_schedules()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_touch_workflow_schedules ON public.workflow_schedules;
CREATE TRIGGER trg_touch_workflow_schedules
    BEFORE UPDATE ON public.workflow_schedules
    FOR EACH ROW EXECUTE FUNCTION public.touch_workflow_schedules();

-- ============================================================================
-- SELESAI. Verifikasi cepat:
--   SELECT column_name, data_type FROM information_schema.columns
--    WHERE table_name = 'workflow_schedules' ORDER BY ordinal_position;
-- ============================================================================
