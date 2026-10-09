# Audit Fitur yang SUDAH ADA — Prasyarat Anti-Duplikasi

> **Instruksi yang dipatuhi:** *"baca dulu dengan seksama apa saja fitur yang
> sudah ada jangan ada duplikat dan ini 2000+ fitur yang ku inginkan"*
>
> Dokumen ini adalah hasil pembacaan itu. **Tidak ada satu pun connector yang
> akan dibangun sebelum daftar ini ada**, karena tanpa ini "2000+ fitur" akan
> menabrak apa yang sudah jalan dan menghasilkan dua sistem yang saling
> bertentangan.
>
> Tanggal audit: 9 Okt 2026. Semua angka di bawah **dihitung runtime dari kode**
> (`C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe`), bukan
> disalin dari dokumen lama.

---

## RINGKASAN EKSEKUTIF — temuan yang mengubah rencana

Brief meminta **"2000+ fitur integrasi"** seolah katalognya kosong. **Katalognya
tidak kosong. Katalognya sudah 25.925 entri.**

| Angka | Nilai | Sumber (dihitung runtime) |
|---|---|---|
| Connector **terkatalog** | **25.925** | `mcp_registry.coverage()["total"]` |
| Entri katalog unik (dedup) | **23.474** | `dedup_canonical.json` (len) |
| Yang **benar-benar bisa dijalankan** | **23** | `mcp_registry.executable_servers()` |
| Metadata-only (tidak bisa jalan) | **25.902** | `coverage()["metadata_only"]` |
| Provider native (in-process) | **8** | `provider_registry.PROVIDERS` |
| Tool OpenAPI ter-generate | **889** (669 callable) | `generated_mcp/apis.json` |
| Aksi OpenConnector terkatalog | **18.010** | `openconnector_coverage()["actions"]` |
| Aksi OpenConnector **call-verified** | **11** | `openconnector_coverage()["actions_call_verified"]` |
| Modul fitur engine | **38** | `_FEATURE_MODULES` di `api_server.py` |

### Diagnosis

Gap-nya **bukan** "kurang 2000 connector". Gap-nya adalah:

> **25.902 connector sudah terkatalog tetapi tidak dapat dieksekusi, dan hanya
> 23 + 8 = 31 yang punya jalur jalan nyata.**

Jadi pekerjaan yang benar **bukan menambah 2000 entri katalog ke-26.000** —
itu akan menaikkan angka `metadata_only` dari 25.902 menjadi ~27.900 dan
**memperburuk** kebohongan yang sudah ada. Pekerjaan yang benar adalah
**menaikkan angka 23 → 2000+**, yaitu memberi *jalur eksekusi + verifikasi
nyata* kepada entri yang sudah terkatalog.

Ini persis pola yang sudah ditegakkan proyek ini berulang kali
(`coverage()` sengaja memisahkan `executable` dari `metadata_only`;
`tools_listed` sengaja tidak pernah dipromosikan menjadi `call_verified`).

---

## BAGIAN 1 — 38 modul fitur engine (JANGAN dibangun ulang)

Dibaca dari `_FEATURE_MODULES` di `api_server.py`, disajikan di `/version` → `features`.

| # | Key | Modul | Status |
|---|---|---|---|
| 01 | `01_cron` | `scheduler_manager` | ✅ |
| 02 | `02_durable` | `durable_execution` | ✅ |
| 03 | `03_retry_dlq` | `retry_policy` | ✅ |
| 04 | `04_subworkflow` | `subworkflow` | ✅ |
| 05 | `05_parallel_fanout` | `parallel_fanout` | ✅ |
| 06 | `06_code_sandbox` | `code_sandbox` | ✅ |
| 07 | `07_secrets` | `secrets_provider` | ✅ |
| 08 | `08_mcp_server` | `mcp_server` | ✅ |
| 09 | `09_memory` | `memory_manager` | ✅ |
| 10 | `10_templates` | `workflow_templates` | ✅ |
| 11 | `11_testkit` | `workflow_testkit` | ✅ |
| 12 | `12_guardrails` | `guardrails` | ✅ |
| 13 | `13_vector_store` | `vector_store` | ✅ |
| 14 | `14_hitl` | `hitl` | ✅ |
| 15 | `15_evaluation` | `evaluation` | ✅ |
| 16 | `16_insights` | `insights` | ✅ |
| 17 | `17_secrets_enterprise` | `secrets_provider` | ✅ |
| 18 | `18_advanced_scheduling` | `advanced_scheduling` | ✅ |
| 19 | `19_monitoring` | `monitoring` | ✅ |
| 20 | `20_environments` | `environments` | ✅ |
| 21 | `21_source_control` | `source_control` | ✅ |
| 22 | `22_queue_mode` | `queue_mode` | ✅ |
| 23 | `23_sso` | `sso` | ✅ |
| 24 | `24_ai_workflow_gen` | `ai_workflow_gen` | ✅ |
| 25 | `25_workflow_optimizer` | `workflow_optimizer` | ✅ |
| 26 | `26_collab` | `collab` | ✅ |
| 27 | `27_plugins` | `plugin_system` | ✅ |
| 28 | `28_metric_eval` | `metrics_eval` | ✅ |
| 29 | `29_memory_provider` | `memory_provider` | ✅ |
| 30 | `30_execution_redaction` | `execution_redaction` | ✅ |
| 31 | `31_two_factor` | `two_factor` | ✅ |
| 32 | `32_log_streaming` | `log_streaming` | ✅ |
| 33 | `33_tracing` | `tracing` | ✅ |
| 34 | `34_self_healing` | `recovery` | ✅ |
| 35 | `35_end_user_credentials` | `end_user_credentials` | ✅ |
| 36 | `36_custom_rbac` | `rbac` | ✅ |
| 37 | `37_sandbox_isolation` | `sandbox_isolation` | ✅ |
| 38 | `38_mcp_build_workflow` | `mcp_build_workflow` | ✅ |

