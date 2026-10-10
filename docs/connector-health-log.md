# Connector Health Log — Uji & Perbaikan Semua Konektor

Laporan per fase sesuai brief "UJI & PERBAIKI SEMUA 25.925 KONEKTOR".
Prinsip pelaporan: hanya angka dari probe live yang dilaporkan sebagai hasil;
angka katalog selalu dilabeli sebagai katalog (metadata), bukan "terhubung".

## FASE #0.1: Skema persistence `connector_activation` v2

### Research
| Sumber | Link | Temuan | Keputusan |
|--------|------|--------|-----------|
| Supabase Python/Postgres docs | https://supabase.com/docs/reference/python | Persistence via tabel + RLS, bukan file | DB = source of truth (sudah diterapkan fase sebelumnya) |
| Railway outage note | https://status.railway.com (30 Sep 2026, routing layer) | Gejala "Application not found" | Mendorong diagnosis FASE 0.2 |

### Implementasi
- Migrasi: `migrations/2026-10-10-connector-activation-v2.sql`
  (kolom `status`, `http_status`, `tools_count`, `last_live_check`,
  `check_interval_hours`, `next_check_at`, `auth_type`, `error_message`,
  `updated_at` + index pada `status`/`next_check_at`/`source`).
- Backfill `auth_type` dari katalog + `last_live_check` dari hasil census.

### Verifikasi
- 994 baris terisi `status` + `last_live_check` (raw output di log sesi).
- Distribusi status dari DB (bukan file): sesuai census census probe live.

## FASE #0.2: Backend produksi Railway — HARD STOP (kondisi keras #2)

### Diagnosis (bukti raw output di log sesi)
1. Kedua domain (`web-production-dc90b`, `web-production-3b02b`) → 404
   "Application not found".
2. Akar: **2 deployment terakhir status FAILED** (September) — aplikasi
   memang tidak jalan, bukan masalah routing.
3. `deploymentRestart` pada deployment FAILED tidak mungkin; perlu deploy baru.
4. Railway CLI v5 menolak token (OAuth browser flow) — **tapi GraphQL API
   menerima token** (`backboard.railway.com/graphql/v2`, endpoint
   `.com` bukan `.app`).
5. Deploy baru via mutation `serviceInstanceDeployV2(commitSha: 88ceff6…)`
   ditolak: **"Your trial has expired. Please select a plan."**

### Keputusan
Hard stop kondisi keras #2 (butuh aksi manusia: memilih paket berbayar /
menambah kartu kredit di dashboard Railway). Tidak bisa diselesaikan secara
otomatis. TODO: pilih plan → trigger ulang
`serviceInstanceDeployV2(sha=88ceff6…, svc=996f34a1-…, env=b332795c-…)`.

## FASE #1: Census live semua konektor ber-URL

### Hasil census URL (dari katalog 29.982 entri)
| Transport | n | punya URL HTTP teruji |
|---|---|---|
| metadata-only | 24.415 | 20.002 (via `source_url`) |
| streamable_http | 1.000 | 1.000 |
| composio-remote | 1.558 | 0 |
| mcp-meta-layer | 1.554 | 0 |
| openapi-generated | 6 | 6 |
| lainnya (None) | 1.318 | 1.317 |

Catatan jujur: `source_url` pada entri metadata-only umumnya URL repo
dokumentasi, **bukan endpoint MCP** — tidak layak diprobe sebagai konektor.
Yang bisa diuji dengan protokol MCP penuh = 1.000 endpoint streamable_http.

### Hasil probe live (semua 1.000, persisted ke `connector_health`)
| Verdict | Jumlah | % |
|---|---|---|
| ALIVE | 660 | 66,0% |
| AUTH | 309 | 30,9% |
| DEAD | 20 | 2,0% |
| UNKNOWN | 11 | 1,1% |

### Meta-test harness (reprodusibilitas)
- 3/3 konsisten: konektor ALIVE diketahui → ALIVE ulang; AUTH → AUTH; DEAD → DEAD.
- Harness: `connector_prober.probe_endpoint` (protokol MCP initialize +
  tools/list, klasifikasi 200+RPC-error = UNKNOWN, bukan ALIVE).

## FASE #2.2: Fix auth-gated — HARD STOP (kondisi keras #1) untuk 309/309

Pencocokan nama provider 309 konektor AUTH terhadap kredensial di `.env`
(github/google/groq/nvidia/deepseek): **nol kecocokan**. `.env` hanya
berisi kredensial LLM/infrastruktur sendiri. Maka semua AUTH → daftar
"needs credential", tidak ada yang bisa di-connect otomatis tanpa
kredensial pihak ketiga.

## FASE #2.3: Fix dead

Sudah ditangani putaran sebelumnya (repair log
`docs/audit/evidence/repair-log.jsonl`): 3 fixed / 1 refused /
25 unfixable → `healthy=False`, tidak ada yang dihapus. ALIVE 660 → 663.
Entri tanpa URL (24.908) **mustahil** diprobe → dilabeli `metadata-only`,
tidak dihitung sebagai alive maupun dead.

## FASE #3: Background health check

- `api_server.py` lifespan: loop asyncio `connector_pulse` baru,
  kill-switch `CONNECTOR_PULSE_ENABLED=1` (default OFF agar test suite
  tidak memicu probe jaringan), probe saat `due()` (interval 6 jam via
  `next_run_at` + claim pattern, tanpa APScheduler).
- Shutdown bersih (cancel task di `__aexit__` lifespan).
- Tes: `tests/test_connector_pulse.py` **15 passed**.

## FASE #4: Dashboard `/connectors/health`

Sudah ada dari putaran sebelumnya; ditambah sesuai brief FASE 4:
- Filter status (klik kartu ALIVE/AUTH/DEAD/UNKNOWN) — sudah ada.
- **Pencarian nama connector** (input search, filter klien).
- **Kolom "Dicek"** (timestamp `checked_at` per baris).
- Perbandingan katalog vs probe live (anti-klaim berlebihan) — sudah ada.

## Batasan yang diakui (jujur)

- Backend produksi masih 404 sampai plan Railway dipilih (FASE 0.2).
- 309 AUTH menunggu kredensial; 0 tersedia di `.env`.
- 24.908 konektor metadata-only tanpa endpoint → tidak bisa diuji live,
  tidak dihitung dalam angka health.
- Total yang *bisa* diuji live: 1.006 endpoint (1.000 streamable_http +
  6 openapi-generated); sisanya katalog metadata.
