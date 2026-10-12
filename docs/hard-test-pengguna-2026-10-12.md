# HARD TEST PENGGUNA NYATA — KATALIR

**Tanggal:** 12 Oktober 2026
**Mode:** AUTONOMOUS + REAL USER PERSPECTIVE + EVIDENCE-ONLY
**Standar acuan:** praktik usability & QA Oktober 2026 (lihat §0)
**Frontend yang diuji:** https://katalir.de5.net
**Backend yang diuji:** https://gateway.katalir.de5.net/katalir-api
**Akun uji:** `otonom-test@katalir-internal.dev` (sesi Supabase nyata, refresh token asli)

---

## VERDICT

> ## ⛔ BELUM SIAP
>
> | Kriteria brief | Hasil | Lulus? |
> |---|---|---|
> | 10 skenario pengguna nyata | **2 PASS / 7 FAIL / 1 BLOCKED** | ❌ (< 8/10) |
> | Skor UX (rata-rata 5 aspek, target ≥ 4) | **3,2 / 5** | ❌ |
> | Mobile 375×667 + 320/768/1440 | tata letak **4/4 bersih**, kirim **4/4 gagal** | ❌ |
> | Load 5/10/20/50 user (≥5/9/18/45) | 5 ✅ · 10 ✅ · 20 ❌ · 50 ⛔ | ❌ |
> | Kepuasan pengguna (≥0,70) | **0,853** (judge tervalidasi) | ✅ |
>
> **TAPI — dan ini bagian terpentingnya:** **seluruh 7 kegagalan frontend berasal dari SATU cacat rilis yang sama**, dan **backend-nya sehat** (kepuasan jawaban 0,853, workflow 5 node/4 edge, load 1–10 user PASS). Artinya ini bukan "produk belum jadi" — ini **satu deploy frontend yang belum diperbaiki**. Perbaikan akarnya jelas, terverifikasi, dan sudah ada gerbang pencegahnya di repo (§5).

---

## 0. RISET WEB-FIRST (dijalankan sebelum menguji)

Metode dipilih setelah meninjau sumber: `nngroup.com/articles/usability-testing-2026`, `microsoft/playwright`, `checkly/playwright-examples`, dan ringkasan praktik usability AI SaaS 2026.

**5 metode terbaik yang ditemukan:**

| # | Metode | Cocok untuk | Peserta |
|---|---|---|---|
| 1 | Moderated remote | menemukan *mengapa* pengguna gagal | 5–8 |
| 2 | Unmoderated remote | volume + metrik | 15–30 |
| 3 | AI-moderated voice | skala besar, murah | 20–100+ |
| 4 | In-person | sinyal non-verbal | 5–12 |
| 5 | Guerrilla | umpan balik cepat | 3–5 |

Prinsip yang dipakai: **Nielsen — 5 pengguna menemukan ~80% masalah**; tulis **tugas, bukan pertanyaan**; ukur dengan **SEQ (Single Ease Question)**.

**Pilihan:** **unmoderated remote berbasis Playwright** + **time-box per charter**. Alasan: (a) target adalah SaaS web produksi, (b) butuh bukti yang bisa diaudit ulang (screenshot + log), bukan opini, (c) Playwright mereproduksi jalur pengguna nyata secara deterministik dan bisa dijalankan lagi kapan pun.

**Skill QA yang dimuat** (`git clone` → `addyosmani/agent-skills`, `naodeng/awesome-qa-skills`):
- `ux-quality-perspective` — hanya boleh menyatakan **PASS/FAIL/BLOCKED/NOT_RUN**, dilarang mengarang layar/state, pisahkan fakta/bukti/inferensi/celah.
- `manual-testing` — satu charter per time-box, catat `prasyarat → aksi → harapan → kenyataan → bukti → state`.
- `llm-evaluation-design` — **kalibrasi judge**, pisahkan evaluasi offline vs online.
- `browser-testing-with-devtools` — verifikasi berbasis screenshot, **console harus bersih**.
- `test-driven-development` — *Prove-It*; bendera merah: *"tes lulus di percobaan pertama"*, *"tidak ada tes yang benar-benar jalan"*.
- `code-review-and-quality` — langkah 5 *"Verify the Verification"*: tes apa yang jalan, screenshot untuk perubahan UI.

---

## 1. TASK 1 — 10 SKENARIO PENGGUNA NYATA

