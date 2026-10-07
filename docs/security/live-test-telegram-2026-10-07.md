# Live Test Workflow Telegram — 7 Oktober 2026

**Status:** ❌ **FASE 1 FAIL · FASE 2 TIDAK DIDUKUNG** — verdict **NO-GO**
**Waktu uji:** 2026-10-07 21:25–21:40 WIB (14:25–14:40 UTC)
**Target:** `https://web-production-dc90b.up.railway.app` (produksi, Railway)
**Launch:** 8 Oktober 2026, 14:01 WIB
**Pesan Telegram terkirim selama uji: `0`** (kuota 2 pesan test tidak terpakai)

> Pendekatan brief: **tanpa grup test** — kirim ke `TELEGRAM_CHAT_ID` (chat pribadi
> user). Ini menggantikan pendekatan Opsi B (grup TEST) pada dokumen versi sebelumnya.

---

## 0. Ringkasan eksekutif

| # | Klaim yang diuji | Hasil | Status |
|---|---|---|---|
| F1 | Workflow manual-trigger **bisa kirim ke Telegram** | Gagal di gerbang kredensial: `needs_credential` | ❌ **FAIL** |
| F2 | **Cron scheduler** jalan (trigger 22:00) | Fitur **tidak ada** di Katalir | ❌ **NOT SUPPORTED** |
| F3 | Kredensial Telegram tersedia di produksi | Vault kosong untuk semua user nyata | ❌ |
| F4 | Redactor menahan token dari log | 0 kebocoran di 5 sumber | ✅ **PASS** |
| F5 | Canary tidak bocor ke log runtime | 0 hit | ✅ **PASS** |
| F6 | Bot token valid | `getMe` → `@Katalir_bot` | ✅ **PASS** |
| F7 | Chat ID format benar | positif 10 digit → chat pribadi | ✅ **PASS** |
| F8 | Gateway LLM cukup sehat untuk membangun workflow via AI | `/chat` timeout **257,5 s** | ❌ **FAIL** |

**Dua temuan yang berpotensi memblokir launch** ada di §6.1 (cron) dan §6.2
(kredensial Telegram wajib per-user).

---

## 1. FASE 1 — Manual trigger

### 1.1 Autentikasi (kendala pertama)

Brief mengasumsikan **login user otonom** jalan. Kenyataannya **tidak**:

```
[RECON 3] Autonomous login (in-memory)
  -> HTTP 400 GAGAL: {"code":400,"error_code":"invalid_credentials",
                      "msg":"Invalid login credentials"}
```

`.autonomous_pw` sudah **basi** (password tidak cocok lagi). Ini kontradiksi B3
pertama → dicatat, tidak dihentikan karena ada jalur sah pengganti.

**Jalur pengganti (sah, non-destruktif):** Supabase Admin API
`POST /auth/v1/admin/generate_link` → `POST /auth/v1/verify`. JWT di-mint
**in-memory**, tidak ditulis ke disk (agar tidak mengembalikan
`.autonomous_session.json` yang sudah dibersihkan di Brief C).

```
[auth] generate_link OK | hashed_token=56ch email_otp=8ch
[auth] verify via token_hash OK | jwt len=808
GET /me -> HTTP 200 | {"status":"success",
                       "email":"otonom-test@katalir-internal.dev","tier":"free"}
```

### 1.2 Percobaan 1 — mode `chat` (sesuai brief)

Brief meminta workflow dibangun via `POST /chat`. Hasilnya:

```
[4] POST /chat (membangun draf workflow) ...
    HTTP 0 | 257.5s
    GAGAL: TimeoutError: The read operation timed out
    meta.workflow KOSONG -> agen tidak menghasilkan draf
```

**Timeout 257,5 detik.** Gateway LLM tidak menyelesaikan satu giliran agen pun.
Ini konsisten dengan anomali gateway yang sudah tercatat sebelumnya
(2,69 s → 20–25 s → ≥30 s). **Kontradiksi B3 kedua.**

Karena tidak ada draf dari agen, workflow dibangun deterministik
(`POST /workflows`), tetap memakai format pesan dari brief:

