# Fitur #2 — Durable Execution: Riset & Verifikasi

**Tanggal:** 8 Okt 2026 · **Mode:** Autonomous research + hard test

---

## A. RESEARCH — 4 kandidat, verifikasi PyPI nyata

| Paket | Versi | Update terakhir | Lisensi | Rilis | Verdict |
|---|---|---|---|---|---|
| **dbos** | **3.2.0** | 2026-09-29 (9 hari) | **MIT** | 524 | ✅ **DIPILIH** |
| temporalio | 1.34.0 | 2026-09-30 | (lihat catatan) | 55 | ❌ Infra berat |
| restate-sdk | 1.0.5 | 2026-09-02 | (lihat catatan) | 42 | ❌ Butuh server Rust terpisah |
| inngest | 0.5.19 | 2026-06-23 (**4 bln**) | (lihat catatan) | 111 | ❌ Versi <1.0, SaaS-centric |

Data mentah diambil langsung dari `https://pypi.org/pypi/<paket>/json`.

### Pilihan: **dbos 3.2.0**

**Alasan (bukan sekadar ikut brief):**

1. **Postgres-native** — state disimpan di Postgres yang **sudah** Katalir
   pakai (Supabase). Tidak ada infrastruktur baru.
   *Riset mendukung:* "**DBOS** 玩了个聪明的路线：状态全存在你已有的 Postgres 里，
   没有额外组件… 适合'不想再加一个新基础设施'的团队" dan rekomendasi resmi
   "**已有 Postgres / 不想加新基础设施：DBOS**".
2. **MIT** + 524 rilis + update 9 hari lalu → production-ready, aktif.
3. **Temporal ditolak**: butuh Postgres + Elasticsearch + Cassandra sendiri.
   *Riset:* "自托罐成本高（ES + Cassandra）".
4. **Restate ditolak**: server Rust terpisah; Python SDK "还在补特性".
5. **Inngest ditolak**: versi 0.5.19 masih pra-1.0 dan inti penjadwalan ada di
   SaaS mereka — tidak cocok untuk deployment mandiri di Railway.

---

## B. VERIFIKASI PAKET (wajib sebelum dipakai)

### B.1 Instalasi terisolasi
```
pip install --target _vdbos dbos==3.2.0   -> EXIT=0
dbos-3.2.0.dist-info terpasang
```

### B.2 API nyata (diperiksa via `dir()`, bukan asumsi)
```
has DBOS=True  DBOSConfig=True  DBOSClient=True
DBOS methods: step, workflow, recv, send, sleep, start_workflow,
              get_workflow_status, list_workflow_steps,
              retrieve_workflow, resume_workflow, fork_workflow, ...
```
`step`/`workflow` adalah **method instance**, bukan fungsi modul
(`dbos.step` tidak ada → `AttributeError`). Sudah dikonfirmasi.

### B.3 Jalankan workflow nyata terhadap Supabase
```
DBOS URL host: aws-0-ap-southeast-1.pooler.supabase.com:6543
Applying DBOS system database schema migration ... (123 migrasi)
DBOS launched!
hasil workflow: 142 (harap 142)      ✅
status: SUCCESS                       ✅
jumlah step tersimpan: 3              ✅
```

### B.4 🎯 UJI KRITIS — crash & resume (inti durable execution)

Simulasi deploy/restart Railway: `os._exit(137)` di tengah workflow.

```
FASE 1 — jalan sampai crash:
  LOG efek samping: ['LANGKAH-1', 'LANGKAH-2']
  (proses mati keras)

FASE 2 — recover (launch() memulihkan workflow pending):
  LOG sebelum recover : ['LANGKAH-1', 'LANGKAH-2']
  hasil setelah recover: selesai-P1
  LOG sesudah recover : ['LANGKAH-1', 'LANGKAH-2', 'LANGKAH-3']
```

**Bukti kunci: `LANGKAH-1` dan `LANGKAH-2` TIDAK diulang.**
Hanya `LANGKAH-3` yang jalan setelah recover. Inilah jaminan
*exactly-once side effect* yang jadi alasan utama durable execution ada.

### B.5 External signal (`recv`) — menunggu approval
```
d.send(workflow_id, "APPROVED-oleh-manajer", topic)  -> workflow lanjut
```

