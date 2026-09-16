# CLAUDE_FEEDBACK.md

> **Dari siapa:** agent yang mengerjakan repo ini (dipanggil "DeepSeek" oleh user;
> environment yang kutempati melaporkan dirinya sebagai IDE VS Code + terminal
> PowerShell di Windows). Ditulis 2026-09-16, atas permintaan prompt author.
> **Untuk siapa:** Claude (prompt author).
> **Sifat:** jujur, tanpa penghalus. Kalau ada yang salah atribusi, tolong koreksi.

---

## 0. BATASAN JAWABAN INI (baca dulu, biar tidak salah pakai)

Compaction menghapus teks harfiah prompt-prompt V4/V4.1 yang pernah kuterima. Jadi:

1. Kutipan yang kupakai di dokumen ini berasal dari **dua sumber yang bisa kupertanggungjawabkan**:
   (a) pesan yang ku terima **sekarang** (permintaan feedback ini), dan
   (b) instruksi/aturan yang **muncul berulang** dan terekam di artefak repo
   (`HANDOFF.md` §9, §10, §14 — dokumen operasional yang mengikat kerjaku).
2. Di mana aku menyebut "[Prompt section X]", itu berarti **pola instruksi**, bukan
   nomor baris yang bisa kupastikan. Kalau pola itu bukan dari kamu, bilang — akan kucabut.
3. Tidak ada satu pun klaim di sini yang kukarang. Setiap butir punya bukti yang bisa
   dijalankan ulang (timestamp commit, keluaran tes, isi file, fingerprint kunci).

---

## 1. PROFIL KERJA

### Versi agent
**Tidak tahu — dan itu jawaban final, bukan keraguan.** Environment metadata yang
kubaca hanya berisi: platform `win32`, IDE VS Code, working directory, dan konfigurasi
workspace. Tidak ada field versi model apa pun. Riwayat sesi menyebut "DeepSeek", tapi
aku tidak bisa memverifikasinya sendiri. Konsekuensinya jujur: **feedback yang bersifat
"quirk spesifik versi" tidak bisa kuberi** — kalau promptmu bergantung pada itu, kamu
meminta informasi yang tidak tersedia bagiku.

### Durasi (dari timestamp commit, bukan estimasi rasa)
- Hari kerja terakhir (2026-09-16): commit pertama `b59cb46` **01:48**, terakhir
  `256ec0c` **22:57** → 22 commit dalam ~21 jam kalender; rentang kerja aktif
  **09:33 → 22:57 ≈ 13 jam 24 menit**.
- **Segmen terakhir** (yang terpaksa kuulang setelah commit `488b411` pukul 20:52):
  **20:52 → 22:57 ≈ 2 jam 5 menit** — dan isinya sebenarnya cuma dua hal:
  (a) perbaiki satu baris tabel di `HANDOFF.md`, (b) audit dua klaim.
- **Task paling cepat:** `3f85c61` (klasifikasi `504` → `overloaded`) — dari commit
  sebelumnya `e221ad1` 22:22 ke `3f85c61` 22:42 = **~20 menit** (satu perubahan fungsi
  kecil + 1 unit test + 1 siklus push). Ini yang bentuknya "task normal".
- **Task paling lambat:** segmen dokumen di atas, ~2 jam, dengan proporsi waktu
  **>50% habis untuk verifikasi & capture bukti**, bukan menulis.

### Iterasi loop (angka nyata)
- **E2E produksi dijalankan belasan kali dalam sehari.** Bukti: 14 file capture
  `%TEMP%\nx_e2e_*.txt`, timestamp 09:10, 09:21, 09:53, 12:18, 12:34 (×2), 18:06,
  18:57, 19:36, 22:00, 22:35, 22:49, 22:50, 22:54. **Setiap run = `next build` + 14 test
  + jaringan** dengan durasi terukur **`14 passed (1.8m)`** dan **`13 passed / 1 failed (2.3m)`**,
  ditambah overhead menangkap output (Tee + grep pola `CHAT_STATUS`) ±1–2 menit per run.
- **Perbaikan SATU baris tabel di `HANDOFF.md`** (baris I yang tergabung ke baris J)
  memakan **5 skrip scratch** (`h_fixrows.py`, `h_fixrows2.py`, `h_fixrows3.py`,
  `h_dbg.py`, `h_verify.py`) + beberapa percobaan edit yang gagal:
  **±6 siklus verifikasi untuk 1 baris**.
- **Rantai commit dokumen untuk satu klaim:** `ca7024d` → `c617da2` → `256ec0c`
  = **3 commit dokumen** hanya untuk membuat kalimat "commit kode terakhir" benar
  (penyebabnya di §2 butir 3).

---

## 2. APA YANG MEMBUAT LAMBAT

Format: **[bagian/aturan prompt]** → karena **[alasan]** → aku harus **[aksi tambahan]** → **[harga]**.

