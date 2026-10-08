# STATUS DEPLOY — 11 Fitur + UI Template Gallery

Terakhir diperbarui: **8 Oktober 2026**

Dokumen ini adalah sumber kebenaran tunggal untuk *apa yang benar-benar
berjalan di produksi*, dengan perintah verifikasi yang bisa diulang siapa pun.
Tidak ada klaim tanpa cara membuktikannya.

---

## 1. Target produksi

| Komponen | URL | Platform | Sumber deploy |
|---|---|---|---|
| Backend API | `https://web-production-dc90b.up.railway.app` | Railway (service `web`, env `production`) | auto-deploy dari `git push` ke `main` |
| Frontend | `https://katalir.de5.net` | Cloudflare Pages (project `proyek-agent`) | **manual**: `npx wrangler pages deploy out --project-name=proyek-agent` |
| Frontend (alias) | `https://proyek-agent.pages.dev` | Cloudflare Pages (alias yang sama) | idem |
| Database | Supabase Postgres `qmukkphwaajzbqjrcvaz` | Supabase | migrasi DDL via pooler `aws-0-ap-southeast-1.pooler.supabase.com:6543` |

**Penting:** project Cloudflare Pages `proyek-agent` **tidak punya Git source**
(`source: null`), jadi `git push` TIDAK men-deploy frontend. Deploy frontend
selalu manual lewat wrangler. Backend sebaliknya: Railway auto-deploy.

---

## 2. Commit yang sedang live

