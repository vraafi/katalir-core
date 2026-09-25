# Catatan Kendala & Keluhan — Katalir v2

File ini adalah catatan honestly dari proses integrasi. Tiap kendala dicatat dengan
dampak, akar masalah, dan status. Jangan hapus entri yang sudah `CLOSED`; ia
penting sebagai jejak audit.

Status: `OPEN` = belum ada solusi, `BLOCKED` = ada solusi tapi butuh keputusan/
kredensial, `CLOSED` = sudah dieksekusi dan diverifikasi.

---

## 2026-09-25 — Token OpenConnector bocor ke transkrip

- **Status:** CLOSED
- **Keluhan:** Saat inspeksi gateway, perintah `tail -20 /opt/agentgateway/config.yaml`
  mencetak isi file yang saat itu masih memuat runtime token OpenConnector, sehingga
  token masuk ke transkrip percakapan.
- **Dampak:** SEV-1. Kredensial runtime OpenConnector sempat terekspos di luar VPS.
- **Akar masalah:** (a) token disimpan langsung di config gateway; (b) skrip inspeksi
  mencetak file mentah tanpa masking.
- **Solusi yang dieksekusi:**
  1. Config gateway dipulihkan dari backup `config.yaml.bak.oc`; service `active`, port 3001 up.
  2. **Token dirotasi** (`openssl rand -base64 32` untuk admin + runtime). Encryption key
     dipertahankan agar kredensial yang sudah tersimpan tetap bisa didekripsi.
  3. Container direcreate dengan token baru, health 200.
  4. Token dipindah keluar dari config: `scripts/openconnector_proxy.py` menyuntikkan
     Authorization saat request, dibaca fresh dari `/root/.openconnector.env`.
  5. `_vps_gw_inspect.py` diganti: hanya grep name/host/port/cmd + masking `Bearer|token|key`.
  6. Semua log `oc-*.log` / `gw-*.log` dihapus.
- **Pelajaran:** jangan pernah `cat`/`tail` file yang mungkin berisi kredensial.
  Selalu inspeksi dengan grep ter-mask, dan rotasi setiap secret yang pernah sampai
  ke transkrip, log, atau commit.

---

## 2026-09-25 — agentgateway MCP target tidak punya field `headers`

- **Status:** CLOSED
- **Keluhan:** Percobaan pertamadma menyematkan `Authorization: Bearer` di dalam target MCP
  gagal: `Error: mcp: unknown field 'headers' at line 1 column 682`. Service crash-loop.
- **Dampak:** SESA. Gateway down sampai rollback dilakukan.
- **Akar masalah:** Skema target MCP agentgateway memang tidak punya field `headers`.
  Berhentinya service terjadi karena config invalid, bukan karena bug agentgateway.
- **Solusi yang dieksekusi:**
  1. Rollback otomatis dari backup (sudah_fail-safe di skrip, pertama sempat salah
     mengira rollback karena hanya menunggu 6 detik → diperbaiki jadi polling 40 detik).
  2. Pendekatan diganti: proxy lokal token-injector di `127.0.0.1:3011`, config gateway
     bersih dari secret.
  3. Verifikasi: `initialize` 200, `tools/list` 38 → 43, `tools/call` sukses.
- **Pelajaran:** jangan menaruh secret di file config. Sisipkan secret di lapisan
  runtime yang bisa dirotasi tanpa restart.

---

## 2026-09-25 — Angka 18.010 actions ≠ 18.010 MCP tools

- **Status:** CLOSED (sudah diklarifikasi, tapi berisiko terulang)
- **Keluhan:** Ada risiko besar klaim marketing menyamakan "18.010 actions" dengan
  "18.010 integrasi executable".
- **Fakta:** OpenConnector hanya mengekspos **5 meta-tool** MCP
  (`list_apps`, `list_connections`, `search_actions`, `get_action_guide`, `execute_action`).
  18.010 actions **reachable saat runtime lewat meta-tool**, bukan 18.010 schema tool.
- **Solusi:** Aturan bahasa dikunci di `docs/architecture/openconnector-integration.md`.
  Klaim yang aman: *"18.010 OpenConnector actions discovered, exposed through a 5-tool
  MCP meta-layer."*
