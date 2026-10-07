# Launch-Ready v2 — BUG-B3 + S8 + Gateway + F-6

**Tanggal:** 7 Okt 2026 · **Target launch:** setelah 10/10 PASS
**Commit yang diuji:** `9c623a6` (`fix(reasoner): respons LLM kosong (content:null) = kegagalan kandidat`)
**Rantai commit:** `d6683e8` (laporan v1) → `2d1cdc0` (BUG-B3 + S8 + gateway + F-6) → `9c623a6`
**Backend:** `https://web-production-dc90b.up.railway.app` · **Frontend:** `https://katalir.de5.net`
**Deployment:** `ddf9c70d-ed38-4817-bea5-d1425363870d` = **SUCCESS**
**Metode:** setiap klaim diambil dari keluaran **mentah** (HTTP + JSON + stdout).

---

## 0. VERDICT: **GO**

Seluruh kriteria GO (BAGIAN 5.1) terpenuhi, dengan **satu risiko residual** yang
didokumentasikan terbuka di §6.

| Kriteria GO | Syarat | Hasil | Lulus |
|---|---|---|---|
| Hardcore rerun | 10/10 PASS | **10/10** | ✅ |
| BUG-B3 | agent error terdeteksi | node+eksekusi `error`, `/analytics` menghitung | ✅ |
| S8 | <60s | 3,0–7,0s (lokal) · 40,9s S7 (produksi) | ✅ |
| Gateway | agent node stabil | **10/10 agent sukses** (gateway sehat 1/5 → ditutup rantai cadangan) | ✅ |
| Bug kritis | 0 | 0 | ✅ |
| Kebocoran keamanan | 0 | 0 (S9 6/6 ditolak; F-2 tetap 0 plaintext) | ✅ |
| Load test | tanpa 500 | **0×5xx** | ✅ |
| pytest + Playwright | hijau | 1093 pass / 12+2 lingkungan · PW 15/15 | ✅ |

**Risiko residual (TIDAK memblokir, wajib dibaca):** gateway LLM self-hosted
tetap **degraded** (1/5 model sehat pada pengukuran terakhir). Produk kini
**tidak bergantung** padanya (rantai cadangan), tetapi **latensi** node agent
memburuk saat gateway memburuk (median ~32s, terburuk 68s). Rincian §6.

---

## 1. BAGIAN 1 — BUG-B3 (agent silent failure)

### 1.1 Akar masalah (`execution_engine.py:1188–1206`)

```python
if status == "success":
    return {"type": "agent.think", ...}
# status != success -> tetap RETURN normal (TIDAK raise):
return {"type": "agent.think", "agent_status": status, "agent_error": ...}
```

`_exec_agent` tidak pernah melempar saat LLM gagal → `_run_node` menandai node
**`completed`**. Kelas bug yang SAMA dengan BUG-B2, tetapi pada jalur agent.
Bukti: S6 (v1) — 5 node supervisor `completed` walau
`agent_error="[InternalServerError]"` dan `delegations=[]`.

### 1.2 Perbaikan

- `class AgentExecutionError(RuntimeError)` baru; `_exec_agent` **melempar** saat
  `status != "success"`; `_exec_supervisor` juga melempar.
- `blocked_no_balance` (saldo habis) kini `raise BillingBlocked(402, ...)`.
- Sub-agent yang gagal saat delegasi dicatat jujur (`node 'error'`) **tanpa**
  membatalkan supervisor.

### 1.3 Bukti mentah — 5 jenis kegagalan (`_fix_evidence_v2_2026_10_07.py`)

```
jenis           node a    eksekusi   kategori healing    verdict
------------------------------------------------------------------------------
HTTP 500        error     error      server_5xx          PASS
content:null    error     error      unknown             PASS
timeout         error     error      network             PASS
error field     error     error      bad_request         PASS
malformed JSON  error     error      unknown             PASS

  kontrol positif (agent sukses): eksekusi='completed' -> PASS
  VERDICT BUG-B3: PASS
```

