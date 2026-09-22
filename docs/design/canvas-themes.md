# Tema Kanvas — definisi & kontrak (FASE 3, 2026-09-22)

Empat tema yang bisa dipilih pengguna. Implementasi: `globals.css` (blok
`[data-canvas-theme="…"]`) + `src/features/builder/themes/canvas-themes.ts`
(nilai TS untuk hal yang tidak bisa dibaca CSS oleh library).

Atribut `data-canvas-theme` dipasang di `<html>` oleh `CanvasThemeProvider`,
jadi seluruh turunan (kanvas, toolbar, palette, minimap, panel konfigurasi)
mewarisi token yang sama tanpa prop-drilling.

## 1. Perbandingan tema

| # | Nama | Gaya | Canvas BG | Node BG | Accent | Edge (diam) | Edge (mengalir) |
|---|---|---|---|---|---|---|---|
| 1 | **Midnight** (default) | n8n-inspired, "developer tool at midnight" | `#1B1F23` | `#282E36` | violet-indigo `#6366F1` | `#5C9DF5` | `#8B5CF6` |
| 2 | **Daylight** | bersih, kontras tinggi | `#FAFAF8` | `#FFFFFF` | violet-indigo `#6366F1` | `#6366F1` | `#8B5CF6` |
| 3 | **Cyberpunk** | neon glow | `#0A0A0F` | `#1A1A2E` | `#00FFD5` + `#FF2E63` | `#00FFD5` | `#FF2E63` |
| 4 | **Minimal** | ultra-clean flat | `#FFFFFF` | `#F5F5F5` | `#18181B` | `#A1A1AA` | `#18181B` |

Kontrak misi (`[data-canvas-theme="…"]`) terpenuhi 1:1 untuk token yang diminta:
`--canvas-bg`, `--canvas-grid-color`, `--node-bg`, `--node-border`,
`--node-trigger-color`, `--node-action-color`, `--node-success-glow`,
`--node-error-glow`, `--node-pulse-color`, `--edge-color`,
`--edge-animated-color`, `--panel-bg`, `--text-primary`, `--text-secondary`.

> Catatan penamaan: implementasi memakai prefiks internal `--canvas-panel-bg`,
> `--canvas-text-primary`, `--canvas-text-secondary` (supaya tidak bertabrakan
> dengan token aplikasi `--bg`/`--fg`), lalu blok `[data-canvas-theme]` membuat
> **alias** dengan nama PERSIS seperti kontrak misi. Jadi kode mana pun boleh
> membaca `var(--panel-bg)` / `var(--text-primary)`.

## 2. Warna per kategori node (pola n8n, diadaptasi)

| Tema | Trigger | Agent | MCP Tool |
|---|---|---|---|
| Midnight | `#FF6D5A` (oranye) | `#5C9DF5` (biru) | `#8B5CF6` (violet) |
| Daylight | `#EA580C` | `#4F46E5` | `#7C3AED` |
| Cyberpunk | `#FF2E63` | `#00FFD5` | `#B14AED` |
| Minimal | `#18181B` | `#18181B` | `#52525B` |

**Adaptasi yang disengaja:** n8n memakai oranye sebagai warna primary. Katalir
TIDAK mengubah accent-nya: accent tetap violet-indigo (oklch 0.62 0.18 275)
sesuai keputusan strategis handoff §B. Yang diadopsi dari n8n adalah POLA-nya
(warna berbeda per kategori + glow semantic untuk status eksekusi).

## 3. Jembatan ke React Flow (`--xy-*`)

Tema tidak mengoper puluhan prop ke komponen library. Sebagai gantinya setiap
blok tema menyetel variabel yang MEMANG dibaca `@xyflow/react` (ditemukan dari
`node_modules/@xyflow/react/dist/style.css`):

| Variabel | Dipakai oleh |
|---|---|
| `--xy-background-color` | latar `.react-flow` |
| `--xy-background-pattern-color` | `<Background variant="dots">` (fill pattern) |
| `--xy-edge-stroke`, `--xy-edge-stroke-width` | edge bawaan & BaseEdge |
| `--xy-edge-stroke-selected` | edge terpilih |
| `--xy-handle-background-color`, `--xy-handle-border-color` | handle |
| `--xy-minimap-background-color`, `--xy-minimap-mask-background-color`, `--xy-minimap-node-background-color` | MiniMap |
| `--xy-controls-button-*` | tombol Controls |

