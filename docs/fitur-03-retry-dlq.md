# Fitur #3 — Retry + Exponential Backoff + DLQ + Circuit Breaker

**Tanggal:** 8 Okt 2026 · **Mode:** Autonomous research + hard test

---

## Research

| Paket | Versi | Update terakhir | Rilis | Verdict |
|---|---|---|---|---|
| **tenacity** | **9.2.1** | **2026-10-07 (1 hari!)** | 62 | ✅ **DIPILIH** (retry+backoff) |
| **pybreaker** | **1.4.1** | 2025-09-21 | 27 | ✅ dipakai (referensi semantik) |
| backoff | 2.2.1 | **2022-10-05** | 37 | ❌ stagnan ~4 tahun |
| stamina | 26.1.0 | 2026-04-13 | 11 | ❌ muda, API tidak stabil |
| pyresilience | 0.4.0 | 2026-06-12 | 9 | ❌ pra-1.0 |

**Pilihan:** `tenacity 9.2.1` untuk retry, `pybreaker 1.4.1` sebagai rujukan
semantik sirkuit.

**Alasan:** tenacity dirilis **sehari sebelum** sesi ini dan menjadi standar
de-facto Python untuk retry; `backoff` sudah tidak dirawat sejak 2022.

### Verifikasi perilaku (bukan asumsi)
```
tenacity: percobaan=4 hasil=sukses total=0.77s      <- backoff nyata
tenacity: ValueError TIDAK di-retry -> percobaan=1  <- penting
pybreaker: sirkuit TERBUKA pada percobaan ke-3
```

---

## Keputusan desain (dan alasannya)

1. **Hanya error yang layak yang di-retry.** `ValueError`, `TypeError`,
   `KeyError`, `AttributeError` **tidak** di-retry — mengulanginya hanya
   memperlambat kegagalan tanpa mengubah hasil. Sudah diverifikasi: tenacity
   pun berperilaku sama, tapi kita tidak bergantung pada default-nya.

2. **Circuit breaker state-nya PERSISTEN di Postgres.** pybreaker menyimpan
   state di memori; **Railway restart akan "melupakan" sirkuit yang sedang
   terbuka** sehingga proteksi hilang tepat saat paling dibutuhkan. Karena itu
   sumber kebenaran state ada di tabel `circuit_breakers`.
   (Diverifikasi: state terbaca `open` dari DB setelah disimpan.)

3. **DLQ mencatat payload + error + jumlah percobaan**, supaya node bisa
   dijalankan ulang tanpa menebak input aslinya.

---

## Implementasi

- **`retry_policy.py`** — `is_retryable`, `backoff_delay`, `with_retry`,
  `circuit_allows/success/failure/reset`, `push_dlq`, `list_dlq`, `dlq_item`,
  `claim_dlq`, `discard_dlq`, `dlq_stats`, `run_protected`.
- **`migrations/2026-10-08-retry-dlq.sql`** — tabel `dead_letter_queue`,
  `circuit_breakers`, RPC `claim_dlq_item`, `dlq_stats`, RLS.

---

## 🐞 BUG-3a — DLQ selalu gagal senyap (error 42P10)

Versi pertama migrasi memakai **partial unique index**:
```sql
create unique index uq_dlq_exec_step
    on dead_letter_queue (execution_id, step_id)
    where execution_id is not null;      -- <-- INI MASALAHNYA
```
Postgres **menolak** index parsial sebagai target `ON CONFLICT`:
```
APIError 42P10: there is no unique or exclusion constraint
matching the ON CONFLICT specification
```
Karena `push_dlq` menelan exception (memang sengaja: DLQ tidak boleh
menjatuhkan alur), kegagalan ini **tersembunyi** — 11 tes lolos, 5 gagal,
tanpa satu pun error yang terlihat.

**Perbaikan:** `execution_id NOT NULL` + **constraint unik biasa**.
**Plus:** `push_dlq` kini mencetak `[dlq] GAGAL menyimpan ...` sehingga
kegagalan tidak lagi senyap.

## 🐞 BUG-3b — KEBOCORAN DATA antar-user di klaim DLQ

RPC `returns public.dead_letter_queue` membuat PostgREST mengembalikan
**dict berisi NULL semua** saat tidak ada baris yang cocok — dan `dict`
itu **truthy di Python**:
```python
# SEBELUM
return data            # -> {'id': None, ...} -> dianggap SUKSES
```
Akibatnya **user asing seolah berhasil mengklaim item DLQ orang lain**
(tes 14 menangkapnya: `KEBOCORAN: item terklaim`).

**Perbaikan (dua lapis):**
1. SQL: `returns jsonb` → `select to_jsonb(k) from klaim k`
   (diverifikasi: hasil kosong sekarang `None`, bukan dict NULL).
2. Python: validasi hasil **wajib punya `id` dan `user_id`**, bukan sekadar
   `is not None`.
3. `dlq_stats` juga divalidasi + fallback hitung langsung.

---

## Hard Test — 16/16 PASS (raw evidence)

| # | Skenario | Status | Bukti |
|---|---|---|---|
| 1 | sukses setelah retry | PASS | `percobaan=3 hasil=ok` |
| 2 | menyerah setelah max | PASS | `percobaan=4 error=TimeoutError` |
| 3 | backoff eksponensial + jitter | PASS | `1,2,4`; cap=30; jitter variasi |
| 4 | ValueError tidak di-retry | PASS | `percobaan=1` |
| 5 | TypeError/KeyError/AttributeError | PASS | ketiganya `1` percobaan |
| 6 | sirkuit terbuka | PASS | `5 gagal -> open, allows=False` |
| 7 | sirkuit menutup setelah sukses | PASS | `closed + allows=True` |
| 8 | **sirkuit PERSISTEN** | PASS | `state di DB = open` |
| 9 | gagal masuk DLQ | PASS | `step=node_x attempts=3 status=pending` |
| 10 | DLQ idempoten | PASS | 3× gagal → `1 baris` |
| 11 | sukses tidak masuk DLQ | PASS | `dlq=False`, DLQ kosong |
| 12 | sirkuit open → fail fast | PASS | `fn dipanggil 0x` + masuk DLQ |
| 13 | klaim atomik | PASS | `klaim#1=True klaim#2=False` |
| 14 | **isolasi antar-user** | PASS | `list=[] item=None claim=None discard=False` |
| 15 | statistik DLQ | PASS | `{'pending': 2}` |
| 16 | performa | PASS | `10 node × 3 percobaan = 2.82s (282 ms/node)` |

```
16 passed, 1 warning in 20.22s
```

---

## Blocker
Tidak ada. (Push git masih menunggu login GitHub — lihat `docs/PUSH_BLOCKER.md`,
tidak menghalangi pengembangan.)

## Next
Fitur #4 — Sub-Workflow Execution.