- **Pelajaran:** `discovered` ≠ `listed` ≠ `call_verified`. Tidak boleh dilewati.

---

## 2026-09-25 — Nango belum bisa dideploy: VPS kekurangan RAM

- **Status:** BLOCKED (sumber daya, bukan riset)
- **Keluhan:** Tidak ada `NANGO_URL` yang terverifikasi, jadi Nango belum bisa
  masuk ke pipeline runtime verification.
- **Penelusuran dilakukan (bukan berhenti di "tidak ada info"):**
  - NangoHQ/nango `docker-compose.yaml` memuat `nango-db` (postgres:16.0-alpine),
    `nango-server` (image `nangohq/nango-server`), `nango-redis` (redis:7.2.4),
    plus elasticsearch opsional untuk logs
  - Env wajib antara lain: `NANGO_ENCRYPTION_KEY`, `NANGO_DB_*`,
    `RECORDS_DATABASE_URL`, `NANGO_SERVER_URL`, `NANGO_PUBLIC_SERVER_URL`
  - Docs Self-Managed: free self-hosting hanya **Auth + Proxy**; fitur lain butuh
    Enterprise Self-Managed. Jalur produksi yang didukung adalah Helm/Kubernetes
    dengan managed image
- **Blocker nyata — hasil pengukuran VPS:**
  - 2 vCPU, RAM total **2.468 MB**, tersedia **931 MB**
  - Disk 43 GB, terpakai 24% (bukan masalah)
  - Container produksi yang harus tetap hidup: `open-connector`, `free-llm-gateway`
  - Postgres + Nango + Redis butuh ±1–1,5 GB RAM
- **Keputusan:** Nango **tidak** dideploy di VPS ini. Mematikan gateway produksi
  demi integrasi yang belum terbukti bukan kemajuan.
- **Syarat untuk membuka blocker:** VM terpisah minimal 4 GB RAM (atau VPS 4 GB
  baru), lalu: jalankan compose → `GET /api/v1/config` → health → `list_connections`
  → sync metadata dengan status `discovered`.
- **Catatan arsitektur:** Nango bernilai sebagai lapisan **OAuth/connection**, bukan
  sumber tool. MCP-nya adalah management MCP (baca config/integrasi), jadi
  federasinya ke agentgateway tidak menambah tool pengguna. Prioritasnya di bawah
  OpenConnector untuk target "10.000+ runtime-verified".

---

## 2026-09-25 — Glama: kontradiksi lisensi & akses

- **Status:** CLOSED (API key tersedia; sync + atribusi selesai)
- **Keluhan:** Prompt menyebut Glama "public/free", sementara riset sebelumnya
  menemukan Glama mewajibkan API key, attribution, dan tunduk pada API Data License.
- **Hasil verifikasi (dokumentasi resmi Glama, dibaca langsung):**
  - Base URL: `https://glama.ai/api/mcp`
  - Endpoint: `GET /v1/servers`, `GET /v1/servers/{namespace}/{slug}`, `GET /v1/connectors`
  - Autentikasi: **wajib** `Authorization: Bearer <GLAMA_API_KEY>` untuk semua endpoint baca
  - Rate limit: 100 request/detik per IP, paginasi cursor (`first`/`after`), maks 100 per halaman
  - Header IETF RateLimit tersedia untuk pacing
  - **Lisensi: API Data License — data ini berlisensi, bukan public domain**
  - **Atribusi wajib** pada setiap halaman yang menampilkan data API: tautan ke
    `https://glama.ai` tanpa `rel="nofollow"/"sponsored"/"ugc"`
  - **Setiap listing wajib tertaut** ke halaman resminya di Glama, berdampingan
    dengan tautan lain (bukan menggantikannya)
  - Atribusi bisa **dibebaskan** lewat lisensi komersial
- **Kesimpulan:** Glama bukan "public domain", tapi **API publik berlisensi dengan
  syarat atribusi**. Kontradiksi tadi muncul karena dua sumber berbeda menyebut
  dua hal berbeda; sekarang tidak ada ambiguitas.
- **Syarat sebelum sync:** (1) `GLAMA_API_KEY` tersedia, (2) UI integrations
  menampilkan kredit Glama, (3) tiap kartu integrasi Glama tertaut ke listing resminya.