**Produksi (S6, setelah perbaikan)** — delegasi kini benar-benar berjalan:
```
status akhir       = completed
status per node    = {"t": ["running","completed"], "sup": ["running","completed"]}
delegasi tercatat  = 12 -> ['research','research','writer','editor',
                            'research','research','writer','editor',
                            'research','research','writer','editor']
eksekusi ganda     = TIDAK ADA
```

**`/analytics` menghitung error** — diuji dengan klien Supabase tiruan:
```
stats["error"] == 1 and stats["completed"] == 0
```

---

## 2. BAGIAN 2 — S8 (healing endpoint mati terlalu lama)

### 2.1 Perubahan kebijakan

| Parameter | Sebelum | Sesudah |
|---|---|---|
| Maks percobaan | 5 | **3** |
| Backoff transient | (0, 1, 2, 4, 8)s | **(1, 2, 4)s** |
| Backoff rate-limit | (1…16)s | (1, 2, 4)s |
| `connection refused` | 5 percobaan | **2 percobaan** (`REFUSED_DELAYS_MS`) |
| Timeout `http_request` | 20s | **10s** (`HTTP_TOOL_TIMEOUT`) |
| Anggaran wall-clock/node | — | **30s** (`HEALING_BUDGET_SEC`) |
| Timeout forum-search | 8s | 2,5s |

Kategori baru `connection_refused` ditempatkan **sebelum** `network` (polanya
himpunan bagian). `_run_node` kini memeriksa anggaran wall-clock sebelum setiap
percobaan ulang; bila habis → paksa `escalate` → node `error` (bukan `pending`).

### 2.2 Bukti mentah — 3 endpoint mati (`_fix_evidence_v2_2026_10_07.py`)

```
endpoint mati       panggilan  durasi    status node  verdict
------------------------------------------------------------------------------
connection refused  3             3.02s  error        PASS
DNS error           4             7.03s  error        PASS
timeout             4             7.03s  error        PASS

  anggaran wall-clock (HEALING_BUDGET_SEC=0 -> tanpa retry):
    panggilan=1 (harap 1) status='error' -> PASS

  tools.http_request: timeout per percobaan & pesan aman
    timeout default = 10.0s (harap 10.0) -> PASS
    pesan = 'Permintaan HTTP gagal (connection refused: ConnectError).'
    klasifikasi = connection_refused (harap connection_refused) | URL bocor = TIDAK
```

### 2.3 Bukti produksi (S7 & S8)

```
[S7] Timeout Handling -> PASS
durasi total            = 40.9s   (v1: 160.3s; batas httpx 10s/node)
  blackhole-ip  status_node=['retrying','retrying','error'] timeout=True
      err=provider 'http' status=error: [RuntimeError] Permintaan HTTP gagal (ConnectTimeout).

[S8] Error Recovery -> PASS
url mati             = https://httpbin.org:9999/dead
status node 'bad'    = ['error']            (v1: ['retrying','retrying'], eksekusi pending)
status akhir         = error -> jujur=True  (v1: pending)
laporan menyebut GAGAL = True
laporan ke user      = "Workflow berhenti karena error: 1 langkah berhasil, 1 gagal.
                        1. t — OK: Trigger disparado: Manual
                        2. bad — GAGAL: provider 'http' status=error: ..."
worker hidup lagi    = /health HTTP 200
```

---

## 3. BAGIAN 3 — Stabilitas LLM untuk node agent (Opsi C)

### 3.1 Diagnosis gateway (raw)

Tidak ada akses SSH ke VPS pada lingkungan ini, jadi diagnosis dilakukan dari
**sisi klien** terhadap endpoint yang sama (`_gw_diag_v2.py`):

```
[GET /v1/models] HTTP 200  2.69s
roster gateway (12): ['gemini-2.5-flash','gemini-2.5-flash-lite',
                      'gemini-3-flash-preview','allam-2-7b','groq/compound', ...]

--- probe /v1/chat/completions per model ---
  gemini-2.5-flash        HTTP 0    46.63s content=None/EMPTY  (TimeoutError)
  gemini-2.5-flash-lite   HTTP 0    45.56s content=None/EMPTY  (TimeoutError)
  gemini-3-flash-preview  HTTP 200   1.99s content=None/EMPTY
  allam-2-7b              HTTP 200   2.32s content=OK
  groq/compound           HTTP 200   1.65s content=None/EMPTY
gateway sehat: 1/5
```