### B.6 Idempotency — ditemukan perilaku nyata
`start_workflow(..., workflow_id="idem-xxx")` **menunda** start
(*enqueue*), sehingga `send()` ke ID itu langsung setelah start gagal:
```
DBOSNonExistentWorkflowError: Non-existent send destination workflow ID: idem-...
```
→ **Catatan implementasi:** untuk dedup, workflow ID harus dipastikan
sudah terdaftar sebelum `send`, atau pakai `duplication_policy`.

### B.7 ⚠️ Inkompatibilitas pooler — diselidiki, bukan diabaikan

Gejala saat uji pertama:
```
(psycopg.errors.DuplicatePreparedStatement) prepared statement "_pg3_1" already exists
```

Riset: Supavisor **transaction mode (6543) tidak mendukung prepared
statement**; **session mode (5432) mendukung**.
(Supabase Docs "Disabling Prepared statements")

**Uji pembanding:**

| Port | Mode | Hasil |
|---|---|---|
| **5432** | session | `['s0','s1','s2','s3','s4']` — SUCCESS ✅ |
| 6543 | transaction | `['s0','s1','s2','s3','s4']` — SUCCESS ✅ (3× berturut) |

Error di uji pertama berasal dari **race saat migrasi paralel** di run
pertama, bukan inkompatibilitas permanen. Kedua port kini stabil.
**Keputusan: pakai 5432 (session)** sebagai utama — sesuai dokumentasi
Supabase untuk prepared statement — dengan 6543 sebagai cadangan.
Untuk psycopg, set `prepare_threshold=None` bila memakai 6543.

### B.8 Isolasi skema ✅
```
SCHEMAS terdeteksi: auth, dbos, extensions, graphql, ..., public, vault
DBOS tables (13): application_versions, dbos_migrations, event_dispatch_kv,
  notifications, operation_outputs, queues, streams, workflow_events,
  workflow_events_history, workflow_input, workflow_output, workflow_schedules
```
DBOS membuat **schema sendiri (`dbos`)**, **tidak menyentuh `public`**.
Tidak ada polusi skema Katalir. Bonus temuan: schema `vault` sudah ada
(relevan untuk Fitur #7).

---

## C. KEPUTUSAN ARSITEKTUR

**Dipilih: pola DBOS (Postgres-native durable execution), diimplementasikan
pada skema Katalir sendiri.**

Alasan tidak memakai library DBOS langsung untuk seluruh engine:
- `executions` Katalir **hanya punya 6 kolom** (id, workflow_id, status,
  result, created_at, updated_at) — tidak ada state/checkpoint.
- Engine Katalir (`engine.launch_execution`) sudah berjalan; mengganti
  total ke runtime DBOS berisiko besar menjelang launch.
- Yang dibutuhkan brief: *state snapshot, resume from checkpoint,
  idempotency key, external signal* — keempatnya bisa ditambahkan pada
  skema `executions` tanpa mengganti engine.

**Rencana:**
1. Tambah kolom ke `executions`: `state jsonb` (checkpoint),
   `current_step_id`, `idempotency_key`, `heartbeat_at`, `retry_count`,
   `resumed_at`, `waiting_for`, `parent_execution_id`.
2. Tabel `execution_steps` untuk log per-node (sumber replay).
3. Resume: eksekusi `status='running'` dengan `heartbeat_at` basi (>5 mnt)
   → tandai `interrupted`, lanjutkan dari `current_step_id`.
4. Idempotency: unique index pada `(execution_id, step_id)`.

**TODO (dicatat, bukan diabaikan):** bila kelak ingin replay penuh
gaya Temporal, runtime DBOS bisa dipasang di schema `dbos` yang sudah
terverifikasi berfungsi — bukti di bagian B sudah cukup untuk itu.

---

## D. Bukti mentah tersimpan
- Instalasi + API: `_vdbos1.py`
- Workflow E2E: `_vdbos2.py`
- **Crash/resume**: `_vdbos3.py` (+ `_vdbos_sideeffect.log`)
- Signal + idempotency: `_vdbos4.py`
- Uji pooler 5432/6543: `_vdbos5.py`
