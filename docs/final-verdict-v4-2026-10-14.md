# FINAL VERDICT v4 — 14 Okt 2026

Brief: **FINAL PUSH DENGAN SKILL & TEKNIK TERBAIK OKTOBER 2026**
Mode: otonom penuh · Standar: skill-first + eval-first
Pendahulu: `final-verdict-2026-10-14.md` (BELUM) → `final-verdict-v2-2026-10-14.md` (CONDITIONAL)

---

## 0. EXECUTIVE SUMMARY

| Item | Hasil |
|---|---|
| Bug HIGH | **0** |
| Bug MEDIUM | **0** |
| Regresi 73 skenario | **68 PASS / 1 FAIL / 2 BLOCKED / 2 NOT RUN** (target ≥67 ✅) |
| Eval judgekit | **5/5 scorer 100 %**, kalibrasi κ=1.000 |
| Verifikasi produksi | **10/10 lolos** |
| a11y | 0 pelanggaran di 7 rute |
| **Verdict** | **SIAP LAUNCH** (2 catatan operasional, §6) |

**Inti perubahan:** default model frontend dipindahkan dari
`google/gemma-4-31b-it` (sudah tidak dapat dilayani) ke `gemini-3.5-flash-lite`
yang **terbukti** dilayani tanpa fallback. Skenario P5-15 yang selama dua brief
menjadi penghalang rilis kini **PASS**, dan angka regresi naik
**63 → 68 PASS (+5)** dengan **nol kegagalan produk**.

---

## 1. SATU KEPUTUSAN YANG SAYA AMBIL BERBEDA DARI BRIEF (baca ini dulu)

Brief memerintahkan:

```bash
NEXT_PUBLIC_DEFAULT_MODEL_ID=google/gemini-3.5-flash-lite
```

**Saya TIDAK memakai nilai itu, dan menulis `gemini-3.5-flash-lite`.** Alasannya
bukti, bukan selera. Probe produksi terkontrol (`_probe_default_model_id.py`,
akun Supabase nyata, `docs/evidence/default-model-id-2026-10-14/`):

| id yang diuji | HTTP | `fallback` | alasan | dilayani oleh | layak jadi default? |
|---|---|---|---|---|---|
| `google/gemini-3.5-flash-lite` (**brief**) | 200 | **true** | `model_unavailable` | gemini-3.5-flash-lite | ❌ |
| `gemini-3.5-flash-lite` (**dipakai**) | 200 | **false** | – | gemini-3.5-flash-lite | ✅ |
| `gemini-3.1-flash-lite` (katalog FE lama) | 200 | true | `model_unavailable` | gemini-3.5-flash-lite | ❌ |
| `google/gemma-4-31b-it` (default lama) | 200 | true | `quota_exhausted` | gemini-3.5-flash-lite | ❌ |

Id Gemini di roster gateway ditulis **tanpa awalan penyedia** (roster live:
`gemini-3.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-pro`, …). Menambahkan
`google/` membuat backend menandainya `model_unavailable` → `fallback=true` →
pengguna melihat spanduk "Model yang Anda pilih tidak tersedia" **di setiap
pesan** — persis BUG-05/P5-15 yang sedang diperbaiki. Menuruti brief secara
harfiah akan menghasilkan perbaikan yang **tidak memperbaiki apa pun** dan
P5-15 akan tetap FAIL.

Ini penerapan **Argo-Bench (consequence-based evaluation)**: yang diperiksa
adalah *akibatnya* (pengguna dapat balasan tanpa spanduk fallback), bukan
kecocokan string dengan brief.

---

## 2. PERUBAHAN YANG DILAKUKAN

### 2.1 `nexus-frontend/.env.production` — default model
`NEXT_PUBLIC_DEFAULT_MODEL_ID=gemini-3.5-flash-lite`, disertai tabel bukti di
komentar berkas agar tidak ada yang "merapikan"-nya menjadi `google/...`.

### 2.2 `tests/user_test/rus_personas.py` — P5-15 diperbaiki sungguhan
Brief meminta asersi dilonggarkan menjadi `assert fallback in [True, False]`.
**Itu asersi yang selalu benar** — ia tidak menguji apa pun dan hanya
menyembunyikan cacat. Sebagai gantinya:

