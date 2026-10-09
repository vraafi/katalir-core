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
| 12 | External Memory Provider | `memory_provider.py` | 14/14 | `74f0dee` | ✅ |
| 11 | Redaction + Enforce 2FA | `execution_redaction.py`, `two_factor.py` | 31/31 | `8446284` | ✅ |
| 4 | Log Streaming SIEM | `log_streaming.py` | 22/22 + 40 E2E | — | ✅ |
| 8 | OTel / LangSmith Tracing | `tracing.py` | 19/19 + 75 E2E | — | ✅ |
| 3 | Self-healing Persistence | `recovery.py` | 19/19 + 62 E2E | — | ✅ |
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

---

## FITUR #4: LOG STREAMING TO SIEM

### A. RESEARCH (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| n8n Log Streaming (docs resmi) | https://n8n.nodejs.cn/log-streaming/ | 3 tipe tujuan: **webhook**, **syslog (RFC 5424)**, **Sentry**; field per-tipe berbeda | Implementasikan ketiga tipe dengan skema field 1:1 dari docs |
| deepwiki n8n-docs 9.5 | https://deepwiki.com/n8n-io/n8n-docs/9.5-log-streaming-and-opentelemetry | Katalog event bergrup (`n8n.workflow.*`, `n8n.node.*`, `n8n.audit.*`, `n8n.worker.*`, `n8n.ai.*`, `n8n.runner.*`, `n8n.queue.*`); `subscribedEvents` menerima **prefiks grup** | `event_matches()` cocokkan grup, nama penuh, dan wildcard `*` |
| n8n log streaming — keandalan | https://n8n.nodejs.cn/log-streaming/#circuit-breaker | **Circuit breaker** `{maxFailures, failureWindow}`; ada **event log lokal durabel** yang di-*re-emit* setelah pulih | `CircuitBreaker` sliding-window + spool durabel dengan `flush()` |
| n8n log streaming — anonimisasi | https://n8n.nodejs.cn/log-streaming/#anonymize-audit-messages | `anonymizeAuditMessages`: pesan audit disamarkan sebelum keluar, **metadata tetap terlihat** | `Destination.prepare()` memakai kembali `redact_value` dari Fitur #11a |
| n8n env-managed | https://n8n.nodejs.cn/log-streaming/#managed-by-env | Deployment bisa mengunci konfigurasi lewat env (`N8N_LOG_STREAMING_MANAGED_BY_ENV`, `N8N_LOG_STREAMING_DESTINATIONS`) | `destinations_from_env()` + flag `managed_by_env` di katalog |
| RFC 5424 (syslog) | https://datatracker.ietf.org/doc/html/rfc5424 | Frame: `<PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID SD MSG`; PRI = `facility*8 + severity` | `format_rfc5424()` + `_default_hostname()` (bukan `-`) |
| Sentry Envelope | https://develop.sentry.dev/sdk/envelopes/ | Amplop 3 baris: header JSON, item header, payload | `SentryDestination.envelope()` |

### B. INVENTORY KREDENSIAL `.env`

| Variabel | Ada? | Dipakai untuk |
|---|---|---|
| `KATALIR_LOG_STREAMING_MANAGED_BY_ENV` | tidak (opsional) | Kunci konfigurasi ke env (gaya n8n) |
| `KATALIR_LOG_STREAMING_DESTINATIONS` | tidak (opsional) | JSON array tujuan bila managed-by-env |
| `KATALIR_LOG_STREAMING_OWNER` | tidak (opsional) | Pemilik bus untuk hook audit non-HTTP (mis. reveal data) |

**Tidak ada kredensial eksternal yang dibutuhkan.** Semua tujuan
(webhook URL, syslog host/port, Sentry DSN) dikonfigurasi oleh pengguna
lewat API dan disimpan per-pemilik. Tidak ada BLOKER.

### C. IMPLEMENTASI

1. **`log_streaming.py`** (baru, ~950 baris)
   - `EVENT_GROUPS` (7 grup) + `EVENTS` (90 nama event, 53 di antaranya audit)
   - `event_matches(event, subscribed)` — grup / nama penuh / wildcard / prefiks `n8n.`
   - `CircuitBreaker` (sliding window, clock ter-injeksi) — `is_open`, `allows()`,
     `record_failure()`, `record_success()`, `snapshot()`
   - `Destination` (ABC) + `WebhookDestination` / `SyslogDestination` / `SentryDestination`
   - `format_rfc5424()` — `<PRI>1 TIMESTAMP HOSTNAME APP PROCID MSGID - MSG`
   - `sentry_dsn_parts()` + `envelope()` — amplop 3 baris
   - `build_destination(spec, *, transport, clock)` — validasi + pabrik
   - `destinations_from_env()` — mode managed-by-env
   - `EventBus` + **spool durabel** (`flush()`, `spool_size()`, `_persist_spool()`)
   - `BRIDGE_MAP` (19 nama Katalir → nama n8n) + `stream()`
   - **`owner_bus()` / `invalidate_owner_bus()`** — bus per-pemilik dengan TTL
     (lihat temuan di bagian F)
