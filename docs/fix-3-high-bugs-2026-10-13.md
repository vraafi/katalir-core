# KATALIR — FIX 3 BUG HIGH (13 Oktober 2026)

**Mode:** SKILL-FIRST + SEARCH-FIRST + OTONOM + EVIDENCE-ONLY
**Target:** 3 bug high dari hard test 13 Okt (`docs/real-user-hard-test-2026-10-13.md`)
**Verdict awal:** CONDITIONAL (0 critical · 3 high) → lihat §6 untuk verdict setelah perbaikan

---

## 1. EXECUTIVE SUMMARY

| Bug | Status | Lapisan | Bukti red→green |
|---|---|---|---|
| **BUG-01** prompt 8.000 karakter: balasan tidak pernah terlihat | **FIXED** (terverifikasi lokal) | Frontend (auto-scroll) | `_diag_bug01_8000.json`, `_verify_fixes.json` |
| **BUG-02** refresh saat AI bekerja → chat kosong | **FIXED** (terverifikasi lokal) | Frontend (pemulihan sesi) | `_rus_repro_p1_01.json`, `_verify_fixes.json` |
| **BUG-06** pendaftaran email `429 email rate limit exceeded` | **SEBAGIAN** — lapisan aplikasi diperbaiki; akar infra **BLOCKED** (butuh `SUPABASE_ACCESS_TOKEN`) | Frontend + Supabase config | `_verify_fixes.json`, `j1-02c-setelah-daftar.png` |

**Poin terpenting yang mengubah kesimpulan laporan sebelumnya:** BUG-01 **bukan** "balasan tidak pernah datang". Instrumentasi membuktikan balasan **datang dan tersimpan** (HTTP 200, `reply_len` 130–169, tertulis di cache TanStack), tetapi **berada di luar layar** karena wadah gulir berhenti di `scrollTop=0` sementara bubble prompt setinggi ~2.900 px. Yang rusak adalah **gulir otomatis**, bukan pengiriman/penyimpanan balasan.

---

## 2. SKILL YANG DIMUAT (WAJIB — FASE 1)

Di-clone ke `D:/caches/october-2026-skills` (di luar repo supaya tidak mengotori proyek; isinya hanya untuk dibaca).

| # | Skill | Pattern utama | Dipakai untuk |
|---|---|---|---|
| 1 | `agentic-pro-skills/skills/root-cause-debug` | Reproduce → hipotesis falsifiable → eksperimen terkecil → regression check yang GAGAL sebelum fix | Semua bug |
| 2 | `agentic-pro-skills/skills/proof-first-testing` | Red-green: test harus gagal karena perilakunya, bukan karena setup | Verifikasi |
| 3 | `superpowers/skills/systematic-debugging` | **Iron Law: NO FIXES WITHOUT ROOT CAUSE FIRST**; 4 fase; instrumentasi di batas komponen | BUG-01, BUG-02 |
| 4 | `superpowers/skills/verification-before-completion` | Bukti sebelum klaim; siklus red-green harus diverifikasi | Semua klaim di laporan ini |
| 5 | `anthropics/skills/skills/webapp-testing` | Playwright + screenshot + console log; recon-then-action | BUG-01, BUG-02, regression |
| 6 | `supabase/agent-skills/skills/supabase` | Auth troubleshooting; "verify against current docs, jangan andalkan training data" | BUG-06 |

**Cara skill #3 mengubah jalannya pekerjaan:** fase 1.4 menuntut instrumentasi di **setiap batas komponen** sebelum mengusulkan fix. Itulah yang mengungkap bahwa respons sudah diterima (`requestfinished`), balasan sudah ada di cache, dan yang gagal hanyalah gulir. Tanpa langkah itu saya akan "memperbaiki" parser/retry yang sebenarnya sehat.

**Cara skill #4 mencegah klaim palsu:** dua hipotesis awal saya **salah** dan dibatalkan justru karena verifikasi menuntut bukti:
- *Hipotesis A (dedup order di `overlay`)*: saya sempat mengubah urutan `[...pendingCache, ...cached]` → `[...cached, ...pendingCache]`. Dump cache membuktikan `__pending__` **kosong** dan balasan sudah ada di `messages(sid)`, jadi hipotesis ini gugur. **Perubahan itu saya revert** (lihat §3.4) — bukan band-aid yang dibiarkan menempel.
- *Hipotesis B (`context` undefined di `onSuccess`)*: gugur karena cache justru berisi balasan lengkap + meta.