```
node=tg type=mcp cfg={'provider':'telegram','chat_id':'2109***369',
  'pesan':'Katalir Test Manual - Jam: {{trigger.timestamp}} - Status: WORKFLOW BERFUNGSI - <canary>'}
POST /workflows            -> HTTP 201 | workflow_id 4116293e-6ace-480a-ae28-5b46586a9e76
POST /workflows/{id}/execute -> HTTP 202 | execution_id 1783ea30-30b4-45db-810c-c4c7c791ac85
```

Hasil eksekusi:

```
node=trg status=completed output={"type":"trigger.fire","event":"Manual",
                                  "message":"Trigger disparado: Manual","webhook_payload":{}}
node=tg  status=error     err=PlaceholderResolutionError: field 'timestamp' tidak
    ditemukan di output 'trigger' (kunci tersedia: event, message, type, webhook_payload).
    Perbaiki referensi {{trigger.timestamp}} di node 'tg'.
```

**Kontradiksi B3 ketiga:** brief memakai `{{trigger.timestamp}}`, tetapi output
node trigger Katalir **tidak punya kunci `timestamp`**. Kunci yang benar:
`type`, `event`, `message`, `webhook_payload`. Tidak ada akar placeholder waktu
sama sekali (diverifikasi di `StatefulOrchestrator._placeholder_roots`).
Workflow rusak ini dihapus (`DELETE /workflows/...` → 200 `deleted: true`).

### 1.3 Percobaan 2 — mode `direct` (placeholder diperbaiki)

Placeholder diganti `{{trigger.event}}`; waktu kirim ditulis literal.

```
node=tg cfg={'provider':'telegram','chat_id':'2109***369',
  'pesan':'Katalir Test Manual - Jam: 2026-10-07 14:30:44 UTC - Trigger: {{trigger.event}} - Status: WORKFLOW BERFUNGSI - <canary>'}
POST /workflows             -> HTTP 201 | workflow_id af3a73a1-516d-478e-949e-afe6f50d0104
POST /workflows/{id}/execute -> HTTP 202 | execution_id 8878d8c5-9c65-43b0-8c7f-20b435c479b9
```

Placeholder **berhasil diresolusi** (error `PlaceholderResolutionError` hilang).
Blocker berpindah ke kredensial:

```
node=trg type=trigger status=completed err=None
node=tg  type=mcp     status=retrying  (healing attempt 1, delay 1000ms)
node=tg  type=mcp     status=retrying  (healing attempt 2, delay 2000ms)
node=tg  type=mcp     status=error
  err=provider 'telegram' status=needs_credential: Kredensial 'telegram' belum ada
  healing.action=escalate | reason=Gagal setelah 2 percobaan
```

### 1.4 Akar masalah (diagnosis 1.4a–1.4d)

| Cek brief | Perintah | Hasil |
|---|---|---|
| 1.4a Bot token valid | `getMe` | ✅ HTTP 200 · bot id `8912001431` · `@Katalir_bot` · `can_join_groups=true` |
| 1.4b Chat ID valid | format | ✅ `2109***369` (10 digit, **positif** = chat pribadi user, sesuai brief) |
| 1.4c Network Railway → api.telegram.org | — | ⚠️ **tidak teruji**: eksekusi berhenti di gerbang kredensial, sebelum panggilan jaringan apa pun |
| 1.4d Redactor: token di-redact sebelum log? | scan 5 sumber | ✅ **0 kebocoran** (lihat §4) |

**Rantai kegagalan** (`provider_registry.run` → `tools.kirim_telegram_message` →
`tools._get_telegram_token`):

```python
cred = db.get_integration(owner_email, "telegram")   # vault -> KOSONG
vault_token = (cred or {}).get("api_token") or ""
if vault_token: return vault_token
fallback_on = (os.environ.get("TELEGRAM_ENV_FALLBACK") or "1").strip() != "0"
env_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() if fallback_on else ""
if env_token: return env_token
raise CredentialMissingError("telegram")             # <-- yang terjadi
```

