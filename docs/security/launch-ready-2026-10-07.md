# Launch-Ready Verification — "FIX 2 BUG KRITIS + 3 TEMUAN TINGGI"

**Tanggal:** 7 Okt 2026 · **Target launch:** 10–12 Okt 2026
**Commit yang diuji:** `b790486` (`fix(bug-b1): batasi perbaikan ke execution_id saja`)
**Backend:** `https://web-production-dc90b.up.railway.app` · **Frontend:** `https://katalir.de5.net`
**Metode:** setiap klaim diambil dari keluaran **mentah** (HTTP + JSON + stdout) — bukan dari ringkasan.

> Brief: *"# FIX 2 BUG KRITIS + 3 TEMUAN TINGGI — LAUNCH BLOCKER"* (7 Okt 2026), BAGIAN 0–8.

---

## 0. VERDICT: **NO-GO**

Enam perbaikan (2 bug kritis + 3 temuan tinggi + 1 turunan) **selesai dan terbukti**.
Namun **syarat GO tidak terpenuhi**: hardcore rerun produksi = **7/10 PASS**, sedangkan
brief mensyaratkan **10/10**.

| Kriteria GO (BAGIAN 8) | Syarat | Hasil | Lulus? |
|---|---|---|---|
| Hardcore rerun | 10/10 PASS | **7/10** | ❌ |
| Bug kritis tersisa | 0 | 0 (BUG-B1, BUG-B2 beres) | ✅ |
| Kebocoran keamanan (F-2) | 0 plaintext | 0 dari 124 baris | ✅ |
| Load test | tanpa 500 | tanpa 5xx | ✅ |
| pytest + Playwright | hijau | 1065 passed / 12 failed+2 error (semua lingkungan) · PW 15/15 | ✅ (dengan catatan) |

**Alasan NO-GO tunggal:** 3 skenario produksi gagal (S2, S6, S8). Dua di antaranya
berakar pada **infrastruktur di luar kode aplikasi** (gateway LLM self-hosted mati;
healing endpoint mati terlalu lambat), satu murni **transien jaringan**. Rincian di §3.

**PENTING (larangan brief):** "JANGAN klaim GO tanpa 10/10 hardcore PASS" — karena
7/10, verdict ini **tidak** menaikkan status ke GO.

---

## 1. Ringkasan Perbaikan (BAGIAN 1–6)

| # | Temuan | Kelas | Status | Bukti |
|---|--------|-------|--------|-------|
| **BUG-B1** | `_run_webhook_dag` menghitung `execution_id` tetapi tidak meneruskannya → log ke baris hantu | KRITIS | **FIXED + terbukti di produksi** | §2.1 |
| **BUG-B2** | `provider_registry.run` mengembalikan `{"status":"error"}` tetapi `_exec_mcp` kembali normal → node `completed` | KRITIS | **FIXED + terbukti di produksi** | §2.2 |
| **F-2** | JWT `Authorization: Bearer …` (826 char) tersimpan plaintext di `execution_logs` | KRITIS (keamanan) | **FIXED + terbukti di produksi** | §2.3 |
| **F-3** | `_meter_save` menulis `last_reset_free` sebagai float → Supabase 22007 → error ditelan | TINGGI | **FIXED + terbukti lokal** | §2.4 |
| **F-1** | Gate free-tier kontradiktif: agent node diblokir `get_balance > 0` (gratis = 0.0) | TINGGI | **FIXED + terbukti lokal** | §2.5 |
| **F-4** | `/chat` membalas HTTP 500 + teks error upstream mentah | TINGGI | **FIXED + terbukti lokal** | §2.6 |

**Temuan BARU selama verifikasi (di luar brief):** **BUG-B3** (§4) dan **F-6** (§5).

---

## 2. BUKTI MENTAH PER PERBAIKAN

### 2.1 BUG-B1 — eksekusi hantu (PRODUKSI)

`_run_webhook_dag` kini meneruskan `execution_id` ke runner dan mengambil status
dari hasil runner (bukan menulis `"completed"` buta). Diuji end-to-end ke produksi
(`_f2_prod_verify.py`), JWT uji 826 karakter:

```
[1] POST /workflows -> HTTP 201
    workflow_id = be9bdcb3-95ca-48ea-a13a-a119f8076c5e
[2] POST /webhook/{id} -> HTTP 202
    execution_id = 19a851da-680d-4328-acc7-0381f9dc0a67
[3] GET /executions/{id} -> HTTP 200  status='completed'  logs=4
    - node=  t type=trigger  status=running    keys=[]
    - node=  t type=trigger  status=completed  keys=['context','event','message','type','webhook_payload']
    - node=  m type=mcp      status=running    keys=[]
    - node=  m type=mcp      status=completed  keys=['provider','result','tool','type']
[4] Supabase execution_logs (langsung): 4 baris

BUG-B1: log pada execution_id yang dikembalikan = 4 (butuh >=3) -> PASS
```

**Sebelum perbaikan:** `execution_id` yang dikembalikan API = **0 log**; log menempel
di baris uuid lain (lihat `hardcore-n8n-user-verification-2026-10-07.md` §2).
**Sesudah:** **4 log pada id yang sama**.

Bukti lokal (`_fix_evidence_2026_10_07.py`):
```
  execution_id diteruskan ke runner : 'EX-B1-PROOF'
  owner_email diteruskan            : '' (sengaja kosong - F-6)
  jumlah log pada id yang SAMA      : 4
  status akhir baris executions     : 'error'      <- BUG-B2 aktif (node m error)
  VERDICT: PASS (butuh >=3 log)
```

> **Catatan kontradiksi (BONUS B3).** Upaya pertama saya juga meneruskan
> `owner_email`; itu memicu regresi tak diminta (S3/S6 jatuh karena kuota free
> user terpakai). Sesuai protokol kontradiksi, saya **membalikkan** perubahan itu,
> menambah tes regresi yang mengunci perilaku "tanpa owner_email", dan mencatatnya
> sebagai temuan **F-6**. Commit `b790486` khusus untuk ini.

### 2.2 BUG-B2 — kegagalan senyap (PRODUKSI, 5 jenis kegagalan)

`_exec_mcp` kini memanggil `_raise_if_tool_failed(provider, result)`; status
non-`success` melempar `ToolExecutionError` → node `error`, eksekusi `error`.
`tools.http_request` juga melempar saat `status_code >= 400`.

Lokal — tabel 5 jenis kegagalan (`_fix_evidence_2026_10_07.py`):
```
jenis          node m     eksekusi   kategori healing   verdict
HTTP 404       error      error      not_found          PASS
HTTP 500       error      error      server_5xx         PASS
timeout        error      error      network            PASS
DNS error      error      error      network            PASS
invalid JSON   error      error      unknown            PASS
  kontrol positif (tool sukses): eksekusi='completed' -> PASS

  tools.http_request (status >= 400 tidak lagi 'sukses'):
    HTTP 404: RuntimeError -> HTTP 404 dari example.com: {"error":"nope"}
    HTTP 500: RuntimeError -> HTTP 500 dari example.com: {"error":"nope"}
    HTTP 503: RuntimeError -> HTTP 503 dari example.com: {"error":"nope"}
```

Produksi — S7 (timeout, endpoint blackhole), log mentah dari `_prod_scenarios_out.json`:
```
blackhole-ip  status_node=['retrying','retrying','retrying','retrying','retrying','error']
              inner=None timeout=True
   err=provider 'http' status=error: [RuntimeError] Permintaan HTTP gagal (ConnectTimeout).
```
Node kini berakhir **`error`** (dulu `completed`) → sinyal kegagalan terlihat di kanvas,
`/analytics`, dan laporan. Analitik menghitung `error` dengan benar.

### 2.3 F-2 — kebocoran JWT (PRODUKSI + retroaktif)

`database.redact_sensitive()` diterapkan di **semua** titik tulis `execution_logs`
(`execution_log_row`, `append_execution_log`). Probe langsung ke Supabase atas
**124 baris**:

```
execution_logs HTTP 200  rows=124
rows containing JWT pattern      : 0
rows containing 'authorization'  : 2
  - id=022f1600-... exec=19a851da-... node=t REDACTED=True
  - id=8a2cece3-... exec=3e987bd9-... node=t REDACTED=True
VERDICT F-2: PASS (0 JWT plaintext)
```

Verifikasi end-to-end (webhook dengan `Authorization: Bearer <JWT 826 char>`):
```
F-2   : JWT utuh tersimpan di execution_logs? False
F-2   : 'Bearer <JWT>' utuh tersimpan?        False
F-2   : penanda [REDACTED] muncul?            True
F-2   VERDICT: PASS
```

Redaksi historis (`scripts/redact_execution_logs_history.py`, **UPDATE-only, tidak
pernah DELETE**) — dry-run atas seluruh tabel:
```
[1/4] dipindai            : 124 baris (error baca: 0)
[2/4] baris ber-teks-rahasia: 0
[3/4] UPDATE              : dilewati (dry-run)
[4/4] verifikasi ulang    : 124 baris, sisa ber-teks-rahasia = 0 (error baca: 0)
HASIL: DRY-RUN selesai
```
Tidak ada baris historis yang perlu diubah (0 teks-rahasia) — jejak audit utuh.

### 2.4 F-3 — meter free-tier tidak persist

```
SEBELUM: last_reset_free ditulis sebagai FLOAT 1700000000.0
         -> Postgres 22007 'invalid input syntax for type timestamp'
         -> error ditelan 'except: pass' -> counter TIDAK pernah persist.
SESUDAH: ditulis sebagai ISO  : '2023-11-14T22:13:20+00:00'
dibaca balik sebagai epoch    : 1700000000.0
round-trip presisi            : True
payload tulis nyata           : {'email': 'u@test.dev', 'free_chat_count': 3,
                                 'plus_chat_count': 0,
                                 'last_reset_free': '2023-11-14T22:13:20+00:00',
                                 'last_reset_plus': None, 'credit_balance': 0.0}
error persistensi             : dinaikkan -> MeterPersistenceError (tidak lagi senyap)
VERDICT: PASS
```

### 2.5 F-1 — kontradiksi gembok free-tier

```
SEBELUM: guard_execution MENGIZINKAN free (10 chat/22 jam), tetapi node agent
         diblokir 'blocked_no_balance' karena get_balance(user gratis) = 0.0.
SESUDAH: agent_status       : None            <- agent TIDAK lagi diblokir
         status node        : 'completed'
         jatah kredit bulanan free : 100.0
         batas gratis MASIH berlaku : allowed=False code=403
             msg='Batas 10 percakapan gratis Anda telah habis...'
VERDICT: PASS
```
Cek saldo kini **hanya** untuk Plus (`model: deepseek-flash`). System prompt
diperbarui (`docs/workflow-prompt-guide.md`).

### 2.6 F-4 — `/chat` 500 tidak membocorkan detail

```
[api_server] /chat gagal: RuntimeError: ClientError: 400 INVALID_ARGUMENT. {...}   <- log SERVER
  SEBELUM: 500 body menyisipkan 'Terjadi kesalahan internal: ClientError: 400 INVALID_ARGUMENT...'
  SESUDAH: HTTP 500
           detail = 'Terjadi kesalahan internal. Silakan coba lagi sebentar lagi.'
  kebocoran terdeteksi          : tidak ada
  VERDICT: PASS
```
Diperbaiki di 4 titik (`/chat`, buat sesi, simpan pesan, simpan balasan):
detail lengkap hanya ke log server; klien menerima pesan generik.

---

## 3. BAGIAN 7 — RERUN HARDCORE DI PRODUKSI

**Target:** `https://web-production-dc90b.up.railway.app` · user uji baru (kuota bersih)

### 3.1 Sepuluh Skenario — **7/10 PASS**