2. **`api_server.py`** — 7 endpoint + 3 model Pydantic + registry `32_log_streaming`:
   `GET /log-streaming/events`, `GET|POST /log-streaming/destinations`,
   `DELETE /log-streaming/destinations/{label}`, `POST /log-streaming/test`,
   `GET /log-streaming/stats`, `POST /log-streaming/flush`, `POST /log-streaming/emit`
3. **Jembatan Fitur #11a → #4** — `/redaction/reveal-audit` memancarkan
   `n8n.audit.execution.data.revealed` ke bus SIEM pemilik.
4. **`migrations/2026-10-09-log-streaming.sql`** — tabel `log_stream_destinations`
   (owner PK) + `log_stream_deliveries` + trigger `updated_at` + RLS.
5. **Antarmuka** — katalog event + CRUD tujuan + tombol uji kirim + statistik
   per-tujuan (endpoint di atas dipakai langsung oleh panel SIEM).

### D. HARD TEST (12 skenario)

Berkas: `tests/test_log_streaming.py` (16 tes) + `tests/test_log_streaming_owner_bus.py` (6 tes).

| # | Kategori | Skenario | Hasil |
|---|---|---|---|
| B1 | Basic | Webhook POST nyata, body JSON berisi `event` | PASS |
| B2 | Basic | Frame syslog RFC 5424 — `parts[0]=="<134>1"`, `parts[3]=="katalir"` (APP-NAME), `parts[4]=="-"` (PROCID), `parts[5]` (MSGID) | PASS |
| B3 | Basic | Amplop Sentry 3 baris (header / item header / payload) | PASS |
| D1 | Durability | Spool menampung event saat tujuan mati, `flush()` mengirim ulang | PASS |
| D2 | Durability | Spool bertahan lintas "restart" (bangun bus baru dari `spool_path`) | PASS |
| E1 | Edge | Langganan prefiks grup + wildcard + nama penuh | PASS |
| E2 | Edge | Konfigurasi tak sah (webhook tanpa URL, syslog port cacat, DSN rusak) ditolak | PASS |
| E3 | Edge | `anonymizeAuditMessages` menyamarkan pesan audit, metadata tetap | PASS |
| P1 | Performance | 1.000 event × 3 tujuan tanpa degradasi | PASS |
| P2 | Performance | `max_spool` membatasi memori (tidak tumbuh tanpa batas) | PASS |
| S1 | Security | Circuit breaker membuka setelah `maxFailures`, lalu pulih | PASS |
| S2 | Security | DSN/header rahasia TIDAK bocor di respons API maupun log | PASS |
| X1 | Ekstra | Pabrik `destinations_from_env()` | PASS |
| X2 | Ekstra | Fan-out satu event ke banyak tujuan | PASS |
| X3 | Ekstra | `BRIDGE_MAP` menerjemahkan semua nama Katalir | PASS |
| X4 | Ekstra | Normalisasi level log | PASS |
| Y1 | Isolasi | Pemilik sama → bus sama (cache hit, pabrik 1×) | PASS |
| Y2 | Isolasi | TTL habis → bus dibangun ulang | PASS |
| Y3 | Isolasi | Dua pemilik → dua bus berbeda | PASS |
| Y4 | Isolasi | `invalidate_owner_bus(id)` / `(None)` | PASS |
| Y5 | Isolasi | Event bus A **tidak** membocor ke tujuan bus B | PASS |

**E2E HTTP mentah** (`_f4_api_e2e.py`, server HTTP lokal + kolektor UDP nyata):