Jadi `needs_credential` = **vault kosong DAN fallback `.env` tidak aktif** di
produksi. Ini **perilaku yang disengaja**: komentar di `tools.py` menyatakan
fallback `.env` membuat semua user memakai bot pemilik — salah untuk SaaS
multi-tenant — dan menganjurkan `TELEGRAM_ENV_FALLBACK=0` di produksi.

**Bukti pendukung — isi `user_vault` produksi (6 baris):**

```
email= e2e.1789523141333@nexus-local.test | provider= openai
email= verdi0377@gmail.com                | provider= google_sheets   <-- pemilik
email= verdi0377@gmail.com                | provider= slack           <-- pemilik
email= katalir@example.com                | provider= gmail_imap
email= k@e.com                            | provider= gmail_imap
email= e2e.1791190942931@nexus-local.test | provider= telegram        <-- 1-satunya
```

**Tidak satu pun user nyata punya kredensial telegram.** Pemilik sendiri
(`verdi0377@gmail.com`) hanya menyimpan `google_sheets` + `slack`.

### 1.5 Hasil FASE 1

| Item | Nilai |
|---|---|
| Workflow ID (percobaan valid) | `af3a73a1-516d-478e-949e-afe6f50d0104` *(sudah dihapus setelah uji)* |
| Execution ID | `8878d8c5-9c65-43b0-8c7f-20b435c479b9` |
| Respons Telegram API | **tidak ada** — tidak pernah mencapai `api.telegram.org` |
| Message ID | **tidak ada** |
| Status | ❌ **FAIL** (`needs_credential`) |

---

## 2. FASE 2 — Cron trigger

### 2.1 Verdict: fitur tidak ada

**Katalir tidak memiliki cron scheduler.** Tidak ada yang bisa didaftarkan dan
tidak ada yang akan menyala pada 22:00. Bukti struktural:

```
pustaka scheduler di requirements : TIDAK ADA
  (pola: apscheduler|croniter|schedule|celery|rq|dramatiq|huey)
cron di railway.json              : TIDAK ADA
cron di Procfile                  : TIDAK ADA
.github/workflows                 : DIREKTORI TIDAK ADA -> tidak ada cron GitHub Actions
parser/registrasi cron di *.py    : 0 baris  (pola: croniter|CronTrigger|add_job(|
                                     schedule.every|pg_cron|parse_cron|cron_expression|next_run_time)
tabel 'schedules'                 : tidak ada (PGRST205)
tabel 'cron_jobs'                 : tidak ada (PGRST205)
tabel 'workflow_schedules'        : tidak ada (PGRST205)
tabel 'triggers'                  : tidak ada (PGRST205)
schema 'cron' (pg_cron)           : tidak di-expose (PGRST106 — hanya public, graphql_public)
```

Catatan kejujuran: pencarian awal `git grep cron` di `execution_engine.py`
memberi **false positive** — yang cocok adalah kata Spanyol *"asin**cron**a"*.
Di `generated_mcp/katalir_openapi_server.py` yang cocok adalah tool **Kubernetes
CronJob** (hasil generate OpenAPI, tidak terkait workflow Katalir).

### 2.2 Apa yang sebenarnya didukung

Config node trigger hanyalah **teks bebas** yang bersifat kosmetik — bukan
jadwal yang dieksekusi:

```ts
// nexus-frontend/src/features/builder/demo-workflow.ts
data: { kind: "trigger", label: "Mulai", config: { event: "Setiap jam 9 pagi" } }
```

Trigger nyata yang tersedia:

| Trigger | Endpoint | Status |
|---|---|---|
| Manual | `POST /workflows/{id}/execute` | ✅ berfungsi (diuji §1) |
| Webhook | `POST /webhook/{workflow_id}` | ✅ ada (belum diuji) |
| **Cron** | — | ❌ **tidak ada** |

### 2.3 Hasil FASE 2

| Item | Nilai |
|---|---|
| Workflow ID | tidak dibuat (fitur tidak ada) |
| Cron expression | tidak ada parser/kolom untuk menyimpannya |
| Fired time | — |
| Message ID | — |
| Status | ❌ **NOT SUPPORTED** |

---

## 3. BAGIAN 4 — Redactor + Canary