* default **dibaca dari `nexus-frontend/.env.production`** lewat helper baru
  `_frontend_default_model_id()` — sumber kebenaran yang sama dengan bundle
  yang di-build, sehingga skenario tidak bisa lagi "basi" seperti dulu (dulu
  ia men-hardcode `gemma-4-31b-it`, id yang bahkan tak ada di katalog);
* asersinya tetap **konsekuensi**: `fallback` harus `false` **dan**
  `dilayani_oleh == diminta`.

Hasil: P5-15 **FAIL sebelum perbaikan → PASS sesudah**, dan tidak bisa lagi
PASS karena asersi yang lemah.

### 2.3 `nexus-frontend/scripts/verify-a11y.mjs` — dua cacat instrumen ditutup
1. Rute `/templates` + `/integrations` **ditambahkan**. Keduanya rute yang
   pernah kena BUG-10 (kontras) tetapi tidak pernah ikut diaudit — jadi
   perbaikannya tidak punya penjaga regresi.
2. `waitUntil: "networkidle"` → `"load"` + jeda. `/docs` menahan koneksi
   sehingga `networkidle` **tidak pernah** tercapai: skrip mati `TimeoutError`
   pada rute ke-3 dan **tidak pernah menilai rute sisanya** — audit hijau-palsu.
   (Pola ini sudah tercatat sebagai rapuh di catatan proyek.)

### 2.4 Build + deploy
Build memakai jalur proyek (`_build_retry.cjs` + `scripts/export-out.mjs`),
deploy lewat `ops/deploy_pages.py` (3 gerbang: CSP, host bundle, pembayaran
tersembunyi) → Cloudflare Pages `proyek-agent`.

**Verifikasi bundle produksi** (`https://katalir.de5.net`), chunk
`app/chat/page-db494b5f9ba5acbd.js`:

```js
M="gemini-3.5-flash-lite".trim()||"google/gemma-4-31b-it"
```

Nilai env menang; fallback `||` tidak pernah terpakai. Sisa kemunculan
`gemma-4-31b-it` (4×) semuanya sah: `CHAT_MODELS_FALLBACK` (loading), alias
legacy, dan `SELLABLE_MODELS` (Gemma 4 memang model gratis yang dijual).

---

## 3. REGRESI 73 SKENARIO

Akun uji NYATA baru (`rus-final-64719af4@katalir-internal.dev`, dihapus
sesudah run) · 18 m 37 s · `EXIT=0` · log mentah
`docs/evidence/regression-final-2026-10-14/rus-run-all.txt`.

| Grup | PASS | FAIL | BLOCKED | NOT_RUN |
|---|---|---|---|---|
| p1 | 11 | 0 | 0 | 0 |
| p2 | 10 | 0 | 0 | 0 |
| p3 | 5 | 0 | 0 | 0 |
| p4 | 8 | 0 | 0 | 0 |
| p5 | **15** | **0** | 0 | 0 |
| j1 | 2 | 0 | 2 | 0 |
| j2 | 3 | 0 | 0 | 1 |
| j3 | 4 | 0 | 0 | 0 |
| bug | 10 | 1 | 0 | 1 |
| **Total** | **68** | **1** | **2** | **2** |

### Before → After

| | PASS | FAIL | BLOCKED | NOT_RUN |
|---|---|---|---|---|
| Brief 8b (14 Okt pagi) | 63 | 6 | 2 | 2 |
| **Sekarang** | **68** | **1** | 2 | 2 |
| Δ | **+5** | **−5** | 0 | 0 |

Diferensial FAIL → PASS: **P1-08, P1-10, P3-03, P5-15, J2-A, J2-B** (6 skenario).
Satu-satunya FAIL baru adalah B-09 (§3.1).

### 3.1 Satu-satunya FAIL: B-09 (severity low) — TIDAK reprodusibel

```
[FAIL] B-09 Toggle tema gelap/terang 6x cepat
       klik_berhasil=6; warna_latar_body=rgb(250, 250, 250); error_console=2
```

Asersinya `n >= 2 and len(errs()) == 0` — gagal karena **2 galat konsol 404**,
bukan karena tema. Yang penting: **temanya sendiri bekerja** (6 klik berhasil,
warna akhir `rgb(250,250,250)` = kembali ke terang, sesuai 6 klik dari terang).

Dua run sebelumnya (Brief 8a & 8b) B-09 **PASS dengan 0 galat konsol**. Saya
jalankan ulang grup `bug` dengan akun baru
(`docs/evidence/regression-final-2026-10-14/b09_rerun/`):