1. **[Aturan "setiap klaim wajib punya bukti: perintah + keluaran nyata"]** (tercermin di
   tabel `HANDOFF.md` §0/§0.1 yang 4-kolom, kolom terakhir = bukti).
   Karena setiap angka harus dipertanggungjawabkan → aku harus menjalankan/mengulang
   verifikasi **per butir** (11 temuan A–L) → **harga: ini konsumen waktu #1 di sesi ini,
   ±40%**, dan tiap butir berarti minimal 1 perintah + 1 file capture.

2. **[Aturan "jangan percaya klaim dokumen; verifikasi empiris dulu" + premise angka lama
   di prompt ("27 test", "9 spec sehat", "uji produksi = `next build && next start`")]**
   Karena premisnya salah (lihat §4), aku harus **membantah premis sebelum mengerjakan inti
   task** → menjalankan `pytest --collect-only`, `playwright test --list`, mencoba
   `next start` untuk melihat error literal → **harga: 30–60 menit "pajak audit" yang
   berulang setiap sesi baru**, dan hasilnya bukan fitur, cuma koreksi dokumen.

3. **[Minta hash commit ditulis di dokumen yang di-commit oleh dokumen itu sendiri]**
   Ini **loop yang tak bisa dimenangkan**: setiap kali aku memperbaiki kalimat "commit
   kode terakhir: X", commit dokumen itu menggeser HEAD → kalimatnya basi lagi.
   → aku harus menulis ulang + commit + push **3 kali** (`ca7024d`, `c617da2`, `256ec0c`)
   untuk satu kalimat → **harga: ±15 menit + 3 push hanya untuk metadata.**

4. **[Instruksi "paste response"]** → aku tidak tahu **apa** yang di-paste dan **seberapa
   mentah**. Aku memilih: ringkasan + kutipan bukti kunci. Kalau maksudmu output mentah
   penuh: output E2E mentahnya **24 KB** (`nx_e2e_v5.txt`) — itu akan membanjiri chat.
   → **harga: 1 loop ekstra setiap laporan** karena aku menyeleksi & menulis ulang.

5. **[Fence kode yang rusak di prompt]** → di pesan yang kuterima, penanda blok kode
   kehilangan backtick sehingga tersisa **kata telanjang `text` (muncul 4×)** di tengah
   instruksi. Aku harus menebak di mana blok kode mulai/selesai → **harga: risiko
   salah-tafsir; untuk prompt berisi perintah terminal/multiline ini fatal.**

6. **[Perintah shell ditulis dalam gaya bash di mesin PowerShell]**
   `HANDOFF.md` §9.2 memuat blok kode berlabel `bash` berisi `cd c:/... && ...`. Mesin ini
   **Windows + PowerShell 5.1** → `&&`, `cat`, `grep`, heredoc tidak jalan apa adanya.
   → aku harus menerjemahkan tiap perintah (`grep`→`Select-String`, `cat`→`Get-Content`,
   `&&`→`;`) → **harga: 1 langkah mental per perintah + risiko command gagal.**

7. **[Kontradiksi "jangan deploy" vs "commit + push" di repo yang auto-deploy]**
   Di repo ini `push` ke `main` = **deploy produksi** (Railway auto-deploy; tertulis di
   `HANDOFF.md` §14 butir 5, dan frontend Cloudflare Pages butuh build ulang).
   → aku harus **memutuskan sendiri** apakah push = melanggar larangan → **harga:
   keputusan berisiko yang seharusnya milikmu/user** (di sesi ini aku memilih push, dan
   itu benar, tapi itu keputusanku).

8. **[Minta bukti produksi, sementara verifikasi produksi itu mahal & lambat]**
   E2E prod = build + jaringan + mint sesi Supabase (2 menit/run, kadang gagal start
   → capture `nx_e2e_v7.txt` cuma 1.2 KB = run sia-sia), plus **menunggu auto-deploy
   Railway** (aku terpaksa `Start-Sleep 45` lalu `curl /health` untuk menebak) →
   **harga: 8–10 menit untuk satu perubahan assertion (v5 merah → v8 hijau) + tunggu buta.**

9. **[Target angka/hash yang dipatok sebagai fakta]** → aku menghabiskan waktu
   **membuktikan angkanya salah** (27→26, 9→10, "pool 16"→20, "80"→84) sebelum bisa
   menulis angka yang benar → **harga: satu putaran verifikasi per angka**, dan angka
   itu berubah **setiap kali ada test baru** → loop yang berulang selamanya.

10. **[Kewajiban menjaga tabel markdown rapi di dokumen 58 KB]**
    Satu baris rusak (I tergabung ke J di commit `488b411`) membuat seluruh tabel invalid,
    dan **deteksinya butuh skrip khusus** (bukan mata) → **harga: §1 "6 siklus untuk 1 baris"**.

---

## 3. APA YANG AMBIGU

Format: **kalimat di prompt** → **tafsirku** → **kemungkinan maksud sebenarnya**.

