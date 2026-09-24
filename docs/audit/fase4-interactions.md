# Audit interaksi FASE 4 (settings/billing/help + auth/i18n + palette)

Sumber: `tests/fase4-pages.spec.ts` (12 tes) + `tests/fase4-a11y.spec.ts` (9 tes),
harness dev (`playwright.dev.config.ts`). Semua angka diambil dari output tes
(`AXE`, `CONTRAST`, `FOCUS`, `S1..`, `B1..`, `A1..`, `P1..`).

## Settings (4)

| # | Interaksi | Status | Bukti |
|---|---|---|---|
| S1 | Grup Bahasa / Tema Aplikasi / Tema Kanvas TERPISAH | PASS | posisi vertikal kartu berurutan (`y=361 < 592 < 778`), 3 radiogroup berlabel, 2 di antaranya punya `aria-describedby` |
| S2 | Tema kanvas bisa diganti dari halaman akun | PASS | 4 radio; klik `cyberpunk` → `html[data-canvas-theme]=cyberpunk` + `localStorage[katalir.canvasTheme]=cyberpunk` + `aria-checked=true` |
| S3 | Validasi + status simpan kredensial (Fernet) | PASS | key kosong → tidak menambah; isi key → status `Tersimpan` (aria-live); server `/api/vault/list` akhirnya memuat provider (`after=["telegram","groq"]`), 0 pageerror |
| S4 | Cabut kredensial | PASS | klik `vault-revoke-groq` → daftar server setelahnya `["telegram"]` (provider hilang) |

## Billing (3)

| # | Interaksi | Status | Bukti |
|---|---|---|---|
| B1 | Kartu pemakaian | PASS | `bars=3` progress bar (`role=progressbar`, `aria-valuenow` 0..100), `empty=0`, `skeleton=0` setelah data tiba |
| B2 | Perbandingan paket + checkout Dodo | PASS | tabel 5 baris; `th scope`: 3 kolom + 5 baris; CTA ada dengan `href="https://checkout.dodopayments.com/buy/pdt_0NnsVLn7IzpG8Sokr3pZh?quantity=1"` + `rel=noopener` |
| B3 | Riwayat invoice | PASS | empty-state jujur (tanpa data dummy): "no invoices yet / invoices appear after your first payment." |

## Help (2)

| # | Interaksi | Status | Bukti |
|---|---|---|---|
| H1 | Pencarian menyaring FAQ | PASS | 7 FAQ → isi "00:00" mempersempit ke 1 hasil (cocok dari ISI, bukan judul), `aria-live` mengumumkan "1 results"; kata kunci tak ada → empty-state |
| H2 | Sidebar navigasi + cheat sheet | PASS | 3 tombol bagian; daftar pintasan memuat `Cmd/Ctrl+K`, `Esc`, `Cmd/Ctrl+Z`, `+`, `-`, `0`, `1` (semua punya binding nyata); klik "Kontak" menampilkan kartu kontak |

## Auth + i18n (3)

| # | Interaksi | Status | Bukti |
|---|---|---|---|
| A1 | Login persist | PASS | email di profil `e2e.…@nexus-local.test` sama setelah reload |
| A2 | Logout bersih | PASS | klik Logout di UserMenu → `html[data-auth]=out`, **0** kunci `sb-…-auth-token` tersisa, 0 pageerror |
| A3 | Ganti bahasa tanpa hydration error | PASS | judul halaman berubah ID↔EN, `aria-checked` berpindah, pilihan bertahan setelah reload, 0 pageerror + 0 error konsol berisi "hydrat" |

## Command palette (3)

| # | Interaksi | Status | Bukti |
|---|---|---|---|
| P1 | Cmd/Ctrl+K membuka, Esc menutup | PASS | `[cmdk-input]` hidden → visible (10 item) → hidden |
| P2 | Enter menjalankan item | PASS | ketik "Billing" → 1 item; Enter → URL `/billing`, dialog tertutup |
| P3 | Label/placeholder ikut bahasa | PASS | locale `en` → placeholder `"Type a command or search…"`, `aria-label="Command palette"` |

## Modul terkait (wajib)

| Modul | Status | Bukti |
|---|---|---|
| Vault ↔ Settings | PASS | S3 (simpan → daftar server) + S4 (cabut → hilang dari server); kunci disimpan terenkripsi di server (`/api/vault/save`), panel tidak pernah menampilkan kembali nilainya |
| Auth ↔ semua route | PASS | `routes-no-crash` 6/6 (0 pageerror) + A1/A2 (login persist, logout bersih) |
| i18n ↔ semua route | PASS | A3 (switch + persist) + P3 (palette ikut locale) + `chat`/`quota`/`help`/`settings`/`billing` semuanya lewat `t()` (string keras di `page.tsx` dihapus) |
| Billing ↔ Dodo | PARTIAL | CTA checkout + `href` nyata terverifikasi (B2); **pembayaran end-to-end tidak diuji** (butuh kartu/akun user — aksi user, lihat `fase4-verification.md` §5) |
| Session store ↔ Chat | PASS | `chat-auth` (EMAIL_VISIBLE=2, `CHAT_STATUS=200` dengan balasan nyata) + C10 (canvas save→reload) |
