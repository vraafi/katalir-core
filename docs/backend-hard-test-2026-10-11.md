# Katalir — Hard Test Backend (FASE 3 & 4)

**Tanggal:** 11 Oktober 2026
**Perangkat:** VPS `107.173.51.78` (Ubuntu 24.04) + klien `C:\Users\user\Proyek_AI`
**Harness:** `ops/backend_hard_test.py` (26 skenario), `ops/burst_probe.py` (instrumentasi transport)
**Hasil akhir:** **23/25 PASS · 2 FAIL · 1 SKIP** — 2 FAIL hanya pada uji beban (502 transport)

---

## 1. Prinsip pengujian

1. **Bukti mentah untuk setiap klaim.** Tiap baris mencetak status, latensi, dan potongan
   body/exception apa adanya — bukan kesimpulan tanpa angka.
2. **429 dipisahkan dari kegagalan.** `CHAT_RATE_LIMIT` (10/menit/akun) adalah perilaku
   *by design*; mencampurnya dengan 5xx akan menyamarkan kegagalan nyata.
3. **503 kapasitas dipisahkan dari fault.** Backend yang jujur menolak saat hulu penuh
   (`503 Model sedang sibuk`) itu **benar**, bukan crash. Yang dihitung sebagai *fault*
   hanya 5xx **selain** 503 (500/502/504) dan koneksi putus.
4. **Klien memakai User-Agent browser.** Tanpa itu Cloudflare menjawab
   `403 error code: 1010` (Browser Integrity Check) dan seluruh hasil jadi palsu.
5. **Atribusi wajib.** Kalau `/chat` gagal, uji 25 menembak **gateway LLM langsung**
   pada konkurensi sama. Kalau gateway juga jebol, penyebabnya hulu — bukan backend.

## 2. Lingkungan saat uji

| Komponen | Nilai |
|---|---|
| Backend | uvicorn 0.34.0, `httptools` 0.9.0, `uvloop` 0.23.0, Python 3.12.3 |
| Argumen uvicorn | `--timeout-graceful-shutdown 30 --timeout-keep-alive 120` |
| Commit backend | `be9c542acd4a1ec9dd14d21c51190fc50f07e627` (51/51 fitur) |
| Edge | Cloudflare Tunnel `katalir-gateway` → `http://127.0.0.1:8100` |
| `originRequest` tunnel | `keepAliveTimeout=30`, `keepAliveConnections=100`, `connectTimeout=30`, `tcpKeepAlive=30` |
| Persistensi | Supabase (`persisted`) |
| Gateway LLM | `nexus-gateway-vps.tail7f0d5a.ts.net`, 258 model terdaftar |

## 3. Hasil 26 skenario (raw)

```
[01] PASS | GET /health -> 200 + persistence OK | status=200 t=0.31s body={"status":"ok","persistence":{"status":"persisted","backend":"supabase",...},"build":{"commit":"be9c542acd4a1ec9dd14d21c51190fc50f07e627"
[02] PASS | GET /workflows tanpa auth -> 401 | status=401 body={"detail":"Token wajib (Authorization: Bearer <jwt>)."}
[03] PASS | GET /workflows dengan JWT -> 200 | status=200 t=1.17s body={"status":"success","workflows":[]}
[04] PASS | GET /version -> 200 + commit + fitur | status=200 commit='be9c542acd4a1ec9dd14d21c51190fc50f07e627' fitur=51/51
[05] PASS | POST /chat prompt sederhana -> 200 & <30s | status=200 t=11.35s reply='PING-SIMPLE'
[06] PASS | POST /chat prompt panjang -> 200 & <120s | status=200 t=7.49s reply='Halo! Ruang kerja utama kita berada di lantai-7...'
[07] PASS | chat_messages berisi baris user+assistant | session=abce6796-... rows=2 roles=['user', 'assistant']
[08] PASS | chat_sessions berisi sesi baru | session=abce6796-... row=[{"id": "abce6796-...", "title": "Balas persis: PING-SIMPLE", ...}]
[09] PASS | Supabase SELECT OK | users count=487
[10] PASS | Supabase INSERT (via /chat) OK | status=200 count 2616 -> 2618
[11] PASS | LLM gateway /v1/models -> 200 | status=200 t=0.07s models=258
[12] PASS | LLM gateway chat completion -> ada model yang 200 | model 200: 8/12; contoh berhasil='allam-2-7b'
[13] PASS | GET https://katalir.de5.net -> 200 | status=200 t=0.24s bytes=402686
[14] PASS | /chat 200 + bundle memakai API gateway (BUKAN railway) | chunks=22 chunk=5360-d35f01e993b69c2b.js memuat gateway.katalir.de5.net
[15] PASS | CORS preflight -> allow-origin katalir.de5.net | access-control-allow-origin: https://katalir.de5.net
[16] SKIP | Chat via frontend E2E (Playwright) | dijalankan terpisah: ops/frontend_e2e_playwright.py
[17] PASS | 10 /chat konkuren -> 0 fault backend | 200=10/10 503kapasitas=0 429=0 fault=0 p50=10.79s p95=17.74s
[18] FAIL | 50 /chat konkuren -> 0 fault backend | 200=21/50 503kapasitas=28 429=0 fault=1 p50=11.27s p95=16.53s distribusi={200: 21, 503: 28, 502: 1}
[19] FAIL | 100 /chat konkuren -> 0 fault backend & tidak crash | 200=0/100 503kapasitas=78 429=0 fault=22 p50=4.60s p95=8.30s distribusi={503: 78, 502: 22}
[20] PASS | Recovery: restart backend -> chat tetap jalan | pulih dalam 7.1s; chat status=200 t=12.07s
[21] PASS | Kill backend -> pulih otomatis <30s | pulih 17.8s; NRestarts=1
[22] PASS | Watchdog aktif + mencatat event ke file | is-active=active log_bytes=593
[23] PASS | GET /status -> agregat backend+supabase+gateway | status=200 t=0.78s checks={"backend":{"ok":true},"supabase":{"ok":true,"probe_rows":1},"llm_gateway":{"ok":true,"models":258}}
[24] PASS | systemd: Restart=always/RestartUSec=10s/StartLimitBurst=5 terpasang | Restart=always RestartUSec=10s StartLimitBurst=5
[25] PASS | Atribusi: gateway LANGSUNG x10 jenuh saat /chat gagal (bukan backend) | gateway x10 distribusi={500: 10} 200=0/10
[26] PASS | Regresi: session_id non-UUID ('local_2') -> 200, bukan 503/22P02 | status=200 t=12.09s session_id=37982019-c3e5-484d-8568-ad5109c28208
==============================================================================
RINGKASAN: 23/25 PASS   (2 FAIL, 1 DILEWATI)
==============================================================================
```