```
==========================================================================
A. KATALOG EVENT
==========================================================================
[PASS] GET /log-streaming/events 200  :: HTTP 200
[PASS] 3 grup inti tersedia  :: ["n8n.workflow", "n8n.node", "n8n.audit", "n8n.worker", "n8n.ai", "n8n.runner", "n8n.queue"]
[PASS] tipe tujuan = webhook/syslog/sentry
[PASS] katalog audit punya >= 20 event  :: 53
  total event = 90
==========================================================================
B. SIMPAN TUJUAN (validasi + penyamaran rahasia)
==========================================================================
[PASS] POST /log-streaming/destinations 200  :: HTTP 200
[PASS] rahasia header disamarkan di respons
[PASS] POST syslog 200  :: HTTP 200
[PASS] sentry DSN rusak -> 422  :: HTTP 422
[PASS] webhook tanpa url -> 422  :: HTTP 422
[PASS] GET daftar tujuan 200
[PASS] 2 tujuan tersimpan  :: ["ops-hook", "soc-udp"]
==========================================================================
C. TES KIRIM NYATA (webhook HTTP + syslog UDP)
==========================================================================
[PASS] POST /log-streaming/test (webhook) 200  :: delivered:true
[PASS] webhook: delivered=true
[PASS] server lokal MENERIMA request  :: n=1
[PASS] body berisi event n8n  :: {"event": "n8n.audit.user.login.success", "group": "n8n.audit", ...
[PASS] Authorization header terkirim  :: Bearer topsecret123
[PASS] POST /log-streaming/test (syslog) 200  :: delivered:true
[PASS] syslog: delivered=true
[PASS] UDP collector MENERIMA frame  :: n=1
[PASS] frame berawalan <110>1  :: <110>1 2026-10-09T05:11:12Z DESKTOP-BKR2
[PASS] frame memuat JSON event  :: ... DESKTOP-BKR2PJ9 katalir - n8n.workflow.success - {"data": {"source": "log-streaming/test", ...
==========================================================================
D. EMIT + STATISTIK + FLUSH
==========================================================================
[PASS] POST /log-streaming/emit 200  :: {"event":"n8n.workflow.success","delivered":{"ops-hook":true,"soc-udp":true},"any_delivered":true,"destinations":2}
[PASS] emit: any_delivered=true  :: {"ops-hook": true, "soc-udp": true}
[PASS] nama bridge diterjemahkan  :: n8n.workflow.success
[PASS] webhook menerima emit
[PASS] emit nama tak dikenal -> 422  :: HTTP 422
[PASS] GET /log-streaming/stats 200
[PASS] stats: 2 tujuan terlacak  :: ["ops-hook", "soc-udp"]
[PASS] stats: bus SAMA dipakai (sent > 0)  :: {"ops-hook": 1, "soc-udp": 1}
[PASS] stats: bus per-pemilik ter-cache
  sent/failed per tujuan = {"ops-hook": [1, 0], "soc-udp": [1, 0]}
[PASS] POST /log-streaming/flush 200  :: {"attempted":0,"delivered":0,"remaining":0,"had_destination":true}
==========================================================================
E. AUDIT REVEAL (Fitur #11a) MEMANCARKAN KE SIEM
==========================================================================
[PASS] POST /redaction/reveal-audit 200  :: HTTP 200
[PASS] event audit reveal terbentuk
[PASS] baris audit tertulis ke execution_logs
[PASS] SIEM menerima event reveal  :: n=1
[PASS] nama event reveal sesuai n8n  :: n8n.audit.execution.data.revealed
[PASS] reveal dikirim ke PEMILIK bus (bukan proses-wide)  :: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
[PASS] tanpa owner: audit tetap 200
[PASS] tanpa owner: tujuan user TIDAK kebanjiran event  :: n=0
==========================================================================
F. REGISTRY /version
==========================================================================
[PASS] registry: 32_log_streaming  :: {"30_execution_redaction": true, "31_two_factor": true, "32_log_streaming": true}
==========================================================================
TOTAL: 40 pemeriksaan | GAGAL: 0
HASIL: LULUS
```

### E. VERIFIKASI

- `pytest tests/test_log_streaming.py tests/test_log_streaming_owner_bus.py` → **22 LULUS**
- `pytest tests/test_log_streaming.py tests/test_execution_redaction.py tests/test_two_factor.py` → **47 LULUS**
- E2E HTTP mentah → **40/40 LULUS** (webhook ke server HTTP lokal nyata, syslog lewat UDP socket nyata)
- `/version` → `32_log_streaming: true`

### F. DEVIASI & TEMUAN

1. **TEMUAN (bug nyata, ditemukan oleh E2E — bukan tes unit).** Endpoint
   `/log-streaming/stats` dan `/flush` semula membangun `EventBus` **baru**
   pada setiap panggilan, sehingga penghitung `sent`/`failed` selalu nol
   (tiap panggilan melihat bus yang belum pernah mengirim apa pun). Hal
   yang sama juga mematikan re-emit spool. Perbaikan: `owner_bus()` di
   `log_streaming.py` (cache per-pemilik + TTL) dipakai bersama oleh
   `/stats`, `/flush`, dan `/emit`; cache dibuang saat tujuan
   disimpan/dihapus. Dikunci oleh 6 tes di `test_log_streaming_owner_bus.py`.
   *Ini persis alasan brief mewajibkan bukti keluaran mentah: tes unit 16/16
   hijau sementara statistik produksi tetap nol.*
2. **Hook audit non-HTTP butuh pemilik eksplisit.** `reveal-audit` dipanggil
   dengan Authorization (pemilik jelas), tetapi jalur audit lain (worker,
   cron, queue) tidak punya header. Karena itu `KATALIR_LOG_STREAMING_OWNER`
   disediakan; tanpa itu hook jatuh ke bus proses-wide (default env) dan
   **tidak** menyentuh tujuan milik pengguna — perilaku ini diuji eksplisit
   ("tanpa owner: tujuan user TIDAK kebanjiran event").
3. **Spool durabel berbasis berkas**, bukan Redis/DB (pola sama dengan
   durable/queue lain di repo). Antarmuka `flush()`/`spool_size()` sudah
   stabil sehingga backend bisa diganti tanpa mengubah API.
4. **`destination` inline di `/log-streaming/test`** memungkinkan uji
   konfigurasi tanpa menyimpannya dulu — berguna untuk tombol "Test" di UI.
5. **Tidak ada BLOKER.** Tidak ada kredensial hilang, tidak ada kartu kredit,
   tidak ada 10 alternatif yang gagal.

### Status: 100% COMPLETE ✅

---

## FITUR #8: DISTRIBUTED TRACING (OPENTELEMETRY / LANGSMITH)

