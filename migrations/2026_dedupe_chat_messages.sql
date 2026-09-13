-- 2026_dedupe_chat_messages.sql
-- Idempotent insert untuk menghilangkan pesan user DUPLIKAT (bug "pesan 2x dalam 1 sesi").
--
-- Root cause (openclaw #69266): POST /chat dapat tiba 2x untuk 1 kiriman logis
-- (retry setelah server-commit, atau double-fire). Tanpa guard, user message
-- di-insert 2x. Solusi: kolom client_request_id (UUID per kiriman) + unique index
-- + insert idempotent di backend (db.add_message).
--
-- Catatan: SEPENUHNYA keyed oleh client_request_id yang pasti dihasilkan frontend
-- per kiriman logis. TIDAK pakai unique (session_id, content) yg bisa salah-blokir
-- kiriman sah teks identik berulang ("halo","halo" adalah 2 pesan sah beda detik).
ALTER TABLE chat_messages
  ADD COLUMN IF NOT EXISTS client_request_id TEXT;

-- Idempotency utama: satu user-pesan per logical send (client_request_id).
-- Partial index: hanya baris ber-client_request_id (tidak mengganggu data lama).
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client_req
  ON chat_messages (client_request_id)
  WHERE client_request_id IS NOT NULL AND role = 'user';