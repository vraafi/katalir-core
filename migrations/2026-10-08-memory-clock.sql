-- ============================================================================
-- migrations/2026-10-08-memory-clock.sql
-- Fitur #11 (AI Agent Memory) — perbaikan BUG-TTL
-- ============================================================================
-- LATAR BELAKANG (terbukti lewat probe 8 Okt 2026):
--
--   `memory_manager.remember(ttl_seconds=N)` menghitung `expires_at` dari jam
--   container aplikasi, lalu menyimpannya sebagai timestamp absolut.
--   Postgres membandingkannya dengan `now()` MILIKNYA di RPC
--   `match_agent_memory` (`am.expires_at > now()`).
--
--   Jam container uji drift ~2 detik di DEPAN jam Postgres. Akibatnya untuk
--   TTL pendek baris langsung lahir dengan `expires_at < now()` dan RPC
--   menyaringnya sejak awal — memori baru tidak pernah terlihat.
--
--   BUKTI (teks & agent_id identik, hanya TTL yang berbeda):
--     TTL=2s   -> expires_at > now() : True (jam lokal)  -> recall 0 baris
--     TTL=300s -> expires_at > now() : True              -> recall 1 baris
--   Perbedaan 2s vs 300s juga membatalkan hipotesis embedding/top-K.
--
-- SOLUSI: aplikasi mengambil basis waktu DARI DB lewat `memory_now()`,
-- sehingga `expires_at` selalu dihitung pada jam yang sama dengan yang
-- dipakai `match_agent_memory` untuk menyaring. Jam aplikasi tidak lagi
-- relevan.
--
-- CARA JALANKAN: buka Supabase Dashboard -> SQL Editor -> tempel file ini
-- -> Run. Idempoten, aman dijalankan berulang.
-- ============================================================================

create or replace function public.memory_now()
returns timestamptz
language sql
stable
security invoker
as $function$
  select now();
$function$;

comment on function public.memory_now() is
  'Jam server DB — basis waktu untuk expires_at di agent_memory (BUG-TTL 8 Okt 2026)';

-- Hanya user terautentikasi + service_role yang boleh memanggil.
revoke all on function public.memory_now() from public;
grant execute on function public.memory_now() to authenticated, service_role;

-- ----------------------------------------------------------------------------
-- VERIFIKASI setelah menjalankan:
--   select public.memory_now();
--   -- harus mengembalikan timestamptz UTC sekarang
--
-- Lalu dari aplikasi:
--   python _probe_ttl5.py
--   -- TTL=2s harus recall 1 baris (sebelumnya 0)
-- ----------------------------------------------------------------------------