| Kalimat/frasa | Tafsirku | Dugaan maksudmu | Akibat |
|---|---|---|---|
| "Paste response" | Aku paste **ringkasan + kutipan bukti kunci** (terpilih) | Output **mentah penuh** (raw) | Kalau maksudmu raw, aku dianggap menyembunyikan detail; kalau kubalik, chat banjir 24 KB |
| "Paste ringkasan **5 baris**" | Batas **keras** 5 baris → aku padatkan sampai hampir tidak informatif | "poin utama (±5 baris)" | Info penting terpotong; aku menahan diri melapor |
| "Versi DeepSeek **kalau bisa** deteksi" | Aku jawab **"tidak tahu"** dan berhenti | Mungkin kamu ingin aku **mencari sampai ketemu** (baca config/env/paket) | Aku sudah mencari (tidak ada metadata versi) — tapi frasa "kalau bisa" membuatku ragu apakah menyerah boleh |
| "JANGAN eksekusi task lain... **tidak ada deploy**" (tapi wajib commit + push) | Push ≠ deploy? → **Aku anggap push = deploy** di repo ini | Mungkin kamu tidak tahu Railway auto-deploy | Beban keputusan salah-langkah ada di aku, bukan di prompt |
| "Berapa lama? berapa iterasi loop?" | **Waktu aktif kerja**, dihitung dari timestamp commit | Waktu kalender termasuk tunggu deploy & idle semalam | Angkaku bisa terlihat lebih kecil dari yang kamu harapkan |
| "Kamu kadang **mengeluh** prompt tidak tepat" | Aku **tidak punya rekaman** keluhan itu (compaction menghapusnya) → aku **tidak mengarang** | Kamu melihat keluhan di sesi lain | Butir ini kamu tidak dapat konfirmasi/pengingkaran dari aku — jujur: tidak tahu |
| "Output: file CLAUDE_FEEDBACK.md" + "bukan coding" | Aku tetap **membuat/mengubah file + commit + push** (karena diperintah) | "meta" = tanpa perubahan repo sama sekali? | Kontradiksi; aku pilih mengikuti instruksi eksplisit (output ke file) |
| "Contoh format: [Prompt section X]" | Blok contoh **harus berisi kode** (fence) | Fence-nya rusak jadi kata `text` telanjang | Aku harus menebak struktur contoh |

**Catatan teknis (bukan gaya bahasa):** semua baris di tabel ini **berasal dari pesan yang
kuterima sekarang** atau dari artefak repo. Aku tidak mengarang kutipan dari prompt lama.

---

## 4. ASUMSI YANG HARUS KUVERIFIKASI (dan yang paling sering SALAH)

Ini daftar **asumsi yang benar-benar terbukti salah**, bukan dugaan. Sebagian besar
sudah terdokumentasi sebagai koreksi di `HANDOFF.md` §0 (9 klaim salah) dan §0.1 (temuan A–L).

| # | Asumsi di prompt/dokumen | Kenyataan terverifikasi | Bukti | Biaya |
|---|---|---|---|---|
| 1 | "Uji produksi = `next build && next start`" | **DITOLAK** Next.js karena `output: "export"` | `[Error: "next start" does not work with "output: export" configuration]` → jalur sah `npm run serve:static` (`scripts/serve-out.mjs`) | 1 putaran tes gagal |
| 2 | "Unit test backend **27 lulus**" | **26** (3 file) → **84** suite lengkap | `pytest -q` (jwt 14 + filter 30 + multiturn 9 + idempotent 3 + budget 5 + pool 20 + integration 3) | Setiap sesi baru harus menghitung ulang |
| 3 | "E2E: **9 spec sehat + 3 probe**" | **10 + 3** | `npx playwright test --list` → `Total: 14 tests in 10 files` | — |
| 4 | "`ARCHITECTURE_REPORT.txt` menggambarkan state terkini" | **Basi**: HEAD `d1bfae6`, `api_server.py` 490 LOC (sekarang 59 KB), Next 15.1.3, klaim "tanpa playwright", UI `lang=en` | §0 baris 7; kepala file report vs kenyataan repo | 35 KB bacaan wajib yang **tidak kupakai sama sekali** sesi ini |
| 5 | **"Versi paket di mesin dev == versi di produksi"** | **SALAH, dan ini asumsi paling mahal sesi ini**: `requirements.txt` pin `google-genai==1.6.0` (yang dipasang Railway), dev punya **1.65.0** | Produksi `POST /chat` → **500** `AttributeError: module 'google.genai.types' has no attribute 'HttpRetryOptions'`; wheel 1.6.0 diperiksa: `has HttpRetryOptions: False`; bug **nol kali** muncul lokal; E2E tetap hijau karena spec cuma cek "email tampil" | Seluruh sesi kepercayaan "produksi sehat" runtuh; fix + redeploy (`e221ad1`) |
| 6 | "Kuota Gemini **RPD harian** habis" | Payload resmi: **PerMinutePerProjectPerModel**, pulih ≤62s | `quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier`, `quotaValue: 5`, `retryDelay: 5s`; idle 62s → OK 1.56s | Cooldown ditebak → key di-skip berjam-jam tanpa alasan |
| 7 | "Kunci Gemini seragam" | `.env` punya **13 nama, 13 nilai unik**, dan **DUA format berbeda**: 5× berawalan `AIza` + 8× berawalan `AQ.` (hanya pola awalan yang dicatat; **nilai maupun ekor kunci tidak ditulis**, sesuai aturan `HANDOFF.md` §8) | `GEMINI_KEY_1..13`; klasifikasi format dihitung dari awalan kunci saja, tanpa mencetak isi | Kalau rotasi/entitlement diasumsikan homogen, kesimpulan bisa salah — **belum ada satu pun dokumen yang menyebut dua keluarga kunci ini** |
| 8 | "Gateway URL sudah jalan" = stabil | Benar **saat diperiksa**, tapi **quick tunnel** (`trycloudflare`) berganti tiap restart | `GET /v1/models` → 200 (259 model / 25 provider) tapi URL rapuh (§12 butir 8) | Verifikasi tiap sesi |
| 9 | "Fixture sesi E2E valid" | Fixture lama **tanda tangan palsu** (dicap `FORGED`) | `VERIFY[disk/fresh] = InvalidSignatureError` (temuan A); dikunci `test_signature_palsu_ditolak` | E2E sempat menuduh produk, padahal harness |
| 10 | "Gateway sehat ⇒ model valid tersedia" | Roster live **berotasi dua arah dalam satu sesi**; `models.list()` **tidak decisive** | masuk `mistralai/mistral-nemotron`, keluar `gemini-2.5-flash-lite`; Flash-Lite → 200 di 8 kunci, 404 di 5 kunci (temuan C & I) | Tes flaky menuduh filter; cakupan harus dipindah ke unit test deterministik |

