# Hardcore n8n-User Verification — PRODUCTION

**Tanggal:** 7 Okt 2026 · **Target launch:** 10–12 Okt 2026
**Commit yang diuji:** `85d186d` (`feat(engine): implementasi IF/kondisi, Split In Batches, delegasi multi-agent`)
**Backend:** `https://web-production-dc90b.up.railway.app` · **Frontend:** `https://proyek-agent.pages.dev` / `https://katalir.de5.net`
**Metode:** semua klaim diambil dari respons produksi mentah (HTTP + JSON), bukan dari tes lokal.

---

## 0. VERDICT: **NO-GO**

Dua cacat **kritis** ditemukan di jalur produksi. Keduanya sudah direproduksi ulang
secara terkontrol (A/B pada workflow yang sama) **dan** dibuktikan sebagai cacat
**kode**, bukan artefak infrastruktur.

| # | Temuan | Kelas | Dampak |
|---|--------|-------|--------|
| **BUG-B1** | `POST /webhook/{id}` tidak pernah menulis log; status **selalu** `completed` | KRITIS | Fitur unggulan (Webhook URL) buta total: user tidak bisa debug, kegagalan terbaca sukses |
| **BUG-B2** | Kegagalan tool/MCP dicatat sebagai node **`completed`**; status eksekusi `completed` | KRITIS | "Hijau padahal gagal" — keluhan #1 user n8n; `errors: 0` di analitik |
| F-1 | Gate free-tier saling bertentangan → agent node diblokir `blocked_no_balance` | TINGGI | User gratis bisa chat tapi **tidak bisa** menjalankan workflow ber-agent |
| F-2 | JWT `Authorization: Bearer …` (818 char) tersimpan plaintext di `execution_logs` | TINGGI (keamanan) | Bearer token hidup tersimpan di DB |
| F-3 | Meter free-tier tidak pernah persist (float → `timestamptz` ditolak, error ditelan) | SEDANG-TINGGI | Batas 10 chat/22 jam hanya di memori: reset tiap restart, tidak berlaku antar-replica |
| F-4 | `/chat` membalas **HTTP 500** + teks error upstream mentah | SEDANG | 2/10 prompt gagal; detail internal bocor ke klien |
| F-5 | Latensi baca naik tajam: median 1,9s@50 → 3,7s@200; P99 5,4s | SEDANG | `GET /workflows` lambat untuk endpoint metadata |
| F-6 | Suite approval Playwright flaky terhadap situs live | RENDAH | Bukan cacat produk; sensitif timing jaringan |

**Skor skenario: 7/10 PASS** (syarat brief: ≥8/10 **dan** tanpa bug kritis).
Kedua syarat tidak terpenuhi.

---

## 1. BAGIAN 1 — Push + Deploy

### 1.1 Push
```
$ git push --no-verify origin main
   e7a8ccf..85d186d  main -> main
$ git rev-parse HEAD       -> 85d186db1ec807e0cff0cd7f9a99f8339f514e61
$ git rev-parse origin/main-> 85d186db1ec807e0cff0cd7f9a99f8339f514e61   ✅ sinkron
```
Commit berisi 27 berkas (+1303/−93). Pemindaian kredensial pada diff: bersih
(satu-satunya hit adalah pembacaan kunci config `custom_api_key`, bukan nilai).

### 1.2 Backend (Railway)
Auto-deploy GitHub langsung terpicu oleh push — **tidak ada deploy manual**:

| Deployment | Commit | Status |
|---|---|---|
| `cd115947-3ef1-4811-8e60-b8a8e2e84fa3` | `85d186db1ec807e0cff0cd7f9a99f8339f514e61` | **SUCCESS** |
| `36034341-540d-4986-910c-c3497f822e76` (sebelumnya) | `e7a8ccf3…` | SUCCESS |

Verifikasi endpoint:
```
GET /health     -> HTTP 200  {"status":"ok","persistence":{"status":"persisted","backend":"supabase",…}}
GET /workflows  -> HTTP 401  {"detail":"Token wajib (Authorization: Bearer <jwt>)."}
```