---

## 3. BUG-01 — Prompt 8.000 karakter: balasan tidak pernah terlihat

### 3.1 Reproduksi (skill #1 langkah 1)
Kirim tepat 8.000 karakter (batas `maxLength` UI) → tunggu. Hasil deterministik: **4/4 percobaan gagal** pada 8.000; **3/3 berhasil** pada 50, 1.000, dan 4.000 karakter.

| Panjang prompt | Teks di area percakapan | Balasan terlihat? |
|---|---|---|
| 50 | 435 | ✅ |
| 1.000 | 1.394 | ✅ |
| 4.000 | 4.541 | ✅ |
| **8.000** | **8.000** (hanya pesan user) | ❌ |

### 3.2 Instrumentasi di batas komponen (skill #3 fase 1.4)
`tests/user_test/diag_bug01.py` merekam: `request`/`response`/`requestfinished`/`requestfailed`, **body respons apa adanya**, console, pageerror, struktur DOM tiap anak `msg-list`, dan posisi gulir.

Temuan berurutan:

| Lapisan | Hasil | Kesimpulan |
|---|---|---|
| L1 request dikirim | `POST /chat` pada t=0,09 s | ✔ |
| L2 respons diterima | `HTTP 200` pada t=8,3 s | ✔ |
| L3 body dibaca | `requestfinished` pada t=8,3 s; body: `status:"success"`, `reply_len:130–169`, `session_id` ada | ✔ (bukan body yang menggantung) |
| L4 state/cache | `chat/messages/<sid>` = `[{user, len 8000}, {assistant, len 130, hasMeta:true}]`; `__pending__` = `[]` | ✔ **balasan TERTULIS** |
| L5 render/gulir | anak asisten: `innerHTML` **memuat "Halo"** tetapi `innerText` = **0**; wadah gulir `scrollTop=0 / scrollHeight=2898`, `di_dasar=false` | ❌ **di luar layar** |

Kontrol yang membuktikan balasan memang ada dan bisa dibaca: **setelah digulir ke bawah, `innerText` = 8.370** (prompt 8.000 + balasan + banner fallback).

Screenshot produksi `docs/evidence/real-user-2026-10-13/p5-02-10000-karakter.png` memperlihatkan **apa yang dilihat user**: hanya bubble-nya sendiri yang memenuhi layar; balasan ada ~2.900 px di bawah garis lipatan.

### 3.3 Akar masalah
1. `?s=`/`sessionId` baru terisi setelah echo respons → `<div key={sessionId ?? "new"}>` **berubah key** → React **me-remount** wadah gulir → `scrollTop` **direset ke 0**.
2. Effect pemasangan listener bergantung pada `[onScroll]` saja, sehingga setelah remount listener tetap menempel di **node lama yang sudah dilepas** — node baru tidak pernah melaporkan posisi gulir.
3. Gulir otomatis dijaga oleh `atBottom` yang **diturunkan dari posisi gulir**; nilai itu sudah terlanjur menjadi `false` akibat layout bubble raksasa + remount, sehingga `if (!atBottom) return;` **mematikan** gulir otomatis tepat saat balasan tiba.

Untuk prompt pendek, ketiga hal ini tidak bergejala karena balasan masih berada di dalam layar. **Itulah sebabnya bug ini hanya muncul pada panjang maksimum.**

### 3.4 Perbaikan (`nexus-frontend/src/app/chat/ChatApp.tsx`)
Prinsip: **gulir otomatis harus dikendalikan NIAT user, bukan posisi gulir.**

1. **`followRef` baru** — `true` saat user mengirim pesan; `false` **hanya** oleh interaksi manusia sungguhan (`wheel`, `touchmove`, `keydown`); `true` lagi saat tombol "Lompat ke bawah" ditekan. Menggantikan `atBottom` sebagai penentu gulir otomatis.
2. Effect pemasangan listener kini bergantung pada `[onScroll, sessionId]` → **dipasang ulang ke node baru** setiap kali wadah di-remount, dan langsung memulihkan posisi ke bawah bila user sedang mengikuti.
3. Effect gulir otomatis: penentu `followRef`, dependensi `[messages.length, loadingMsg, sessionId]`, plus **satu penegasan ulang pada 400 ms** karena layout bubble 8.000 karakter baru stabil setelah frame pertama.
4. `sendPrompt` menyalakan mode ikuti (`followRef`, `atBottomRef`, `setAtBottom(true)`).

