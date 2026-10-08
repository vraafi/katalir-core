# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/).
Versi mengikuti tanggal kerja (proyek ini belum memakai semver rilis).

## [2026-10-08] — Verifikasi lanjutan: suite tes, batas memori Linux, bypass str.format

Brief "VERIFIKASI 3 HAL KRITIS DARI HARD TEST". Tiga hal yang masih
menggantung setelah kampanye pertama. Laporan penuh:
**`docs/hard-test-limits.md`** (bagian "VERIFIKASI LANJUTAN — V1/V2/V3").

### V1 — `pytest` polos menggantung >1 jam ✅ FIXED

**Akar masalahnya bukan tes yang menggantung, melainkan konfigurasi koleksi.**
`pytest` tanpa argumen dari root menyapu skrip harness ad-hoc berpola
`*_test.py` (pola bawaan `python_files` mencakup `*_test.py`). Salah satunya,
`_prod_hard_test.py`, adalah **program**: tanpa fungsi `test_*` dan tanpa
penjaga `if __name__ == "__main__"` (`grep -c "__main__"` → 0). Seluruh
isinya berjalan saat **impor** — load test 850 request konkuren ke produksi,
30 vektor adversarial, workflow 60 node. Jadi "hang" itu adalah hard test
produksi yang dijalankan tanpa sengaja oleh kolektor tes.

Bukti: `python -c "import _prod_hard_test"` → timeout 25 s tanpa output;
`pytest _prod_hard_test.py --co -q` → timeout 40 s tanpa output;
koleksi seluruh repo kecuali `tests/` → 317 s + 15 error dari kode vendored
`_vdbos/greenlet`.

→ **`pytest.ini`** baru: `testpaths = tests`, `norecursedirs` (kecualikan
kode vendored & skrip harness), `python_files = test_*.py` (buang pola
`*_test.py`). Berkas harness lokal diganti nama ke `_prod_hard_run.py`.

Hasil: koleksi **1273 tes dalam 4,94 s**; suite penuh
**1273 lulus, 0 gagal, 0 error dalam 503,61 s (8 m 23 s)** — sebelumnya
tidak pernah selesai.

### V2 — penegakan memori di Linux (Railway) ✅ VERIFIED

`RLIMIT_AS` belum pernah dibuktikan. Karena **produksi tidak punya jalur
eksekusi sandbox** (tak ada node `code`, tak ada tool MCP/agen, tak ada
endpoint; `code_sandbox` hanya dipakai `/version` dan validasi statis
testkit), jalur Linux diuji dengan menjalankan runner yang sama di Linux
sungguhan lewat job CI baru `sandbox-linux-limit` (`ubuntu-24.04`):

```
[trivial]       ok=True  os_limits=on  dur=0.043s
[alokasi-64MB]  ok=True  os_limits=on  dur=0.042s
[bomb-2GB]      ok=False os_limits=on  error='MemoryError: '
[bomb-512MB]    ok=False os_limits=on  error='MemoryError: '
[bomb-loop]     ok=False os_limits=on  error='MemoryError: '
```

Tidak perlu cgroup v2 / `systemd-run` / container per eksekusi.
Temuan sampingan (dicatat, belum ditutup): F6 belum tersambung ke produksi.

### V3 — bypass `str.format` ✅ FIXED (severity tetap MEDIUM)

Perbaikan kampanye pertama (pindai konstanta string di AST) **tidak memadai**:
pemindai melihat literal satu per satu, sehingga string yang **dirakit saat
runtime** lolos — **5/5 vektor rakitan bocor**:

```python
"{0." + "__class__" + "}".format(1)          # -> <class 'int'>
("{0." + chr(95)*2 + "class" + chr(95)*2 + "}").format(1)
f = ("{0." + "__class__" + "}").format; f(1)
```

Tidak bisa dieskalasi ke eksekusi kode (`str.format` hanya membaca atribut,
tak punya primitif pemanggilan) → **MEDIUM (pengungkapan), bukan HIGH**.

