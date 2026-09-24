# FASE 6 — Regression penuh + mobile + Lighthouse + final (verifikasi)

Tanggal: 2026-09-24. Branch `level-3-experiment`. HEAD saat diukur: `6fbec8e`
(+ perbaikan tap-target sesudahnya). Harness: dev (`:3000` + BE `:8000`),
kecuali Lighthouse yang memakai **build produksi** (`out/`).

## 1. Ringkas hasil

| Kriteria FASE 6 | Ambang | Hasil | Status |
|---|---|---|---|
| Audit interaksi FASE 0-5 | 39+ item | **81 item PASS** (15 + 24 + 10 + 9 + 23) — rekap: `final-interactions.md` | **PASS** |
| E2E Level 3 (S1/S2/S3) | 3/3 | **SKIPPED (jujur, dengan sebab)**: `playwright.config.ts` menolak port 3000 yang sudah dipakai dev (`reuseExistingServer:false` — desain sengaja, lihat kepala config), dan menjalankannya berarti mematikan dev server yang diminta tetap hidup. Selain itu S1/S2 butuh kredensial Telegram nyata + kuota LLM. Tidak ada klaim lulus. Kontrak yang dipakai S1 (`[data-testid="run-report"]` + teks laporan backend) **sengaja dipertahankan** saat kartu laporan FASE 5 dibuat, sehingga spec itu tidak ikut rusak | **SKIPPED** |
| Fix lama tetap aman | — | duplicate-key, drop-position, lifecycle, hydration, dark, AuthProvider — semuanya di suite dev | **PASS** |
| Mobile 6 halaman × 3 device | pageerror 0, tap ≥ 44, layout utuh | **18/18 PASS** (`final-mobile.spec.ts`) | **PASS** |
| axe 6 rute × 3 device | 0 serious/critical | **18/18 `[]`** | **PASS** |
| Lighthouse a11y (desktop+mobile) | ≥ 90 | **100 / 100** (12/12 laporan valid) | **PASS** |
| Lighthouse best-practices | ≥ 90 | **96-100** | **PASS** |
| Lighthouse SEO | ≥ 90 | **100** | **PASS** |
| Lighthouse perf mobile | ≥ 80 | **57-63** | **GAGAL** |
| PWA manifest | opsional | **ditambahkan** (manifest + ikon 192/512 + SW produksi) | **PASS** |
| tsc / build / pytest | 0 / 0 / hijau | tsc **0**, build **SUCCESS** (9 rute), pytest **136 passed** | **PASS** |
| PR #2 | updated, tidak di-merge | diperbarui, tetap **DRAFT** | **PASS** |

## 2. Matriks mobile (angka)

`tests/final-mobile.spec.ts` — 6 halaman × 3 device (iPhone 14 390×844,
Pixel 7 412×915, iPad Mini 768×1024):

```
MOB_<device>_<route>=touch:<N> tooSmall:0 overflow:0     (semua 18 kombinasi)
AXE_MOB_<device>_<route>=[]                              (semua 18 kombinasi)
18 passed (1.9m)
```

**Temuan nyata (bukan hijau palsu).** Versi pertama spec hanya MENCETAK ukuran
target sentuh, sehingga halaman dengan 14-210 kontrol kecil tetap "PASS".
Setelah ambang 44 px dijadikan assertion, terukur pelanggaran di SELURUH halaman:
`tooSmall` = 9 (`/`), 9 (`/chat`), 11 (`/settings`), 5 (`/billing`), 8 (`/help`),
14-67 (`/builder`), 210 (`/` di iPad Mini). Contoh: nav `Chat` 79×36, tombol tema
36×36, radio tema 42 px, tombol bagian Help 30 px.

Perbaikan: aturan `@media (pointer: coarse)` (`min-height/min-width: 44px`)
di `globals.css`, mengecualikan `.sr-only` dan isi kanvas React Flow (FASE 3).
Perbandingan memakai pembulatan CSS px karena pada DPR 2 elemen 44 px terukur
43.99 (gagal ambang secara palsu). Hasil akhir: **tooSmall=0 pada 18 kombinasi**,
tanpa overflow horizontal (`overflow:0`), `41 passed` (18 mobile + 23 a11y).

