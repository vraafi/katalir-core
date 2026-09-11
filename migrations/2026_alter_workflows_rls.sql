-- =============================================================================
-- MIGRASI SUPABASE — RLS workflows (fix security bocor multi-tenant)
-- Root cause lama: policy "workflows_public_all" FOR ALL USING (TRUE)
--   => seluruh user bisa melihat workflow user lain.
-- Fix: tambah kolom user_id + policy owner-only + index.
-- Urutan PENTING utk idempotent / bisa diulang:
--   (a) drop policy yg mereferensikan kolom user_id SEBELUM drop column
--   (b) truncate cascade barulah drop/add column
-- Eksekusi di Supabase Dashboard: SQL Editor -> Run
-- =============================================================================

-- 1) Bersihkan data test (di-approve owner: hanya 2 row "Draft Workflow").
--    CASCADE agar ikut menghapus baris child (execution/relasi) bila ada.
truncate table public.workflows cascade;

-- 2) Hapus policy lama (public_all bocor) + policy owner (kalau ada dari run
--    sebelumnya) — WAJIB drop policy yg mereferensikan user_id TERLEBIH DAHULU.
drop policy if exists "workflows_public_all" on public.workflows;
drop policy if exists "workflows_owner_all" on public.workflows;

-- 3) Pastikan user_id belum ada (backdrop kalau pernah ditambah).
--    Sudah TIDAK ada policy yg mereferensikannya, jadi drop column aman.
alter table public.workflows drop column if exists user_id;

-- 4) Tambah kolom owner (wajib, default diisi dari JWT di backend).
alter table public.workflows
  add column user_id uuid not null references auth.users(id);

-- 5) Aktifkan (kembali) row level security.
alter table public.workflows enable row level security;

-- 6) Policy owner-only: user hanya bisa melihat/menyunting workflow miliknya.
create policy "workflows_owner_all" on public.workflows
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 7) Index untuk akses cepat per-user.
create index if not exists idx_workflows_user_id on public.workflows(user_id);