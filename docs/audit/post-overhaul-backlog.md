# Post-overhaul backlog

Status checkpoint: 2026-09-24 · branch `level-3-experiment`

## Selesai dan terverifikasi

- Slack OAuth authorize/callback/status sudah tersedia; authorize memakai state server-side dan callback menolak state invalid.
- UI `/settings` memiliki kartu Google Sheets/Slack dengan status, connect, disconnect, loading, dan error handling.
- Jalur tool Google/Slack mengembalikan `needs_oauth` dengan `connect_url`; chat merender Connect inline.
- Telegram memakai token Vault lebih dulu, lalu fallback `TELEGRAM_BOT_TOKEN` untuk dev/self-hosted. Fallback harus dimatikan di SaaS multi-tenant.
- Execution report memakai locale ID/EN melalui `Accept-Language`.
- Model policy memiliki allowlist free, wildcard plus, deny untuk tier unknown, dan log model blocked.
- Backend suite terakhir: **183 passed**.

## Perlu verifikasi pengguna

- Klik consent Google OAuth dan Slack OAuth di akun/workspace yang benar.
- Pastikan Slack redirect URI `http://localhost:8000/oauth/slack/callback` terdaftar.
- Setelah connect asli, verifikasi status, disconnect, dan pengiriman pesan end-to-end.

## Sisa pekerjaan

- Jalankan probe screenshot Settings dengan dev/production frontend yang benar dan simpan artefak desktop/mobile.
- Ambil screenshot report ID dan EN.
- Jalankan `tests/l3-level3.spec.ts`; jika kuota habis, catat `SKIPPED` dengan alasan.
- Verifikasi `tsc` dan `npm run build` setelah semua perubahan frontend.
- Commit perubahan yang tersisa dan update PR #2 dalam status draft tanpa merge.

## Risiko yang diketahui

- Fallback Telegram `.env` tidak aman bila aktif pada deployment SaaS shared.
- E2E OAuth tidak boleh diklaim hanya dari mock; mock hanya membuktikan UI dan kontrak endpoint.
- Redirect URI Slack harus cocok antara `APP_UI_URL`/konfigurasi lokal dan api.slack.com.
