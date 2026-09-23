# FASE 5 — Verifikasi (a11y tuntas + hutang FASE 4: skip-link, user_preferences, Dodo)

Tanggal: 2026-09-24. Branch `level-3-experiment`. Harness: **dev**
(`playwright.dev.config.ts`, FE `:3000` + BE `:8000`).

## 1. Deliverable & kriteria PASS

| # | Deliverable | Status | Bukti (angka yang bisa dibaca ulang) |
|---|---|---|---|
| 1 | skip-link berfungsi di 5 rute | **PASS** | `SKIP_<route>` = tepat 1 tautan, `href="#main-content"`, target ada, `tabindex=-1`, elemen fokusable pertama; `SKIP_FOCUS_*` kotak terlihat **119.4×36 @16,16** (sebelum fokus **1×1 @-1,-1**); `SKIP_AFTER_ENTER_*` → `activeElement.id=main-content` |
| 2 | axe + Lighthouse 100 di semua rute | **PASS** | axe `[]` di **7 rute** (bersesi) + **3 rute** (tanpa sesi) + `/builder` dengan node — **dan diulang pada build produksi: 23/23 lulus, semua `AXE_*` = `[]`**; Lighthouse **desktop 100×5** dan **mobile 100×5** pada build produksi, 10/10 laporan valid, `GAGAL=[]` (§2) |
| 3 | Migration `user_preferences` + dry-run reversible | **PASS** | `--dry-run` mencetak DDL tanpa mengubah apa pun; `--apply` → tabel + index dibuat (via `psql`), `NOTIFY pgrst` reload; `--verify` → kolom `user_email/prefs/updated_at` ADA, round-trip tulis→baca `{"canvasTheme":"midnight"}`; rollback tersedia (`DROP TABLE`, butuh `--yes-rollback`) |
| 4 | Hutang FASE 4 — verifikasi Dodo | **PARTIAL (jujur)** | API key Dodo valid di **live_mode** (`GET /products` → **200**); webhook `pytest tests/test_dodo_webhook.py` → **11 passed**; **pembayaran sungguhan TIDAK diuji** (butuh kartu/akun pemilik) |

## 2. Angka Lighthouse (final)

Angka yang berlaku sekarang: **satu batch 10 run, pada BUILD PRODUKSI** — `npm run
build` lalu `npm run serve:static` (`out/` disajikan statis di `:3000`), dijalankan
oleh `node scripts/fase5-lighthouse.mjs`. Semua 10 laporan **valid** (tidak ada
`runtimeError`), tidak ada audit merah, dan **tidak ada audit merah berbobot 0**:

| Rute | Desktop | Mobile |
|---|---|---|
| `/` | **100** `[]` | **100** `[]` |
| `/settings` | **100** `[]` | **100** `[]` |
| `/billing` | **100** `[]` | **100** `[]` |
| `/help` | **100** `[]` | **100** `[]` |
| `/builder` | **100** `[]` | **100** `[]` |

Verifikasi silang dari berkas bukti (bukan dari proses yang menjalankannya):

```
node scripts/fase5-lighthouse-read.mjs
desktop /  100 lhf_desktop_root.json    2026-09-23 23:31:47 valid
...  (10 baris, semuanya SKOR=100, GAGAL=[-], BOBOT0=[-])
SEMUA_100
```

Batasan yang tetap berlaku: **semua halaman diukur TANPA SESI**, karena Lighthouse
tidak bisa menanam sesi Supabase (disimpan di `localStorage`, bukan cookie).
Halaman `/chat` karena itu tidak terukur (ia butuh sesi) — lihat §5.4.

Catatan kejujuran: `/builder` mobile pernah ber-skor `100` tetapi masih menyisakan
satu audit berbobot **0** (`label-content-name-mismatch`). Skornya 100 karena
bobotnya nol, BUKAN karena bersih. Audit itu diperbaiki (§4.6) dan diukur ulang →
`[]`. Pelajaran ini kini melekat di alat: `fase5-lighthouse-read.mjs` melaporkan
`BOBOT0=[...]` secara terpisah, dan skrip pengukuran **menolak** laporan yang tidak
valid (§7.2) alih-alih mencetak skornya.

