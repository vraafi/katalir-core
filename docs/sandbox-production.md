# SANDBOX ↔ PRODUCTION — MENYAMBUNGKAN FITUR #6 KE JALUR EKSEKUSI

**Status:** ✅ TERSAMBUNG. Dua jalur, satu mesin sandbox.

| Jalur | Titik masuk | Untuk siapa | Berkas |
| --- | --- | --- | --- |
| Node `code` | `NodeKind.CODE` → `_exec_code` | pengguna Builder (drag & drop, editor kode) | `execution_engine.py` |
| Tool MCP `execute_code` | `svc_execute_code` | agen/LLM (Claude Desktop, klien MCP apa pun) | `mcp_server.py` |

Keduanya memanggil `code_sandbox.execute()` — **tidak ada** dua implementasi
isolasi yang perlu dijaga sinkron.

---

## 1. Masalah yang diperbaiki

`code_sandbox.py` sudah ada, sudah dikeraskan (tiga lapis pertahanan) dan sudah
lulus hard test — **tetapi tidak ada satu pun jalur eksekusi yang memanggilnya**.

Akibatnya `/version` melaporkan `06_code_sandbox: true` (modulnya bisa diimpor)
padahal tidak ada cara apa pun untuk menjalankan kode: tidak ada kind node,
tidak ada tool MCP, tidak ada UI. Laporan "fitur ada" itu benar secara teknis
dan menyesatkan secara praktis.

Perbaikan: menambahkan **dua** titik masuk yang memanggil mesin yang sudah ada,
bukan menulis sandbox baru.

---

## 2. Keputusan integrasi: Opsi C (Hybrid)

Tiga opsi dipertimbangkan:

- **A — hanya node `code`.** Terintegrasi Builder (drag & drop), tapi agen tidak
  bisa memakai sandbox sama sekali.
- **B — hanya tool MCP `execute_code`.** Agen bisa langsung memakai, tapi
  pengguna Builder tidak melihat apa pun di UI; tidak ada cara mengisi `code`
  lewat kanvas.
- **C — keduanya (DIPILIH).** Node untuk permukaan pengguna, tool untuk
  permukaan agen, keduanya di atas `code_sandbox.py` yang sama.

### Kenapa tidak mengadopsi E2B / Modal / gVisor / Firecracker

Kriteria pemilihan (dari brief): (1) production-ready (≥1.0, aktif dirawat);
(2) sudah ada di repo; (3) dapat diintegrasikan dengan mesin workflow yang ada;
(4) dukungan Python **dan** JavaScript; (5) batas memori/CPU/timeout/jaringan.

| Kandidat | Kriteria 2 (sudah di repo) | Kriteria 5 (batas ditegakkan) | Catatan |
| --- | --- | --- | --- |
| `code_sandbox.py` (repo) | ✅ ya | ✅ RLIMIT_AS / Job Object, timeout, no-network | **dipilih** |
| E2B | ❌ tidak | ✅ | microVM terkelola; kode user dikirim ke pihak ketiga + biaya |
| Modal Sandbox | ❌ tidak | ✅ | sama: kode user keluar dari jaringan kita |
| Firecracker langsung | ❌ tidak | ✅ | butuh KVM; Railway (produksi) tidak menyediakannya |

Prinsip yang dipakai: *"boleh data keluar dari jaringan kita?"* Kalau tidak
(dan di sini jawabannya tidak — ini fitur yang menjalankan kode milik pengguna),
maka self-host. Sandbox repo sudah menegakkan empat hal yang matriks 2026 sebut
wajib (memori, CPU/waktu, tanpa jaringan, tanpa filesystem), jadi mengadopsi
layanan pihak ketiga hanya akan menambah dependensi berbayar dan **menduplikasi
isolasi yang sudah terverifikasi**.

---

## 3. Batas yang ditegakkan (bukan saran)

Nilai-nilai ini ada di `code_sandbox.py` dan **dipaksa turun** ke cap, bukan
sekadar divalidasi:

| Batas | Nilai | Konstanta | Cara ditegakkan |
| --- | --- | --- | --- |
| Waktu | 30 s | `CODE_TIMEOUT_S` | `subprocess.communicate(timeout=)` → proses dibunuh |
| Memori | 128 MB | `CODE_MEMORY_MB` | Linux: `RLIMIT_AS`; Windows: Job Object + watchdog |
| Keluaran | 64 KB | `CODE_MAX_OUTPUT_BYTES` | dipotong, ditandai `dipotong` |
| Kode | 100 KB | `CODE_MAX_CODE_BYTES` | ditolak sebelum berjalan |
| Data workflow | 256 KB | `CODE_MAX_VARS_BYTES` | `SandboxError` |
| Impor modul | tidak ada | penjaga AST | `import` ditolak sebelum eksekusi |
| Jaringan / filesystem | tidak ada | penjaga AST | `socket`, `open`, `os` ditolak |