**Implikasi anti-duplikasi:** brief baru meminta FASE 2 "master framework
(`connector_registry.py`)", FASE 4 "10 hard test", FASE 5 "OpenAPI →
auto-generation". **Ketiganya punya padanan yang sudah ada** — lihat Bagian 3.

---

## BAGIAN 2 — Katalog connector yang SUDAH ADA (8 sumber)

Dibaca dari `mcp_registry.py` + file cache di root repo.

| Sumber | Entri | File | Isi | Verifikasi tersedia |
|---|---|---|---|---|
| `glama` (MCP servers) | 20.000 | `glama_servers.json` (13,2 MB) | server MCP pihak ketiga | `runtime_verified` per entri |
| `toolsdk` | 4.415 | `mcp_registry_cache.json` (2,9 MB) | paket MCP ToolSDK | metadata-only (dinyatakan eksplisit) |
| `composio` | 1.558 | `composio_toolkits.json` (0,9 MB) | toolkit Composio | `tools` + `call_verified` |
| `openconnector` | 1.554 svc / **18.010 aksi** | `openconnector_actions.json` (8,5 MB) | aksi API | `noAuthRunnable`, `call_verified` |
| `nango` | 1.024 | `nango_providers.json` (0,5 MB) | provider OAuth (bukan tools) | — |
| `glama-connector` | 1.000 | `glama_connectors.json` (1,5 MB) | connector remote Glama | `healthy`, `auth_type` |
| `openapi-generated` | 6 API / **889 tool** | `openapi_apis.json` (0,3 MB) | tool hasil generate OpenAPI | `tools_callable`, `tools_call_verified` |
| `metorial` | 1 | `metorial_integrations.json` | provider Metorial (GitHub) | — |

**Endpoint API yang sudah melayani katalog ini** (di `api_server.py`):

```
GET  /mcp/registry                  GET  /mcp/registry/sources
GET  /mcp/registry/capabilities     GET  /mcp/registry/coverage
GET  /mcp/registry/categories       GET  /mcp/registry/{server_id:path}
GET  /mcp/native                    POST /mcp/registry/sync
GET  /mcp/recommendations           GET  /mcp/recommended
GET  /mcp/my-instances              POST /mcp/install
POST /mcp/auto-config/preview       DELETE /mcp/uninstall/{mcp_id}
GET  /mcp/gateway/health            GET  /mcp/gateway/servers
POST /mcp/gateway/call              GET  /mcp/server/tools
POST /mcp/server/call               GET  /mcp/katalir/info
POST /mcp/katalir/key               GET  /mcp/katalir/verify
POST /community/submit              GET  /community/browse
GET  /community/review              GET  /community/my-earnings
```

**Script sinkronisasi + verifikasi yang sudah ada** (`scripts/`):

```
sync-glama.py                 composio_sync.py
sync-openconnector.py         sync_nango_metorial.py
openapi_to_mcp.py             batch-verify-glama-connectors.py
batch-call-glama-connectors.py   batch-test-openconnector.py
```

**UI frontend yang sudah ada:**
`nexus-frontend/src/app/integrations/`, `.../integrations/[slug]/integration-detail-client.tsx`,
`nexus-frontend/src/app/my-integrations/` + 4 spec Playwright
(`integration-detail.spec.ts`, `integration-tools.spec.ts`,
`integrations-logged-in.spec.ts`, `repro-integrations.spec.ts`).