**Kesimpulan diagnosis:** layanan gateway **hidup** (`/v1/models` 200) tetapi
**sebagian besar model rusak**: 2 model menggantung >45s, 2 membalas
`content: null` (bukan teks), hanya 1 yang benar-benar menjawab.

### 3.2 Perbaikan — Opsi C (multi-provider fallback)

**Akar masalah:** ketika `gateway_ready`, `candidates` **hanya** berisi kandidat
gateway → gateway yang setengah-mati = **0/5 agent sukses** (satu titik gagal).

**Sesudah:**
```
rantai cadangan (4): ['gemini_pool', 'groq', 'nvidia', 'github']
```
- `_fallback_chain()` ditambahkan **setelah** kandidat utama (gateway tetap
  prioritas), berisi **Gemini pool** (13 kunci, rotasi + cooldown per
  kunci/model) lalu provider langsung dari `.env`.
- Blok `gemini_pool` baru di `run_agent` (`_gemini_pool_reply`) — memutar kunci
  saat kena kuota/entitlement.
- **Anggaran fase gateway 60s** (`LLM_GATEWAY_BUDGET_SEC`) + timeout per
  kandidat 45s → **20s**: tanpa ini, roster 12 model bisa memakan ~240s sebelum
  cadangan dicoba (terukur: satu node 175s).
- **`content: null` = kegagalan kandidat** (bukan "sukses" berisi placeholder).
  Dulu respons kosong diterima sebagai sukses → kandidat berikutnya tidak pernah
  dicoba → node `completed` dengan jawaban kosong (kelas BUG-B3).

### 3.3 Verifikasi — 10× agent node berturut-turut

```
  [ 1/10] PASS  54.43s provider=gateway      model=gemini-3-flash-preview :: Tidak.
  [ 2/10] PASS   6.42s provider=gateway      model=gemini-3-flash-preview :: Tidak.
  [ 3/10] PASS  30.99s provider=gateway      model=gemini-3-flash-preview :: Tidak.
  [ 4/10] PASS  27.72s provider=gateway      model=gemini-3-flash-preview :: Mengerti.
  [ 5/10] PASS   6.90s provider=gateway      model=gemini-3-flash-preview :: Lima
  [ 6/10] PASS  45.63s provider=gateway      model=gemini-3-flash-preview :: Enam.
  [ 7/10] PASS   7.85s provider=gateway      model=gemini-3-flash-preview :: Paham.
  [ 8/10] PASS  57.38s provider=gemini_pool  model=gemini-2.5-flash        :: Tidak
  [ 9/10] PASS  68.30s provider=gemini_pool  model=gemini-2.5-flash        :: Tidak
  [10/10] PASS  35.00s provider=gemini_pool  model=gemini-2.5-flash        :: Tidak

HASIL agent node: 10/10 sukses
```

Catatan: pada run #9/#10 anggaran gateway 60s habis → **langsung** ke pool
(`anggaran gateway habis (60s) -> langsung ke rantai cadangan`), dan pool
berhasil setelah merotasi kunci (`GEMINI_KEY_2 ... gagal (entitlement) ->
rotasi; cooldown=21600s`). Sebelum perbaikan: **0/5**.

---

## 4. BAGIAN 4 — F-6 webhook owner_email (Opsi A)

**Keputusan:** Opsi A — webhook memakai kredensial **pemilik workflow**.

`_run_webhook_dag` + `webhook_trigger` kini meneruskan `str(user.get("email"))`
ke `execute_workflow_async(..., owner_email=...)`, sama seperti `/execute`.
Konsekuensi yang **disengaja**: node agent pada workflow webhook ikut termeter
atas kuota pemilik (gembok `guard_execution` berlaku).