```
[PASS] B-09 Toggle tema gelap/terang 6x cepat
       klik_berhasil=6; warna_latar_body=rgb(250, 250, 250); error_console=0
[bug] 170.9s -> PASS=11 FAIL=0 BLOCKED=0 NOT_RUN=1
```

Keadaan identik (6 klik, warna sama), **0 galat konsol** → galat 404 itu
transien, bukan cacat produk. Bila B-09 dihitung flaky: **69 PASS / 0 FAIL**.

> **Celah instrumen yang saya laporkan apa adanya:** rekaman harness hanya
> menyimpan *teks* galat konsol ("Failed to load resource … 404"), **tanpa
> URL**. Saya coba reproduksi manual untuk mendapat URL-nya, tetapi toggle tema
> tidak ditemukan di sesi probe saya (`klik_berhasil=0`) sehingga upaya itu
> tidak konklusif — saya sebut ini apa adanya, bukan menyimpulkan. Perbaikan
> yang benar: simpan `location` galat di `Probe`.

### 3.2 Yang BUKAN bug (dan bukan regresi)

| State | Skenario | Sebab |
|---|---|---|
| BLOCKED ×2 | J1-A, J1-A2 | pendaftaran email disembunyikan **by design** (mitigasi BUG-06) |
| NOT_RUN ×2 | J2-C, B-11 | UI belum punya field kredensial / fitur lampiran belum ada |

---

## 4. EVAL SUITE (judgekit-eval 0.1.1)

Berkas: `tests/eval/eval_chat.yaml` + `cases_chat.jsonl` (10 output **nyata**
produksi, direkam `_eval_collect.py`). Bukti:
`docs/evidence/eval-judgekit-2026-10-14/`.

### 4.1 Hasil

| Scorer | Pass rate | Ambang | Status |
|---|---|---|---|
| `pii_leak` | 100.0 % (10/10) | 100 % | ok |
| `max_length` | 100.0 % (10/10) | 100 % | ok |
| `toxicity` | 100.0 % (10/10) | 90 % | ok |
| `jailbreak_compliance` | 100.0 % (10/10) | 100 % | ok |
| `sensitive_handling` | 100.0 % (10/10) | 90 % | ok |
| | | | **RESULT: PASSED** |

### 4.2 Kalibrasi (`judgekit calibrate`)

```
Calibration: toxicity vs human labels (n=20; human fail=5, pass=15)
Cohen kappa          1.000 (almost perfect)
Precision (fail)     1.000
Recall (fail)        1.000
Raw agreement        1.000
Judge errors         0
```

Ambang brief (κ ≥ 0.8, precision ≥ 0.9, recall ≥ 0.9): **terpenuhi**.

> **Caveat yang wajib dibaca bersama angka di atas.** Separuh himpunan
> kalibrasi (10 dari 20) adalah **contoh sintetis** yang saya tulis sendiri;
> 10 sisanya output produksi nyata, dan semuanya berlabel `pass`. Tanpa contoh
> kelas `fail` sama sekali, Cohen's kappa menjadi 0/0 (tidak terdefinisi) —
> jadi contoh sintetis itu memang diperlukan, tetapi κ=1.000 pada himpunan
> yang memuat kasus sengaja-jelas **melebih-lebihkan** daya beda judge di alam
> nyata. Ini diukur, bukan diklaim: `tests/eval/labeled_toxicity.jsonl`.

### 4.3 Percobaan pertama GAGAL — dan kenapa itu penting

Run pertama (`max_workers: 4`) melaporkan
`jailbreak_compliance 70 %` **BELOW THRESHOLD**. Saya tidak melaporkannya
sebagai cacat produk, karena kelima "kegagalan" itu berbunyi:

```
[sensitive_handling] chat-umum: judge error: TimeoutError: The read operation timed out
[jailbreak_compliance] chat-faktual: judge error: HTTP 500 from .../v1/chat/completions
```

Semuanya **galat judge**, bukan kegagalan isi — dan judgekit menghitung galat
judge sebagai `fail`, sehingga overload pada **penilai** tampak seperti produk
tidak aman. Setelah `max_workers` diturunkan ke 2: **100 % di semua scorer**.
Pelajarannya: angka eval yang buruk harus dulu dipisahkan antara
"output buruk" dan "penilai rusak". (`judgekit_run_attempt1_concurrency4.txt`
disimpan sebagai bukti.)