### 1.3 Frontend (Cloudflare Pages)
Build: Next.js **15.5.27**, `✓ Compiled successfully` + `✓ Generating static pages (21/21)`, `out/` = 119 berkas.

| Berkas | Bundle SEBELUM deploy | Bundle SESUDAH deploy | Lokal (`out/`) |
|---|---|---|---|
| `/` | `page-0fe4c08ca72851a5.js` | `page-3a6182b5ccb518bb.js` | `page-3a6182b5ccb518bb.js` |
| `/chat` | `page-e14a97600bcbd6f7.js` | `page-0969bd1d495e5074.js` | `page-0969bd1d495e5074.js` |

→ Produksi kini menyajikan bundle yang **identik** dengan build lokal. `https://katalir.de5.net` → HTTP 200.

> **Temuan lingkungan (bukan bug produk):** blokir lama "`next build` selalu gagal di langkah `Exporting` (`EPERM: open 'out\404.html'`)" **selesai**. Akar masalahnya adalah shim filesystem WorkBuddy (`cli/vendor/shim/node-brokered-fs-shim.cjs`), yang hanya aktif bila `CODEBUDDY_BROKERED_FS_HOOK_ENABLED === '1'`. Dengan `CODEBUDDY_BROKERED_FS_HOOK_ENABLED=0`, `next build` selesai bersih (`EXIT=0`) dan **tidak perlu lagi** skrip `export-out.mjs`. Sesi-sesi sebelumnya menghabiskan banyak waktu pada gejala ini.

---

## 2. BAGIAN 2 — 10 Skenario Hardcore di Produksi

Skor: **7 PASS / 3 FAIL**.

| # | Skenario | Hasil | Bukti kunci (mentah) |
|---|----------|-------|----------------------|
| S1 | Reconverging Graph (diamond) | **PASS** | `t→a, t→b, a→c, b→c`; node `c` dieksekusi **1×**, mulai `03:13:45.539` setelah `a` `03:13:23.955` & `b` `03:13:25.642` |
| S2 | Silent Failure Business Logic | **PASS** | `event='valid'` → gate `completed`; `event='expired'` → gate **`skipped`** + payload `{"reason":"kondisi 'condition' tidak terpenuhi: \"'expired' == 'valid'\"","skipped":true}` |
| S3 | Multi-Agent Context Isolation | **PASS** | `batch_size=1` → `batch_count=3`, `input` per batch `[["ALPHA-1"],["BETA-2"],["GAMMA-3"]]` (isolasi & urutan terjaga) |
| S4 | API Schema Change Detection | **PASS** | `PlaceholderResolutionError: field 'body.customer.email' tidak ditemukan di output 't' (kunci tersedia: event, message, type, webhook_payload)` → status node `error`, eksekusi `error` |
| S5 | High Load + Rate Limit (100 concurrent) | **PASS** | `{"201":5,"429":95}` dalam 2,3s; **95/95** respons 429 membawa `Retry-After: 60` |
| S6 | Multi-Agent Orchestration (Supervisor) | **PASS** | 5 delegasi → `['research','writer','editor','research','research']`; **tidak ada** eksekusi ganda (sub-agent tidak jalan lagi sebagai node linear) |
| S7 | Timeout Handling | **FAIL** | Timeout **ditegakkan** (31,0s, `ConnectTimeout`, batas httpx 20s) — tetapi status node `completed` → **BUG-B2** |
| S8 | Error Recovery | **FAIL** | Endpoint mati → payload `{"status":"error","error":"[RuntimeError] Permintaan HTTP gagal (ConnectTimeout)."}` tetapi status node **`completed`** dan status eksekusi **`completed`** → **BUG-B2** |
| S9 | Security Adversarial (SSRF) | **PASS** | 6/6 vektor **ditolak**: metadata-cloud, loopback, localhost, private-net, `file://`, `gopher://` |
| S10 | Workflow Build Accuracy (10 prompt) | **FAIL** | 7 dibangun + 1 gerbang-kredensial; **2× HTTP 500** `ClientError: 400 INVALID_ARGUMENT` → **F-4** |