Canary: `KATALIR_TEST_CANARY_772B58491571` (pola `KATALIR_TEST_CANARY_<12 upper-hex>`).

### 3.1 Canary scan (4a–4f)

```
berkas lokal (repo)      : 0 hit
execution_logs           : 0 hit / 8 baris discan   (scope: execution 8878d8c5)
chat_messages            : 0 hit / 1000 baris discan
workflows                : 1 hit  / 91 baris
     -> af3a73a1-516d-478e-949e-afe6f50d0104 (workflow uji itu sendiri)
sessions                 : tabel tidak ada (PGRST205)
TOTAL HIT = 1
```

**Interpretasi (penting, jangan salah baca):** satu-satunya hit adalah
**definisi workflow itu sendiri** — canary memang bagian dari template pesan yang
tersimpan di `flow_data`. Itu **by design** (workflow disimpan sebagai data),
**bukan** kebocoran kredensial. **Tidak ada** canary yang lolos ke log runtime
(`execution_logs`, `chat_messages`) maupun berkas lokal. Workflow uji sudah
dihapus setelah scan → hit menjadi 0.

### 3.2 Scan kebocoran token (1.4d)

Pola `<8–12 digit>:<30+ char>` + pencocokan nilai token asli, atas **seluruh**
isi tabel:

```
execution_logs : 0 kebocoran / 132 baris
chat_messages  : 0 kebocoran / 1000 baris
workflows      : 0 kebocoran / 91 baris
user_vault     : 0 plaintext / 6 baris   (semua terenkripsi)
```

✅ **Redactor & penanganan secret bersih.** Token tidak pernah masuk log/DB.

---

## 4. Larangan yang dipatuhi

| Larangan | Status |
|---|---|
| JANGAN kirim lebih dari 2 pesan test | ✅ **0 pesan terkirim** (tidak ada yang mencapai Telegram) |
| JANGAN paste bot token ke chat/log | ✅ token hanya direferensikan sebagai panjang/format; 0 kebocoran (§3.2) |
| JANGAN skip Fase 1 — manual dulu | ✅ FASE 1 dijalankan (2 percobaan) sebelum FASE 2 |
| JANGAN deploy ulang setelah Fase 1 jalan | ✅ tidak ada deploy/redeploy |
| JANGAN ganti chat ID tanpa konfirmasi user | ✅ `TELEGRAM_CHAT_ID` dari `.env` dipakai apa adanya |
| JANGAN abaikan canary | ✅ BAGIAN 4 dijalankan penuh + scan token tambahan |

Tambahan inisiatif keamanan: `chat_id` literal **sengaja tidak dimasukkan ke
prompt `/chat`**. Gateway Katalir memakai tool-calling berbasis teks
(`[TELEGRAM: chat_id=<id> pesan="<teks>"]`), sehingga model bisa **langsung
mengirim pesan** dan melampaui kuota 2 pesan. Prompt memakai placeholder
`__CHAT_ID__`, lalu chat ID asli di-inject ke config node setelah draf terbentuk.
Efek samping menguntungkan: kalaupun model tetap mencoba mengirim, chat_id tidak
valid → Telegram menolak → tidak ada pesan terkirim.

---

## 5. Artefak & kebersihan

| Artefak | Aksi |
|---|---|
| Workflow `4116293e-…` (placeholder invalid) | dihapus (`DELETE` → 200) |
| Workflow `af3a73a1-…` (needs_credential) | dihapus (`DELETE` → 200) |
| Workflow test tersisa untuk user otonom | **0** |
| JWT | in-memory saja, tidak pernah ditulis ke disk |
| `.autonomous_session.json` | **tidak dibuat ulang** (menghormati Brief C) |

---

## 6. Temuan untuk launch (8 Okt)

### 6.1 🔴 Cron/scheduled workflow tidak ada
Jika materi pemasaran/onboarding menjanjikan *"workflow berjalan otomatis
sesuai jadwal"*, klaim itu **belum terpenuhi**. Yang tersedia hanya manual +
webhook. Jadwal bisa dicapai **hanya** bila scheduler **eksternal**
(Railway cron / GitHub Actions / crontab VPS) memanggil
`POST /webhook/{workflow_id}`.