Nilai TS (`canvas-themes.ts`) hanya dipakai untuk yang tidak bisa dibaca CSS:
`colorMode` React Flow, prop `color` pada `<Background>`, dan `maskColor`/
`nodeColor` pada `<MiniMap>`. **Nilai TS dan CSS diuji silang** oleh
`tests/canvas-theme.spec.ts` (computed style harus sama dengan nilai TS), jadi
dua sumber ini tidak bisa menyimpang tanpa tes merah.

## 4. Status node (kontrak visual)

| Status | Dot | Efek | Indikator resmi React Flow |
|---|---|---|---|
| `initial` | abu (`--text-secondary`) | tanpa glow | — (tidak ada pembungkus) |
| `loading` | amber `#F59E0B` | pulse ring (`::after` scale 0.6→1.6) + border glow berjalan (`node-executing-glow` 2s) | `NodeStatusIndicator variant="border"` (conic-gradient berputar) |
| `success` | `--node-success-glow` | `box-shadow: 0 0 8px` warna token | `variant="border"` (border hijau) |
| `error` | `--node-error-glow` | `box-shadow: 0 0 8px` warna token | `variant="overlay"` (overlay + spinner) |

Glow border node yang dieksekusi memakai `--node-pulse-color` (kontrak
MachinaOS) dan beranimasi 2s ease-in-out seperti pola n8n v2.

## 5. Aksesibilitas

- **prefers-reduced-motion**: pulse ring, glow-border executing, animasi edge
  `edge-flow`, spinner status, dan transisi Auto Layout semuanya dimatikan pada
  `@media (prefers-reduced-motion: reduce)`; status tetap terbaca dari warna dot
  + label teks ("Siap/Berjalan/Berhasil/Gagal").
- **Status dot `aria-hidden="true"`** (dekoratif). Makna dibawa teks pendamping
  (`title` + label), sesuai pola n8n.
- **Kontras**: label status memakai `--text-secondary`; pada Midnight
  `#8B909A` di atas `#282E36` ≈ 4.9:1 (AA untuk teks kecil ≥ 11px bold), pada
  Daylight `#52525B` di atas `#FFFFFF` ≈ 8.6:1. Angka ini diambil dari rasio
  luminansi token, bukan diukur piksel demi piksel di screenshot.
- **Tap target 44×44** di perangkat sentuh (`@media (pointer: coarse)`): semua
  tombol toolbar + CTA empty state. Diuji: `C14` mengukur seluruh tombol
  toolbar = 44×44 (10 tombol, 0 yang lebih kecil).
- **Handle**: 12px di desktop; 20px di perangkat sentuh dengan area sentuh
  diperluas ke 44×44 memakai pseudo-element `::after` (pseudo-element di-hit-test
  sebagai bagian elemen induk, jadi React Flow tetap menerima pointerdown).
  Terukur: desktop `12×12` (7 handle), mobile `20×20` (7 handle).

## 6. Persistensi

| Lapisan | Status | Bukti |
|---|---|---|
| URL `?canvasTheme=<id>` | works (override sesaat, tidak dipersist) | spec tema memakai ini untuk determinisme |
| `localStorage["katalir.canvasTheme"]` | works | `C…`: setelah memilih Cyberpunk, `localStorage` berisi `cyberpunk`; reload TANPA parameter memakai tema tersimpan |
| Supabase profile | **BELUM (gap terdokumentasi)** | Backend repo ini tidak punya endpoint preferensi UI (`GET /me` hanya `{email, tier}`). Menambah kolom = schema migration, dan itu keputusan strategis yang tidak ada di misi → tidak dilakukan. `syncToProfile()` disediakan sebagai titik sambung (no-op, dengan catatan) supaya FASE 4 tinggal mengisi |

## 7. Batasan yang diketahui (jujur)

1. **Panel konfigurasi memakai kelas warna keras lama** (`text-gray-100`, dst).
   Alih-alih menulis ulang `ConfigPanel` di FASE 3, warna teks + kontrol form
   diarahkan ke token tema lewat pembungkus `.k-config-host` (blok CSS
   terdokumentasi). TECH-DEBT FASE 4: ganti kelas kerasnya lalu hapus blok itu.
2. **Minimap auto-hide** hanya berdasarkan `pointer: coarse` atau lebar
   < 768px; belum ada preferensi pengguna untuk memaksa tampil/sembunyi
   (tombol toggle toolbar sudah ada, state-nya tidak dipersist).
3. **Deep-tema ketiga** (mis. menambah "Solarized") belum ada: daftar tema
   didefinisikan di dua tempat (TS + CSS) dan divalidasi silang oleh tes; tema
   baru harus ditambah di keduanya.

