# Fitur #5 — Parallel Fan-Out / Fan-In

**Status:** ✅ SELESAI — 12/12 skenario lolos (3× berturut-turut)
**Modul:** `parallel_fanout.py` · **Migrasi:** `migrations/2026-10-08-parallel-fanout.sql`
**Tes:** `tests/test_parallel_fanout.py`

---

## A. RESEARCH

Mesin Katalir (`execution_engine.StatefulOrchestrator.run`) **sudah** menjalankan
node selevel lewat `asyncio.gather`, tetapi brief meminta tiga hal yang **tidak
ada** di sana:

| Yang diminta brief | Status sebelum #5 |
|---|---|
| Merge/join barrier — "merge tunggu semua" | ❌ tidak dijamin; satu cabang gagal → `RuntimeError` melempar, cabang lain dibiarkan menggantung |
| Timeout per cabang | ❌ tidak ada; satu cabang lambat menahan seluruh gelombang |
| Partial-failure handling | ❌ tidak ada; tidak ada pilihan `all_settled` / `quorum` |

Karena itu Fitur #5 dibangun sebagai **lapisan orkestrasi fan-out/fan-in** di
atas checkpoint durable yang sudah ada, bukan menulis ulang mesin.

### Perbandingan kandidat

| Paket / Pendekatan | Versi | Verdict | Alasan |
|---|---|---|---|
| **anyio** | 4.15.1 (PyPI) / 4.12.1 (terpasang) | ✅ **DIPAKAI** | MIT, `Development Status :: 5 - Production/Stable`, rilis 5 Sep 2026, 5 maintainer, 2.553 bintang. `move_on_after` = timeout **per cabang** tanpa membatalkan saudaranya; `create_task_group` = barrier eksplisit. Sudah jadi dependensi transitif FastAPI/Starlette → tidak menambah beban baru. |
| `asyncio.TaskGroup` | bawaan Python ≥3.11 | ❌ ditolak sebagai primitif utama | Semantiknya **semua-atau-tidak-sama-sekali**: satu tugas gagal → seluruh grup dibatalkan. Itu kebalikan dari "partial failure handling" yang diminta. (Tetap dipakai sebagai *carrier* karena Katalir berjalan di loop asyncio — lihat catatan.) |
| `asyncio.gather(return_exceptions=True)` | bawaan | ⚠️ sebagian | Bisa menunggu semua & mengumpulkan pengecualian, tetapi **tidak punya timeout per-item** — timeout harus dibungkus manual. Primitif ini yang dipakai mesin lama; #5 memakai `anyio.move_on_after` untuk bagian timeout. |
| `mcp-agent` (ParallelLLM / `parallel` workflow) | — | ❌ | Pola fan-out/fan-in bagus & terdokumentasi (docs.mcp-agent.com/workflows/parallel), tetapi menyeret **framework agen penuh** + asumsi pemanggilan LLM. Terlalu berat untuk kebutuhan "jalankan N cabang, tunggu semua, gabungkan". |
| PyAgent — pola *Fan-Out/Fan-In* | — | ❌ | Dokumentasi pola (`pyagent.org/packages/patterns/orchestration/fan-out-fan-in/`), bukan pustaka inti yang bisa dipin. |
| Temporal / Restate / Inngest | — | ❌ | Memerlukan infrastruktur terpisah (server) atau SDK pra-1.0; mengganti engine menjelang launch tidak dapat dibenarkan. Sudah dievaluasi & ditolak di Fitur #2. |

### Verifikasi paket (bukan asumsi)

Instalasi terisolasi + uji API nyata:

```
pip install --target ./_verify_f5 anyio
→ anyio 4.15.1 terpasang

T1 basic  : ['B ok', 'A ok']                       # task group dasar
T2 timeout: {'cepat': 'cepat ok', 'lambat': 'TIMEOUT'}   # timeout PER cabang
T3 partial: {'satu': 'satu ok', 'dua': 'ERR:dua gagal'}  # kegagalan tidak menular
```

Metadata resmi (`anyio-4.15.1.dist-info/METADATA`):
```
Name: anyio
Version: 4.15.1
License-Expression: MIT
Classifier: Development Status :: 5 - Production/Stable
Requires: Python >=3.10
```

**Pilihan:** `anyio` 4.12.1 (pin di `requirements.txt`).