- **Status sync:** SELESAI 2026-09-25. `GLAMA_API_KEY` dipakai, 20.000 server + 1.000
  konektor tersinkron, dan atribusi + backlink sudah dirender di `/integrations`,
  `/`, `/docs`, `/pricing` tanpa `rel="nofollow"`. Lihat
  `docs/architecture/glama-integration.md` dan
  `docs/distribution/glama-attribution.md`.

---

## 2026-09-25 — Toolkit Composio butuh OAuth per user

- **Status:** CLOSED (dibatasi, bukan diblokir)
- **Keluhan:** 20/20 toolkit lolos `list_tools`, tapi `call_tool` hanya berhasil di 1 toolkit
  no-auth. Sisanya butuh connected account per user.
- **Solusi:** skema `runtime_verified` dipecah jadi `tools_listed` dan `call_verified`
  supaya UI tidak menampilkan "verified" untuk yang hanya lolos listing.


---

## 2026-09-25 — Glama API intermittent: HTTP 525 dan balasan HTML

- **Status:** CLOSED
- **Keluhan:** Probe pertama ke `glama.ai` timeout, lalu HTTP **525** (SSL handshake
  gagal di edge Cloudflare) padahal TCP connect cuma 67 ms dan Composio normal (401).
  Sempat terlihat seperti jaringan diblokir.
- **Akar masalah:** Glama (via Cloudflare) memang sesekali tidak stabil.
  Konfirmasi: setelah ~2 menit, request yang sama balas 200/401 normal.
- **Solusi:** `scripts/sync-glama.py` retry 5xx/525 **dan** balasan non-JSON dengan
  exponential backoff (`Retry-After` diprioritaskan). Sync 20.000+1.000 entry
  selesai dengan 222 request + 18 transient retry, nol kegagalan.
- **Pelajaran:** timeout sesaat dari satu vendor bukan bukti blockade. Isolasi dulu
  (TCP vs TLS vs HTTP vs JSON) sebelum menyimpulkan.

---

## 2026-09-25 — Asumsi "20.000 Glama server" meleset di dua tempat

- **Status:** CLOSED
- **Keluhan:** Rencana awal mengklaim 91.014 server + 843.355 tools bisa di-sync.
  Kenyataannya tidak bisa, dan mengarangnya berarti memalsukan data.
- **Temuan aktual (2026-09-25, API resmi):**
  1. `/v1/servers` **tidak mengembalikan daftar tool** — field `tools` selalu kosong,
     bahkan di endpoint detail (25/25 sampel). `/v1/tools` bukan endpoint; dia
     302 ke halaman dokumentasi. Jadi **843.355 tools tidak bisa diambil** lewat
     API ini, dan tidak diklaim.
  2. `/v1/connectors` **dibatasi 1.000 entry unik**, bahkan kalau difilter
     `?auth=none` atau `?status=healthy` (diverifikasi dua kali).
  3. Response tidak punya field `total`, jadi ukuran direktori tidak boleh
    diasumsikan dari skrip.
- **Solusi:** sinkron 20.000 server + 1.000 konektor, laporkan hanya angka yang
  benar-benar terambil, dan simpan angka direktori sebagai referensi dari facets.
- **Pelajaran:** klaim harus berasal dari payload yang kita baca sendiri, bukan
  dari angka yang diharapkan.

---

## 2026-09-25 — Label `auth:none` dari Glama tidak bisa dipercaya

- **Status:** CLOSED
- **Keluhan:** 619 konektor ditandai `auth:none`, jadi terlihat aman untuk diuji.
- **Hasil nyata:** dari 60 yang di-probe, **30 (50%) tetap meminta kredensial**
  (401/403). Hanya 28 yang benar-benar bisa `initialize` + `tools/list`.
- **Dampak kalau tidak dicek:** klaim "619 no-auth connector terverifikasi" akan
  salah setengah.
- **Solusi:** `verification.tools_listed` per konektor disimpan dari hasil probe,
  bukan dari label Glama. Badge "Auth required" muncul justru dari bukti runtime.
- **Pelajaran:** metadata vendor adalah petunjuk, bukan janji. Ukur ulang.

---

## 2026-09-25 — Build Next.js menggantung karena proses-nya dibunuh