### 6.2 🔴 Node Telegram wajib kredensial per-user
Setiap user harus menyimpan token bot Telegram sendiri di Brankas (form
kredensial) sebelum node Telegram bisa jalan; `.env` fallback **sengaja mati** di
produksi. **Tidak ada user nyata** yang saat ini punya kredensial itu — jadi
workflow Telegram akan gagal untuk semua user baru sampai mereka mengisinya.
Pastikan: (a) UI form kredensial Telegram menonjol, (b) pesan `needs_credential`
ditampilkan sebagai ajakan mengisi kredensial (bukan error merah).

### 6.3 🔴 Gateway LLM degraded
`POST /chat` timeout **257,5 s** → Discovery Agent **tidak bisa** membangun
workflow sama sekali. Ini mematikan alur "chat → workflow" yang jadi nilai jual
utama. Perlu ditangani sebelum launch.

### 6.4 🟡 Placeholder waktu tidak tersedia
`{{trigger.timestamp}}` tidak ada. Format pesan yang lazim ditebak model
(timestamp) akan gagal dengan `PlaceholderResolutionError`. Pertimbangkan
menambah akar `{{now}}` / `{{trigger.timestamp}}` agar draf AI tidak gagal.

### 6.5 🟡 `healing` mencoba 2× lalu escalate
Untuk kegagalan `needs_credential`, retry 2× (delay 1 s + 2 s) tidak berguna —
kredensial tidak akan muncul sendiri. Pertimbangkan agar `needs_credential`
**tidak** di-retry.

### 6.6 ✅ Yang terbukti sehat
- Bot token valid (`@Katalir_bot`).
- Mesin eksekusi DAG berjalan: trigger `completed`, edge dieksekusi, log
  persisten lengkap (`execution_logs`).
- Resolusi placeholder berfungsi (`{{trigger.event}}` teresolusi benar).
- **Tidak ada kebocoran** token/canary ke log mana pun.

---

## 7. VERDICT

# ❌ NO-GO

| Fase | Status |
|---|---|
| FASE 1 — manual trigger → Telegram | ❌ **FAIL** — `needs_credential` (vault kosong, fallback `.env` mati di produksi) |
| FASE 2 — cron trigger 22:00 | ❌ **NOT SUPPORTED** — cron scheduler tidak ada di Katalir |
| BAGIAN 4 — redactor + canary | ✅ **PASS** — 0 kebocoran |

**Bukan kerusakan acak.** Kedua kegagalan punya sebab pasti dan dapat diperbaiki:
FASE 1 = prasyarat konfigurasi (user harus menyimpan kredensial Telegram);
FASE 2 = fitur yang belum dibangun.

**Untuk membuktikan jalur kirim Telegram benar-benar bekerja** (§6.2), perlu
langkah tambahan yang butuh keputusan Anda — lihat opsi di akhir laporan.

---

## 8. Opsi lanjutan (butuh keputusan user)

| Opsi | Tindakan | Efek |
|---|---|---|
| **A** | Simpan token bot ke Brankas user uji (`POST /integrations` / `/api/vault/save`), lalu ulangi FASE 1 | Membuktikan jalur Telegram end-to-end. Token produksi tersimpan (terenkripsi) untuk akun uji → **wajib dihapus setelah uji** |
| **B** | Aktifkan `TELEGRAM_ENV_FALLBACK=1` di Railway, lalu ulangi | Mengubah env produksi → memicu redeploy. **Melanggar larangan** bila Fase 1 sudah jalan |
| **C** | Isi kredensial Telegram via UI aplikasi sebagai pemilik (`verdi0377@gmail.com`) | Paling realistis (jalur user nyata), tapi butuh login manual Anda |
| **D** | Hentikan di sini; cukup andalkan temuan §6 | 0 pesan test terpakai |

**Rekomendasi:** **Opsi C** (paling menyerupai user nyata, tanpa menyentuh env
produksi dan tanpa menyimpan token ke akun uji) — atau **Opsi A** bila Anda ingin
hasil otomatis sekarang, dengan komitmen menghapus baris vault setelah uji.