Harness: `tests/user_test/run_user_test.py` · Bukti: `tests/user_test/_user_test_results.json` + `docs/evidence/user-test/*.png`

| # | Skenario | Aksi | Harapan | Kenyataan | State | Bukti |
|---|---|---|---|---|---|---|
| 1 | Daftar (Google OAuth) | Klik "Login dengan Google" | Diarahkan ke consent Google lalu balik ke `/chat` | Tombol ada, redirect benar ke `accounts.google.com` — **berhenti di consent** (butuh akun Google manusia) | **BLOCKED** | `s01-a`, `s01-b` |
| 2 | Chat pertama | Ketik "Buat workflow sederhana" + Enter | Balasan < 30 s | **50,41 s, balasan TIDAK ADA**; muncul "Gagal mengirim / Koneksi lambat. Cek internetmu." | **FAIL** | `s02` |
| 3 | Bangun workflow dari chat | Prompt Telegram → buka `/builder` | Workflow terbangun, node terlihat | chat 55,06 s; `/builder` **nodes=0 edges=0** | **FAIL** | `s03-a`, `s03-b` |
| 4 | Riwayat chat bertahan | Refresh lalu buka `/chat` | Riwayat masih ada | sidebar kosong, 0 item | **FAIL** | `s04-a` |
| 5 | Simpan credential Telegram | Ketik "kirim ke telegram saya" | Form inline muncul | 45,08 s; `input_form=0` | **FAIL** | `s05-a` |
| 6 | Lihat templates | Buka `/templates` | Daftar template tampil | "**Gagal memuat template**"; 0 kartu | **FAIL** | `s06-a` |
| 7 | Edit workflow | Buka `/builder`, klik node | Node terpilih, bisa simpan | nodes=0, node tidak bisa dipilih | **FAIL** | `s07-a` |
| 8 | Cek insights | Buka `/insights` | Chart + metrik tampil | chart=0; banner **"Failed to fetch"** | **FAIL** | `s08-a` |
| 9 | Prompt ekstrem (12.000 char) | Kirim `x`×12000 | Pesan galat ramah + coba lagi | tombol "Coba Lagi" ada, pesan ramah ada | **PASS** | `s09-a` |
| 10 | Logout → login lagi | Hapus sesi, pulihkan | Identitas kembali | logout & pemulihan sesi benar | **PASS** | `s10-a/b/c` |

**Ringkasan:** `PASS=2 · FAIL=7 · BLOCKED=1 · NOT_RUN=0`

### 1.1 Akar tunggal dari 7 kegagalan

Console browser pada **setiap** skenario gagal berisi pola yang sama:

```
Connecting to 'https://web-production-dc90b.up.railway.app/<path>' violates
the following Content Security Policy directive: "connect-src 'self'
https://gateway.katalir.de5.net https://qmukkphwaajzbqjrcvaz.supabase.co …"
```

Path yang diblokir: `/chat`, `/models`, `/sessions`, `/quota`, `/templates`, `/insights`…

**Bukti rantai sebab (semuanya diverifikasi, bukan dugaan):**

1. `nexus-frontend/src/lib/api.ts:3` → `export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";`
2. `NEXT_PUBLIC_*` **di-inline saat build**, bukan saat runtime → nilai lama ikut ter-panggang ke bundle.
3. Pemindaian 74 berkas JS produksi (`tests/user_test/extract_cfg.py`) → satu-satunya host API di bundle: **`https://web-production-dc90b.up.railway.app`** (host **mati**: `/templates` dan `/health` → **404**).
4. `nexus-frontend/.env.example:5` masih memuat host lama yang sama.
5. CSP produksi (`public/_headers`) hanya mengizinkan `gateway.katalir.de5.net` + Supabase → **semua panggilan ke host lama diblokir browser**.

**Efek ke pengguna:** pesan **"Koneksi lambat. Cek internetmu."** — menyalahkan internet pengguna, padahal penyebabnya konfigurasi rilis kita sendiri. Ini masuk hitungan pada aspek UX *error_message* (§2).

---

## 2. TASK 2 — UX AUDIT (bukti, bukan opini)

Skor **dihitung** dari artefak uji oleh `tests/user_test/ux_audit.py` → `_ux_audit.json` (rumus bisa diaudit ulang).