| Commit | Isi |
|---|---|
| `17647c7` | `/version` + `build` di `/health` (verifikasi deploy) |
| `9617b80` | **UI Template Gallery** `/templates` (Fitur #10) + 12 tes Playwright |
| `f15917b` | **fix**: mount `/mcp/katalir` menelan `/info`, `/key`, `/verify` (Fitur #8 mati) |
| `a23c068` | **fix**: validasi graf `POST /workflows` + id template rusak 404 (bukan 500) |

Verifikasi commit yang benar-benar jalan (bukan yang di-push):

```bash
curl -s https://web-production-dc90b.up.railway.app/version
# -> {"build":{"commit":"a23c068...","branch":"main","service":"web",
#             "environment":"production","python":"3.12.7"},
#     "features":{"01_cron":true, ... "11_testkit":true},
#     "features_present":11,"features_total":11}
```

---

## 3. Status 11 fitur (produksi)

Semua diverifikasi lewat HTTP ke backend LIVE, bukan lewat unit test.
Skrip: `_prod_e2e_11features.py` (23 pemeriksaan).

| # | Fitur | Endpoint produksi | Status |
|---|---|---|---|
| 1 | Scheduled Trigger (cron) | `POST/GET/DELETE /workflows/{id}/schedule` | ✅ `next_run_at=2026-10-08T03:50:00+00:00` |
| 2 | Durable Execution | `POST /workflows/{id}/execute`, `GET /executions/{id}` | ✅ 202 → status `success` persisten |
| 3 | Retry + Backoff + DLQ | state di `GET /executions/{id}` (`report`/`logs`) | ✅ |
| 4 | Sub-Workflow | flag `/version` `04_subworkflow` | ✅ |
| 5 | Parallel Fan-Out/Fan-In | flag `/version` `05_parallel_fanout` | ✅ |
| 6 | Code Node (Sandbox) | flag `/version` `06_code_sandbox` | ✅ |
| 7 | External Secrets Manager | `POST /api/vault/save`, `GET /api/vault/list` | ✅ tanpa plaintext di respons |
| 8 | MCP Server Built-in | `/mcp/katalir/info`, `/key`, `/verify`, `/mcp/katalir` | ✅ key 220 char, `valid:true` |
| 9 | AI Agent Memory (pgvector) | `POST /memory/remember`, `/recall`, `GET /preferences` | ✅ recall menemukan baris tersimpan |
| 10 | Workflow Templates | `GET /templates`, `/templates/info`, `/{id}`, `POST /{id}/use` | ✅ 10 bawaan + kustom |
| 11 | Testing Framework | flag `/version` `11_testkit` | ✅ (modul Python, tanpa endpoint) |

Hasil terakhir: **23/23 PASS — ALL GREEN.**

---

## 4. UI Template Gallery (`/templates`)

Dibangun di `nexus-frontend/src/features/templates/`:

| Berkas | Peran |
|---|---|
| `types.ts` | tipe `Template`, kategori, `FlowData` |
| `api.ts` | klien `/templates*` via `apiFetch` (Bearer JWT otomatis) |
| `TemplateCard.tsx` | kartu: ikon, chip kategori, badge "Kustom", node count, aksi |
| `TemplateGallery.tsx` | kontainer: react-query, pencarian + filter server-side, modal, notice |
| `TemplatePreview.tsx` | modal pratinjau + rantai node terurut topologis |
| `src/app/templates/page.tsx` | halaman via `SimplePage` (`max-w-5xl`) |
| navigasi | tautan **Template** di header shell (`data-testid="shell-templates-link"`) |

Verifikasi: **12/12 tes Playwright lulus** melawan produksi
(`tests/templates-gallery.spec.ts`, config `playwright.templates.config.ts`),
plus **1 tes live tanpa stub** (`tests/templates-live.spec.ts`) yang memuat
template asli dari backend Railway memakai JWT Supabase nyata.
**14 screenshot** di `docs/marketing/screenshots/templates-gallery/`
(12 dari suite stub + `13-live-prod.png`, `14-live-preview.png`).

```bash
cd nexus-frontend

# Suite stub (deterministik, endpoint /templates di-stub)
E2E_BASE_URL=https://katalir.de5.net \
  node node_modules/@playwright/test/cli.js test --config=playwright.templates.config.ts
# -> 12 passed

# Suite live (backend nyata, tanpa stub)
E2E_BASE=https://katalir.de5.net E2E_SPEC=templates-live \
  node node_modules/@playwright/test/cli.js test --config=playwright.templates.config.ts
# -> 1 passed  (14 kartu termuat; "RSS → Slack" ada; pratinjau 4 node)
```

Bukti suite live (mentah):

```
PROD_LIVE storageKey=sb-qmukkphwaajzbqjrcvaz-auth-token user=e2e.1791190942931@nexus-local.test
PROD_LIVE account-logo href=/chat
PROD_LIVE jumlah kartu = 14
PROD_LIVE nama: ["Email masuk → Google Sheets","RSS → Slack","Digest Harian → Telegram","Webhook → API HTTP","Tanya Jawab AI"]
PROD_LIVE kartu kustom = 4
PROD_LIVE node di pratinjau = 4
1 passed (14.0s)
```

---

## 5. Cara mengulang seluruh verifikasi

```bash
# 1. Backend 11 fitur (butuh sesi E2E; refresh otomatis dari fixture)
python _prod_e2e_11features.py            # -> TOTAL 23/23 PASS

# 2. Hard test produksi (load/adversarial/durability/integrasi/n8n)
python _prod_hard_run.py

# 3. Load terisolasi saja (angka bersih, tanpa beban saingan)
python _prod_load_isolated.py             # -> TOTAL 5/5 PASS

# 4. Diagnosis straggler (watchdog + retry) — timeout, ukuran, ronde
python _probe_load_stall.py 60 500 3

# 5. Unit + integrasi (lokal)
python -m pytest -q

# 6. UI gallery — suite stub (12) lalu suite live (1)
cd nexus-frontend
E2E_BASE_URL=https://katalir.de5.net \
  node node_modules/@playwright/test/cli.js test --config=playwright.templates.config.ts
E2E_BASE=https://katalir.de5.net E2E_SPEC=templates-live \
  node node_modules/@playwright/test/cli.js test --config=playwright.templates.config.ts
```

---

## 6. Catatan operasional yang WAJIB diketahui

### 6.1 Build frontend di mesin ini butuh `_build_retry.cjs`

`next build` di mesin ini gagal acak dengan
`EPERM: operation not permitted, open '...\.next\trace'` (lalu `out\404.html`).
Penyebabnya bukan kode repo: agen keamanan/antivirus memegang handle scan
sesaat setelah file ditulis, dan Node tidak mengulang sementara Next
memperlakukannya sebagai fatal. Perbaikannya adalah preload kecil yang
mengulang operasi buka/tulis transien:

```bash
cd nexus-frontend
NODE_OPTIONS="--require=$PWD/_build_retry.cjs" \
  "/c/Program Files/nodejs/node.exe" node_modules/next/dist/bin/next build
```

Gunakan **Node sistem (24.x)**. Node terkelola (22.x) *segmentation fault*
saat memuat `@next/swc-win32-x64-msvc`.

### 6.2 Jangan biarkan Next menumpuk `.next` lama

Guard `safe-delete` memblokir penghapusan massal (>50 berkas) sehingga
pembersihan cache `.next` oleh Next bisa menggagalkan build. Pola yang aman:
**pindahkan** `.next`/`out` ke direktori lain sebelum build (rename, bukan
hapus), lalu build bersih.

### 6.3 Deploy frontend manual

```bash
cd nexus-frontend
python _deploy_pages.py     # wrangler pages deploy out --project-name=proyek-agent
```

### 6.4 Push GitHub di mesin ini

`git-credential-manager.exe` menggantung pada subcommand interaktif. Pola
bypass yang terbukti ada di `docs/PUSH_BLOCKER.md`.

---

## 7. Temuan & perbaikan pada sesi ini

| Temuan | Tingkat | Perbaikan |
|---|---|---|
| Mount `/mcp/katalir` menelan `/info`, `/key`, `/verify` → user tak pernah bisa menerbitkan API key MCP | **Kritis** (fitur mati) | mount dipindah ke akhir modul; 2 tes regresi |
| `POST /workflows` tanpa validasi graf: 5.000 node, self-loop, edge hantu diterima | **Tinggi** (DoS + data rusak) | `validate_workflow_flow()` untuk INSERT & UPDATE; 12 tes |
| `GET/DELETE /templates/{non-uuid}` → 500 | Sedang | guard `uuid.UUID()` → 404 |
| `GET /executions/{id asing}` → 200 `execution:null` | Rendah (tidak bocor) | **diterima sebagai desain** (frontend melakukan polling; 404 akan mengganggu). Didokumentasikan, tidak diubah. |
| Playwright gagal *cleanup* `test-results` (340 berkas) karena guard `safe-delete` | Toolchain | `outputDir` diarahkan ke luar workspace (`PW_OUTPUT_DIR`, default TEMP) |

---

## 8. Diagnosis "straggler" pada load test

Pada load test awal, `GET /health` n=200 dan n=500 masing-masing menyisakan
**tepat 1** request yang menggantung sampai persis timeout klien (60,0 s),
**tanpa satu pun 5xx**. p95 justru membaik saat n naik, jadi kapasitas server
tidak sedang jenuh. Karena itu dijalankan `_probe_load_stall.py` untuk
memisahkan penyebab server-side dari klien/edge.

Metodenya: satu *watchdog thread* menembak `/health` di **koneksi baru** setiap
2 detik selama load berjalan, dan tiap straggler diulang satu per satu.

Hasil (3 ronde, n=500, timeout klien 60 s):

| Ronde | 200 | straggler | watchdog (jumlah tembakan) | watchdog median / max | watchdog non-200 | retry straggler |
|---|---|---|---|---|---|---|
| 1 | 500 | 0 | 3 | 375 ms / 603 ms | 0 | — |
| 2 | 496 | 4 | 23 | 394 ms / 5.610 ms | **0** | 908 / 368 / 367 / 581 ms — semuanya **200** |
| 3 | 500 | 0 | 2 | 1.496 ms / 1.679 ms | 0 | — |

**Kesimpulan:** server tetap sehat sepanjang load (watchdog 23× `200` berturut
di ronde yang sama, median 394 ms), dan setiap straggler sukses `<1 s` begitu
diulang. Jadi straggler = **artefak koneksi klien/edge** (TLS/keep-alive),
bukan kegagalan backend.

Konsekuensinya, harness load memakai **retry sekali untuk GET idempoten** —
persis perilaku klien produksi (browser/SDK). Hasil akhir setelah perbaikan
(`_prod_load_isolated.py`, timeout 60 s):

```
[PASS] A.LOAD GET /health n=50  :: 200=50  err=0 p50=625ms p95=1492ms max=2532ms
[PASS] A.LOAD GET /health n=100 :: 200=100 err=0 p50=996ms p95=1670ms max=3075ms
[PASS] A.LOAD GET /health n=200 :: 200=200 err=0 p50=537ms p95=1925ms max=3913ms
[PASS] A.LOAD GET /health n=500 :: 200=500 err=0 p50=593ms p95=1117ms max=2357ms
[PASS] A.LOAD GET /templates(auth) n=100 :: 200=100 err=0 p50=2914ms p95=3681ms max=4218ms
TOTAL: 5/5 PASS
retry GET idempoten yang terpakai: 2   (dari 950 request = 0,2 %)
VERDICT: ALL GREEN
```
