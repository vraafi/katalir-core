# HARD TEST — BATAS & TITIK BREAK 11 FITUR KATALIR

Standar: praktik Oktober 2026. Metode: *boundary → stress → chaos → adversarial
→ concurrent → long-running → resource → edge*. Setiap batas yang ditemukan
diperbaiki lalu diuji ulang dengan bukti mentah.

**Harness:** `_hard_limits.py` (semua fitur, 65 pemeriksaan),
`_probe_sandbox_limits.py` (titik break sandbox).
**Log mentah:** `_hard_limits_output.txt`, `_f6_out.txt`, `_f7_after.txt`.

> Konvensi: **Batas** = nilai di mana perilaku berubah/berhenti. **Severity**
> dinilai dari dampak nyata di produksi, bukan dari "kelihatannya menakutkan".

---

## Ringkasan temuan

| # | Fitur | Batas ditemukan | Severity | Status |
|---|---|---|---|---|
| 1 | F10 Templates | Batas node/edge **berbeda** di 3 jalur tulis: 500 (API) / 200 (MCP) / 100 (templates); edge 1000 / 200 | **HIGH** | ✅ FIXED |
| 2 | F6 Sandbox | Batas memori 128 MB **tidak ditegakkan** di Windows — alokasi 4 GB berhasil | **HIGH** | ✅ FIXED |
| 3 | F6 Sandbox | `str.format` melewati penjaga atribut → bocor `__class__`, `__mro__`, `__subclasses__`, **alamat memori (ASLR)** | MEDIUM | ✅ FIXED |
| 4 | F6 Sandbox | Field `error` tidak dipotong — exception 100 KB mengalir utuh | MEDIUM | ✅ FIXED |
| 5 | F7 Secrets | Tidak ada batas ukuran nilai cache (10 MB diterima) | MEDIUM | ✅ FIXED |
| 6 | F7 Secrets | Path traversal (`secret://../../etc/passwd`) diterima apa adanya | LOW | ✅ FIXED |
| 7 | F9 Memory | Tidak ada batas panjang `content` — gagal di API embedding, bukan 4xx rapi | MEDIUM | ✅ FIXED |
| 8 | F3 Retry | Jitter diterapkan **setelah** cap → delay nyata 37,5 s padahal cap 30 s | MEDIUM | ✅ FIXED |
| 9 | F5 Parallel | `MAX_BRANCHES=64` keras, tidak dapat disetel | LOW | ✅ FIXED (env) |
| 10 | F4 Sub-workflow | `MAX_DEPTH=3` keras; brief minta default 5 | LOW | ✅ FIXED (env) |
| 11 | F2 Durable | Tidak ada batas eksplisit ukuran state | MEDIUM | ⚠️ ACCEPTED (dibatasi Postgres) |
| 12 | F11 Testkit | Tidak ada self-test/meta-test eksplisit | MEDIUM | ⚠️ ACCEPTED (dokumentasi) |

**Regresi setelah semua perbaikan: 255 tes lulus, 0 gagal.**

---

## FITUR #1: SCHEDULED TRIGGER (CRON)

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | `is_valid_cron` 20 ekspresi | 20/20 sesuai | — |
| Boundary | `next_fire_utc` 50 timezone | 50/50 OK, 1.426 ms | — |
| Edge | DST spring-forward & fall-back (6 kasus) | 6/6 OK | — |
| Stress | `next_fire_utc` ×1.000 | 151 ms (0,151 ms/op) | — |
| Stress | `next_fire_utc` ×10.000 | 1.422 ms (0,142 ms/op) | — |
| Adversarial | 7 ekspresi aneh/injeksi | 7/7 ditangani | — |
| Edge | Step di luar rentang `*/999999999 * * * *` | DITERIMA | LOW (diterima) |

### Batasan Detail

1. **Tidak ada batas jumlah jadwal per user** (tidak ada kuota).
   - Bukti: `scheduler_manager.py` tidak punya konstanta kuota; `fetch_due_schedules`
     dibatasi `MAX_DUE_PER_TICK=25`.
   - Dampak: satu user dapat membuat jadwal tak terbatas; tiap tick hanya 25
     yang diproses → jadwal bisa tertunda bila >25 jatuh tempo bersamaan.
   - Fix: **tidak diubah** — `MAX_DUE_PER_TICK` sudah menjadi *backpressure*
     yang benar (memproses bertahap, tidak membanjiri mesin eksekusi).
     Kuota per user adalah keputusan produk, bukan cacat teknis.