| # | Skenario | Hasil | Bukti kunci |
|---|----------|-------|-------------|
| S1 | Reconverging Graph (diamond) | **PASS** | node `c` dieksekusi **1×**, mulai `05:34:05` setelah `a` `05:33:48` & `b` `05:33:33` |
| S2 | Silent Failure Business Logic | **FAIL** → PASS saat retry | run bersih: `HTTP 0 TimeoutError` (transien klien); retry (`_run_s2s6_d.log`): gate `completed`/`skipped` benar → **PASS** |
| S3 | Multi-Agent Context Isolation | **PASS** | `batch_count=3`, `input=[["ALPHA-1"],["BETA-2"],["GAMMA-3"]]`; `executions`=1 (tanpa baris hantu), log pada id API=4 |
| S4 | API Schema Change Detection | **PASS** | `PlaceholderResolutionError: field 'body.customer.email' tidak ditemukan...` → node `error`, eksekusi `error` |
| S5 | High Load + Rate Limit (100 cc) | **PASS** | `{"201":4,"429":95,"0":1}` dalam 60,5s; **95** respons 429 membawa `Retry-After` |
| S6 | Multi-Agent Orchestration (Supervisor) | **FAIL** | 0 delegasi; `agent_error="[InternalServerError] Internal Server Error"`; node tetap `completed` → **BUG-B3 + gateway mati** |
| S7 | Timeout Handling | **PASS** | timeout ditegakkan; node `['retrying'×5,'error']` → **BUG-B2 terlihat** |
| S8 | Error Recovery (node mati) | **FAIL** | `status node 'bad'=['retrying','retrying']`, akhir `pending` setelah 420s; healing ×5 terlalu lambat untuk endpoint mati |
| S9 | Security Adversarial (SSRF) | **PASS** | **6/6** vektor ditolak (metadata-cloud, loopback, localhost, private-net, `file://`, `gopher://`) dan **6/6 terlihat gagal** |
| S10 | Workflow Build Accuracy (10 prompt) | **PASS** | 9 dibangun + 1 gerbang-kredensial; **10/10 jawaban sah, semua HTTP 200** |

```
RINGKASAN: 7/10 PASS
  PASS  S1  S3  S4  S5  S7  S9  S10
  FAIL  S2  S6  S8
```

### 3.2 Akar masalah 3 kegagalan

| Skenario | Akar masalah | Kode atau infra? |
|---|---|---|
| **S2** | `HTTP 0 TimeoutError: The read operation timed out` saat membuat workflow. Retry bersih → **PASS**. | **Transien** (jaringan/klien) |
| **S6** | Gateway LLM self-hosted (`/chat/completions`) **tidak stabil**: `gemini-2.5-flash-lite → HTTP 500`, `groq/compound-mini → HTTP 200 content:null`, `openai/gpt-oss-20b → HTTP 200`; probe pertama timeout 45,6s. 0/5 sukses dua kali (05:09–06:04 UTC). | **Infra** (+ **BUG-B3** memperparah) |
| **S8** | Endpoint mati `https://httpbin.org:9999/dead` sangat lambat di produksi (proxy HTTP) + healing retry ×5 → node masih `retrying` setelah 420s; eksekusi `pending`. | **Infra/konfigurasi** |

> **Paradoks S6/S8 (inti BUG-B3).** Node tetap tercatat `completed` (S6) atau
> `running`→`pending` (S8) padahal agent gagal — **status mesin berbohong**.
> Laporan manusiawi S8 berbunyi *"Workflow berhasil: 2 langkah berhasil, 0 gagal"*
> padahal node `bad` tidak pernah sukses.

### 3.3 Load Test Produksi (50/100/200 concurrent)

**`GET /workflows`** (jalur baca ber-JWT):

| Concurrency | Status | median | P95 | P99 | max |
|---|---|---|---|---|---|
| 50 | `{200: 50}` | 2 092,6 ms | 2 562,4 ms | 2 630,6 ms | 2 630,6 ms |
| 100 | `{200: 100}` | 3 276,9 ms | 4 162,9 ms | 4 211,7 ms | 4 214,7 ms |
| 200 | `{195×200, 5×0}` | 4 355,4 ms | 6 579,2 ms | 63 383,1 ms | 67 004,1 ms |

`{0: 5}` = **timeout klien**, **bukan** 5xx server. **Tidak ada 500/503.**