**Alasan:** satu-satunya kandidat yang memberi **timeout per cabang tanpa
membatalkan saudaranya** *dan* **barrier tunggu-semua** dalam satu API, berlisensi
MIT, Production/Stable, dan **sudah menjadi dependensi transitif** Katalir —
sehingga tidak menambah permukaan dependensi baru menjelang launch.

---

## B. IMPLEMENTASI

### Berkas

| Berkas | Perubahan |
|---|---|
| `parallel_fanout.py` | **Baru.** Fan-out, status per cabang, fan-in (3 kebijakan), eksekutor paralel, resume. |
| `migrations/2026-10-08-parallel-fanout.sql` | **Baru.** Tabel `execution_branches`, kolom `executions.parallel_policy`, `execution_steps.timeout_seconds`, RPC `branch_summary`, RPC `bulk_update_branches`, RLS. |
| `requirements.txt` | Pin `anyio==4.12.1`. |
| `tests/test_parallel_fanout.py` | **Baru.** 12 skenario. |

### DDL

```sql
create table public.execution_branches (
    id            uuid primary key default gen_random_uuid(),
    execution_id  uuid not null references public.executions(id) on delete cascade,
    split_step_id text not null,     -- node SPLIT pemilik cabang
    branch_key    text not null,     -- identitas cabang ("0", "alamat", …)
    merge_step_id text,              -- node MERGE yang menunggu
    status        text not null default 'pending',
                  -- pending|running|success|failed|timeout|skipped|cancelled
    attempt       integer not null default 1,
    input  jsonb, output jsonb, error text,
    started_at timestamptz, finished_at timestamptz,
    created_at timestamptz not null default now(),
    constraint branch_split_key unique (execution_id, split_step_id, branch_key)
);
```

`unique (execution_id, split_step_id, branch_key)` adalah **kunci idempotensi**:
resume setelah restart tidak bisa menggandakan cabang — dan karenanya tidak
menggandakan efek samping.

### API modul

| Fungsi | Guna |
|---|---|
| `fan_out(execution_id, split_step_id, branch_keys, merge_step_id, inputs, policy)` | Daftarkan cabang (idempoten). Simpan `parallel_policy`. |
| `list_branches(execution_id, split_step_id, user_id)` | Baca cabang; `user_id` memaksa cek kepemilikan. |
| `mark_branch(...)` | Perbarui satu cabang (dipakai resume/endpoint). |
| `mark_branches_bulk(execution_id, split_step_id, updates)` | Perbarui **banyak** cabang dalam **satu** round trip. |
| `branch_summary(execution_id)` | Agregat (total/success/failed/timeout/running/settled) via RPC. |
| `all_settled(execution_id, merge_step_id)` | True bila tak ada cabang berjalan. |
| `merge_decision(execution_id, policy)` | Fan-in: `all_success` / `all_settled` / `quorum`. |
| `run_branches(...)` | **Eksekutor paralel**: timeout per cabang, barrier, tulis status ke DB. |
| `unfinished_branches(...)`, `seconds_since_start(...)` | Dukungan resume. |

### Kebijakan fan-in

| Policy | Merge sukses bila |
|---|---|
| `all_success` | **semua** cabang sukses (barrier klasik) |
| `all_settled` | semua cabang **selesai**, apa pun hasilnya; yang gagal dilaporkan, bukan fatal |
| `quorum` | **mayoritas murni** sukses (`>= total//2 + 1`) — 2/4 ditolak, 3/4 diterima |

---

## C. HARD TEST

Supabase **nyata**, 12 skenario (brief minta min 8).

