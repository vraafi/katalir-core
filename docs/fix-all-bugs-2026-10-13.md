# KATALIR — PERBAIKAN BUG-06 + 5 MEDIUM + PENUTUPAN PEMBAYARAN

**Tanggal:** 13 Oktober 2026
**Mode:** SKILL-FIRST + SEARCH-FIRST + OTONOM PENUH + EVIDENCE-ONLY
**Basis temuan:** `docs/real-user-hard-test-2026-10-13.md` (73 skenario, 64 PASS)
**Target:** 0 HIGH · 0 MEDIUM · regresi ≥ 69 PASS · pembayaran benar-benar tertutup

---

## 1. RINGKASAN EKSEKUTIF

| # | Temuan | Severity awal | Status | Bukti |
|---|---|---|---|---|
| BUG-03 | Null byte → bocoran `chat_sessions.insert [22P05]` | medium | **FIXED** | `_bug34_test.py` ALL PASS |
| BUG-04 | ID non-UUID → 500 + error Postgres mentah | medium | **FIXED** | `_bug34_test.py` ALL PASS |
| BUG-05 | `DEFAULT_MODEL_ID` tidak dilayani katalog | medium | **FIXED** | probe katalog 13 model |
| BUG-06 | Pendaftaran email → 429 (kuota Supabase) | high | **MITIGASI** (signup email disembunyikan) + **BLOCKED** untuk akar infra | spec 10/10 PASS |
| BUG-07 | 404 bawaan Next.js (Inggris, tanpa jalan kembali) | medium | **FIXED** | `src/app/not-found.tsx` |
| BUG-10 | a11y `/templates`: kontras ×9 + urutan heading | low | **FIXED** | spec 3/3 PASS · axe 0 pelanggaran |
| FASE 7 | Pembayaran harus tertutup ("coming soon") | — | **DONE** | 21/21 test backend · bundle bebas URL checkout |
| FASE 8 | Regresi 73 skenario (target ≥69 PASS) | — | **DIJALANKAN · 0 regresi** — 54 PASS; 15 gagal dgn sebab terukur (10 hulu model 503 · 2 backend belum di-deploy · 1 skenario usang · 2 transien) | §8 |

**Catatan penting:** BUG-10 ternyata bukan hanya soal `/templates`. Kelas cacat yang
sama (`bg-<c>-500/15 text-<c>-600` → rasio 2,8–4,3:1) juga ada di `/integrations`,
dan **tidak pernah terukur** karena satu bug di harness (lihat §5).

**Catatan FASE 8:** target ≥69 PASS **tidak** tercapai pada run ini, dan penyebabnya
terukur: hulu model sedang cooldown kuota pada jam run (§8.3). Yang penting, **tidak ada
satu pun** kegagalan yang berasal dari perubahan kode Brief 7 — dan 3 skenario justru
berubah FAIL → PASS sebagai bukti langsung perbaikan bekerja (§8.4).

---

## 2. BUG-03 & BUG-04 — kebocoran detail internal dari API

### Akar masalah
Pola `raise HTTPException(500, f"Gagal <X>: {exc}")` menyalin pesan Postgres
mentah ke body respons. Untuk input yang tidak valid bentuknya:

- **BUG-03:** `\x00` di prompt → PostgREST menolak dengan `22P05`
  (`unsupported Unicode escape sequence`) → user melihat nama tabel + kolom.
- **BUG-04:** id non-UUID → `22P02` (`invalid input syntax for type uuid`) → 500
  dengan pesan driver, di 5 handler `/workflows/{id}`.

Keduanya **bukan** "500 tanpa isi": justru isinya yang masalah — ia memberi tahu
penyerang bentuk skema internal, dan memberi tahu user hal yang tidak bisa
ditindaklanjuti.

### Perbaikan (dua lapis, sesuai skill `systematic-debugging`: akar, bukan gejala)
1. **Sanitasi input di batas sistem** (`api_server.py::sanitize_text`) — membuang
   `\x00` dan karakter kontrol selain `\n`/`\t`. Dipanggil di validator
   `ChatRequest._validate_prompt_length`, sehingga permintaan tidak pernah sampai
   ke database dalam bentuk yang ditolak.
2. **Frontend tidak mengirim sampah** (`useChat.ts::sanitizePrompt`) — lapis
   kedua supaya request cacat tidak dibuat sejak awal.