- **Status:** CLOSED
- **Keluhan:** `next build` terlihat macet di "Creating an optimized production
  build" selama belasan menit, tanpa error.
- **Akar masalah:** build dijalankan lewat `Start-Process cmd -NoNewWindow`; saat
  perintah tool timeout, proses anaknya ikut dibunuh. Yang tersisa di Task Manager
  ternyata proses `node` **orphan dari sesi 7,5 jam sebelumnya**, bukan build saya.
- **Solusi:** jalankan detached (`-WindowStyle Hidden`), tulis `EXIT=%ERRORLEVEL%`
  ke file, lalu polling file tersebut. Build selesai normal, `BUILD_EXIT=0`.
- **Pelajaran:** sebelum menyimpulkan build hang, cek `StartTime` proses — proses
  lama yang masih hidup bukan bukti build sedang jalan.

---

## 2026-09-25 — RAM produksi: katalog Glama mentah, hampir OOM

- **Status:** CLOSED
- **Keluhan:** `glama_servers.json` versi pertama 23,4 MB dan memuatnya utuh ke
  registry memberi **183 MB peak** — berisiko OOM di container Railway.
- **Akar masalah:** saya menyimpan field yang tidak pernah dipakai UI (`auth_schemes`,
  `thumbnail_url`, `install_config`, `quality_score`) plus JSON ber-indentasi.
- **Solusi:** simpan proyeksi slim (16 field, separator rapat, deskripsi 200
  karakter) → file 13,2 MB, peak 143 MB, retensi 56 MB.
- **Pelajaran:** ukur `tracemalloc` sebelum dan sesudah menambah sumber katalog.


- **Status:** CLOSED

---

## 2026-09-26 — Fase I (Activepieces/Metorial/velane/Executor): STOP sebelum deploy

- **Status:** BLOCKED (keras) — kontradiksi spesifikasi vs realitas + blocker RAM
- **Kenapa berhenti:** riset repo (semua dibaca langsung, 2026-09-26) menunjukkan
  4 dari 5 premis Fase I salah. Menerapkannya apa adanya akan (a) OOM-mematikan
  produksi, dan (b) Gelembungkan angka katalog dengan entri duplikat — persis
  kebohongan yang selama ini kita talangi.
- **Bukti per repo:**

| Asumsi prompt | Aktual (sumber) | Dampak |
| --- | --- | --- |
| Activepieces: 764 pieces | Tagline repo: "~400 MCP servers". Endpoint `/api/v1/pieces` **tidak ada** di compose/dokumentasi yang diperiksa. | Angka 764 tidak terverifikasi |
| Activepieces: "Docker Compose" | `docker-compose.yml` (main) mendefinisikan `app` + `worker` dengan **`deploy.replicas: 5`** + `postgres` (pgvector) + `redis` → **8 container** | 8 container di box 2 vCPU / 1,75 GB tersedia = pasti OOM |
| velane: 800+ OAuth integrasi sendiri | Diagram arsitekturnya sendiritertulis: **"OAuth Proxy (800+ providers via Nango)"** | 800 = katalog Nango. Sync velane + Nango = **double count** |
| velane: AGPL-3.0 | AGPL-3.0 **+ COMMERCIAL-LICENSE** (komersial butuh lisensi) | Batasan lisensi tambahan |
| velane: deploy via Docker Compose | Butuh Postgres + Redis + **ClickHouse** + control plane (Go) + executor pool (Bun + Python) | ClickHouse sendirinya ~2 GB+ RAM |
| Executor: `shuv1337/executor`, 1 container Docker | Itu **fork 0-star** dari `UsefulSoftwareCo/executor`; README: "Development happens in this private repository" | Repo yang dirujuk bukan yang otoritatif; tidak ada image Docker 1-container |
| Executor: self-host Docker | Docs menyebut `bun run server` / `bun run executor serve`, app jalan di **workerd** (Cloudflare Workers runtime) | Mekanisme deploy tidak seperti asumsi |
| Metorial: 600+ verified tools, serverless MCP | Situs resmi: "**142 tools across 18 integrations**" (demo), klaim marketing "1,000 integrations". Produk = enterprise agentic infra (SSO/SAML, Protoguard, tracing) | Angka 600+ tidak terverifikasi |
| Nango Cloud free: 10 connections + **100k runs** | Pricing resmi: Free $0 = **10 connections, 10 jam/bulan compute, 10 GB/bulan transfer**. Bukan run-count. | 100k runs = angka salah |

