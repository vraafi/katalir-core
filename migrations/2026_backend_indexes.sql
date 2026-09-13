-- 2026_backend_indexes.sql
-- Fix telemper /sessions lambat (2.6s) + /messages timeout.
--
-- Root cause: query filter/order by user_id / session_id tanpa index -> Postgres
-- full table scan setiap hit; seiring tabel grow (400+ pesan/sesi), latency
-- linijicka tlin. Migration ini tambah index yang dicocok filter+order aktual.
--
-- Catatan: PostgREST (RLS bypass via service_role) + tne indexni filter
-- tblidamka. Ikuti Supabase Performance Advisor recommendation.
--
-- RUN: Supabase Dashboard > SQL Editor > paste + RUN.

-- 1) filter riwayat by user (list_sessions: WHERE user_id = $ LIMIT 100 ORDER created_at DESC)
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id
  ON chat_sessions (user_id);

-- 2) compound: ORDER BY created_at DESC per user (list_sessions)
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_created
  ON chat_sessions (user_id, created_at DESC);

-- 3) filter pesan by session (get_messages: WHERE session_id = $)
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
  ON chat_messages (session_id);

-- 4) compound: ORDER BY created_at ASC per session (get_messages full transcript)
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
  ON chat_messages (session_id, created_at ASC);

-- (optional) ownership check in get_messages/delete_session: WHERE id=X AND user_id=Y
CREATE INDEX IF NOT EXISTS idx_chat_sessions_id_user
  ON chat_sessions (id, user_id);

ANALYZE chat_sessions;
ANALYZE chat_messages;