3. **Gerbang bentuk id** (`_require_uuid_or_404`) — id non-UUID dibalas **404**
   ("tidak ada"), bukan 500. 404 adalah jawaban yang benar: resource itu memang
   tidak ada, dan tidak ada yang rusak.
4. **Galat database tidak lagi membocorkan payload** — `_db_error_500()` dan
   `database.py::_map_api_error` mengembalikan pesan generik + `ref` korelasi
   (`uuid4().hex[:12]`). Detail lengkap tetap masuk log server, jadi operator
   tidak kehilangan apa pun. **35 pemanggilan** pola lama diganti.

### Bukti
```
_payment_gate_test.py  -> 21/21 PASS
_bug34_test.py         -> ALL PASS (EXIT 0), termasuk HTTP nyata:
                          GET /workflows/not-a-uuid -> 404 (bukan 500)
```

---

## 3. BUG-05 — model default yang tidak pernah dilayani

`DEFAULT_MODEL_ID` bernilai `gemma-4-31b-it`, sedangkan katalog gateway memakai
id berawalan penyedia: `google/gemma-4-31b-it`. Akibatnya setiap pesan user baru
jatuh ke jalur fallback (`fallback=True`) — model benar-benar dipanggil, tetapi
lewat jalur cadangan, dan **kuota dicatat ke ember yang salah**.

**Perbaikan** (`src/lib/models.ts`): `DEFAULT_MODEL_ID` → `google/gemma-4-31b-it`,
plus `LEGACY_MODEL_ALIASES` + `normalizeModelId()` supaya sesi lama yang masih
menyimpan id gaya lama di localStorage ikut dipetakan (bukan hanya default baru).

**Bukti:** katalog live berisi 13 model dan memuat `google/gemma-4-31b-it`;
`_resolve_model('gemma-4-31b-it')` → `fallback=True`, sedangkan
`_resolve_model('google/gemma-4-31b-it')` → `fallback=False`.

---

## 4. BUG-06 — pendaftaran email (429) — MITIGASI + BLOCKED

### Kenapa BLOCKED
Pengirim email bawaan Supabase dibatasi **2 email/jam per PROYEK** untuk paket
gratis. Satu-satunya perbaikan yang benar adalah memasang SMTP kustom, yang
menuntut **`SUPABASE_ACCESS_TOKEN`** (Management API). Token itu **tidak ada** di
`.env`, dan variabel `SMTP_*` / `RESEND_API_KEY` juga tidak ada.

Sesuai aturan brief: **tidak mengakali** batas ini. Yang dilakukan adalah
mitigasi jujur — menyembunyikan jalan yang pasti gagal — lalu melaporkan sisa
langkah manualnya (§9).

### Mitigasi (commit `15322d6`)
`login-modal.tsx`: `EMAIL_AUTH_HIDDEN = true` menyembunyikan form email, pembatas
"atau", dan tombol alih masuk/daftar; diganti keterangan "segera hadir".
**Google & GitHub OAuth tetap berfungsi penuh.**

Spec `tests/login-modal.spec.ts` **ditulis ulang total** (versi lama
meng-assert `login-email-form` VISIBLE — kini justru kebalikannya) → **10/10 PASS**,
termasuk uji pendaftaran Google sampai layar consent, dengan verifikasi
`redirect_uri` mengarah ke broker Supabase (bukan `/auth/callback` aplikasi).

---

## 5. BUG-07 — halaman 404

Belum ada `src/app/not-found.tsx`, sehingga 404 memakai halaman bawaan Next.js:
berbahasa Inggris, tanpa navigasi kembali.

**Perbaikan:** `src/app/not-found.tsx` — berbahasa Indonesia, `data-testid="not-found"`,
dua jalan kembali (`/chat`, `/`). Sengaja **tanpa** `useSearchParams`/`usePathname`
supaya aman untuk static export (keduanya memaksa CSR-bailout dan membuat build gagal).

---

## 6. BUG-10 — aksesibilitas `/templates` (dan kelas cacat yang sama di `/integrations`)

### 6.1 Akar masalah (diukur, bukan ditebak)
Reproduksi deterministik (build produksi disajikan statis + data template
di-inject) menghasilkan **2 pelanggaran**, persis seperti laporan:

