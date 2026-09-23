# FASE 5 — Verifikasi (a11y tuntas + hutang FASE 4: skip-link, user_preferences, Dodo)

Tanggal: 2026-09-24. Branch `level-3-experiment`. Harness: **dev**
(`playwright.dev.config.ts`, FE `:3000` + BE `:8000`).

## 1. Deliverable & kriteria PASS

| # | Deliverable | Status | Bukti (angka yang bisa dibaca ulang) |
|---|---|---|---|
| 1 | skip-link berfungsi di 5 rute | **PASS** | `SKIP_<route>` = tepat 1 tautan, `href="#main-content"`, target ada, `tabindex=-1`, elemen fokusable pertama; `SKIP_FOCUS_*` kotak terlihat **119.4×36 @16,16** (sebelum fokus **1×1 @-1,-1**); `SKIP_AFTER_ENTER_*` → `activeElement.id=main-content` |
| 2 | axe + Lighthouse 100 di semua rute | **PASS** | axe `[]` di **7 rute** (bersesi) + **3 rute** (tanpa sesi) + `/builder` dengan node; Lighthouse **desktop 100×5** dan **mobile 100×5**, semuanya `GAGAL=[]` |
| 3 | Migration `user_preferences` + dry-run reversible | **PASS** | `--dry-run` mencetak DDL tanpa mengubah apa pun; `--apply` → tabel + index dibuat (via `psql`), `NOTIFY pgrst` reload; `--verify` → kolom `user_email/prefs/updated_at` ADA, round-trip tulis→baca `{"canvasTheme":"midnight"}`; rollback tersedia (`DROP TABLE`, butuh `--yes-rollback`) |
| 4 | Hutang FASE 4 — verifikasi Dodo | **PARTIAL (jujur)** | API key Dodo valid di **live_mode** (`GET /products` → **200**); webhook `pytest tests/test_dodo_webhook.py` → **11 passed**; **pembayaran sungguhan TIDAK diuji** (butuh kartu/akun pemilik) |

## 2. Angka Lighthouse (final)

`scripts/fase5-lighthouse.cmd` (10 run) + `scripts/fase5-lighthouse-mobile.cmd` (3 run ulang):

| Rute | Desktop | Mobile |
|---|---|---|
| `/` | **100** `[]` | **100** `[]` |
| `/settings` | **100** `[]` | **100** `[]` |
| `/billing` | **100** `[]` | **100** `[]` |
| `/help` | **100** `[]` | **100** `[]` |
| `/builder` | **100** `[]` | **100** `[]` |

Catatan kejujuran: `/builder` mobile awalnya ber-skor `100` tetapi masih
menyisakan satu audit berbobot **0** (`label-content-name-mismatch`). Skornya 100
karena bobotnya nol, BUKAN karena bersih. Audit itu diperbaiki (§4.6) dan diukur
ulang → `[]`.

## 3. Angka axe (final)

`AXE_<route>` = daftar `id(impact)xjumlah`:

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
2. **Mobile `/billing` & `/help`** diukur pada batch yang sama SEBELUM perbaikan
   `builder.canvasThemeShort`; rute itu tidak memakai tombol tema kanvas sehingga
   tidak terpengaruh — tetapi secara metodologis angkanya bukan dari kode terakhir.
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
.\scripts\fase5-lighthouse.cmd
.\scripts\fase5-lighthouse-mobile.cmd

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
di-restart) — ini angka dari KODE YANG DI-COMMIT (`3cbfe5d`):

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