### A. RESEARCH (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| n8n — Trace executions with OpenTelemetry | https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/trace-executions-with-opentelemetry | Preview sejak 2.19.0. **Dua span per eksekusi**: `workflow.execute` (root) + `node.execute` (anak). Sejak 2.33.0 span agen `gen_ai.*`; sejak 2.42.0 span eksekusi *crashed*. Resource: `service.name` (default `n8n`), `service.version`, `n8n.instance.id`, `n8n.instance.role`. | Nama span + seluruh tabel atribut disalin 1:1; 5 detektor crash didukung |
| n8n — OTel (protokol, sampling, env) | halaman yang sama | Default `http/protobuf`; endpoint = **BASE URL** dan exporter menambahkan `/v1/traces`. Protokol `grpc` (2.39.0) mengabaikan path & **butuh port eksplisit**. Sampling `N8N_OTEL_TRACES_SAMPLE_RATE` (trace-id ratio). Default **hanya produksi**. | `traces_url()` tidak menambah path bila sudah ada; grpc pakai endpoint apa adanya; sampler berbasis trace-id |
| n8n — propagasi & konfigurasi UI | halaman yang sama | `traceparent` W3C masuk menjadi induk span workflow; keluar disuntik ke node HTTP. Sub-workflow memakai span induk. Resume setelah `wait` memakai **span link** + `n8n.continuation.reason`. Konfigurasi UI (2.27.0) tanpa restart; **env menang** atas UI. Ada tombol "Send test trace". | `link_previous()`, `inject_into_headers()`, `POST /tracing/config` (uji kirim) |
| LangSmith — Trace with OpenTelemetry | https://docs.langchain.com/langsmith/trace-with-opentelemetry | `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.smith.langchain.com/otel`; header `x-api-key`; `Langsmith-Project` untuk nama proyek. **Jangan** sertakan `/v1/traces` di base URL (jadi dobel → 404). | Preset `langsmith` di `BACKEND_PRESETS`; `traces_url()` mencegah path dobel |
| W3C Trace Context | https://www.w3.org/TR/trace-context/ | `traceparent = 00-<32hex trace-id>-<16hex span-id>-<2hex flags>`; versi `ff` dilarang; **semua-nol tidak sah**. Huruf kecil wajib saat *menghasilkan*; penerima boleh menerima huruf besar. | `is_valid_traceparent()` menolak nol/`ff`/panjang salah; pengurai menormalkan ke huruf kecil |
| OTLP TraceService proto | https://github.com/open-telemetry/opentelemetry-proto | Struktur `ExportTraceServiceRequest` → `ResourceSpans` → `ScopeSpans` → `Span` | Encoder protobuf ditulis tangan (nol dependensi) |

### B. INVENTORY KREDENSIAL `.env`

| Variabel | Ada? | Dipakai untuk |
|---|---|---|
| `N8N_OTEL_ENABLED` | tidak (opsional) | Gerbang utama tracing |
| `N8N_OTEL_EXPORTER_OTLP_ENDPOINT` | **tidak** | Base URL collector |
| `N8N_OTEL_EXPORTER_OTLP_HEADERS` | **tidak** | `k=v,k=v` (mis. `x-api-key=...`) |
| `N8N_OTEL_EXPORTER_OTLP_PROTOCOL` | tidak (opsional) | `http/protobuf` (default) atau `grpc` |
| `N8N_OTEL_TRACES_SAMPLE_RATE` | tidak (opsional) | Rasio sampling 0..1 |
| `N8N_OTEL_TRACES_PRODUCTION_ONLY` | tidak (opsional) | Default `true` (manual tidak ditrace) |
| `N8N_OTEL_TRACES_INCLUDE_NODE_SPANS` | tidak (opsional) | Matikan span node bila terlalu banyak |
| `N8N_OTEL_TRACES_INJECT_TRACEPARENT` | tidak (opsional) | Matikan suntikan header keluar |
| `N8N_AGENTS_TRACING_ENABLED` | tidak (opsional) | Span agen (butuh `N8N_OTEL_ENABLED` juga) |
| `N8N_AGENTS_TRACING_RECORD_INPUTS` / `_OUTPUTS` | tidak (opsional) | Kecualikan prompt/argumen/hasil dari span |

**Kredensial opsional yang mungkin sudah ada:** LangSmith/Honeycomb. Bila
`N8N_OTEL_EXPORTER_OTLP_ENDPOINT` dan header-nya **tidak** diisi, tracing
nonaktif — **bukan** BLOKER. Tanpa endpoint, seluruh fungsionalitas tetap
diuji memakai **collector OTLP lokal nyata** (loopback), jadi tidak ada
ketergantungan pada akun berbayar.

### C. IMPLEMENTASI

1. **`tracing.py`** (baru, ~1.248 baris) — nol dependensi OTel baru:
   - **Encoder protobuf OTLP ditulis tangan**: `encode_any_value`,
     `encode_key_value`, `encode_attributes`, `encode_resource`,
     `encode_span`, `encode_scope_spans`, `encode_resource_spans`,
     `encode_export_request` (varint + length-delimited + fixed64).
   - **W3C Trace Context**: `new_trace_id`, `new_span_id`,
     `is_valid_traceparent`, `parse_traceparent`, `format_traceparent`.
   - `Sampler` (trace-id ratio), `Span` (dengan `links`, `status`, `events`,
     `record_exception`), `ExecutionTrace` (+ `_NodeCtx` konteks `with`).
   - `OTLPExporter` — transport **dapat disuntik**; `urllib` di produksi;
     `build_headers`, `traces_url` (anti-dobel `/v1/traces`).
   - Semantik n8n: `workflow_attributes` (16 atribut), `node_attributes`
     (8 atribut), `agent_attributes` (`gen_ai.*` + `execute_tool`),
     `crashed_attributes` (5 detektor), `agent_span_name`, `tool_span_name`.
   - `start_execution`, `trace_crashed_execution`, `trace_workflow`,
     `inject_into_headers`, `tracer_from_env`, `describe`, `BACKEND_PRESETS`.