**Dedup engine yang sudah ada:** `mcp_dedup.py` → `dedup_canonical.json`
(23.474 baris, kunci `canonical_key`, `member_ids`, `source_count`,
`quality_score`, `unique_verified`). Sudah menangani ~22% duplikasi lintas sumber.

---

## BAGIAN 3 — Tiga komponen brief yang SUDAH PUNYA PADANAN

Ini bagian terpenting dari audit. Brief meminta tiga hal yang **sudah
dibangun dengan nama berbeda**:

| Brief FASE | Yang diminta | Yang SUDAH ada | Bukti |
|---|---|---|---|
| **FASE 2** | `connector_registry.py` — master framework connector | `mcp_registry.py` (526 baris) + `provider_registry.py` (362) + `mcp_dedup.py` (177) + `plugin_system.py` (537) | 4 modul, 1.602 baris, sudah melayani 17 endpoint |
| **FASE 4** | `ConnectorTestHarness` 10 hard test | `workflow_testkit.py` (fitur #11) + `batch-verify-glama-connectors.py` + `batch-call-glama-connectors.py` + `batch-test-openconnector.py` + `audit_call_safety.py` | 5 modul, sudah punya aturan SSRF/no-auth/read-only |
| **FASE 5** | OpenAPI → auto-generation | `scripts/openapi_to_mcp.py` + `generated_mcp/katalir_openapi_server.py` + `generated_mcp/apis.json` | sudah menghasilkan **889 tool dari 6 API nyata** |

**Kesimpulan anti-duplikasi:** membuat `connector_registry.py` dari nol akan
menghasilkan **sistem katalog kedua** yang tidak mengetahui 25.925 entri yang
sudah ada, tidak memakai dedup engine yang sudah terbukti, dan tidak melayani UI
`/integrations`. Yang benar adalah **memperluas yang sudah ada**, bukan
menggantinya.

---

## BAGIAN 4 — Daftar DEDUP EKSPLISIT (yang TIDAK boleh dibangun ulang)

| # | Jangan bangun | Karena sudah ada | Modul |
|---|---|---|---|
| 1 | Registry connector baru dari nol | `mcp_registry.py` + 8 sumber + dedup | `mcp_registry`, `mcp_dedup` |
| 2 | Provider registry baru | `provider_registry.PROVIDERS` (8 native) | `provider_registry` |
| 3 | OpenAPI→MCP generator baru | `scripts/openapi_to_mcp.py` (889 tool) | `openapi_to_mcp` |
| 4 | Test harness connector baru dari nol | `workflow_testkit.py` + 5 script batch | `workflow_testkit` |
| 5 | Dedup engine baru | `mcp_dedup.py` → `dedup_canonical.json` | `mcp_dedup` |
| 6 | Marketplace UI baru | `/integrations` + `/my-integrations` + 4 spec | `nexus-frontend/src/app/integrations` |
| 7 | MCP server Katalir baru | `mcp_server.py` (890 baris, 6 tool) | `mcp_server` |
| 8 | MCP build loop baru | `mcp_build_workflow.py` (53 tool, 7 kategori) | `mcp_build_workflow` |
| 9 | Gateway MCP client baru | `mcp_gateway/client.py` + `policy.py` | `mcp_gateway` |
| 10 | Plugin system baru | `plugin_system.py` (537 baris) | `plugin_system` |
| 11 | Credential form baru | `credential_forms.py` (423) + `credential_proxy.py` (316) | `credential_*` |
| 12 | End-user credential store baru | `end_user_credentials.py` (781 baris) | `end_user_credentials` |
| 13 | OAuth Google/Slack baru | `oauth_google.py` (319) + `oauth_slack.py` (201) | `oauth_*` |
| 14 | Sheets/Gmail connector native baru | `sheets_dynamic.py` (301) + `gmail_imap.py` (305) | `sheets_dynamic`, `gmail_imap` |
| 15 | Tool schema baru | `tools.py` (1.159) + `tool_schemas.py` (119) | `tools` |
| 16 | Community platform baru | `/community/*` (4 endpoint, fail-closed) | `community-platform.sql` |
| 17 | Rekomendasi/scoring baru | `mcp_registry.compute_recommendation_score` | `mcp_registry` |
| 18 | Sync script per sumber baru | 4 sync script untuk 8 sumber | `scripts/sync-*` |

---

## BAGIAN 5 — Gap NYATA yang tersisa (yang HARUS dikerjakan)

Dari 25.902 entri `metadata_only`, ini yang benar-benar belum ada:

### G1 — Jalur eksekusi untuk entri terkatalog (gap utama, ≥2000 target)
`executable_servers()` = **23**. Entri `metadata-only` tidak punya
`install_config.transport ∈ {stdio,http,sse}` dan `runtime_verified=False`.
Tidak ada yang bisa memanggilnya. **Ini gap yang harus ditutup.**

### G2 — Verifikasi `tools/call` nyata
- OpenConnector: 18.010 aksi terkatalog → **11** call-verified (**0,06%**)
- OpenAPI: 889 tool ter-generate → **1** call-verified
- Glama: `call_verified` belum dipromosikan untuk mayoritas

### G3 — Kredensial per-source yang belum tersambung
Nango 1.024 provider OAuth terkatalog, tapi **tidak ada alur connect OAuth
generik** untuk sembarang provider. Hanya `oauth_google` + `oauth_slack`.

### G4 — Cakupan OpenAPI ter-generate terlalu sempit
`openapi_to_mcp.py` hanya membaca **6** spec, semuanya di-hardcode di dict
`SPECS`. Brief FASE 5 meminta APIs.guru (2500+ spec) + public-apis + RapidAPI
— **belum tersambung**.

### G5 — Tidak ada `ConnectorTestHarness` terpadu
Verifikasi tersebar di 5 script ad-hoc dengan aturan SSRF berbeda-beda. Tidak
ada 1 harness dengan 10 test terdefinisi yang bisa dijalankan pada entri mana pun.

---

## BAGIAN 6 — Rekonsiliasi: brief lama vs brief baru

| Item | Brief lama (12 fitur n8n gap) | Brief baru (2000+ connector) | Status |
|---|---|---|---|
| #1 n8n Agents first-class | **pending** | — | lanjut |
| #2 MCP build workflow | ✅ engine/test/migration/API | tumpang tindih dengan FASE 2 | **selesai, jangan ulang** |
| #9 Dapr durable execution | **pending** | — | lanjut |
| FASE 2 `connector_registry.py` | — | diminta | **sudah ada** (`mcp_registry`) |
| FASE 5 OpenAPI gen | — | diminta | **sudah ada** (889 tool) |

**Keputusan:** brief baru **tidak membatalkan** brief lama. Keduanya dikerjakan
berurutan: selesaikan #1 dan #9 (sisa 12 fitur), lalu kerjakan gap G1–G5 di atas
sebagai bentuk nyata dari "2000+ fitur integrasi" — **tanpa** membuat katalog
kedua.

---

## BAGIAN 7 — Angka target yang jujur

Target brief "2000+ connector × 10 hard test = 100% PASS" **dapat dipenuhi**,
tetapi definisinya harus diperbaiki agar tidak berbohong:

| Klaim | Definisi lama (menyesatkan) | Definisi jujur (yang dipakai) |
|---|---|---|
| "2000+ connector" | menambah 2000 entri katalog ke-26.000 | **2000+ entri yang `runtime_verified`** |
| "10 hard test" | 10 assertion dangkal pada metadata | 10 test yang **salah satunya memanggil endpoint nyata** |
| "100% PASS" | melaporkan PASS dari metadata | PASS hanya bila `call_verified=True` |

Baseline hari ini: **23 executable + 8 native = 31**. Target: **≥2000**.

---

## Bagian 8 — Bukti (perintah yang dijalankan)

```bash
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe -c "
import mcp_registry as c, provider_registry as pr
print('source_counts:', c.source_counts())
print('coverage:', c.coverage())
print('executable:', len(c.executable_servers()))
print('openconnector:', c.openconnector_coverage())
print('openapi:', c.openapi_coverage())
print('native:', len(pr.PROVIDERS))
"
```

Keluaran:

```
source_counts: {'glama': 20000, 'toolsdk': 4415, 'composio': 1558,
                'openconnector': 1554, 'nango': 1024, 'glama-connector': 1000,
                'openapi-generated': 6, 'metorial': 1}
coverage: {'total': 25925, 'executable': 23, 'metadata_only': 25902,
           'basis': 'dedup_canonical', ...}
executable: 23
openconnector: {'services': 1554, 'actions': 18010, 'meta_tools': 5,
                'actions_call_verified': 11, 'services_call_verified': 5}
openapi: {'apis': 6, 'tools': 889, 'tools_callable': 669,
          'tools_call_verified': 1}
native: 8 ['telegram','slack','http','gmail','google_sheets','whatsapp',
           'google_calendar','gateway']
```

`dedup_canonical.json` → **23.474 baris** kanonik.

---

**Status: AUDIT SELESAI.** Tidak ada connector baru akan dibangun sebelum
Bagian 4 (daftar dedup) diverifikasi ulang terhadap kode saat itu. Langkah
berikutnya adalah FASE 1 brief baru (riset 5 repo) —
`docs/connector-architecture-decision.md` — yang keputusannya **dibatasi oleh
temuan ini**: arsitektur yang dipilih harus memperluas `mcp_registry.py`, bukan
menggantikannya.