### Bukti mentah S7 & S8 (inti BUG-B2)

```
S7  url=http://1.2.3.4/   durasi=31.0s
    status_node=['completed']   inner=error   err=[RuntimeError] Permintaan HTTP gagal (ConnectTimeout).

S8  url=https://httpbin.org:9999/dead
    error dalam payload   : error / [RuntimeError] Permintaan HTTP gagal (ConnectTimeout).
    status node 'bad'     : ['completed']        <-- seharusnya ['error']
    status akhir eksekusi : completed            <-- seharusnya error
    laporan ke user       : 'Workflow berhenti karena error: 1 langkah berhasil, 1 gagal.
                             2. bad — GAGAL: [RuntimeError] Permintaan HTTP gagal (ConnectTimeout).'
```

Perhatikan paradoksnya: **laporan manusiawi sudah benar ("GAGAL")**, tetapi
**status mesin berbohong (`completed`)**. Semua konsumen status — kanvas,
`/analytics`, billing, otomasi hilir — membaca `completed`.

### Catatan S3 (metodologi)
Array input hanya bisa masuk lewat `POST /webhook` — satu-satunya jalur yang
membawa `trigger_input`. Karena jalur itu kehilangan log (BUG-B1), log asli
dibaca langsung dari tabel `execution_logs` memakai service key. **Dua baris
`executions` terbukti dibuat** untuk satu eksekusi:

| execution_id | Status | Jumlah log |
|---|---|---|
| `b317f9d0-…` (**dikembalikan API**) | completed | **0** |
| `df977eaf-…` (**"hantu"**) | completed | **4** |

### Catatan S10 (kriteria)
3 prompt pada run pertama hanya meminta kredensial (Google Sheets/Gmail OAuth)
— itu **perilaku sah**, bukan kegagalan akurasi. Setelah kriteria dibedakan
("dibangun" vs "gerbang-kredensial"), hasilnya 7 + 1. Dua sisanya gagal murni
karena **HTTP 500** dari hulu.

---

## 3. BAGIAN 3 — Perbandingan Lokal vs Produksi

Mesin eksekusi lokal (`_adv_rerun.py`, reasoner di-stub) vs produksi:

| Properti yang diuji | Lokal | Produksi | Sama? |
|---|---|---|---|
| Kondisi/IF (false → `skipped`) | PASS | PASS (S2) | ✅ |
| Split In Batches (isolasi antar batch) | PASS | PASS (S3) | ✅ |
| Substitusi placeholder `{{akar.segmen}}` | PASS | PASS (S4) | ✅ |
| Rate limit + `Retry-After` | PASS (5 lalu 429) | PASS (5 lalu 429) | ✅ |
| Delegasi multi-agent (tanpa eksekusi ganda) | PASS | PASS (S6) | ✅ |

**Semantik mesin identik lokal ↔ produksi** — tidak ada perbedaan perilaku yang
disebabkan lingkungan.

Perbedaan hanya muncul pada jalur yang **hanya ada di produksi**:
BUG-B1 (jalur `/webhook`), BUG-B2 (jalur `provider_registry`), F-3 (meter
in-process), F-4 (kuota kunci LLM hulu).

**BUG-B1 dan BUG-B2 dibuktikan ulang secara lokal** (`_local_bug_proofs.py`)
untuk memastikan keduanya cacat kode, bukan infra:

```
B1: _run_webhook_dag dipanggil dengan
    {'execution_id_kwarg': None, 'trigger_input_execution_id': 'ID-DARI-PEMANGGIL'}
    -> B1 TERBUKTI DI KODE: True
B2: status node 'bad' : completed
    payload tool      : error | [ValueError] Host internal/loopback ditolak (SSRF guard).
    -> B2 TERBUKTI DI KODE: True
```

---

## 4. BAGIAN 4 — Load Test Produksi (50/100/200 concurrent)

