# BUGFIX 3 KRITIS — hasil test browser user (2026-10-06)

Tiga bug dilaporkan dari test browser manual. Dokumen ini mencatat **akar
masalah** (bukan gejala), **perbaikan**, dan **bukti** untuk tiap bug.

Konteks yang penting: ketiga bug punya pola yang sama dengan bug-bug
sebelumnya di proyek ini — **"proteksi tampak ada padahal mati"**: kode ada,
tes hijau, tapi perilaku produksi tidak sesuai karena (a) tes men-monkeypatch
justru bagian yang rusak, atau (b) kartu hidup di cache klien yang tidak
persist.

---

## Bug #1 — prompt "kirim ke telegram chat 123 pesan halo" tidak memunculkan approval card

### Akar masalah (terkonfirmasi)
`textual_tool_handlers._missing_provider(tool)` memanggil
`credential_forms.check_credential(provider, "")` dengan **email KOSONG**.

Vault disimpan **per-user**, jadi cek dengan email kosong **selalu** melaporkan
"kredensial belum ada" — untuk SETIAP user, termasuk user yang sudah menyimpan
kredensialnya. Akibatnya TELEGRAM/SLACK/EMAIL/SHEETS **selalu** jatuh ke
`requires_credential` (form) dan approval card **TIDAK PERNAH** tampil.

Tes lama menyembunyikannya: `test_execute_textual_tool_telegram_minta_persetujuan`
dan 5 tes lain selalu men-`monkeypatch.setattr(..., "_missing_provider", lambda t: "")`
— jadi jalur yang rusak tidak pernah dieksekusi.

### Perbaikan
`_missing_provider(tool, user_email="")` — email user sebenarnya diteruskan dari
`execute_textual_tool`. Bila email kosong, fungsi sengaja **tidak** menyimpulkan
"hilang" (lebih baik menampilkan approval daripada memaksa user mengisi ulang).

### Bukti mentah
```
$ python _bug1_repro.py
=== 0. PARSER ===
raw model text : 'Baik, saya kirim ke Telegram sekarang.\n[TELEGRAM: chat_id=123 pesan="halo"]'
parsed calls   : [{'tool': 'TELEGRAM', 'args': {'chat_id': '123', 'pesan': 'halo'}, ...}]

=== 1. USER PUNYA kredensial telegram ===
email dipakai saat cek -> ['user@example.com']
status -> requires_approval            # <-- approval card muncul
OK: approval card muncul (requires_approval + approval_token).

=== 2. USER BELUM punya kredensial telegram ===
status -> requires_credential | provider -> telegram
OK: urutan benar - kredensial dicek dulu sebelum approval.
```
Sebelum perbaikan, skenario 1 menghasilkan `requires_credential` dengan
`email dipakai saat cek -> ['']`.

### Tes regresi
`tests/test_tool_injection.py::test_missing_provider_pakai_email_user_bukan_kosong`
— TIDAK men-monkeypatch `_missing_provider`; ia memverifikasi email yang
benar-benar diterima `check_credential`.

---

## Bug #2 — agen bertanya "berapa chat_id?" alih-alih membangun workflow

### Akar masalah
System prompt (`api_server._AGENT_SYSTEM`, blok MODE DISCOVERY) memperlakukan
**"intensi ambigu"** dan **"satu nilai teknis kosong"** sebagai hal yang sama:
- poin 2: *"tanyakan bila belum ada, karena tanpa itu workflow tidak bisa dijalankan"*
- poin 4: *"`chat_id`/`url`/`channel` TIDAK boleh dikarang — kalau belum disebut, tanya dulu"*

Jadi untuk permintaan yang alurnya sudah jelas (mis. multi-node) tapi satu
nilai teknis belum disebut, agen menahan diri dan bertanya — workflow tidak
pernah dibangun.

### Perbaikan
Blok baru **ATURAN BUILD WORKFLOW (WAJIB)**:
- (a) alur sudah jelas (≥2 node/langkah, atau pemicu+aksi) → **LANGSUNG bangun**;
- (b) nilai teknis yang belum disebut → isi **placeholder** `{{chat_id}}`,
  `{{url}}`, `{{channel}}`, `{{spreadsheet_id}}` (jangan tanya);
- (c) tanya **hanya** bila INTENSI ambigu;
- (d) jangan mengulang pertanyaan; "langsung buat"/"terserah" → bangun sekarang;
- (e) rangkum + sebutkan placeholder mana yang perlu diisi di kanvas.

Poin 2 & 4 diubah agar konsisten dengan aturan ini.

