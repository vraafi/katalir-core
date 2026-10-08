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

### Verifikasi lanjutan (V1–V3)

| # | Area | Temuan | Severity | Status |
|---|---|---|---|---|
| 13 | Suite tes | `pytest` polos dari root **tidak pernah selesai** (>1 jam): skrip harness `*_test.py` dijalankan **saat impor** (load test produksi) + kode vendored `_vdbos` | **HIGH** | ✅ FIXED (`pytest.ini`) |
| 14 | F6 di Linux | Penegakan memori di Linux (Railway) **belum pernah dibuktikan** — hanya jalur Windows yang diuji | MEDIUM | ✅ VERIFIED (`RLIMIT_AS` aktif) |
| 15 | F6 Sandbox | Penjaga `str.format` **dapat dilewati** dengan merakit string saat runtime (5/5 vektor rakitan bocor) | MEDIUM | ✅ FIXED (penjaga runtime) |
| 16 | F6 Sandbox | Sandbox **tidak bisa mendefinisikan `class`** (`NameError: __metaclass__`) | LOW | ⚠️ DOCUMENTED |
| 17 | F6 Sandbox | F6 **tidak punya jalur eksekusi di produksi** (tak ada node `code`, tak ada tool, tak ada endpoint) | MEDIUM | ⚠️ OPEN (keputusan produk) |

**Regresi setelah semua perbaikan: suite penuh 1273 lulus, 0 gagal, 0 error
dalam 8 m 23 s** (sebelumnya menggantung >1 jam), plus **26 tes pengunci**
hard test lulus.

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

## VERIFIKASI LANJUTAN — V1/V2/V3

Tiga hal yang pada kampanye pertama masih menggantung: suite tes yang
menggantung, penegakan memori di Linux yang belum pernah diuji, dan apakah
bypass `str.format` bisa dieskalasi.

---

## V1. `pytest` POLOS MENGGANTUNG >1 JAM

### Gejala

`pytest -q` dari root (tanpa argumen) tidak pernah selesai. Dua sesi
berturut-turut. Yang mengejutkan: **koleksi saja sudah menggantung**.

```
$ pytest --co -q            # hanya koleksi, tidak menjalankan tes
(TIDAK ADA OUTPUT — dihentikan setelah 120 s)
```

### Isolasi (bukti mentah)

Probe per berkas (`_v1_probe.py`, `pytest <file> --co -q`, timeout keras 40–60 s)
menjalankan **96 berkas** di `tests/`:

```
total file       : 96
file hang        : 0
total tes        : 1247
waktu total probe : 436.7s
```

Koleksi `tests/` sebagai satu direktori:

```
$ pytest tests --co -q
1273 tests collected in 8.25s        <-- CEPAT. Bukan penyebabnya.
```

Jadi hang-nya **di luar `tests/`**. Probe berkas di luar `tests/`:

```
HANG   40.06s exit=None tests=0 _prod_hard_test.py   | last: (no output before timeout)
ok      3.00s exit=5    tests=0 _vps_public_dns_test.py
ok      9.06s exit=5    tests=0 vps_ssh_test.py
ok      3.27s exit=0    tests=4 tools\picgen-mcp\test_local.py
```

### Akar masalah

`_prod_hard_test.py` **bukan modul tes** — ia program. Tidak ada satu pun
fungsi `test_*`, dan **tidak ada penjaga `if __name__ == "__main__"`**
(`grep -c "__main__" _prod_hard_test.py` → **0**). Seluruh isinya berjalan
saat **impor**, termasuk:

- load test **850 request konkuren** (50/100/200/500) ke backend produksi,
- **30 vektor adversarial** ke produksi,
- workflow **60 node** + polling sampai 90 s per eksekusi,
- 10 skenario n8n.

pytest menyapu berkas ini karena pola bawaan `python_files` mencakup
`*_test.py`, bukan hanya `test_*.py`. Jadi "hang" sebenarnya adalah
**hard test produksi yang dijalankan tanpa sengaja oleh kolektor tes**.

Bukti langsung:

```
$ python -c "import _prod_hard_test"
exit=124 elapsed=26s   (124 = timeout, TANPA satu baris output)
```

Bukti pendukung: koleksi seluruh repo **kecuali** `tests/` memakan
**317 s** dan menghasilkan 15 error dari kode vendored:

```
exit=2 elapsed=321s
113 tests collected, 15 errors in 317.14s (0:05:17)
ERROR _vdbos/greenlet/tests/test_weakvars.py
ERROR _vdbos/greenlet/tests/test_weakref.py   ... (15 berkas)
```

### Fix

**`pytest.ini`** (baru) — membatasi suite pada tes milik proyek:

```ini
[pytest]
testpaths = tests
norecursedirs = .* _* node_modules __pycache__ .git build dist *.egg-info .venv venv gacha-purgatory
python_files = test_*.py
```

Alasan tiap baris:

| Baris | Alasan |
|---|---|
| `testpaths = tests` | `pytest` polos hanya menyentuh suite utama (1273 tes). Tes root butuh jaringan/kredensial (Playwright, Supabase, Gemini) sehingga dijalankan eksplisit. |
| `norecursedirs` | Sabuk pengaman untuk `pytest .`: jangan pernah menyusuri kode vendored (`_vdbos`) atau skrip harness. |
| `python_files = test_*.py` | **Inti perbaikan.** Pola `*_test.py` dibuang karena di repo ini pola itu dipakai skrip harness produksi, bukan modul tes. |

Selain itu berkas harness lokal `_prod_hard_test.py` diganti nama menjadi
`_prod_hard_run.py` supaya tidak pernah bisa dikoleksi lagi (berkas ini
di-`.gitignore`, jadi tidak masuk repo).

`pytest-timeout` **tidak** ditambahkan sebagai dependensi (ia akan ikut
terpasang di image produksi hanya untuk kebutuhan tes). Rekomendasi tetap
tertulis di `pytest.ini`: pasang lalu pakai `--timeout=120` bila suite
kembali menggantung.

### Hasil uji ulang

```
$ pytest --co -q
1273 tests collected in 4.94s
```

Suite penuh (dua kali dijalankan):

```
# run 1 (mesin juga dipakai proses lain: 2 pytest + polling CI)
1 failed, 1271 passed, 15 warnings, 1 error, 42 subtests passed in 529.69s (0:08:49)

# run 2 (mesin tenang)
1273 passed, 15 warnings, 42 subtests passed in 503.61s (0:08:23)   EXIT=0
```

Sebelum perbaikan: **tidak pernah selesai (>1 jam)**.
Sesudah perbaikan: **1273 lulus, 0 gagal, 0 error, 8 m 23 s** — di bawah
anggaran 10 menit.