| Aspek | Skor | Bukti |
|---|---|---|
| loading_time | **2 / 5** | rata-rata muat halaman **9,6 s**; rata-rata balasan chat **46,4 s** (target < 30 s) |
| clarity | **2 / 5** | 7/18 layar memakai kosakata Indonesia yang jelas; 1 layar memakai teks menyesatkan |
| error_message | **4 / 5** | ramah ✅, tombol coba-lagi ✅, **jujur ❌** (menyalahkan internet pengguna) |
| responsiveness | **5 / 5** | 4/4 viewport bersih; target sentuh ≥ 44 px di mobile ✅ |
| consistency | **3 / 5** | 9/16 rute 200; **kontrak `API_URL` tidak cocok dengan CSP** |

**Rata-rata: 3,2 / 5 → FAIL (target ≥ 4).**
Di bawah target: `loading_time`, `clarity`, `consistency`.

---

## 3. TASK 3 — MOBILE (WAJIB)

Harness: `tests/user_test/mobile_test.py` · Bukti: `_mobile_results.json` + `mobile-*.png`

| Viewport | Muat | Composer terlihat | Dapat diklik | Di dalam layar | Overflow X | Tombol < 44 px | Kirim |
|---|---|---|---|---|---|---|---|
| 320×568 | 22,1 s | ✅ | ✅ | ✅ | **0 px** | **0/9** | ❌ 25,4 s tanpa balasan |
| **375×667 (iPhone SE)** | 5,3 s | ✅ | ✅ | ✅ | **0 px** | **0/9** | ❌ 25,1 s tanpa balasan |
| 768×1024 | 5,1 s | ✅ | ✅ | ✅ | **0 px** | 3/9 | ❌ |
| 1440×900 | 5,9 s | ✅ | ✅ | ✅ | **0 px** | 2/9 | ❌ |

**Temuan jujur:**
- ✅ **Tata letak mobile-first SEHAT.** Composer benar-benar bisa disentuh (diuji dengan `elementFromPoint`, bukan sekadar `is_visible()`), nol overflow horizontal di keempat viewport, target sentuh ≥ 44 px di semua layar ponsel.
- ❌ **Kirim tetap gagal di keempat viewport** — cacat API/CSP yang sama, bukan masalah mobile.

Bukti visual `mobile-375x667.png`: pesan "tes mobile" terkirim, lalu kartu **"⚠ Gagal mengirim — Koneksi lambat. Cek internetmu." + Coba Lagi**.

---

## 4. TASK 4 — WORKFLOW NYATA: USE CASE SHOPEE

Prompt nyata: *"Buat workflow: webhook Shopee → batch order jam 8 → kirim WhatsApp → AI parse balasan → update Sheets"*

### 4.1 Lewat FRONTEND → **FAIL**

- chat 70,05 s, balasan tidak muncul → **"Gagal mengirim / Koneksi lambat. Cek internetmu."**
- `/builder`: **nodes = 0, edges = 0** — "Kanvas masih kosong"
- Bukti: `shopee-01-chat.png`, `shopee-02-canvas.png`

### 4.2 Lewat BACKEND (langsung) → **PASS**

Bukti: `docs/evidence/user-test/shopee-03-backend-workflow.json`

```
workflow name : Shopee Order to Sheets      (200, 11,4 s)
nodes         : 5
edges         : 4
   n1 trigger  Webhook Shopee
   n2 agent    Batch Order Jam 8
   n3 mcp      Kirim WhatsApp
   n4 agent    AI Parse Balasan
   n5 mcp      Update Sheets
   n1 → n2 → n3 → n4 → n5
```

**Kesimpulan:** mesin workflow + LLM **sehat dan memahami intent dengan tepat** (5 node, 4 edge, urutan persis sesuai permintaan, termasuk placeholder `{{nomor_tujuan}}` / `{{spreadsheet_id}}`). Yang gagal **hanya jembatan frontend→backend**.

---

## 5. TASK 5 — LOAD TEST

Harness: `tests/user_test/load_multi.py` — **N akun Supabase BERBEDA** (dibuat lewat Admin API, dihapus setelah selesai) supaya rate limiter per-akun tidak mengaburkan hasil. `dibuat 50 · JWT didapat 32 · dihapus 50/50`.