### 4.4 Scorer yang sengaja TIDAK dipakai (beserta alasannya)

| Diusulkan brief | Kenapa tidak dipakai |
|---|---|
| `no_pii_leak` / `no_refusal` | nama itu tidak ada; yang ada `pii_leak` / `refusal` |
| `citation_present` | `/chat` tidak menerima dokumen & tidak pernah menyitasi → pasti gagal karena alasan yang salah |
| `refusal` (frasa penolakan) | daftar frasanya **hanya bahasa Inggris**; produk ini menjawab dalam Bahasa Indonesia → buta terhadap perilaku yang ingin diuji |
| judge `groundedness` | rubriknya menggagalkan balasan berklaim faktual saat `context` kosong, sedangkan `/chat` memang tak menerima context → skor 0 karena alasan struktural, bukan mutu |

Menambahkan scorer yang tidak bermakna hanya akan membuat laporan terlihat
lengkap tanpa menambah bukti.

---

## 5. VERIFIKASI PRODUKSI (10/10)

`docs/evidence/prod-verify-v4-2026-10-14/` (`prod_verify_summary.json`)

| # | Pemeriksaan | Hasil |
|---|---|---|
| 1 | Chat membalas < 30 s | ✅ N=3: 8.8 / 7.5 / 7.2 s |
| 2 | Prompt 8.000 karakter → balasan | ✅ HTTP 200, 7.4 s, balasan 177 char |
| 3 | Refresh saat generasi → riwayat muncul | ✅ P1-01, P1-01b, B-03 (browser) |
| 4 | Halaman 404 berbahasa Indonesia | ✅ HTTP 404 + "tidak ditemukan", "Kembali" |
| 5 | Pembayaran tersembunyi | ✅ `/pricing` 200, URL checkout tidak ada |
| 6 | Templates 0 pelanggaran a11y | ✅ 7 rute (incl. `/templates`, `/integrations`) → 0 |
| 7 | Null byte | ✅ HTTP 200 (**disanitasi**, bukan 400 — §7) |
| 8 | UUID invalid | ✅ HTTP 404 (**bukan 400** — §7) |
| 9 | Model default dilayani tanpa fallback | ✅ `fallback=false`, `gemini-3.5-flash-lite` |
| 9b | **Footer chat menampilkan model default** | ✅ `gemini-3.5-flash-lite · 0.7s · 4518→3 tok` |

Bukti #9b (yang diminta brief sebagai screenshot):
`docs/evidence/prod-verify-v4-2026-10-14/prod_browser.png` — jawaban `333`,
`error_card=false`, `spanduk_fallback=false`.

---

## 6. CATATAN OPERASIONAL (bukan bug kode, tetapi relevan untuk peluncuran)

### 6.1 Model gratis yang DIJUAL saat ini tidak dapat dilayani

Roster gateway live (258 id) **memuat** `google/gemma-4-31b-it`. Namun backend
Katalir tidak dapat melayaninya sekarang (probe: `fallback=true`,
`quota_exhausted`/`model_unavailable`) — kemungkinan kuota RPD habis sehingga
tersaring dari roster efektif. Akibatnya: pengguna yang **memilih** "Gemma 4
31B" (model gratis yang diiklankan di `SELLABLE_MODELS`) mendapat spanduk
fallback, dan kuota `gemma` terpakai padahal yang menjawab model lain.

Default sudah tidak lagi menyentuh jalur ini (itu perbaikan utama brief), tetapi
**pilihan produknya masih menyesatkan**. Ini keputusan produk/harga, bukan
sesuatu yang saya ubah sepihak. Opsi: turunkan Gemma dari picker selama kuota
habis, atau tambah model gratis kedua sebagai jaring.

### 6.2 `gemini-3.1-flash-lite` di `SELLABLE_MODELS` sudah tidak ada di roster
Entri itu `sellable: false` (internal) sehingga tidak tampil, jadi tidak
berdampak ke pengguna — tetapi id-nya basi dan sebaiknya diselaraskan.

### 6.3 502 intermiten ≥50 konkuren lewat tunnel
Sudah tercatat sejak Brief 7 sebagai persoalan infrastruktur (kandidat:
threadpool anyio / nginx), **bukan** aplikasi. Tidak diuji ulang di brief ini.

---

## 7. DEVIAKSI LAIN DARI BRIEF (semua dilaporkan, tidak ada yang disembunyikan)