```
color-contrast [serious] x8
  Notifikasi  fg #2563eb pada bg #e2ecfe = 4.34:1
  Marketing   fg #db2777 pada bg #fce4f0 = 3.82:1
  Data        fg #059669 pada bg #dbf5ec = 3.28:1
  Operasional fg #d97706 pada bg #fef0da = 2.83:1   <- terburuk
  Integrasi   fg #0891b2 pada bg #daf4f9 = 3.20:1
heading-order [moderate] x1  (h1 -> h3, melompati h2)
```

Jadi **bukan** "satu chip yang salah", melainkan satu **pola warna** yang dipakai
berulang: `bg-<warna>-500/15` + `text-<warna>-600`. Ambang AA untuk teks 11–12px
adalah 4,5:1 — lima dari enam kategori gagal.

### 6.2 Perbaikan
- Chip kategori (`TemplateCard.tsx::CATEGORY_STYLE`): shade teks 600 → **800** di
  mode terang. Terukur: blue 7.34 · pink 6.57 · emerald 6.69 · amber 6.31 ·
  cyan 6.33 · violet 7.22 (semua ≥ 6,3:1, margin aman). **`amber-700` sengaja
  tidak dipakai** karena hanya 4,47:1 — masih di bawah ambang.
  Mode gelap tetap `-400` (5,3–7,7:1).
- Judul kartu: `<h3>` → `<h2>` (`h1` halaman → `h2` kartu, tidak melompat).
- Badge tier `/integrations` (`TIER_STYLE`): shade 600 → 800 + **varian gelap
  yang sebelumnya tidak ada sama sekali**.

### 6.3 Bukti (sebelum → sesudah)

| | Sebelum | Sesudah |
|---|---|---|
| Pelanggaran axe `/templates` | `color-contrast` serious ×8, `heading-order` ×1 | **0** |
| Rasio kontras terburuk | 2,83:1 | 6,31:1 |
| Warna teks chip (terukur `getComputedStyle`) | `rgb(37,99,235)` … | `rgb(30,64,175)` … (shade 800) |
| Urutan heading | `[1,3,3,3,…]` | `[1,2,2,2,…]` |
| Pelanggaran axe `/integrations` | belum pernah terukur (harness 404) | **0** |

Screenshot (di-commit): `docs/evidence/bug10-templates-before.png`,
`docs/evidence/bug10-templates-after.png`.

**Catatan kejujuran:** rasio di atas diukur pada warna yang benar-benar terpasang
(`getComputedStyle`), bukan disimpulkan dari nama kelas — "hijau karena kelasnya
tidak ada" adalah kegagalan mode yang nyata di sini, jadi kelas `-800` diverifikasi
ada di CSS hasil build *dan* warnanya dibaca dari DOM.

### 6.4 BONUS: bug harness yang menyembunyikan `/integrations` dari audit
`scripts/serve-out.mjs` menyelesaikan rute tanpa ekstensi dengan urutan
**"direktori dulu, baru `.html`"**. Static export menghasilkan **keduanya**:

- `out/integrations.html` (rute `/integrations`)
- `out/integrations/` (rute anak `/integrations/catalog`)

Direktori menang → `out/integrations/index.html` tidak ada → **404**. Cloudflare
Pages (produksi) menyajikan `integrations.html`. Akibatnya setiap audit a11y
`/integrations` selama ini mengukur **halaman 404**, dan melaporkan
`document-title`/`html-has-lang`/`landmark-one-main` sebagai "pelanggaran produk".

Diperbaiki: urutan dibalik (`foo.html` menang atas `foo/index.html`), sama seperti
produksi. Ini murni bug harness — **tidak ada perubahan produk** di baliknya.

---

## 7. FASE 7 — pembayaran ditutup ("coming soon")

### Prinsip: "disembunyikan" harus berarti **tidak ada jalan**, bukan **tombol mati**
Menyembunyikan tombol hanya menyembunyikan jalan, bukan kemampuan. Dua gerbang
dipasang, dan keduanya fail-closed.

### 7.1 Backend (`api_server.py`)
```
PAYMENT_ENABLED (default: false)
GET  /payment/status    -> 200 selalu; {enabled, checkout_available, message}
POST /payment/checkout  -> 503 selama ditutup
```
`/payment/status` sengaja **tidak pernah** 503: UI perlu membedakan "pembayaran
ditutup" (tampilkan lencana) dari "backend rusak" (tampilkan galat). Endpoint yang
selalu gagal justru memaksa klien menebak.