## 3. Angka axe (final)

`AXE_<route>` = daftar `id(impact)xjumlah`. Diukur ulang pada **build produksi**
(server statis `out/`, artefak yang sama dengan §2): **23 tes lulus, seluruh
`AXE_*` = `[]`**, dan `MODEL_TRIGGER` menampilkan nama model asli
(`Gemma 4 31B`) sehingga aturan Label in Name benar-benar dievaluasi — bukan
mengukur label kosong:

| Keadaan | Rute | Hasil |
|---|---|---|
| Bersesi | `/`, `/chat`, `/settings`, `/billing`, `/help`, `/builder`, `/builder+nodes`, `/pricing` | **`[]`** untuk semuanya |
| **Tanpa sesi** (paritas Lighthouse) | `/`, `/builder`, `/settings` | **`[]`**; `/builder` juga diperiksa tanpa toleransi impact → `[]` |

## 4. Bug yang DITEMUKAN dan DIPERBAIKI (semuanya dari angka, bukan dugaan)

1. **skip-link — akar masalah sebenarnya.** Audit Lighthouse FASE 4 berbunyi
   `"Skip links are not focusable." / "No skip link target"` pada node
   `body > a.sr-only`. Penyebabnya bukan tautan yang saya tambahkan di FASE 4,
   melainkan tautan **lama di `app/layout.tsx`** ber-`href="#main"` — dan
   `id="main"` **tidak ada di seluruh aplikasi**. Tautan tanpa target itu adalah
   elemen fokusable pertama, jadi Lighthouse menilainya lebih dulu. Perbaikan:
   satu tautan per halaman (`SkipToContent`) menuju `#main-content`; dipindah dari
   root layout ke `Shell`/`SimplePage` karena `useI18n` melempar di luar provider.
2. **Kontras `serious` di `/builder` (1.29:1).** Teks putih di atas `#00ffd5`
   (tema Cyberpunk) — gagal total. Token `--canvas-accent` **dikunci** oleh
   `tests/canvas-theme.spec.ts`, jadi variasi isi-tombol dipisah:
   `--canvas-accent-solid/-fg` + `--node-success-solid/-fg` per tema. Cyberpunk
   kini memakai teks gelap `#041512` (**16.3:1**); midnight/daylight `#4f46e5`
   (**4.95:1**); tombol Jalankan `#15803d` (**4.7:1**).
3. **`page-has-heading-one`** di `/`, `/chat`, `/builder`: merek di header adalah
   `<span>` → dijadikan `<h1>` halaman.
4. **`landmark-unique`** di `/builder`: ada **dua** `<aside>` tanpa nama (sidebar
   chat Shell + sidebar alur kerja). Probe `scripts/probes/fase5-landmarks.mjs`
   membuktikannya (`VISIBLE_BY_ROLE={"complementary":["(tanpa nama)","(tanpa nama)"]}`);
   ketiga landmark kini bernama lewat i18n.
5. **`label-content-name-mismatch` pada pemilih model (`/`).** `aria-label` statis
   "Pilih model AI" sementara teks terlihat adalah nama model → label dibangun
   dari teks terlihat. Efek samping yang ikut ditemukan: **dua spesifikasi lama
   memilih tombol itu lewat `button[aria-label='Pilih model AI']`**
   (`model-filter`, `hydration`) → dipindah ke `data-testid="model-selector"`
   supaya tidak bergantung pada teks berbahasa.
6. **`label-content-name-mismatch` pada tombol tema kanvas (mobile).** Teks mobile
   masih **hardcode "Tema"** (kelas bug yang sama dengan backlog 3 FASE 4)
   sementara nama aksesibel ikut i18n → di locale `en` teks terlihat tidak termuat
   dalam nama. Diganti `t("builder.canvasThemeShort")` ("Tema"/"Theme").