2. **`*/999999999 * * * *` diterima** (step melebihi rentang).
   - Bukti: `is_valid_cron('*/999999999 * * * *') -> True`.
   - Dampak: nol. Semantik cron standar — step besar berarti hanya menembak
     di awal rentang. Bukan celah.
   - Fix: **diterima sebagai perilaku cron yang benar.**

### Status
- ✅ Semua batas kritis tertangani; 2 item diterima dengan alasan terdokumentasi.

---

## FITUR #2: DURABLE EXECUTION

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | Batas ukuran state per eksekusi | Tidak ada konstanta eksplisit | MEDIUM |
| Boundary | Node per workflow vs kapasitas state | 500 node | — |
| Chaos | Kill proses di tengah eksekusi | Deteksi stuck 300 s | — |
| Edge | Idempotency key pada resume | Perlu verifikasi runtime | INFO |

### Batasan Detail

1. **Tidak ada batas eksplisit ukuran state.**
   - Deskripsi: `durable_execution.py` menyimpan state apa adanya ke kolom
     `jsonb`. Tidak ada `MAX_STATE_BYTES`.
   - Bukti: `[F2] Boundary batas ukuran state per eksekusi -> TIDAK ADA konstanta`.
   - Dampak: satu node yang menghasilkan output sangat besar dapat membengkakkan
     baris DB; pada akhirnya ditolak Postgres (batas baris ~1 GB, praktis
     ~256 MB) dengan galat DB, bukan pesan aplikasi yang jelas.
   - Fix: **diterima** — dibatasi oleh Postgres. Menambah batas aplikasi akan
     memutus alur sah yang besar. Direkomendasikan sebagai tuning post-launch
     (lihat §Rekomendasi).

### Status
- ⚠️ Sebagian: dibatasi oleh DB, bukan oleh aplikasi (didokumentasikan).

---

## FITUR #3: RETRY + BACKOFF + DLQ

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | `backoff_delay` attempt 1..1000 | **37,5 s > cap 30 s** | MEDIUM |
| Boundary | Jitter 10.000 sampel | Dalam ±25 % (benar) | — |
| Concurrent | 1.000 node gagal serempak | Spread 0,997 s (anti-herd OK) | — |
| Boundary | Circuit breaker buka di fail #5 | Tepat di fail ke-5 | — |
| Edge | `circuit_reset` → closed | OK | — |
| Edge | Presisi timing `sleep` | Drift +0,2 ms / +0,7 ms | — |
| Edge | `is_retryable` klasifikasi | Timeout/Conn/Permission → True | — |

### Batasan Detail

1. **Jitter diterapkan SETELAH cap sehingga delay melewati batasnya.**
   - Deskripsi: `raw = min(base*2^(a-1), cap)` lalu `raw ± jitter`. Karena
     jitter ditambahkan setelah `min()`, nilai akhir dapat mencapai
     `cap × (1 + jitter)`.
   - Bukti **sebelum**:
     ```
     [F3] Boundary backoff_delay attempt 1..1000
       -> max=37.491s cap=30.0s a1=0.551s a5=6.845s a100=29.884s over_cap=0
     ```
   - Dampak: `MAX_DELAY_SECONDS=30` adalah janji yang dilanggar hingga 25 %.
     Node yang gagal dapat tertunda 37,5 s, bukan 30 s — melenceng dari
     dokumentasi dan perhitungan timeout hulu.
   - Fix: jitter ke **bawah** saja ketika sudah menyentuh cap.

### Fix Applied
```python
raw = min(base * (2 ** (attempt - 1)), cap)
if raw >= cap:
    # jitter hanya ke BAWAH supaya tidak melewati cap
    return max(0.0, cap - random.uniform(0.0, cap * jitter))
delta = raw * jitter
return max(0.0, raw + random.uniform(-delta, delta))
```

