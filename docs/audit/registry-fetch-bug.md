# Bug: "Registry tidak dapat dimuat" di `/integrations`

Status: **SELESAI & TERVERIFIKASI DI PRODUKSI.** Perbaikan backend di
commit `2a6e207`; `/mcp/registry/sources` kini 200 dengan angka source
yang benar.

## Gejala yang dilihat user

- `/integrations` menampilkan "Gagal memuat registry. Registry tidak
  dapat dimuat. Coba lagi."
- Tab source semua `(0)`: Native MCP 0, Glama 0, dan seterusnya.
- "All (29.558)" tetap tampil.
- Search bar justru berfungsi (instant).

## Yang BUKAN penyebabnya

Tiga hal sempat dicurigai dan ketahuan salah. Dicatat supaya tidak
diulang:

1. **`NEXT_PUBLIC_API_URL` masih `localhost:8000`.** Tidak. Bundle
   produksi sudah memanggil
   `https://web-production-dc90b.up.railway.app` (regresi ini memang
   pernah ada dan sudah diperbaiki di `352f633`).
2. **CORS salah.** Tidak. Header sudah benar:
   - `access-control-allow-origin: https://katalir.de5.net`
   - `vary: Origin, accept-encoding`
3. **Backend mati.** Tidak. `/health` balas 200 dan `/mcp/registry`
   balas 200 dengan data nyata.

## Isolasi

```
GET /health                                  -> 200
GET /mcp/registry?limit=5&search=&view=all    -> 200   (data nyata)
GET /mcp/registry/sources                     -> 500   <-- hanya ini
```

Katalog UTAMA sehat. Yang mati hanya endpoint yang mengisi tab source.
Itu menjelaskan kenapa "All (29.558)" tetap muncul sementara semua tab
source nol: keduanya datang dari endpoint berbeda.

## Akar masalah

Commit `e7ff081` menghapus tiga fungsi dari `mcp_registry.py`:

- `coverage()`
- `recommend_servers()`
- `openconnector_coverage()`

…tapi pemanggilnya masih ada:

| Lokasi | Panggilan |
| --- | --- |
| `api_server.py:1640` | `"coverage": catalog.coverage(),` |
| `api_server.py:1655` | `return catalog.coverage()` |
| `tests/test_mcp_recommendations.py:5` | `c = mcp_registry.coverage()` |

Hasil: `AttributeError: module 'mcp_registry' has no attribute
'coverage'` -> 500 dengan body kosong. Frontend menangkapnya dan
menampilkan pesan "Registry tidak dapat dimuat"; tab source tetap
`(0)` karena datanya memang tidak pernah sampai.

## Yang dipulihkan

- **`coverage()`** — `total` dijumlah dari `source_counts_unique()`,
  `executable` dari `executable_servers()`. Keduanya berasal dari
  katalog yang sama sehingga tidak bisa berbeda definisi, dan tidak
  ada angka konstanta di dalamnya.
  Catatan: menghitung tier lewat `list_canonical` ditolak karena
  fungsi itu menolak `limit > 100` dan harus memindai ~29 ribu baris
  per halaman — terlalu lambat untuk dipanggil tiap request.
- **`recommend_servers()`** dan **`openconnector_coverage()`** —
  dipulihkan apa adanya dari `e7ff081^`, bukan ditulis ulang.

## Test yang sudah merah sejak saat itu

`pytest tests/test_mcp_recommendations.py tests/test_mcp_registry.py`
gagal sejak `e7ff081` dengan `AttributeError` yang sama. Tidak
ketahuan karena saat itu hanya file registry yang dijalankan.

```
15 passed
78 passed, 265 deselected   (pytest -k "registry or glama or mcp")
coverage() -> total 25925, executable 23, metadata_only 25902
PROVIDERS  -> 7   (angka tab "Native MCP")
```

## Verifikasi produksi

Dijalankan setelah deploy `2a6e207` ke Railway.

### Endpoint

```
GET /health                    -> 200
GET /mcp/registry?limit=5...   -> 200
GET /mcp/registry/sources      -> 200   (sebelumnya 500)
```

Payload `/mcp/registry/sources` di produksi:

```
glama            = 20000
toolsdk          = 4415
composio         = 1558
openconnector    = 1554
nango            = 1024
glama-connector  = 1000
openapi-generated= 6
metorial         = 1
native           = 7          <- angka tab "Native MCP"
coverage.total   = 29558
coverage.executable = 23
attribution.glama.required = true
```

### Browser (Playwright, target produksi)

Dijalankan dengan `E2E_TARGET=https://katalir.de5.net`:

```
API=200 .../mcp/registry?limit=50&search=&view=all
API=200 .../mcp/registry/sources
API=200 .../mcp/registry/categories?limit=40
HAS_ERROR_MSG=false
NATIVE_COUNT=7
EXIT=0
```

Screenshot: `docs/audit/integrations-live-verify.png`

Screenshot itu diambil dengan sesi lokal dummy (butuh auth), jadi
sama seperti tiga screenshot self-healing sebelumnya ia **internal-only**
dan tidak layak jadi materi Product Hunt. Angka di dalamnya asli
produksi, tapi sesinya bukan sesi pengguna sungguhan. Untuk materi
publik, ambil ulang dengan sesi signed-in asli.

## Jebakan kedua: `coverage.total` = 0 di produksi

Setelah `coverage()` pulih, `/mcp/registry/sources` sudah 200 tapi
`coverage.total` masih **0**. Penyebabnya: `total` dihitung dari
`source_counts_unique()`, yang membaca `dedup_canonical.json` — dan
file itu **di-gitignore** (`.gitignore:22`) karena merupakan hasil
build. Jadi di produksi file itu tidak ada dan
`source_counts_unique()` mengembalikan `{}`.

Perbaikan: `coverage()` memakai `source_counts_unique()` kalau ada,
dan jatuh ke `source_counts()` kalau tidak, dengan `native`
dikeluarkan karena itu jumlah provider internal (ditambahkan
terpisah oleh endpoint). Field `basis` menyebut angka mana yang dipakai
supaya tidak pernah disalahartikan.

Angka hasil fallback = **29558**, persis sama dengan "All (29.558)"
yang dilihat user di tab UI. Dua sumber yang tidak saling tahu
menghasilkan angka yang sama, jadi ini cross-check yang baik.

Sesi tanpa `dedup_canonical.json` diuji langsung:

```
no-canonical -> {"total": 29558, "executable": 23,
                 "metadata_only": 29535, "basis": "source_counts"}
```

## Test

```
pytest tests/test_mcp_recommendations.py tests/test_mcp_registry.py
  15 passed
pytest tests/ -k "registry or glama or mcp"
  78 passed, 265 deselected
```

## Catatan untuk sesi berikutnya

Dua token di `.env` (`RAILWAY_TOKEN`, `RAILWAY_API_TOKEN`) tidak
berhak memicu deploy. `deploymentTriggerCreate` membalas
`Not Authorized` untuk keduanya. Yang berhasil adalah
`serviceInstanceRedeploy` lewat skrip yang sudah ada:

```
python _railway_deploy_check.py --apply
```

Skrip itu juga melaporkan apakah deploy sudah lebih baru dari commit
tanpa perlu `--apply` — artinya push ke `main` sebenarnya sudah
memicu build otomatis.