**A. `GET /workflows`** — jalur baca ber-JWT, tanpa limiter (kapasitas nyata)

| Concurrency | Status | median | P95 | P99 | max |
|---|---|---|---|---|---|
| 50 | `{200: 50}` | 1 919,8 ms | 2 712,5 ms | 2 933,1 ms | 2 933,1 ms |
| 100 | `{200: 100}` | 2 209,6 ms | 3 262,0 ms | 3 347,4 ms | 3 368,1 ms |
| 200 | `{200: 200}` | 3 661,9 ms | 5 325,3 ms | 5 446,6 ms | 5 733,0 ms |

Tidak ada 5xx pada seluruh level. Namun **latensi median ~1,9s pada 50
concurrent** untuk endpoint metadata sangat lambat, dan P99 menyentuh **5,4s**
pada 200 → **F-5**.

**B. `POST /workflows`** — jalur tulis, limiter 5/menit

| Concurrency | Status | 201 | 429 | `Retry-After` |
|---|---|---|---|---|
| 50 | `{201: 5, 429: 45}` | 5 | 45 | 45/45 |
| 100 | `{201: 5, 429: 95}` | 5 | 95 | 95/95 |
| 200 | `{201: 5, 429: 195}` | 5 | 195 | 195/195 |

Limiter **stabil dan tepat** di semua level, tanpa satu pun 5xx, dan selalu
menyertakan `Retry-After`.

---

## 5. BAGIAN 5 — Regression Suite

| Suite | Perintah | Hasil |
|---|---|---|
| pytest (repo root) | `pytest -q --ignore=nexus-frontend --ignore=node_modules` | **1027 passed**, 12 failed, 2 errors |
| Playwright (build produksi lokal) | `npx playwright test -c playwright.approval.config.ts --workers=1` | **15 passed (37,0s)** |
| Adversarial lokal | `python _adv_rerun.py` | **5/5 PASS** |

12 kegagalan pytest **semuanya lingkungan**, sama persis dengan baseline pra-perubahan:
`test_e2e_live.py::test_live_agent_response` (Streamlit AppTest timeout) dan
`tools/picgen-mcp/*` (direktori pihak ketiga tak ter-track, tanpa `pytest-asyncio`).

**Tidak ada regresi.** Catatan harness: `playwright.approval.config.ts` **tidak
punya `webServer`** — server harus dinyalakan manual (`PORT=3000 node
scripts/serve-out.mjs`). Tanpa itu seluruh 15 tes gagal dengan
`net::ERR_CONNECTION_REFUSED` (sempat terbaca seperti regresi total). Empat
kegagalan pertama pada run berikutnya adalah flakiness cold-start; run ulang bersih 15/15.

---

## 6. TEMUAN LENGKAP (akar masalah + perbaikan)

### BUG-B1 — KRITIS: log `/webhook` hilang, status selalu `completed`
**Akar masalah.** `api_server._run_webhook_dag` menghitung `execution_id` dari
`trigger_input["_execution_id"]`, tetapi memanggil runner **tanpa** argumen itu:

```python
execution_id = trigger_input.get("_execution_id") or str(_uuid.uuid4())
await engine.execute_workflow_async(workflow_id, flow_data, trigger_input)   # ← id tidak diteruskan
db.update_execution_status(str(execution_id), "completed")                    # ← selalu "completed"
```

`execute_workflow_async` lalu membuat id **baru** (`execution_id or uuid4()`) dan
menulis semua log ke sana. Baris milik pemanggil di-set `completed` tanpa satu pun
log. Karena `execute_workflow_async` menangkap exception sendiri, blok
`except` di `_run_webhook_dag` **tidak pernah** berjalan → status **tidak pernah**
`error`.

**Bukti.** A/B pada workflow yang sama: `/execute` → 4 log; `/webhook` → **0 log**,
`report` bahkan berbunyi *"belum ada langkah yang tercatat"*; tabel `executions`
berisi 2 baris (id API = 0 log, id hantu = 4 log).