**Perubahan yang DI-REVERT:** urutan dedup `overlay` dikembalikan ke `[...pendingCache, ...cached]` karena hipotesisnya tidak terbukti (dump cache menunjukkan `__pending__` kosong). Tidak ada perubahan tanpa akar masalah yang dibiarkan di kode.

### 3.5 Bukti red → green (skill #2 + #4)
| Keadaan | `scrollTop/scrollHeight` | `di_dasar` | Teks di area percakapan | Bubble asisten |
|---|---|---|---|---|
| **RED** (sebelum fix) | `0 / 2898` | false | 8.000 (hanya prompt) | `n=0`, teks ada di `innerHTML` tapi tak ter-render |
| **GREEN** (sesudah fix) | `2311 / 2924` | **true** | **8.399** | `n=398`, `ada_halo=true` |

`_verify_fixes.json` → `{"bug01": "GREEN"}` (balasan terlihat pada 15,7 s; 0 kartu galat).

---

## 4. BUG-02 — Refresh saat AI bekerja → chat kosong

### 4.1 Akar masalah
`?s=<sessionId>` adalah **sumber kebenaran** sesi aktif (`ChatApp.tsx:200-201`), tetapi nilainya baru ditulis di `sendPrompt` **setelah** `mutateAsync` selesai (`ChatApp.tsx:774`). Bila user menekan F5 di tengah generasi, URL belum memuat id sesi → `sessionId = null` → `messagesData = []` → aplikasi membuka **chat baru yang kosong**, walaupun server sudah membuat sesi dan menyimpan pesan user (itulah sebabnya judulnya muncul di sidebar).

Bukti red (`_rus_repro_p1_01.json`):
```
setelah_refresh: url=/chat  panjang_area_chat=0  marker_di_chat=false  marker_di_sidebar=true
VERDICT: B — pesan tersimpan di server (terlihat di sidebar), area percakapan tetap kosong
```

### 4.2 Perbaikan
Memakai kembali mesin yang sudah ada dan teruji (dipakai tombol Stop): `POST /chat/interrupted` — idempoten, memeriksa kepemilikan, tidak menghapus apa pun, dan memetakan `client_request_id` → `session_id`.

1. `useChat.ts`: `markPendingTurn()` / `clearPendingTurn()` / `readPendingTurn()` — penanda `katalir.pendingTurn.v1` di localStorage, **TTL 3 menit**.
2. `sendPrompt`: `markPendingTurn(clientRequestId)` **sebelum** request dikirim; penanda dihapus di `finally` **hanya bila sesi sudah terikat** (`sesiTerikat`).
3. `ChatApp`: effect yang, ketika `sessionId` masih kosong, membaca penanda lalu memanggil `resolveInterruptedSession()` dan mengarahkan URL ke sesi itu — **dengan 4 percobaan berjarak 1,5 detik**.

### 4.3 Dua koreksi yang ditemukan saat verifikasi produksi (dicatat apa adanya)
Verifikasi produksi pertama memberi **RED** (`_verify_fixes.json`, 10:09) meski pemeriksaan lokal sudah GREEN. Penelusuran lanjutan menemukan **dua kelemahan nyata** pada rancangan awal saya, dan keduanya diperbaiki:

| Kelemahan | Bukti | Perbaikan |
|---|---|---|
| **Percobaan pemulihan hanya SEKALI.** Bila `POST /chat/interrupted` dipanggil sebelum backend sempat meng-insert pesan user (atau `getSession()` di halaman yang baru dimuat belum siap), hasilnya `null` dan percobaan tidak pernah diulang — penanda tetap ada, tetapi percakapan tidak pernah dipulihkan. | Setelah RED: penanda masih ada (`penanda_ls_setelah` = id yang sama) padahal `POST /chat/interrupted` dengan id itu **mengembalikan 200 + session_id** saat diuji langsung | 4 percobaan berjarak 1,5 detik |
| **TTL 15 menit terlalu panjang** → penanda basi menarik user kembali ke percakapan lama saat ia membuka chat baru beberapa menit kemudian. Ditemukan justru karena uji lokal saya sendiri jadi tidak sah (sesi lama ikut dipulihkan). | Uji lokal: 3/3 percobaan melaporkan `terikat_dalam_250ms=true` tanpa respons apa pun — URL sudah memuat `?s=` sesi lama | TTL dipendekkan ke **3 menit** + `clearPendingTurn()` pada `newChat` (tindakan eksplisit user) |