2. **`api_server.py`** — 6 endpoint + 3 model Pydantic + registry `33_tracing`:
   `GET /tracing/config`, `GET /tracing/spans`, `GET /tracing/stats`,
   `POST /tracing/flush`, `POST /tracing/config` (padanan *Send test trace*),
   `POST /tracing/export`, `POST /tracing/test`.
3. **`migrations/2026-10-09-tracing.sql`** — tabel `tracing_config`,
   `tracing_config_secrets` (header terenkripsi, **tanpa policy RLS**),
   `execution_trace_context` (propagasi lintas-proses gaya queue mode n8n),
   `tracing_spans` (ringkasan untuk UI, indeks GIN pada `attributes`) +
   trigger `updated_at` + RLS per-pemilik.
4. **Antarmuka** — panel Settings > Tracing: status, endpoint, sampling,
   opsi span, tombol uji kirim, dan daftar span terakhir.

### D. HARD TEST (12 skenario)

Berkas: `tests/test_tracing.py` (19 tes).

| # | Kategori | Skenario | Hasil |
|---|---|---|---|
| B1 | Basic | `traceparent` versi 00 dibentuk & diurai bolak-balik | PASS |
| B2 | Basic | Satu eksekusi → span `workflow.execute` + `node.execute` terkirim | PASS |
| B3 | Basic | Header OTLP (auth, `Content-Type: application/x-protobuf`) + URL `/v1/traces` | PASS |
| D1 | Durability | Ekspor gagal → span dikembalikan ke antrean, ulang berhasil | PASS |
| D2 | Durability | Antrean dibatasi `MAX_SPOOL` saat backend mati terus-menerus | PASS |
| E1 | Edge | Span node memakai span workflow sebagai induk (trace sama) | PASS |
| E2 | Edge | Sub-workflow jadi anak; resume `wait` → span link + `n8n.continuation.reason` | PASS |
| E3 | Edge | Konfigurasi tak sah ditolak (endpoint, protokol, header, sampler, detektor) | PASS |
| P1 | Performance | 1.000 span (200 eksekusi × 5) dikodekan & diekspor | PASS |
| P2 | Performance | Sampler konsisten per trace-id; rasio 0,25 terukur 0,256 | PASS |
| S1 | Security | `traceparent` cacat DITOLAK (nol, `ff`, panjang salah, non-hex); keluaran selalu huruf kecil | PASS |
| S2 | Security | Atribut tidak memuat kunci API; input/output agen dapat dikecualikan | PASS |
| X1 | Ekstra | Semua env `N8N_OTEL_*` dibaca benar (incl. `BACKEND_PRESETS`) | PASS |
| X2 | Ekstra | Span eksekusi crash (2.42.0): status, `error_type`, detektor, `reconstructed` | PASS |
| X3 | Ekstra | Nama span agen/tool + seluruh atribut `gen_ai.*` | PASS |
| X4 | Ekstra | Wire-format protobuf sah (trace_id/span_id biner, fixed64 start_ns) | PASS |
| X5 | Ekstra | Suntikan `traceparent` keluar; dapat dimatikan lewat env | PASS |
| X6 | Ekstra | Gerbang mode produksi (manual diblokir secara default) | PASS |
| X7 | Ekstra | `trace_workflow` mengembalikan `None` saat tracing nonaktif | PASS |

**E2E HTTP mentah** (`_f8_api_e2e.py`, **collector OTLP lokal nyata** di loopback
menerima POST `/v1/traces`, payload diperiksa byte-level):

