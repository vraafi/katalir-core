# DIAGNOSA BACKEND KATALIR — 11 Oktober 2026

> Gejala yang dilaporkan: chat di `katalir.de5.net` **gagal kirim prompt**
> ("Failed to send — Koneksi lambat. Cek internetmu."), riwayat chat kosong
> ("No chats yet"), prompt panjang stuck, tombol "Try again" muncul.
>
> Metode: **bukti mentah dulu, fix belakangan.** Tidak ada asumsi di bawah ini
> yang tidak punya perintah + output pendampingnya.

---

## RINGKASAN EKSEKUTIF

**Root cause tunggal: frontend produksi masih menunjuk backend Railway yang
sudah MATI.** Backend VPS, tunnel, Supabase, dan LLM gateway semuanya SEHAT.

Bukti paling langsung — string di bundle produksi yang benar-benar diunduh
browser dari `katalir.de5.net`:

```console
$ curl -sS -A "Mozilla/5.0" https://katalir.de5.net/chat -o chat.html
$ grep -oE '/_next/static/chunks/5360-[a-z0-9]+\.js' chat.html
/_next/static/chunks/5360-10f55fb5d915b6a0.js      <-- DEPLOY LAMA

$ curl -sS "https://katalir.de5.net/_next/static/chunks/5360-10f55fb5d915b6a0.js" \
    | grep -o '.\{40\}railway\.app.\{20\}'
>f.abort(),o);try{return await fetch("".concat("https://web-production-dc90b.up.railway.app").concat(e),{...c,headers:m,signal:f.si
```

Sedangkan build LOKAL (sudah benar) berisi:

```console
$ grep -rl "gateway.katalir" nexus-frontend/out/_next/static/chunks/*.js
nexus-frontend/out/_next/static/chunks/5360-36d85060d46c8f08.js

$ grep -o '.\{30\}gateway\.katalir[a-z0-9./-]*' nexus-frontend/out/_next/static/chunks/5360-36d85060d46c8f08.js
try{return await fetch("".concat("https://gateway.katalir.de5.net/katalir-api").concat(e)
```

Hash chunk berbeda (`...10f55fb5...` vs `...36d85060...`) = **isi berbeda** =
deploy ketinggalan satu build. Frontend yang benar sudah ada di disk sejak
`2026-10-11 02:17`, tetapi **tidak pernah di-upload** ke Cloudflare Pages.

### Mengapa gejalanya persis "Koneksi lambat. Cek internetmu."

Railway hidup sebagai edge, tapi app-nya mati → balas 404 **tanpa header CORS**:

```console
$ curl -sS -D - -o /dev/null -H "Origin: https://katalir.de5.net" \
    https://web-production-dc90b.up.railway.app/sessions
HTTP/1.1 404 Not Found
Cache-Control: public, max-age=5
Content-Type: application/json
Server: railway-hikari
x-railway-fallback: true
   <-- TIDAK ADA Access-Control-Allow-Origin
```

Tanpa `Access-Control-Allow-Origin`, browser **membuang respons** dan `fetch`
melempar `TypeError` — bukan HTTP error. Di `nexus-frontend/src/lib/api.ts:37`:

```ts
if (e && e.name === "TypeError") {
  // fetch network failure (offline / DNS / reset)
  return { message: "Koneksi lambat. Cek internetmu.", retryable: true };
}
```

→ Pesan itulah yang muncul di UI, dan tombol "Try again" (`retryable: true`).
Karena `/sessions` juga menuju Railway yang sama, sidebar riwayat ikut kosong
("No chats yet") walau di Supabase ada **662 sesi**.

---

## TABEL DIAGNOSA (9 CEK)

