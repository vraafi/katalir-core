# FASE 6 FINAL — laporan penutup (perf mobile + pemisahan landing)

Tanggal: 2026-09-24. Branch `level-3-experiment`. HEAD saat diukur: lihat
`COMMIT` di laporan akhir sesi. Dokumen ini MELENGKAPI
`docs/audit/fase6-verification.md` (yang memuat audit mobile/a11y/PWA dan
riwayat iterasi 1-3).

## 1. Hasil perf mobile `/` — median 3 run (bukan best-run)

Aturan pengukuran: Lighthouse CLI, `--only-categories=accessibility,performance,
best-practices,seo`, preset **mobile** (4× CPU throttle + slow 4G), **build
produksi** yang disajikan `scripts/serve-out.mjs` (dengan kompresi br/gzip,
parity Cloudflare Pages), satu rute per run (`scripts/perf-median.cmd / mobile 3`).
Semua laporan valid (`VALID=1/1 DITOLAK=0`; laporan `runtimeError` ditolak skrip).

| Tahap | Run 1 | Run 2 | Run 3 | **Median** | Min-Max | Sebaran |
|---|---|---|---|---|---|---|
| **BASELINE** (sebelum Opsi 1+2) | 67 | 68 | 69 | **68** | 67-69 | 2 |
| **SESUDAH** (landing split + motion out) | 84 | 76 | 76 | **76** | 76-84 | 8 |

Sebaran ≤ 8 (ambang kewaspadaan yang saya pakai: > 10 → mesin terlalu berisik),
jadi angka ini layak dibandingkan. Skor a11y/best-practices/SEO tetap
**100 / 100 / 100** di setiap run.

**Kesimpulan: median 68 → 76 (+8).** Target misi ≥ 80 **belum** tercapai; misi
mengizinkan penerimaan pada 75+ dengan dokumentasi jujur, dan itu yang dilakukan
(§3).

## 2. Dua opsi yang dieksekusi

### Opsi 2 — pisahkan landing dari aplikasi chat
* `/` sekarang **landing ringan**: hero + CTA + 3 kartu fitur + footer.
  Provider yang dipasang HANYA `I18nProvider` + `HydrationReady` +
  `SkipToContent` — **tanpa** AuthProvider, QueryProvider, Shell, atau store.
* Aplikasi chat pindah ke **`/chat`** (`src/app/chat/ChatApp.tsx`, di-export ulang
  oleh `src/app/chat/page.tsx` supaya hanya ada SATU implementasi chat).
* CTA "Mulai sekarang" (`data-testid="landing-cta"`) → `/chat`.

**Bundle before/after (First Load JS, tabel build Next):**

| Rute | Sebelum | Sesudah | Catatan |
|---|---|---|---|
| `/` (landing) | **367 kB** (aplikasi chat) | **117 kB** | −250 kB / −68% |
| `/chat` (aplikasi chat) | 367 kB (alias) | **365 kB** | tidak berubah (memang chat) |

Isi `/` kini: 103 kB shared (React/Next + i18n) + ~14 kB halaman. Verifikasi
"tanpa bundle chat/query/canvas" dilakukan dengan (a) tabel ukuran build, dan
(b) daftar impor halaman landing yang hanya berisi `next/link`, `lucide-react`,
`@/i18n/context`, `HydrationReady`, `SkipToContent` — tidak ada `useChat`,
`@tanstack/react-query`, `zustand`, `@xyflow/react`, atau `motion/react`.

### Opsi 1 — motion keluar dari landing
* Animasi masuk landing memakai CSS murni: `.k-fade-up`
  (`@keyframes k-fade-up` di `globals.css`) dan **dimatikan** pada
  `@media (prefers-reduced-motion: reduce)`.
* **Hero tidak dianimasikan** dari opacity 0 — temuan FASE 6: elemen LCP baru
  tercatat saat TERLIHAT, jadi fade-in pada hero menunda LCP.
* `motion/react` **tetap dipakai di chat & kanvas** (thread, queue, builder) —
  itu bagian UX yang diminta misi, bukan sasaran pemangkasan.

## 3. Yang belum sempurna (jujur) + sisa opsi

Median **76 < 80**. Sisa selisih ada di jalur kritis yang tidak bisa dipotong
tanpa mengubah arsitektur:

1. **Shared runtime 103 kB** dimuat semua rute (React 19 + Next runtime + i18n
   provider + `next-themes` + `sonner` Toaster yang dipasang di root layout).
   Untuk landing, Toaster/theme tidak dipakai. **Opsi sisa A**: pindahkan
   `Toaster` + `ThemeProvider` dari `app/layout.tsx` ke rute yang memakainya
   (Shell + layout `/builder`) sehingga landing tidak membayarnya. Perkiraan
   hemat 20-30 kB jalur kritis; risiko: toast di rute yang lupa dipasangi
   provider (perlu tes toast per rute).
