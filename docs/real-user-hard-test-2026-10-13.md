# KATALIR — REAL USER HARD TEST (BUG HUNT DARI PERSPEKTIF PENGGUNA)

**Tanggal:** 13 Oktober 2026
**Mode:** Autonomous · Real User Simulation · Bug Hunting
**Target uji:** Frontend `https://katalir.de5.net` · Backend `https://gateway.katalir.de5.net/katalir-api`
**Akun uji:** `rus-final-c8055fba@katalir-internal.dev` (dibuat & dihapus otomatis oleh harness)
**Harness:** `tests/user_test/` (rus_core · rus_personas · rus_extra · rus_run · rus_report + 4 skrip reproduksi terarah)
**Bukti mentah:** `docs/evidence/real-user-2026-10-13/` — **106 PNG · 6 video (webm) · 1 network log (jsonl)** = 113 berkas, 30 MB
**Digest mesin:** `tests/user_test/_rus_digest.json` · `_rus_digest.md`

---

## 1. EXECUTIVE SUMMARY

**VERDICT: CONDITIONAL (SIAP DENGAN SYARAT)**
**0 critical · 3 high · 4 medium · 3 low**

Dari **73 skenario** yang dijalankan dengan 5 persona pengguna nyata, **62 PASS · 9 FAIL · 2 NOT_RUN · 0 BLOCKED**.

Aplikasi ini **tidak mengalami kehilangan data, tidak ada kebocoran lintas-pengguna, dan tidak ada celah eksekusi skrip**. Isolasi data multi-user terbukti bersih di tiga lapis (daftar, akses langsung lintas-user, dan tingkat sesi browser). Ketahanan input berbahaya (SQL injection, XSS, HTML mentah, RTL, payload 2 MB, JSON rusak, prompt injection) **semuanya lulus**.

Namun **tiga cacat high** harus diperbaiki sebelum peluncuran publik, karena dua di antaranya menyentuh alur utama (chat) dan satu memblokir pertumbuhan (pendaftaran pengguna baru):

1. **Prompt tepat pada batas maksimum yang diizinkan UI (8.000 karakter) tidak pernah dibalas.** UI mengirim 1 permintaan, backend menjawab HTTP 200 dalam **8 detik**, tetapi layar tetap kosong selama **150 detik** tanpa balasan, tanpa kartu galat, dan **tanpa indikator proses sama sekali**.
2. **Refresh saat AI masih bekerja melempar user ke chat kosong.** Pesan sebenarnya tersimpan di server (judulnya muncul di sidebar), tetapi area percakapan tidak memulihkan sesi — bagi user, pesannya "hilang".
3. **Pendaftaran pengguna baru tidak dapat diandalkan.** Pendaftaran email+sandi mengembalikan **HTTP 429 "email rate limit exceeded"** setelah beberapa percobaan, karena konfirmasi email wajib (`mailer_autoconfirm=false`) sementara SMTP bawaan Supabase (tanpa SMTP kustom) membatasi pengiriman email.

Di sisi positif, **7 temuan awal ternyata artefak harness** dan sudah dikoreksi (lihat §6) — termasuk dua "bug" yang tadinya tampak serius (panggilan API terputus, dan spam 12 pesan). Ini penting: laporan ini tidak menutupi bug, tetapi juga tidak mengarang bug.

**Yang harus diperbaiki sebelum launch (urutan prioritas):**

| # | Perbaikan | Berkas |
|---|---|---|
| 1 | Perbaiki alur prompt 8.000 karakter (BUG-01) | `ChatApp.tsx`, `ChatComposer.tsx` |
| 2 | Pulihkan sesi aktif setelah refresh (BUG-02) | `ChatApp.tsx` |
| 3 | Naikkan batas/kirim SMTP kustom untuk pendaftaran (BUG-06) | konfigurasi Supabase |
| 4 | Perbaiki id model default (BUG-05) | `models.ts:24` |
| 5 | Jangan bocorkan pesan internal DB (BUG-03, BUG-04) | `api_server.py` |
| 6 | Tambahkan halaman 404 sendiri (BUG-07) | `src/app/not-found.tsx` (belum ada) |

---

## 2. METODOLOGI

### 2.1 Lima persona, 10+ skenario masing-masing

| Persona | Karakter | Jumlah skenario | Fokus |
|---|---|---|---|
| **P1 Budi** | Tidak sabar, refresh bila >5 detik | 11 | refresh/spam/back/stop, latensi, tab kedua |
| **P2 Siti** | Pemula, salah klik | 10 | onboarding, prompt kabur, 20 rute nyata, 404, bahasa, label tombol |
| **P3 Andi** | Distracted, multi-tab | 5 | 3 tab, pindah tab, 2 tab 1 sesi, sinkronisasi sidebar, idle 90 s |
| **P4 Rina** | Jaringan 3G lambat | 8 | throttle CDP 3G, offline, abort request, latensi API 2 s |
| **P5 Dedi** | Kritis, uji batas | 15 | emoji, 10.000 char, SQLi, XSS, null byte, RTL, HTML, 2 MB, JSON rusak, non-UUID, burst, fallback model |
| **J1–J3** | Journey end-to-end | 12 | user baru → workflow; integrasi Shopee; kolaborasi/isolasi multi-user |
| **B-01–B-12** | Bug hunt terarah | 12 | boundary, state, timing, UI, data, aksesibilitas (axe-core) |

### 2.2 Instrumen

- **Playwright (Python 1.58.0)** headless Chromium, `PLAYWRIGHT_BROWSERS_PATH=D:/caches/playwright`.
- **Throttling jaringan & mode offline**: Chrome DevTools Protocol `Network.emulateNetworkConditions` (bukan simulasi) — 3G: 400 kbps turun / 400 kbps naik / 400 ms; offline: `offline=true`.
- **Pembatalan permintaan**: `context.route()` membatalkan `POST /chat` sungguhan (`net::ERR_FAILED`).
- **Zoom**: emulasi viewport CSS + `deviceScaleFactor` per context (Playwright tidak dapat menekan Ctrl+=).
- **Aksesibilitas**: `axe-core` disuntikkan dari `nexus-frontend/node_modules/axe-core/axe.min.js` ke 4 halaman.
- **User nyata**: akun Supabase sungguhan dibuat/dihapus lewat Admin API (`/auth/v1/admin/users`); dua akun berbeda untuk uji isolasi.
- **Kontrol negatif**: setiap pencarian/penolakan disertai kontrol yang HARUS berhasil (mis. cari "slack" saat mencari "shopee"; `/templates/not-a-uuid` sebagai pembanding `/workflows/not-a-uuid`).
- **MANDATORY diagnosis rule dijalankan**: bundel produksi (19 chunk, 1,38 MB) digrep lebih dulu → **0 rujukan `railway.app`**, `gateway.katalir.de5.net/katalir-api` ada. Backend `/status` = 200 (supabase + gateway 258 model + gemini 13/13 sehat).