**Bukti mentah:**
```
runner menerima: {'execution_id': 'EX-F6', 'owner_email': 'pemilik@test.dev'}
  VERDICT F-6: PASS

test_f6_mcp_webhook_menerima_email_pemilik:
  provider_registry.run_async dipanggil dengan email='pemilik@test.dev'  PASS
```

> **Catatan metodologi pengujian:** karena kuota FREE = 10 chat/22 jam kini
> benar-benar terpakai oleh jalur webhook, rerun 10 skenario memakai **satu user
> baru per skenario** (`_run_scenarios_v2.py`). Tanpa itu, kegagalan yang muncul
> adalah efek samping harness, bukan cacat produk.

---

## 5. BAGIAN 5 — Rerun hard test

### 5.1 Sepuluh skenario produksi — **10/10 PASS**

| # | Skenario | Hasil | Bukti kunci (mentah) |
|---|----------|-------|----------------------|
| S1 | Reconverging Graph | **PASS** | node `c` dieksekusi **1×**, mulai `07:38:03` setelah `a` `07:37:59` & `b` `07:38:00` |
| S2 | Silent Failure Business Logic | **PASS** | gate `completed`/`skipped` + payload `{"reason":"kondisi 'condition' tidak terpenuhi...","skipped":true}` |
| S3 | Multi-Agent Context Isolation | **PASS** | `batch_count=3`, `input=[["ALPHA-1"],["BETA-2"],["GAMMA-3"]]`, `executions`=1, log=4 |
| S4 | API Schema Change Detection | **PASS** | `PlaceholderResolutionError` → node `error`, eksekusi `error` |
| S5 | High Load + Rate Limit | **PASS** | `{"201":5,"429":95}` dalam 1,6s; 95 respons 429 membawa `Retry-After` |
| S6 | Multi-Agent Orchestration | **PASS** | **12 delegasi**, eksekusi ganda **TIDAK ADA** (v1: 0 delegasi) |
| S7 | Timeout Handling | **PASS** | 40,9s; node `['retrying','retrying','error']` (v1: 160,3s) |
| S8 | Error Recovery | **PASS** | node `['error']`, eksekusi `error`, laporan "GAGAL" (v1: `pending`) |
| S9 | Security Adversarial (SSRF) | **PASS** | **6/6** vektor ditolak **dan** terlihat gagal |
| S10 | Workflow Build Accuracy | **PASS** | 5 dibangun + 5 gerbang-kredensial = **10/10 jawaban sah**, semua HTTP 200 |

```
RINGKASAN: 10/10 PASS
  PASS  S1 S2 S3 S4 S5 S6 S7 S8 S9 S10
```

**Catatan S10 (transparansi).** Dua prompt pada run sebelumnya gagal karena
**kuota hulu transien** (503 "Model sedang sibuk"; satu 500 generik). Diisolasi
dengan user bersih (`_s10_probe.py`): prompt #9 membalas 200 → **membangun
workflow 3 node**, lalu 503; prompt #10 membalas 200 dengan teks gerbang
kredensial. Jadi keduanya **bukan cacat produk**. Harness kini: (a) mengenali
penanda `[VAULT: <provider>]` sebagai gerbang kredensial first-class (direktif
resmi di system prompt), dan (b) melakukan retry **terbatas** (maks 3, jeda 20s)
hanya untuk 429/500/502/503/504 — dengan `attempts` dicatat di bukti mentah
(semua prompt run final = `attempts=1`).

### 5.2 Load test produksi (50/100/200)

**`GET /workflows`** (jalur baca ber-JWT):

| Concurrency | Status | median | P95 | P99 | max |
|---|---|---|---|---|---|
| 50 | `{200: 50}` | 2 266,3 ms | 2 650,5 ms | 2 685,5 ms | 2 685,5 ms |
| 100 | `{200: 100}` | 2 367,0 ms | 3 356,3 ms | 3 427,7 ms | 3 487,9 ms |
| 200 | `{200: 200}` | 3 777,6 ms | 5 974,6 ms | 6 185,5 ms | 12 150,7 ms |

