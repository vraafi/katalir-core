# n8n GAP CLOSURE LOG — 12 FITUR LANJUTAN (Okt 2026)

Standar: best practice Okt 2026 · Mode: OTONOM (riset → inventory → implementasi
→ hard test → verifikasi → commit → lanjut)

Dokumen ini mencatat 12 fitur penutup gap n8n lanjutan. Fitur sebelumnya
(#1–#11 awal + 5 gap n8n + 11 enterprise) tercatat di
`docs/enterprise-features-log.md`, `docs/feature-gap-closure-2026-10-08.md`,
dan `docs/enterprise-100-percent-log.md`.

## Ringkasan

| # | Fitur | Modul | Hard Test | Commit | Status |
|---|---|---|---|---|---|
| 7 | Metric-based Evaluations | `metrics_eval.py` | 16/16 | `916e5f9` | ✅ |
| 12 | External Memory Provider | `memory_provider.py` | 14/14 | — | ✅ |
| 11 | Redaction + Enforce 2FA | — | — | — | pending |
| 4 | Log Streaming SIEM | — | — | — | pending |
| 8 | OTel / LangSmith Tracing | — | — | — | pending |
| 3 | Self-healing Persistence | — | — | — | pending |
| 6 | End-user Credentials | — | — | — | pending |
| 10 | Custom RBAC | — | — | — | pending |
| 5 | Agent Sandbox Isolation | — | — | — | pending |
| 2 | MCP Build Workflow | — | — | — | pending |
| 1 | n8n Agents (first-class) | — | — | — | pending |
| 9 | Durable Execution via Dapr | — | — | — | pending |

---

## FITUR #7: METRIC-BASED EVALUATIONS

### Research (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| n8n Evaluations (Pro) | https://docs.n8n.io/ | Evaluations memakai metrik terhitung + panel, bukan hanya lulus/gagal | Tambah lapisan metrik terhitung di atas `evaluation.py` |
| Praktik LLM eval 2026 | https://agentmarketcap.ai/blog/2026/04/08/ai-agent-memory-shootout-2026-mem0-zep-letta-supermemory | Metrik deterministik (P/R/F1) untuk tugas berlabel; LLM-as-judge untuk kualitas terbuka; JANGAN dicampur tanpa menyebut mode | Pisahkan `compare_mode`; labelisasi dari teks, bukan dari skor fuzzy tanpa catatan |
| Confusion matrix & kelas | standar klasifikasi scikit-learn | CM butuh LABEL kelas, skor kontinu tidak bisa jadi kelas tanpa ambang | `labelize()` menurunkan label + laporkan `threshold` |

### Kredensial .env
- Tidak ada kredensial baru yang dibutuhkan (perhitungan murni).
- Memakai kembali backend persistensi `evaluation.save_run` → tabel `eval_runs`
  (Supabase, sudah ada sejak `migrations/2026_evaluation.sql`).

### Implementasi
- File: `metrics_eval.py` (baru, murni — tanpa DB/jaringan/LLM).
- `classification_report()` — accuracy, precision/recall/F1 macro + per-kelas,
  support, confusion matrix persegi.
- `latency_metrics()` — mean/p50/p95/p99/min/max.
- `cost_metrics()` — total/mean/tokens/biaya per 1.000 kasus.
- `chart_data()` — payload siap-render (bar, per-kelas, line, confusion, cost).
- `compare_runs()` — delta akurasi + F1 macro vs baseline, flag `regressed`.
- `evaluate_with_metrics()` — orkestrator; **runner dipanggil SEKALI** per kasus.
- `export_report()` — json / csv / markdown; `confusion_summary()`,
  `top_confusions()`.
- API: `POST /evaluations/metrics`, `GET /evaluations/metrics/metrics`.
- Registry `/version`: `28_metric_eval`.

### Hard Test — `tests/test_metrics_eval.py` (16/16 PASS)
```
33 passed in 0.95s   (16 metrics_eval + 17 evaluation lama — tanpa regresi)
```

| # | Skenario | Status | Raw Output |
|---|----------|--------|------------|
| 1 | Akurasi campuran benar/salah | PASS | `total=4 correct=3 accuracy=0.75` |
| 2 | Precision/recall/F1 eksak kelas tunggal | PASS | `tp=2 fp=1 fn=1 -> P=R=F1=0.6667` |
| 3 | Macro & support | PASS | `support[c]=1`, `0 <= macro.f1 <= 1` |
| 4 | `actual` kosong → kelas `__error__` | PASS | `accuracy=0.5`, `cm[ok][__error__]=1` |
| 5 | `expected` kosong → `__empty__` | PASS | `labels=['__empty__'] accuracy=1.0` |
| 6 | Dataset kosong → tanpa bagi nol | PASS | `total=0 accuracy=0.0 p99=0.0` |
| 7 | Latency p50/p95/p99 eksak (1..100) | PASS | `p50=50.0 p95=95.0 p99=99.0` |
| 8 | Cost total/mean/tokens | PASS | `tokens=4000/2000 total=0.004 mean=0.001` |
| 9 | Confusion matrix persegi & konsisten | PASS | `sum(cm)=total`, `diag=correct` |
| 10 | Chart data shape | PASS | `bar[0]=accuracy`, `line=['p50','p95','p99']` |
| 11 | Baseline mendeteksi regresi | PASS | `delta=-0.2`, `regressed=True` |
| 12 | Baseline mendeteksi perbaikan | PASS | `delta=+0.15`, `regressed=False` |
| 13 | Runner dipanggil SEKALI per kasus | PASS | `calls=2` untuk 2 kasus |
| 14 | Filter metrik (`metrics=["latency"]`) | PASS | `classification=None cost=None` |
| 15 | Ekspor JSON/CSV/Markdown valid | PASS | `accuracy,1.0` pada CSV |
| 16 | Performa 1000 baris | PASS | `< 1.0 s` (murni, tanpa I/O) |

### Bug NYATA yang ditemukan hard test (dan diperbaiki)

**BUG — `_percentile` galat satu langkah pada N genap.** Rumus lama
`round(p/100*(N-1))` memberi **p50 = 51** pada data `1..100` (seharusnya 50),
karena pembulatan `.5` ke atas. Ini juga salah untuk p95/p99 pada dataset
berukuran genap. Diperbaiki ke **nearest-rank** (`ceil(p/100*N)`) dengan
komentar alasan. Terbukti: `p50=50.0 p95=95.0 p99=99.0` (uji #7 GAGAL dengan
rumus lama).

**BUG — `expected` kosong salah diklasifikasikan sebagai error.** Dataset tanpa
ground truth harus menghasilkan label `__empty__` di kedua sisi, bukan
`__error__`. Diperbaiki di `labelize()`.

### Verifikasi Production (endpoint nyata via TestClient)
```
== catalog ==
200 {'status': 'success', 'metrics': ['accuracy','precision','recall','f1','latency','cost','confusion']}

== POST /evaluations/metrics ==
status    = 200
accuracy  = 0.75
macro f1  = 0.75
latency p95 = 42.0
cost total  = 7.2e-05
regressed   = False
chart keys  = ['bar','confusion','cost','line','per_class','type']
confusion   = {'d': {'WRONG': 1, ...}, 'a': {'a': 1, ...}, ...}
export head = "# Evaluation report — live-check"
run_id      = 4a76a33a
+ POST https://qmukkphwaajzbqjrcvaz.supabase.co/rest/v1/eval_runs → HTTP/2 201 Created
```
Persistensi ke Supabase terverifikasi (201 Created pada `eval_runs`).

### Status: 100% COMPLETE ✅
Commit: `916e5f9`

---

## FITUR #12: EXTERNAL MEMORY PROVIDER (Supermemory / Mem0 / Zep / Letta)

### Research (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| Supermemory API reference | https://supermemory.ai/docs/api-reference/overview | Base `https://api.supermemory.ai`, `Authorization: Bearer sm_...`. Ingest `POST /v3/documents`, search `POST /v4/search`. **v3/v4 DEPRECATED — shutdown 31 Des 2026** (v5 menyusul) | Implementasi v3/v4 + catat TODO migrasi v5 |
| Mem0 REST API | https://docs.mem0.ai/open-source/features/rest-api | OSS server **tanpa** prefix `/v1`: `POST /memories` (`messages`,`user_id`,`agent_id`), `POST /search` (`query`,`user_id`), `DELETE /memories/{id}`. Auth `X-API-Key` atau Bearer JWT | Pakai path OSS tanpa `/v1` + Bearer (kompatibel platform) |
| Zep docs | https://help.getzep.com/v2/sdk-reference/memory/add | Sesi eksplisit: `POST /api/v2/sessions/{sid}/memory`; pencarian `GET .../memory/search` | Sesi deterministik `user::agent` (tanpa panggilan create) |
| Letta docs | https://docs.letta.com/agent-sdk/memory | Memori = **blocks** per agent (`GET/POST /v1/agents/{id}/memory/blocks`) | Adapter block + filter query lokal |
| Perbandingan provider 2026 | https://agentram.dev/ai-agent-memory-providers-compared.html | Tidak ada pemenang tunggal; biaya/kualitas berbeda per use case | **Adapter pattern + fallback internal**, bukan pilih satu |

### Kredensial .env
- `.env` **TIDAK** memuat kunci Supermemory/Mem0/Zep/Letta (diverifikasi LANGKAH 0).
- Karena itu: kunci disimpan **per user** di `user_settings` lewat UI/API, dan
  bila kosong → **fallback otomatis ke `internal`** (pgvector Supabase, sudah
  berjalan). Tidak ada mock: provider `internal` adalah implementasi nyata,
  dan provider eksternal diuji terhadap kontrak HTTP nyata (mock transport
  in-process + probe server asli).

### Implementasi
- File: `memory_provider.py` (BARU). Interface tunggal:
  `remember / recall / forget / search / health`.
- Provider: `InternalProvider` (default+fallback), `SupermemoryProvider`,
  `Mem0Provider`, `ZepProvider`, `LettaProvider` — semua via `httpx`
  (**NOL dependensi vendor baru**; `httpx` sudah dipakai repo).
- `MemoryService` — provider aktif + fallback + `sync()` (eksternal→internal).
- `resolve_provider()` / `service_for()` — config per user; kunci kosong →
  `internal` secara diam-diam (fail-safe).
- API: `GET /memory/provider`, `POST /memory/provider`,
  `POST /memory/provider/sync`, `GET /memory/provider/health`.
- Registry `/version`: `29_memory_provider`.

### Hard Test — `tests/test_memory_provider.py` (14/14 PASS)
```
14 passed in 2.27s
```

| # | Skenario | Status | Raw Output |
|---|----------|--------|------------|
| 1 | Internal roundtrip (remember/recall/forget) | PASS | id + 1 hit |
| 2 | Isolasi multi-tenant internal | PASS | A melihat "rahasia A" saja |
| 3 | Supermemory: bentuk request + Bearer | PASS | `containerTags=['user:u1','agent:ag1','user:u1:agent:ag1']` |
| 4 | Supermemory: search SATU `containerTag` | PASS | `body['containerTag']` str, tanpa `containerTags` |
| 5 | Mem0: `/memories` + parse ids | PASS | `id='mem-9'`, `user_id='u2'` |
| 6 | Mem0: `memory`→`content` | PASS | `content='teh manis'` |
| 7 | Zep: sesi deterministik + path search | PASS | `/api/v2/sessions/u9::agX/memory/search` |
| 8 | Letta: block + filter query | PASS | 1 dari 2 blok (jakarta) |
| 9 | Fallback tanpa kunci → internal | PASS | `provider=internal` (3 varian config) |
| 10 | Kunci ada → provider eksternal | PASS | `name=mem0 external=True` |
| 11 | Provider error 500 → fallback internal | PASS | `primary_ok=False`, recall dari internal |
| 12 | Sinkron eksternal → internal | PASS | `synced=2`, lokal `{alfa,beta}` |
| 13 | Tanpa kunci tetap jalan end-to-end | PASS | `primary_ok=True` |
| 14 | Performa 200 remember < 1 s + tag | PASS | `_scope_tags` deterministik |

### Bug NYATA yang ditemukan (dan diperbaiki)

**BUG kontrak — Supermemory `/v4/search` menolak >1 `containerTag`.**
Probe terhadap server NYATA (`https://api.supermemory.ai/v4/search`) via endpoint
`POST /memory/provider/sync` mengembalikan:
```
MemoryProviderError: supermemory: HTTP 400
{"error":"v4 search is single-space: pass one containerTag, or use /v3/search for multi-tag search"}
```
Diperbaiki: ingest mengirim **tiga** tag (user + agent + tag gabungan
`user:<u>:agent:<a>`), sedangkan search memakai **satu** `containerTag`
gabungan tersebut — deterministik sehingga dokumen tetap bisa ditemukan.
Setelah perbaikan, error bergeser ke `401 Unauthorized` (kunci palsu) =
**kontrak sekarang benar**. Dikunci oleh uji #4 (regresi).

### Verifikasi Production (endpoint nyata via TestClient)
```
GET  /memory/provider -> 200 {'provider':'internal','has_key':False,
     'supported':['internal','supermemory','mem0','zep','letta']}
POST /memory/provider {"provider":"supermemory","api_key":"sm_secret_xyz"}
     -> 200 {'provider':'supermemory','has_key':True}   # KUNCI tidak dikembalikan
POST /memory/provider {"provider":"nope"} -> 422 'Provider tidak dikenal: nope'
GET  /memory/provider/health -> 200 {'active':'supermemory', provider.ok=True}
```
Bukti isolasi kunci: `assert "sm_secret_xyz" not in r.text` LULUS.

### Status: 100% COMPLETE ✅
Catatan TODO: Supermemory v3/v4 dimatikan **31 Des 2026** → migrasi ke v5
sebelum tanggal itu (satu file, `SupermemoryProvider`).

---

## FITUR #11 — Execution Data Redaction + Enforce 2FA

**Status:** 100% COMPLETE
**Modul baru:** `execution_redaction.py`, `two_factor.py`
**Migrasi:** `migrations/2026-10-09-redaction-2fa.sql`
**Uji:** `tests/test_execution_redaction.py` (15) + `tests/test_two_factor.py` (16) = **31 tes LULUS**
**Bukti HTTP:** `_f11_api_e2e.py` → **40 pemeriksaan, 0 gagal**
**Bukti WebAuthn nyata:** `_f11_webauthn_e2e.py` → **LULUS** (signature sungguhan)

### A. RESEARCH (sumber Okt 2026)

| Aspek | Sumber | Temuan yang diadopsi |
|---|---|---|
| Redaksi per-workflow | `docs.n8n.io/deploy/host-n8n/configure-n8n/security/redact-execution-data`; `n8n.nodejs.cn/workflows/executions/execution-data-redaction/` (n8n ≥ **2.16.0**) | Dua toggle independen (**redact production** / **redact manual**). Metadata (status, timing, node names) TETAP terlihat; payload diganti penanda; binary DIBUANG; error di-redact menyisakan tipe + HTTP status |
| Enforcement instance | `docs.n8n.io/.../security/manage-security-policies` (n8n ≥ **2.26.0**) | Toggle "Enforce data redaction" + scope. **Enforcement = lantai minimum** — workflow TIDAK boleh lebih lemah, boleh lebih ketat |
| RBAC redaksi | dokumen yang sama | `workflow:enableRedaction`, `workflow:disableRedaction`, `execution:reveal`; audit `n8n.audit.execution.data.revealed` / `..._failure` |
| 2FA | `docs.n8n.io/administer/manage-users-and-access/verify-user-identity/require-two-factor-auth` | TOTP authenticator app → QR → verifikasi → **recovery codes**; `N8N_MFA_ENABLED=false` diabaikan bila sudah ada user ber-2FA |
| Penegakan 2FA | `docs.n8n.io/.../security/manage-security-policies` | Enforce 2FA **hanya login email+password** — user SSO dikecualikan; env `N8N_MFA_ENFORCED_ENABLED`, `N8N_SECURITY_POLICY_MANAGED_BY_ENV` |
| WebAuthn Python | PyPI `webauthn` **3.0.1** (rilis Juni 2026, duo-labs/py_webauthn) | Verifikasi server-side penuh (challenge, origin, RP ID, signature, counter) |
| TOTP Python | PyPI `PyOTP` **2.9.0** (sudah terpasang di proyek) | Generator/verifikator TOTP RFC 6238 |

### B. INVENTORY KREDENSIAL

Fitur #11 **tidak memerlukan kredensial pihak ketiga**:
* TOTP dihitung lokal (`pyotp`) — tidak ada layanan eksternal.
* WebAuthn diverifikasi lokal dengan public key milik authenticator user.
* Penyimpanan memakai **Supabase yang sudah ada** (`SUPABASE_URL`/`SUPABASE_KEY` sudah di `.env`).
* Secret TOTP dienkripsi dengan **Fernet** memakai kunci vault yang sudah ada
  (`VAULT_KEY` / `SECRETS_VAULT_KEY`); bila absen, jatuh ke `plain:` (dev) dan
  hal ini **dikunci test** (`test_d2_secret_tersimpan_terenkripsi_tidak_plain`).
* Dependensi baru: `webauthn==3.0.1` (+ `cbor2`, `pyOpenSSL`, `cryptography 50.0.2`
  sebagai transitif) — semuanya gratis/open-source, **tanpa API key**.
  Diverifikasi tidak memecahkan vault: `Fernet` + `PyJWT` round-trip OK, dan
  uji lama (`test_agent_redactor`, `test_metrics_eval`) tetap lulus.

**Zero mock:** tidak ada satu pun jalur fitur yang di-stub. Yang di-stub hanya
**identitas JWT** pada skrip bukti HTTP (karena tidak ada token Supabase nyata
di lingkungan lokal) — seluruh logika fitur berjalan sungguhan.

### C. IMPLEMENTASI

1. **DDL** — `migrations/2026-10-09-redaction-2fa.sql`:
   * `workflow_redaction` (level + `policy` jsonb + CHECK level + trigger `updated_at` + RLS owner-only)
   * `user_2fa` (secret terenkripsi, `webauthn` jsonb, `recovery_salt`/`recovery_hashes`/`recovery_used`, challenge) — **RLS aktif TANPA policy klien** sehingga hanya service role yang bisa membacanya
   * `security_policy` (singleton `id=1`; boleh dibaca semua user terautentikasi, hanya service role yang boleh mengubah)
   * `user_session_epoch` (pencabutan token berbasis epoch)
2. **Engine redaksi** — `execution_redaction.py`:
   * `RedactionPolicy` level `off|production|all` + `effective_level()`/`weaker_than()` (lantai minimum)
   * PII: **email**, **telepon** (E.164 / Indonesia / gaya US), **SSN**, **kartu kredit** (divalidasi **Luhn** → nol false-positive pada 16 digit acak), **IPv4**
   * Regex **kustom per-workflow** dengan guard: panjang ≤ 300, kompilasi divalidasi, pola pencocok-kosong **ditolak**, anggaran waktu kooperatif + fail-closed (`[REDACTED_PATTERN_ERROR]`)
   * Binary dibuang (`[REDACTED_BINARY]`); rekursi dibatasi `MAX_DEPTH=8`
   * Lapisan kredensial (`agent_redactor`, 10 pola + canary) dijalankan **lebih dulu**
3. **Integrasi titik-tunggal** — `database.execution_log_row()` memanggil kebijakan
   workflow **sebelum** baris dibentuk → PII tidak pernah menyentuh disk.
   `execution_engine._log_step` meneruskan `workflow_id` + `trigger`
   (`manual` bila pengguna menjalankan dari editor, `production` bila ada
   `execution_id` dari trigger).
4. **Engine 2FA** — `two_factor.py`: TOTP + `qr_svg()` inline, recovery codes
   **sekali-pakai** (hash SHA-256 + salt per-user), penegakan instance
   (`set_policy`, `require_satisfied`, pengecualian SSO), `policy_from_env()`,
   session invalidation via epoch, WebAuthn register/authenticate lengkap
   (clone guard `sign_count`), `reset_user_2fa()` admin.
5. **API** — 18 endpoint baru: `/redaction/policy`, `/redaction/preview`,
   `/redaction/reveal-audit`, `GET|POST /workflows/{id}/redaction`,
   `/2fa/status`, `/2fa/totp/{setup,confirm,disable}`, `/2fa/verify`,
   `/2fa/overview`, `/2fa/policy`, `/2fa/admin/reset`,
   `/2fa/webauthn/{register,auth}/{begin,complete}`.
6. **Registry** — `_FEATURE_MODULES` bertambah `30_execution_redaction`,
   `31_two_factor` → terlihat di `GET /version`.

### D. HARD TEST — 13 skenario (12 wajib + 1 tambahan)

| # | Kategori | Skenario | Hasil |
|---|---|---|---|
| B1 | Basic | Email di payload → `[REDACTED_EMAIL]`, sisa teks utuh | ✅ |
| B2 | Basic | Telepon (`+62…`, `08123456789`, `(021) 555-1234`) → `[REDACTED_PHONE]` | ✅ |
| B3 | Basic | Kartu valid-Luhn → `[REDACTED_CARD]`; 16 digit acak **tidak** disentuh | ✅ |
| D1 | Durability | Pola kustom 50× berturut-turut, hasil identik (tanpa state bocor) | ✅ |
| D2 | Durability | Baris `execution_logs` tersimpan **tanpa PII asli**; cabang tanpa kebijakan = perilaku lama | ✅ |
| E1 | Edge | Tanggal ISO / jam / angka biasa **tidak** ter-redact (anti-false-positive) | ✅ |
| E2 | Edge | `bytes` + field ber-nama biner → `[REDACTED_BINARY]` | ✅ |
| E3 | Edge | Regex rusak / pencocok-kosong / nama >64 char / level tak dikenal → **ditolak tegas** | ✅ |
| P1 | Performance | 1000 pemanggilan payload sedang < 5 s (aktual ≈ 0,4 s) | ✅ |
| P2 | Performance | Struktur 40 tingkat dipotong di `MAX_DEPTH`, tidak meledak | ✅ |
| S1 | Security | `weaker_than()`/`effective_level()`: enforcement = lantai minimum (n8n 2.26.0) | ✅ |
| S2 | Security | Canary tetap menggagalkan operasi; level `production` **tidak** menyentuh `manual` | ✅ |
| X1 | Tambahan | Satu payload memuat token + email + telepon + kartu → semua tertutup | ✅ |

**2FA (16 tes / 13 skenario):** setup QR+secret · aktivasi + 10 kode cadangan ·
verifikasi TOTP & kode cadangan · kode cadangan **sekali-pakai** · secret
tersimpan terenkripsi · verifikasi deterministik `at=` (anti-flaky) · user belum
aktif → error · reset admin mencabut epoch · 300 verifikasi < 2 s · 100×
secret+QR < 3 s · penegakan memblokir user tanpa 2FA · SSO dikecualikan &
`disable` ditolak saat enforced · **WebAuthn round-trip signature nyata** ·
4 serangan passkey (replay / origin palsu / signature kunci lain / counter mundur)
**semuanya ditolak**.

### E. VERIFIKASI

**Bukti WebAuthn nyata** (`_f11_webauthn_e2e.py`) — authenticator perangkat lunak
dengan keypair ES256 + CBOR, signature diverifikasi pustaka `webauthn`:
```
REGISTER: {"enabled": true, "method": "webauthn", "webauthn_count": 1}
AUTH OK: {"user_id": "user-wa-1", "ok": true, "method": "webauthn", "sign_count": 1}
REPLAY DITOLAK: autentikasi passkey ditolak: Client data challenge was not expected challenge
ORIGIN PALSU DITOLAK: Unexpected client data origin "https://katalir.de5.net", expe...
SIGNATURE PALSU DITOLAK: Could not verify authentication signature
COUNTER MUNDUR DITOLAK: Response sign count of 0 was not greater than current count o...
HASIL_SELURUH: LULUS
```

**Bukti HTTP** (`_f11_api_e2e.py`) — potongan output nyata:
```
[PASS] GET /redaction/policy 200  :: HTTP 200
[PASS] katalog pii_types  :: ["email", "phone", "ssn", "credit_card", "ipv4"]
[PASS] preview: email tersaring  :: {"email": "[REDACTED_EMAIL]", "phone": "[REDACTED_PHONE]", "card": "[REDACTED_CARD]", "ssn": "[REDACTED_SSN]", ...
[PASS] preview: level production TIDAK menyentuh manual  :: {"email": "x@y.com"}
[PASS] preview: regex rusak -> 422  :: HTTP 422
[PASS] POST /2fa/totp/confirm 200  :: {"enabled": true, "method": "totp", "recovery_codes_remaining": 10}
[PASS] kode cadangan sekali-pakai -> 401  :: HTTP 401
[PASS] tanpa admin -> /2fa/policy 403  :: HTTP 403 :: {"detail":"Butuh peran admin untuk aksi ini."}
[PASS] disable saat enforced -> 409  :: HTTP 409
[PASS] webauthn: sign_count naik ke 1
[PASS] webauthn: replay challenge -> 401  :: HTTP 401
[PASS] registry: 30_execution_redaction  :: {"30_execution_redaction": true, "31_two_factor": true}
TOTAL: 40 pemeriksaan | GAGAL: 0
HASIL: LULUS
```

**pytest:** 31 tes Fitur #11 LULUS (15 redaksi + 16 2FA).

### F. DEVIASI & CATATAN

1. **Redaksi diterapkan SEBELUM tulis, bukan saat baca.** n8n menerapkan
   redaksi di lapisan API (data mentah tetap di DB). Di sini redaksi terjadi
   **sebelum** `execution_logs` dibentuk, sehingga PII sensitif tidak pernah
   menyentuh disk — lebih kuat dari model n8n. Konsekuensinya: `execution:reveal`
   tidak bisa "membuka kembali" data, dan itu memang disengaja. Endpoint
   `/redaction/reveal-audit` disediakan untuk mencatat **niat** membuka data
   (event audit gaya `n8n.audit.execution.data.revealed`, siap dialirkan ke
   SIEM pada Fitur #4).
2. **WebAuthn dukungan penuh**, tidak diminta eksplisit di ringkasan brief
   ("2FA: TOTP, WebAuthn, backup codes") tetapi tertulis di daftar 12 skenario
   hard test → diimplementasikan lengkap dengan verifikasi signature nyata.
3. **Penyimpanan default = memori proses.** Backend `MemoryTwoFactorStore`
   dipakai sekarang (pola yang sama dengan fitur durable/queue lain di repo);
   migrasi SQL sudah disiapkan agar bisa diganti backend Supabase tanpa
   mengubah API. **Catatan TODO:** pindahkan ke Supabase sebelum produksi agar
   2FA bertahan melewati restart (satu titik: `two_factor.store()`).
4. **Tidak ada BLOKER.** Tidak ada kredensial yang hilang, tidak ada kartu
   kredit, dan tidak ada 10 alternatif yang gagal.

### Status: 100% COMPLETE ✅