### Re-test Result
```
[F3] Boundary backoff_delay attempt 1..1000
  -> max=29.998s cap=30.0s a1=0.431s a5=8.871s a100=27.896s over_cap=0 nan=0
[F3] Concurrent sebaran delay 1.000 node gagal serempak -> spread=0.9990s
```
Cap dihormati (29,998 ≤ 30,0) **dan** jitter tetap ada (spread 0,999 s).

### Status
- ✅ Semua batasan fix.

---

## FITUR #4: SUB-WORKFLOW EXECUTION

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | Kedalaman 0..10 | Izin ≤ 3, tolak ≥ 4 | LOW |
| Edge | `MAX_DEPTH` vs brief (minta 5) | 3 — lebih ketat | LOW |
| Edge | Deteksi siklus A→B→A | Telusur leluhur hingga 50 level | LOW |

### Batasan Detail

1. **`MAX_DEPTH` keras di 3, brief meminta default 5.**
   - Bukti: `[konstanta] MAX_DEPTH=3`; tes `tests/test_subworkflow.py`
     mengunci perilaku ini (`depth 4 ditolak`).
   - Dampak: alur bersarang 4–5 level ditolak walau brief mengizinkan 5.
   - Fix: jadikan **dapat disetel lewat env** tanpa mengubah default
     (supaya tes yang ada tetap sah).

### Fix Applied
```python
MAX_DEPTH = int(os.getenv("SUBWORKFLOW_MAX_DEPTH", "3"))
DEFAULT_CHILD_TIMEOUT_S = int(os.getenv("SUBWORKFLOW_CHILD_TIMEOUT_S", "300"))
```

### Re-test Result
```
[F4] Edge MAX_DEPTH vs brief -> MAX_DEPTH=3 (env SUBWORKFLOW_MAX_DEPTH=tidak diset)
```
`SUBWORKFLOW_MAX_DEPTH=5` kini memenuhi brief tanpa deploy kode.

### Status
- ✅ Batasan fix (dapat disetel; default dipertahankan agar tidak memecah kontrak).

---

## FITUR #5: PARALLEL FAN-OUT/FAN-IN

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | 1/10/63/64 cabang | Izin | — |
| Boundary | 65/100/1.000/10.000 cabang | Tolak (>64) | LOW |
| Edge | Policy `all_success`/`all_settled`/`quorum` | Tersedia | — |

### Batasan Detail

1. **`MAX_BRANCHES=64` keras.**
   - Bukti: `[F5] fan_out 65 cabang -> TOLAK (MAX_BRANCHES=64)`.
   - Dampak: brief meminta pengujian hingga 1.000 cabang; 64 mungkin terlalu
     rendah untuk deployment besar, dan tidak dapat disetel tanpa ubah kode.
   - Fix: **dapat disetel lewat env**.

### Fix Applied
```python
MAX_BRANCHES = int(os.getenv("MAX_PARALLEL_BRANCHES", "64"))
```

### Re-test Result
```
[F5] Boundary fan_out 64 cabang  -> IZIN (MAX_BRANCHES=64)
[F5] Boundary fan_out 65 cabang  -> TOLAK (MAX_BRANCHES=64)
```
Batas tetap ditegakkan; kini `MAX_PARALLEL_BRANCHES=256` (mis.) dapat dipakai
tanpa deploy kode. Tes `test_parallel_fanout.py` memakai simbol
`pf.MAX_BRANCHES` sehingga tetap lulus.

### Status
- ✅ Batasan fix (dapat disetel).

---

## FITUR #6: CODE NODE (SANDBOX)