### 2.3 Prinsip pengukuran (kenapa angka di laporan ini bisa dipercaya)

Aturan yang dipakai untuk **mencegah PASS palsu**:

- **Balasan dianggap tiba hanya bila penanda footer balasan (`→ N tok`) muncul** — bukan karena teks "berubah". Indikator "Sedang memproses…" pernah membuat skenario menilai isi balasan yang belum ada (menghasilkan `kata_bimbingan=0` palsu).
- **Bila user mengirim pesan yang TIDAK mengandung kata di prompt**, verifikasi balasan wajib memakai kata yang tidak ada di prompt (mis. minta `111+222` lalu cek `333`).
- **Teks area percakapan dibaca hanya dari `[data-testid="msg-list"]`**, tidak pernah dari `<body>` — fallback ke `<body>` pernah membuat judul sesi di sidebar terbaca sebagai "pesan tampil di layar" (PASS palsu).
- **Status HTTP 500 dari backend dianggap bug hanya bila ada kontrol pembanding yang lulus.**
- **Setiap kegagalan yang terbukti artefak lingkungan/harness WAJIB didokumentasikan sebagai artefak** — bukan ditutupi dengan menurunkan ambang, dan bukan pula dilaporkan sebagai bug produk.

---

## 3. HASIL RINGKAS

| Grup | Skenario | PASS | FAIL | NOT_RUN | Durasi |
|---|---|---|---|---|---|
| P1 Budi (tidak sabar) | 11 | 10 | 1 | 0 | 184 s |
| P2 Siti (pemula) | 10 | 9 | 1 | 0 | 164 s |
| P3 Andi (distracted) | 5 | 5 | 0 | 0 | 203 s |
| P4 Rina (jaringan lambat) | 8 | 8 | 0 | 0 | 129 s |
| P5 Dedi (kritis) | 15 | 10 | 5 | 0 | 206 s |
| J1 user baru → workflow | 4 | 3 | 1 | 0 | 95 s |
| J2 integrasi Shopee | 4 | 3 | 0 | 1 | 51 s |
| J3 isolasi multi-user | 4 | 4 | 0 | 0 | 41 s |
| B bug hunt | 12 | 10 | 1 | 1 | 179 s |
| **TOTAL** | **73** | **62** | **9** | **2** | **≈21 mnt** |

**Skor per persona (persepsi pengguna):**

- **P1 Budi (tidak sabar): 10/11** — satu-satunya kegagalan adalah refresh di tengah generasi (BUG-02). Spam tombol, spam Enter, back/forward, tombol Stop, tab kedua, dan idle semuanya bertahan.
- **P2 Siti (pemula): 9/10** — 20 dari 20 rute aplikasi nyata sehat; kegagalan tunggal adalah kualitas halaman 404 (BUG-07).
- **P3 Andi (multi-tab): 5/5** — tiga tab bersamaan, dua tab mengirim ke satu sesi, dan sinkronisasi sidebar semuanya konsisten.
- **P4 Rina (jaringan lambat): 8/8** — termasuk pemulihan offline→online tanpa reload, dan penanganan request yang diputus (kartu galat + tombol "Coba Lagi" berfungsi).
- **P5 Dedi (kritis): 10/15** — 5 kegagalan, seluruhnya terverifikasi (lihat §4).
- **Journey: 10/12** — isolasi multi-user sempurna; pendaftaran nyata gagal karena rate limit email.
- **Bug hunt: 10/12** — batas panjang, state, timing, dan UI semuanya lulus; hanya aksesibilitas `/templates` yang gagal.

---

## 4. BUG LIST (URUT SEVERITY)

**Definisi severity yang dipakai laporan ini:**

- **P0 / critical** — kehilangan data, kebocoran keamanan berdampak nyata, crash, atau alur yang tidak dapat diselesaikan sama sekali.
- **P1 / high** — alur inti rusak ATAU tidak memberi umpan balik/jalan pemulihan, mengenai semua/sebagian besar pengguna; atau kendala operasional yang memblokir peluncuran.
- **P2 / medium** — cacat berarti, masih ada jalan pintas, atau hanya terpicu input tak biasa.
- **P3 / low** — kosmetik, salah kata, ketidakonsistenan kecil.

> Catatan: kolom `severity` di `_rus_digest.json` adalah nilai awal yang ditulis saat skenario dibuat; klasifikasi di bawah adalah hasil penilaian akhir setelah semua bukti terkumpul, dan sengaja berbeda pada beberapa butir (mis. P5-02 dinaikkan ke P1, P5-12b diturunkan ke P2).

### Ringkasan tabel

| ID | Judul | Sev | Lapisan | Skenario | Bukti utama |
|---|---|---|---|---|---|
| **BUG-01** | Prompt 8.000 karakter tidak pernah dibalas (layar diam 150 s) | **P1** | Frontend | P5-02 | `_rus_repro_long.json`, `p5-02-10000-karakter.png`, `repro-long-t*.png` |
| **BUG-02** | Refresh saat generasi berjalan → chat kosong (pesan tak dipulihkan) | **P1** | Frontend | P1-01 | `_rus_repro_p1_01.json`, `repro-p101-*.png` |
| **BUG-06** | Pendaftaran user baru kena `429 email rate limit exceeded` | **P1** | Infra/Auth | J1-A2 | `j1-02c-setelah-daftar.png`, `/auth/v1/settings` |
| **BUG-03** | Null byte di prompt → kartu galat user membocorkan internal Supabase | P2 | Backend | P5-05 | `p5-05-null-byte.png`, `_rus_repro_backend.json` (C) |
| **BUG-04** | ID non-UUID → HTTP 500 + bocoran error Postgres mentah | P2 | Backend | P5-11, P5-12b | `_rus_repro_backend.json` (A), `_rus_repro_500.json` |
| **BUG-05** | Model default `gemma-4-31b-it` tidak dilayani → fallback di tiap pesan | P2 | FE+BE | P5-15 | `GET /models`, meta `/chat` |
| **BUG-07** | URL salah ketik → 404 bawaan Next.js berbahasa Inggris, tanpa jalan kembali | P2 | Frontend | P2-03b | `p2-03b-*.png` (4 rute) |
| **BUG-08** | Teks galat berbahasa Indonesia rusak: "Gagal melanjar ejekution" | P3 | Backend | inspeksi kode | `api_server.py:4419, 8070` |
| **BUG-09** | Sumber daya tidak ada → HTTP 200 + `null`/`[]`, bukan 404 | P3 | Backend | repro A | `_rus_repro_backend.json` |
| **BUG-10** | Aksesibilitas `/templates`: kontras warna (serius ×9) + urutan heading | P3 | Frontend | B-12 | `b12-axe-templates.png` |