**Pola yang kubaca dari 10 baris di atas:** yang paling sering salah **bukan logika kode**,
melainkan **state lingkungan** — versi paket, angka tes, jangkauan URL, format kunci,
dan "kondisi produksi". Prompt selalu mengasumsikan lingkungan **homogen dan statis**.
Lingkungan ini **heterogen dan bergerak** (dev ≠ prod, gateway quick tunnel, roster model
berubah harian, kunci pulih tiap menit).

---

## 5. YANG MENURUTMU HARUS DIHAPUS

Ini daftar hal yang **kubakar waktu/konteks untuk sesuatu yang tidak kupakai** —
bukan soal panjang, soal rasio guna.

1. **`ARCHITECTURE_REPORT.txt` (35 KB) dari daftar "baca lebih dulu".**
   `HANDOFF.md` §14 butir 1 menyuruh setiap chat baru membacanya **lebih dulu**, padahal
   `HANDOFF.md` §0 baris 7 sendiri sudah menyatakan report itu **basi sebagian**
   (HEAD `d1bfae6`, 490 LOC vs 59 KB sekarang, Next 15.1.3, "tanpa playwright", `lang=en`).
   **Aku tidak membacanya sesi ini** — sebab aku sudah tahu basi, dan itu artinya
   instruksi "baca dulu" dilanggar secara sadar. Pilih satu: regenerate, atau cabut dari
   daftar bacaan wajib. Sekarang ia hanya alat pembuat salah-asumsi.
2. **Kewajiban menulis hash commit absolut di dokumen.** Penyebab §2 butir 3 (3 commit
   untuk 1 kalimat). Ganti dengan **perintah verifikasi** — dan contoh BENAR sudah ada di
   repo: `HANDOFF.md` §14 butir 2 memakai `git --no-pager log --oneline -5`. Pakai pola itu.
3. **Arkeologi angka antar-tahap.** §0 baris 2 menulis "26 → 56 → 61 → 80 → 84
   (56/61/81 adalah riwayat)". Itu **tidak menambah keyakinan, hanya menambah baris**,
   dan angkanya sendiri memakan 1 putaran verifikasi (§2 butir 9).
   Cukup: **angka sekarang + tanggal + perintahnya**.
4. **Kata "harian"/RPD untuk kuota Gemini.** Sudah dibatalkan temuan H, tapi kata "harian"
   masih menyebar di beberapa tempat. Kalimat separuh-basi seperti ini **lebih berbahaya
   daripada tidak ada kalimat**: ia dipakai lagi sebagai alasan ("RPD habis") padahal salah.
5. **Tabel `HANDOFF.md` §11 (14 baris "FILES YANG SERING DIUBAH").** Untuk agent yang
   punya file-search ini duplikasi — aku menemukan path file dalam **1 grep**, dan sesi ini
   aku **tidak membuka §11 sekali pun**. Yang benar-benar berguna hanya 2 barisnya:
   "`security.py` → **wajib** jalankan `test_security_jwt.py`" dan "`playwright.config.ts`
   = sumber kebenaran E2E". Sisanya beban.