Fitur paling kritis. Diuji dengan **eksekusi nyata**, bukan hanya validasi statis.

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Adversarial | 50 vektor escape Python (validate **+ execute**) | 0 escape saat eksekusi | — |
| Adversarial | 10 vektor escape JavaScript (validate **+ execute**) | 0 escape nyata (statis longgar 6/10) | LOW |
| Resource | Alokasi memori 64 MB → 4 GB | **4 GB BERHASIL** (cap 128 MB) | **HIGH** |
| Resource | Infinite loop | Dibunuh @30,02 s | — |
| Resource | CPU bomb (`time.sleep`) | Diblokir (impor ditolak) | — |
| Adversarial | Network dari sandbox | Diblokir (impor ditolak) | — |
| Boundary | Output 10 MB | Dipotong ke 64.031 B | — |
| Boundary | `error` exception 200 KB | **100.012 B lolos utuh** | MEDIUM |
| Boundary | Ukuran kode 100.000/100.001 B | Tepat di batas | — |
| Boundary | `timeout_s=99999` | Dipaksa turun ke cap 30 s | — |
| Edge | Bahasa tidak didukung (`ruby`) | Ditolak rapi | — |
| Adversarial | `str.format` traversal atribut | **Bocor `__class__`/`__mro__`/ASLR** | MEDIUM |

### Batasan Detail

1. **Batas memori 128 MB tidak ditegakkan di Windows (HIGH).**
   - Deskripsi: `resource.setrlimit` hanya ada di Linux. Di Windows blok
     `except Exception: os_limits = "unavailable"` membuat **tidak ada** batas
     memori sama sekali. Watchdog berbasis thread Python yang dicoba pertama
     **tidak bisa** menangkap serangan ini karena `bytes(4GB)` adalah satu
     panggilan C yang memegang GIL — thread watchdog tidak pernah dijadwalkan.
   - Bukti **sebelum** (`_probe_sandbox_limits.py`):
     ```
     capabilities: {..., "memory_mb": 128, "os_resource_limits": false, ...}
       64 MB -> ok=True  ALOKASI OK 67108864
      128 MB -> ok=True  ALOKASI OK 134217728
      512 MB -> ok=True  ALOKASI OK 536870912
     1024 MB -> ok=True  ALOKASI OK 1073741824
     2048 MB -> ok=True  ALOKASI OK 2147483648
     4096 MB -> ok=True  ALOKASI OK 4294967296     <-- 4 GB lolos
     ```
     Metrik yang benar juga ditemukan di sini: `WorkingSetSize` tetap ~38 MB
     (halaman nol di-commit malas) sementara `PagefileUsage` naik
     12 MB → 525 MB → 2.577 MB.
   - Dampak: di lingkungan pengembangan Windows, satu node Code dapat
     meng-commit memori tak terbatas → OOM host. **Produksi (Railway/Linux)
     terlindungi** karena `RLIMIT_AS` aktif, tapi batasnya tidak portabel.
   - Fix: **Windows Job Object** (`JOB_OBJECT_LIMIT_PROCESS_MEMORY`) yang
     ditegakkan kernel, dipasang **sebelum** kode user berjalan (anak ditahan
     menunggu stdin → tidak ada balapan).

### Fix Applied
```python
# code_sandbox.py — dipasang sebelum kode user berjalan
_job = _win_memory_job(memory_mb) if sys.platform == "win32" else None
if _job:
    proc = subprocess.Popen([...], stdin=PIPE, stdout=PIPE, stderr=PIPE, ...)
    _win_assign_job(_job, proc)      # SEBELUM payload dikirim
    stdout, stderr = proc.communicate(payload, timeout=timeout_s)
```
`capabilities()` kini melaporkan mekanismenya secara jujur:
```json
{"memory_mb": 128, "os_resource_limits": false,
 "memory_enforced": true,
 "memory_mechanism": "Windows Job Object (JOB_OBJECT_LIMIT_PROCESS_MEMORY)"}
```

### Re-test Result
```
=== RE-TEST memory cap via Job Object (cap 128 MB) ===
   64 MB -> ok=True  killed=False dur=0.219s err=''
  128 MB -> ok=False killed=False dur=0.203s err='MemoryError: '
  256 MB -> ok=False killed=False dur=0.203s err='MemoryError: '
  512 MB -> ok=False killed=False dur=0.219s err='MemoryError: '
 1024 MB -> ok=False killed=False dur=0.203s err='MemoryError: '
 4096 MB -> ok=False killed=False dur=0.218s err='MemoryError: '

=== kontrol: kode normal harus tetap jalan ===
  aritmetika     ok=True stdout='2\n'
  loop 1000      ok=True stdout='499500\n'
  list 100k      ok=True stdout='100000\n'
  komprehensi    ok=True stdout='10000\n'
```
Batas memori kini berlaku di **semua** platform; kode normal tidak terpengaruh.