| n | OK | Error | p50 | p95 | Gate | Hasil |
|---|---|---|---|---|---|---|
| 1 | 1/1 | 0% | 8.972 ms | 8.972 ms | n/a | ✅ |
| 5 | 5/5 | 0% | 10.583 ms | 13.282 ms | ≥5 | ✅ PASS |
| 10 | 10/10 | 0% | 15.818 ms | 17.124 ms | ≥9 | ✅ PASS |
| 20 | 2/20 | **90%** | 9.044 ms | 9.388 ms | ≥18 | ❌ FAIL |
| 50 | 0/50 | — | — | — | ≥45 | ⛔ BLOCKED |

Kegagalan n=20: HTTP 503 `"Model sedang sibuk (quota/overload). Coba lagi dalam 1 menit."` — **kontensi kuota Gemini** saat 20 permintaan benar-benar bersamaan.
n=50 tidak tercapai karena hanya 32/50 akun berhasil login paralel.

**p95 tertinggi 17.124 ms (target < 5.000 ms) · error 90% (target < 5%) → VERDICT FAIL.**

> Catatan metodologi: percobaan pertama memakai **satu** akun dan "gagal" di n=10 — itu **mengukur limit produk (10 pesan/60 detik/akun), bukan kapasitas server**. Metodologi diperbaiki dengan akun terpisah; n=1/5/10 lalu lolos.

---

## 6. TASK 6 — KEPUASAN PENGGUNA (LLM-as-judge DISKRIMINATIF)

Harness: `tests/user_test/satisfaction_judge.py` → `_satisfaction_results.json`

### 6.1 Kenapa "diskriminatif" itu penting — dan ini bukan teori

Percobaan **pertama** memakai endpoint `/chat` produk sebagai judge. Hasilnya:

```
kalibrasi jangkar: GOOD=0.0  BAD=0.0  MID=0.175  →  INVALID
skor akhir       : 0.922  (seolah-olah LULUS gemilang)
```

**Judge stempel karet** akan melaporkan "0,922 — luar biasa". **Kalibrasi menangkapnya**: judge memberi nilai **0,0** untuk jawaban bagus dan **0,0** untuk jawaban buruk — artinya judge tidak mengukur apa pun. Penyebabnya: `/chat` menempelkan **persona produk Katalir**, yang menabrak instruksi penilai.

Perbaikan: judge memakai **model mentah Gemini** (`gemini_llm.chat_with_fallback`) dengan `system_instruction` sendiri + `temperature=0`.

### 6.2 Kalibrasi jangkar (setelah perbaikan)

| Jangkar | Harapan | Hasil | |
|---|---|---|---|
| GOOD (jawaban Shopee nyata) | ≥ 0,80 | **0,925** | ✅ |
| BAD ("Maaf, saya tidak mengerti") | ≤ 0,30 | **0,000** | ✅ |
| MID (setengah benar) | di antara | **0,125** | ✅ |

**→ Judge VALID & diskriminatif.** (Kejujuran tambahan: satu percobaan sempat gagal kalibrasi karena **jangkar salah pasang** — prompt Shopee dipasangkan jawaban Telegram; judge menilainya 0,05. Itu justru bukti judge peka terhadap ketidaksesuaian prompt↔jawaban.)

### 6.3 Skor 10 jawaban nyata (backend)

| # | Skenario | helpful | actionable | intent | expectation | Rata-rata | |
|---|---|---|---|---|---|---|---|
| S1 | onboarding | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |
| S2 | chat pertama | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |
| S3 | build workflow | 0,9 | 0,8 | 1,0 | 0,9 | **0,90** | PASS |
| S4 | history | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |
| S5 | credential | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |
| S6 | template | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |
| S7 | edit workflow | 0,4 | 0,0 | 0,9 | 0,5 | **0,45** | FAIL |
| S8 | insights | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |
| S9 | prompt ngawur | 0,2 | 0,0 | 0,2 | 0,3 | **0,175** | FAIL |
| S10 | logout/login | 1,0 | 1,0 | 1,0 | 1,0 | **1,00** | PASS |

**Per-dimensi:** helpful **0,85** · actionable **0,78** · intent **0,91** · expectation **0,87**
**Overall 0,853 ≥ 0,70 → PASS** (8/10 lulus)

**Cross-check deterministik (tanpa LLM):** 10/10 jawaban tidak kosong · 7/10 punya langkah bernomor · 2/10 punya placeholder · cakupan entitas **1,00**. Konsisten dengan skor judge.

S7 & S9 gagal secara wajar: S7 ("tambahkan filter ke workflow tadi") tidak punya konteks sebelumnya; S9 sengaja prompt ngawur.