## 3. Lighthouse (build produksi, 12/12 laporan valid)

`node scripts/final-lighthouse.mjs` (BASE_URL=:3000, `serve:static`):
`VALID=12/12 DITOLAK=0`, `AMBANG_LOLOS` untuk a11y/BP/SEO — **kecuali perf mobile**.

| Rute | Desktop (a11y/perf/BP/SEO) | Mobile (a11y/perf/BP/SEO) |
|---|---|---|
| `/` | 100/87/100/100 | 100/**57**/100/100 |
| `/chat` | 100/92/100/100 | 100/**63**/100/100 |
| `/settings` | 100/93/96/100 | 100/**60**/96/100 |
| `/billing` | 100/93/96/100 | 100/**61**/96/100 |
| `/help` | 100/93/96/100 | 100/**59**/96/100 |
| `/builder` | 100/91/96/100 | 100/**58**/96/100 |

Agregat: `a11y_desktop_min=100`, `a11y_mobile_min=100`, `seo_min=100`,
`bp_min=96`, `perf_mobile_min=57`.

### Perf mobile: GAGAL ambang — diagnosis (bukan dugaan)

Metrik mobile `/`: `FCP=2356ms LCP=10001ms TBT=542ms SI=3492ms CLS≈0`,
`BOOTUP=1181ms MAINTHREAD=2145ms`, `total-byte-weight≈1.56MB`,
`unused-javascript≈4020ms` (potensi), `unused-css-rules≈300ms`.

Artinya: skor jatuh karena **LCP ≈ 10 detik** (bobot terbesar di metrik perf) dan
**1,56 MB JS/CSS** yang sebagian besar tidak terpakai di rute itu. Ini bukan
kesalahan konfigurasi Lighthouse atau efek dev-server (ukurannya sudah di build
statis produksi).

Dua opsi (belum dikerjakan — butuh keputusan/lebih banyak waktu):
1. **Code-splitting per rute** (`next/dynamic`): rute `/` saat ini memuat
   bundle chat yang juga menarik `motion`, `nuqs`, TanStack Query dan (lewat
   komponen bersama) React Flow. Memisahkannya adalah intervensi paling berdampak
   pada `unused-javascript` + LCP. Risiko: menambah kompleksitas loading state.
2. **Turunkan beban render awal**: font `next/font` di-preload dgn `display:swap`
   sudah aktif, tetapi hero + animasi masuk pertama menahan LCP. Alternatif:
   render hero server-side (tanpa animasi masuk) lalu animasikan setelah idle.

Belum ada iterasi perbaikan perf yang dijalankan; karena itu statusnya **PARTIAL
dengan angka**, bukan klaim lulus.

## 4. PWA (opsional)

* `public/manifest.json`: `name/short_name "Katalir"`, `display: standalone`,
  `theme_color #4F46E5`, `background_color #09090b`, ikon 192 + 512 (+ maskable)
  dan SVG.
* Ikon PNG **dihasilkan dari `src/app/icon.svg`** memakai headless Chrome
  (`--screenshot`), jadi tidak ada dependensi image tooling baru.
* `public/sw.js`: navigasi **network-first** (cache-first untuk HTML = halaman
  basi setelah deploy), aset `_next/static` cache-first (nama ber-hash), hanya GET
  dan hanya origin sendiri (API tidak pernah di-cache).
* Registrasi `ServiceWorkerRegistrar` **hanya di produksi** — di dev/harness E2E
  service worker tidak aktif supaya tes tidak membaca halaman dari cache.
* Batas jujur: audit PWA Lighthouse **tidak** dijalankan (manifest+SW baru
  ditambahkan setelah batch Lighthouse; menjalankannya lagi = build + 12 run).