**Bukti: `_payment_gate_test.py` → 21/21 PASS**, termasuk: default mati; aktif tapi
tanpa URL → 503 "belum dikonfigurasi"; aktif + URL → 200 dengan tautan berisi
plan & email; dan 8 nilai env menyesatkan (`"false"`, `"0"`, `"no"`, `""`, `"  "`,
`"yes"`, `"on "`, `"TRUE "`) dipetakan persis seperti yang diharapkan.

### 7.2 Frontend — satu sakelar, bukan tiga salinan
Sebelumnya `NEXT_PUBLIC_DODO_CHECKOUT_URL` dibaca sendiri-sendiri di **tiga**
berkas (billing, UserMenu, ModelSelector). Tiga salinan berarti "mematikan
pembayaran" menuntut tiga perubahan yang konsisten — satu yang terlewat = tombol
bayar masih hidup. Sekarang ada `src/lib/payment.ts` sebagai satu-satunya sumber
kebenaran; komponen yang hanya tahu "ada URL / tidak ada URL" ikut mati otomatis.

Perubahan UI: `/billing` → lencana "Segera hadir" + penjelasan (menggantikan CTA);
`/pricing` → lencana (bukan tautan); `UserMenu` → butir "Upgrade" hilang;
`ModelSelector` → lencana pada upsell; `/chat` → **spanduk** yang bisa ditutup
(tersimpan di localStorage, `role="status"`, tanpa kedipan saat hidrasi).

### 7.3 URL checkout tidak lagi ikut ke browser — dan gerbang yang menjaganya
Langkah pertama tampak cukup: **mengomentari** baris `NEXT_PUBLIC_DODO_CHECKOUT_URL`
di `nexus-frontend/.env.production` (di-commit) dan menambah
`NEXT_PUBLIC_PAYMENT_ENABLED=false`.

**Itu tidak cukup, dan pengukurannya yang membuktikan.** Setelah build, URL checkout
masih ada di bundle. Penyebabnya: Next.js memuat **beberapa** berkas env dengan
prioritas `.env.production.local` > `.env.local` > `.env.production` > `.env`, dan
`.env.local` (dev, tidak di-commit) masih memuat nilai itu. Yang lebih penting:

> `NEXT_PUBLIC_*` di-INLINE secara **tekstual** saat build. Jadi
> "nilai tidak dipakai di runtime" **tidak** berarti "tidak ada di bundle".
> `PAYMENT_ENABLED ? URL : ""` tetap meninggalkan URL di bundle — dan siapa pun
> yang membacanya bisa membuka checkout langsung.

Artinya "disembunyikan" versi itu **tidak benar-benar disembunyikan**. Karena
akarnya adalah berkas env mana pun yang terlewat (kesalahan yang tidak terlihat
dari sumber mana pun), jawabannya bukan "ingat mengomentari semua berkas", tetapi
**gerbang otomatis yang menilai HASIL**:

`nexus-frontend/scripts/check-payment-hidden.mjs`
- pembayaran TUTUP → URL checkout (host `dodopayments.com` / id `pdt_*`) **haram**
  ada di `out/`;
- pembayaran BUKA → URL checkout **wajib** ada di `out/` (kalau tidak, CTA
  menampilkan "segera hadir" padahal seharusnya bisa dibayar).

Dijalankan sebagai `postbuild` (`package.json`) dan sebagai gerbang ketiga di
`ops/deploy_pages.py`. **Gerbangnya dibuktikan bekerja pada build yang bocor
sebelum diperbaiki: exit 1, menyebut 7 berkas.** Setelah `.env.local` dikomentari
dan `.next/cache` dibersihkan (cache menyimpan nilai env lama), build ulang bersih.

`tests/payment-hidden.spec.ts` menyisir sendiri berkas `out/` yang benar-benar
dikirim ke browser dan menuntut string `dodopayments.com` tidak ada — bukti
tingkat artefak, bukan tingkat komponen.

---

## 8. REGRESI 73 SKENARIO

### 8.1 Cara menjalankan (dan kenapa bukan lewat produksi)
Harness default menembak produksi (`RUS_FRONTEND=https://katalir.de5.net`). Perbaikan Brief 7
ada di build lokal dan **belum di-deploy**, jadi run ke produksi hanya akan menguji kode LAMA —
tidak bermakna sebagai regresi. Karena itu run dijalankan **lokal**:

```bash
python tests/user_test/serve_out.py 4321          # serve nexus-frontend/out
python _rus_local.py all                          # wrapper (scratch, gitignored)
```

`_rus_local.py` menetapkan `RUS_FRONTEND=http://127.0.0.1:4321` lalu membungkus
`rus_core.new_ctx` agar setiap context memasang `proxy_backend(ctx)` **sebelum**
`rus_personas`/`rus_extra` meng-import `new_ctx`. Proksi bekerja karena base API di `out/`
bersifat ABSOLUT (`https://gateway.katalir.de5.net/katalir-api`), sehingga
`ctx.route("**/katalir-api/**")` tidak bergantung origin; `/chat` sinkron (bukan SSE) jadi
buffering proksi tidak merusak apa pun.

Konsekuensi yang harus disadari: yang diuji adalah **frontend lokal + backend produksi**.
Perbaikan sisi backend (BUG-03/04) karena itu **tidak** tereksekusi di run ini.

Sesi: token `_session.json` sudah kedaluwarsa (~12 jam) → `rus_newuser.py` membuat akun uji
nyata baru lewat Supabase Admin API; `rus_cleanup.py` menghapusnya setelah run (sudah dijalankan).

### 8.2 Hasil
| | PASS | FAIL | BLOCKED | NOT_RUN | total |
|---|---|---|---|---|---|
| Run ini (14 Okt, build lokal) | **54** | 15 | 2 | 2 | 73 |
| Run pembanding (13 Okt, produksi) | 64 | 7 | 0 | 2 | 73 |

Per grup: `p1` 9/2 · `p2` 8/2 · `p3` 4/1 · `p4` 6/2 · `p5` 10/5 · `j1` 1/1(+2 BLOCKED) ·
`j2` 2/1(+1 NOT_RUN) · `j3` 4/0 · `bug` 10/1(+1 NOT_RUN). Durasi ≈ 25 menit.

### 8.3 Klasifikasi 15 kegagalan — **0 regresi**
| Sebab | Jml | Skenario | Bukti |
|---|---|---|---|
| Hulu model 503 (`status=error`) | 10 | P1-04, P2-02, P2-05, P3-05, P4-02, P4-06, P5-01, P5-13, J1-B, J2-D | `POST /chat` langsung: `google/gemma-4-31b-it` → 503 "semua kunci model ini sedang cooldown (kuota)"; `gemini-3.5-flash-lite` (default yang diiklankan server sendiri) → 503 timeout; hanya `gemini-2.5-flash` → 200. Roster: `degraded=true, reason=cache_stale_refresh_async`. |
| Perbaikan backend belum di-deploy | 2 | P5-11, P5-12b | Balasan masih `500 {"detail":"...invalid input syntax for type uuid..."}` — yaitu kode VPS yang LAMA. Fix BUG-04 ada di `api_server.py` lokal, belum di `scp` (§9.2). |
| Skenario repro usang | 1 | P5-15 | Skenario **men-hardcode** id pra-perbaikan `"gemma-4-31b-it"` (`rus_personas.py:1718`), jadi gagal menurut konstruksinya. Perlu diperbarui ke `google/gemma-4-31b-it`. |
| Pengukuran transien (lolos saat diulang) | 2 | P1-09, B-07 | Probe ulang: composer ADA di semua kasus — B-07 pada 1440×900 tanpa login, dan P1-09 tab-2 pada 4 s dan 10 s (`composer=True`, `errCards=0`). |

Dua `BLOCKED` (J1-A, J1-A2) **bukan** regresi: keduanya berhenti karena jalur pendaftaran email
memang sengaja disembunyikan (mitigasi BUG-06, commit `15322d6`) — justru perilaku yang dituju.

### 8.4 Bukti positif: 3 skenario berubah FAIL → PASS
Perbandingan langsung dengan run 13 Okt menunjukkan perbaikan Brief 7 benar-benar bekerja:

| Skenario | Isi | Sebelum | Sesudah |
|---|---|---|---|
| `B-12` | Audit aksesibilitas axe-core 4 halaman | FAIL | **PASS** ← BUG-10 |
| `P2-03b` | URL salah ketik: halaman 404 yang diterima user | FAIL | **PASS** ← BUG-07 |
| `P5-05` | Input ekstrem: null byte | FAIL | **PASS** ← BUG-03 |

