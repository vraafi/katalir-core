# Katalir — Laporan Pemulihan Backend (FASE 5)

**Tanggal:** 11 Oktober 2026
**Mode:** AUTONOMOUS + EVIDENCE-DRIVEN + HARD TEST GATE
**Standar acuan:** Oktober 2026 best practice
**Laporan pendamping:** `docs/diagnosis-2026-10-11.md` (Fase 1),
`docs/backend-hard-test-2026-10-11.md` (Fase 3/4)

---

## 1. Ringkasan

Keluhan awal: chat di `katalir.de5.net` **gagal mengirim prompt**
("Failed to send - Koneksi lambat. Cek internetmu."), riwayat chat kosong
("No chats yet"), prompt panjang macet, tombol "Try again" muncul.

Hasil diagnosa (Fase 1, sebelum ada perbaikan apa pun):

* Infrastruktur **sehat** — `/health` publik 200, VPS aktif, tunnel jalan,
  Supabase 126 user / 662 sesi / 2056 pesan, gateway LLM 258 model, CORS benar.
* **Defect #1 (akar keluhan utama):** bundle frontend yang **disajikan ke
  browser** masih memanggil backend **Railway yang sudah mati**
  (`web-production-dc90b.up.railway.app`). Railway menjawab 404 **tanpa**
  header `Access-Control-Allow-Origin`, sehingga browser membuang respons dan
  `fetch` melempar `TypeError`; `classifyChatError()` memetakan `TypeError`
  menjadi "Koneksi lambat. Cek internetmu." Persis gejala yang dilaporkan.

Setelah Fase 1 selesai, Fase 2 menemukan **tiga defect tambahan yang nyata**
(dua di antaranya tidak terlihat dari gejala awal, dan baru muncul saat diuji
konkuren):

* **Defect #2:** `session_id` non-UUID bocor ke kolom `uuid` Postgres → `22P02`
  → HTTP **503**.
* **Defect #3:** exception tak tertangani (gangguan transport PostgREST)
  lolos ke Starlette → HTTP **500 `Internal Server Error` tanpa `detail`**.
* **Defect #4:** balapan tulis kuota (SELECT-lalu-INSERT) → `23505
  duplicate key ... user_usage_pkey` → HTTP 500.

Semua defect diperbaiki, diverifikasi dengan bukti mentah, lalu diuji ulang
dengan hard test 26 skenario.

---

## 2. Tabel SEBELUM → SESUDAH (11 item)

| # | Item | SEBELUM | SESUDAH | Bukti mentah |
|---|------|---------|---------|--------------|
| 1 | Endpoint `/health` backend | 200 `persisted/supabase` (sehat sejak awal) | 200 `persisted/supabase` | §3.1 |
| 2 | **Bundle frontend → API URL** | Chunk produksi `5360-10f55fb5d915b6a0.js` memanggil `web-production-dc90b.up.railway.app` (404, tanpa CORS) → `TypeError` | Chunk `5360-d35f01e993b69c2b.js` memanggil `https://gateway.katalir.de5.net/katalir-api` | §3.2 |
| 3 | **CSP `connect-src`** | Memuat `https://web-production-dc90b.up.railway.app` (host mati) | Hanya `gateway.katalir.de5.net` + Supabase + Cloudflare Insights | §3.3 |
| 4 | **Timeout chat** (`CHAT_TIMEOUT_MS`) | `15e4` = **150 000 ms** (sisa margin 8 s dari anggaran 142 s) | `18e4` = **180 000 ms** | §3.4 |
| 5 | **Chat E2E (kirim prompt)** | Gagal: "Failed to send - Koneksi lambat. Cek internetmu." | Balasan nyata `333` muncul; 0 console error; 0 error CSP/CORS | §3.5 |
| 6 | **Riwayat chat (sidebar)** | Kosong ("No chats yet") — `/sessions` juga menuju Railway | Sesi muncul di sidebar dan **tetap ada setelah reload** | §3.6 |
| 7 | **`session_id` non-UUID** | `POST /chat {"session_id":"local_2"}` → **503** `chat_sessions.own_check [22P02]` | **200** (sesi baru UUID dibuat); `{"session_id":"<uuid acak>"}` tetap **403** | §3.7 |
| 8 | **Exception tak tertangani** | `/chat x10` → **10× 500 `Internal Server Error`** tanpa `detail` (71 `Exception in ASGI application`) | `/chat x10` → **10× 200**; 0 exception baru; gangguan transport → **503 berpesan** | §3.8 |
| 9 | **Balapan tulis kuota** | `23505 duplicate key ... user_usage_pkey` → 500 | UPSERT atomik (`ON CONFLICT email`); 0 kejadian | §3.9 |
| 10 | **Monitoring `/status`** | Tidak ada endpoint deep health | `/status` → 200 dengan 3 pemeriksaan (`backend`, `supabase`, `llm_gateway`) + 503 bila ada yang gagal | §3.10 |
| 11 | **Auto-recovery** | Tidak ada watchdog; unit systemd default | `Restart=always`, `RestartUSec=10s`, `StartLimitBurst=5`; watchdog 60 s → pulih **17,5 s** setelah `SIGKILL` | §3.11 |