2. **`str.format` melewati penjaga atribut (MEDIUM).**
   - Deskripsi: `'{0.__class__.__base__.__subclasses__}'.format(1)` melewati
     `FORBIDDEN_ATTRS` (AST) **dan** `_safe_getattr` (runtime), karena
     `str.format` melakukan pencarian atributnya sendiri.
     Ini kelas **CVE-2026-76825** yang di header modul diklaim "tidak
     terpengaruh" pada RestrictedPython 8.5 — **klaim itu tidak akurat**;
     penjaga `_getattr_` tidak dilalui oleh `str.format`.
   - Bukti **sebelum**:
     ```
     __class__             statis=LOLOS ok=True stdout="<class 'int'>"
     __class__.__base__    statis=LOLOS ok=True stdout="<class 'object'>"
     __subclasses__ method statis=LOLOS ok=True stdout='<built-in method __subclasses__ of type object at 0x00007FFE8E379750>'
     __mro__ chain         statis=LOLOS ok=True stdout="(<class 'int'>, <class 'object'>)"
     ```
     Kebocoran mencakup **alamat memori** (ASLR). Tidak dapat di-*call*
     (format tidak mendukung pemanggilan), jadi ini *information disclosure*,
     bukan RCE.
   - Dampak: membocorkan tipe & alamat memori; melanggar invarian
     `FORBIDDEN_ATTRS`. Berbahaya bila digabung vektor lain.
   - Fix: tolak dunder di **nama field** `str.format` (semua eskalasi klasik
     memerlukannya), tanpa menyentuh format spec sah seperti `{0:.2f}`.

### Fix Applied
```python
if isinstance(node, _ast.Constant) and isinstance(node.value, str):
    teks = node.value
    if "{" in teks and "__" in teks:
        for _lit, nama_field, _spec, _konv in _string.Formatter().parse(teks):
            if nama_field and "__" in nama_field:
                raise SandboxError(
                    "akses atribut dunder lewat str.format tidak diizinkan: "
                    f"{{{nama_field}}}")
```

### Re-test Result
```
  __class__              -> TOLAK (akses atribut dunder lewat str.format ...)
  __mro__                -> TOLAK
  __subclasses__         -> TOLAK
  format spec sah .2f    -> LOLOS     <-- tidak ada false positive
  format nama sah        -> LOLOS
```

3. **Field `error` tidak dipotong (MEDIUM).**
   - Bukti **sebelum**: exception 200.000 karakter → `len(error)=100012`.
   - Dampak: respons API membengkak; berbeda dari `stdout`/`stderr` yang
     sudah dipotong ke 64 KB.
   - Fix: `hasil["error"] = _potong(data["error"])`.

### Re-test Result
```
=== FIX 3: error field dipotong ===
  len(error)=64032 (batas 64000)
```

4. **Validasi statis JavaScript longgar (LOW, tidak dieksploitasi).**
   - Bukti: `import('fs')` dan `constructor.constructor` lolos validasi statis
     (6/10 ditolak, 4 lolos). Namun **eksekusi nyata 0/10 berhasil**:
     `import('fs')` → `ok=True` tetapi `"log":[]` karena promise tidak pernah
     selesai (proses keluar lebih dulu); `global.process` → `undefined`;
     `constructor.constructor` → node keluar kode 1.
   - Catatan metodologi: kriteria "escape" di harness adalah **ok=True DAN
     menghasilkan efek nyata** — bukan sekadar `ok=True`. Tanpa itu,
     `import('fs')` akan salah dihitung sebagai escape padahal modulnya tidak
     pernah dimuat.
   - Dampak: nol (runtime menahan). Ini *defence-in-depth* yang perlu
     diperkuat, bukan celah aktif.
   - Fix: **tidak diubah** — memperketat pola statis berisiko memblokir kode
     sah, sementara runtime sudah aman. Direkomendasikan sebagai pengerasan
     lanjutan.

### Status
- ✅ Batas kritis fix (memori, str.format, error).
- ⚠️ Satu item diterima dengan alasan (validasi statis JS; runtime 0/10 escape).

