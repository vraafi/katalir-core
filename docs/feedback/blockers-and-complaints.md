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

- **Status:** CLOSED (ketentuan terverifikasi; sync masih butuh API key)
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
- **Status sync:** BELUM — terkunci di syarat (1). Tidak ada data Glama yang
  disalin ke cache produksi sebelum ketiganya terpenuhi.

---

## 2026-09-25 — Toolkit Composio butuh OAuth per user

- **Status:** CLOSED (dibatasi, bukan diblokir)
- **Keluhan:** 20/20 toolkit lolos `list_tools`, tapi `call_tool` hanya berhasil di 1 toolkit
  no-auth. Sisanya butuh connected account per user.
- **Solusi:** skema `runtime_verified` dipecah jadi `tools_listed` dan `call_verified`
  supaya UI tidak menampilkan "verified" untuk yang hanya lolos listing.


---

## 2026-09-25 — Heuristik "credential free" menyesatkan

- **Status:** CLOSED
- **Keluhan:** Sync pertama melaporkan `CREDENTIAL_FREE=13840` dari heuristik
  `requiredScopes == [] and providerPermissions == []`. Angka itu **menipu**:
  13.840 action itu tetap butuh API key atau OAuth. Kalau dipakai untuk klaim
  "13.840 no-credential integrations", itu sama dengan memalsukan bukti.
- **Akar masalah:** OpenConnector punya field `execution` yang sudah menyatakan
  kebenaran (`noAuthRunnable`, `requiredAuthTypes`, `locallyExecutable`, `catalogOnly`).
  Heuristik homemade mengabaikannya.
- **Angka sebenarnya setelah membaca `execution`:**
  - `noAuthRunnable: true` → **170 action** (24 service)
  - dari 170 itu, yang input schema-nya kosong → **19 action**
  - `locallyExecutable: true` → 18.010, tapi itu bukan klaim runtime.
- **Solusi yang dieksekusi:**
  1. Skrip sync memakai `execution.noAuthRunnable` sebagai penentu, bukan tebakan.
  2. `credential_free()` tetap ada tapi didokumentasikan eksplisit sebagai
     "tidak ada scope", bukan "tanpa kredensial".
  3. Batch test memakai kriteria `read + noAuthRunnable + no input` → 19 kandidat.
- **Pelajaran:** kalau sumber data punya verdict sendiri, pakai verdict itu.
  Heuristik hanya untuk hal yang benar-benar tidak dijawab sumber.

---

## 2026-09-25 — Batch test 50 action tidak bisa jadi 50

- **Status:** CLOSED (dibatasi, bukan gagal)
- **Keluhan:** Rencana awal "uji 50 action no-credential" tidak bisa pursuit 50.
- **Fakta:** hanya 19 action yang memenuhi `read + noAuthRunnable + input kosong`.
  Memaksakan 50 berarti salah satu dari: mengarang argumen, memanggil API bertulis,
  atau memakai kredensial milik orang lain. Ketiganya tidak dilakukan.
- **Solusi:** jalankan 19 yang aman, hasilnya 11 `ok` / 4 `auth_required` /
  3 `invalid_input` / 1 `no_connection` — semuanya hasil nyata, bukan noise.
- **Pelajaran:** angka target yang tidak bisa dicapai dengan cara aman harus
  diturunkan dan dijelaskan, bukan dipaksakan.

---

## 2026-09-25 — Penulisan skrip terpotong (SyntaxError/NameError)

- **Status:** CLOSED
- **Keluhan:** Menulis `scripts/sync-openconnector.py` lewat beberapa operasi insert
  menghasilkan file tidak valid: `SyntaxError` → `IndentationError` → `NameError:
  credential_free is not defined`. Penyebabnya sisa blok lama di ekor file yang tidak
  terhapus saat truncation.
- **Dampak:** SESA pada skrip, tidak menyentuh produksi.
- **Solusi:** `py_compile` dijadikan gerbang sebelum setiap upload ke VPS,
  `credential_free()` dipulihkan, file dipangkas bersih, lalu idempotensi diuji:
  dua kali sync menghasilkan md5 identik dan `DIFF_SERVICES 0`.
- **Pelajaran:** kompilasi lokal dulu sebelum kirim ke server, dan selisih hash
  dicari sampai habis, bukan dianggap kebetulan.