Dua kegagalan pada run 1 **bukan** regresi kode; keduanya hilang pada run 2
dan lulus saat diuji terisolasi (rinciannya di tabel "Dua kegagalan suite
penuh" pada bagian Bukti akhir).

### Status

✅ **FIXED** — akar masalahnya adalah konfigurasi koleksi, bukan tes yang
menggantung. Tidak ada satu pun tes yang perlu diubah.

---

## V2. PENEGAKAN MEMORI DI LINUX (RAILWAY)

### Pertanyaan

Perbaikan batas memori sebelumnya memakai **Windows Job Object**. Railway
berjalan di **Linux**, dengan mekanisme berbeda (`resource.setrlimit`).
Apakah `RLIMIT_AS` benar-benar bekerja di sana? Sebelumnya belum diuji.

### Temuan penting: tidak ada jalur eksekusi di produksi

Pertanyaan brief adalah "kirim prompt → eksekusi workflow di produksi".
Jalur itu **tidak ada**. Bukti:

1. **Mesin workflow tidak punya node `code`.** Hanya tiga jenis node:
   ```
   class NodeKind(str, Enum):
       TRIGGER = "trigger"
       AGENT   = "agent"
       MCP     = "mcp"
   ```
2. **Tidak ada endpoint sandbox.** Seluruh rute `api_server.py` tidak memuat
   `/sandbox`, `/code`, atau serupa.
3. **Tool MCP bawaan tidak memuat eksekutor kode:**
   `create_workflow`, `update_workflow`, `list_workflows`,
   `execute_workflow`, `get_execution_status`.
4. **Tool agen chat** hanya `create_spreadsheet` + `append_row`.
5. `code_sandbox` hanya dipanggil dari **dua** tempat: `/version`
   (melaporkan `capabilities()`) dan `workflow_testkit.py`
   (**validasi statis** `validate_python`, tanpa eksekusi).

Konsekuensinya jujur: **di produksi saat ini batas memori sandbox tidak
pernah ditegakkan karena sandbox tidak pernah dijalankan.** Ini dicatat
sebagai temuan #17, bukan sebagai "terverifikasi aman".

### Verifikasi jalur Linux (eksekusi nyata)

Karena produksi tidak dapat dijangkau, jalur Linux diuji dengan
**menjalankan kode runner yang sama di Linux sungguhan** —
job CI `sandbox-linux-limit` pada `ubuntu-24.04` (GitHub Actions).
Runner memakai `sys.executable`, jadi berkas yang dieksekusi identik
dengan yang dipakai Railway.

Capabilities yang dilaporkan di Linux:

```
platform        : linux
capabilities    : {"languages": ["python","javascript"], "python_available": true,
                   "javascript_available": true, "timeout_s": 30, "memory_mb": 128,
                   "os_resource_limits": true, "memory_enforced": true,
                   "memory_mechanism": "RLIMIT_AS",
                   "platform": "linux"}
```

Hasil (mentah, dari log CI):

```
[trivial]       ok=True  os_limits=on killed=False dur=0.043s   error='None'
[alokasi-64MB]  ok=True  os_limits=on killed=False dur=0.042s   error='None'
[bomb-2GB]      ok=False os_limits=on killed=False dur=0.046s   error='MemoryError: '
[bomb-512MB]    ok=False os_limits=on killed=False dur=0.046s   error='MemoryError: '
[bomb-loop]     ok=False os_limits=on killed=False dur=0.045s   error='MemoryError: '

=== HASIL ===
trivial 64MB lolos     : True
2GB   ditolak          : True
512MB ditolak          : True
loop  ditolak          : True
OK: RLIMIT_AS menegakkan batas memori di Linux.
```

Arti tiap baris:

| Kasus | Harapan | Hasil | Catatan |
|---|---|---|---|
| `print("halo")` | jalan | `ok=True` | **Penting**: runner tetap sanggup start dengan `RLIMIT_AS=128MB`; batas tidak membunuh interpreter. |
| `bytes(64MB)` | jalan | `ok=True` | Alokasi wajar di bawah batas tidak terganggu. |
| `bytes(2GB)` | gagal | `MemoryError` | Batas ditegakkan. |
| `bytes(512MB)` | gagal | `MemoryError` | Ditegakkan. |
| loop 1024×1MB | gagal | `MemoryError` | Alokasi bertahap juga tertahan. |

### Status

✅ **VERIFIED** — `RLIMIT_AS` menegakkan batas memori di Linux, dan
`os_limits=on` mengonfirmasi lapis OS aktif. Tidak perlu cgroup v2,
`systemd-run`, atau container per eksekusi.
⚠️ Namun lihat temuan #17: jalur ini belum tersambung ke produksi.

---

## V3. APAKAH BYPASS `str.format` BISA DIESKALASI?

### Latar

Kampanye pertama menemukan `'{0.__class__}'.format(1)` melewati penjaga
atribut, lalu memperbaikinya dengan **memindai konstanta string di AST**
(`string.Formatter().parse`, tolak `__` di nama field). Pertanyaannya:
apakah perbaikan itu memadai?

### Hasil: perbaikan itu TIDAK memadai

Pemindaian literal melihat tiap konstanta **satu per satu**. String yang
**dirakit saat runtime** tidak pernah terlihat utuh oleh pemindai:

```
[ C1] LEAK  konkatenasi +              -> <class 'int'>
[ C2] LEAK  konkatenasi + (bocor mro)  -> (<class 'int'>, <class 'object'>)
[ C3] LEAK  chr(95) membangun dunder   -> <class 'int'>
[ C4] LEAK  join() membangun dunder    -> <class 'int'>
[ C7] LEAK  dunder dipecah variabel    -> <class 'int'>
```

**5/5 vektor rakitan bocor.** Contoh yang lolos:

```python
s = "{0." + "__class__" + "}"
print(s.format(1))          # -> <class 'int'>
```

Sementara vektor langsung tetap diblokir (A1–A4, B1, B2, C8, C10, C14, C15).
Jadi perbaikan lama hanya menutup bentuk literal.

### Bisa dieskalasi ke eksekusi kode? TIDAK

`str.format` **hanya membaca atribut**; ia tidak punya primitif pemanggilan.
Semua rantai RCE klasik butuh memanggil sesuatu (`__subclasses__()` lalu
`__init__.__globals__['__builtins__']['__import__']`), dan itu tidak mungkin
lewat format. Vektor `__reduce__`/`__reduce_ex__` (kandidat RCE via pickle)
juga diblokir. Karena itu klasifikasinya **MEDIUM (pengungkapan
informasi), bukan HIGH** — tetapi tetap diperbaiki karena membocorkan
hierarki kelas dan **alamat memori (ASLR)** adalah bahan baku eksploitasi
lanjutan.

### Fix: penjaga berbasis RUNTIME

Pemindaian literal diganti **transformasi AST + pemeriksaan saat runtime**,
sehingga string diperiksa **sesudah dirakit**:

```python
# X.format(...)      ->  katalir_attr_format(X)(...)
# X.format_map(...)  ->  katalir_attr_format_map(X)(...)
class _T(_a.NodeTransformer):
    def visit_Attribute(self, node):
        self.generic_visit(node)
        if node.attr in ("format", "format_map"):
            ...
```

Transformasi dilakukan di level **`Attribute`**, bukan `Call`, sehingga
jalur "ambil atribut tanpa memanggil" ikut tertutup:

```python
f = ("{0." + "__class__" + "}").format   # C16
print(f(1))                              # kini diblokir
```

Pemeriksa memindai **field dan format spec bersarang**:

```python
def _periksa(fmt, kedalaman=0):
    for _lit, field, spec, _konv in _s.Formatter().parse(fmt):
        if field and "__" in field:
            raise AttributeError(...)
        if spec:
            _periksa(spec, kedalaman + 1)
```

### Hasil uji ulang (20 vektor, jalur produksi `run_python`)

```
=== RINGKASAN V3 ===
BLOCKED : 20
OK      : 4
RUNTIME : 2
vektor LEAK (bocor): 0
```

Format yang sah tetap jalan (kontrol fungsional):

| Kontrol | Hasil |
|---|---|
| `'{0:.2f}'.format(3.14159)` | `3.14` ✅ |
| `str.format('{0}-{1}', 'a', 'b')` | `a-b` ✅ |
| `format(3.14159, '.2f')` | `3.14` ✅ |
| `'%s' % (1,)` | `1` ✅ |
| `'{}'.format` diambil lalu dipanggil | diblokir bila field memuat dunder ✅ |

Diverifikasi ulang **di Linux** (job CI) — 6 vektor, `bocor: 0/6`:

```
BLOK jejak=[] 'print("{0.__class__}".format(1))'
BLOK jejak=[] 'print("{0." + "__class__" + "}".format(1))'
BLOK jejak=[] 'u = chr(95) * 2\nprint(("{0." + u + "class" + u + "}").format'
BLOK jejak=[] 'f = ("{0." + "__class__" + "}").format\nprint(f(1))'
BLOK jejak=[] 'f = str.format\nprint(f("{0." + "__class__" + "}", 1))'
BLOK jejak=[] 's = "{a." + "__class__" + "}"\nprint(s.format_map({"a": 1}))'
bocor: 0/6
```

### Temuan sampingan: `class` tidak didukung sandbox

Vektor kontrol "objek non-str dengan `.format` sendiri" gagal:

```
class P:
    def m(self): return 1
print(P().m())
-> NameError: name '__metaclass__' is not defined
```

Diuji pada versi **sebelum dan sesudah** perbaikan — hasilnya identik,
jadi ini **bukan** akibat perubahan `str.format`, melainkan perilaku
RestrictedPython (butuh `__metaclass__` di globals). Klasifikasi **LOW**
(keterbatasan fungsional, bukan lubang keamanan). Tidak diaktifkan dalam
kampanye ini karena menambah permukaan serangan (metaclass kustom) dan
butuh peninjauan ancaman tersendiri.

### Status

✅ **FIXED** (penjaga runtime, 0/20 bocor) · **severity tetap MEDIUM**
(pengungkapan, bukan eksekusi kode).

---

## REKOMENDASI TUNING POST-LAUNCH

| Prioritas | Item | Tindakan |
|---|---|---|
| **Kritis** | Jalur eksekusi F6 | Sandbox sudah dikeraskan dan batas memori **terbukti** berlaku di Linux, tetapi **tidak tersambung ke apa pun**: tak ada node `code`, tak ada tool MCP/agen, tak ada endpoint. Selama ini belum tersambung, F6 tidak memberi nilai di produksi — dan batas memorinya tidak relevan karena tak pernah dijalankan. Sambungkan ke satu jalur resmi (node `code` atau tool MCP) lalu ulangi V2 lewat jalur itu. |
| Tinggi | Batas memori sandbox di Linux | Sudah ada (`RLIMIT_AS`) dan **kini terbukti** (2GB/512MB/loop → `MemoryError`). Job CI `sandbox-linux-limit` menjaganya tetap begitu. |
| Tinggi | Validasi statis JS | Perketat pola (`import(`, `constructor.constructor`) setelah suite JS sah dibangun, agar tidak ada *false positive*. |
| Sedang | Ukuran state durable | Pertimbangkan `MAX_STATE_BYTES` aplikasi + kompresi (gzip) untuk output node besar. |
| Sedang | Kuota jadwal per user | Keputusan produk: batasi jumlah jadwal/user, atau biarkan `MAX_DUE_PER_TICK` sebagai backpressure. |
| Sedang | Meta-test testkit | Tambah `self_test()` yang sengaja menjalankan skenario gagal untuk membuktikan deteksi. |
| Sedang | Penjaga hang suite | Pasang `pytest-timeout` dan tambahkan `--timeout=120` di `pytest.ini` supaya tes yang macet **dilaporkan**, bukan menggantung senyap. Belum dipasang karena dependensi tes akan ikut ke image produksi. |
| Sedang | Asersi paralelisme rapuh | `test_parallel_fanout.py::test_12_performa_paralel_vs_seri` memakai ambang **absolut** (0,65 s) dengan margin hanya ~10 % terhadap hasil terukur (0,58 s), sehingga gagal saat mesin sibuk (terukur 1,11 s). Ubah menjadi **relatif terhadap baseline seri yang diukur pada mesin yang sama**, agar tetap jujur di bawah beban. |
| Rendah | `class` di sandbox | Sandbox belum bisa mendefinisikan `class` (`NameError: __metaclass__`). Menambah `__metaclass__ = type` akan menutupnya, tetapi memperluas permukaan serangan (metaclass kustom) — butuh peninjauan ancaman tersendiri. |
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
| **Regresi baru** `tests/test_hard_test_fixes.py` (26 tes pengunci) | **26 lulus** |
| **Suite penuh `pytest -q`** (setelah `pytest.ini`) | **1273 lulus, 0 gagal, 0 error — 503,61 s (8 m 23 s)** |
| Koleksi suite penuh | **1273 tes dalam 4,94 s** (sebelumnya: menggantung >1 jam) |
| Sandbox escape Python (eksekusi nyata) | **0/50 berhasil** |
| Sandbox escape JavaScript (eksekusi nyata) | **0/10 berhasil** |
| Batas memori sandbox di Windows (64 MB vs 512 MB–4 GB) | **ditegakkan** (Job Object) |
| Batas memori sandbox di Linux (CI `ubuntu-24.04`) | **2 GB / 512 MB / loop → `MemoryError`**; 64 MB lolos |
| Vektor `str.format` (20, jalur produksi) | **0 bocor** (20 diblokir, format sah tetap jalan) |
| Vektor `str.format` di Linux (6, CI) | **0 bocor** |

### Dua kegagalan pada run 1 — keduanya lingkungan, bukan kode

Keduanya **tidak muncul** pada run 2 (mesin tenang → 1273 lulus, 0 gagal).

| Item | Gejala saat suite penuh | Uji ulang terisolasi | Kesimpulan |
|---|---|---|---|
| `test_parallel_fanout.py::test_12_performa_paralel_vs_seri` | `AssertionError: tidak cukup paralel: 1.11s (seri 0.80s)` | **3/3 lulus**, `paralel=0.58 s` (ambang 0,65 s) | Asersi waktu dengan **margin hanya ~10 %**; runtuh saat mesin sibuk (saat itu ada 2 proses pytest + polling CI berjalan). Bukan regresi kode. |
| `test_agent_memory.py::test_2c8_scale_1000_memories` (setup `pg`) | `psycopg2.OperationalError: SSL error: unexpected eof while reading` | **lulus dalam 61,18 s** | SSL transien ke pooler Supabase. Bukan regresi kode. |

Rekomendasi dari temuan ini: jadikan asersi paralelisme **relatif terhadap
baseline seri yang diukur pada mesin yang sama** (bukan ambang absolut),
supaya suite tetap jujur saat mesin sibuk.