**Pelajaran metodologi:** RED di produksi **tidak** saya anggap "flaky" lalu diabaikan. Penanda yang tetap ada + resolver yang terbukti bekerja adalah dua fakta yang menunjuk tepat ke "percobaan tunggal yang gagal karena balapan" — dan itulah yang diperbaiki.

### 4.4 Bukti red → green
| Keadaan | `?s=` sebelum refresh | Setelah reload |
|---|---|---|
| **RED** (`_rus_repro_p1_01.json`, produksi) | tidak ada (mid-flight) | area percakapan **0** karakter; sesi hanya muncul di sidebar |
| **GREEN** (`_verify_fixes.json`, lokal) | tidak ada (mid-flight) | `?s=<uuid>` + penanda prompt **terlihat** di area percakapan |

---

## 5. BUG-06 — Pendaftaran email `429 email rate limit exceeded`

### 5.1 Akar masalah (diverifikasi ke dokumentasi resmi — mandat skill #6)
`https://supabase.com/docs/guides/auth/rate-limits`:

> **Emails sent by Supabase Auth** — *Limited by: Project* — **"2 emails per hour with the built-in email provider."** You can configure this limit when you use custom SMTP or the Send Email hook.

Ditambah fakta dari proyek:
```
GET /auth/v1/settings → mailer_autoconfirm: false      (konfirmasi email WAJIB)
                       enabled providers: github, google, email
                       custom SMTP: tidak ada
```
→ Setiap pendaftaran mengirim email konfirmasi; pengirim bawaan hanya 2 email/jam **per proyek**; pendaftaran ke-3 dalam satu jam → `429 email rate limit exceeded`. Batas ini **tidak dapat diubah tanpa SMTP kustom / Send Email hook**.

Probe pendaftaran publik (bukti): `katalir-internal.dev` → 400 *"Email address … is invalid"*; `example.com`, `gmail.com`, `mailinator.com` → **429** *email rate limit exceeded*.

### 5.2 Yang diperbaiki (lapisan aplikasi — terverifikasi)
Sebelumnya user melihat pesan **mentah berbahasa Inggris** (`email rate limit exceeded`) tanpa jalan keluar. Sekarang:

- `src/lib/auth-actions.ts` → `classifyAuthError()` memetakan galat Supabase ke kunci i18n.
- `src/i18n/messages/id.ts` + `en.ts` → 4 kunci baru (`errRateLimit`, `errEmailInvalid`, `errAlreadyRegistered`, `errPasswordShort`).
- `src/components/auth/login-modal.tsx` → memakai pemetaan itu.

Terverifikasi: user kini melihat **"Alamat email ini tidak diterima. Periksa penulisannya, atau pakai Google/GitHub."** (Indonesia, bisa ditindaklanjuti, menyebut jalan keluar yang benar-benar tersedia).

### 5.3 Akar infra — **BLOCKED** (jujur, tidak diklaim selesai)
Perbaikan sesungguhnya adalah konfigurasi proyek Supabase, dan itu **hanya bisa lewat Management API** dengan `SUPABASE_ACCESS_TOKEN`. Token tersebut **tidak ada di `.env`** (yang tersedia hanya `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWKS`, `SUPABASE_DB_PASSWORD`) dan **tidak dapat dibuat sendiri** oleh agen — ia harus dibuat manusia di dashboard Supabase.

