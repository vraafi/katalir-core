# Audit Navigasi Katalir

Diaudit 2026-09-28 sebelum perbaikan. Semua lokasi di bawah dibaca dari
source, bukan dari memorizing tampilan.

## Ringkasan temuan

Bug-nya nyata, dan ternyata **lebih luas dari logo dan tombol Back**:
tombol "Chat" di shell pun mengarah ke `/`, bukan ke `/chat`.

## Peta rute

| Rute | Isi | Shell mana |
|---|---|---|
| `/` | Landing marketing | `Shell` |
| `/chat` | Aplikasi chat (alias dari `ChatApp`) | `Shell` |
| `/builder` | Builder | `Shell` |
| `/settings`, `/billing`, `/help`, `/integrations`, `/my-integrations` | Halaman akun | `SimplePage` |

`src/app/chat/page.tsx` hanya re-export `default` dari `./ChatApp`, jadi
chat punya satu implementasi dan `/chat` adalah deep-link yang stabil.

## Lokasi tautan yang salah

### 1. Logo di halaman akun

- **File: `nexus-frontend/src/components/SimplePage.tsx:79`**
- `<Link href="/" className="flex items-center" aria-label="Katalir">`
- Dipakai oleh /settings, /billing, /help, /integrations, /my-integrations.
- Efek: user yang sudah login menekan logo dan mendarat di marketing.

### 2. Tombol Back di halaman akun

- **File: `nexus-frontend/src/components/SimplePage.tsx:82-88`**
- `<Link href="/" ...><ArrowLeft .../>{t("common.back")}</Link>`
- Efek: sama, kembali ke landing, bukan ke app.

### 3. Tombol "Chat" di Shell (tidak dilaporkan, tapi salah)

- **File: `nexus-frontend/src/components/shell.tsx:213`**
- `<Link href="/" ...><MessageSquare .../>{t("nav.chat")}</Link>`
- Efek: tombol yang bernama "Chat" justru membuka landing. Ini
  membingungkan dan tidak akan ketahuan kalau hanya logo yang
  diuji.
- Perintah `Chat` di `CommandPalette.tsx:67` juga `go("/")` -- bug
  kembar di tempat lain.

## Yang SUDAH benar (tidak diubah)

- **Logo landing** `src/app/page.tsx:81` sudah `<Link href="/chat">`.
  Sudah sesuai standar: di marketing, logo menuju app.
- **CTA landing** `src/app/page.tsx:64` memakai
  `window.location.assign("/chat")` kalau sudah punya sesi.
- **Tidak ada auto-redirect** dari `/` untuk user login. Ini benar dan
  harus dipertahankan: halaman marketing tetap perlu untuk SEO, dan
  redirect paksa merusak share link.
- `Shell` **tidak punya** tautan logo di header, hanya tombol nav. Jadi
  tidak ada logo shell yang perlu diperbaiki.

## Komponen yang perlu dibuat

Tidak ada satu pun dari tiga hal berikut yang ada di repo:

- `src/hooks/useBack.ts` (hook navigasi balik)
- `src/components/back-button.tsx`
- tracker "sudah pernah navigasi internal" (sessionStorage)

## Bukti bahwa 404 di /integrations/<slug> juga gejalanya

Bagaimana pun link dan tombol Back diperbaiki, `/integrations/<slug>`
karena static export hanya meng-prerender satu slug. Sudah diperbaiki
lewat query-param (`/integrations/catalog?slug=...`) di commit
`ec4230d` dan `92bcce7`.