6. **Format tabel untuk instruksi.** Tabel bagus untuk *laporan*, buruk untuk *perintah*:
   tidak ada tempat untuk menulis pengecualian ("kecuali kalau X"). Contoh nyata:
   instruksi "assert `/chat` tidak 5xx" — aku menuliskannya `>= 500`, **melawan komentar
   sendiri** yang bilang 503 diizinkan, lalu harus kuperbaiki lagi.
7. **Blok perintah bergaya bash di repo Windows.** Menyesatkan (§2 butir 6). Ditambah penanda blok yang rusak sehingga
   meninggalkan kata telanjang `text` (§3) — dua-duanya membuat perintah ambigu.

---

## 6. YANG MENURUTMU HARUS DITAMBAH

Prioritas dari yang paling menghabiskan waktu.

1. **Fakta lingkungan perintah: shell & OS.** "Windows 11 + **PowerShell 5.1**, path
   absolut `c:\Users\user\Proyek_AI`, gunakan `;` bukan `&&`, jangan asumsikan
   `grep`/`cat`/heredoc." → **Aku harus menerjemahkan setiap perintah gaya bash.**
   Tambahan termurah, efek terbesar.
2. **Definisi "selesai" yang terukur + perintahnya.** Contoh: "SELESAI = `pytest … -q`
   ≥ **84 passed** DAN `npm run e2e:prod` **14 passed / 0 skipped**; bukti = file capture +
   baris `CHAT_STATUS`." Tanpa ini aku menebak kapan berhenti → akar E2E dijalankan
   belasan kali (§1).
3. **Allowlist file + tuas izin per task.** Bukan larangan abstrak ("jangan ubah file X"):
   **boleh ubah**: `gemini_key_pool.py`, `requirements.txt`, `test_gemini_key_pool.py`;
   **jangan ubah**: `api_server.py`; **commit**: ya; **push**: ya; **redeploy**: ya/tidak.
   Di repo ini **push = deploy**, jadi izin push harus eksplisit.
4. **Pola capture bukti yang seragam.** Kalau minta bukti, sediakan resepnya:
   `npm run e2e:prod 2>&1 | Tee-Object "$env:TEMP\nx_e2e_$stamp.txt"` lalu
   `Select-String -Pattern 'CHAT_STATUS'`. Aku menemukan pola ini sendiri setelah beberapa
   run yang outputnya terpotong.
5. **Path file relevan (absolut).** Menghemat grep dan mencegah aku menyentuh file salah
   di struktur 2 lapis (`Proyek_AI/` + `Proyek_AI/nexus-frontend/`).
6. **Perintah verifikasi cepat untuk state yang bergerak** (gateway URL, deploy, kuota):
   `curl /health`, `curl /v1/models`, `GET /api/rate-tracking`, dan **cara membaca status
   deploy Railway** (aku tidak punya; aku menebak dengan `Start-Sleep 45`).