Tambahan (di luar 11 baris): **penjaga konsistensi deploy**
`scripts/verify_deploy_consistency.py` — lihat §4.

---

## 3. Raw output per item

### 3.1 Endpoint `/health` (tidak pernah bermasalah)

```
$ curl -s -H "Host: gateway.katalir.de5.net" http://127.0.0.1:8100/katalir-api/health
HTTP 200
{"status":"ok","persistence":{"status":"persisted","backend":"supabase",
 "url":"https://qmukkphwaajzbqjrcvaz.supabase.co"},
 "build":{"commit":"be9c542acd4a1ec9dd14d21c51190fc50f07e627","python":"3.12.3"}}
```

Catatan: probe **wajib** mengirim `-H "Host: gateway.katalir.de5.net"`.
`ALLOWED_HOSTS` tidak memuat `127.0.0.1`, jadi tanpa header itu jawabannya
`400 Invalid host header` — dan itu **perilaku benar** (mitigasi
CVE-2026-48710), bukan bug. Kesalahan ini sempat membuat watchdog v1
melakukan restart palsu.

### 3.2 Bundle frontend → API URL

Chunk yang benar sudah ada di `out/`, tetapi **belum di-upload**:

```
$ curl -s https://katalir.de5.net/chat | grep -oE '/_next/static/chunks/5360-[a-f0-9]+\.js'
/_next/static/chunks/5360-10f55fb5d915b6a0.js      # build LAMA (Railway)

$ grep -oE "https://[a-z0-9.-]+\.(app|net)" nexus-frontend/out/_next/static/chunks/5360-*.js
https://gateway.katalir.de5.net                    # build BENAR (VPS)
```

Setelah `wrangler pages deploy out`:

```
$ curl -s https://katalir.de5.net/chat | grep -oE '/_next/static/chunks/5360-[a-f0-9]+\.js'
/_next/static/chunks/5360-d35f01e993b69c2b.js

$ curl -s https://katalir.de5.net/_next/static/chunks/5360-d35f01e993b69c2b.js \
    | grep -oE "https://[a-z0-9.-]+\.(app|net)" | sort -u
https://gateway.katalir.de5.net
```

**Catatan penting:** deploy pertama (commit `be9c542`) **belum cukup**. Guard
§4 kemudian membuktikan bahwa `_headers` produksi masih versi lama dan chunk
produksi masih membawa timeout lama — artinya perbaikan FASE 2 poin 3 & 4
**tidak pernah sampai ke produksi**. Deploy diulang setelah guard dibuat.

### 3.3 CSP `connect-src`

Sebelum (dibaca langsung dari respons produksi):

```
$ curl -s -D - -o /dev/null https://katalir.de5.net/ | grep -i content-security-policy
content-security-policy: ... connect-src 'self' https://gateway.katalir.de5.net
  https://web-production-dc90b.up.railway.app https://qmukkphwaajzbqjrcvaz.supabase.co
  wss://qmukkphwaajzbqjrcvaz.supabase.co https://cloudflareinsights.com
```