| # | Cek | Status | Bukti (ringkas) | Root Cause |
|---|-----|--------|-----------------|------------|
| 1 | Backend health | ✅ | `GET /katalir-api/health` → **200**, `persistence: persisted / supabase`, t=2.10s | — |
| 2 | VPS status | ✅ | `katalir-backend.service` **active (running)** 15 jam; `journalctl … grep -i error` → **0 baris**; RAM 1.4 GB tersedia; disk 30% | — |
| 3 | Tunnel | ✅ | `cloudflared` active; 4 koneksi terdaftar (`ord08`,`ord15`,`ord02`,`ord11`); sempat QUIC timeout 20:08 lalu **reconnect sendiri** | — |
| 4 | Supabase | ✅ | service key: `users=126`, `chat_sessions=662`, `chat_messages=2056`; kolom `chat_sessions.user_id`, `chat_messages.session_id` ada | — |
| 5 | LLM gateway | ✅ | `/v1/models` → **200** (12 model, 0.09s); `/v1/chat/completions` → **200** `content:"OK"` (0.80s) | — |
| 6 | **Frontend URL** | ❌ | bundle produksi memanggil `web-production-dc90b.up.railway.app` (404) | **DEPLOY BASI — AKAR MASALAH** |
| 7 | CORS | ✅ | preflight `/chat` → 200, `access-control-allow-origin: https://katalir.de5.net` | — |
| 8 | Chat endpoint | ✅ | `POST /chat` → **200** t=10.14s, `reply:"HALO-E2E"`, `session_id` dibuat | — |
| 9 | Chat persist | ✅ | `chat_messages` +2 baris (user+assistant); sesi baru terlihat di `GET /sessions` | — |

**Catatan penting #6:** cek 1–5, 7–9 dijalankan terhadap backend VPS yang
BENAR. Artinya, kalau frontend menunjuk ke sana, semuanya sudah bekerja —
dibuktikan di cek 8/9 sebelum ada satu pun perubahan kode backend.

---

## RAW OUTPUT PER CEK

### 1.1 Backend health (publik, lewat tunnel)

```console
$ curl -sS -o /tmp/h.txt -w "status=%{http_code} time_total=%{time_total}s time_connect=%{time_connect}s\n" \
    --max-time 30 https://gateway.katalir.de5.net/katalir-api/health
status=200 time_total=2.103826s time_connect=0.918473s
{"status":"ok","persistence":{"status":"persisted","backend":"supabase",
 "url":"https://qmukkphwaajzbqjrcvaz.supabase.co"},
 "build":{"commit":"unknown","branch":"unknown","service":"local",
 "environment":"local","deployment_id":"local","python":"3.12.3"}}
```

### 1.2 VPS

```console
$ ssh root@107.173.51.78 'uptime; systemctl status katalir-backend --no-pager | head -20; free -m; df -h /'
 10:20:34 up 76 days,  6:22,  3 users,  load average: 0.10, 0.05, 0.04
● katalir-backend.service - Katalir Backend API (FastAPI/uvicorn)
     Loaded: loaded (/etc/systemd/system/katalir-backend.service; enabled)
     Active: active (running) since Sat 2026-10-10 19:12:52 UTC; 15h ago
   Main PID: 293792 (python3)
     Memory: 251.9M (peak: 294.6M)
             └─293792 /root/katalir-core/venv/bin/python3 -m uvicorn _root_app:app --host 0.0.0.0 --port 8100
--- journalctl -u katalir-backend | grep -iE "error|traceback|exception" ---
(0 baris)
               total        used        free      shared  buff/cache   available
Mem:            2468        1007         186           2        1471        1461
/dev/vda2        43G   12G   29G  30% /
```

> Port asli = **8100** (bukan 8000 seperti di brief); mount `/katalir-api` ada di
> `_root_app.py`, sehingga `http://127.0.0.1:8100/health` memang **404** —
> jalur lokal yang benar adalah `http://127.0.0.1:8100/katalir-api/health`.

### 1.3 Tunnel