---

## 5. DETAIL PER BUG

### BUG-01 — Prompt 8.000 karakter tidak pernah dibalas (P1 / high)

**Lapisan:** Frontend · **Skenario:** P5-02 · **Persona:** P5 Dedi

**Langkah reproduksi**
1. Masuk, buka chat baru.
2. Tempel/ketik 10.000 karakter (textarea `maxLength=8000` memotongnya menjadi tepat 8.000).
3. Tekan Enter.
4. Amati layar selama 150 detik.

**Yang diharapkan:** pesan dibalas (atau ditolak dengan pesan jelas).

**Yang terjadi:** pesan user muncul di area percakapan, lalu **tidak ada apa pun selama 150 detik**.

**Bukti terukur** (`_rus_repro_long.json`, dipantau tiap 1 detik):

```
panjang efektif di composer: 8000
  t=   1.1s  len= 8000  replies=0  busy=False  err=False
  t=  20.0s  len= 8000  replies=0  busy=False  err=False
  t=  75.0s  len= 8000  replies=0  busy=False  err=False
  t= 150.3s  len= 8000  replies=0  busy=False  err=False
HASIL: status=timeout  POST_chat=1
busy_pernah_muncul: False    error_pernah_muncul: False
console_errors: []           failed_requests: []   (hanya beacon RUM Cloudflare)
```

**Kontrol — backend TIDAK bersalah.** Payload yang sama persis dikirim langsung ke API:

| Payload | HTTP | Waktu | Model |
|---|---|---|---|
| 8.000 char, `model=gemma-4-31b-it` + `client_request_id` (seperti UI) | **200** | **8,9 s** | gemini-3.5-flash-lite (fallback) |
| 8.000 char, tanpa `model` | **200** | **7,3 s** | gemini-3.5-flash-lite |
| 8.000 char (repro B, 8.000 tepat di batas) | **200** | — | balasan normal |
| 8.001 char | **422** | — | pesan actionable: "Pesan terlalu panjang: 8.001 karakter…" |

Jadi: backend menjawab dalam ~8 detik, sementara UI tetap kosong selama 150 detik.

**Dampak:** setiap pengguna yang menempelkan dokumen panjang (kasus yang justru paling bernilai untuk produk otomasi) kehilangan pekerjaannya tanpa satu pun petunjuk. Tidak ada kartu galat, tidak ada tombol coba lagi, tidak ada indikator "sedang memproses" — satu-satunya jalan keluar adalah reload (dan reload saat generasi berjalan memicu BUG-02).

**Hipotesis akar masalah:** jalur balasan untuk prompt sangat panjang tidak menangani respons dengan benar — kandidat: pemotongan/parsing respons, atau state streaming tidak pernah di-reset karena batas panjang membuat salah satu guard (`ChatComposer.tsx:182` menyebut kasus "paste via API") menolak secara senyap. Perlu diperiksa khususnya interaksi antara `maxLength={8000}` (`ChatApp.tsx:1366`) dan validasi panjang di backend (`CHAT_MAX_CHARS = 8000`, `api_server.py:706`) — nilai yang persis sama di kedua sisi adalah kombinasi paling rawan.

**Reproduksibilitas:** 3/3 (dua kali di skenario P5-02 + satu probe khusus 150 detik).

---

### BUG-02 — Refresh saat generasi berjalan melempar user ke chat kosong (P1 / high)

**Lapisan:** Frontend · **Skenario:** P1-01 · **Persona:** P1 Budi (tidak sabar)

**Langkah reproduksi**
1. Masuk, buka chat baru.
2. Kirim prompt `buat workflow inventory sederhana`, tekan Enter.
3. Tunggu 3 detik (Budi menekan F5 karena merasa lambat).
4. Tekan F5.
5. Amati area percakapan dan sidebar.

**Yang diharapkan:** pesan tetap terlihat (terkirim, atau minimal tersimpan dan dipulihkan).

**Yang terjadi:** area percakapan **kosong** (`len=0`), pesan tidak ditampilkan, **tanpa pesan galat apa pun**. Namun judul sesi **muncul di sidebar**.

**Bukti** (`_rus_repro_p1_01.json`):

```
setelah_refresh: url=https://katalir.de5.net/chat
                 panjang_area_chat=0     marker_di_chat=false
                 marker_di_sidebar=true  sidebar_n=60
                 judul_teratas=["Chat Baru", "REPRO-P101-460323 buat workflo...", ...]
VERDICT: B: pesan tersimpan di server (terlihat di sidebar), tetapi area
         percakapan tetap kosong setelah refresh
```

**Ini BUKAN kehilangan data** — pesannya ada di server dan sesinya ada di sidebar. Yang rusak adalah **pemulihan sesi aktif**: aplikasi membiarkan user di chat kosong alih-alih kembali ke percakapan yang sedang berjalan, dan tidak memberi tahu bahwa percakapan itu masih ada.

**Dampak:** ini tepat perilaku persona "tidak sabar". Persepsi user = "pesanku hilang". Setiap refresh di tengah generasi memicu kejadian ini, dan kepercayaan pada produk runtuh lebih cepat daripada bug fungsional biasa.

**Bukti pembanding yang penting:** refresh **setelah** balasan selesai berhasil memulihkan semuanya (P1-01b PASS: `pesan_masih_ada=True; panjang=407`). Jadi yang gagal spesifik adalah pemulihan pada keadaan "generasi belum selesai".

**Hipotesis akar masalah:** saat generasi belum selesai, UI belum mengikat URL ke id sesi (`/chat` tanpa penanda sesi), sehingga setelah reload aplikasi membuka sesi baru yang kosong. Perbaikan yang disarankan: tulis id sesi ke URL/`localStorage` **saat permintaan dikirim**, bukan saat balasan selesai.