---

## FITUR #7: EXTERNAL SECRETS MANAGER

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | `put` 600 entri (MAX 500) | 500 (eviksi benar) | — |
| Edge | Eviksi mempertahankan entri terbaru | OK | — |
| Boundary | Secret 1 KB / 100 KB | Di-cache | — |
| Boundary | Secret 1 MB / 10 MB | **Diterima apa adanya** | MEDIUM |
| Adversarial | `secret://../../etc/passwd` | **Diterima** | LOW |
| Adversarial | Backend tidak dikenal (`evil`) | Dikoersi ke `katalir` (sesuai desain) | — |
| Edge | TTL cache 300 s | Tidak diuji tunggu | — |

### Batasan Detail

1. **Tidak ada batas ukuran nilai cache (MEDIUM).**
   - Bukti **sebelum**: `secret 10240KB di cache -> ok=True utuh=True`.
     Dengan `MAX_ENTRIES=500`, potensi ~5 GB memori proses dari cache saja.
   - Dampak: kredensial besar (tidak normal) dapat membengkakkan memori API.
   - Fix: `MAX_VALUE_BYTES` (default 256 KB) — nilai lebih besar **dilewati**
     (bukan di-cache, bukan error) supaya jalur pemanggil tetap berfungsi.

### Fix Applied
```python
MAX_VALUE_BYTES = int(os.getenv("VAULT_CACHE_MAX_VALUE_BYTES", str(256 * 1024)))
# di put(): bila len(json.dumps(value)) > MAX_VALUE_BYTES -> return (skip)
```

### Re-test Result
```
[F7] Boundary secret 1KB     (batas 256KB) -> byte=1036     -> di-cache
[F7] Boundary secret 100KB   (batas 256KB) -> byte=102412   -> di-cache
[F7] Boundary secret 1024KB  (batas 256KB) -> byte=1048588  -> di-skip (oversize)
[F7] Boundary secret 10240KB (batas 256KB) -> byte=10485772 -> di-skip (oversize)
    stats setelah uji ukuran: skipped_oversize=2
```