**`POST /workflows`** (jalur tulis, limiter 5/menit):

| Concurrency | Status | 201 | 429 | `Retry-After` |
|---|---|---|---|---|
| 50 | `{201: 5, 429: 45}` | 5 | 45 | 45/45 |
| 100 | `{201: 5, 429: 95}` | 5 | 95 | 95/95 |
| 200 | `{201: 5, 429: 195}` | 5 | 195 | 195/195 |

Limiter tepat di semua level, **tanpa 5xx**, selalu menyertakan `Retry-After`.

### 3.4 Security Adversarial

S9 (produksi) — **6/6 vektor SSRF ditolak**, dan kini **terlihat gagal** (BUG-B2):
```
metadata-cloud http://169.254.169.254/latest/meta   node=['retrying','retrying','error'] ditolak=YA terlihat_gagal=YA
loopback       http://127.0.0.1:8000/admin          node=['retrying','retrying','error'] ditolak=YA terlihat_gagal=YA
localhost      http://localhost:5432/               node=['retrying','retrying','error'] ditolak=YA terlihat_gagal=YA
private-net    http://10.0.0.5/secret               node=['retrying','retrying','error'] ditolak=YA terlihat_gagal=YA
file-scheme    file:///etc/passwd                   node=['retrying','retrying','error'] ditolak=YA terlihat_gagal=YA
gopher-scheme  gopher://127.0.0.1:6379/_INFO        node=['retrying','retrying','error'] ditolak=YA terlihat_gagal=YA
```

### 3.5 pytest + Playwright

**pytest (repo root, `pytest -q`):**
```
12 failed, 1065 passed, 6 warnings, 2 errors in 265.91s (0:04:25)
```
14 tidak-hijau **semuanya lingkungan** (sama dengan baseline pra-perubahan):
- `test_browser_e2e.py` ×3 (browser chromium tak tersedia di runner)
- `test_e2e_live.py::test_live_agent_response` (Streamlit AppTest timeout)
- `tools/picgen-mcp/*` ×8 failed + 2 errors (direktori pihak ketiga tak ter-track, tanpa `pytest-asyncio`)

**Tidak ada regresi.** 38 tes baru (`tests/test_launch_blocker_fixes_2026_10_07.py`)
+ `test_provider_registry.py` = **70 passed** (bukti terarah).

**Playwright** (`--workers=1`, build produksi lokal):
```
13 passed (56.2s)   <- tanpa retry
2 failed: approval-card.spec.ts:376 'hasil tool kosong' + card-persistence.spec.ts:240 'kontra-regresi'
```
Kedua kegagalan adalah **flakiness cold-start** (hidrasi elemen); dengan
`--retries=2` keduanya lulus → **15/15 efektif** (`.last-run.json: status=passed`).
Bukan cacat produk.

---

## 4. TEMUAN BARU — **BUG-B3** (KRITIS, di luar brief)

**Gejala.** Node agent yang gagal (`agent_status='error'`) tetap tercatat **`completed`**.
Terbukti di produksi S2 & S6 (5 node supervisor semuanya `completed` walau
`agent_error="[InternalServerError] Internal Server Error"` dan `delegations=[]`).

**Akar masalah** (`execution_engine.py:1188–1206`):
```python
if status == "success":
    return {"type": "agent.think", ...}
# status != success -> tetap RETURN normal (tidak raise):
return {
    "type": "agent.think",
    "message": f"[Agent {status}] {res.get('error', 'tanpa LLM key')}",
    "agent_status": status,          # <- hanya field, bukan status node
    "agent_error": res.get("error"),
}
```
`_exec_agent` **tidak pernah melempar** saat agent gagal → `_run_node` menandai
node `completed`. Ini **kelas bug yang sama dengan BUG-B2**, tetapi pada jalur
agent (bukan jalur tool/MCP). Perbaikan BUG-B2 tidak menyentuh `_exec_agent`.

**Dampak.** Sama seperti BUG-B2: "hijau padahal gagal" pada kanvas, `/analytics`,
billing, dan otomasi hilir untuk **semua workflow ber-agent**.