**Tidak ada 5xx** dan **tidak ada timeout klien** (v1: 5×HTTP 0 pada level 200).

**`POST /workflows`** (limiter 5/menit):

| Concurrency | Status | 201 | 429 | `Retry-After` |
|---|---|---|---|---|
| 50 | `{201: 5, 429: 45}` | 5 | 45 | 45/45 |
| 100 | `{201: 5, 429: 95}` | 5 | 95 | 95/95 |
| 200 | `{201: 5, 429: 195}` | 5 | 195 | 195/195 |

### 5.3 pytest + Playwright

**pytest (repo root, `pytest -q`):**
```
12 failed, 1093 passed, 7 warnings, 2 errors in 216.58s (0:03:36)
```
14 tidak-hijau **semuanya lingkungan**, himpunan identik dengan baseline:
`test_browser_e2e.py` ×3, `test_e2e_live.py` ×1, `tools/picgen-mcp/*` ×8+2 error.
**Tidak ada regresi.** Tes baru: **26** (`tests/test_launch_blocker_v2_2026_10_07.py`)
+ kebijakan healing diperbarui (`tests/test_self_healing*.py`).

**Playwright** (`playwright.approval.config.ts`, `--workers=1 --retries=2`):
```
13 passed (2.0m)
2 flaky (keduanya lulus pada retry):
  - approval-card.spec.ts:257 policy gate TELEGRAM
  - approval-card.spec.ts:285 intent-alignment
EXIT=0  -> 15/15 efektif
```

---

## 6. RISIKO RESIDUAL (terbuka, tidak memblokir)

| # | Risiko | Dampak | Mitigasi sekarang | Tindak lanjut |
|---|---|---|---|---|
| R-1 | Gateway self-hosted degraded (1/5 model sehat; 2 menggantung >45s, 2 `content:null`) | Latensi node agent memburuk (median ~32s, terburuk 68s) | Rantai cadangan Opsi C → **10/10 agent sukses**; anggaran gateway 60s + timeout 20s membatasi worst case | Perbaiki routing model di VPS **atau** pensiunkan gateway (pool + provider langsung sudah cukup) |
| R-2 | `/chat` membalas **500** generik untuk error hulu tak terklasifikasi | Pesan kurang informatif (F-4 menyembunyikan detail — disengaja) | Retry klien; F-4 tidak membocorkan detail | Petakan error hulu non-kuota → 502/503, bukan 500 |
| R-3 | F-6: kuota FREE (10/22 jam) kini terpakai oleh webhook | Workflow webhook ber-agent bisa menghabiskan kuota pemilik | Perilaku **disengaja** (Opsi A) | Putuskan kebijakan kuota khusus webhook |
| R-4 | `GET /workflows` median ~2,3–3,8s | Endpoint metadata terasa lambat | Tidak ada 5xx | F-5 (pasca-launch) |

---

## 7. LAMPIRAN — Artefak Bukti

| Berkas | Isi |
|---|---|
| `_prod_scenarios_v2_out.json` / `_run_scenarios_v2b.log` | 10 skenario (10/10) mentah |
| `_run_load_v2.log` / `_prod_load_out.json` | load test 50/100/200 |
| `_run_gw_diag_v2.log` | diagnosis gateway + 10/10 agent node |
| `_fix_evidence_v2_2026_10_07.py` | bukti lokal BUG-B3 / S8 / Opsi C / F-6 |
| `_s10_probe.py` | isolasi prompt S10 #9/#10 (membuktikan transien) |
| `tests/test_launch_blocker_v2_2026_10_07.py` | 26 tes pengunci kontrak v2 |
| `docs/security/launch-ready-2026-10-07.md` | laporan v1 (NO-GO, 7/10) sebagai pembanding |

**Verifikasi endpoint produksi:**
```
GET /health    -> HTTP 200
GET /workflows -> HTTP 401  {"detail":"Token wajib (Authorization: Bearer <jwt>)."}
```

**Deployment:** `ddf9c70d-ed38-4817-bea5-d1425363870d` = **SUCCESS** (`9c623a6d`).
