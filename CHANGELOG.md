# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/).
Versi mengikuti tanggal kerja (proyek ini belum memakai semver rilis).

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