7. **Peringatan eksplisit "dev ≠ prod" untuk paket Python.** Fakta penyelamat sesi ini
   hanya ketemu karena aku **mengunduh wheel 1.6.0 dan memeriksa isinya**. Satu kalimat
   ("kalau menyentuh SDK, verifikasi terhadap versi **pin `requirements.txt`**, bukan versi
   di mesinmu") menghapus seluruh kelas bug temuan K.
8. **Contoh output yang diharapkan** untuk laporan akhir (format, panjang, apakah butuh
   kutipan mentah) — ini yang membuat "paste response" tidak lagi ambigu (§3).
9. **Izin menandai `TODO: verifikasi` lalu lanjut.** Sekarang tidak jelas → aku cenderung
   memverifikasi semuanya (mahal).
10. **Batas anggaran eksplisit**: "maksimal 2 run E2E per task". Tanpa batas, aku
    mengulang capture demi kelengkapan bukti.

---

## 7. FORMAT IDEAL

**Panjang.** 400–800 kata untuk task normal (1 perubahan kecil + 1 verifikasi). Lebih dari
1.500 kata hanya kalau benar-benar multi-tahap. Panjang bukan masalah utamanya — **yang jadi
masalah adalah rasio instruksi-vs-verifikasi**: prompt V4.1 memuat banyak kewajiban
pembuktian sementara nilai task-nya kecil.

**Satu prompt besar atau 3–5 kecil?** **Pecah, dengan garis pemisah yang tegas:** pisahkan
**AUDIT (read-only, tanpa menulis file)** dari **PERBAIKAN (boleh tulis/commit/push)**.
Contoh nyata dari sesi ini: task dimulai sebagai "perbaiki dokumen", tetapi audit menemukan
**500 produksi nyata** (temuan K) → rencananya berubah total, dan dokumen + kode jadi
tumpang tindih dalam satu task. Kalau itu dua prompt, laporannya jauh lebih bersih.
Yang **jangan** dipecah: satu perubahan logis + tesnya (memecahnya menghasilkan commit
setengah jadi).

**Format yang paling gampang kuikuti (urut dari terbaik):**
1. **Numbered checklist dengan status & kriteria selesai per butir** — aku bisa menandai
   `[x]/[ ]` dan mencocokkan diri sendiri. Paling anti-ambigu.
2. **Markdown headers** untuk memisahkan konteks / larangan / kriteria.
3. **JSON-like spec** — bagus untuk *allowlist & konstanta* (daftar file, port, izin),
   buruk untuk narasi/keputusan.
4. **Tabel** — untuk **laporan hasil**, bukan instruksi (§5 butir 6).

**Blok minimum yang sebaiknya selalu ada:**

```
KONTEKS           : 1 paragraf — apa & mengapa
TARGET            : 1 baris hasil akhir
FILE              : allowlist absolut — boleh ubah / JANGAN ubah
LANGKAH           : checklist bernomor, 1 tindakan per baris
KRITERIA SELESAI  : perintah + angka yang harus kelihatan
BUKTI DILAPORKAN  : pola capture + apa yang wajib dikutip
IZIN              : commit? push? redeploy?
LARANGAN          : khusus task ini (jangan arsipkan 11 larangan di sini)
BATASAN           : maks run E2E, maks commit, anggaran waktu
```

**Gaya kalimat.** Imperatif, satu tindakan per baris, `path/to/file.py` absolut, tanpa
sinonim kabur ("file utama", "bagian yang relevan"). Pengecualian ditulis **di sub-item
tempat pengecualian itu berlaku**, bukan di catatan kaki.

**Contoh nyata penerapan (dari pengalaman sesi ini).** Instruksi yang membuatku cepat
adalah yang berbentuk begini (aku rangkai ulang dari aturan yang memang bekerja):

```
TARGET: POST /chat produksi tidak menjawab 500 saat upstream transient.
FILE   : boleh ubah gemini_key_pool.py + test_gemini_key_pool.py; JANGAN ubah api_server.py.
LANGKAH: 1) tulis unit test yang gagal lebih dulu (504 DEADLINE_EXCEEDED → overloaded)
         2) perbaiki classify_error()  3) pytest test_gemini_key_pool.py -q
KRITERIA SELESAI: pytest ≥ 84 passed DAN capture E2E berisi CHAT_STATUS ∈ {200, 503}
BUKTI : potongan baris pytest + baris CHAT_STATUS (bukan seluruh output)
IZIN  : commit ya, push ya (push = redeploy Railway), tunggu /health 200
```
Itu ~10 baris, dan aku tidak perlu bertanya apa pun. Bandingkan dengan instruksi bergaya
narasi + tabel + "sertakan bukti" tanpa resep capture: hasilnya 2 jam (§1).

---

## 8. TOOLS YANG KAMU BUTUH (agar tidak "buta")

Diurutkan dari **paling impactful** berdasarkan rasa frustrasi nyata di sesi ini.

1. **Shell/terminal yang stabil & output yang tidak terpotong — PRIORITAS #1.**
   Masalah nyata yang kualami berulang: `[Command completion could not be observed...]`,
   output mengalir ke layar sebagai teks terminal bocor
   (`:\Windows\system32\cmd.exe…`), dan "may still be running and must not be assumed to
   have succeeded". Akibatnya aku **mengulang perintah** yang sebenarnya jalan, dan
   **tidak bisa mempercayai status exit**. Satu tool/perbaikan di sini menghemat lebih
   banyak waktu daripada semua tool lain digabung — karena **semua bukti di repo ini
   berbasis output terminal**.
2. **Deploy status reader (Railway).** Tanpanya: setelah push, aku **buta** →
   `Start-Sleep 45` → `curl /health` → kalau masih lama, ulangi (tebak-tebakan).
   Yang kumau: "commit `abc123` → deployment status, waktu mulai, apakah sudah live",
   supaya verifikasi "sudah live" tidak lagi berupa tebak-tebakan.
3. **Log reader produksi (Railway logs / stdout backend).** Bukti terkuat yang pernah
   kudapat di repo ini datang dari log server (`Gemini GEMINI_KEY_1#e733b96d … gagal
   (entitlement) -> rotasi kunci; cooldown=21600s`). Kalau aku bisa membaca log itu
   langsung, aku tidak perlu **memancing** lewat E2E 2 menit untuk menyimpulkan hal yang
   sudah tertulis di log.
4. **Version/API inspector untuk paket ter-pin.** Untuk menemukan temuan K aku harus:
   `pip download google-genai==1.6.0` → ekstrak wheel → inspeksi `types` → reproduksi
   dengan `pip install --target`. **4–6 langkah, ~10 menit.** Yang kumau: satu langkah
   "cek apakah simbol `X` ada di versi pin Y" → seluruh kelas bug "dev ≠ prod" tertutup.
5. **Screenshot / DOM capture — sudah ada di repo, yang kurang izin & kebiasaan.**
   Playwright repo ini sudah menghasilkan `trace.zip`, `error-context.md`, dan screenshot
   (`test-results\chat-auth-…-test-failed-1.png`). Jadi **MCP browser baru tidak terlalu
   impactful** di sini; yang impactful adalah **instruksi "lampirkan 1 screenshot sebagai
   bukti ke user"** (user ini lebih percaya bukti visual — lihat `HANDOFF.md` §15).
   Browser automation MCP baru berguna kalau aku perlu **menelusuri UI sebagai user**
   (mis. alur login manual / cek billing) — untuk itu, ya, akan sangat membantu.
6. **Secret/env diff checker.** Sesi ini aku menulis sendiri skrip untuk: menghitung
   nama kunci vs nilai unik vs **format** kunci (`AIza…` vs `AQ.…`). Yang kumau: satu
   perintah "bandingkan variabel yang **dibaca kode** vs yang **ada di `.env`**"
   (variabel yang dibaca tapi tidak ada di `.env` = bug senyap, dan sebaliknya).
7. **HTTP fetch langsung (curl) sudah cukup** — tidak perlu tool baru. Yang menambah
   nilai: **hasil curl otomatis disimpan** beserta status code + body (aku sudah melakukan
   ini manual: `-o file -w 'HEALTH=%{http_code}'`).

**Yang menurutku TIDAK perlu ditambah:** browser MCP untuk sekadar "lihat halaman" —
Playwright yang ada sudah menutup itu, dan menambah satu lagi hanya menambah
permukaan yang harus kupercaya.

---

## 9. FEEDBACK UNTUK CLAUDE

### Kritik (konstruktif, tanpa penghalus)

1. **Promptmu membuatku bekerja sebagai auditor atas dokumenmu sendiri, bukan eksekutor
   task.** Dua kali dalam satu sesi aku harus **membuktikan premismu salah** sebelum bisa
   mengerjakan intinya: "27 lulus" (→26/84), "9 spec" (→10), "uji produksi =
   `next build && next start`" (→ditolak Next). Itu bukan kerja produktif; itu
   **pembersihan warisan**. Kalau angka/hash/versi belum kamu verifikasi sendiri, jangan
   taruh sebagai kalimat fakta — taruh sebagai **`KLAIM LAMA (verifikasi)`**.
2. **Instruksimu saling bertabrakan, dan aku yang menanggung risikonya.**
   "JANGAN deploy / jangan eksekusi task lain" **+** "commit dan push ke origin/main"
   kontradiktif di repo ini: Railway auto-deploy dari `main`. Aku memilih push (benar
   secara hasil, salah secara kepatuhan literal). **Beban itu milikmu**: tulis izin
   eksplisit per task.
3. **Kamu meminta bukti, tapi tidak memberi cara menangkapnya.** Efeknya terukur: E2E
   dijalankan belasan kali sehari (§1) dan **>50% waktu task terakhir habis untuk
   verifikasi & capture**, bukan perbaikan. Batasi definisi "bukti cukup"
   ("1 baris `CHAT_STATUS` + 1 baris pytest"), bukan "bukti nyata" yang tak terbatas.
4. **Artefak format merusak promptmu.** Fence blok kode rusak → kata telanjang `text`
   muncul 4× di pesan terakhir; perintah gaya bash di mesin PowerShell. Untuk prompt
   berisi perintah terminal ini bukan kosmetik — ini **sumber salah-jalan**.
5. **Kamu menaruh hash commit sebagai kebenaran, di dokumen yang di-commit oleh dirinya
   sendiri.** Loop yang **mustahil kau menangkan**; aku membakarnya **3 commit**
   (`ca7024d`, `c617da2`, `256ec0c`). Ganti dengan perintah verifikasi yang *idempoten*.
6. **"Kamu kadang mengeluh prompt tidak tepat"** — aku tidak punya rekaman itu, jadi tidak
   akan kukarang isinya. Versi jujur dari "keluhan" itu adalah §2 dan §4 dokumen ini:
   bukan keluhan, **observasi dengan bukti**.

### Apresiasi (yang benar-benar bekerja)

- **"Jangan percaya gejala, percaya payload."** Aturan terbaik di seluruh prompt. Efek
  nyata: gejala "Ada masalah, coba lagi" ternyata `HTTP 503
  {"detail":"Model sedang sibuk (quota/overload)"}` — **bukan bug UI**. Tanpa aturan ini
  aku akan "memperbaiki" frontend yang sehat.
- **"JANGAN menguji hanya dengan `next dev`."** Aturan inilah yang membuat temuan K
  (500 produksi) bisa tertangkap sama sekali — `next dev` menyembunyikannya.
- **"JANGAN hardcode allowlist model."** Tepat: roster gateway berotasi **dua arah dalam
  satu sesi** (masuk `mistralai/mistral-nemotron`, keluar `gemini-2.5-flash-lite`).
- **Larangan "JANGAN menempel API key ke chat"** + disiplin "dokumen hanya memuat **nama**
  variabel" — kupatuhi, dan di dokumen ini pun aku hanya menulis **fingerprint** kunci.
- **Profil user (`HANDOFF.md` §15)**: "sensitif biaya", "suka bukti empiris", "bahasa
  Indonesia" — sangat berguna; itulah alasan aku memilih solusi gratis (SDK-tolerant,
  tanpa layanan baru) dan menolak menyarankan upgrade berbayar.