```console
$ systemctl is-active cloudflared
active
2026-10-10T20:08:30Z ERR failed to serve tunnel connection error="datagram manager encountered a failure while serving" connIndex=0
2026-10-10T20:08:38Z INF Registered tunnel connection connIndex=3 ... location=ord08 protocol=quic
2026-10-10T20:08:38Z INF Registered tunnel connection connIndex=1 ... location=ord15 protocol=quic
2026-10-10T20:08:38Z INF Registered tunnel connection connIndex=2 ... location=ord02 protocol=quic
2026-10-10T20:08:40Z INF Registered tunnel connection connIndex=0 ... location=ord11 protocol=quic
```

### 1.4 Supabase

```console
$ venv/bin/python3 /tmp/_vps_db2.py     # pakai _get_write_client() (service key)
[SERVICE SELECT users]          count=126  sample_rows=5
[SERVICE SELECT chat_sessions]  count=662  sample_rows=5
[SERVICE SELECT chat_messages]  count=2056 sample_rows=5
[COLUMN OK] chat_sessions.user_id -> 1 row
[COLUMN OK] chat_messages.session_id -> 1 row
[COLUMN OK] users.email -> 1 row
```

> Catatan metodologis: probe pertama memakai `_get_client()` (**anon key**) dan
> mengembalikan `count=0` untuk ketiga tabel. Itu **bukan** bukti tabel kosong —
> itu RLS memfilter anon. Diulang dengan service key → 126/662/2056. Probe yang
> salah key bisa menghasilkan kesimpulan "Supabase kosong" yang keliru.

### 1.5 LLM gateway

```console
$ venv/bin/python3 /tmp/_vps_probe.py     # dari VPS, base = Tailscale host
BASE = https://nexus-gateway-vps.tail7f0d5a.ts.net | key_len = 46 | n_models = 12
[models] status=200 t=0.09s body={"object":"list","data":[{"id":"llama-3.3-70b",...
[chat gemini-2.5-flash] status=200 t=0.80s
   body={"choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
         "usage":{"prompt_tokens":6,"completion_tokens":1,"total_tokens":25}}
```

> `/opt/gw-guard/proxy.py` memasang whitelist path: `ALLOW_PREFIXES = ("/v1/",)`,
> `ALLOW_EXACT = ("/v1", "/api/ping")`. Jadi `…/models` → `403 gw-guard: path
> tidak di-whitelist` (benar), sedangkan `…/v1/models` → 200. Ini bukan bug.

### 1.6 Frontend URL — **AKAR MASALAH**

```console
$ # bundle PRODUKSI
$ grep -o '.\{40\}railway\.app.\{20\}' 5360-10f55fb5d915b6a0.js
try{return await fetch("".concat("https://web-production-dc90b.up.railway.app").concat(e)

$ # build LOKAL
$ grep -o '.\{30\}gateway\.katalir[a-z0-9./-]*' nexus-frontend/out/_next/static/chunks/5360-36d85060d46c8f08.js
try{return await fetch("".concat("https://gateway.katalir.de5.net/katalir-api").concat(e)

$ # Railway benar-benar mati
$ curl -sS -o /dev/null -w "%{http_code}\n" https://web-production-dc90b.up.railway.app/health
404
$ nslookup web-production-dc90b.up.railway.app
Name:    web-production-dc90b.up.railway.app
Address:  69.46.46.26
```

### 1.7 CORS

```console
$ curl -sS -D - -o /dev/null -X OPTIONS https://gateway.katalir.de5.net/katalir-api/chat \
    -H "Origin: https://katalir.de5.net" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: authorization,content-type"
HTTP/1.1 200 OK
access-control-allow-credentials: true
access-control-allow-headers: authorization,content-type
access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
access-control-allow-origin: https://katalir.de5.net
access-control-max-age: 600

$ curl -sS -o /tmp/s.txt -w "status=%{http_code}\n" https://gateway.katalir.de5.net/katalir-api/sessions
status=401
{"detail":"Token wajib (Authorization: Bearer <jwt>)."}
```

