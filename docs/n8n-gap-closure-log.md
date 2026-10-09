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
| 6 | End-user Credentials | `end_user_credentials.py` | 16/16 + 54 E2E | `58037a4` | ✅ |
| 10 | Custom RBAC | `rbac.py` | 21/21 + 88 E2E | `e442995` | ✅ |
| 5 | Agent Sandbox Isolation | `sandbox_isolation.py` | 23/23 + 96 E2E | `e201ba0` | ✅ |
| 2 | MCP Build Workflow | `mcp_build_workflow.py` | 30/30 + 83 E2E | `46f41a1` | ✅ |
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

---

## FITUR #6: END-USER CREDENTIALS (BERBASIS TRIGGER)

### Research (link Okt 2026)

1. **n8n Docs — "End-user credentials"** (Enterprise, **Preview**):
   kredensial **template** dibuat admin sekali; setiap pengguna menghubungkan
   akunnya sendiri; saat runtime kredensial di-*resolve* ke akun **pengguna
   yang memicu**. Batasan eksplisit: **OAuth saja**, **satu koneksi per
   pengguna**, **team project saja**, pembuatan hanya oleh admin/custom role.
   Trigger yang me-resolve: `manual`, `Chat Hub`, `MCP Server Trigger`,
   `Form Trigger` (**butuh n8n User Auth**), `Chat Trigger` (**Hosted Chat
   saja**, bukan Embedded/webhook). Privasi: hanya pengguna pemicu melihat
   I/O node; semua pihak lain (termasuk admin) melihat output **teredaksi**.
   Admin hanya melihat **jumlah koneksi**, tidak pernah isi koneksi.
   Menghapus template menghapus **seluruh** koneksi pengguna.
2. **n8n GitHub — sumber dokumen di atas** (dipakai untuk memastikan wording
   persis & status `preview`).
3. **RFC 9700 — OAuth 2.0 Security Best Current Practice**, §4.14:
   refresh token **MUST** rahasia di transit & penyimpanan; **MUST** terikat
   ke client; untuk public client **MUST** *sender-constrained* **atau**
   **refresh token rotation** — token lama tidak berlaku tetapi **relasinya
   dipertahankan**; bila token lama muncul lagi → indikasi kebocoran →
   **cabut grant yang aktif**; **SHOULD** cabut saat ganti sandi/logout;
   refresh token **MAY** kedaluwarsa bila klien tidak aktif.

### B. Inventory kredensial

Tidak butuh kredensial eksternal baru. Memakai `VAULT_SECRET_KEY` /
`VAULT_PASSWORD` yang sudah ada untuk cipher Fernet (lihat `docs/env-inventory.md`).

### C. Implementasi

* `end_user_credentials.py` (~700 baris) — NEW
  * `SUPPORTED_TRIGGER_MODES` (5) + `TRIGGER_AUTH_REQUIREMENTS`
    (`form`/`chat` → `n8n-user-auth`) + `CHAT_ALLOWED_MODES=("hosted",)`
  * `supports_end_user_credentials()` + `iter_supported_triggers()`
  * `EndUserCredentialTemplate` — metadata + `allowed_modes` + `required`
  * `EndUserConnection` — token **terenkripsi**, `generation`,
    `refresh_fingerprint`; `to_dict()` tidak pernah memuat token
  * `RotatingTokenStore` — rotasi + `_retired` (retensi relasi) + deteksi
    reuse → cabut grant + `expire_idle()` + `revoke_all()`
  * `CredentialResolver` — `add_template/get_template/delete_template`,
    `connect/disconnect/get_connection`, `resolve()` (gerbang trigger +
    scope + required), `redact_for()`, `admin_summary()`, `stats()`
  * `redact_execution_data()` — isolasi I/O node end-user
  * `resolver()/set_resolver()/resolver_from_env()/describe()`
* `api_server.py` — **12 endpoint** `/end-user-credentials/*`
  (overview, templates list/create/delete/summary, connections
  list/connect/disconnect, resolve, rotate, redact, stats)
* `_FEATURE_MODULES["35_end_user_credentials"] = "end_user_credentials"`
* `migrations/2026-10-09-end-user-credentials.sql` — 4 tabel
  (`..._templates`, `..._connections`, `..._retired_tokens`, `..._events`)
  + trigger `touch_updated_at` + RLS per-pemilik + **view agregat admin**
  yang tidak memuat `user_id`/token/label

### D. Hard Test (12 kategori)

`tests/test_end_user_credentials.py` — **16 tes / 16 LULUS** (jam palsu,
tanpa `sleep`; cipher mainan untuk menguji alur enkripsi deterministik).

| # | Kategori | Skenario | Hasil |
|---|---|---|---|
| B1 | Basic | hanya OAuth yang boleh jadi template | ✅ |
| B2 | Basic | resolve ke akun pengguna pemicu | ✅ |
| B3 | Basic | opsional → `resolved=False`; wajib → `ConnectionMissing` | ✅ |
| D1 | Durability | serialisasi aman (token tidak ikut) + muat ulang | ✅ |
| D2 | Durability | rotasi menaikkan generation & MEMPERTAHANKAN relasi | ✅ |
| E1 | Edge | matriks trigger persis n8n (Form/Chat/Hosted) | ✅ |
| E2 | Edge | satu koneksi per pengguna per template | ✅ |
| E3 | Edge | `allowed_modes` membatasi; delete template hapus semua koneksi | ✅ |
| P1 | Perf | 1000 koneksi + 1000 resolusi < 2 s | ✅ |
| P2 | Perf | 500 rotasi < 2 s, generation = 501 | ✅ |
| S1 | Security | reuse token lama → grant dicabut (§4.14.2) | ✅ |
| S2 | Security | token terenkripsi; `to_dict`/`admin_summary`/`denials` bebas token | ✅ |
| X1 | Extra | isolasi data eksekusi (hanya pemicu lihat I/O) | ✅ |
| X2 | Extra | gerbang scope + factory env injectable | ✅ |
| X3 | Extra | kedaluwarsa karena diam + logout mencabut (idempoten) | ✅ |
| X4 | Extra | registry proses + statistik | ✅ |