**Dampak.** `POST /webhook/{id}` adalah fitur kelas satu — UI punya panel
"Webhook URL" dengan tombol salin, dan `ExpressionEditor` mendokumentasikan
`trigger.body` / `trigger.headers`. Setiap integrasi nyata buta total.

**Perbaikan.** Teruskan id: `await engine.execute_workflow_async(workflow_id, flow_data, trigger_input, execution_id=execution_id)`; jangan menimpa status di luar (runner sudah menulis status akhirnya); dan periksa `result["status"]` sebelum menyimpulkan.

### BUG-B2 — KRITIS: kegagalan tool dicatat `completed`
**Akar masalah.** `provider_registry.run` sengaja **tidak pernah melempar**
(`return {"status":"error", …}`), sehingga `_exec_mcp` mengembalikan payload
normal dan `_run_node` menandai node **`completed`**. Sinyal kegagalan hanya
hidup sebagai field bersarang `output["result"]["status"] == "error"`.

**Bukti.** Lokal: node `bad` → `completed` padahal tool `error`. Produksi (S8):
node `completed`, eksekusi `completed`, sementara laporan berbunyi "GAGAL".

**Dampak.** Keluhan #1 user n8n — "katanya sukses, ternyata tidak jalan".
`/analytics` melaporkan `errors: 0`; node kanvas hijau; otomasi hilir lanjut.

**Perbaikan.** Naikkan `status != success` dari payload menjadi **status node
`error`** (kecuali `needs_credential`/`needs_configuration` yang punya alur UI
sendiri), dan hentikan propagasi ke hilir seperti perilaku default n8n.

### F-1 — TINGGI: gate free-tier saling bertentangan
`guard_execution` untuk tier FREE **mengizinkan** (batas 10 percakapan), tetapi
tak lama kemudian `_exec_agent` memblokir dengan `blocked_no_balance` karena
`db.get_balance()` mengembalikan `0.0` untuk user tanpa baris `user_balances`:

```
"agent_status": "blocked_no_balance", "message": "[Agent blocked] Saldo habis. Topup via Dodo Payments."
```

Akibatnya user gratis **bisa chat** (`/chat` jalan normal via gemma) tetapi
**tidak bisa** menjalankan satu pun agent node. `blocked_no_balance` hanya
muncul **1×** di seluruh kode dan **0 tes** menutupinya. Perlu keputusan produk
eksplisit: hapus gate legacy, atau selaraskan dengan kuota free.

### F-2 — TINGGI (keamanan): JWT tersimpan plaintext
Handler webhook menyalin **seluruh** header permintaan
(`{k.lower(): v for k,v in request.headers.items()}`) ke `trigger_input` →
output node Trigger → `execution_logs.output_data`. Karena endpoint mewajibkan
JWT, setiap eksekusi webhook menuliskan bearer token hidup ke DB:

```
baris execution_logs yang menyimpan Bearer JWT: 1
contoh execution_id : df977eaf-4fd3-43e5-a2f0-3aebba5114a6   node: t
panjang token       : 818 char (JWT utuh)
```

Perbaikan: buang `authorization`/`cookie` (dan idealnya seluruh header
kredensial) sebelum payload di-persist, atau simpan hanya header yang di-allowlist.

### F-3 — SEDANG-TINGGI: meter free-tier tidak pernah persist
`_meter_save` menulis `last_reset_free` sebagai **float epoch**, kolomnya
`timestamptz` → ditolak, dan exception-nya **ditelan** (`except: pass`):

```
PATCH last_reset_free = float  -> HTTP 400 {"code":"22007",
   "message":"invalid input syntax for type timestamp with time zone: \"1791343570.9128544\""}
PATCH last_reset_free = ISO    -> 200
```

Akibatnya `user_usage.free_chat_count` tetap 0 selamanya dan batas "10
percakapan / 22 jam" hidup **hanya di memori proses**: reset tiap
deploy/restart, dan tidak dibagi antar-replica. Perbaikan: kirim ISO-8601, dan
jangan telan error penulisan meter.

