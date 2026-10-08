-- 2026_advanced_scheduling.sql — Fitur #2 Advanced Scheduling (Okt 2026)
-- Menambah kolom untuk: kondisi, dependency antar-jadwal, dan label di UI.
-- Idempotent (IF NOT EXISTS) supaya aman dijalankan berulang.

ALTER TABLE IF EXISTS workflow_schedules
    ADD COLUMN IF NOT EXISTS "condition" text;

ALTER TABLE IF EXISTS workflow_schedules
    ADD COLUMN IF NOT EXISTS depends_on jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE IF EXISTS workflow_schedules
    ADD COLUMN IF NOT EXISTS label text;

-- Indeks ringan untuk pencarian label di UI.
CREATE INDEX IF NOT EXISTS idx_workflow_schedules_label
    ON workflow_schedules (label);

-- Verifikasi
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'workflow_schedules'
  AND column_name IN ('condition', 'depends_on', 'label')
ORDER BY column_name;