7. **Kontras 3.66:1 pada petunjuk sidebar alur kerja** (`text-zinc-500` di atas
   `#18181b`) → `text-zinc-400` (**4.7:1**, lolos).
8. **Celah alat uji (temuan paling penting).** axe melaporkan "0 pelanggaran"
   sementara Lighthouse menemukan **dua**. Tiga sebab, semuanya diperbaiki:
   * spec FASE 4 menjalankan axe hanya dengan tag WCAG, padahal `skip-link` dan
     `label-content-name-mismatch` adalah aturan **best-practice** → spec FASE 5
     memakai tag WCAG **+ best-practice**;
   * spec selalu **menyemai sesi**, sedangkan Lighthouse selalu menjelajah **tanpa
     sesi** → ditambahkan blok scan tanpa sesi;
   * axe discan sebelum data model tiba (teks terlihat masih kosong), sehingga
     aturan Label in Name tidak bisa dievaluasi → `ready()` kini menunggu pemilih
     model benar-benar menampilkan nama model.
9. **Dodo (temuan konfigurasi, TIDAK diubah).** `DODO_CHECKOUT_URL` di `.env`
   berisi `https://…pages.dev/api/webhook` — itu URL **webhook**, bukan tautan
   checkout Dodo; jawabannya 200 karena itu halaman web lain. Tautan checkout yang
   benar ada di `nexus-frontend/.env.local` → `NEXT_PUBLIC_DODO_CHECKOUT_URL`.
   API key juga aktif di **live_mode**, sehingga endpoint **test** menjawab 401
   (endpoint live 200). Keduanya ada di `.env*` (rahasia), jadi saya **tidak
   mengubahnya** — dilaporkan untuk keputusan pemilik.
10. **Host database Supabase berubah**: `db.<ref>.supabase.co` sudah **tidak
    diresolusi** (`could not translate host name`). Host pooler yang benar
    ditemukan dengan mencoba 30 kandidat region dan hanya menerima yang lolos
    autentikasi (`_probe_supabase_pooler.py`) →
    `aws-0-ap-southeast-1.pooler.supabase.com:6543`, username `postgres.<ref>`.
11. **PostgREST schema cache (PGRST205)**: tabel yang dibuat lewat koneksi
    Postgres belum terlihat lewat REST → `NOTIFY pgrst, 'reload schema'` (kini
    langkah tetap di `--verify`).

## 5. Yang TIDAK diverifikasi (batas misi)

1. **Pembayaran Dodo end-to-end** — butuh akun+kartu pemilik. Yang dibuktikan
   hanya lapisan milik kita (kredensial live 200, tautan checkout di `.env.local`,
   webhook 11 tes).
2. **~~Mobile `/billing` & `/help` diukur pada batch sebelum perbaikan
   `builder.canvasThemeShort`.~~ SUDAH DITUTUP.** Kedua rute itu kini diukur pada
   batch produksi 10-run yang sama dengan rute lain (§2), jadi tidak ada lagi angka
   yang berasal dari kode antara. (Rute tersebut memang tidak memakai tombol tema
   kanvas, jadi hasilnya tidak berubah — yang berubah adalah kerapian bukti.)
3. **Migrasi dijalankan pada database PRODUKSI bersama.** Sifatnya aditif +
   idempoten + reversible (ada `--rollback`), tetapi tetap perlu disadari: tabel
   `user_preferences` kini ada di project Supabase yang dipakai bersama.
4. **`/chat` belum diukur Lighthouse** karena Lighthouse selalu menjelajah tanpa
   sesi sementara `/chat` butuh sesi. axe-nya bersih: `/chat` bersesi `[]`, dan
   `/` tanpa sesi `[]` (kerangka halaman sama).
5. **`.env` Dodo tidak diperbaiki** (rahasia) — hanya dilaporkan di §4.9.