### Tes regresi
`tests/test_discovery_agent.py::test_prompt_membangun_langsung_dengan_placeholder`
— memastikan aturan + placeholder tetap ada di prompt.

---

## Bug #3 — vault (form kredensial) hilang setelah navigasi/refresh

### Akar masalah
Kartu (form kredensial / approval / oauth) **hanya** hidup di cache klien
(TanStack, ditandai `_localId`) — **tidak pernah** dipersist. Setelah reload,
`GET /messages/{session_id}` hanya mengembalikan `{role, content}` dari
`chat_messages`, jadi kartunya tidak bisa dibangun ulang → hilang.

"Supabase tetap ada" karena konfirmasi Supabase biasanya berupa **teks biasa**
(dipersist sebagai pesan assistant), bukan kartu — jadi terlihat tidak konsisten.

Skema `chat_messages`: `(id, session_id, role, content, created_at, client_request_id)`
— tidak ada kolom `type`/`meta`.

### Perbaikan (tanpa migration)
Kartu dipersist sebagai baris **`role="system"`** berisi envelope JSON
`{__katalir_card, ...}`. Baris ini aman karena:
- `load_history` hanya mengirim role user/assistant → **bukan** konteks LLM;
- `get_last_assistant_reply` memfilter role=assistant → **bukan** "balasan";
- index unik `client_request_id` bersifat **partial** (`role='user'`) → tak bentrok.

Sisi klien: `fetchMessages` (useChat.ts) mendekode envelope menjadi
`ChatMessage` bertipe dengan `_localId` stabil. Karena `messagesData` memakai
query key yang sama dengan `activeKey`, kartu ikut lolos filter `overlay` di
`ChatApp` — **tanpa cabang render baru**.

### Bukti
```
$ pytest tests/test_card_persistence.py -q
......                                                                   [100%]
6 passed
```
Mencakup: bentuk baris + envelope, dedup by req_id, tidak melempar saat DB
down, endpoint mempersist kartu approval & kredensial, dan `load_history`
mengabaikan baris kartu.

---

## Verifikasi