- **Blocker infrastruktur (diukur langsung):**
  ```
  CPU  : 2 vCPU
  RAM  : 2468 MB total · 1752 MB available · swap 1279 MB
  Disk : 32 GB free
  Jalan: open-connector, free-llm-gateway (produksi)
  ```
  Aktifpieces saja butuh 8 container. Menambah velane (ClickHouse) dan Executor
  akan mengambil alih RAM produksi — berulang kali keputusan yang sama sudah
  menolak Nango self-host, dan alasannya belum berubah.
- **Temuan paling penting:** 800 "integrasi" velane **adalah katalog Nango**.
  Menyalin keduanya ke registry akan menggandakan entri yang sama dan membuat
  klaim "40.000+ catalog" menjadi angka yang dipompa, bukan hasil kerja.
- **Opsi (pilih satu):**
  1. **Naikkan kapasitas VPS ke ≥8 GB**, lalu deploy hanya **Activepieces** (satu
     platform, nilai nyata) dan **Nango Cloud** (butuh signup user). Abaikan
     velane & Executor sampai repo-nya matang. *(rekomendasi)*
  2. **Tetap di box sekarang**: tidak ada yang di-deploy. Fokuskan energi pada
     menaikkan angka **runtime-verified** dari katalog yang sudah ada — kita punya
     28.532 entri tapi baru 45 terverifikasi; di situ sebenarnya gap-nya.
- **User action dibutuhkan (bisa dilakukan paralel):** signup Nango Cloud di
  https://app.nango.dev → simpan `NANGO_API_KEY` ke `.env`. Saya tidak bisa
  mendaftar akun atas nama Anda.



- **Status:** CLOSED (Opsi 3 dipilih user, selesai 2026-09-26)
- **Keluhan:** Tab "Native" diimplementasikan sebagai bucket sumber `toolsdk`, yaitu
  **4.416 entri metadata ToolSDK** — bukan provider MCP native yang benar-benar
  berjalan. User bisa mengira 4.416 entri itu sudah bisa dijalankan.
- **Keputusan user:** Opsi 3 — pisahkan tab Native (yang berjalan) dari tab
  ToolSDK (metadata katalog).
- **Solusi yang dieksekusi:**
  1. Endpoint baru `GET /mcp/native` mengembalikan `provider_registry.PROVIDERS`
     apa adanya, lengkap dengan `needs_credential`. **Angka diturunkan dari kode**,
     tidak pernah di-hardcode di UI — itu akar masalahnya.
  2. `/integrations` sekarang 6 tab: All · Native MCP · OpenConnector · Composio ·
     Glama · ToolSDK, masing-masing dengan info card (`tab-note`).
  3. `GET /mcp/registry/sources` menambah key `native` agar count di UI sama
     dengan kenyataan.
  4. Regression test mengunci kontrak ini: `/mcp/native` harus sama dengan
     `provider_registry`, dan `runtime_verified` hanya true bila provider tidak
     butuh kredensial.
- **Temuan sampingan (penting):** spesifikasi menyebut "Native MCP (5)", tapi kode
  berisi **7** provider native: telegram, slack, http, gmail, google_sheets,
  whatsapp, google_calendar. Angka 5 **tidak dipakai** karena bertentangan dengan
  kode; hanya `http` yang benar-benar tanpa kredensial. Menyebut "5" akan menjadi
  klaim palsu yang persis sama dengan masalah yang sedang diperbaiki.
- **Bug yang tertangkap saat menulis test:** endpoint awalnya memakai
  `runtime_verified: True` hardcode untuk semua provider, sehingga 6 dari 7
  provider mendapat badge Ready padahal butuh kredensial. Assertion
  `runtime_verified is (not needs_credential)` langsung menangkapnya.
- **Pelajaran:** angka di spesifikasi tetap perlu diadu dengan kode. Kalau
  berbeda, kodenya yang benar — dan selisihnya dicatat, bukan dihilangkan.