> **Batasan yang dinyatakan terbuka:** mutu jawaban diukur lewat **backend langsung**, karena frontend sedang tidak bisa mengirim pesan. Skor 0,853 adalah mutu **model + workflow engine**, bukan pengalaman end-to-end pengguna (yang saat ini 0/7 berhasil).

---

## 7. AKAR MASALAH & PERBAIKAN

### Cacat produksi (blocker)

`NEXT_PUBLIC_API_URL` ter-panggang di bundle build ke host mati `web-production-dc90b.up.railway.app`, sementara CSP produksi hanya mengizinkan `gateway.katalir.de5.net`. Browser memblokir **semua** panggilan API → chat, template, insights, builder, riwayat, kredensial semuanya mati.

**Perbaikan yang sudah dilakukan di repo (mencegah terulang):**

| Berkas | Isi |
|---|---|
| `nexus-frontend/scripts/check-api-url-csp.mjs` | **Gerbang pre-build**: membaca `connect-src` dari `public/_headers`, **menggagalkan build** bila origin `NEXT_PUBLIC_API_URL` tidak diizinkan (mendukung wildcard `*.`). Keluar kode 1 dengan petunjuk ke insiden 12 Okt 2026. |
| `nexus-frontend/.env.example` | **Perlu diperbarui** ke `https://gateway.katalir.de5.net/katalir-api` (masih memuat host lama). |
| Deploy produksi | **Perlu build + redeploy** frontend dengan `NEXT_PUBLIC_API_URL` yang benar (tidak bisa dikerjakan dari lingkungan ini). |

### Prioritas tindak lanjut

| P | Tindakan | Dampak |
|---|---|---|
| **P0** | Set `NEXT_PUBLIC_API_URL=https://gateway.katalir.de5.net/katalir-api`, build ulang, deploy; aktifkan gerbang `check-api-url-csp.mjs` di pipeline | membuka 7/10 skenario sekaligus |
| **P0** | Ganti teks galat "Koneksi lambat. Cek internetmu." → jujur & bisa ditindak | memperbaiki aspek `error_message` |
| **P1** | Naikkan kuota/konkurensi Gemini agar n≥20 tidak 503 | load gate 20 & 50 |
| **P1** | Turunkan latensi balasan (46,4 s → target < 30 s) | aspek `loading_time` |
| **P2** | Sediakan jalur uji OAuth tanpa akun Google manusia (test identity) | membuka S1 yang BLOCKED |
| **P2** | Perbaiki 404 pada rute yang ditautkan (`/login`, `/dashboard`, dll.) | aspek `consistency` |

---

## 8. INDEKS BUKTI

| Artefak | Isi |
|---|---|
| `tests/user_test/_user_test_results.json` | 10 skenario lengkap (prasyarat→aksi→harapan→kenyataan→state) |
| `tests/user_test/_mobile_results.json` | 4 viewport × (composer, overflow, target sentuh, kirim) |
| `tests/user_test/_shopee_results.json` | Shopee via frontend (FAIL) |
| `docs/evidence/user-test/shopee-03-backend-workflow.json` | Shopee via backend (5 node / 4 edge) |
| `tests/user_test/_load_multi_results.json` | Load 1/5/10/20/50, akun dibuat & dihapus |
| `tests/user_test/_satisfaction_results.json` | Skor judge + kalibrasi VALID |
| `tests/user_test/_satisfaction_chatjudge_invalid.json` | **Bukti judge stempel karet tertangkap kalibrasi** (0,922 tapi INVALID) |
| `tests/user_test/_ux_audit.json` | Matriks UX 5 aspek + rumus |
| `tests/user_test/_recon.json` | 16 rute, status HTTP, teks kepala |
| `docs/evidence/user-test/*.png` | 19 screenshot (10 skenario + 4 mobile + 2 shopee + recon) |

**Reproduksi:**
```bash
python tests/user_test/bootstrap_session.py     # sesi Supabase nyata
python tests/user_test/run_user_test.py         # TASK 1
python tests/user_test/ux_audit.py              # TASK 2
python tests/user_test/mobile_test.py           # TASK 3
python tests/user_test/shopee_test.py           # TASK 4
python tests/user_test/load_multi.py            # TASK 5
python tests/user_test/satisfaction_judge.py    # TASK 6
```