**Catatan metodologis (penting untuk dipercaya):** temuan ini sempat **salah dinyatakan aman** oleh versi pertama skrip repro, karena skrip itu membaca teks dari seluruh `<body>` — dan judul sesi di sidebar memuat penanda, sehingga "pesan tampil di layar" terbaca `True`. Setelah pembacaan dibatasi ke `[data-testid="msg-list"]`, hasilnya berbalik menjadi jelas. Pelajaran ini sudah dibakukan menjadi helper `msglist_text()`.

**Reproduksibilitas:** 3/3 skenario + 2/2 probe terarah.

---

### BUG-06 — Pendaftaran user baru tidak dapat diandalkan (P1 / high)

**Lapisan:** Infrastruktur / Auth · **Skenario:** J1-A2 · **Journey:** user baru → workflow pertama

**Langkah reproduksi**
1. Buka landing tanpa sesi → klik CTA masuk → modal autentikasi terbuka (Google, GitHub, email+sandi).
2. Klik tombol alih-mode ke **daftar** (`login-toggle-mode`).
3. Isi email + sandi baru → klik daftar.

**Yang terjadi:** `email rate limit exceeded` (dan untuk domain uji internal: `Email address "…@katalir-internal.dev" is invalid`).

**Bukti** — probe langsung ke endpoint pendaftaran publik Supabase:

| Domain email | HTTP | Pesan |
|---|---|---|
| `katalir-internal.dev` | 400 | `Email address "…" is invalid` |
| `example.com` | **429** | `email rate limit exceeded` |
| `gmail.com` | **429** | `email rate limit exceeded` |
| `mailinator.com` | **429** | `email rate limit exceeded` |

Konfigurasi auth (`GET /auth/v1/settings`):

```
mailer_autoconfirm : False      <-- konfirmasi email WAJIB
disable_signup     : False      <-- pendaftaran terbuka
enabled providers  : ['github', 'google', 'email']
custom SMTP        : tidak ada
```

**Dampak:** konfirmasi email wajib **dan** pengirim email bawaan Supabase dibatasi sangat ketat. Akibatnya, setelah beberapa pendaftaran dalam satu jendela waktu, pengguna baru menerima **429** dan tidak dapat membuat akun sama sekali. Untuk produk yang sedang tumbuh, ini memblokir akuisisi pengguna — bukan cacat kosmetik.

**Catatan kejujuran:** batas ini terpicu sebagian karena pengujian saya sendiri (5 percobaan pendaftaran dalam beberapa menit). Namun mekanismenya nyata dan pasti terpicu oleh basis pengguna sungguhan. **Perlu diverifikasi** terhadap batas yang benar-benar dikonfigurasi di proyek (nilai bawaan SMTP Supabase berada pada orde beberapa email per jam).

**Rekomendasi:** konfigurasi SMTP kustom (mis. Resend/Postmark/SES) dan naikkan batas; atau pertimbangkan `mailer_autoconfirm=true` untuk peluncuran awal dengan konsekuensi trade-off keamanan yang disadari.

**Catatan positif:** jalur masuk lewat Google/GitHub tidak terpengaruh, sehingga pengguna masih bisa masuk — yang gagal adalah jalur email+sandi. Modal juga menampilkan pesan galat dengan benar (`login-error`), jadi user tahu apa yang terjadi.

---

### BUG-03 — Null byte di prompt membocorkan internal Supabase ke kartu galat user (P2 / medium)

**Lapisan:** Backend · **Skenario:** P5-05 · **Persona:** P5 Dedi

**Langkah reproduksi**
1. Masuk, buka chat baru.
2. Kirim prompt yang mengandung null byte: `test\x00injection`.
3. Amati kartu galat.

**Yang terjadi — teks yang benar-benar dilihat user:**

```
test\x00injection
Gagal mengirim
Supabase error saat chat_sessions.insert [22P05]: {'message': 'unsupported Unicode
escape sequence', 'code': '22P05', 'hint': None, 'details': '\\u0000 cannot be
converted to text.'}.
Coba Lagi
```

**Yang bocor:** nama tabel + operasi (`chat_sessions.insert`), kode SQLSTATE (`22P05`), nama driver, dan struktur internal (`hint`/`details`). Nama penyedia penyimpanan juga ikut terekspos.

**Bukti API (kontrol)** — `POST /chat {"prompt": "tes\x00injection"}` → **HTTP 503** dengan muatan yang sama. Status 503 ("layanan tidak tersedia") juga **salah kelas**: ini masalah input klien, seharusnya 4xx. Status 503 mengundang klien melakukan percobaan ulang otomatis untuk kesalahan yang tidak akan pernah berhasil.

**Dampak:** pengungkapan informasi internal ke pengguna akhir; pesan tidak dapat ditindaklanjuti oleh user; potensi percobaan ulang berulang.

**Hipotesis akar masalah:** prompt diteruskan ke `chat_sessions.insert` tanpa membersihkan `\x00` (Postgres menolaknya pada kolom `text`), lalu string pengecualian diinterpolasi ke dalam respons.

**Reproduksibilitas:** 3/3 (API 503, kartu galat UI, dan repro terarah C).

---

### BUG-04 — ID non-UUID → HTTP 500 + bocoran error Postgres mentah (P2 / medium)

**Lapisan:** Backend · **Skenario:** P5-11, P5-12b

**Langkah reproduksi**
1. Masuk dengan token apa pun yang valid.
2. `GET /workflows/not-a-uuid` (atau PATCH/DELETE).

**Yang terjadi:**

```json
{"detail":"Gagal memuat workflow: {'message': 'invalid input syntax for type uuid:
 \"not-a-uuid\"', 'code': '22P02', ...}"}
```

**Bukti terkontrol** (`_rus_repro_backend.json` A — 15 endpoint diuji, termasuk kontrol):

| Kelompok | 5xx | Bocor error internal |
|---|---|---|
| **Target** (`/workflows/{id}` GET·PATCH·DELETE, `/workflows/1`, `/workflows/%20`) | **5/12** | **5/12** |
| **Kontrol** (`/templates/{id}`, `/evidence/{id}/verify`, UUID valid milik orang lain) | **0/3** | 0/3 |

**Temuan penting:** cacat ini **terlokalisasi**, bukan pola menyeluruh. Endpoint bersaudara sudah benar:

| Endpoint | Hasil | Benar? |
|---|---|---|
| `/workflows/not-a-uuid/schedule` | 404 "Workflow tidak ditemukan." | ya |
| `/workflows/not-a-uuid/redaction` | 404 | ya |
| `/agents/not-a-uuid` | 404 "agent tidak ditemukan" | ya |
| `/hitl/not-a-uuid` | 404 | ya |
| `/evaluations/runs/not-a-uuid` | 404 | ya |
| `/templates/not-a-uuid` | 404 | ya |
| **`/workflows/not-a-uuid`** | **500 + bocoran** | **tidak** |

**Akar masalah teridentifikasi tepat:** lima handler workflow (`api_server.py:4019, 4032, 4165` → `raise` di `3994, 4015, 4026, 4046, 4172`) tidak memiliki penjaga tipe (`db.is_uuid` sudah tersedia dan dipakai di tempat lain, mis. `api_server.py:2495`), lalu menangkap semuanya dengan `except Exception → HTTPException(500, f"...{exc}")`.

**Skala laten:** pola `HTTPException(500, f"...{exc}")` muncul di **35 tempat** di `api_server.py`. Setiap tempat yang menerima parameter path adalah kandidat bug kelas yang sama.

**Catatan penting tentang penangan galat global:** commit `b4c5690` menambahkan `@app.exception_handler` global untuk 500 yang kosong. Handler itu **tidak menolong di sini**, karena ke-35 tempat tersebut menaikkan `HTTPException` secara sengaja — handler global hanya berlaku untuk pengecualian tak tertangani. Jadi perbaikan harus di tingkat handler, bukan di handler global.

**Perbaikan yang disarankan:** validasi `db.is_uuid(id)` di awal tiap handler → 404, dan hentikan interpolasi `{exc}` ke `detail` (catat ke log server, kirim pesan generik + id korelasi ke klien).

---

### BUG-05 — Model default `gemma-4-31b-it` tidak dapat dilayani (P2 / medium)

**Lapisan:** Frontend + Backend · **Skenario:** P5-15

**Langkah reproduksi**
1. Masuk sebagai akun gratis, jangan mengubah pilihan model (jadi memakai default).
2. Kirim pesan apa pun.

**Yang terjadi:** setiap pesan memunculkan spanduk:

> **Model yang Anda pilih tidak tersedia** — Model ini sedang tidak bisa dipakai. Silakan coba lagi sebentar atau pilih model lain. · Beralih ke gemini-3.5-flash-lite · diminta: gemma-4-31b-it

Sementara itu panel kuota tetap berlabel **"Gemma 4 (default)"**.

**Bukti** — meta respons `POST /chat` dengan `model=gemma-4-31b-it`:

```
HTTP 200
fallback        = True
requested_model = gemma-4-31b-it
model           = gemini-3.5-flash-lite
fallback_reason = model_unavailable
quota_bucket    = gemma          <-- kuota "gemma" terpakai oleh model lain
```

**Bukti akar masalah** — katalog model dari server sendiri (`GET /models`, tier free, 13 model):

```json
{"id": "google/gemma-4-31b-it", "name": "Gemma 4 31B It",
 "provider": "Gateway · nvidia", "tier": "free", "hint": "1484ms", "locked": false}
default server: "gemini-3.5-flash-lite"
```

Sedangkan frontend menuliskan id **tanpa awalan penyedia**:

```ts
// nexus-frontend/src/lib/models.ts:24
export const DEFAULT_MODEL_ID = "gemma-4-31b-it";
// dipakai di nexus-frontend/src/app/chat/ChatApp.tsx:237
const [selectedModel, setSelectedModel] = useState<string>(DEFAULT_MODEL_ID);
```

Model itu **hidup** (terdaftar, `locked:false`, `hint:1484ms`) tetapi id yang dikirim frontend tidak dapat diresolusi → `model_unavailable`.

**Dampak:** **100% pengguna gratis** melihat spanduk "model tidak tersedia" pada **setiap** pesan — kesan pertama yang buruk dan merusak kepercayaan. Ditambah lagi, kuota dibebankan ke ember `gemma` padahal yang menjawab `gemini-3.5-flash-lite`, sehingga angka kuota yang ditampilkan ke pengguna menyesatkan.

**Catatan:** `gateway_roster.py:145` memasukkan `"gemma-4-31b-it"` ke `FREE_TIER_MODEL_IDS`, dan komentar di `gateway_roster.py:426–429` sudah mencatat persis kelas masalah ini (perbedaan id berawalan penyedia vs tanpa awalan). Ini tampaknya regresi yang belum tertutup.

**Perbaikan yang disarankan:** frontend membaca katalog dari `GET /models` dan memakai id yang dikembalikan server (bukan konstanta hardcode); atau backend menormalkan alias tanpa awalan. Tambahkan uji yang memastikan `DEFAULT_MODEL_ID` benar-benar ada di katalog.

---

### BUG-07 — URL salah ketik: 404 bawaan Next.js berbahasa Inggris tanpa jalan kembali (P2 / medium)

**Lapisan:** Frontend · **Skenario:** P2-03b · **Persona:** P2 Siti (pemula)

**Langkah reproduksi**
1. Masuk, lalu buka `/vault` (atau `/dashboard`, `/workflows`, `/orders`).

**Yang terjadi:** halaman 404 dengan **33 karakter**, tanpa navigasi, tanpa bahasa Indonesia, tanpa jalan kembali:

| Rute | HTTP | Panjang teks | Penanda 404 | Bahasa Indonesia | Jalan kembali |
|---|---|---|---|---|---|
| `/vault` | 404 | 33 | ya | **tidak** | **0** |
| `/dashboard` | 404 | 33 | ya | **tidak** | **0** |
| `/workflows` | 404 | 33 | ya | **tidak** | **0** |
| `/orders` | 404 | 33 | ya | **tidak** | **0** |

**Akar masalah terkonfirmasi di kode:** direktori `nexus-frontend/src/app/` **tidak memiliki `not-found.tsx`**, sehingga Next.js mengekspor halaman bawaannya ke `out/404.html` (judul: `404: This page could not be found.`).

**Dampak:** persona pemula yang salah mengetik (atau mengikuti tautan lama) langsung terlempar keluar dari aplikasi ke halaman Inggris tanpa jalan pulang — dead end yang hanya bisa dilewati dengan mengedit URL manual.