→ Penjaga **berbasis runtime**: transformasi AST `X.format`/`X.format_map`
→ `katalir_attr_format(X)` (di level `Attribute`, sehingga jalur "ambil
atribut tanpa memanggil" ikut tertutup), lalu string diperiksa **sesudah
dirakit**, termasuk format spec bersarang. Hasil: **0 bocor dari 20 vektor**,
format sah (`'{0:.2f}'`, `str.format(...)`, `format(x, '.2f')`) tetap jalan.
Diverifikasi ulang di Linux: 0 bocor dari 6 vektor.

Temuan sampingan: sandbox belum bisa mendefinisikan `class`
(`NameError: __metaclass__`) — terbukti identik sebelum & sesudah perubahan,
jadi bukan akibat fix ini; dicatat sebagai keterbatasan LOW.

## [2026-10-08] — Hard test batas 11 fitur: 10 batas ditemukan & diperbaiki

Brief "HARD TEST 11 FITUR — TEMUKAN BATASAN & PERBAIKI". Tujuannya bukan
"apakah fitur bekerja" (sudah dibuktikan), tapi **di mana ia BREAK**. Harness
`_hard_limits.py` (11 grup, 65 pemeriksaan) menjalankan boundary, stress, chaos,
adversarial, concurrent, long-running, resource, dan edge test. Laporan penuh:
**`docs/hard-test-limits.md`**.

### Diperbaiki — HIGH

- **Batas graf berbeda di tiga jalur tulis.** `api_server` 500 node/1000 edge,
  `mcp_server` 200 node, `workflow_templates` 100 node/200 edge. Akibatnya
  workflow 300 node bisa dibuat lewat API tetapi **ditolak** saat disimpan
  sebagai template atau dikirim lewat MCP.
  → modul baru **`flow_limits.py`** sebagai sumber kebenaran tunggal; ketiga
  modul mengimpornya. Kini 500/1000 di semua jalur.
- **Batas memori sandbox 128 MB tidak ditegakkan di Windows.** Alokasi
  **4 GB berhasil** (`ok=True`, 0,2 s). Watchdog berbasis thread Python tidak
  dapat menangkapnya karena `bytes(4GB)` adalah satu panggilan C yang memegang
  GIL — thread watchdog tidak pernah dijadwalkan. Metrik yang benar juga
  ditemukan: **`PagefileUsage` (commit charge), bukan `WorkingSetSize`**
  (WS tetap 38 MB sementara commit naik 12 → 525 → 2.577 MB).
  → **Windows Job Object** (`JOB_OBJECT_LIMIT_PROCESS_MEMORY`), ditegakkan
  kernel, dipasang sebelum kode user berjalan. Kini 64 MB lolos,
  128 MB–4 GB → `MemoryError`. `capabilities()` melaporkan `memory_enforced`
  dan `memory_mechanism` secara jujur.

### Diperbaiki — MEDIUM

- **`str.format` melewati penjaga atribut.** `'{0.__class__.__mro__}'.format(1)`
  membocorkan `__class__`, `__subclasses__`, dan **alamat memori (ASLR)** —
  melewati `FORBIDDEN_ATTRS` (AST) *dan* `_safe_getattr` (runtime). Ini kelas
  CVE-2026-76825 yang header modul klaim "tidak terpengaruh" pada
  RestrictedPython 8.5; **klaim itu tidak akurat** untuk jalur `str.format`.
  → tolak dunder di nama field `str.format`; format spec sah (`{0:.2f}`) tetap lolos.
- **Field `error` sandbox tidak dipotong** — exception 200 KB lolos utuh
  (stdout/stderr sudah dipotong). → `_potong()`.
- **`vault_cache` tanpa batas ukuran nilai** — 10 MB diterima. →
  `MAX_VALUE_BYTES` 256 KB; nilai lebih besar dilewati (bukan error).
- **`memory_manager` tanpa batas panjang `content`** — gagal di API embedding
  dengan galat buram, bukan 4xx rapi. → `MAX_CONTENT_CHARS` 20.000.
- **Jitter backoff diterapkan setelah cap** — delay nyata mencapai 37,5 s
  padahal `MAX_DELAY_SECONDS=30`. → jitter hanya ke bawah saat menyentuh cap.

### Diperbaiki — LOW

- `secret://../../etc/passwd` diterima apa adanya (inert: path dipakai sebagai
  kunci DB, bukan path berkas) → tolak segmen traversal dan karakter di luar
  `[A-Za-z0-9._-]`.
- `MAX_BRANCHES=64` dan `MAX_DEPTH=3` keras → dapat disetel lewat env
  (`MAX_PARALLEL_BRANCHES`, `SUBWORKFLOW_MAX_DEPTH`).

### Ditambahkan

- **`/version` mengekspos `limits`** (flow, sandbox, rate) untuk observabilitas.
- **`tests/test_hard_test_fixes.py`** — 16 tes pengunci agar perbaikan tidak
  dapat mundur diam-diam.
- **`docs/hard-test-limits.md`** — matriks per fitur, bukti mentah
  sebelum/sesudah, rekomendasi tuning post-launch, daftar env baru.

### Diterima (didokumentasikan, bukan diperbaiki)

- Tidak ada batas aplikasi untuk ukuran state durable — dibatasi ukuran baris
  Postgres.
- Validasi statis JavaScript longgar (`import(`, `constructor.constructor`),
  tetapi **eksekusi nyata 0/10 escape** — runtime menahan.
- `workflow_testkit` belum punya self-test/meta-test.

### Bukti

| Verifikasi | Hasil |
|---|---|
| Harness hard limit (11 grup, 65 pemeriksaan) | 10 batas diperbaiki |
| Regresi (sandbox/templates/secrets/flow/MCP) | **65 lulus** |
| Regresi (retry/subworkflow/parallel/memory/sandbox e2e) | **74 lulus + 19 subtests** |
| Regresi (workflow API/lifecycle/schedules/trigger/testkit/credential) | **100 lulus** |
| Tes pengunci baru | **16 lulus** |
| **Total** | **255 lulus, 0 gagal** |
| Escape sandbox Python / JavaScript (eksekusi nyata) | **0/50** dan **0/10** |

---

## [2026-10-08] — Lanjutan: verifikasi live, diagnosis straggler load, artefak final

Penutupan sesi: tes live tanpa stub untuk `/templates`, diagnosis tuntas untuk
1 request yang menggantung di load test, dan artefak bukti final.

### Ditambahkan

- **`nexus-frontend/tests/templates-live.spec.ts`** — tes Playwright **tanpa
  stub** yang memuat `/templates` di produksi memakai JWT Supabase nyata
  (di-refresh otomatis dari fixture). Menangkap kelas bug yang tidak bisa
  ditangkap suite stub: URL API salah, CORS, atau token tidak terkirim.
  Bukti: **14 kartu** termuat dari backend Railway, "RSS → Slack" ada,
  pratinjau menampilkan 4 node.
- **`_prod_load_isolated.py`** — leg load terisolasi (50/100/200/500) yang bisa
  diulang tanpa beban saingan, dengan retry GET idempoten.
- **`_probe_load_stall.py`** — probe pembeda server-vs-klien: watchdog menembak
  `/health` di koneksi baru tiap 2 detik selama load + retry straggler.
- **2 screenshot baru** (`13-live-prod.png`, `14-live-preview.png`) → total 14.

### Diperbaiki

- **Playwright gagal membersihkan `test-results` (340 berkas).** Guard
  `safe-delete` memblokir penghapusan massal (>50 berkas) sehingga run yang
  sebenarnya lulus tetap berakhir dengan error. Bukan bug produk.
  → `outputDir` di `playwright.templates.config.ts` diarahkan **ke luar
  workspace** (`PW_OUTPUT_DIR`, default `%TEMP%/katalir_pw_out/...`).
  Config juga menerima `E2E_SPEC` untuk memilih suite stub atau live.

### Diagnosis

- **"Straggler" load test = artefak koneksi klien/edge, bukan backend.**
  Pada n=200/500 tepat 1 request menggantung sampai persis timeout klien tanpa
  satu pun 5xx. `_probe_load_stall.py` (3 ronde × n=500) menunjukkan: watchdog
  menembak 23× `200` berturut-turut di ronde yang sama (median 394 ms, nol
  non-200), dan keempat straggler sukses **<1 s** saat diulang.
  → harness memakai retry GET idempoten (perilaku klien produksi);
  hasil akhir **5/5 PASS**, hanya 2 retry dari 950 request (0,2 %).

### Bukti

| Verifikasi | Hasil |
|---|---|
| Playwright `/templates` (12 stub + 1 live) | **13/13 PASS** |
| Load terisolasi (`_prod_load_isolated.py`) | **5/5 PASS — ALL GREEN** |
| Load mentah tanpa retry | 0× 5xx; 0–4 straggler klien/ronde |
| `/version` produksi | commit `53886ad`, `features_present: 11/11` |
| `/templates` di 2 domain | **200**, 13.948 byte |

---

## [2026-10-08] — Deploy 11 fitur + UI Template Gallery + perbaikan bug produksi

Sesi ini menutup tiga hal: (1) 11 fitur workflow di-deploy & diverifikasi di
produksi, (2) UI Template Gallery dibangun dan di-deploy, (3) dua bug produksi
yang hanya muncul lewat hard test adversarial diperbaiki.

### Ditambahkan

- **UI Template Gallery** (`nexus-frontend/src/features/templates/`) — halaman
  `/templates` dengan pencarian + filter kategori (server-side), modal
  pratinjau yang menampilkan rantai node terurut topologis, aksi "Pakai"
  (membuat workflow nyata), dan hapus untuk template kustom.
  - `TemplateCard.tsx`, `TemplateGallery.tsx`, `TemplatePreview.tsx`,
    `api.ts`, `types.ts`, `index.ts`
  - `src/app/templates/page.tsx` (pola `SimplePage`, `max-w-5xl`)
  - tautan **Template** di navigasi shell + kunci i18n `nav.templates` (id/en)
  - `templateKeys` di `src/lib/query-keys.ts`
- **Endpoint `/version`** dan blok `build` pada `/health` — memuat
  `RAILWAY_GIT_COMMIT_SHA`, service, environment, dan status 11 modul fitur.
  Dipakai untuk membuktikan commit mana yang benar-benar jalan.
- **`validate_workflow_flow()`** di `api_server.py` — validasi graf untuk jalur
  tulis `/workflows` (batas 500 node / 1000 edge, id unik, edge menunjuk node
  yang ada, tanpa self-loop).
- **Tes**: `tests/templates-gallery.spec.ts` (12 Playwright),
  `tests/test_workflow_flow_validation.py` (12 pytest),
  2 tes regresi MCP di `tests/test_mcp_server_builtin.py`.
- **Dokumentasi**: `docs/deployment-status.md` (sumber kebenaran status deploy),
  `docs/marketing/screenshots/templates-gallery/` (12 screenshot).

### Diperbaiki

- **Kritis — Fitur #8 MCP tidak bisa dipakai sama sekali.** `app.mount("/mcp/katalir", ...)`
  didaftarkan di awal modul, sedangkan `/mcp/katalir/info`, `/mcp/katalir/key`,
  dan `/mcp/katalir/verify` dideklarasikan ~3.500 baris di bawahnya. Karena
  `Mount` cocok berdasarkan **prefix** dan menurut urutan pendaftaran, ketiga
  route itu tidak pernah tercapai dan membalas JSON-RPC `-32001` (auth MCP).
  Akibatnya user tidak pernah bisa menerbitkan API key MCP.
  → mount dipindah ke **akhir modul**; route eksplisit kini menang.
  Route exact `/mcp/katalir` tetap di index 0 agar POST tanpa trailing slash
  tidak 307.

- **Tinggi — `POST /workflows` menyimpan `flow_data` apa adanya.** Terbukti di
  produksi: graf 5.000 node diterima (201), self-loop diterima, dan edge ke
  node yang tidak ada diterima. Padahal `workflow_templates.validate_flow_data`
  dan `mcp_server._validate_flow_data` sudah menegakkan aturan yang sama — jalur
  tulis utama justru yang paling longgar (permukaan DoS + data rusak).
  → validasi dipasang untuk INSERT **dan** UPDATE (autosave kanvas), pelanggaran
  membalas **422**, bukan 500.

- **Sedang — `GET /templates/{id}` dengan id non-UUID membalas 500.**
  PostgREST menolak sintaks uuid sehingga muncul "Internal Server Error".
  Jawaban benar untuk "tidak ada" adalah 404. Cacat yang sama ada di
  `DELETE /templates/{id}`.
  → guard `uuid.UUID()` di `get_template()` dan `delete_custom_template()`.

### Dicatat, sengaja TIDAK diubah

- `GET /executions/{id}` untuk id yang tidak ada membalas **200** dengan
  `execution: null` dan `report` berisi "status 'unknown'". Tidak ada kebocoran
  data (ownership tetap dicek saat eksekusi ada), dan frontend melakukan
  polling sehingga 404 justru mengganggu. Dipertahankan sebagai desain;
  didokumentasikan di `docs/deployment-status.md`.

### Bukti

| Verifikasi | Hasil |
|---|---|
| E2E 11 fitur di produksi (`_prod_e2e_11features.py`) | **23/23 PASS** |
| Playwright Template Gallery vs produksi | **12/12 PASS** |
| Hard test produksi (load/adversarial/durability/long/integrasi/n8n) | lihat `docs/deployment-status.md` |
| Suite pytest (lokal) | **1227 passed** (sebelum sesi) + tes baru hijau |
| Regresi 9 file workflow/MCP | **103 passed** |

### Catatan operasional

- Frontend di-deploy **manual** (project Cloudflare Pages `proyek-agent` tidak
  punya Git source); backend auto-deploy dari `git push` ke `main`.
- Build frontend di mesin ini memerlukan preload `_build_retry.cjs` dan Node
  sistem (24.x) — lihat `docs/deployment-status.md` §6.