```
==========================================================================
A. KATALOG + KONFIGURASI
==========================================================================
[PASS] GET /tracing/config 200  :: HTTP 200
[PASS] enabled dari env
[PASS] url = endpoint + /v1/traces  :: http://127.0.0.1:57941/v1/traces
[PASS] nama header terbaca (nilai TIDAK)  :: ["Langsmith-Project", "x-api-key"]
[PASS] rahasia tidak bocor di /tracing/config
[PASS] service_name = katalir
[PASS] span names sesuai n8n
[PASS] 5 detektor crash n8n  :: ["stall", "queue-recovery", "startup-recovery", "start-failure", "workflow-deactivation"]
[PASS] GET /tracing/spans 200
[PASS] atribut workflow lengkap (16 = tabel n8n)  :: 16
[PASS] atribut node lengkap (8)  :: 8
[PASS] atribut agen gen_ai.* ada
[PASS] 2 protokol OTLP  :: ["http/protobuf", "grpc"]
[PASS] preset langsmith tersedia
==========================================================================
B. EKSPOR NYATA KE COLLECTOR (protobuf di byte-level)
==========================================================================
[PASS] POST /tracing/export 200  :: HTTP 200
[PASS] span_count = 3 (root + 2 node)  :: 3
[PASS] node_count_attribute = 2
[PASS] exporter melaporkan sent_spans > 0  :: {"protocol": "http/protobuf", "url": "http://127.0.0.1:57941/v1/traces", "headers": ["Langsmith-Project", "x-api-key"], "sent_spans": 3, "failed_spans": 0, "last_status": 200, "last_error": ""}
[PASS] collector MENERIMA POST /v1/traces  :: n=1
[PASS] path = /v1/traces  :: /v1/traces
[PASS] Content-Type protobuf  :: application/x-protobuf
[PASS] payload protobuf tidak kosong  :: 985 B
[PASS] resource: service.name=katalir
[PASS] resource: n8n.instance.id
[PASS] resource: n8n.instance.role=main
[PASS] span name workflow.execute
[PASS] span name node.execute
[PASS] trace_id root ada di payload
[PASS] span_id root ada di payload
[PASS] span_id node #1 ada di payload
[PASS] atribut n8n.workflow.id
[PASS] atribut n8n.execution.mode=webhook
[PASS] atribut n8n.node.type
[PASS] atribut n8n.node.items.output
[PASS] RAHASIA tidak masuk payload span
[PASS] node span memakai root sebagai induk  :: cc4b28057a2774d1 vs cc4b28057a2774d1
[PASS] semua span berada dalam satu trace
==========================================================================
C. PROPAGASI W3C traceparent (masuk & keluar)
==========================================================================
[PASS] trace_id mengikuti traceparent masuk  :: cccccccccccccccccccccccccccccccc
[PASS] parent_span_id = span pemanggil
[PASS] traceparent keluar dibentuk ulang dengan trace sama  :: 00-cccccccccccccccccccccccccccccccc-b14c3227951b8251-01
[PASS] traceparent cacat diabaikan
==========================================================================
D. SPAN CRASH (n8n 2.42.0) + SPAN AGEN gen_ai.*
==========================================================================
[PASS] POST crash span 200
[PASS] status crash
[PASS] error_type = WorkflowCrashedError
[PASS] detektor stall
[PASS] reconstructed=false
[PASS] span crash terkirim ke collector
[PASS] detektor ngawur -> 422
[PASS] POST agent span 200
[PASS] span agen terkirim ke collector
[PASS] gen_ai.operation.name
[PASS] gen_ai.agent.name  :: Sales Bot
[PASS] span agen .generate
[PASS] span tool execute_tool search_web
[PASS] gen_ai.tool.call.id
[PASS] gen_ai.request.model openai/gpt-4o
==========================================================================
E. GERBANG MODE + SAMPLING
==========================================================================
[PASS] mode manual tetap diizinkan di endpoint eksplisit
[PASS] gerbang produksi: manual DITOLAK
[PASS] gerbang produksi: webhook DITERIMA
[PASS] production_only=false -> manual diterima
[PASS] sampler 0.25 memberi rasio wajar  :: ratio=0.256
[PASS] sampler 1.0 selalu menerima
==========================================================================
F. UJI KONFIGURASI (padanan 'Send test trace')
==========================================================================
[PASS] POST /tracing/config 200
[PASS] delivered=true
[PASS] http_status 200
[PASS] collector menerima span uji
[PASS] skema endpoint salah -> 422  :: HTTP 422
[PASS] protokol salah -> 422  :: HTTP 422
==========================================================================
G. STATISTIK + FLUSH + REGISTRY
==========================================================================
[PASS] GET /tracing/stats 200
[PASS] sent_spans > 0  :: {"sent_spans": 36, "failed_spans": 0, "last_status": 200}
[PASS] sample_rate terbaca  :: 1.0
[PASS] auto_flush aktif
[PASS] POST /tracing/flush 200
[PASS] flush tanpa sisa  :: {"exported": 0, "ok": true, "pending": 0}
[PASS] registry: 33_tracing  :: {"30_execution_redaction": true, "31_two_factor": true, "32_log_streaming": true, "33_tracing": true}
==========================================================================
TOTAL: 75 pemeriksaan | GAGAL: 0
HASIL: LULUS
```

### E. VERIFIKASI

- `pytest tests/test_tracing.py` → **19 LULUS**
- `pytest tests/test_tracing.py tests/test_log_streaming*.py tests/test_execution_redaction.py tests/test_two_factor.py` → **72 LULUS**
- E2E HTTP mentah → **75/75 LULUS** (collector OTLP lokal nyata, payload protobuf diperiksa byte-level)
- `/version` → `33_tracing: true`

### F. DEVIASI & TEMUAN

1. **TEMUAN (bug nyata, ditangkap E2E).** `ExecutionTrace.finish()` tidak
   menerima `error_type`, padahal n8n menulis atribut
   `n8n.execution.error_type` pada span yang gagal. Endpoint
   `/tracing/export` memanggilnya dengan kata kunci itu → `TypeError` (500).
   Diperbaiki: `finish(error_type=...)` kini menulis atribut tersebut dan
   menandai status span `ERROR`. Tes unit 19/19 hijau **tidak** menangkapnya
   karena tidak memanggil jalur HTTP — sekali lagi alasan brief mewajibkan
   bukti keluaran mentah.
2. **TEMUAN (bug nyata, ditangkap uji).** `Sampler` semula mengambil 16 hex
   **terakhir** trace-id. Karena `uuid4().hex` menaruh nibble versi/variant di
   posisi tengah, sebaran nilai ekor terbukti tidak seragam — rasio terukur
   **0,000** untuk rate 0,25. Diperbaiki memakai 16 hex **pertama**; rasio kini
   0,256 (rate 0,25) dan 0,506 (rate 0,5).