**Catatan penting:** ini berlaku untuk URL yang tidak dikenal. Rute aplikasi yang **ada** semuanya sehat — **20/20 rute nyata** (dari `src/app/**/page.tsx`) dimuat dengan benar tanpa layar kosong (P2-03 PASS). Jadi masalahnya murni pada halaman 404, bukan pada perutean.

**Perbaikan:** tambahkan `src/app/not-found.tsx` berbahasa Indonesia dengan tautan kembali ke Chat/Beranda.

---

### BUG-08 — Teks galat berbahasa Indonesia rusak (P3 / low)

**Lapisan:** Backend · Ditemukan lewat inspeksi kode (bukan skenario).

```python
# api_server.py:4419
raise HTTPException(500, f"Gagal melanjar ejekution: {exc}")
# api_server.py:8070
raise HTTPException(500, f"Gagal memuat ejekution: {exc}")
```

`"melanjar ejekution"` bukan bahasa Indonesia (seharusnya kira-kira "melancarkan eksekusi"), dan `"ejekution"` adalah campuran Inggris-Indonesia yang tidak konsisten dengan istilah "eksekusi" yang dipakai di tempat lain. Muncul ke user bila endpoint tersebut gagal.

**Perbaikan:** perbaiki kedua string; sekaligus jadikan pesan galat 500 generik (lihat BUG-04).

---

### BUG-09 — Sumber daya tidak ada mengembalikan HTTP 200 + `null`/`[]` (P3 / low)

**Lapisan:** Backend · Bukti: `_rus_repro_backend.json` (A).

| Endpoint | Seharusnya | Kenyataan |
|---|---|---|
| `GET /executions/not-a-uuid` | 404 | **200** `{"status":"success","execution":null,"logs":[],…}` |
| `GET /messages/not-a-uuid` | 404 | **200** `{"status":"success","messages":[]}` |

Tidak ada kebocoran dan tidak ada crash (jadi lebih baik daripada BUG-04), tetapi `200 + null` membuat klien tidak dapat membedakan "tidak ada" dari "ada tapi kosong", dan menyembunyikan kesalahan pemanggilan dari pemantauan.

**Perbaikan:** kembalikan 404 untuk id yang tidak ada; simpan `200 + []` hanya untuk daftar yang sah namun kosong.

---

### BUG-10 — Aksesibilitas `/templates` (P3 / low)

**Lapisan:** Frontend · **Skenario:** B-12 (axe-core, 4 halaman)

| Halaman | Pelanggaran serius/kritis |
|---|---|
| `/chat` | 0 |
| `/builder` | 0 |
| `/settings` | 0 |
| **`/templates`** | **2** — `color-contrast` (**serious**, 9 node), `heading-order` (moderate, 1 node) |

Tiga dari empat halaman bersih. Sembilan node dengan kontras warna di bawah ambang adalah masalah nyata bagi pengguna low-vision. `heading-order` yang melompat menyulitkan navigasi pembaca layar.

**Perbaikan:** naikkan kontras teks di `/templates` ke rasio ≥4.5:1 dan rapikan hierarki heading.

---

## 6. ARTEFAK HARNESS YANG DIKOREKSI (dan mengapa ini penting)

Selama pengujian, **7 temuan awal ternyata cacat pada alat ukur, bukan pada produk.** Semuanya diperbaiki, dan **tidak satu pun** ditutupi dengan menurunkan ambang penilaian. Daftar ini disertakan karena laporan bug-hunt yang tidak mencatat kesalahan alatnya sendiri tidak dapat dipercaya.