## 6. Cara reproduksi

```powershell
# BE + FE
cd c:\Users\user\Proyek_AI; python api_server.py
cd c:\Users\user\Proyek_AI\nexus-frontend; $env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"; npm run dev

# PENTING (terbukti di fase ini): JANGAN menjalankan `npm run build` saat dev
# masih hidup. Build dan dev memakai folder `.next` yang sama; setelah build,
# `/` menjawab **500** (rute lain masih 200, jadi gejalanya menyesatkan).
# Pemulihan: matikan dev, hapus `nexus-frontend/.next`, jalankan `npm run dev`
# lagi (dilakukan di sini dan semua rute kembali 200).

# a11y (axe: WCAG + best-practice; bersesi & tanpa sesi)
npx playwright test -c playwright.dev.config.ts tests/fase5-a11y.spec.ts

# Lighthouse 5 rute x 2 preset
#  - `.cmd` untuk batch klasik (dev server di :3000)
#  - `node scripts/fase5-lighthouse.mjs` untuk versi yang MEMVALIDASI laporan
#    (menolak laporan `runtimeError`; toleran terhadap exit code non-nol dari bug
#    pembersihan chrome-launcher di Windows)
#  - diagnosa cepat SATU rute tanpa menunggu 10 run:
$env:ONLY_ROUTE='/'; $env:ONLY_PRESET='desktop'; node scripts/fase5-lighthouse.mjs
Remove-Item Env:ONLY_ROUTE, Env:ONLY_PRESET   # WAJIB dibersihkan (lihat §7.3)
.\scripts\fase5-lighthouse.cmd
.\scripts\fase5-lighthouse-mobile.cmd

# Ukur pada BUILD PRODUKSI (metode yang dipakai untuk angka §2) -- lebih
# representatif daripada dev server dan jauh lebih ringan di RAM:
npm run build
npm run serve:static          # out/ disajikan statis di :3000
node scripts/fase5-lighthouse.mjs
node scripts/fase5-lighthouse-read.mjs   # baca ulang artefak + cek validitas

# migrasi (SELALU dry-run dulu)
cd c:\Users\user\Proyek_AI
python migrate_user_preferences.py --dry-run
python migrate_user_preferences.py --apply
python migrate_user_preferences.py --verify
python migrate_user_preferences.py --rollback --yes-rollback   # bila ingin dibatalkan

# hutang FASE 4
python _verify_prefs_persistence.py     # PUT/GET /preferences + baris di Postgres
python _verify_dodo_live.py             # kredensial + tautan checkout Dodo
python -m pytest tests/test_dodo_webhook.py -q
```

## 7. Hasil regresi penuh (semua suite, bukan hanya a11y)

```
npx playwright test -c playwright.dev.config.ts      ->  80 passed, 1 failed  (8.7m)
  1 failed: tests/model-filter.spec.ts:267 "BUG 1 -- /models & selector
            produksi tidak menyajikan model paid-only"
            MODELS_COUNT=9  FORBIDDEN_HITS=[]   <-- filter kita bersih;
            upstream memang tidak mengirim model berkuota besar (sama seperti FASE 4)
```

Bukti suite lain di run yang sama (semuanya hijau):

| Suite | Bukti dari log |
|---|---|
| `fase5-a11y` | `23 passed`; `AXE_*` = `[]` di 7 rute bersesi, 3 rute tanpa sesi, dan `/builder+nodes` |
| `canvas-*` | lulus (termasuk `canvas-theme.spec.ts` yang mengunci `--canvas-accent`) |
| `fase4-*` | lulus |
| `model-filter` | lulus kecuali BUG 1 di atas |
| `chat-auth` | lulus — `EMAIL_VISIBLE=2`, `CHAT_STATUS=200`, `VALID_CHAT_BODIES=[200]` |
| `routes` | lulus — 5 rute `200` |