2. **LCP masih ~2,8-3,5 s** (target "good" 2,5 s) karena HTML+CSS+font harus
   tiba lebih dulu. **Opsi sisa B**: inline CSS kritis landing
   (`content-visibility`/critical CSS) atau sajikan landing tanpa framework
   (HTML statis terpisah) — dampak terbesar, tetapi menambah satu jalur build
   yang harus dijaga konsisten dengan i18n.
3. **Derau mesin ±4-8 poin** (run 1 = 84, run 2-3 = 76). Karena itu laporan ini
   memakai median 3 run, bukan angka tertinggi; klaim "≥80" TIDAK dibuat meski
   satu run mencapainya.

## 4. Dodo (status)

`PAYMENT_PORTAL_URL` **ditunda oleh user** — tidak disentuh di fase ini.
`DODO_CHECKOUT_URL` sudah diperbaiki sebelumnya (lihat
`fase6-verification.md` §4b).

## 5. Catatan metodologi yang dibawa dari fase sebelumnya

* Laporan Lighthouse bisa tersimpan walau halaman tidak dimuat → skrip menolak
  (`TIDAK_VALID`) dan pengukuran median memakai skrip yang sama.
* `next dev` dan `npm run build` menulis `.next` yang sama: setiap kali build
  dijalankan di sesi ini, dev server di-restart dan diverifikasi 200 sebelum
  tes/regresi berikutnya.

## 6. Penutup: `color-contrast` `/builder` mobile + `chat-auth`

### 6.1 `color-contrast` — klasifikasi: **TIMING (settling)**, bukan warna yang salah

Pemicu: regresi dev melaporkan `color-contrast` serious **×9** di `/builder`
(iphone14) — satu-satunya kegagalan a11y di seluruh matriks, dan rute/perangkat
yang sama LULUS (`AXE_MOB=[]`) sekitar dua jam sebelumnya.

Langkah yang dijalankan (dan hasilnya):
1. **Probe detail** `scripts/probes/fase6-contrast-probe.mjs` (Playwright +
   axe `color-contrast`, device iPhone 14, 3 run per mode, mencetak elemen +
   rasio + tema + token):
   * mode **tanpa sesi** (parity spec/Lighthouse) → `theme=midnight`,
     `canvasToken=#1b1f23`, pelanggaran **[0,0,0]**;
   * mode **bersesi** (tema tersimpan pengguna) → `theme=cyberpunk`,
     `canvasToken=#0a0a0f`, pelanggaran **[0,0,0]**.
   6 run terisolasi = **0 pelanggaran**, jadi angka 9 TIDAK bisa direproduksi
   pada keadaan tenang.
2. **Kesimpulan**: yang terukur saat regresi adalah keadaan transisi (font web
   belum selesai swap dan/atau token tema kanvas belum terpasang saat axe
   mengukur), bukan pasangan warna akhir aplikasi. Karena itu perbaikan
   dilakukan pada **kesiapan pengukuran**, bukan pada warna:
   `final-mobile.spec.ts` kini memakai `settle()` yang menunggu
   `html[data-hydrated='true']` + `document.fonts.ready` + atribut
   `data-canvas-theme` (khusus `/builder`) sebelum scan.
3. **Bukti sesudah**: `tests/final-mobile.spec.ts` (18 tes, 3 device) →
   **18/18 PASS**, dan tiap scan mencetak keadaannya:
   `AXE_MOB_<device>_rootbuilder=[] STATE={"theme":"cyberpunk","hydrated":"true","fontsDone":"loaded"}`
   untuk iphone14, pixel7, dan ipadmini.
4. **Yang TIDAK saya klaim**: overlay visual axe pada screenshot tidak dibuat
   (tidak ada di misi sebelumnya). Bukti yang ada: screenshot
   `test-results/fase6-contrast/builder_mobile_run{1,2,3}.png` +
   `test-results/final-mobile/<device>_rootbuilder.png`, serta keluaran axe
   (jumlah pelanggaran + elemen + rasio) dari probe dan spec.
5. **Catatan risiko**: karena klasifikasinya timing, perbaikan ini TIDAK
   menghapus kemungkinan kontras asli yang buruk di suatu state lain (mis. tema
   lain × lebar lain). Kalau muncul lagi, probe ini yang dipakai lebih dulu —
   dan ia mencetak nama tema + token aktif supaya penyebabnya langsung terbaca.

### 6.2 `chat-auth` — **PASS** setelah revert

Kegagalan sebelumnya disebabkan perubahan saya sendiri (spec itu menguji SITUS
PRODUKSI `proyek-agent.pages.dev` yang belum ter-deploy ulang, sehingga `/chat`
menjawab 404). Setelah dikembalikan ke `/`:

```
npx playwright test -c playwright.dev.config.ts tests/final-mobile.spec.ts tests/chat-auth.spec.ts
EMAIL_VISIBLE=2
CHAT_STATUS=200 body={"status":"success","reply":"Halo! Ada yang bisa saya bantu?",...,"meta":{"model":"gemini-2.5-flash-lite","requested_model":"gemma-4-31b-it"...}}
19 passed (2.4m)
```

Catatan: `final-mobile` (18) + `chat-auth` (1) dijalankan bersamaan → **19 passed**.

