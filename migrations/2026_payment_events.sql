-- 2026_payment_events.sql
-- Idempotensi webhook Dodo Payments (audit billing 2026-09-18).
--
-- KENAPA: Dodo punya RETRY otomatis + "bulk replay" (docs resmi). Tanpa tabel
-- ini, satu pembayaran bisa dikredit BERKALI-KALI (double-credit), dan sebaliknya
-- tidak ada cara membuktikan sebuah event sudah diproses.
--
-- `status` dipakai (bukan sekadar keberadaan baris) supaya alur aman-dua-arah:
--   * klaim  -> INSERT status='pending'  (PK menahan duplikat -> race-safe)
--   * sukses -> UPDATE status='processed'
--   * gagal  -> baris tetap 'pending', sehingga RETRY berikutnya boleh
--               memproses ulang (uang user tidak hilang karena kegagalan
--               sementara di pihak kita).

CREATE TABLE IF NOT EXISTS payment_events (
  webhook_id   TEXT PRIMARY KEY,
  payment_id   TEXT,
  event_type   TEXT,
  amount       NUMERIC,
  email        TEXT,
  status       TEXT NOT NULL DEFAULT 'pending',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ
);

-- Lookup per pembayaran (audit/rekonsiliasi dengan dashboard Dodo).
CREATE INDEX IF NOT EXISTS idx_payment_events_payment_id
  ON payment_events(payment_id);

-- Antrean pemulihan: cari event yang diklaim tetapi tidak pernah selesai.
CREATE INDEX IF NOT EXISTS idx_payment_events_status
  ON payment_events(status);

COMMENT ON TABLE payment_events IS
  'Idempotensi webhook Dodo Payments: webhook_id unik + status pending/processed';

-- CATATAN SERVICE ROLE: backend memakai SUPABASE_SERVICE_KEY sehingga RLS
-- dilewati. Bila kelak RLS diaktifkan di tabel ini, tambahkan policy untuk
-- service role (atau biarkan service role bypass seperti tabel lain).
ALTER TABLE payment_events ENABLE ROW LEVEL SECURITY;