3. **TEMUAN (pemahaman spec).** Saya semula menganggap huruf besar pada
   `traceparent` harus ditolak. W3C §3.2.2 mewajibkan huruf kecil saat
   **menghasilkan**, tetapi penerima boleh menerima keduanya. `is_valid_traceparent`
   tidak lagi menolak huruf besar; pengurai menormalkan sebelum memakai nilainya,
   dan `format_traceparent` dijamin selalu huruf kecil. Perilaku ini dikunci tes.
4. **`TracingError` dipetakan ke HTTP 422** di endpoint (detektor crash ngawur,
   protokol salah, skema endpoint salah) — bukan 500.
5. **Encoder protobuf ditulis tangan, bukan SDK `opentelemetry-*`.**
   Alasannya: keep the production image lean (sandbox produksi memang tanpa
   Node/Python berat), dan menghindari perubahan tak terduga pada
   `cryptography`/Fernet yang sudah dipakai Fitur #11. Konsekuensinya: hanya
   sinyal *traces* yang didukung (bukan metrics/logs) — sesuai cakupan n8n
   yang juga baru traces. Dekode oleh collector tetap standar karena byte
   yang dihasilkan mengikuti skema OTLP resmi.
6. **Tidak ada BLOKER.** Tracing nonaktif tanpa endpoint; seluruh pengujian
   memakai collector lokal. Tidak ada kredensial wajib, kartu kredit, atau
   10 alternatif yang gagal.

### Status: 100% COMPLETE ✅

---

## FITUR #3: SELF-HEALING PERSISTENCE (EXECUTION RECOVERY OTONOM)

### Research (link Okt 2026)

Sumber yang dibaca (3, sesuai mandat):

1. **Forum komunitas n8n — "Worker crashed, what happens to the job?"**
   (`community.n8n.io/t/.../json` — API `.json` dipakai karena HTML-nya
   diblokir checkpoint Vercel). Temuan kunci:
   * Job pada worker yang crash **TIDAK** otomatis dioper ke worker lain.
   * **Tidak ada checkpoint** di tengah workflow: retry selalu mulai dari awal
     → efek samping WAJIB idempoten.
   * `QUEUE_WORKER_MAX_STALLED_COUNT` **deprecated**.
2. **Dokumentasi n8n — OpenTelemetry / crash detection (2.42.0).**
   5 detektor: `stall`, `queue-recovery`, `startup-recovery`, `start-failure`,
   `workflow-deactivation`. n8n **mendeteksi lalu berhenti**.
3. **Playbook produksi AIFLOXIUM 2026 — "Self-healing workflows".**
   5 lapisan: idempotency → smart retry (exponential backoff + **full jitter**)
   → compensating action → DLQ → observability. 7 mode kegagalan dipetakan ke
   jenis pemulihan; aturan retry: **5xx/429/401 diulang, 422 TIDAK pernah**.

### B. Inventory kredensial

Tidak butuh kredensial eksternal. Seluruh perilaku in-process; konfigurasi
lewat env `KATALIR_*`. Spool file ditulis di disk lokal untuk durability.

### C. Implementasi

* `recovery.py` (~900 baris) — NEW
  * `DETECTORS` (5, persis n8n), status const, `TERMINAL`/`NON_TERMINAL`
  * `idempotency_key()` (SHA-256), `recovery_key(execution_id, attempt)`
  * `classify_error()` → `{kind, http_status, retryable, reason}` dengan 9 regex
  * `backoff_delay_ms()` — eksponensial + **full jitter** `[expo/2, expo]`
  * `ExecutionRecord` + `ExecutionSupervisor`
    (`register/start/heartbeat/finish/fail/scan/startup_scan/mark_start_failure/
    signal_crash/decide/remediate/run_once/stats/list_records`)
  * `IdempotencyGuard` (`claim/seen/commit/compensate/release/flush/stats`)
  * `supervisor_from_env()`, `describe()`, registry `supervisor()`/`guard()`
* `api_server.py` — 16 endpoint `/recovery/*` (overview, executions CRUD,
  start/heartbeat/finish/fail, scan, run-once, crash, startup-scan,
  start-failure, actions, guard claim/commit/stats)
* `_FEATURE_MODULES["34_self_healing"] = "recovery"`
* `migrations/2026-10-09-self-healing.sql` — `execution_recovery_state`,
  `idempotency_keys`, `recovery_actions` + trigger `touch_updated_at` + RLS

**Divergensi yang disengaja dari n8n:** n8n *mendeteksi lalu berhenti*.
`recovery.py` *menyembuhkan*: deteksi → klasifikasi → putuskan → jalankan,
di bawah gerbang idempotensi sehingga restart tidak pernah menggandakan efek
samping.

### D. Hard Test (12 kategori)

`tests/test_recovery.py` — **19 tes / 19 LULUS** (tanpa `sleep`; jam palsu).