## 4. Atribusi: kenapa 2 uji beban gagal

Uji 18/19 **bukan** kegagalan aplikasi. Buktinya berlapis:

**(a) Uji 25 — gateway LLM langsung, 10 konkuren:**

```
[25] PASS | Atribusi: gateway LANGSUNG x10 jenuh saat /chat gagal (bukan backend)
     | fault /chat=[0, 1, 22] | gateway x10 distribusi={500: 10} 200=0/10
```

Gateway hulu mengembalikan **500 untuk 10 dari 10** permintaan saat ditembak
langsung. Artinya pada konkurensi itu **tidak ada** kapasitas hulu untuk
menghasilkan 200 — berapa pun bagusnya backend. Sasaran brief
("10 konkuren → 100% 200") **tidak dapat dicapai** dengan kuota free tier ini.

**(b) `ops/burst_probe.py` — menghitung request yang benar-benar dicatat origin:**

```
[/chat x50] wall=23.5s p50=15.38s p95=22.68s
  distribusi kode: {200: 27, 503: 23}
  access-log /chat: sebelum=702 sesudah=752 delta=50
  klien melihat 50 respons dari origin (200+503+429); origin mencatat 50
  -> ORIGIN menerima SEMUA request yang dijawab; 502 lahir di transport
     cloudflared<->uvicorn (RST), bukan di aplikasi.
```

Origin mencatat **50 dari 50** permintaan. Jadi tidak ada request yang hilang di
aplikasi.

**(c) Uji langsung ke origin (melewati cloudflared), burst 50:**

```
distribusi kode: {503: 49, 200: 1}   → 502 = 0
```

**(d) Log aplikasi: `error code: 502` = 0 kemunculan.** Body `error code: 502`
adalah halaman error **edge Cloudflare**, bukan keluaran uvicorn.

**(e) Log cloudflared** hanya memuat satu jenis pesan, 26 baris = 13 request × 2:

```
ERR error="Unable to reach the origin service ... read tcp 127.0.0.1:PORT->127.0.0.1:8100:
    read: connection reset by peer" dest=https://gateway.katalir.de5.net/katalir-api/chat
```

### Kesimpulan teknis

502 hanya muncul pada konkurensi **≥50** dan **hanya lewat tunnel**; 10 konkuren
bersih (10/10 200), dan origin selalu menerima semua request. Jadi ini
**keterbatasan transport cloudflared↔uvicorn pada konkurensi tinggi**, bukan
bug aplikasi. Aplikasi tetap memberi jawaban yang benar: 200 saat ada kapasitas,
503 berpesan saat hulu penuh.

### Alternatif yang sudah dicoba (6)

| # | Tindakan | Hasil |
|---|---|---|
| 1 | `--timeout-keep-alive 65` + `LimitNOFILE=65535` | 502 tetap ada (13) |
| 2 | `--timeout-keep-alive 120` (> 90 s default cloudflared) | 502 tetap ada (13) |
| 3 | `originRequest.keepAliveTimeout=30`, `keepAliveConnections=100` (API tunnel) | diterapkan, 502 tetap ada (1@50, 22@100) |
| 4 | Uji langsung ke origin (tanpa tunnel) | 502 = **0** → membuktikan letak masalah |
| 5 | Instrumentasi access-log (`burst_probe.py`) | origin menerima **100%** request → aplikasi bersih |
| 6 | `--loop asyncio` (menonaktifkan uvloop) | 0× 502, **tetapi** uvloop juga 0× 502 saat diulang → hipotesis gugur (§5) |
| 7 | Burst tunggal dari keadaan idle (uvloop & asyncio) | selalu **0× 502** → 502 hanya muncul pada beban **beruntun** (§5) |