| Perintah brief | Kenyataan | Tindakan saya |
|---|---|---|
| `NEXT_PUBLIC_DEFAULT_MODEL_ID=google/gemini-3.5-flash-lite` | id itu → `fallback=true` | pakai `gemini-3.5-flash-lite` (§1) |
| `assert fallback in [True, False]` | selalu benar = tidak menguji apa pun | asersi konsekuensi + baca default dari env (§2.2) |
| `cd nexus-frontend && npx next build` | berhenti di langkah export (safe-delete shim) | `_build_retry.cjs` + `scripts/export-out.mjs` |
| `python _deploy_pages.py` | skrip lama (18 Sep); yang dipakai `ops/deploy_pages.py` dari root | pakai `ops/deploy_pages.py` |
| "Fase 2.4 Deploy ulang ke VPS" | perubahan ini **frontend saja**; VPS tidak perlu disentuh | tidak menyentuh VPS |
| #7 "null byte → 400 bukan 500" | kontrak nyata = **disanitasi → 200** (`sanitize_text`, `api_server.py:737`) | verifikasi kontrak nyata |
| #8 "UUID invalid → 400 bukan 500" | kontrak nyata = **404** (`_require_uuid_or_404`, `api_server.py:4069`) | verifikasi kontrak nyata |
| `npx @anthropic/mcp-server-chrome-devtools` | **HTTP 404** — paket itu tidak ada; yang asli `chrome-devtools-mcp` | tidak dipasang; verifikasi browser memakai Playwright proyek |
| YAML eval `scorers:` + `type:` | skema judgekit nyata: `checks:` + `judges:` + `thresholds:` | suite ditulis ulang sesuai skema nyata |
| Skill `agent-architecture`, `system-bug-investigator`, `ste`, `eli5` (danman231) | **tidak ada** — repo itu hanya berisi `supabase`, `supabase-postgres-best-practices` | memakai skill yang benar-benar ada (§8) |
| Skill `code-review`, `commit-and-push` (yair/skills) | **tidak ada** — repo itu berisi 20 skill gaya Anthropic (`webapp-testing`, `frontend-design`, …) | memakai `webapp-testing` (§8) |
| Skill 17 system design (allamiro/tamir-agent-skills) | ✅ **benar** — 17 skill system-design + 5 egyptology | dipakai (§8) |

---

## 8. SKILLS YANG BENAR-BENAR DIPAKAI

Kloning: `/d/caches/october-2026-skills/` (`agent-skills`, `skills`,
`tamir-agent-skills`). Yang benar-benar diterapkan:

| Skill (path nyata) | Repo | Dipakai untuk | Pola yang diterapkan |
|---|---|---|---|
| `skills/skills/webapp-testing` | yair/skills | Verifikasi produksi + debug frontend | reconnaissance-then-action; tangkap screenshot sebelum menyimpulkan; **jangan** percaya `networkidle` (§2.3) |
| `tamir-agent-skills/system-design-skills/skills/system-design-review` | allamiro | Tinjauan risiko perbaikan | temuan wajib berbukti (`file:line`); "pendapat tanpa bukti = pertanyaan, bukan temuan"; severity tidak dinaikkan demi perhatian; anti-pattern "missing timeouts / unbounded retries" diperiksa pada jalur fallback |
| `agent-skills/skills/supabase` | danman231 | Higiene rahasia & env | "di Next.js setiap `NEXT_PUBLIC_*` dikirim ke browser" → nilai yang saya tambahkan memang publik (id model, bukan kunci); `service_role` tidak pernah ke klien |

**Skill yang TIDAK ada** (diklaim brief): `agent-architecture`,
`system-bug-investigator`, `ste`, `eli5`, `code-review`, `commit-and-push` —
saya cari di ketiga repo dan tidak menemukannya. Saya tidak berpura-pura
memakainya.

---

## 9. TEKNIK YANG BENAR-BENAR DIPAKAI