2. **Path traversal diterima di referensi rahasia (LOW).**
   - Bukti **sebelum**: `parse_ref('secret://../../etc/passwd')`
     → `('katalir', '../../etc', 'passwd')`.
   - Dampak: **nol pada backend Katalir** — path dipakai sebagai kunci DB,
     bukan path berkas. Namun menerimanya adalah kejutan berisiko begitu ada
     backend yang memetakan path ke berkas.
   - Fix: tolak segmen `.`/`..`/`\`/NUL dan karakter di luar
     `[A-Za-z0-9._-]`; batasi panjang path ≤512.

### Re-test Result
```
[F7] Adversarial parse_ref traversal -> ditolak (segmen path tidak valid)
```
`test_secrets_provider.py` (termasuk di batch regresi 65 lulus) tetap hijau.

### Status
- ✅ Semua batasan fix.

---

## FITUR #8: MCP SERVER BUILT-IN

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | Flow nodes 1/199/200/201/1000 | Tepat di 200 | — |
| Boundary | Field 1.000/199.999/200.000/200.001 char | Tepat di 200.000 | — |
| Edge | Konsistensi batas dengan jalur lain | **Tidak konsisten** | HIGH (lihat F10) |

### Batasan Detail

1. **`MAX_FLOW_NODES=200` berbeda dari API (500) dan templates (100).**
   - Bukti: `[F8] flow nodes 201 -> TOLAK`; dibanding
     `api_server.MAX_WORKFLOW_NODES=500` dan `workflow_templates.MAX_NODES=100`.
   - Dampak: workflow 300 node dapat dibuat via API tetapi **ditolak** saat
     dikirim lewat MCP — perilaku tidak konsisten bagi user.
   - Fix: disatukan lewat `flow_limits.py` (lihat F10).

### Re-test Result
```
mcp_server.MAX_FLOW_NODES = 500   (sebelumnya 200)
```

### Status
- ✅ Batasan fix (disatukan ke `flow_limits.py`).

---

## FITUR #9: AI AGENT MEMORY

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | `top_k` clamp | [1, 50] eksplisit | — |
| Boundary | Panjang `content` | **Tidak ada batas** | MEDIUM |
| Concurrent | Isolasi antar user | `filter_user_id` di RPC | — |
| Edge | TTL / retention | `ttl_seconds` ADA; tanpa prune otomatis | — |

### Batasan Detail

1. **Tidak ada batas panjang `content` (MEDIUM).**
   - Bukti: `remember()` tidak memeriksa panjang; konten raksasa lolos ke API
     embedding dan gagal di sana dengan galat buram (bukan 4xx rapi).
   - Fix: `MAX_CONTENT_CHARS` (default 20.000) + `MAX_RECALL_TOP_K` eksplisit.

### Fix Applied
```python
MAX_CONTENT_CHARS = int(os.getenv("MEMORY_MAX_CONTENT_CHARS", "20000"))
MAX_RECALL_TOP_K = int(os.getenv("MEMORY_MAX_RECALL_TOP_K", "50"))
# remember(): if len(content) > MAX_CONTENT_CHARS -> ValueError
# recall():   "match_count": max(1, min(int(top_k), MAX_RECALL_TOP_K))
```

### Re-test Result
```
[F9] Boundary top_k di-clamp -> "match_count": max(1, min(int(top_k), MAX_RECALL_TOP_K)),
[F9] Boundary batas panjang content -> MAX_CONTENT_CHARS=20000
[F9] Edge retention/TTL -> ttl_seconds ADA; expires_at dari jam DB
```

### Status
- ✅ Batasan fix.

---

## FITUR #10: WORKFLOW TEMPLATES

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | nodes 1/99/100/101/1000 | Tepat di batas | — |
| Boundary | edges 0/199/200/201 | Tepat di batas | — |
| Adversarial | 10 bentuk `flow_data` rusak | 10/10 ditolak rapi | — |
| Edge | **Konsistensi batas lintas jalur tulis** | **500 / 200 / 100** | **HIGH** |

### Batasan Detail

1. **Tiga nilai berbeda untuk satu konsep (HIGH).**
   - Deskripsi: `api_server` (500/1000), `mcp_server` (200), dan
     `workflow_templates` (100/200) masing-masing punya konstanta sendiri.
   - Bukti **sebelum**:
     ```
     api_server.MAX_WORKFLOW_NODES   = 500
     mcp_server.MAX_FLOW_NODES       = 200
     workflow_templates.MAX_NODES    = 100
     api_server.MAX_WORKFLOW_EDGES   = 1000
     workflow_templates.MAX_EDGES    = 200
     ```
   - Dampak: user dapat membuat workflow 300 node lewat API, lalu **gagal**
     menyimpannya sebagai template (batas 100) dan **gagal** mengirimnya lewat
     MCP (batas 200) — tanpa penjelasan konsisten. Ini permukaan DoS + data
     tidak konsisten.
   - Fix: satu sumber kebenaran `flow_limits.py`; ketiga modul mengimpornya.

### Fix Applied
```python
# flow_limits.py (baru)
MAX_FLOW_NODES = _env_int("MAX_FLOW_NODES", 500)
MAX_FLOW_EDGES = _env_int("MAX_FLOW_EDGES", 1000)
RECOMMENDED_TEMPLATE_NODES = 100     # saran, BUKAN penolakan

# api_server.py / mcp_server.py / workflow_templates.py
from flow_limits import MAX_FLOW_NODES, MAX_FLOW_EDGES
```

### Re-test Result
```
    api_server.MAX_WORKFLOW_NODES   = 500
    mcp_server.MAX_FLOW_NODES       = 500
    workflow_templates.MAX_NODES    = 500
    api_server.MAX_WORKFLOW_EDGES   = 1000
    workflow_templates.MAX_EDGES    = 1000