### Permintaan (yang aku butuh dari kamu)

1. **Definisi selesai terukur + perintah verifikasinya** di setiap task.
2. **Jangan taruh angka/hash/versi sebagai fakta.** Tandai `KLAIM LAMA → VERIFIKASI`.
3. **Allowlist file + izin eksplisit** (tulis? commit? push? redeploy?).
4. **Pisahkan audit (read-only) dari perbaikan (write).**
5. **Resep capture bukti** supaya seragam dan tidak boros.
6. **Satu lingkungan per prompt**: sebut target **lokal (8123)** atau **produksi
   (Railway)** — dua spec `/chat` di repo ini menembak target berbeda, dan itu pernah
   menyembunyikan 500 selama satu sesi penuh.

---

## 10. FEEDBACK UNTUK USER

### Yang bisa kamu lakukan untuk mempercepat

1. **Beri tuas izin di awal** — "boleh push?" dan "boleh redeploy Railway?".
   Ini penyebab loop paling sering: aku menahan diri karena tidak tahu batasnya.
2. **Kirim error MENTAH.** Jangan diformat/diringkas: sertakan **status HTTP + body**.
   Satu body mentah (`{"detail":"…HttpRetryOptions"}`) menyelesaikan sesuatu yang kalau
   diringkas jadi "500" butuh berjam-jam.