`timeout_s` dari node **dan** dari tool MCP di-clamp: `max(1, min(nilai, 30))`.
Menulis `timeout_s=600` menghasilkan eksekusi 30 detik, bukan error — dan itu
disengaja (permintaan yang tidak masuk akal tidak boleh mematikan alur).

---

## 4. Keputusan desain yang perlu dibaca sebelum mengubah kode

### 4.1 `{{...}}` TIDAK disubstitusi di dalam `config.code`

`_resolve_text` menyisipkan nilai string **apa adanya, tanpa kutip**. Kalau
substitusi placeholder diaktifkan di dalam kode, payload webhook (atau keluaran
LLM) berisi `"; __import__("os").system("rm -rf /") #` akan menjadi **teks
program** — data tak tepercaya menjadi kode yang dieksekusi.

Karena itu `_exec_code` sengaja **membuang** kunci `code` sebelum memanggil
`_resolve_cfg`, dan data workflow masuk sebagai **variabel**:

```python
# Python
result = input_data["input"]["nilai"] * 2

# JavaScript
result = input_data.input.nilai * 2;
```

Nama variabel **sama** di kedua bahasa (`VARS_NAME = "input_data"`) supaya
pengguna hanya perlu mengingat satu nama. Data disanitasi lewat JSON round-trip
(`sanitize_vars`) — nilai yang tidak bisa diserialisasi **dibuang**, bukan
diubah dengan `str()` (yang akan memanggil `__repr__` objek tak dikenal).

### 4.2 Awalan `"CodeExecutionError: "` di setiap pesan error

Self-healing mencocokkan **teks** pesan error (`self_healing.RULES`, aturan
pertama yang cocok menang). Pesan timeout sandbox berbunyi
`"... timeout: eksekusi dihentikan setelah 30s"` dan **mengandung kata
"timeout"** — yang cocok dengan aturan `network`. Tanpa perbaikan, satu
infinite loop akan **diulang 3×** (± 90 detik terbuang) padahal hasilnya pasti
sama.

Solusinya dua lapis:

1. Setiap `CodeExecutionError` dimulai dengan prefiks literal
   `"CodeExecutionError: "`.
2. `self_healing.RULES` mendapat aturan **paling awal**:

```python
Rule("code_execution", re.compile(r"CodeExecutionError"),
     "abort", max_attempts=0, search=False, reason="…")
```

`max_attempts=0` = jangan pernah coba lagi. Menjalankan ulang kode yang **sama**
tidak akan mengubah hasil; yang perlu diubah adalah `config.code`.

### 4.3 `asyncio.to_thread` di `_exec_code`

`code_sandbox.execute()` memblokir (subprocess + `communicate`). Memanggilnya
langsung di event loop akan membekukan **seluruh** API selama hingga 30 detik.
Karena itu eksekusi dijalankan di thread terpisah.

### 4.4 `print()`/`console.log()` masuk ke `stdout`; `result` adalah nilai balik

Runner internal mengirim hasil sebagai satu baris JSON di stdout. Sebelum
diperbaiki, `hasil["stdout"]` hanya ditimpa **jika** pengguna memanggil
`print()`. Kalau tidak, nilainya tetap baris JSON internal itu — dan sekarang
bocor ke UI karena node `code` merender `stdout`. Perbaikannya: penetapan
**tanpa syarat**.

---

## 5. Bug yang ditemukan saat menyambungkan (dan diperbaiki)

| # | Gejala | Akar masalah | Perbaikan |
| --- | --- | --- | --- |
| 1 | `NameError: name 'input_data' is not defined` | Python menyuntik data per-kunci, JavaScript memakai satu variabel kontainer; `_exec_code` mengirim dict → tidak ada kunci bernama `input_data` | Python menyuntik **satu** variabel `input_data` (sama dengan JS) |
| 2 | `stdout` berisi JSON internal saat pengguna tidak mencetak apa pun | penetapan `stdout` bersyarat (`if printed:`) | penetapan tanpa syarat |
| 3 | **Node `code` tampil sebagai kotak abu-abu bawaan React Flow** — tanpa kartu, tanpa Handle, tanpa `data-testid="node-card"` | `NODE_TYPES` (`nodes/index.ts`) tidak punya kunci `code`. React Flow **tidak melempar error** untuk `nodeTypes[kind]` yang tidak ada — ia diam-diam memakai node bawaannya | `code: CanvasNode` ditambahkan; dikunci oleh `tests/node-types.unit.spec.ts` (kesetaraan himpunan `META` ↔ `NODE_TYPES`) dan `tests/builder-code-node.spec.ts` test E2 |
| 4 | `cron_trigger` diam-diam menjadi `agent` | `kindOf` menulis ulang daftar kind tiga kali secara inline | daftar diturunkan dari `META` (`node-graph.ts`) |
| 5 | Node `cron_trigger` memakai token CSS yang tidak ada | `Palette.kindColorVar` menyalin ulang pemetaan `cssKind` | didelegasikan ke `cssKind` |
| 6 | **Panel konfigurasi desktop menutup sendiri begitu kolom APA PUN diisi** (nilainya tetap tersimpan, jadi yang rusak hanya visibilitas) | `Sheet` panel mobile dibuka `open={!!selectedNode}` di SEMUA lebar layar dan hanya disembunyikan `lg:hidden`. `display:none` tidak mengubah state Radix: `DismissableLayer` menutup dialog pada pointerdown/focus di luar `Content` → `onOpenChange(false)` → `setSelectedId(null)` | `open={!!selectedNode && sheetMobile}`, dengan `useSheetMobile()` (`matchMedia("(max-width: 1023px)")`) — breakpoint yang sama dengan `lg:hidden`. Dikunci oleh `tests/builder-code-node.spec.ts` F1/F2 (desktop) dan F3 (mobile tetap bekerja) |