### 1.8 + 1.9 Chat E2E + persistensi (JWT nyata, lewat URL publik)

User uji dibuat lewat Supabase Admin API, lalu sign-in password → JWT ES256:

```console
[admin create] 200 :: {"id":"af74a8cb-...","email":"e2e-diag-...@test.dev","email_confirmed_at":"2026-10-11T10:29:36Z"}
[signin] 200 jwt=OK len=810
[GET /sessions]    status=200 t=4.09s :: {"status":"success","sessions":[]}
[GET /models]      status=200 t=1.38s :: {"status":"success","tier":"free","default":"gemini-3.5-flash-lite",...}
[POST /chat]       status=200 t=10.14s :: {"status":"success","reply":"HALO-E2E",
                     "session_id":"5d1cfd6e-ec1a-4f50-8677-b9476d19f961",
                     "meta":{"requested_model":"gemini-2.5-flash","model":"gemini-3.5-flash-lite",
                             "latency_ms":696,"fallback":true,"fallback_reason":"model_unavailable"}}
[GET /sessions#2]  status=200 t=0.71s :: {"sessions":[{"id":"5d1cfd6e-...","title":"Balas persis: HALO-E2E"}]}
```

Persistensi di Supabase:

```console
[chat_messages utk session 5d1cfd6e-...] rows=2
    user      | Balas persis: HALO-E2E | 2026-10-11T10:29:48.933777+00:00
    assistant | HALO-E2E                | 2026-10-11T10:29:50.699284+00:00
[total chat_messages sekarang] 2058      (sebelum: 2056)
```

---

## TEMUAN SEKUNDER (bukan penyebab insiden, tapi perlu dicatat)

1. **Cloudflare error 1010 memblokir klien non-browser.** Request dari
   `Python-urllib` (UA default) ke URL publik dijawab `403 error code: 1010`.
   Ini Cloudflare Browser Integrity Check, **bukan** backend. Klien browser
   tidak terkena. Konsekuensi praktis: harness uji WAJIB memakai User-Agent
   browser, kalau tidak hasilnya 403 palsu.
   ```console
   [GET /sessions] status=403 t=0.24s body=error code: 1010      (UA: Python-urllib)
   [GET /sessions] status=200 t=4.09s                            (UA: Chrome)
   ```
2. **`SUPABASE_SECRET_KEY` (format baru `sb_secret_…`) ditolak Supabase Auth.**
   `POST /auth/v1/admin/users` → `401 {"message":"Forbidden use of secret API
   key in browser"}`. Kunci lama `SUPABASE_SERVICE_KEY` (JWT) → 200.
   `database.py:45` sudah memprioritaskan `SUPABASE_SERVICE_KEY` lalu
   `SUPABASE_SERVICE_ROLE_KEY` dan **tidak** memakai `SUPABASE_SECRET_KEY`,
   jadi produksi aman. Ini hanya jebakan bagi skrip/agent baru.
3. **`connect-src` CSP masih memuat host Railway yang mati.** Tidak menyebabkan
   insiden (browser tetap memblokir karena CORS), tapi menyesatkan. Dibersihkan
   di perbaikan.
4. **Fallback model.** `gemini-2.5-flash` tidak tersedia → fallback otomatis ke
   `gemini-3.5-flash-lite` (`fallback_reason: model_unavailable`). Perilaku ini
   by-design, bukan kegagalan.

---

## KESIMPULAN

Infrastruktur (VPS, tunnel, Supabase, LLM gateway, CORS) **semuanya sehat dan
sudah terbukti bekerja end-to-end** sebelum ada perubahan apa pun. Satu-satunya
cacat adalah **artefak deploy**: build frontend yang benar ada di disk, tetapi
yang tersaji ke pengguna adalah build lama yang menunjuk backend Railway yang
sudah mati. Perbaikannya ada di `docs/backend-recovery-2026-10-11.md`.