Sesudah:

```
$ curl -s -D - -o /dev/null https://katalir.de5.net/chat | grep -i content-security-policy
content-security-policy: ... connect-src 'self' https://gateway.katalir.de5.net
  https://qmukkphwaajzbqjrcvaz.supabase.co wss://qmukkphwaajzbqjrcvaz.supabase.co
  https://cloudflareinsights.com

$ curl -s -D - -o /dev/null https://katalir.de5.net/chat | grep -ci railway
0
```

### 3.4 Timeout chat

```
# SEBELUM (chunk produksi)
$ curl -s https://katalir.de5.net/_next/static/chunks/5360-36d85060d46c8f08.js \
    | grep -o "18e4\|15e4" | sort | uniq -c
      1 15e4          # 150000 ms

# SESUDAH (chunk produksi)
$ curl -s https://katalir.de5.net/_next/static/chunks/5360-d35f01e993b69c2b.js \
    | grep -o "18e4\|15e4" | sort | uniq -c
      1 18e4          # 180000 ms
```

Kedua chunk berukuran **6929 byte** dan sama-sama menyebut
`gateway.katalir.de5.net` — jadi satu-satunya perbedaan memang konstanta
timeout. Inilah bukti kuat bahwa perbaikan timeout tadinya tidak ter-deploy.

### 3.5 Chat E2E (Playwright, produksi)

Prompt yang dipakai: `"Berapa hasil 111+222? Balas HANYA angkanya."`
Jawaban yang diharapkan: `333` — kata yang **tidak ada** di prompt, sehingga
gema pesan user tidak bisa dihitung sebagai bukti palsu.

```
balasan muncul: True
riwayat setelah reload: True
console error/warning: 2   (keduanya warning preload CSS — benign)
request gagal: 2           (keduanya cdn-cgi/rum analitik Cloudflare — benign)
error CSP/CORS: 0
error-card: 0
```

Screenshot: `docs/chat-e2e-2-sukses.png` (balasan `333`, meta
`gemini-3.5-flash-lite · 0.7s`), `docs/chat-e2e-1-kosong.png` (sebelum),
`docs/chat-e2e-3-riwayat.png` (riwayat setelah reload).

### 3.6 Riwayat chat

Terlihat di `docs/chat-e2e-3-riwayat.png`: sidebar "Chat History" memuat sesi
yang sama setelah halaman dimuat ulang — artinya `/sessions` mengarah ke
backend yang benar dan datanya persisten di Supabase.

### 3.7 `session_id` non-UUID (`22P02` → 503)

**SEBELUM** (`ops/repro_uuid_bug.py`, di VPS):

```
[FAIL] K1 /chat session_id='local_2' (sintetis) -> HTTP 503:
   {"detail":"Supabase error saat chat_sessions.own_check [22P02]:
    {'message': 'invalid input syntax for type uuid: \"local_2\"',
     'code': '22P02', 'hint': None, 'details': None}."}
[FAIL] K2 /chat session_id='bukan-uuid' -> HTTP 503: ... 22P02 ...
[PASS] K3 /chat session_id=<uuid acak tak ada> -> HTTP 403
[PASS] K4 /chat tanpa session_id (baseline) -> HTTP 200
[PASS] K5 GET /messages/local_2 -> HTTP 200
[PASS] K6 DELETE /sessions/local_2 -> HTTP 404
RINGKASAN: 4/6 sesuai harapan; 2 FAIL
```

**SESUDAH:**

```
[PASS] K1 /chat session_id='local_2' (sintetis) -> HTTP 200:
   {"status":"success","reply":"OK","session_id":"fbb1d5a4-1655-4a64-a27c-cc99723c8c75",...}
[PASS] K2 /chat session_id='bukan-uuid' -> HTTP 200: {"status":"success","reply":"OK! ..."}
[PASS] K3 /chat session_id=<uuid acak tak ada> -> HTTP 403
[PASS] K4 /chat tanpa session_id (baseline) -> HTTP 200
[PASS] K5 GET /messages/local_2 -> HTTP 200
[PASS] K6 DELETE /sessions/local_2 -> HTTP 404
RINGKASAN: 6/6 sesuai harapan; 0 FAIL
```

