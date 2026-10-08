# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/).
Versi mengikuti tanggal kerja (proyek ini belum memakai semver rilis).

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