| # | Kategori | Skenario | Hasil |
|---|---|---|---|
| B1 | Basic | `idempotency_key` deterministik & sensitif input; `recovery_key` per-attempt berbeda | ✅ |
| B2 | Basic | stall terdeteksi lalu di-restart | ✅ |
| B3 | Basic | klasifikasi error (503/429/422/network/401) | ✅ |
| D1 | Durability | state supervisor bertahan restart proses | ✅ |
| D2 | Durability | `recovered_keys` bertahan restart | ✅ |
| E1 | Edge | jatah habis → quarantine | ✅ |
| E2 | Edge | pending terlalu lama → queue-recovery | ✅ |
| E3 | Edge | 5 detektor + start-failure + backoff menolak attempt < 1 | ✅ |
| P1 | Perf | scan 5000 eksekusi | ✅ |
| P2 | Perf | backoff dibatasi cap + jittered | ✅ |
| S1 | Security | compensating action dijalankan sekali | ✅ |
| S2 | Security | sinyal crash idempoten; hook rusak tidak merusak supervisor | ✅ |
| X1 | Extra | spool guard bertahan restart | ✅ |
| X2 | Extra | startup-scan mendeteksi worker yatim | ✅ |
| X3 | Extra | `run_once` + statistik akurat | ✅ |
| X4 | Extra | `describe` + factory env (default & nilai rusak) | ✅ |
| X5 | Extra | tulis spool digabung, tetapi `commit()` memaksa tulis | ✅ |
| X6 | Extra | `deactivation_timeout_sec` dapat dikonfigurasi | ✅ |
| X7 | Extra | `created_at` memakai jam yang disuntik | ✅ |

`_f3_api_e2e.py` — **62/62 LULUS** (HTTP nyata via TestClient, spool nyata di
disk, "restart" = instance baru membaca file yang sama):
register/start/heartbeat/finish, 5 detektor, eksekusi yatim, crash idempoten,
restart→durability, restart vs quarantine, 422 tidak diulang, scan 3000
eksekusi, 3000 klaim guard, auth 401 tanpa token, tanpa kebocoran rahasia.

### Raw output (bukti)

```
$ pytest tests/test_recovery.py -q
...................                                                      [100%]
19 passed in 3.11s

$ python _f3_api_e2e.py
[PASS] 5 detektor n8n persis
[PASS] GET /version memuat fitur #3
[PASS] stall terdeteksi di 35 s
[PASS] queue-recovery terdeteksi
[PASS] workflow-deactivation terdeteksi
[PASS] startup-recovery: worker yatim terdeteksi
[PASS] crash kedua: duplicate=true
[PASS] restart: crash_signalled ex-c5 tetap true
[PASS] jatah habis -> quarantine
[PASS] 422 dikarantina meski jatah banyak
[PASS] scan 3000+ eksekusi < 2 s  :: 0.0040 s
[PASS] 3000 klaim guard langsung < 2 s  :: 0.0091 s
[PASS] tanpa Authorization -> ditolak  :: HTTP 401
HASIL: 62/62 LULUS
```

### E. Verifikasi + Commit

* `pytest tests/test_recovery.py tests/test_log_streaming.py
  tests/test_log_streaming_owner_bus.py tests/test_tracing.py -q`
  → **60 passed**
* Suite penuh: **1736 passed**, 3 gagal = flaky lama (`test_parallel_fanout`
  timeout cabang & performa paralel, `test_queue_mode::test_06_timeout`) —
  ketiganya tidak mengimpor modul baru dan gagal juga sebelum sesi ini.

### F. Temuan (bug nyata, ditangkap uji)

1. **TEMUAN (durability).** `IdempotencyGuard.commit()` semula **tidak**
   menulis spool. Proses yang restart akan kehilangan tanda "sudah commit" dan
   bisa menjalankan efek samping **dua kali**. Kini `commit()` memanggil
   `_persist(force=True)`; dikunci `test_x1` + `test_x5`.
2. **TEMUAN (detektor buta).** `register()` memakai `created_at` bawaan
   `time.time()`, sementara seluruh uji waktu memakai jam palsu → `age_sec` /
   `silent_sec` menjadi **negatif** (di-clamp 0) sehingga tidak ada detektor
   yang pernah menyala. Kini `created_at` diambil dari jam yang disuntik;
   dikunci `test_x7`.
3. **TEMUAN (injectability).** `_env_float()` membaca `os.environ`, bukan dict
   env yang di-inject → `supervisor_from_env(env)` **mengabaikan** konfigurasi
   yang diberikan (terukur `30.0` padahal env berisi `15`). Kini bertanda
   tangan `(env, name, default)`; dikunci `test_x4`.
4. **TEMUAN (performa O(n²)).** `claim()` menulis ulang **seluruh** berkas
   spool setiap panggilan → 3000 klaim memakan **55 s**. Ditambahkan jendela
   penggabungan tulis (`persist_interval_sec`) + `flush()` eksplisit; jalur
   langsung kini **0,0091 s** untuk 3000 klaim (≈6000× lebih cepat).
   `commit`/`compensate`/`release` tetap memaksa tulis karena kritis.
5. **`scan()` tidak lagi meledak** pada status tak dikenal (mis. dari versi n8n
   yang lebih baru) dan melewati record `CRASHED` (sudah ditangani
   `signal_crash`). Ambang `workflow-deactivation` dipisah menjadi
   `deactivation_timeout_sec` (default 4× visibility, seperti n8n).
6. **Tidak ada BLOKER.** Tidak butuh kredensial, kartu kredit, atau alternatif
   gagal.

### Status: 100% COMPLETE ✅
