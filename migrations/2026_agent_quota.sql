-- 2026_agent_quota.sql
-- Kuota HARIAN per node-agent (bukan global per user).
--
-- PRINSIP: kuota global di `user_usage` tetap jadi pagar terakhir.
-- Tabel ini TIDAK menggantikannya: ini pembagian di dalam pagar itu,
-- supaya satu workflow dengan 3 agent tidak menghabiskan seluruh jatah
-- user dari satu node yang rakus.
--
-- RESET: 00:00 WIB (UTC+7), sama seperti kuota global, supaya angka
-- di kedua tempat bisa dibandingkan tanpa konversi manual.
--
-- Tabel ini di-key per `user_id` UUID. Kuota global memakai `email`
-- TEXT karena tabelnya sudah lama ada; tabel baru boleh pakai UUID
-- karena tidak ada data lama yang perlu dimigrasi. Yang penting RLS.

CREATE TABLE IF NOT EXISTS agent_quota (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workflow_id    UUID,
  node_id        TEXT NOT NULL,
  agent_name     TEXT NOT NULL DEFAULT '',
  provider       TEXT NOT NULL DEFAULT '',
  model          TEXT NOT NULL DEFAULT '',
  quota_daily    INT  NOT NULL DEFAULT 100 CHECK (quota_daily >= 0),
  used_daily     INT  NOT NULL DEFAULT 0  CHECK (used_daily  >= 0),
  day_key        DATE NOT NULL DEFAULT ((now() AT TIME ZONE 'Asia/Jakarta')::date),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, workflow_id, node_id)
);

COMMENT ON TABLE agent_quota IS
  'Kuota harian per node-agent, dihitung per hari WIB. Pagar terakhir tetap user_usage.daily_*.';

CREATE INDEX IF NOT EXISTS idx_agent_quota_user ON agent_quota(user_id);

-- ---------------------------------------------------------------------------
-- RLS
-- Tanpa ini, satu user bisa membaca kuota user lain hanya dengan
-- menebak UUID. Policy ditulis eksplisit, bukan `FOR ALL`: untuk tabel
-- kuota, `FOR ALL` memberi user hak DELETE pada baris siapa pun yang
-- masih milik dia sendiri, dan tidak ada gunanya.
-- ---------------------------------------------------------------------------
ALTER TABLE agent_quota ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_quota_read_own ON agent_quota;
CREATE POLICY agent_quota_read_own ON agent_quota
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS agent_quota_insert_own ON agent_quota;
CREATE POLICY agent_quota_insert_own ON agent_quota
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS agent_quota_update_own ON agent_quota;
CREATE POLICY agent_quota_update_own ON agent_quota
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- TIDAK ada policy DELETE. Baris lama dibersihkan dari backend, bukan
-- oleh user.

-- ---------------------------------------------------------------------------
-- Penambahan usage ATOMIK, dengan reset harian.
--
-- Kenapa RPC dan bukan read-modify-write dari Python: dua eksekusi
-- paralel bisa membaca `used_daily` yang sama lalu sama-sama menulis
-- +1, sehingga user bisa melewati kuota. `UPDATE ... SET x = x + n`
-- bersifat atomik di Postgres.
--
-- Reset dilakukan DI DALAM fungsi yang sama lewat `day_key`, jadi
-- request setelah tengah malam WIB otomatis menghitung ke hari baru
-- tanpa cron. Ini menghapus ketergantungan pada cron yang bisa gagal
-- atau ternyata tidak terpasang.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION increment_agent_quota(
  p_user_id     UUID,
  p_workflow_id UUID,
  p_node_id     TEXT,
  p_amount      INT DEFAULT 1,
  p_quota_daily INT DEFAULT NULL
) RETURNS TABLE (
  allowed     BOOLEAN,
  used_daily  INT,
  quota_daily INT,
  remaining   INT,
  day_key     DATE
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_today DATE := (now() AT TIME ZONE 'Asia/Jakarta')::date;
  v_row   agent_quota%ROWTYPE;
BEGIN
  IF p_amount < 1 THEN
    RAISE EXCEPTION 'amount harus >= 1, dapat %', p_amount;
  END IF;

  INSERT INTO agent_quota (user_id, workflow_id, node_id, day_key)
  VALUES (p_user_id, p_workflow_id, p_node_id, v_today)
  ON CONFLICT (user_id, workflow_id, node_id) DO NOTHING;

  UPDATE agent_quota
     SET day_key    = v_today,
         -- Reset kalau baris ini masih menunjuk hari sebelumnya.
         used_daily = CASE WHEN day_key = v_today THEN used_daily ELSE 0 END,
         -- `p_quota_daily` hanya dipakai saat baris BARU dibuat (lihat
         -- ON CONFLICT DO NOTHING di atas), jadi mengulang panggilan
         -- dengan angka lebih besar tidak bisa menaikkan jatah sendiri.
         quota_daily = COALESCE(quota_daily, p_quota_daily),
         updated_at  = NOW()
   WHERE agent_quota.user_id = p_user_id
     AND agent_quota.node_id = p_node_id
     AND agent_quota.workflow_id IS NOT DISTINCT FROM p_workflow_id
  RETURNING * INTO v_row;

  -- Melebihi kuota: TIDAK dinaikkan, hasilnya disallowed. Menaikkan
  -- lalu menolak akan membuat angka terlihat terpakai padahal tidak.
  IF v_row.used_daily + p_amount > v_row.quota_daily THEN
    RETURN QUERY SELECT FALSE, v_row.used_daily, v_row.quota_daily, 0, v_row.day_key;
    RETURN;
  END IF;

  UPDATE agent_quota
     SET used_daily = used_daily + p_amount,
         updated_at = NOW()
   WHERE id = v_row.id;

  RETURN QUERY SELECT TRUE, v_row.used_daily + p_amount, v_row.quota_daily,
                      v_row.quota_daily - v_row.used_daily - p_amount, v_row.day_key;
END;
$$;

COMMENT ON FUNCTION increment_agent_quota IS
  'Menambah usage per node-agent secara atomik, mereset di tengah malam WIB, dan menolak tanpa menambah kalau kuota habis.';