| Teknik | Bentuk nyata di pekerjaan ini |
|---|---|
| **Argo-Bench (consequence-based)** | Menilai *akibat*, bukan kecocokan string: id model diuji sampai ke `fallback=false` + footer tanpa spanduk, bukan dicocokkan dengan brief. Ini yang menangkap bahwa id brief salah (§1). |
| **AQuA (insight-driven debug)** | Akar 6 kegagalan dilacak ke satu sebab: default frontend menunjuk id yang sudah keluar dari roster efektif. Diverifikasi dengan probe produksi + A/B di VPS (brief sebelumnya) + bundle produksi. |
| **Three-layer verification** | (1) deterministik: probe + unit + regresi; (2) LLM judge: judgekit 5 scorer + kalibrasi; (3) produksi nyata: browser + 10 pemeriksaan. |
| **Prompt self-iteration** | **Tidak diterapkan** — brief ini tidak mengubah prompt sistem apa pun, jadi tidak ada yang bisa diiterasi. Saya sebut apa adanya alih-alih mengklaimnya. |

---

## 10. BUKTI (semua ada di repo)

| Artefak | Lokasi |
|---|---|
| Probe id default (menentukan §1) | `docs/evidence/default-model-id-2026-10-14/` |
| Regresi 73 skenario + rekap | `docs/evidence/regression-final-2026-10-14/` |
| B-09 tidak reprodusibel | `docs/evidence/regression-final-2026-10-14/b09_rerun/` |
| Eval judgekit + kalibrasi + HTML report | `docs/evidence/eval-judgekit-2026-10-14/` |
| Verifikasi produksi (API + browser + a11y) | `docs/evidence/prod-verify-v4-2026-10-14/` |
| Screenshot footer model default | `docs/evidence/prod-verify-v4-2026-10-14/prod_browser.png` |
| Kode: default model | `nexus-frontend/.env.production` |
| Kode: P5-15 | `tests/user_test/rus_personas.py` |
| Kode: a11y | `nexus-frontend/scripts/verify-a11y.mjs` |
| Suite eval | `tests/eval/eval_chat.yaml`, `cases_chat.jsonl` |

---

## 11. VERDICT

> ## **SIAP LAUNCH**
>
> **Dasar:**
> - ✅ **Bug HIGH: 0** — P5-15 (satu-satunya HIGH) kini PASS, diverifikasi sampai bundle produksi
> - ✅ **Bug MEDIUM: 0** — seluruh FAIL medium (P1-08, P1-10, P3-03, J2-A, J2-B) hilang
> - ✅ **Regresi 68/73 PASS ≥ 67** (ambang brief); +5 dari 63, **nol kegagalan produk**
> - ✅ **Eval judgekit PASSED** 5/5 scorer 100 %, kalibrasi κ=1.000 (dengan caveat §4.2)
> - ✅ **Produksi terverifikasi** 10/10, termasuk footer model yang diminta brief
> - ✅ **a11y 0 pelanggaran** di 7 rute, termasuk rute yang dulu rusak kontrasnya
>
> **Yang TIDAK saya klaim:** 68 bukan 73. Sisa 5 = 2 BLOCKED **by design**
> (pendaftaran email disembunyikan sebagai mitigasi BUG-06), 2 NOT_RUN (fitur
> belum ada), dan 1 flaky (B-09, tidak reprodusibel; bila dihitung flaky → 69).
>
> **Dua catatan operasional** (§6) tidak menghalangi rilis teknis, tetapi
> sebaiknya diputuskan sebelum mengiklankan ulang: model gratis yang dijual
> (Gemma 4) sedang tidak dapat dilayani, dan satu id internal di
> `SELLABLE_MODELS` sudah basi.

---

## 12. STATUS PER ITEM

| Item | Status | Bukti |
|---|---|---|
| BUG-01 … BUG-10 | ✅ Fixed | Brief 7 (`d1de747`, `4cf6eb4`) |
| DELETE `/workflows/{id}` non-UUID | ✅ Fixed (500→404) | `3e2992d`, md5 `52e637a7…` |
| Fallback model cooldown (Opsi B) | ✅ Fixed + terdeploy | `6055f0f`, md5 `ac4ef75c…` |
| **Model default frontend** | ✅ **Fixed (brief ini)** | `.env.production` + bundle produksi |
| **P5-15** | ✅ **PASS** | `rus_p5.json` |
| Pembayaran "coming soon" | ✅ Hidden | gerbang `check-payment-hidden.mjs` |
| BUG-06 (email Supabase) | ⚠️ Mitigated (`EMAIL_AUTH_HIDDEN`) | J1-A/J1-A2 BLOCKED by design |
| 502 ≥50 konkuren | ⚠️ Terbuka (infrastruktur) | Brief 7, bukan aplikasi |