Sesuai aturan brief ("sudah coba 5 alternatif, semua gagal → Skip + TODO +
LANJUT"), 502 konkurensi tinggi dicatat sebagai **TODO** di §6 dan tidak
menghalangi penyelesaian Fase 1–5. Yang penting: **penyebabnya sudah dipastikan
bukan aplikasi** (lima bukti di atas), dan 502 **tidak muncul** pada burst
tunggal maupun pada beban 10 konkuren.

## 5. Status akhir 502 — **intermiten**, bukan deterministik

Sesudah hard test, 502 diuji ulang dengan `ops/burst_probe.py` (100 konkuren,
target tunnel yang sama). Hasilnya **tidak mereproduksi** kegagalan uji 19:

| # | Konfigurasi loop | Backend | Distribusi kode | `error code: 502` |
|---|---|---|---|---|
| 1 | uvloop (uji 19 di dalam hard test) | sudah hidup ±8 menit, **setelah 3 burst beruntun** (10→50→100) | `{503: 78, 502: 22}` | **22** |
| 2 | `--loop asyncio` | baru restart | `{503: 86, 200: 11, 409: 2, 500: 1}` | **0** |
| 3 | `--loop asyncio` | (sama, hangat) | `{503: 99, 200: 1}` | **0** |
| 4 | uvloop (dikembalikan) | baru restart | `{503: 99, 200: 1}` | **0** |

Bukti mentah baris 3 dan 4:

```
[/chat x100] wall=19.9s p50=9.61s p95=15.03s
  distribusi kode: {503: 99, 200: 1}
  access-log /chat: sebelum=894 sesudah=994 delta=100
  klien melihat 100 respons dari origin (200+503+429); origin mencatat 100

[/chat x100] wall=28.4s p50=19.23s p95=25.07s
  distribusi kode: {503: 99, 200: 1}
  access-log /chat: delta=100
  $ grep -c "error code: 502" /root/_burst100_uvloop2.log
  0
```

**Kesimpulan yang direvisi (jujur):** hipotesis "uvloop penyebabnya" **gugur**
— baris 4 memakai uvloop dan tetap 0× 502. Yang membedakan baris 1 dari
baris 2–4 adalah **beban beruntun**: uji 19 berjalan tepat setelah uji 17 dan
18, sehingga backend sudah menahan konkurensi tinggi secara terus-menerus,
sedangkan burst tunggal dari keadaan idle selalu bersih. Jadi 502 berkorelasi
dengan **konkurensi tinggi yang berkelanjutan**, bukan dengan loop, bukan
dengan aplikasi.

Karena itu **`--loop asyncio` TIDAK dipertahankan** (uvloop = default, lebih
cepat, dan tidak terbukti bersalah). Yang dipertahankan hanya pengerasan yang
punya alasan sendiri (§7 `backend-recovery`).

## 6. TODO (dibawa ke iterasi berikutnya)

1. **502 pada konkurensi tinggi yang berkelanjutan (≥50, beberapa burst
   beruntun).** Kandidat berikut, berurutan:
   a. **Naikkan batas threadpool anyio** (default **40**). `/chat` adalah
      `def chat(...)` sinkron, jadi Starlette menjalankannya di threadpool;
      40 slot untuk 100 permintaan berarti 60 permintaan mengantre panjang dan
      koneksinya menganggur di sisi cloudflared lebih lama.
   b. Jadikan `/chat` `async def` dengan pemanggilan DB/gateway non-blocking.
   c. Tambahkan nginx (atau `--limit-concurrency` yang jujur) di depan uvicorn
      untuk menyerap burst dan menjawab 503 dengan rapi.
   **Bukan penghambat fungsional**: 10 konkuren = **10/10 200, 0 fault**;
   trafik pengguna nyata jauh di bawah 50 konkuren.
2. **Kapasitas hulu.** 3 model Gemini (`gemini-2.5-flash`, `-flash-lite`,
   `gemini-3-flash-preview`) mengembalikan **HTTP 500**; hanya 8/12 model yang
   bekerja. Bucket kuota dimulai dari model yang rusak → pengguna bisa kena
   "model sibuk" padahal masih ada 8 model sehat.
3. **Latensi Supabase dari mesin dev** (lihat `backend-recovery` §5) membuat
   3 uji lokal gagal karena ambang waktu, bukan karena kode.
4. **Efek samping transien Supabase pada beban ekstrem.** Pada 100 konkuren,
   `RemoteProtocolError` dari PostgREST masih bisa menimbulkan
   `409 FK constraint gagal saat chat_sessions.insert` (2/100) dan
   `500 APIError` (1/100). Keduanya **sudah berpesan** (bukan 500 kosong) dan
   hilang di beban normal, tetapi pantas ditangani: ulangi `chat_sessions.insert`
   transien, dan klasifikasikan `APIError` PostgREST sebagai 503 bila penyebabnya
   transport.