Perintah siap jalan (butuh token dari https://supabase.com/dashboard/account/tokens):

```bash
export SUPABASE_ACCESS_TOKEN="<scoped token>"
export PROJECT_REF="qmukkphwaajzbqjrcvaz"

# 1) Lihat konfigurasi sekarang
curl -s "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  | python -c "import json,sys;d=json.load(sys.stdin);print({k:v for k,v in d.items() if 'rate_limit' in k or 'mailer' in k})"

# 2A) OPSI TERBAIK — SMTP kustom, lalu naikkan batas kirim email
curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"smtp_host":"...","smtp_port":587,"smtp_user":"...","smtp_pass":"...","smtp_admin_email":"no-reply@katalir.de5.net","smtp_sender_name":"Katalir","rate_limit_email_sent":30}'

# 2B) ALTERNATIF CEPAT — tanpa konfirmasi email (batas 2 email/jam tidak lagi berlaku
#     karena tidak ada email yang dikirim). Trade-off keamanan harus disadari.
curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"mailer_autoconfirm": true}'
```

**Dampak bisnis bila tidak dikerjakan:** pengguna ke-3 yang mendaftar lewat email dalam satu jam akan gagal. Jalur Google/GitHub tetap normal, jadi ini memblokir satu kanal akuisisi — bukan seluruh produk.

---

## 6. VERIFIKASI DI PRODUKSI

Perbaikan dideploy ke Cloudflare Pages lewat `ops/deploy_pages.py` (kedua gerbang wajib lolos: `check-api-url-csp` + `check-bundle-hosts`), lalu diuji ulang **terhadap `https://katalir.de5.net`**:

| Pemeriksaan | Hasil produksi | Bukti |
|---|---|---|
| BUG-01 — balasan prompt 8.000 karakter terlihat | **GREEN** | balasan tiba 1,3–1,4 s; area percakapan bertambah; `posisi_gulir.di_dasar = true` |
| BUG-02 — refresh mid-generation memulihkan percakapan | **GREEN** | percobaan **sah** (`url_bersih_sebelum_kirim=true`, `terikat_dalam_250ms=false`), setelah reload `?s=<uuid>` + pesan terlihat; console: `[info] [katalir] sesi giliran terputus dipulihkan e323e8cd-…` |
| BUG-06 — pesan galat pendaftaran bisa ditindaklanjuti | **GREEN** | user melihat: *"Pendaftaran lewat email sedang dibatasi (kuota kirim email harian tercapai). Coba lagi nanti…"* |

**Jejak console pemulihan** (bukti langsung bahwa jalur BUG-02 benar-benar berjalan, bukan kebetulan):
```
[info] [katalir] sesi giliran terputus dipulihkan e323e8cd-53a0-4de4-9669-fc2f7dd6d75d
```

### 6.1 Kesalahan pada alat ukur saya sendiri — ditemukan dan diperbaiki
Pemeriksaan BUG-01 versi pertama memakai ambang **`panjang_area_chat > 8000 + 20`**. Ambang itu **terlalu longgar**: baris status "Agen sedang berpikir…" menambah ~20 karakter ke area percakapan, sehingga uji sempat melaporkan **GREEN palsu** saat balasan belum tiba (`panjang_area=8024`).

Ketahuan karena saya **membaca screenshotnya**, bukan hanya angkanya: `verify-bug01-sesudah.png` masih memperlihatkan "Agen sedang berpikir…" dan belum ada balasan. Ambang dinaikkan ke **`+80`** (balasan nyata 130–170 karakter) dan ditambah pemeriksaan `posisi_gulir.di_dasar` supaya klaim "balasan terlihat" tidak bisa lolos hanya karena status bar.

Ini contoh konkret mengapa skill #4 (`verification-before-completion`) menuntut bukti, bukan angka: **angka yang benar bisa berasal dari pengukuran yang salah.**

---

## 7. REGRESSION — 73 SKENARIO DIULANG

Dijalankan ulang terhadap produksi setelah deploy (`tests/user_test/rus_run.py all`), memakai akun uji baru.

| Grup | Sebelum | Sesudah | Catatan |
|---|---|---|---|
| P1 Budi (tidak sabar) | 10 PASS / 1 FAIL | **11 / 0** | ✅ **P1-01 (BUG-02) kini PASS** |
| P2 Siti (pemula) | 9 / 1 | 9 / 1 | P2-03b (404) — medium, di luar lingkup |
| P3 Andi (multi-tab) | 5 / 0 | 5 / 0 | |
| P4 Rina (jaringan lambat) | 8 / 0 | 8 / 0 | |
| P5 Dedi (kritis) | 10 / 5 | **11 / 4** | ✅ **P5-02 (BUG-01) kini PASS** |
| J1 user baru → workflow | 3 / 1 | 3 / 1 | J1-A2 — infra (BUG-06 §5.3) |
| J2 integrasi Shopee | 3 / 0 / 1 NOT_RUN | 3 / 0 / 1 NOT_RUN | |
| J3 isolasi multi-user | 4 / 0 | 4 / 0 | |
| B bug hunt | 10 / 1 / 1 NOT_RUN | 10 / 1 / 1 NOT_RUN | B-12 (a11y) — low |
| **TOTAL** | **62 PASS · 9 FAIL · 2 NOT_RUN** | **64 PASS · 7 FAIL · 2 NOT_RUN** | **73 skenario** |

**Tidak ada regresi:** tidak satu pun skenario yang tadinya PASS berubah menjadi FAIL.

**Sisa 7 FAIL — semuanya di luar lingkup 3 bug high:**

| Skenario | Sev | Alasan masih FAIL |
|---|---|---|
| P5-05 null byte → bocoran internal | medium | BUG-03 — belum diperbaiki (tugas ini hanya 3 high) |
| P5-11 non-UUID → 500 + bocoran | medium | BUG-04 — belum diperbaiki |
| P5-12b non-UUID PATCH/DELETE → 500 | medium | BUG-04 — belum diperbaiki |
| P5-15 model default tidak dilayani | medium | BUG-05 — belum diperbaiki |
| P2-03b halaman 404 | medium | BUG-07 — belum diperbaiki |
| J1-A2 pendaftaran email | high (infra) | BUG-06 §5.3 — **BLOCKED**, butuh `SUPABASE_ACCESS_TOKEN` |
| B-12 aksesibilitas /templates | low | BUG-10 — belum diperbaiki |

### 7.1 Target ≥70 PASS: **TIDAK TERCAPAI — dilaporkan apa adanya**
Brief menargetkan **≥70 PASS**; hasilnya **64**. Angka ini **tidak saya bulatkan atau klaim tercapai**.

Sebabnya jelas dan terukur: target itu mengandaikan seluruh 9 kegagalan awal beres, sedangkan **tugas ini hanya meminta 3 bug high**. Dua di antaranya (P1-01, P5-02) berhasil → +2. Sisanya:

| Untuk mencapai | Perlu | Tambahan PASS |
|---|---|---|
| 64 (sekarang) | — | — |
| **68** | perbaiki BUG-03, BUG-04 (×2 skenario), BUG-05 | +4 |
| **69** | + BUG-07 (halaman 404) | +1 |
| **70** ✅ | + BUG-10 (a11y) | +1 |

Jadi **≥70 PASS memerlukan 4 bug medium/low tambahan** (BUG-03, BUG-04, BUG-05, BUG-07, BUG-10) — pekerjaan yang nyata dan terukur, bukan penghalang misterius. Yang **tidak** bisa dicapai lewat kode adalah J1-A2 (BUG-06 §5.3).


---

## 8. VERDICT SETELAH PERBAIKAN

| Bug | Sebelum | Sesudah |
|---|---|---|
| BUG-01 | high (P1) | **FIXED & terverifikasi di produksi** — balasan terlihat; `posisi_gulir.di_dasar=true`, area percakapan 8.404 (prompt + balasan + footer) |
| BUG-02 | high (P1) | **FIXED & terverifikasi di produksi** — percakapan dipulihkan setelah refresh; jejak console `sesi giliran terputus dipulihkan …` |
| BUG-06 | high (P1) | **TURUN ke medium** — pesan galat kini bisa ditindaklanjuti; akar infra masih perlu 1 perintah manusia |

**Konsekuensi pada verdict:** high tersisa **0–1** (BUG-06 hanya bila tim menilai kendala infra tetap high).
- Bila tim menyelesaikan §5.3 → **SIAP LAUNCH** (0 critical, 0 high).
- Bila §5.3 belum dikerjakan → **CONDITIONAL** dengan sisa 1 butir high non-kode (1 perintah Management API), bukan cacat aplikasi.

**Skor hard test bergerak 62 → 64 PASS** (dan 0 regresi). Untuk mencapai target ≥70 PASS masih perlu BUG-03, BUG-04, BUG-05, BUG-07, BUG-10 (§7.1).

> Catatan kejujuran: BUG-06 **tidak saya klaim fixed**. Batas 2 email/jam adalah kebenaran sistem yang hanya bisa diubah pemilik proyek; yang saya kerjakan adalah bagian yang memang ada di tangan saya (pesan galat yang bisa ditindaklanjuti), dan itu terverifikasi. Target ≥70 PASS juga **tidak tercapai** dan dilaporkan apa adanya beserta rincian apa yang diperlukan untuk mencapainya.

---

## 9. YANG DIUBAH (ringkas)

| Berkas | Perubahan | Untuk |
|---|---|---|
| `nexus-frontend/src/app/chat/ChatApp.tsx` | `followRef` (niat user) menggantikan `atBottom` sebagai penentu gulir; listener dipasang ulang per `sessionId`; gulir otomatis + penegasan 400 ms; mode ikuti dinyalakan saat kirim; tombol "Lompat ke bawah" menyalakan mode ikuti; **effect pemulihan sesi (BUG-02)**; `markPendingTurn`/`clearPendingTurn` di `sendPrompt` | BUG-01, BUG-02 |
| `nexus-frontend/src/features/chat/hooks/useChat.ts` | `PENDING_TURN_KEY`, `markPendingTurn`, `clearPendingTurn`, `readPendingTurn` | BUG-02 |
| `nexus-frontend/src/lib/auth-actions.ts` | `classifyAuthError()` | BUG-06 |
| `nexus-frontend/src/components/auth/login-modal.tsx` | pakai pemetaan galat auth | BUG-06 |
| `nexus-frontend/src/i18n/messages/id.ts`, `en.ts` | 4 kunci galat auth baru | BUG-06 |
| `tests/user_test/diag_bug01.py` | instrumentasi batas komponen (jaringan, body, DOM, gulir) | diagnosis |
| `tests/user_test/verify_fixes.py` | uji red-green BUG-01/02/06 | verifikasi |
| `tests/user_test/serve_out.py` | server statis lokal untuk uji sebelum deploy | verifikasi |
| `tests/user_test/rus_core.py` | `proxy_backend()` (lewati CORS untuk uji lokal), `RUS_FRONTEND` env override | verifikasi |

**Tidak ada perubahan yang dibiarkan tanpa akar masalah.** Satu perubahan (urutan dedup `overlay`) di-revert setelah hipotesisnya gugur.

---

## 10. CATATAN METODOLOGI (agar angka ini bisa dipercaya)

- **Perbaikan diuji LOKAL dulu** (build statis di `127.0.0.1:4321` menunjuk backend produksi) sebelum menyentuh produksi. Karena backend produksi menolak origin lokal lewat CORS, harness memakai `proxy_backend()` yang meneruskan request dari Python dengan origin produksi lalu mengembalikannya dengan header CORS permisif — **isi respons tidak diubah**. Tanpa ini, semua request lokal gagal dan pengujian akan menyesatkan (gejalanya "error card" yang sama sekali tidak berhubungan dengan bug).
- **`innerText` tidak boleh dipakai sendirian** untuk menilai "apakah balasan tampil": pada BUG-01, teks balasan ada di `innerHTML` sementara `innerText` melaporkan 0 karena subtree berada di luar area pandang. Penilaian akhir memakai kombinasi `innerText` + `innerHTML` + posisi gulir + screenshot.
- **Batas panjang di-bisect**, bukan diasumsikan: 50/1.000/4.000 lulus, 8.000 gagal → mengarahkan ke mekanisme yang bergantung tinggi konten (gulir), bukan ke parser/retry.
- **Hook debug dibuang dari produksi.** Selama diagnosis saya menambahkan `window.__katalirCache()` (di-gate `NEXT_PUBLIC_DEBUG_CACHE`). Cache build Next.js membuat hook itu ikut ter-inline ke build produksi, jadi hook **dihapus dari sumber** dan build dijalankan ulang bersih (`.next/cache` dibersihkan) — diverifikasi `grep __katalirCache out/` = 0.
- **Berkas harness tidak diubah saat run berjalan** (modul sudah ter-import; perubahan tidak berlaku dan memaksa run ulang).