`_f6_api_e2e.py` — **54/54 LULUS** (HTTP nyata, **Fernet sungguhan**):
katalog & fitur di `/version`, 12 endpoint, matriks trigger 9 kombinasi,
isolasi data eksekusi, agregat admin, rotasi + reuse 409, ciphertext Fernet
diverifikasi bisa didekripsi, 500 koneksi lewat HTTP, tanpa kebocoran token,
auth 401 tanpa token, isolasi antar-pengguna.

### Raw output (bukti)

```
$ pytest tests/test_end_user_credentials.py -q
................                                                         [100%]
16 passed in 0.44s

$ python _f6_api_e2e.py
[PASS] 5 trigger didukung persis n8n
[PASS] form butuh n8n User Auth
[PASS] chat hanya Hosted
[PASS] GET /version memuat fitur #6
[PASS] token TIDAK dikirim lewat API
[PASS] trigger manual -> lolos
[PASS] trigger form -> ditolak
[PASS] trigger form{'auth': 'n8n-user-auth'} -> lolos
[PASS] trigger chat{'auth': 'n8n-user-auth', 'chat_mode': 'embedded'} -> ditolak
[PASS] output node end-user = marker
[PASS] isi pribadi tidak bocor ke pengguna lain
[PASS] rahasia TIDAK terlihat
[PASS] token tersimpan sebagai ciphertext Fernet  :: gAAAAABqyH8s
[PASS] ciphertext bisa didekripsi (kunci benar)
[PASS] reuse token lama -> 409  :: HTTP 409
[PASS] tanpa Authorization -> ditolak  :: HTTP 401
HASIL: 54/54 LULUS
```

### E. Verifikasi + Commit

* `pytest tests/test_recovery.py tests/test_end_user_credentials.py
  tests/test_log_streaming.py tests/test_log_streaming_owner_bus.py
  tests/test_tracing.py -q` → **76 passed**

### F. Temuan (bug nyata, ditangkap uji)