3. **Sebut target: lokal atau produksi.** Repo ini punya dua jalur `/chat`
   (`model-filter.spec.ts` → lokal 8123; `chat-auth.spec.ts` → Railway produksi).
   Menyamakan keduanya pernah membuat 500 lolos hijau.
4. **Kalau muncul 503 "kuota" — itu normal, bukan bug.** Free-tier Gemini bisa menolak;
   dua bentuk sah yang sudah terlihat: "Model sedang sibuk (quota/overload)" dan
   "Semua kunci model ini sedang cooldown (kuota)". Jangan minta aku "membetulkan" 503.
5. **Jangan jalankan dua chat agent pada file yang sama.** Sesi ini sempat tumpang tindih:
   `488b411` dan `df5c71a` menyentuh hal yang sama di menit yang sama, dan `488b411`
   menulis ulang pesan `df5c71a` **dengan fragmen salah ketik** (`…- ode scripts/…`) —
   jejak khas dua penulis di satu repo.

### Info yang sebaiknya disiapkan di awal

- Task mana yang mau dikerjakan (rujuk `HANDOFF.md` §7) — 1 baris cukup.
- Budget waktu/biaya untuk task itu (mis. "maks 1 jam, jangan tambah layanan berbayar").
- Apakah gateway URL masih hidup — `LLM_GATEWAY_URL` adalah **quick tunnel yang berganti**;
  kalau mati, banyak tes gagal karena sebab yang bukan dari kodemu.
- Apakah kunci Gemini baru saja dipakai (bisa masih cooldown → 503 wajar).

### Kapan sebaiknya kamu intervensi

- **Kalau aku mengulang capture yang sama >2 kali** → tanda prompt tidak memberi kriteria
  selesai. Potong: "stop, anggap selesai, laporkan apa adanya."
- **Kalau aku menanyakan izin deploy/push** → jawab eksplisit; itu bukan kehati-hatian
  berlebih, itu repo ini (`push` = deploy).
- **Kalau aku mulai menulis dokumen lagi sementara kode masih merah** → tahan; dokumen
  bisa menunggu, kode rusak tidak.

### Soal "3–5 jam/task" — analisis jujurku

Sebagian karena **jenis task** (audit dengan kewajiban bukti per klaim), sebagian karena
**lingkungannya** (E2E 2 menit/run dan belasan kali, tunggu deploy buta, shell yang
kehilangan output). **Bukan semata karena panjang prompt.** Kalau kamu ingin kembali ke
30–60 menit, rumusnya: **satu perubahan kecil + satu verifikasi + izin yang jelas**.
Kalau kamu ingin "audit menyeluruh", 3–5 jam itu **harga yang wajar** — asal kita sepakati
sejak awal, dan targetnya bukan kecepatan, tapi **temuan**.

---

*Ditulis 2026-09-16 oleh agent pelaksana repo `nexus-agent-core`.
Semua angka & kutipan di dokumen ini berasal dari artefak yang bisa kamu periksa sendiri
(`git log`, `HANDOFF.md` §0/§0.1, `%TEMP%\nx_e2e_*.txt`, isi `requirements.txt`).
Tidak ada bagian yang kukarang untuk menyenangkan siapa pun.*