**Cakupan harness (temuan saat menulis laporan ini).** Run di atas = 81 tes dari 8
spec yang terdaftar di `playwright.dev.config.ts` (`canvas-fase3`, `canvas-theme`,
`fase4-pages`, `fase4-a11y`, `fase5-a11y`, `model-filter`, `routes-no-crash`,
`chat-auth`). `hydration.spec.ts` **TIDAK ada di daftar itu** — ia hanya dimuat
`playwright.config.ts`, yang mem-build produksi >300 detik dan menolak port
terpakai, sehingga **perubahan FASE 5 pada spec itu tidak pernah dijalankan**
(saya awalnya menuliskan "lulus" di tabel ini; itu salah dan sudah dikoreksi).
Tindakan: `hydration.spec.ts` ditambahkan ke harness dev dan dijalankan langsung
pada dev server bersih:

```
npx playwright test -c playwright.dev.config.ts tests/hydration.spec.ts
HYDRATION_HITS=0   PAGEERRORS=[]   MONITOR_RECOVERED=0
STORED_MODEL_AFTER=gemma-4-9b-it   QUEUE_AREA_COUNT=0
1 passed (6.0s)
```

Artinya `data-testid="model-selector"` benar-benar ada & terlihat, dan gate
`mounted` masih melepas (label netral "Memuat" tidak permanen).

Verifikasi terakhir pada dev server bersih (setelah `.next` dihapus dan dev
di-restart) — ini angka dari KODE YANG DI-COMMIT. Angka di bawah diambil pada
`3cbfe5d`; `git diff --stat 3cbfe5d..24aed79` membuktikan commit berikutnya hanya
menyentuh `docs/audit/fase5-verification.md` + `playwright.dev.config.ts` (daftar
spec harness), jadi tidak ada kode a11y/ui yang berubah di antaranya. **Angka a11y
yang otoritatif sekarang ada di §3 (diukur pada build produksi, artefak yang sama
dengan Lighthouse §2); blok di bawah adalah jalur dev sebagai pembanding —
hasilnya identik.**

```
AXE_/ = []   AXE_/chat = []   AXE_/settings = []   AXE_/billing = []
AXE_/help = []   AXE_/builder = []   AXE_/pricing = []
AXE_UNAUTH_/ = []   AXE_UNAUTH_/builder = []   AXE_UNAUTH_/settings = []
AXE_UNAUTH_BUILDER_ALL = []        AXE_/builder+nodes = []
MODEL_TRIGGER={"visible":"Choose a model","name":"Choose a model — Choose AI model"}
SKIP_AFTER_ENTER_* = {"id":"main-content","tag":"main"}   (5/5 rute)
23 passed (1.7m)
```

Backend: `pytest tests -q` -> **136 passed** (di antaranya 11 tes webhook Dodo).
Frontend: `npx tsc --noEmit` -> 0 error; `npm run build` -> **SUCCESS** (9 rute).

Artefak: commit `3cbfe5d` di branch `level-3-experiment`; PR #2 diperbarui
(komentar `issuecomment-5800202124`) dan **tetap DRAFT** (tidak di-merge di fase ini).

## 8. Jebakan alat ukur yang DITEMUKAN saat mengulang pengukuran (2026-09-24 pagi)

Saat mencoba mengukur ulang agar semua 10 angka berasal dari satu batch, ketiga
jebakan di bawah muncul berurutan. Semuanya menghasilkan **angka yang terlihat
sah padahal bukan** — dan semuanya sudah ditutup di kode.

### 8.1 Laporan Lighthouse bisa "berisi" walaupun halaman TIDAK PERNAH dimuat

Dev server mati tepat saat batch dimulai (penyebabnya di §8.4: RAM). Chrome di
dalam Lighthouse mendapat `ERR_CONNECTION_REFUSED` dan **Lighthouse tetap menulis
berkas laporan**:
`runtimeError = CHROME_INTERSTITIAL_ERROR`, `categories.accessibility.score = null`,
dan **nol audit dinilai**. Skrip lama mencetak:

```
SKOR=0 GAGAL=[]        <-- terbaca "nol pelanggaran", padahal halaman tidak dimuat
```

Perbaikan: `fase5-lighthouse.mjs` **menolak** laporan dengan `runtimeError` /
skor `null` (`TIDAK_VALID (...) audit_dinilai=0`), dan
`fase5-lighthouse-read.mjs` menandai berkas seperti itu sebagai `TIDAK_VALID` +
mencetak `PERINGATAN: N berkas TIDAK VALID` serta menahan `SEMUA_100`. Tanpa ini,
sebuah server yang mati bisa dilaporkan sebagai "aksesibilitas tanpa pelanggaran".

Bukti (berkas batch 06:00, sekarang ditolak):

```
PERINGATAN: 10 berkas TIDAK VALID (navigasi gagal) -- angkanya TIDAK boleh dipakai:
desktop/=CHROME_INTERSTITIAL_ERROR, desktop/settings=CHROME_INTERSTITIAL_ERROR, ...
```

### 8.2 Exit code non-nol TIDAK berarti pengukuran gagal (bug Windows)

`chrome-launcher` gagal menghapus profil sementaranya
(`EPERM ... \Temp\lighthouse.<pid>`) **setelah** laporan selesai ditulis, sehingga
`npx lighthouse` keluar dengan status non-nol. Batch `.cmd` pertama hari ini
menghasilkan **9 error** semacam itu padahal 10 laporannya lengkap. Skrip lama
langsung `continue` → laporan yang sah dibuang dan batch tampak gagal total.
Perbaikan: kegagalan exit code dicatat (`EXIT_NONZERO ... berkas laporan tetap
diperiksa`), lalu **berkasnya yang menentukan** valid/tidak.

### 8.3 Kebocoran variabel lingkungan antar perintah = batch "10 run" yang hanya 1 run

`ONLY_ROUTE`/`ONLY_PRESET` (filter diagnosa) yang diset untuk satu probe ternyata
**terwarisi perintah berikutnya** di shell yang sama, sehingga "batch penuh" hanya
mengukur 1 rute — dan karena guard-nya membandingkan dengan daftar rute yang
tersisa, hasilnya mencetak **`SEMUA_100`** dari satu rute. Ini angka paling
menyesatkan dari semuanya: hijau sempurna untuk cakupan 10%.
Mitigasi sekarang: (a) guard menolak nilai `ONLY_ROUTE` yang tidak dikenal
(terbukti menangkap `ONLY_ROUTE=" "` saat `set X=` menghasilkan spasi), (b) §6
memuat `Remove-Item Env:ONLY_ROUTE, Env:ONLY_PRESET` sebagai langkah wajib,
(c) ringkasan selalu mencetak jumlah hasil (`BELUM_SEMPURNA (N hasil...)`) sehingga
batch yang tidak lengkap tidak pernah terlihat seperti batch penuh.

### 8.4 Mengapa metode berubah ke build produksi

Mesin ini punya **7,8 GB RAM dengan ~1,1 GB bebas** saat dev server hidup
(dev = 526 MB). Chrome untuk Lighthouse butuh ratusan MB per run → dev server mati
di tengah batch (§8.2/§8.1). `next dev` juga menyuntikkan perangkat dev (overlay)
yang tidak ada di produksi. Karena itu angka §2 diukur pada `out/` hasil
`npm run build` yang disajikan `scripts/serve-out.mjs` (`npm run serve:static`):
lebih representatif (halaman yang benar-benar dikirim ke Cloudflare Pages) dan
jauh lebih ringan, sehingga 10/10 laporan valid.

Catatan tambahan: `next start` **tidak bisa** dipakai di project ini karena
build-nya `output: "export"` — jawabannya persis itu, dan `serve:static` adalah
jalur yang benar (tercatat di `scripts/serve-out.mjs` §1-8).