| # | Skenario | Status | Bukti (raw) |
|---|---|---|---|
| 1 | 3 cabang paralel semua sukses | ✅ | `ok=True reason=semua cabang sukses` · `summary{total:3, success:3, failed:0}` |
| 2 | Merge tunggu SEMUA (barrier) | ✅ | 3-cabang vs 1-cabang(0.30s): **tambah 2 cabang hanya +0.09s** (seri akan +0.15s) |
| 3 | Output tiap cabang terpisah di DB | ✅ | 2 baris, `output={'cabang':'x','nilai':120}` / `{'cabang':'y','nilai':121}`, semua `finished_at` terisi |
| 4 | **Durability**: status bertahan setelah restart | ✅ | `sesi-2 summary == sesi-1 summary` · `jumlah_baris=2` |
| 5 | **Durability**: resume tidak menggandakan cabang | ✅ | `belum final: ['r2','r3']` · `setelah fan_out ulang, jumlah baris = 3` (bukan 6) · cabang sukses **tidak** diturunkan ke running |
| 6 | **Edge**: timeout PER cabang | ✅ | `timeout_keys=['lambat']` · `2 sukses, 0 gagal, 1 timeout` · durasi < 2s (bukan 5s) |
| 7 | **Edge**: partial failure → `all_settled` lanjut | ✅ | `success=2, failed=1, failed_keys=['rusak'], ok=True` |
| 8 | **Edge**: `all_success` gagal bila ada cabang gagal | ✅ | `ok=False`, `failed_keys=['b']` |
| 9 | **Edge**: `quorum` | ✅ | 2/4 → `ok=False (butuh >= 3)` · 3/4 → `ok=True` |
| 10 | **Edge**: validasi input | ✅ | `kosong -> []` · `duplikat ditolak` · `65 cabang melebihi MAX_BRANCHES=64` · `policy ngawur ditolak` |
| 11 | **Security**: isolasi antar user | ✅ | `user asing lihat 0 cabang` · `milik_user(...) is False` |
| 12 | **Performance**: 8 cabang paralel vs seri | ✅ | `paralel=0.62s < 0.65s (seri 0.80s)` |

Hasil akhir: **`12 passed`** — dijalankan 3× berturut-turut: `12 passed / 12 passed / 12 passed`.

### Dua bug nyata yang ditemukan tes ini

**BUG-5a — fan-out "paralel" justru lebih lambat daripada seri.**
`test_02` & `test_12` awalnya gagal dengan waktu **lebih besar** daripada seri
(`8 cabang × 0.1s → 2.89s` vs seri `0.80s`).
Dua sebab, ditemukan lewat probe terukur:
1. Semua tulis-baca DB di `run_branches` **sinkron** (klien PostgREST) dan
   dipanggil langsung dari korut → **memblokir event loop**, sehingga cabang
   "paralel" berjalan berurutan. → diperbaiki dengan `asyncio.to_thread`.
2. Bahkan setelah itu, terukur **satu panggilan PostgREST = ~110–125 ms**.
   Menulis 8 cabang satu-per-satu = 16 round trip = >0,9 s hanya untuk
   pembukuan. → diperbaiki dengan menulis **satu kali massal** di awal
   (semua `running`) dan **satu kali massal** di akhir (semua hasil).
   Setelah perbaikan: `2.89s → 0.62s`.

**BUG-5b — `upsert` PostgREST tidak bisa untuk pembaruan parsial.**
Upaya pertama memakai `table(...).upsert(payload, on_conflict="id")` gagal:
```
APIError 23502: null value in column "execution_id" of relation
"execution_branches" violates not-null constraint
```
PostgREST memperlakukan payload parsial sebagai **INSERT**, sehingga kolom
NOT NULL menjadi NULL. → diganti dengan RPC SQL
`bulk_update_branches(execution_id, split_step_id, jsonb)` yang benar-benar
meng-`UPDATE` baris yang ada (`update ... where`), plus **fallback per-cabang**
bila RPC tak tersedia sehingga fan-out tidak pernah gagal hanya karena
optimasi.

### Catatan desain (kesalahan tes, bukan kode)

`quorum` awalnya memakai `len(sukses) >= total/2`, sehingga **2 dari 4**
dianggap kuorum. Tes #9 benar menolaknya: tepat separuh bukan mayoritas.
Ambang diubah ke **mayoritas murni** `total//2 + 1` — sekarang 2/4 ditolak,
3/4 diterima.

---

## D. VERIFIKASI

- `pytest tests/test_parallel_fanout.py` → **12 passed**, 3× berturut-turut.
- Migrasi diterapkan & diverifikasi:
  ```
  [OK] migrasi fan-out diterapkan
  [OK] RPC: ['branch_summary', 'bulk_update_branches']
  [OK] executions.parallel_policy: True
  ```
- Pemeriksaan langsung `pg_proc`:
  ```
  RPC: branch_summary | p_execution_id uuid
  RPC: bulk_update_branches | p_execution_id uuid, p_split_step_id text, p_updates jsonb
  ```

## E. STATUS

Lolos. Lanjut ke Fitur #6 (Code Node / Sandbox).