Bug #3 adalah yang paling mahal: store sudah **benar** (id, `data.kind`, default
config semuanya ada) sehingga setiap pemeriksaan level-data lulus, sementara
yang salah hanya lapisan render. Tanpa tes UI, satu-satunya gejala adalah "node
tidak muncul" tanpa pesan error apa pun.

Bug #6 juga hanya bisa ditemukan lewat UI: **semua pemeriksaan level-data lulus**
nilai benar-benar tersimpan di store (dibuktikan probe: setelah memilih ulang
node, `timeout` terbaca `"12"`). Yang gagal hanya visibilitas panel — dan
akibatnya panel konfigurasi desktop tidak bisa dipakai mengedit sama sekali.
Cakupan tes lama tidak menangkapnya karena spec kanvas hanya *mengklik* node lalu
memeriksa panel muncul, tidak pernah *mengetik* ke dalamnya.

Bug #4 dan #5 tidak berhubungan dengan sandbox, tetapi ditemukan justru karena
menyambungkan node baru memaksa kedua fungsi itu dibaca ulang.

---

## 6. Batasan yang diketahui (jujur, tidak disembunyikan)

1. **RestrictedPython menolak nama variabel berawalan garis bawah.**
   `_x = 1` gagal dengan `"invalid variable name because it starts with '_'"`.
   Ini perilaku pustaka, bukan bug kita — tapi pengguna perlu tahu karena
   konvensi Python yang umum memakai `_` untuk variabel "buang".
2. **Tidak ada impor modul sama sekali** — termasuk `math`, `json`, `re`.
   Kebijakannya "nol impor", bukan "impor aman diizinkan". Aritmetika murni dan
   struktur data bawaan tetap bekerja. Kalau suatu saat impor dibutuhkan,
   daftar putih eksplisit harus ditambahkan **beserta** alasan per modul.
3. **Validasi statis JavaScript lebih longgar dari Python.** `import('fs')`
   dan `constructor.constructor` lolos penjaga pola, tetapi eksekusi nyata
   **0/11** berhasil (runtime menahan). Ini defence-in-depth, bukan celah aktif.

---

## 7. Bukti

- **`tests/test_sandbox_production.py`** — 58 tes (bagian A–H): registrasi node,
  injeksi data, integrasi alur, protokol MCP nyata, keamanan (20 vektor Python +
  11 vektor JS → 0 bocor), self-healing, `/version`, dan batas yang ditegakkan
  (timeout 30 s nyata, bom memori 2 GB → `MemoryError`, keluaran dipotong).
- **`tests/test_code_sandbox.py`** + **`tests/test_hard_test_fixes.py`** — suite
  sandbox lama tetap hijau setelah perubahan.
- **`tests/builder-code-node.spec.ts`** — UI: palette, node masuk kanvas, panel
  konfigurasi (bahasa/timeout/editor), token tema di 4 tema, screenshot.
- **`/version`** — blok `code_sandbox` (`enabled`, `languages`,
  `max_timeout_s`, `memory_limit_mb`, `memory_enforced`, `endpoints`) dan
  `mcp_tools` yang memuat `execute_code`.

---

## 8. Cara memakai

**Node `code` (Builder):** tarik node **Kode** dari palette → pilih bahasa
(Python 3 / JavaScript) → tulis kode → atur batas waktu (default 30 s). Data dari
node sebelumnya tersedia sebagai `input_data`. Tetapkan `result` untuk
mengembalikan nilai.

**Tool MCP:**

```jsonc
// tools/call
{ "name": "execute_code",
  "arguments": { "code": "result = 6 * 7", "language": "python", "timeout_s": 30 } }
```

```bash
# via HTTP (streamable MCP). Butuh header X-API-Key.
curl -sS -X POST "https://web-production-dc90b.up.railway.app/mcp/katalir/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $KATALIR_API_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"execute_code","arguments":{"code":"result = 6 * 7","language":"python"}}}'
```

Batas yang berlaku sama untuk kedua jalur: 30 s, 128 MB, 64 KB keluaran, tanpa
impor/jaringan/filesystem.