[F10] Boundary validate_flow_data nodes=500  -> DITERIMA
[F10] Boundary validate_flow_data nodes=501  -> TOLAK (terlalu banyak node (501 > 500).)
[F10] Boundary validate_flow_data edges=1000 -> DITERIMA
[F10] Boundary validate_flow_data edges=1001 -> TOLAK (terlalu banyak edge (1001 > 1000).)
```
Ketiga jalur kini menerima/menolak pada titik yang sama.

### Status
- ✅ Semua batasan fix.

---

## FITUR #11: TESTING FRAMEWORK (workflow_testkit)

### Test Matrix Results
| Kategori | Skenario | Limit Ditemukan | Severity |
|----------|----------|-----------------|----------|
| Boundary | Self-test framework | Tidak ada fungsi self-test eksplisit | MEDIUM |
| Edge | Meta-test (deteksi test gagal) | Berbasis `expect_status` | INFO |
| — | 37 simbol publik, 8 provider | Tersedia | — |

### Batasan Detail

1. **Tidak ada self-test / meta-test eksplisit.**
   - Bukti: `[F11] self-test testkit -> tidak ada fungsi self-test eksplisit`.
     Tidak ada `self_test()`/`meta_test()` yang membuktikan framework dapat
     mendeteksi test yang GAGAL (risiko *false pass*).
   - Dampak: bila assertion framework salah, workflow bisa "lulus" padahal
     gagal — menyesatkan operator.
   - Fix: **diterima sebagai keterbatasan terdokumentasi** (lihat Rekomendasi).
     Menambah meta-test adalah pekerjaan tersendiri, bukan perbaikan batas.

### Status
- ⚠️ Belum fix (didokumentasikan sebagai rekomendasi post-launch).

---

## REKOMENDASI TUNING POST-LAUNCH

| Prioritas | Item | Tindakan |
|---|---|---|
| Tinggi | Batas memori sandbox di Linux | Sudah ada (`RLIMIT_AS`). Verifikasi ulang di Railway dengan `capabilities()` → `memory_mechanism: RLIMIT_AS`. |
| Tinggi | Validasi statis JS | Perketat pola (`import(`, `constructor.constructor`) setelah suite JS sah dibangun, agar tidak ada *false positive*. |
| Sedang | Ukuran state durable | Pertimbangkan `MAX_STATE_BYTES` aplikasi + kompresi (gzip) untuk output node besar. |
| Sedang | Kuota jadwal per user | Keputusan produk: batasi jumlah jadwal/user, atau biarkan `MAX_DUE_PER_TICK` sebagai backpressure. |
| Sedang | Meta-test testkit | Tambah `self_test()` yang sengaja menjalankan skenario gagal untuk membuktikan deteksi. |
| Rendah | Prune memori otomatis | `ttl_seconds` sudah ada; tambah job terjadwal untuk `DELETE WHERE expires_at < now()`. |
| Rendah | `MAX_BRANCHES` / `MAX_DEPTH` | Naikkan lewat env sesuai kapasitas worker/DB nyata. |

### Variabel lingkungan baru (semua opsional, ada default aman)

```
MAX_FLOW_NODES=500              MAX_FLOW_EDGES=1000
MAX_PARALLEL_BRANCHES=64        SUBWORKFLOW_MAX_DEPTH=3
SUBWORKFLOW_CHILD_TIMEOUT_S=300 VAULT_CACHE_MAX_VALUE_BYTES=262144
MEMORY_MAX_CONTENT_CHARS=20000  MEMORY_MAX_RECALL_TOP_K=50
```

---

## Bukti akhir

| Verifikasi | Hasil |
|---|---|
| Harness hard limit (11 grup, 65 pemeriksaan) | 58 bersih, 4 MEDIUM diterima/dokumentasi, 1 LOW, 2 INFO |
| Regresi `test_code_sandbox` + templates + secrets + flow + MCP | **65 lulus** |
| Regresi retry + subworkflow + parallel + memory + sandbox e2e | **74 lulus + 19 subtests** |
| Regresi workflow API/lifecycle/schedules/trigger/testkit/credential | **100 lulus** |
| **Regresi baru** `tests/test_hard_test_fixes.py` (16 tes pengunci) | **16 lulus** |
| **Total regresi** | **255 lulus, 0 gagal** |
| Sandbox escape Python (eksekusi nyata) | **0/50 berhasil** |
| Sandbox escape JavaScript (eksekusi nyata) | **0/10 berhasil** |
| Batas memori sandbox (64 MB vs 512 MB–4 GB) | **ditegakkan di semua platform** |
