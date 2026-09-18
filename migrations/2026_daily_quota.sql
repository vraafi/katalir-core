-- 2026_daily_quota.sql
-- Kuota HARIAN per model (struktur bisnis final 2026-09-18).
--
-- PRINSIP: 1 request = 1 RPD, dihitung PER HARI, reset 00:00 **WIB** (UTC+7).
-- Kolom lama (`free_chat_count`, `plus_chat_count`) tetap ada untuk kompatibilitas
-- dengan `execution_engine.guard_execution` (metered eksekusi) -- JANGAN dihapus.
--
-- BUCKET: `gemma` = jalur gratis (Gemma + model gratis lain + flash-lite internal),
-- `flash` = DeepSeek Flash, `pro` = DeepSeek Pro.

ALTER TABLE user_usage
  ADD COLUMN IF NOT EXISTS daily_gemma    INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS daily_flash    INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS daily_pro      INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS daily_reset_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

COMMENT ON COLUMN user_usage.daily_reset_at IS
  'Awal jendela kuota harian. Reset dilakukan saat TANGGAL WIB berubah.';

-- Pencarian per email (dipakai setiap request /chat).
CREATE INDEX IF NOT EXISTS idx_user_usage_email ON user_usage(email);

-- ---------------------------------------------------------------------------
-- Kenaikan ATOMIK satu bucket.
-- Kenapa RPC, bukan read-modify-write dari backend: dua request paralel bisa
-- membaca nilai yang sama lalu sama-sama menulis +1 -> hitungan meleset
-- (user bisa melewati kuota). UPDATE ... SET x = x + 1 bersifat atomik di
-- Postgres. Nama kolom di-whitelist lewat CASE sehingga tidak ada SQL dinamis.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION increment_daily_quota(p_email TEXT, p_bucket TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  IF p_bucket NOT IN ('gemma', 'flash', 'pro') THEN
    RAISE EXCEPTION 'bucket tidak dikenal: %', p_bucket;
  END IF;
  UPDATE user_usage SET
    daily_gemma = daily_gemma + CASE WHEN p_bucket = 'gemma' THEN 1 ELSE 0 END,
    daily_flash = daily_flash + CASE WHEN p_bucket = 'flash' THEN 1 ELSE 0 END,
    daily_pro   = daily_pro   + CASE WHEN p_bucket = 'pro'   THEN 1 ELSE 0 END
  WHERE email = p_email;
END;
$$;

-- Reset jendela harian (dipakai backend saat tanggal WIB berganti).
CREATE OR REPLACE FUNCTION reset_daily_quota(p_email TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE user_usage SET
    daily_gemma = 0, daily_flash = 0, daily_pro = 0, daily_reset_at = NOW()
  WHERE email = p_email;
END;
$$;

ALTER TABLE user_usage ENABLE ROW LEVEL SECURITY;