| Temuan awal | Tampak seperti | Ternyata | Akar masalah alat ukur |
|---|---|---|---|
| **P4-05 / P4-06** "permintaan API diputus → UI macet di 'Sedang memproses…' tanpa kartu galat" | bug high (hang senyap) | **bukan bug** — kartu galat muncul dan tombol "Coba Lagi" **berhasil** (`berhasil_setelah_retry=True`) | `send_measured` menilai "sudah dibalas" hanya dari perubahan teks, lalu keluar sebelum kartu galat sempat muncul |
| **P5-14** "spam 12 pesan → pesan hilang senyap" | bug medium (kehilangan data) | **bukan bug** — aplikasi punya **antrean FIFO** (`queue-area` terlihat) | Pemeriksaan memakai `queued-msg` (area terlipat) dan kata kunci "sibuk"/"antrean", melewatkan indikator "Agen sedang berpikir…" |
| **P2-01** "wizard onboarding tidak muncul" | bug medium | **bukan bug** — wizard **sengaja** disembunyikan untuk user yang sudah punya riwayat chat (`OnboardingFlow.tsx:70`) | Skenario memakai akun uji yang sudah pernah mengobrol; diperbaiki dengan user sementara khusus (dibuat & dihapus otomatis) |
| **P2-02** "balasan tidak membimbing" (`kata_bimbingan=0`) | bug medium | **bukan bug** — balasan belum tiba saat dinilai | `send_measured` keluar terlalu cepat (lihat baris P4-05) |
| **P5-02** (versi pertama) | bug medium | **BUG NYATA** — dipertahankan & dinaikkan ke P1 setelah probe 150 detik | Batas tunggu terlalu pendek; setelah diperbaiki, bug-nya makin jelas |
| **B-07** "zoom 150% mendorong composer keluar layar" | bug medium | **bukan bug** — composer tetap di dalam layar | Zoom disimulasikan dengan `style.zoom` (tidak setara zoom browser); diganti emulasi viewport + `deviceScaleFactor` |
| **B-02** "batas 8.001 karakter lulus" | PASS | **PASS PALSU** — permintaan memakai field `message`, padahal API memakai `prompt` | 422 yang muncul adalah "Field required", bukan validasi panjang; diperbaiki → sekarang menguji 8.001 char dan memverifikasi pesan menyebut batas |
| **J3-D** "identitas antar-tab tidak terverifikasi" | FAIL | **bukan bug** — isolasi bersih | Sesi ditanamkan pada `about:blank` (localStorage origin opaque → gagal senyap); setelah navigasi ke origin lebih dulu → `sesi_A=True; sesi_B=True; A_lihat_email_B=False` |
| **J1-A** "pendaftaran wajib consent Google (BLOCKED)" | blocked | **premis salah** — CTA membuka modal dengan Google/GitHub/**email+sandi** | Skenario hanya menunggu popup OAuth |
| **J1-B** (versi pertama) "workflow tidak terbangun" | bug high | **bukan bug** — workflow terbentuk (2–5 node) dan aplikasi **meminta kredensial Telegram** lebih dulu (perilaku benar) | Kriteria lulus menuntut node tanpa memperhitungkan gerbang kredensial |
| **P1-01** (skrip repro versi pertama) | "pesan hilang" | **tetap bug, tapi alasannya berbeda** | Skrip membaca seluruh `<body>`; judul di sidebar memuat penanda → "tampil di layar" terbaca `True` (PASS palsu) |

**Dampak koreksi ini pada angka akhir:** dua "bug high" (P4-05, J1-B) dan tiga "bug medium" (P5-14, P2-01, P2-02) yang tadinya akan dilaporkan sebagai cacat produk **dihapus** dari daftar bug, sementara satu PASS palsu (B-02) diubah menjadi uji yang benar-benar menguji.

---

## 7. YANG TERBUKTI BAIK (jangan diubah tanpa alasan)

Uji ini tidak hanya mencari cacat. Berikut yang bertahan terhadap tekanan dan layak dipertahankan:

**Keamanan & isolasi data**
- **Isolasi multi-user bersih di tiga lapis**: user B tidak melihat workflow user A (`kebocoran=False`); akses langsung lintas-user ke `/workflows/{id}` → **404**; dan di tingkat sesi browser, tiap tab memakai token miliknya sendiri tanpa satu pun email bocor ke tab lain (J3: 4/4 PASS).
- **Ketahanan input berbahaya**: SQL injection, skrip XSS, HTML mentah, teks RTL, payload 2 MB, JSON rusak, dan prompt injection — **semuanya ditangani** tanpa eksekusi skrip, tanpa `alert()`, tanpa layar rusak. Prompt injection **ditolak** dan tidak membocorkan system prompt.
- **Validasi autentikasi & batas**: `POST /chat` tanpa token → **401** dengan pesan jelas; 8.001 karakter → **422** dengan pesan yang menyebut angka batas dan berapa karakter harus dipotong; 2 MB → 422; JSON rusak → 422.

**Ketahanan UI**
- **Antrean FIFO** menangani burst 12 pesan tanpa kehilangan satu pun, dengan area antrean yang terlihat.
- **Pemulihan jaringan**: setelah offline lalu online, aplikasi pulih **tanpa reload**; permintaan yang diputus memunculkan kartu galat + tombol "Coba Lagi" yang benar-benar berfungsi.
- **State & navigasi**: back 5× lalu forward 2× tidak menghasilkan halaman rusak; tutup tab lalu buka lagi aman; 3 tab bersamaan konsisten; dua tab mengirim ke satu sesi tidak saling menimpa; idle 90 detik tidak memaksa login ulang.
- **Ketahanan tata letak**: zoom 75%/100%/150%, font root 24 px, rotasi ponsel portrait↔landscape — **tidak ada overflow horizontal**, composer tetap di dalam layar.
- **Batas input di UI**: counter karakter muncul tepat saat mendekati batas, dan pemotongan di 8.000 bekerja konsisten (0/1/7.999/8.000/8.001 → 0/1/7.999/8.000/8.000).
- **Konsistensi bahasa**: tidak ada halaman yang mencampur Indonesia dan Inggris (P2-06), dan 29 tombol ikon semuanya punya label aksesibel (P2-07: `tanpa_label=0`).
- **Performa**: landing siap dalam ~0,5–0,9 s (FCP 764–876 ms, DCL ~1,0 s); `/chat` di 3G termuat tanpa skeleton yang menggantung; latensi API buatan 2 detik tidak membuat UI berputar tanpa henti.

---

## 8. VERDICT

### **CONDITIONAL — SIAP LAUNCH DENGAN SYARAT**

Penerapan aturan dari brief secara eksplisit:

| Kriteria | Ambang | Hasil | Lulus? |
|---|---|---|---|
| **critical (P0)** | harus 0 | **0** | ya |
| **high (P1)** | ≤ 3 | **3** (BUG-01, BUG-02, BUG-06) | ya |
| **medium (P2)** | — | 4 (BUG-03, BUG-04, BUG-05, BUG-07) | — |
| **low (P3)** | — | 3 (BUG-08, BUG-09, BUG-10) | — |

**Verdict = CONDITIONAL**, karena 0 critical dan tepat **3 high** (batas atas untuk kategori ini).

### Peringatan kejujuran tentang ambang batas

Jumlah high **tepat berada di ambang**. Jika tim menilai salah satu dari berikut sebagai high, verdict otomatis berubah menjadi **BELUM SIAP LAUNCH**:

- **BUG-03** (null byte → kartu galat user membocorkan `chat_sessions.insert` + SQLSTATE `22P05`) dan **BUG-04** (non-UUID → HTTP 500 + error Postgres mentah) — keduanya saya nilai **medium** karena memerlukan input yang dirancang khusus dan kebocorannya tidak memuat kredensial; namun keduanya adalah **pengungkapan informasi internal** dan **kode status HTTP yang salah**. Karena alasan itu, keduanya saya masukkan ke daftar **wajib perbaiki sebelum launch** meskipun bukan high.
- **BUG-05** (model default fallback di setiap pesan) saya nilai **medium** karena alur tetap selesai (jawaban tetap datang); tetapi dampaknya **universal** — setiap pengguna gratis, setiap pesan.

### Yang WAJIB diperbaiki sebelum launch

1. **BUG-01** — prompt 8.000 karakter: alur inti rusak, tanpa umpan balik, tanpa pemulihan.
2. **BUG-02** — refresh di tengah generasi: persepsi kehilangan data pada alur inti.
3. **BUG-06** — pendaftaran email: memblokir akuisisi pengguna baru.
4. **BUG-03 + BUG-04** — hentikan kebocoran pesan internal DB (dan perbaiki kode status). Terapkan penjaga `db.is_uuid` + pesan galat generik; pola `f"...{exc}"` masih ada di **35 tempat**.
5. **BUG-05** — samakan id model default dengan katalog server.
6. **BUG-07** — tambahkan halaman 404 sendiri.

**Setelah enam perbaikan itu, verdict dapat dinaikkan menjadi SIAP LAUNCH** (0 critical, 0 high), dengan BUG-08/09/10 sebagai pekerjaan lanjutan.

---

## 9. REKOMENDASI TEKNIS

| Prioritas | Tindakan | Berkas / lokasi |
|---|---|---|
| 1 | Telusuri jalur respons untuk prompt panjang; pastikan `maxLength` UI dan `CHAT_MAX_CHARS` backend tidak menciptakan kasus batas senyap. Tambahkan uji regresi: prompt 8.000 char **harus** mendapat balasan | `ChatApp.tsx:1366`, `ChatComposer.tsx:182`, `api_server.py:706` |
| 2 | Tulis id sesi ke URL/`localStorage` **saat permintaan dikirim**; pulihkan sesi itu setelah reload | `ChatApp.tsx` |
| 3 | Konfigurasi SMTP kustom & naikkan batas email; tinjau `mailer_autoconfirm` | Konfigurasi Supabase |
| 4 | Tambahkan penjaga `db.is_uuid` di kelima handler workflow; ganti `HTTPException(500, f"...{exc}")` menjadi pesan generik + id korelasi; audit 35 lokasi lain | `api_server.py:3994–4194`, `4165` |
| 5 | Bersihkan/validasi `\x00` sebelum insert; kembalikan 4xx, bukan 503 | `api_server.py` (jalur `/chat`) |
| 6 | Frontend membaca katalog dari `GET /models` alih-alih konstanta hardcode; tambahkan uji konsistensi `DEFAULT_MODEL_ID ∈ katalog` | `models.ts:24`, `ChatApp.tsx:237` |
| 7 | Tambahkan `src/app/not-found.tsx` (Indonesia, ada tautan kembali) | `nexus-frontend/src/app/` |
| 8 | Perbaiki string `"melanjar ejekution"` / `"memuat ejekution"` | `api_server.py:4419, 8070` |
| 9 | Kembalikan 404 (bukan 200 + `null`) untuk id yang tidak ada | `/executions/{id}`, `/messages/{id}` |
| 10 | Perbaiki kontras warna & urutan heading di `/templates` | `src/app/templates/` |
| 11 | (Fitur) Fitur lampiran berkas belum ada di `/chat` — tidak ada `input[type=file]`, sehingga uji unggah berkas tidak dapat dijalankan | — |

---

## 10. INDEKS BUKTI

**Direktori:** `docs/evidence/real-user-2026-10-13/` — **113 berkas, 30 MB**

| Kategori | Jumlah | Contoh |
|---|---|---|
| Screenshot (PNG) | **106** | `p1-01a-sebelum-refresh.png`, `p2-03b-vault.png`, `p4-05-request-diabort.png`, `p5-05-null-byte.png`, `p5-13-spam-kuota.png`, `b12-axe-templates.png`, `j1-02c-setelah-daftar.png`, `j3-01-userA.png` |
| Video (webm) | **6** | `video/*.webm` (perjalanan J1 lengkap + sesi P1/P3) — **4,4 MB** |
| Network log (jsonl) | **1** | `logs/j1-network.jsonl` |
| Screenshot probe khusus | 7 | `repro-long-t5s.png`, `repro-long-t20s.png`, `repro-long-t45s.png`, `repro-long-akhir.png`, `repro-p101-01..03` |

> **Catatan tentang video:** berkas `.webm` **tidak di-commit** karena `.gitignore:123` proyek ini mengabaikan seluruh pola `*.webm` (aturan yang sengaja dipertahankan agar media besar tidak masuk repositori). Videonya tetap tersimpan di `docs/evidence/real-user-2026-10-13/video/` pada mesin pengujian dan dapat dilampirkan terpisah bila diperlukan. Seluruh bukti visual lain (106 PNG) **ikut ter-commit**.

**Data mesin (JSON):**

| Berkas | Isi |
|---|---|
| `tests/user_test/_rus_digest.json` / `.md` | agregat 73 skenario + 9 masalah, urut severity |
| `tests/user_test/_rus_p1..p5, j1..j3, bug.json` | hasil per grup (termasuk console error, request gagal, screenshot) |
| `tests/user_test/_rus_repro_backend.json` | 15 endpoint ID non-UUID + batas 8.000/8.001 + null byte |
| `tests/user_test/_rus_repro_long.json` | timeline 150 detik prompt 8.000 karakter |
| `tests/user_test/_rus_repro_p1_01.json` | pembeda "data hilang" vs "UI tidak memulihkan" |
| `tests/user_test/_rus_repro_500.json` | sapuan awal ID non-UUID |
| `_rus_final3.log` | log lengkap run final (21 menit) |

**Harness (dapat dijalankan ulang):**

```bash
cd /c/Users/user/Proyek_AI
PY=C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe
$PY tests/user_test/rus_newuser.py            # buat akun uji baru
$PY -u tests/user_test/rus_run.py all          # 73 skenario, ~21 menit
$PY tests/user_test/rus_report.py              # agregasi -> digest
$PY tests/user_test/rus_repro_backend.py       # repro backend (A/B/C)
$PY tests/user_test/rus_repro_long.py          # repro prompt 8.000 char
$PY tests/user_test/rus_repro_p1_01.py         # repro refresh di tengah generasi
$PY tests/user_test/rus_cleanup.py             # hapus akun uji
```

---

## 11. CATATAN PENUTUP

- **Semua bukti diambil dari sistem produksi**, bukan lingkungan lokal: frontend `katalir.de5.net` (Cloudflare Pages) dan backend VPS melalui gateway `gateway.katalir.de5.net`.
- **Diverifikasi lebih dulu sesuai aturan diagnosis**: bundel JS produksi (19 chunk, 1,38 MB) **tidak** mengandung rujukan `railway.app`, dan backend melaporkan `/status` sehat (supabase OK, gateway 258 model, gemini 13/13). Jadi temuan di laporan ini bukan gejala artefak deploy yang basi.
- **Keterbatasan yang diakui**: (a) batas rate limit email diverifikasi terhadap perilaku sistem, bukan terhadap angka konfigurasi proyek — perlu konfirmasi tim infra; (b) zoom browser disimulasikan lewat viewport + `deviceScaleFactor`, bukan Ctrl+= sungguhan; (c) dua skenario berstatus NOT_RUN karena prasyaratnya memang tidak ada di produk — J2-C (tidak ada form kredensial di halaman detail integrasi) dan B-11 (tidak ada fitur lampiran berkas di `/chat`); keduanya dilaporkan apa adanya, bukan dihitung sebagai lulus.
- **Tidak ada bug yang ditutupi dengan menurunkan ambang.** Sebaliknya, satu PASS palsu (B-02) ditemukan dan diperbaiki, dan tujuh temuan awal dibatalkan setelah terbukti artefak alat ukur (§6).