### 8.5 Verdict jujur atas target ≥69 PASS
**Target ≥69 PASS TIDAK tercapai** (54 PASS) — dan penyebabnya terukur, bukan tersembunyi:
10 dari 15 kegagalan adalah hulu model yang sedang cooldown (kuota) pada jam run, 2 menunggu
deploy backend, 1 skenario usang, 2 transien. Tidak ada satu pun yang dapat diatribusikan ke
perubahan kode Brief 7, dan tidak ada ambang yang diturunkan untuk menutupinya. Run ulang
layak dilakukan **setelah** (a) hulu model pulih dan (b) backend di-deploy (§9.2).

**Artefak run ini:** `docs/evidence/regression-2026-10-14/` (log lengkap `rus-run-all.txt`
+ 9 berkas `rus_<grup>.json`). Catatan: harness menulis screenshot ke
`docs/evidence/real-user-2026-10-13/` **secara menimpa**, sehingga 94 screenshot milik
laporan 13 Okt ikut tertimpa; direktori itu **dikembalikan** ke keadaan semula agar
laporan 13 Okt tetap utuh dan dapat diaudit.

---

## 9. SISA LANGKAH MANUAL (BLOCKED — butuh keputusan/token Anda)

### 9.1 BUG-06 akar masalah — SMTP kustom
Tidak bisa dikerjakan tanpa kredensial. Langkah:
1. Buat akun penyedia email (mis. Resend) dan verifikasi domain pengirim.
2. Buat `SUPABASE_ACCESS_TOKEN` (Management API) di dashboard Supabase.
3. Set SMTP di proyek Supabase (Auth → SMTP Settings) dengan kredensial itu.
4. Setelah terpasang, ubah `EMAIL_AUTH_HIDDEN` → `false` di
   `nexus-frontend/src/components/auth/login-modal.tsx` dan pulihkan asersi spec
   (lihat komentar di berkas itu).

### 9.2 Deploy backend
Perubahan `api_server.py` + `database.py` (BUG-03/04 + gerbang `/payment/*`)
**belum ada di VPS** (`/root/katalir-core`). Selama belum di-deploy:
- `/payment/checkout` belum ada → 404 (bukan 503) di produksi;
- pesan galat DB di produksi masih versi lama.
Pembayaran **tetap** tertutup tanpa deploy ini, karena gerbangnya sudah
fail-closed di frontend (tanpa URL di bundle).
Perintah (prosedur rutin: backup → scp → import-check → restart → verifikasi):
```bash
ssh -i ~/.ssh/katalir_vps_ed25519 root@107.173.51.78 \
  'cp /root/katalir-core/api_server.py /root/katalir-core/api_server.py.bak-$(date -u +%Y%m%dT%H%M%SZ)'
scp -i ~/.ssh/katalir_vps_ed25519 api_server.py database.py \
  root@107.173.51.78:/root/katalir-core/
ssh -i ~/.ssh/katalir_vps_ed25519 root@107.173.51.78 \
  'cd /root/katalir-core && ./venv/bin/python -c "import api_server" && systemctl restart katalir-backend'
```

---

## 10. ARTEFAK

| Berkas | Isi |
|---|---|
| `tests/bug10-a11y.spec.ts` | regresi a11y `/templates` + `/integrations` (fixture deterministik) |
| `tests/payment-hidden.spec.ts` | regresi "pembayaran tertutup", termasuk penyisiran bundle |
| `_bug34_test.py` | unit + integrasi BUG-03/04 (scratch, gitignored) |
| `_payment_gate_test.py` | 21 test gerbang pembayaran (scratch, gitignored) |
| `docs/evidence/bug10-templates-{before,after}.png` | bukti visual BUG-10 |
| `nexus-frontend/scripts/serve-out.mjs` | **diperbaiki**: resolusi clean URL sesuai produksi |
| `nexus-frontend/scripts/check-payment-hidden.mjs` | **baru**: gerbang build — URL checkout haram ada di bundle saat pembayaran tutup |
| `nexus-frontend/src/lib/payment.ts` | **baru**: satu sakelar pembayaran (fail-closed) |
| `nexus-frontend/src/components/PaymentBanner.tsx` | **baru**: spanduk "pembayaran belum dibuka" di `/chat` |
