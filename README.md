# Katalir

AI Agent Builder SaaS dengan production di `katalir.de5.net`.

## Cara Lanjut Kerja
Lihat `AGENT_PLAYBOOK.md`. Jalankan `scripts/auto-work.ps1` untuk instruksi.

## Migrasi Database (WAJIB sebelum fitur baru dipakai)

Beberapa fitur butuh tabel/RPC baru di Supabase. Jalankan SQL ini di
**Supabase Dashboard → SQL Editor**:

| File | Untuk fitur | Isi |
|---|---|---|
| `migrations/2026-10-08-cron.sql` | #1 Scheduled Trigger | tabel `workflow_schedules` + index + trigger |
| `migrations/2026-10-08-memory-clock.sql` | #11 AI Agent Memory (perbaikan BUG-TTL) | RPC `memory_now()` |

Semua file migrasi **idempoten** — aman dijalankan berulang.

Catatan: `migrations/2026-10-08-memory-clock.sql` sudah diterapkan ke proyek
Supabase saat ini (8 Okt 2026). File ini disimpan sebagai sumber kebenaran
kalau proyek di-restore/kloning.
