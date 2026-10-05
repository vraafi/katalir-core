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
| Suite penuh | `pytest tests/ -q` | lihat laporan |
| Bug #1 repro | `python _bug1_repro.py` | 2 skenario lulus |
| Type-check FE | `tsc --noEmit` | exit 0 |
| Tes kartu | `pytest tests/test_card_persistence.py -q` | 6 passed |