Perubahan: `database._is_uuid()` (alias publik `database.is_uuid`) sebagai
penjaga di `add_message` / `rename_session` / `delete_session` /
`get_messages` / `get_last_assistant_reply`; id fallback memori
`create_session` diubah dari `"local_<n>"` menjadi UUID sah dan didaftarkan di
`_LSESS`; `api_server` mengabaikan `session_id` non-UUID dari klien.
Perilaku **403** untuk UUID milik user lain sengaja **dipertahankan** (K3).

### 3.8 Exception tak tertangani (500 tanpa `detail`)

**SEBELUM** (`/root/api_server.log`):

```
$ grep -c "Exception in ASGI application" /root/api_server.log
71
$ grep -oE "^[a-zA-Z_.]+(Error|Exception): .*" /root/api_server.log | sort | uniq -c | sort -rn | head
     58 httpx.RemoteProtocolError: Server disconnected
     58 httpcore.RemoteProtocolError: Server disconnected
      2 httpx.WriteError: EOF occurred in violation of protocol (_ssl.c:2417)
      2 httpx.RemoteProtocolError: <ConnectionTerminated error_code:1, last_stream_id:149 ...>
      1 postgrest.exceptions.APIError: {'message': 'duplicate key value violates unique
          constraint "user_usage_pkey"', 'code': '23505', ...}
```

Jalur bocornya teridentifikasi tepat: `db.check_quota(...)` di endpoint
`/chat` **tidak berada di dalam `try/except` mana pun**, sehingga kegagalan
tulis kuota naik sampai Starlette → body teks polos `Internal Server Error`.

```
$ ops/diag_concurrency.py 10        # SEBELUM
[/chat x10] wall=2.9s p50=2.85s
  distribusi kode: {500: 10}
  GAGAL kode=500 t=2.92s body=Internal Server Error
  ... (10x)
[gateway langsung x10] wall=0.2s distribusi kode: {200: 2, 500: 8}
```

**SESUDAH:**

```
$ ops/diag_concurrency.py 10        # SESUDAH
[/chat x10] wall=14.0s p50=13.18s
  distribusi kode: {200: 10}
[gateway langsung x10] wall=0.2s distribusi kode: {500: 10}
  GAGAL kode=500 t=0.14s body=Internal Server Error
  ... (10x)

=== baris log BARU sejak marker ===
0
(0 = tidak ada exception baru)
```

Perhatikan: **gateway hulu tetap 100% gagal** (`{500: 10}`) untuk model
pertama, tetapi `/chat` sekarang **10/10 berhasil** karena rantai fallback
backend bekerja, dan tidak ada satu pun exception baru di log.

Perubahan: `_wrap_write(..., retry_transient=True)` (ulang sekali untuk
gangguan transport pada operasi idempoten) + handler global
`@app.exception_handler(Exception)` yang memetakan gangguan transport →
**503 berpesan** dan exception lain → **500 berpesan** (tidak pernah hampa).

### 3.9 Balapan tulis kuota (`23505`)

```
postgrest.exceptions.APIError: {'message': 'duplicate key value violates unique
 constraint "user_usage_pkey"', 'code': '23505',
 'details': 'Key (email)=(hardtest-load9-1791715185-6fac73@test.dev) already exists.'}
```

Penyebab: `_quota_write` melakukan `SELECT` lalu `INSERT`/`UPDATE` (TOCTOU).
Dua request bersamaan untuk user yang belum punya baris sama-sama `SELECT`
kosong lalu sama-sama `INSERT`.

Perbaikan: `UPSERT` atomik (`.upsert(payload, on_conflict="email")`) dengan
jalur manual sebagai cadangan, dan `23505` pada jalur cadangan
diperlakukan sebagai balapan → `UPDATE`, bukan kegagalan. Setelah perbaikan:
**0 kejadian** `23505` di log.

### 3.10 Monitoring `/status` (deep health)