| Item | Perintah | Hasil |
|------|----------|-------|
| Suite penuh | `pytest tests/ -q` | **714 passed**, 1 warning (sebelumnya 706) |
| Bug #1 repro | `python _bug1_repro.py` | 2 skenario lulus |
| Tes kartu (Bug #3) | `pytest tests/test_card_persistence.py -q` | 6 passed |
| Type-check FE | `tsc --noEmit` (node 24 sistem) | exit 0 |
| Decoder kartu (satuan) | `playwright test -c playwright.unit.config.ts` | **7 passed** |
| Kartu bertahan setelah refresh | `playwright test -c playwright.approval.config.ts tests/card-persistence.spec.ts` | **2 passed** (build produksi lokal) |
| Suite kartu (build produksi) | `playwright test -c playwright.approval.config.ts` | **15 passed** (13 approval + 2 persistensi) |
| Situs live | idem, `E2E_BASE_URL=https://proyek-agent.pages.dev` | **GAGAL 1/2** — lihat di bawah |

---

## Laporan lanjutan (5 Okt 2026, sesi kedua)

Sesi pertama menutup dengan dua hal yang **belum** dibuktikan. Keduanya
dikerjakan di sesi ini.

### 1. Blocker build: akar masalah akhirnya ditemukan (bukan `EPERM`)

Blocker yang tercatat sebagai "macet di `Creating an optimized production
build`" ternyata **dua sebab berbeda**, dan keduanya lingkungan:

**Sebab A — `next lint` menggantung.** Build penuh tanpa `--no-lint` berhenti
di `buildStage: "compile"` selama >9 menit tanpa menulis satu berkas pun
(terverifikasi: `.next` hanya berisi 7 berkas metadata). Dengan
`--no-lint`, kompilasi selesai dalam ~60 detik dan menghasilkan 266 berkas.
Di sinilah `EPERM: open 'out\404.html'` yang dulu terlihat sebenarnya muncul —
sebagai gejala sekunder, bukan sebab.

**Sebab B — shim safe-delete WorkBuddy, terbukti dari pesan galatnya:**

```
Error: [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
  {"count":178,"threshold":50,"scope":"turn",
   "targets":["...\\.next\\export"],"targetCount":1}
    at checkBulkDeleteGuard (.../node-safe-delete-shim.cjs:239:19)
    at Object.wrappedPromisesRm [as rm] (...:829:15)
```

Next.js menghapus `.next/export` (176–178 berkas) di langkah pembersihan
terakhir, sedangkan lingkungan ini membatasi **50 penghapusan per giliran tool**.
Bukti bahwa ini murni langkah kosmetik, bukan kegagalan build: baris
`✓ Generating static pages (21/21)` **sudah tercetak** sebelum galat muncul.

Karena itu pula memindahkan `.next` lebih dulu TIDAK menolong (sudah dicoba):
build dari `.next` yang benar-benar kosong pun tetap macet di Sebab A, lalu
menabrak Sebab B begitu kompilasi berhasil.

**Solusi yang dipakai** — pisahkan tahapnya dan salin sendiri hasilnya:

```bash
cd nexus-frontend
npx next build --no-lint --experimental-build-mode generate   # compile + generate
node scripts/export-out.mjs --clean                          # .next/server/app -> out/
```

`scripts/export-out.mjs` mereplikasi langkah yang gagal: menyalin HTML halaman
dari `.next/server/app/` ke `out/` (hanya `*.html`; `.meta`/`.rsc`/`.js`
artefak server TIDAK ikut), `_not-found.html` → `404.html`, `.next/static` →
`out/_next/static`, dan `public/`. Hasil: **`out/` 103 berkas**.

Bukti build ini setara produksi: chunk `page-27addee031fc38d6.js` (70.277 B)
memuat `__katalir_card`, `srv-card`, dan `credential_form` — tiga penanda fix
Bug #3.

### 2. Kartu kredensial SETELAH refresh — sekarang dibuktikan di browser

`tests/card-persistence.spec.ts` menguji rantai yang persis dipakai user:
kirim prompt → `requires_credential` → **refresh halaman** → kartu harus
muncul lagi **murni dari jawaban `GET /messages`** (bukan sisa cache).

```
2 passed (12.7s)
  ✓ kartu kredensial muncul kembali setelah refresh
  ✓ kontra-regresi: tanpa baris kartu di server, kartu memang TIDAK muncul
```

Tes kedua sengaja ada supaya tes pertama terbukti **tajam**: bila server tidak
mengembalikan baris kartu (perilaku kode lama), kartunya hilang. Kalau tes itu
justru menampilkan kartu, berarti kartu masih hidup di cache klien dan tes
pertama tidak membuktikan apa pun.

Diperkuat `tests/card-persistence.unit.spec.ts` — **7 tes** atas
`decodePersistedCard` (pemetaan `display_name`/`resume_token`/`approval_token`,
`_localId` wajib terisi, baris biasa tidak diubah, JSON rusak tidak melempar).

### 3. Situs live BELUM ter-deploy — ini gap yang masih terbuka

Dijalankan spec yang sama terhadap `https://proyek-agent.pages.dev`: **1/2
gagal**. Penyebabnya diverifikasi langsung pada bundel yang disajikan:

```
live chunk: page-6eb4f85538eda943.js (69.193 B)
__katalir_card     0
srv-card           0
approval-card      1
```

Chunk live **tidak memuat** sentinel maupun decoder kartu, artinya versi yang
di-deploy masih pra-perbaikan. Yang sudah live: `approval-card` (fix 5 Okt
sebelumnya). **Fix Bug #3 belum ter-deploy.**

Untuk menutupnya, `out/` hasil sesi ini harus di-deploy ke Cloudflare Pages,
lalu spec dijalankan ulang dengan `E2E_BASE_URL`. Perintahnya:

```bash
cd nexus-frontend
E2E_BASE_URL=https://proyek-agent.pages.dev E2E_SHOT_PREFIX=card-persistence-live \
  npx playwright test -c playwright.approval.config.ts tests/card-persistence.spec.ts
```

### Yang BELUM terverifikasi (jujur)

- **Situs live masih gagal 1/2** (bukti chunk di atas). Ini bukan bug kode —
  build lokal dari source yang sama lulus 15/15 — melainkan deploy yang belum
  dijalankan.
- **Belum diuji terhadap backend produksi dengan sesi nyata.** Seluruh spec
  memakai `page.route` untuk men-stub jawaban backend, jadi yang dibuktikan
  adalah rantai render + kontrak data, bukan integrasi end-to-end dengan
  Supabase hidup. Refresh token `.autonomous_session.json` masih dicabut
  (catatan sesi sebelumnya).
- **Bug #2 belum diuji terhadap LLM sungguhan** (butuh kredensial gateway yang
  masih hidup). Yang dibuktikan: aturan + placeholder ada di prompt, dan
  tes regresi mencegah aturannya hilang saat prompt diedit.