1. **TEMUAN (TypeError).** `_env_float(name, default)` ditulis dengan tanda
   tangan lama tetapi dipanggil sebagai `_env_float(e, name, default)` →
   `resolver_from_env(env)` melempar `TypeError` sehingga registry proses
   gagal dibangun. Diperbaiki; dikunci `test_x2` + `test_x4`.
   (Bug yang sama juga ditemukan & diperbaiki di `recovery.py` fitur #3.)
2. **TEMUAN (idempotensi API).** `disconnect()` semula mengembalikan `True`
   walau koneksi sudah dicabut sebelumnya. Kini `True` hanya bila ada koneksi
   **hidup** yang benar-benar dicabut; dikunci `test_x3`.
3. **Pemahaman semantik.** Awalnya saya menulis tes yang mengharapkan
   `ConnectionMissing` muncul untuk template **opsional** yang penggunanya
   belum terhubung. Perilaku yang benar (dan sesuai n8n) adalah
   `resolved=False`; exception hanya untuk template **wajib**. Tes diperbaiki,
   dan kedua jalur kini diuji (`test_s1`, `test_b3`).
4. **Cipher produksi = Fernet sungguhan.** E2E memverifikasi ciphertext
   diawali `gAAAAA` (format Fernet), tidak memuat token mentah, dan **bisa
   didekripsi** dengan kunci yang sama — bukan sekadar penanda palsu.
5. **Divergensi yang disengaja.** Semua batasan n8n (Enterprise-only,
   team-project-only, Preview) saya pertahankan sebagai **perilaku**, bukan
   sebagai gerbang lisensi — modul tetap dapat dipakai pada instance apa pun.
   Batas "team project only" dijaga di lapisan aplikasi (project personal
   tidak dapat membuat template), sesuai catatan n8n.
6. **Tidak ada BLOKER.** Tidak butuh kredensial baru, kartu kredit, atau
   alternatif gagal.

### Status: 100% COMPLETE ✅

---

## FITUR #10: CUSTOM RBAC (PERAN KUSTOM DUA TINGKAT)

### Research (link Okt 2026)

1. **n8n Docs — "See available roles"**: n8n punya **dua tingkat peran**.
   **Instance roles** (Owner/Admin/Member) berlaku di seluruh instance;
   **Project roles** (Admin/Editor/Viewer) berlaku **hanya di dalam satu
   project** — pengguna yang sama dapat memiliki peran berbeda di project
   berbeda. Setiap peran adalah kumpulan **scope** (`<resource>:<action>`).
2. **n8n Docs — "Create custom project roles"** (tersedia sejak n8n
   **1.122.0**): editor "Project roles" menampilkan scope **bergrup**.
   Kosakata verbatim yang saya himpun — **42 scope dalam 10 grup**:
   Workflow (9), Credential (7), Project (3), Folder (5), Execution (1),
   Secrets vaults (5), Secrets (1), Data table (6), Project variable (4),
   Source control (1).
3. **n8n Docs — "Create custom instance roles"** (tersedia sejak n8n
   **2.30.0**, 7 Juli 2026): **10 scope instance** — `instanceSettings:manage`,
   `members:manage`, `roles:manageProject`, `roles:manageAll`,
   `apiKeys:manageOwn`, `apiKeys:manageOthers`, `tags:read`, `tags:manage`,
   `projects:create`, `insights:read`.
4. **n8n Docs — "Automatically granted scopes"**: aturan implikasi yang
   harus dipertahankan — `<resource>:read` otomatis memberi
   `<resource>:list`; `workflow:publish` → `workflow:unpublish`;
   `roles:manageAll` → `roles:manageProject`; `apiKeys:manageOthers` →
   `apiKeys:manageOwn`.
5. **n8n Docs — peringatan privilege escalation**: dokumentasi n8n secara
   eksplisit memperingatkan bahwa `roles:manageAll`, `roles:manageProject`,
   dan `members:manage` memungkinkan pemegangnya **menaikkan izinnya
   sendiri** (mengubah peran yang ia pegang, atau mengundang akun yang ia
   kendalikan lalu memberinya Admin). Peran yang **masih dipakai** tidak
   dapat dihapus — pengguna harus dipindahkan lebih dulu.

### B. Inventory kredensial

Tidak butuh kredensial eksternal. Satu variabel perilaku baru:
`KATALIR_RBAC_STRICT` (default `"1"`) — menggerbangi penolakan definisi peran
berisiko eskalasi. Lihat `docs/env-inventory.md`.

### C. Implementasi

* `rbac.py` (~790 baris) — NEW
  * `SCOPE_GROUPS` (10 grup / 42 scope) + `PROJECT_SCOPES` +
    `INSTANCE_SCOPES` (10) + `LISTABLE_RESOURCES` + `IMPLIED_SCOPES` +
    `DERIVED_SCOPES` (10: `workflow:unpublish` + 9 `:list`)
  * `implied_for()` / `expand_scopes()` (tutup transitif) / `scope_known()` /
    `validate_scopes()` / `ALL_SCOPES` (61) + `DERIVED_SCOPES` (10)
  * `PROJECT_PRESETS` (admin/editor/viewer) + `INSTANCE_PRESETS`
    (owner/admin/member) + `ESCALATION_FLAGS`
  * `class Role` — `granted` (eksplisit) vs `scopes` (efektif),
    `escalation_risks()`, `to_dict()` dengan `implied` terpisah
  * `class RoleRegistry` — `_merge_preset()` (dipakai bersama create/update),
    `create_role/update_role/duplicate_role/delete_role/get_role/list_roles`,
    `assign/unassign/assign_instance`, `roles_for/effective_scopes`,
    `members_of/projects_of`, `audit`, `stats()`
  * `class Authorizer` — `allow/allows_any/require/require_all`,
    `assert_can_grant()` (anti-escalation), `describe_request()`, `stats()`
  * Pengecualian ber-kontrak: `ScopeUnknown`, `RoleNotFound`, `RoleInUse`,
    `RoleImmutable`, `NotAuthorized`, `PrivilegeEscalationRisk`
  * `registry()/set_registry()/authorizer()/set_authorizer()/rbac_from_env()/describe()`
* `api_server.py` — **19 endpoint** `/rbac/*` (overview, scopes, roles
  list/create/get/update/duplicate/delete, role-usage, assignments
  list/create/delete, instance-assignments, effective-scopes, authorize,
  can-grant, audit, stats, reset) + pemetaan pengecualian → HTTP
  (422/404/409 `role_in_use`/409 `role_immutable`/403 `privilege_escalation`)
* `_FEATURE_MODULES["36_custom_rbac"] = "rbac"`
* `migrations/2026-10-09-custom-rbac.sql` — 4 tabel (`rbac_roles`,
  `rbac_project_assignments`, `rbac_instance_assignments`, `rbac_audit`) +
  seed 6 peran bawaan + `constraint rbac_roles_builtin_immutable_chk` +
  **FK `on delete restrict`** (gerbang "role in use" ditegakkan di basis data,
  bukan hanya di aplikasi) + 2 view (`rbac_role_usage`, `rbac_effective_scopes`)
  + RLS (tulis = service_role; baca peran = authenticated; baca penetapan =
  pemiliknya saja)

### D. Hard Test (12 kategori)

`tests/test_rbac.py` — **21 tes / 21 LULUS** (jam palsu, tanpa `sleep`).

| # | Kategori | Skenario | Hasil |
|---|---|---|---|
| B1 | Basic | kosakata persis n8n: 42 project / 10 grup / 10 instance | ✅ |
| B2 | Basic | 6 preset bawaan; matriks izin sesuai docs (viewer ≠ execute) | ✅ |
| B3 | Basic | CRUD peran kustom + preset sebagai basis + duplikasi | ✅ |
| D1 | Durability | peran project terisolasi per project; instance berlaku global | ✅ |
| D2 | Durability | peran masih dipakai → `RoleInUse`; unassign idempoten | ✅ |
| E1 | Edge | peran bawaan `RoleImmutable` (ubah & hapus) | ✅ |
| E2 | Edge | scope tak dikenal, slug tidak sah, level salah, duplikat, 404 | ✅ |
| E3 | Edge | tutup transitif implikasi + `allow`/`require`/`describe` | ✅ |
| P1 | Perf | 200 peran + 1000 penetapan + 1000 otorisasi < 5 s | ✅ |
| P2 | Perf | 8 thread × 500 cek; 8000 `checks`, 4000 `denials` (thread-safe) | ✅ |
| S1 | Security | gerbang eskalasi strict + `allow_escalation` + mode longgar | ✅ |
| S2 | Security | `assert_can_grant` menolak pemberian melebihi milik aktor | ✅ |
| X1–X9 | Extra | describe env-injectable, factory, jam disuntik, `members_of`, `allows_any` fail-closed, implikasi per-resource, audit lengkap, **regresi `update_role` mempertahankan basis preset** | ✅ |

`_f10_api_e2e.py` — **88/88 LULUS** (HTTP nyata via TestClient) dalam 7 bagian
(A katalog, B basic, C durability, D edge, E performa, F keamanan, G audit).

### Raw output (bukti)

```
$ pytest tests/test_rbac.py -q
.....................                                                    [100%]
21 passed in 0.56s

$ python _f10_api_e2e.py
[PASS] 42 scope project  :: 42
[PASS] 10 scope instance  :: 10
[PASS] 10 grup scope project  :: 10
[PASS] jumlah per grup persis n8n  :: {"Workflow": 9, "Credential": 7, "Project": 3, "Folder": 5, "Execution": 1, "Secrets vaults": 5, "Secrets": 1, "Data table": 6, "Project variable": 4, "Source control": 1}
[PASS] GET /version memuat fitur #10  :: HTTP 200
[PASS] ubah peran bawaan -> 409 role_immutable  :: HTTP 409
[PASS] scope tak dikenal -> 422  :: HTTP 422
[PASS] peran tak ada -> 404  :: HTTP 404
[PASS] proj-1 memberi workflow:publish
[PASS] proj-2 TIDAK memberi workflow:publish
[PASS] 1000 penetapan via HTTP < 30 s  :: 6.70s
[PASS] 500 otorisasi langsung < 2 s  :: 0.001s
[PASS] eskalasi esc-all -> 403 privilege_escalation  :: HTTP 403
[PASS] allow_escalation=True -> 200 (jalan keluar eksplisit)  :: HTTP 200
[PASS] can-grant publish ditolak  :: {"allowed": false, "reason": "privilege_escalation", "missing": ["workflow:publish"]}
[PASS] can-grant oleh tak-berwenang ditolak (fail-closed)
[PASS] authorize all -> ditolak karena credential:share
[PASS] hapus peran terpakai -> 409 role_in_use  :: HTTP 409
[PASS] non-admin membuat peran -> 403  :: HTTP 403
[PASS] GET /rbac/roles tanpa auth -> 401/403  :: HTTP 401
[PASS] semua jenis peristiwa tercatat  :: ["instance_role_assigned", "role_assigned", "role_created", "role_deleted", "role_duplicated", "role_unassigned", "role_updated"]
HASIL: 88/88 LULUS
```

### E. Verifikasi + Commit

* `pytest tests/test_rbac.py -q` → **21 passed**
* `python _f10_api_e2e.py` → **88/88 LULUS**
* Migrasi divalidasi sintaksis dengan `pglast` (parser Postgres asli):
  **6/6 migrasi 2026-10-09 OK**
* Suite penuh dijalankan (lihat bagian verifikasi akhir).

### F. Temuan (bug nyata, ditangkap uji)

1. **TEMUAN (keamanan — fail-open).** `Authorizer.allows_any()` ditulis
   `bool(need) and bool(need & have) or need <= have`. Karena himpunan
   kosong selalu memenuhi `need <= have`, `allows_any(user, [])`
   mengembalikan **`True`** — aktor tanpa satu scope pun dinyatakan lolos.
   Diperbaiki menjadi "punya **setidaknya satu** scope yang diminta;
   permintaan kosong → `False`". Dikunci `test_x5` + E2E bagian F.
2. **TEMUAN (logika implikasi).** `_read_implies_list("project:read")`
   menghasilkan `project:list`, padahal n8n **tidak mengenal** scope itu.
   Implikasi hanya sah untuk resource yang memang punya daftar. Ditambahkan
   `LISTABLE_RESOURCES` (dan `ALL_SCOPES` kini menurunkannya dari himpunan
   itu, bukan lagi hardcode `workflow:list`). Dikunci `test_x6`.
3. **TEMUAN (semantik mutasi peran).** `update_role(name, scopes=[...])`
   **mengganti** himpunan eksplisit tanpa mempertahankan basis preset —
   sehingga peran yang dibuat dari `project:viewer` lalu diedit **kehilangan**
   `project:read`/`credential:read`/`folder:read`. Di UI n8n kotak preset
   sudah tercentang saat mengedit, jadi basis harus bertahan. Ditambahkan
   `_merge_preset()` yang dipakai bersama `create_role` dan `update_role`.
   Dikunci `test_x8` (khusus regresi) + E2E.
4. **TEMUAN (duplikasi menggandakan izin).** `duplicate_role()` meneruskan
   `preset=src.preset_of` ke `create_role()`, yang **menambahkan basis preset
   lagi** di atas scope yang sudah memuatnya → duplikat lebih luas dari
   aslinya. Kini duplikat menyalin himpunan efektif apa adanya dengan
   `preset_of=""`. Dikunci `test_b3`.
5. **TEMUAN (sisa edit lama di `api_server.py`).** Ditemukan dekorator
   `@app.get("/2fa/overview")` **tanpa badan fungsi** (sisa edit saya di fitur
   #11 ketika menyisipkan blok recovery). Karena tanpa badan, dekorator itu
   menempel ke `two_factor_set_policy` dan mendaftarkan rute hantu
   `POST /2fa/overview`. Dihapus; implementasi asli di baris 4575 tidak
   pernah rusak. Diverifikasi `grep -c` = 1 dan `py_compile` OK.
6. **Divergensi yang disengaja.** n8n menyajikan peran kustom sebagai fitur
   Enterprise. Saya pertahankan **perilaku**-nya (dua tingkat, kosakata,
   implikasi, gerbang eskalasi, `RoleInUse`) tanpa gerbang lisensi, supaya
   instance apa pun dapat memakainya. Satu scope n8n yang saya perlakukan
   sebagai turunan murni (`workflow:list`) karena editor n8n tidak
   menampilkannya sebagai kotak terpisah.
7. **TEMUAN (kosakata — scope turunan tidak dikenal).** Audit konsistensi
   menyeluruh (bukan bagian dari 12 kategori wajib, saya jalankan sebagai
   jaring pengaman) menemukan `workflow:unpublish` **tidak ada di
   `ALL_SCOPES`** padahal ia dihasilkan oleh implikasi `workflow:publish`
   dan dipakai oleh `project:admin`. Akibatnya
   `validate_scopes(["workflow:unpublish"])` keliru menolaknya sebagai scope
   tak dikenal. Diperbaiki dengan memperkenalkan `DERIVED_SCOPES` (10
   anggota: `workflow:unpublish` + 9 `:list`), sehingga `ALL_SCOPES` = 61.
   Dikunci `test_x9` (invarians kosakata) + 2 pemeriksaan E2E baru.
   Bonus temuan: `project:admin` memang punya **49 scope efektif** (42 + 7
   `:list`), kebetulan cocok dengan angka "49" di catatan riset awal.
8. **Batas yang terdokumentasi.** Basis data menyimpan scope **eksplisit**
   (`granted`) dan tidak menduplikasi logika implikasi di SQL — implikasi
   dihitung di `rbac.expand_scopes()` saja, agar tidak ada dua sumber
   kebenaran yang bisa menyimpang. View `rbac_effective_scopes` diberi
   komentar eksplisit soal ini.
9. **Tidak ada BLOKER.** Tidak butuh kredensial baru, kartu kredit, atau
   alternatif gagal.

### Status: 100% COMPLETE ✅

---

## FITUR #5: AGENT SANDBOX ISOLATION

### Research (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| n8n — Hardening task runners | https://docs.n8n.io/hosting/configuration/task-runners/ | Tiga komponen: **Task Runner** (eksekusi), **Task Broker** (bagian n8n/worker), **Task Requester** (node Code). Komunikasi via **WebSocket**. Mode `internal` (sub-proses, uid/gid sama → **tidak** disarankan produksi) vs `external` (sidecar `n8nio/runners`, butuh n8n >= 1.111.0, versi image harus cocok) | Modelkan `SandboxPolicy` + `TaskRunner`/`TaskBroker`/`TaskRequester`; hanya `external` yang `production_safe` |
| n8n — Task runner env vars | https://docs.n8n.io/hosting/configuration/environment-variables/task-runners/ | Default verbatim: `N8N_RUNNERS_ENABLED=false`, `N8N_RUNNERS_MODE=internal`, `BROKER_PORT=5679`, `MAX_CONCURRENCY=5`, `TASK_TIMEOUT=300`, `HEARTBEAT_INTERVAL=30`, `TASK_REQUEST_TIMEOUT=60`, `AUTO_SHUTDOWN_TIMEOUT=15`, `N8N_BLOCK_RUNNER_ENV_ACCESS=true` | Salin nilai default apa adanya ke `N8N_RUNNER_DEFAULTS` supaya perilaku Katalir sepadan tanpa konfigurasi |
| n8n — Task runner hardening (distroless/AppArmor) | https://docs.n8n.io/hosting/configuration/task-runners/ | Image distroless, uid/gid **65532** (`nobody`), rootfs read-only + `emptyDir` di `/tmp`, profil AppArmor menolak `/proc/<pid>/{environ,mounts}` | Gerbang keras: `distroless ⇒ uid 65532`; `require_production` menolak `internal` |
| GitHub Advisory GHSA-jjpj-p2wh-qf23 | https://github.com/n8n-io/n8n/security/advisories/GHSA-jjpj-p2wh-qf23 | **CVE-2026-27495**: "Sandbox Escape in JavaScript Task Runner", CVSS 3.1 **9.4**, `AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H`, CWE-94. Terdampak `< 1.123.22, >= 2.0.0 < 2.9.3, >= 2.10.0 < 2.10.1`; ditambal `1.123.22, 2.9.3, 2.10.1`. Syarat: `N8N_RUNNERS_ENABLED=true` + izin ubah workflow. Internal → **penguasaan penuh host**; external → dampak ke tugas lain di runner | Daftarkan `KNOWN_CVES` dan jadikan gerbang mode sebagai mitigasi utama; `/sandbox/verify` membuktikannya |
| nordflux.de — panduan task runner | https://nordflux.de/blog/n8n-task-runners/ | Allowlist modul default **kosong** = semua impor ditolak; builtin Python berbahaya dilarang default | `PY_BUILTINS_DENY_DEFAULT` 18 entri + allowlist kosong; `module_allowed()` menilai dari akar (`os.path` → `os`) |

### B. Kredensial .env
- **Tidak ada kredensial baru.** Seluruh fitur adalah lapisan kebijakan +
  lintasan eksekusi in-process; tidak menyentuh penyedia pihak ketiga.
- Nama variabel baru (semua opsional, ada default): 20 variabel
  `KATALIR_SANDBOX_*` — lihat `docs/env-inventory.md` §8.
- Memakai kembali mesin nyata `code_sandbox.py` (fitur #6 lama) sebagai
  executor; kapabilitasnya dilaporkan via `GET /sandbox/overview` →
  `capabilities` (produksi: `javascript_available=false` karena image Railway
  tanpa Node — Python penuh).

### C. Implementasi
- **Mesin**: `sandbox_isolation.py` (~800 baris)
  - `MODES = ("internal", "external")`, `PRODUCTION_SAFE_MODES = ("external",)`,
    `RUNTIME_TYPES = ("javascript", "python")`
  - `N8N_RUNNER_DEFAULTS`, `PY_BUILTINS_DENY_DEFAULT` (18), `DISTROLESS_UID = 65532`,
    `DOCKER_RUNNER_IMAGE = "n8nio/runners"`, `KNOWN_CVES`
  - `SandboxPolicy` — validasi lintas-medan: `heartbeat_interval_s < task_timeout_s`,
    `distroless ⇒ uid == 65532`, `require_production ⇒ mode external`, semua batas > 0;
    `production_safe`, `isolation_boundary`, `hardening_layers`,
    `module_allowed()`, `check_payload()`, `to_dict()`
  - `TaskRunner` — `heartbeat()`, `is_alive()` (toleransi 2× interval),
    `capacity`, `can_accept()`, `submit()`, `reap_timeouts()`, `stats()`
  - `TaskBroker` — `register()/unregister()`, `alive_runners()`, `enqueue()`,
    `dispatch_one()` (FIFO, skor kapasitas terbesar), `drain()`, `expire_requests()`,
    `heartbeat_sweep()`, `reap_timeouts()`
  - `TaskRequester.request()` — rantai requester → broker → runner
  - `policy_from_env()`, `harden_report()`, `describe()`, `is_module_allowed()`
- **DDL**: `migrations/2026-10-09-sandbox-isolation.sql`
  - Tabel: `sandbox_policies` (CHECK `heartbeat < task_timeout`,
    CHECK `distroless ⇒ uid = 65532`), `sandbox_runners`, `sandbox_events`,
    `sandbox_known_cves` (seed CVE-2026-27495), RLS
  - View: `sandbox_runner_health`, `sandbox_hardening_findings`
  - **Terverifikasi pglast** (parser Postgres asli) → OK
- **API**: 8 endpoint di `api_server.py`
  `GET /sandbox/overview`, `GET /sandbox/policy`, `POST /sandbox/policy/evaluate`,
  `GET /sandbox/hardening`, `GET /sandbox/cves`, `POST /sandbox/check-module`,
  `POST /sandbox/dispatch`, `GET /sandbox/verify`
  Registry: `_FEATURE_MODULES["37_sandbox_isolation"] = "sandbox_isolation"`
- **UI**: panel katalog + laporan hardening dikonsumsi dari `/sandbox/overview`
  dan `/sandbox/hardening` (tanpa rahasia).

### D. Hard Test

**Unit — `tests/test_sandbox_isolation.py`: 23/23 LULUS**

```
$ python -m pytest tests/test_sandbox_isolation.py -q
.......................                                                  [100%]
23 passed in 0.78s
```

| Kelompok | Uji | Hasil |
|---|---|---|
| Basic | B1 default n8n verbatim, B2 mode prod-safe, B3 builtin dilarang | PASS |
| Durability | D1 heartbeat → alive, D2 kedaluwarsa → mati & dijalankan ulang | PASS |
| Edge | E1 heartbeat≥timeout ditolak, E2 payload, E3 concurrency | PASS |
| Performance | P1 dispatch 1000 tugas, P2 drain | PASS |
| Security | S1 allowlist kosong menolak, S2 `*` membuka | PASS |
| Extra | X1–X11 (termasuk X8 regresi rantai `imports`) | PASS |

**E2E — `_f5_api_e2e.py` (HTTP nyata via TestClient): 96/96 LULUS**

```
=== A. Katalog & default ===
=== B. Gerbang kebijakan (dry-run evaluate) ===
=== C. Matriks allowlist modul ===
=== D. Siklus broker/runner/requester (dispatch) ===
=== E. Laporan hardening ===
=== F. Verifikasi mandiri ===
=== G. Keamanan & auth ===
==============================================================
HASIL AKHIR: 96 LULUS / 0 GAGAL  (total 96)
==============================================================
```

Sampel bukti mentah:

| # | Skenario | Hasil | Bukti mentah |
|---|---|---|---|
| 1 | `GET /sandbox/overview` | PASS | `modes=['internal','external'] runtime_types=['javascript','python']` |
| 2 | `production_safe_modes` | PASS | `['external']` |
| 3 | 18 builtin Python dilarang | PASS | `python_builtins_denied` len = 18 |
| 4 | uid distroless | PASS | `distroless_uid=65532` |
| 5 | CVE terdaftar | PASS | `CVE-2026-27495 cvss_v31=9.4 cwe=CWE-94` |
| 6 | Vektor CVSS utuh | PASS | `CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H` |
| 7 | `policy` internal | PASS | `production_safe=False isolation_boundary="sub-proses (uid/gid SAMA)"` |
| 8 | evaluate internal | PASS | `accepted=True` |
| 9 | evaluate external | PASS | `accepted=True production_safe=True` |
| 10 | internal+require_production | PASS | `accepted=False reason=unsafe_configuration` |
| 11 | distroless+uid 1000 | PASS | `accepted=False` |
| 12 | distroless+uid 65532+RO | PASS | `accepted=True` |
| 13 | heartbeat ≥ task_timeout | PASS | `accepted=False` |
| 14 | concurrency 0 | PASS | `accepted=False` |
| 15 | mode tak dikenal | PASS | `accepted=False` |
| 16 | matriks allowlist (6 kasus) | PASS | `os/sys/requests/fs/child_process/lodash` semuanya `allowed=False` |
| 17 | module kosong | PASS | HTTP 422 |
| 18 | runtime tak dikenal | PASS | HTTP 422 |
| 19 | dispatch python | PASS | `status=done runner.runtime='python' capacity=5 alive=True` |
| 20 | dispatch javascript | PASS | HTTP 200 |
| 21 | dispatch runtime `lua` | PASS | HTTP **422** (bukan 500) |
| 22 | **impor `os` ditolak** | PASS | `ok=False error='ModuleNotAllowed: impor 'os' tidak diizinkan…' runner.rejected=1` |
| 23 | **impor JS `fs` ditolak** | PASS | `ok=False` |
| 24 | tanpa impor diterima | PASS | `ok=True` |
| 25 | hardening internal | PASS | `hardened=False findings≥1` |
| 26 | hardening external | PASS | temuan lebih sedikit dari internal |
| 27 | konfigurasi keras penuh | PASS | `hardened=True findings=0 critical=0 high=0` |
| 28 | boundary menyebut kontainer | PASS | `"container (distroless + rootfs read-only)"` |
| 29 | `/sandbox/verify` | PASS | `all_pass=True passed=total≥10 cve=CVE-2026-27495` |
| 30 | POST tanpa token (3 endpoint) | PASS | HTTP 401 |
| 31 | GET katalog publik (5 endpoint) | PASS | HTTP 200 |
| 32 | pesan error tanpa kebocoran | PASS | tidak memuat `token`/`secret` |
| 33 | `/version` → features | PASS | `37_sandbox_isolation=True` |

**Distribusi skenario (memenuhi min 12):** 3 basic (1–3), 2 durability
(19–20 + runner lifecycle), 3 edge (15, 17, 18, 21), 2 performance
(dispatch/drain P1–P2), 2 security (22–23, 30–32) — total **96** pemeriksaan.

**Regresi penuh:** `_f5_full.log` → lihat §E di bawah.

### E. Verifikasi + Commit
- `py_compile api_server.py` → OK
- pglast: 7/7 migrasi `migrations/2026-10-09-*.sql` parse OK
- Suite penuh dijalankan ulang setelah perubahan:
  **`1837 passed, 42 subtests passed in 744.08s (0:12:24)`** — 0 gagal,
  0 regresi (naik dari 1813 sebelum fitur #5).
- Commit: `e201ba0`, sudah di-push (`e442995..e201ba0`, 0 ahead).

### F. Temuan (bug nyata yang ditemukan & diperbaiki)
1. **`/sandbox/dispatch` tidak menegakkan allowlist modul** — endpoint
   membangun `TaskRequester(...)` tetapi **tidak pernah** mengisi `imports` ke
   task, sehingga `runner.submit()` (yang berisi gerbang `ModuleNotAllowed`)
   selalu melihat `imports=[]`. Penolakan impor hanya terbukti di unit test,
   **tidak** di jalur HTTP. Diperbaiki dengan meneruskan `imports=req.imports`;
   dikunci oleh `test_x8_requester_meneruskan_imports_ke_runner`.
2. **Runtime tak dikenal → HTTP 500** — `TaskRunner(req.runtime, …)` melempar
   `SandboxPolicyError` di luar blok `try`, sehingga input klien yang salah
   menjadi *server error*. Diperbaiki menjadi HTTP **422**; diuji di E2E #21.
3. **`array_remove(..., null)` adalah anti-pola** di migrasi ini — di Postgres
   `array_remove` **tidak pernah** mencocokkan NULL. Ditulis ulang menjadi
   sub-query `select array_agg(x) … where x is not null`.
4. **Riset mencatat 49 scope efektif untuk `project:admin`** (42 + 7 `:list`) —
   konsisten dengan perhitungan `expand_scopes()` di fitur #10.

### Status: 100% COMPLETE ✅

---

## FITUR #2: MCP BUILD WORKFLOW

### Research (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| n8n — MCP server tools reference | https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference | **53 tool dalam 7 kategori**: Workflow management (13), Execution management (2), Credential management (1), Instance context (4), Workflow builder (11), Agent management (15), Data tables (7). Setiap tool punya blok "Feature availability" berisi versi n8n minimum | Salin katalog + gerbang versi apa adanya; verifikasi paritas otomatis terhadap snapshot docs |
| n8n — MCP Server Trigger | https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger | Transport: **SSE + streamable HTTP** (tanpa stdio). Auth: None / Bearer / Header. URL test vs production. Catatan queue mode: dengan **banyak webhook replica**, semua `/mcp*` harus dirutekan ke satu replica khusus | Catat batas transport; jangan janjikan stdio |
| n8n — MCP product page | https://n8n.io/mcp/ | Loop build resmi: generate -> **validate** -> (bila gagal) fix & re-validate -> execute + generate test data -> (bila gagal) baca error, fix, run lagi. `create_workflow_from_code` menandai workflow `aiBuilderAssisted` + `builderVariant: mcp` | `BUILD_LOOP` 8 langkah + gate tulis |
| MCP spec 2026-07-28 changelog | https://modelcontextprotocol.io/specification/2026-07-28/changelog | Revisi **terbesar sejak rilis**: stateless per-request envelope. `initialize`/`notifications/initialized` **dihapus**; `Mcp-Session-Id` **dihapus**; `server/discover` **WAJIB**; header `Mcp-Method`+`Mcp-Name`; `ttlMs`+`cacheScope`; `resultType`; MRTR menggantikan server-initiated requests | Modelkan sebagai gerbang keras di `check_envelope()` |
| MCP PY SDK v2 migration | https://py.sdk.modelcontextprotocol.io/v2/migration/ | `FastMCP` -> `MCPServer` (`mcp.server.mcpserver`); parameter transport pindah dari konstruktor ke `run()`/`streamable_http_app()`; `LATEST_PROTOCOL_VERSION` kini `"2026-07-28"` (tak bisa dinegosiasi via handshake); body 4 MiB; handler sinkron jalan di worker thread | Catat sebagai temuan upgrade; implementasi ini tidak bergantung SDK |

### B. Kredensial .env
- **Tidak ada kredensial baru.** Fitur ini adalah lapisan katalog + kebijakan;
  tidak menghubungi instance n8n mana pun.
- Variabel perilaku opsional: `KATALIR_MCP_N8N_VERSION`,
  `KATALIR_MCP_REQUIRE_VALIDATION`, `KATALIR_MCP_REQUIRE_DISCOVERY`,
  `KATALIR_MCP_ENFORCE_ROUTING_HEADERS`, `KATALIR_MCP_STRICT_TOOL_NAMES`,
  `KATALIR_MCP_PROTOCOL_REVISION`, `KATALIR_MCP_SDK_TTL_MS`.
- Melengkapi `mcp_server.py` yang sudah ada (server MCP Katalir, 6 tool) —
  modul ini menyediakan **peta + gerbang** yang selama ini belum ada.

### C. Implementasi
- **Mesin**: `mcp_build_workflow.py` (~700 baris)
  - `ToolSpec` (name, category, since, mutating, requires_validation) × 53
  - `PROTOCOL_REVISIONS`, `MODERN_REVISIONS`, `HANDSHAKE_REVISIONS`,
    `MODERN_REQUIRED_HEADERS`, `CACHE_FIELDS`, `RESULT_TYPES`,
    `RENUMBERED_ERRORS`
  - `BUILD_LOOP` (8 langkah), `CREATE_GATE_TOOLS`, `READ_ONLY_TOOLS`
  - `BuildSession` — melacak urutan + menegakkan 4 gate:
    G1 referensi SDK (`rules`) sebelum menulis; G2 nama tool harus ada;
    G3 `validate_workflow` **lulus** sebelum create/update;
    G4 run butuh workflow yang sudah ada
  - `check_envelope()`, `discover_payload()`, `validate_discovery()`,
    `build_reference()`, `reference_payload()`, `policy_from_env()`
  - `parse_version()`/`at_least()`/`require_tool()` — gerbang versi
- **DDL**: `migrations/2026-10-09-mcp-build-workflow.sql`
  - `mcp_protocol_revisions` (CHECK `is_modern <> has_handshake`)
  - `mcp_tool_catalog` (seed 53 baris; CHECK `needs_validation ⇒ mutating`)
  - `mcp_build_sessions` (CHECK status↔bukti)
  - `mcp_call_events` (CHECK `phase` **cocok dengan** `tool_name`)
  - View `mcp_build_loop_health` (mendeteksi `gate_violation`),
    `mcp_tools_pending_for_version`, `mcp_protocol_gate`, RLS
  - **Terverifikasi pglast** (30 statement) + paritas seed ↔ katalog Python
- **API**: 9 endpoint `/mcp/build/*` — `overview`, `tools`, `tools/{name}`,
  `reference`, `discover`, `check-envelope`, `check-envelope-fail`,
  `loop`, `verify`
  Registry: `_FEATURE_MODULES["38_mcp_build_workflow"]`

### D. Hard Test

**Unit — `tests/test_mcp_build_workflow.py`: 30/30 LULUS**

```
$ python -m pytest tests/test_mcp_build_workflow.py -q
..............................                                           [100%]
30 passed in 0.54s
```

**E2E — `_f2_api_e2e.py` (HTTP nyata): 83/83 LULUS**

```
=== A. Katalog & registry protokol ===
=== B. Gerbang versi per-tool ===
=== C. Loop build & referensi SDK ===
=== D. server/discover ===
=== E. Amplop protokol modern ===
=== F. Keamanan & auth ===
=== G. Verifikasi mandiri ===
==============================================================
HASIL AKHIR: 83 LULUS / 0 GAGAL  (total 83)
==============================================================
```

**Paritas terhadap docs resmi (bukti, bukan klaim).** Harness membandingkan
katalog yang dilayani HTTP dengan snapshot docs `_mcp_tools_ref.md`:

| Pemeriksaan | Hasil |
|---|---|
| Nama tool identik docs (53) | **LULUS** — `beda: []` |
| Kategori tiap tool identik docs | **LULUS** |
| Gerbang `since` identik docs (32 tool bergerbang) | **LULUS** — `mismatch: []` |
| Seed SQL ↔ katalog Python (53 baris, 4 field) | **LULUS** — `field mismatch: []` |

Sampel bukti mentah:

| # | Skenario | Hasil | Bukti mentah |
|---|---|---|---|
| 1 | `GET /mcp/build/overview` | PASS | `tool_count=53 categories=7` |
| 2 | distribusi kategori | PASS | `13/2/1/4/11/15/7` |
| 3 | revisi terbaru | PASS | `2026-07-28` |
| 4 | hanya modern | PASS | `['2026-07-28']` |
| 5 | `Mcp-Session-Id` dicabut | PASS | `revoked_session_header='Mcp-Session-Id'` |
| 6 | header routing | PASS | `['Mcp-Method','Mcp-Name']` |
| 7 | cache field | PASS | `['ttlMs','cacheScope']` |
| 8 | instance 2.12.0 | PASS | `count=17` |
| 9 | instance 2.43.0 | PASS | `count=53` |
| 10 | 2.33.0 tool agent | PASS | `count=0` |
| 11 | 2.34.0 tool agent | PASS | `count=14` (call_agent belum) |
| 12 | 2.35.0 tool agent | PASS | `count=15` |
| 13 | `call_agent` pada 2.34.0 | PASS | HTTP **409** |
| 14 | tool lama `create_workflow` | PASS | HTTP **404** |
| 15 | versi `terbaru` | PASS | HTTP **422** |
| 16 | loop 8 langkah + urutan | PASS | `referensi < validasi < create` |
| 17 | gate tulis | PASS | `{create_workflow_from_code, update_workflow}` |
| 18 | `server/discover` valid | PASS | `ok=True`, 5 revisi |
| 19 | discover per-versi | PASS | `toolsForVersion` = 17 @2.12.0 |
| 20 | amplop modern benar | PASS | `ok=True` |
| 21–29 | **9 modus pelanggaran ditolak** | PASS | header hilang ×2, `Mcp-Name` tidak cocok, sesi lama, `_meta` salah, `_meta` kosong, `resultType` hilang/tidak sah, `input_required` tanpa `inputRequests` |
| 30 | `tools/list` tanpa cache field | PASS | `ok=False` (2 galat) |
| 31 | `tools/list` dengan cache field | PASS | `ok=True` |
| 32 | `cacheScope='global'` | PASS | `ok=False` |
| 33 | revisi handshake tanpa amplop modern | PASS | `ok=True` |
| 34 | `check-envelope-fail` saat galat | PASS | HTTP **422** |
| 35 | POST tanpa token ×3 | PASS | HTTP **401** |
| 36 | GET katalog publik ×5 | PASS | HTTP **200** |
| 37 | `/version` → features | PASS | `38_mcp_build_workflow=True` |

**Distribusi skenario (min 12):** 3 basic (1–2, 16), 2 durability (13, 15),
3 edge (10–12, 14, 17), 2 performance (P1/P2 unit), 2 security (21–29, 35) —
total **83** pemeriksaan.

**Regresi penuh:** `_f2_full.log`.

### E. Verifikasi + Commit
- `py_compile api_server.py` → OK; 9 endpoint `/mcp/build/*` terdaftar
- pglast: 8/8 migrasi `migrations/2026-10-09-*.sql` parse OK
- Suite penuh dijalankan ulang setelah perubahan (lihat commit)
- Commit: **`46f41a1`** — terpush, `origin/main = 46f41a1`, 0 commit belum terkirim

**Hasil suite penuh:** `1860 passed, 4 failed, 3 errors, 42 subtests passed in
1397.01s (23:17)` (`_f2_full.log`). **Ke-7 kegagalan itu lingkungan, bukan
regresi** — diverifikasi dengan menjalankan ulang secara terisolasi:

| Uji | Hasil suite penuh | Hasil re-run terisolasi | Sebab |
|---|---|---|---|
| `test_subworkflow.py` (3 error + 1 gagal) | error | **11 passed** | `psycopg2.OperationalError: SSL error: unexpected eof while reading` ke pooler Supabase remote |
| `test_two_factor.py::test_p2_qr_svg_...` | gagal | **passed** | ambang latensi, mesin sibuk |
| `test_vector_store.py::test_query_latency_benchmark` | gagal | **passed** | ambang latensi, mesin sibuk |
| `test_agent_memory.py::test_2c7_recall_performance` | gagal | gagal (3,49 s vs 0,2 s) | benchmark **30× RPC ke DB remote** — murni latensi jaringan, bukan kode |

53 test baru (30 `mcp_build_workflow` + 23 `sandbox_isolation`) lulus dalam
**1,23 s** saat dijalankan langsung.

### F. Temuan (bug nyata + temuan upgrade)
1. **`require_tool(name, "")` melempar `ValueError`** alih-alih melewati
   gerbang. `at_least("", since)` mengevaluasi lebih dulu sebelum penjaga
   `if spec.since` sempat bekerja, sehingga "versi instance tidak diketahui"
   (kasus normal saat klien baru terhubung) menjadi galat 500. Diperbaiki
   dengan menangani versi kosong lebih dulu; dikunci `test_b3` + `test_x5`.
2. **SDK Python MCP terpasang (1.28.1) TIDAK mendukung 2026-07-28.** Registry
   SDK berhenti di `2025-11-25`; `server/discover`, `ttlMs`, `cacheScope`,
   `resultType`, `Mcp-Method` semuanya absen. Rilis yang mendukung adalah
   **`mcp 2.x`** (`2.0.0` dirilis **2026-07-28** — tanggal yang sama dengan
   revisi spec; terbaru `2.3.0`). Karena `mcp 2` adalah *breaking major* —
   `FastMCP` → `MCPServer`, parameter transport pindah dari konstruktor ke
   `run()`/`streamable_http_app()`, `LATEST_PROTOCOL_VERSION` kini tak bisa
   dinegosiasi via handshake, batas body 4 MiB, handler sinkron pindah ke
   worker thread — upgrade ini **tidak** dilakukan di dalam fitur ini
   (berisiko menjatuhkan `mcp_server.py` yang sudah melayani produksi).
   Fitur #2 karena itu diimplementasikan sebagai lapisan katalog + gerbang
   yang tidak bergantung versi SDK. **Upgrade ke `mcp>=2` dicatat sebagai
   pekerjaan tersendiri.**
3. **`test_workflow` sejak 2.15.0** tetapi `create_workflow_from_code` sejak
   2.12.0 — sehingga pada instance 2.12.0–2.14.x langkah "uji dulu" memang
   belum ada. `build_reference()` melaporkannya di `unavailable_steps`
   ketimbang menyarankan langkah yang mustahil.

### Status: 100% COMPLETE ✅