```
$ curl -s -H "Host: gateway.katalir.de5.net" http://127.0.0.1:8100/katalir-api/status
HTTP 200
{"status":"ok","checked_in_ms":735,"checks":{
  "backend":{"ok":true,"detail":"handler menjawab"},
  "supabase":{"ok":true,"detail":{"backend":"supabase","probe_rows":1}},
  "llm_gateway":{"ok":true,"detail":{"status":200,"models":258}}},
 "build":{"commit":"be9c542acd4a1ec9dd14d21c51190fc50f07e627","python":"3.12.3"}}
```

Pembagian peran (best practice Oktober 2026): `/health` = **liveness murah**
(tidak menyentuh jaringan, supaya gateway yang lambat tidak memicu
restart-loop), `/status` = **readiness** dengan timeout keras per dependensi
dan HTTP 503 bila ada pemeriksaan yang gagal.

### 3.11 Auto-recovery

```
$ systemctl show katalir-backend -p Restart -p RestartUSec -p StartLimitBurst
Restart=always
RestartUSec=10s
StartLimitBurst=5
```

Uji bunuh proses (hard test #21):

```
[21] PASS | Kill backend -> pulih otomatis <30s | pulih 17.5s; NRestarts=1
[22] PASS | Watchdog aktif + mencatat event ke file | is-active=active log_bytes=217
```

Catatan: nama property systemd adalah **`RestartUSec`**, bukan `RestartSec`
(yang merupakan nama direktif di berkas unit). `systemctl show -p RestartSec`
mengembalikan **kosong** — versi pertama uji ini gagal palsu karena itu.
Selain itu `StartLimitBurst`/`StartLimitIntervalSec` **wajib** di `[Unit]`,
bukan `[Service]` (kalau tidak, systemd mengabaikannya dengan peringatan).

---

## 4. Penjaga konsistensi deploy (defect #5 yang ditemukan sendiri)

Karena defect #1 adalah "build benar tapi tidak di-deploy", ditambahkan
`scripts/verify_deploy_consistency.py`. Dijalankan **sebelum** deploy, ia
langsung menemukan bahwa produksi masih tidak konsisten:

```
$ python scripts/verify_deploy_consistency.py
  GET /        HTTP 200  chunk direferensikan: 17
  GET /chat    HTTP 200  chunk direferensikan: 22
A. membandingkan 23 chunk produksi dengan `out/`...
   22/23 chunk identik byte-per-byte
B/C. memeriksa host backend di bundle produksi...
   host aktif gateway.katalir.de5.net: TIDAK DITEMUKAN
   host mati: tidak ada
D. memeriksa CSP yang benar-benar dikirim...
   connect-src memuat gateway.katalir.de5.net: ya
HASIL: DRIFT TERDETEKSI — 4 masalah
  - /_next/static/chunks/5360-36d85060d46c8f08.js: ADA di produksi tapi TIDAK ADA di out/
  - tidak ada chunk produksi yang menyebut host AKTIF gateway.katalir.de5.net
  - CSP masih memuat host mati web-production-dc90b.up.railway.app
  - CSP masih memuat host mati railway.app
```

Setelah deploy ulang:

```
$ python scripts/verify_deploy_consistency.py
  GET /        HTTP 200  chunk direferensikan: 17
  GET /chat    HTTP 200  chunk direferensikan: 22
A. membandingkan 23 chunk produksi dengan `out/`...
   23/23 chunk identik byte-per-byte
B/C. memeriksa host backend di bundle produksi...
   host aktif gateway.katalir.de5.net: DITEMUKAN
   host mati: tidak ada
D. memeriksa CSP yang benar-benar dikirim...
   connect-src memuat gateway.katalir.de5.net: ya
HASIL: KONSISTEN — produksi == out/ (chunk, host backend, CSP)
  chunk identik: 23/23
```

Guard ini juga **memperbaiki bug logikanya sendiri**: versi pertama
melewati pemeriksaan host ketika berkas lokal tidak ada (`continue` terlalu
dini), sehingga chunk yang belum ter-deploy justru lolos dari pemeriksaan
host — persis kasus yang harus ditangkap.

---

## 5. Regresi test suite (lokal)

Suite penuh dijalankan setelah semua perbaikan (kondisi mesin saat itu sedang
dibebani uji beban paralel):

```
$ python -m pytest tests/ -q
6 failed, 2315 passed, 20 warnings, 2 errors, 42 subtests passed in 2416.82s (0:40:16)

FAILED tests/test_agent_memory.py::test_2c7_recall_performance
FAILED tests/test_agent_memory.py::test_2c8_scale_1000_memories
FAILED tests/test_agents.py::test_p1_buat_200_agent_cepat
FAILED tests/test_durable_execution.py::test_14_performa_checkpoint
FAILED tests/test_parallel_fanout.py::test_06_timeout_per_cabang_tidak_batalkan_saudara
FAILED tests/test_parallel_fanout.py::test_12_performa_paralel_vs_seri
ERROR  tests/test_durable_execution.py::test_07_idempotency_kunci_sama        (psycopg2.OperationalError)
ERROR  tests/test_parallel_fanout.py::test_11_isolasi_antar_user             (psycopg2.OperationalError)
```

**Kedelapan kegagalan itu artefak lingkungan, bukan regresi.** Bukti:

1. **8 test yang sama dijalankan ulang terpisah → 5 lulus**, termasuk **kedua**
   `psycopg2.OperationalError`. Jadi error DB itu murni kehabisan koneksi
   pooler saat mesin dibebani.
2. **3 sisanya semuanya ambang latensi**, dan sumbernya terukur:
   ```
   $ python -c "<12x GET /rest/v1/users ke Supabase dari mesin dev>"
     #01  572.7 ms   #02  402.3 ms   #03  704.3 ms   #04  866.8 ms
     #05  482.9 ms   #06  165.9 ms   #07  151.6 ms   #08 1856.9 ms
     #09 1545.5 ms   #10  150.0 ms   #11  165.7 ms   #12 31836.4 ms (GAGAL)
     median REST Supabase (12x) = 528 ms   min=150 ms   max=31836 ms
     ambang test_2c7 = 200 ms -> GAGAL (lingkungan)
   ```
   Median **528 ms** (anggaran 200 ms) dengan lonjakan **31,8 detik** dan satu
   request gagal total. `test_2c7` mengukur median RPC Supabase dan gagal di
   **4,89 s**; `test_2c8` (1000 memori via RPC) dan `test_06` (fanout yang
   menulis ke Postgres di tiap cabang, 2,23 s vs ambang 2,0 s) mengikuti
   penyebab yang sama.
3. **Perubahan pada insiden ini tidak menyentuh kode yang diuji.**
   `git diff --name-only` = `api_server.py`, `database.py`,
   `ops/backend_hard_test.py`, `ops/katalir-backend.service`, dan 3 berkas test.
   **Tidak ada** perubahan pada `memory_manager.py` maupun `parallel_fanout.py`;
   fixture `svc` pada `test_agent_memory.py` adalah `db.get_write_client()` —
   klien Supabase mentah, jadi assertion-nya murni mengukur jaringan.

Test baru yang mengunci perbaikan:

| Berkas | Isi |
|--------|-----|
| `tests/test_session_id_uuid_guard.py` | 14 test — `is_uuid`, fallback UUID, semua jalur DB menolak id non-UUID tanpa menyentuh Postgres |
| `tests/test_unhandled_exception_contract.py` | 3 test — transport → 503 berpesan; bug biasa → 500 berpesan; `HTTPException` tidak tertelan |

Test lama yang **diperbarui** (bukan dihapus) karena mengunci asumsi keliru:

| Berkas | Alasan |
|--------|--------|
| `tests/test_csp_headers.py::test_host_lama_tidak_hilang` → `test_host_backend_aktif_tidak_hilang` | Versi lama **menuntut** host Railway yang sudah mati tetap ada di `connect-src` — asumsi itu justru mengunci regresi dan gagal saat bug-nya diperbaiki |
| `tests/test_chat_retry_no_data_loss.py` | Fixture memakai `session_id` sintetis (`"s1"`, `"sess-1"`) sehingga setelah penjaga UUID terpasang ia menguji jalur memori, bukan jalur yang dimaksud. Fixture diganti UUID sah; invarian (dedup, filter `client_request_id`) tidak berubah |
| `tests/test_daily_quota.py` | Klien tiruan diberi `upsert()` supaya kontrak "datetime → string ISO" diuji di jalur yang sekarang benar-benar dipakai produksi |

---

## 6. Sisa risiko (jujur, tidak disembunyikan)

1. **Kapasitas hulu LLM = plafon sebenarnya.** Gateway gratis saat ini
   menjawab **500** untuk ketiga model Gemini dan hanya ~11/212 kandidat
   roster yang lulus. Backend sudah tidak lagi menjatuhkan request karena ini
   (fallback bekerja), tetapi **latensi naik** (p50 13,2 s pada 10 konkuren)
   dan pada konkurensi sangat tinggi request akan ditolak dengan **503
   kapasitas** — perilaku yang benar, tetapi tetap berarti kapasitas terbatas.
   Perbaikan sesungguhnya bersifat operasional: kunci/provider berbayar.
2. **Model pertama di `LLM_GATEWAY_MODELS` rusak** (`gemini-2.5-flash` → 500).
   Ini konfigurasi operasional, belum diubah karena mengubahnya mengubah
   perilaku fallback produksi dan butuh keputusan pemilik produk.
3. **502 pada konkurensi ≥50 lewat Cloudflare Tunnel.** Ditemukan oleh hard test
   Fase 3 (uji 18: 1× 502; uji 19: 22× 502 pada 100 konkuren). **Bukan bug
   aplikasi** — dibuktikan berlapis di `docs/backend-hard-test-2026-10-11.md` §4:
   origin mencatat **100%** request (instrumentasi access-log), uji langsung ke
   origin tanpa tunnel memberi **0× 502**, log aplikasi memuat **0** kemunculan
   `error code: 502`, dan uji 25 membuktikan hulu memang sudah jenuh
   (gateway langsung 10 konkuren → `{500: 10}`, 0/10 sukses).
   6 alternatif sudah dicoba (`--timeout-keep-alive` 65 lalu 120, `LimitNOFILE`,
   `originRequest.keepAliveTimeout=30`/`keepAliveConnections=100` lewat API
   tunnel, uji langsung ke origin, instrumentasi access-log) tanpa menghilangkan
   502 pada konkurensi tinggi. Sesuai aturan brief, dicatat sebagai TODO.
   **Dampak nyata kecil**: 10 konkuren = **10/10 200, 0 fault**, dan trafik
   pengguna nyata jauh di bawah 50 konkuren.
4. **`/vault` → 404** dan `javascript_available: false` di sandbox
   (kondisi yang sudah ada sebelumnya, tidak terkait insiden ini).

---

## 7. Pengerasan yang diterapkan (di luar perbaikan insiden)

| Perubahan | Nilai | Alasan |
|---|---|---|
| `ops/katalir-backend.service` | `Restart=always`, `RestartUSec=10s`, `StartLimitBurst=5`, `LimitNOFILE=65535`, `--timeout-keep-alive 120`, `--timeout-graceful-shutdown 30` | auto-recovery + keep-alive origin lebih panjang dari cloudflared (default 90 s) supaya origin tidak pernah menutup koneksi yang masih dipakai edge |
| `originRequest` tunnel (API Cloudflare, bukan dashboard) | `keepAliveTimeout=30`, `keepAliveConnections=100`, `connectTimeout=30`, `tcpKeepAlive=30`, `http2Origin=false` | sisi hulu selalu menutup koneksi idle lebih dulu; terverifikasi live (`cloudflared ... Updated to new configuration ... version=4`) |
| `ops/cf_tunnel_config.py` (baru) | — | mengelola `originRequest` tunnel lewat API; **tidak pernah mencetak token**. Catatan: `/user/tokens/verify` menolak token akun (`cfat_…`) — itu normal, bukan tanda token tidak sah |