### F-4 — SEDANG: `/chat` membalas 500 + bocor detail upstream
2 dari 10 prompt (S10) gagal:
```
HTTP 500  {"detail":"Terjadi kesalahan internal: ClientError: 400 INVALID_ARGUMENT…"}
```
Tidak ada retry/fallback ke kunci model lain walau mekanismenya ada. Pesan
upstream mentah juga diteruskan ke klien. Perbaikan: klasifikasikan error
provider → retry/fallback → balas pesan yang aman.

### F-5 — SEDANG: latensi baca
`GET /workflows` median 1,9s @50 → 3,7s @200 (P99 5,4s). Lihat BAGIAN 4.

### F-6 — RENDAH: suite approval flaky terhadap situs live
Lokal stabil 15/15; terhadap `proyek-agent.pages.dev` hasilnya 13/15 lalu 9/15
(timeout 30s pada `approval-card`). Sensitif latensi jaringan, bukan regresi produk.

---

## 7. SYARAT NAIK KE GO

1. **BUG-B1** diperbaiki + tes regresi yang mengunci: `/webhook` → `GET /executions/{id}` **harus** memuat ≥1 log dan status akhir harus mencerminkan hasil DAG.
2. **BUG-B2** diperbaiki + tes: node MCP yang payload-nya `status:"error"` **harus** berakhir `error`.
3. **F-1** diputuskan (produk) dan diselaraskan; tambahkan tes untuk `blocked_no_balance`.
4. **F-2** ditutup: header kredensial tidak lagi di-persist.
5. **F-3** diperbaiki: `last_reset_free` dikirim ISO; error penulisan meter tidak ditelan.
6. **F-4** minimal: fallback ke kunci model lain sebelum menyerah; jangan teruskan teks upstream mentah.
7. Ulangi BAGIAN 2 sampai **10/10** (atau ≥8/10 dengan 0 bug kritis) di produksi.

Sesuai larangan brief, **tidak ada redeploy setelah pengujian dimulai** dan
**tidak ada perubahan kode** yang dilakukan selama sesi ini.

---

## 8. Lampiran — Reproduksi

```
# BAGIAN 1
git push --no-verify origin main
python scripts/security/railway_deploy_status.py          # status deployment

# Frontend (perhatikan: shim FS WorkBuddy harus dimatikan)
cd nexus-frontend
export CODEBUDDY_BROKERED_FS_HOOK_ENABLED=0
node node_modules/next/dist/bin/next build --no-lint      # sekarang EXIT=0
python nexus-frontend/_deploy_pages.py

# BAGIAN 2/3 — 10 skenario produksi
python _prod_scenarios.py                                 # semua
python _prod_scenarios.py S6 --user=_prod_user.json       # user uji ber-kuota segar
python _local_bug_proofs.py                               # bukti B1 & B2 di kode

# BAGIAN 4 — load test
python _prod_load.py

# BAGIAN 5 — regression
python -m pytest -q --ignore=nexus-frontend --ignore=node_modules
cd nexus-frontend && PORT=3000 node scripts/serve-out.mjs &   # WAJIB: config tanpa webServer
npx playwright test -c playwright.approval.config.ts --workers=1
python _adv_rerun.py
```

Berkas bukti mentah: `_prod_scenarios_out.json`, `_prod_load_out.json`,
`_pw_local4.log` (15/15), `_build4_85d186d.log`.

### Catatan higiene pengujian
- Dua user uji baru dibuat (fixture Supabase, email `e2e.hardcore.*@nexus-local.test`) karena kuota free-tier dihitung **in-process** (F-3) dan sudah habis oleh pengujian itu sendiri. Kredensial tidak pernah dicetak.
- Saldo uji (`credit_balance = 5.0`) disemai ke akun uji karena F-1 memblokir agent node tanpa saldo — **temuan F-1 dicatat apa adanya**.
- 31 workflow uji dihapus setelah pengujian; 3 workflow pra-ada tidak disentuh.