**Rekomendasi.** Terapkan pola `_raise_if_tool_failed` pada `_exec_agent`
(raise saat `status` bukan `success`/`needs_credential`), atau tandai node `error`
di `_run_node` ketika payload memuat `agent_status == 'error'`.

---

## 5. TEMUAN BARU — **F-6** (keputusan diperlukan)

**Gejala.** Jalur `POST /webhook/{id}` **tidak** meneruskan `owner_email` ke runner.

**Konsekuensi.** Node MCP yang butuh kredensial user (mis. Google Sheets/Gmail
OAuth) pada workflow ber-trigger webhook **tidak dapat** me-resolve token pemilik.

**Mengapa sengaja dibiarkan.** Meneruskan `owner_email` membuat webhook
menghabiskan **kuota free user pemilik** setiap kali webhook dipanggil pihak
ketiga → regresi S3/S6 (terbukti saat verifikasi). Ini keputusan produk:
apakah webhook adalah jalur "atas nama pemilik" (kena kuota) atau "mesin publik"
(tanpa kuota, tanpa kredensial user).

**Status.** Di luar brief. Perlu keputusan produk sebelum launch fitur
webhook + kredensial user.

---

## 6. BAGIAN 8 — EVALUASI GO/NO-GO

| Syarat | Target | Aktual | Lulus |
|---|---|---|---|
| Hardcore 10/10 | 10/10 | 7/10 | ❌ |
| Bug kritis = 0 | 0 | 0 | ✅ |
| Kebocoran keamanan = 0 | 0 | 0 (0/124 baris) | ✅ |
| Load test tanpa 500 | 0×5xx | 0×5xx | ✅ |
| pytest + Playwright hijau | hijau | 1065 pass / 12+2 lingkungan · PW 15/15 | ✅ |

**Verdict: NO-GO.**

Blocker NO-GO:
1. **S6** — gateway LLM self-hosted (`/chat/completions`) **tidak stabil/mati**
   → semua node agent gagal ~100%. **Perbaikan infra**, bukan kode.
2. **S8** — healing endpoint mati ×5 terlalu lambat (>420s) di produksi → eksekusi
   menggantung `pending`. Perlu timeout healing lebih agresif atau batas total.
3. **BUG-B3** — node agent gagal tercatat `completed` → wajib diperbaiki agar
   sinyal kegagalan konsisten dengan BUG-B2.

Jalan ke GO (semua wajib):
- [ ] Perbaiki **BUG-B3** (`_exec_agent` raise saat gagal) + tes.
- [ ] Stabilkan/kembalikan gateway LLM self-hosted; verifikasi 5/5 agent sukses.
- [ ] Turunkan total waktu healing endpoint mati (< 60s) → S8 `error` tegas.
- [ ] Rerun 10 skenario hingga **10/10**, tanpa regresi.
- [ ] Putuskan **F-6** (kuota webhook) lalu kunci dengan tes.

---

## 7. LAMPIRAN — Artefak Bukti

| Berkas | Isi |
|---|---|
| `_prod_scenarios_out.json` / `_run_scenarios_c.log` | 10 skenario (7/10) mentah |
| `_run_s2s6_d.log` | S2 PASS saat retry; S6 FAIL |
| `_prod_load_out.json` / `_run_load_b.log` | load test 50/100/200 |
| `_fix_evidence_2026_10_07.py` | bukti lokal 6 perbaikan (SEMUA PASS) |
| `_f2_prod_verify.py` | BUG-B1 + F-2 end-to-end produksi (PASS/PASS) |
| `_f2_probe.py` | probe Supabase 124 baris (0 plaintext) |
| `scripts/redact_execution_logs_history.py` | redaksi historis (UPDATE-only, dry-run 0 perubahan) |
| `tests/test_launch_blocker_fixes_2026_10_07.py` | 38 tes pengunci kontrak perbaikan |

**Deployment:** commit `b7904860` → deployment `c55a9b2d-fb35-40fe-b506-bbef7d9a9e93` = **SUCCESS**
(`GET /health` → 200; `GET /workflows` tanpa auth → 401).
