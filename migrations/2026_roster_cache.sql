-- 2026_roster_cache.sql — cache roster model PERSISTENT (temuan 2026-09-19).
--
-- KENAPA: Railway memakai filesystem EPHEMERAL. Cache gateway sebelum ini
-- hanya `.gw_roster_cache.json` di disk, sehingga setiap deploy/restart instance
-- kehilangan daftar model. Bila satu-satunya probe gateway saat itu meleset,
-- roster jadi kosong dan discovery diam-diam jatuh ke daftar Gemini-only —
-- user melihat "hanya model Google" tanpa penjelasan.
--
-- Tabel ini menyimpan roster terakhir (hasil probe PASS) supaya restart tidak
-- pernah kehilangan daftar provider. Akses lewat service_role (backend),
-- bukan anon. Idempoten: aman dijalankan berulang.

CREATE TABLE IF NOT EXISTS roster_cache (
  id TEXT PRIMARY KEY DEFAULT 'current',
  models JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: aktifkan dan JANGAN buat policy untuk anon/authenticated. Hanya
-- service_role (yang melewati RLS) yang boleh baca/tulis baris ini.
ALTER TABLE roster_cache ENABLE ROW LEVEL SECURITY;