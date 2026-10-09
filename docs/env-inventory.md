# INVENTORY `.env` — Katalir v2

> **Aturan:** dokumen ini HANYA memuat **NAMA variabel**. Tidak ada satu pun
> **nilai** rahasia yang ditulis, dicetak, atau dikomit. Untuk memverifikasi
> keberadaan kredensial, dipakai status `SET` (ada & non-kosong) / `EMPTY` /
> `ABSENT` beserta panjang string — **bukan isinya**.

## 1. Ringkasan hasil scan

| Berkas | Jumlah variabel | Catatan |
|---|---:|---|
| `.env` | 98 | sumber kebenaran runtime (dipakai server) |
| `.env.template` | 99 | template deploy (superset, ada `RAILWAY_akun`, `RAILWAY_projek`) |
| `.env.example` | 5 | contoh minimal |
| `nexus-frontend/.env.local` | 4 | env frontend |
| `nexus-frontend/.env.example` | 4 | contoh frontend |
| `gacha-purgatory/gameplay/.env` | 95 | proyek lain (tidak dipakai misi ini) |
| `tools/picgen-mcp/.env.example` | 2 | contoh MCP |
| **Total** | **307** | |

Berkas cadangan (`*.bak-*`, 6 buah) **tidak** dianalisis sebagai sumber aktif —
hanya arsip historis.

## 2. Kategorisasi variabel `.env` (nama saja)

### 2.1 LLM / Gateway
`GOOGLE_API_KEY` · `GEMINI_API_KEY` · `GEMINI_KEY_1`…`GEMINI_KEY_13` ·
`GROQ_API_KEY` · `NVIDIA_API_KEY` · `DEEPSEEK_API_KEY` · `OPENAI_API_KEY` ·
`ANTHROPIC_API_KEY` · `LLM_GATEWAY_URL` · `LLM_GATEWAY_KEY` ·
`LLM_GATEWAY_MODELS` · `NINEROUTER_KEY` · `NINEROUTER_EXTERNAL_URL` ·
`HYRVE_API_KEY` · `AGENTGATEWAY_URL` · `MCP_SDK` · `promptpilot_mcp` · `beatapi`

### 2.2 Auth / OAuth / Identity (→ **Fitur #7 SSO**)
`GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GITHUB_CLIENT_ID` ·
`GITHUB_CLIENT_SECRET` · `SLACK_APP_ID` · `SLACK_CLIENT_ID` ·
`SLACK_CLIENT_SECRET` · `SLACK_SIGNING_SECRET` · `SLACK_VERIFICATION_TOKEN`

### 2.3 Database / Backend (Supabase)
`SUPABASE_URL` · `SUPABASE_KEY` · `SUPABASE_PUBLISHABLE_KEY` ·
`SUPABASE_SERVICE_KEY` · `SUPABASE_SERVICE_ROLE_KEY` · `SUPABASE_SECRET_KEY` ·
`SUPABASE_DB_PASSWORD` · `SUPABASE_JWKS` · `PERSIST_REQUIRED`

### 2.4 Secrets / Integration providers (→ **Fitur #1 Secrets**)
`VAULT_PASSWORD` · `VAULT_SECRET_KEY` · `NANGO_API_KEY` · `METORIAL_API_KEY` ·
`COMPOSIO_API_KEY` · `COMPOSIO_API_KEY_consumer` · `GLAMA_API_KEY`

### 2.5 Version control (→ **Fitur #5 Git**)
`GITHUB_TOKEN` · `GITHUB_CLIENT_ID` · `GITHUB_CLIENT_SECRET`

### 2.6 Cloud / Infra / VPS (→ **Fitur #6 Queue**, **Fitur #10 Collab**)
`CLOUDFLARE_ACCOUNT_ID` · `CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_R2_ACCESS_KEY_ID` ·
`CLOUDFLARE_R2_SECRET_ACCESS_KEY` · `CLOUDFLARE_R2_ENDPOINT` · `RAILWAY_TOKEN` ·
`RAILWAY_API_TOKEN` · `VPS_IP` · `VPS_USERNAME` · `VPS_PASSWORD` · `VPS_OS` ·
`ALLOWED_HOSTS` · `CORS_ORIGIN`

### 2.7 Billing / Payment
`DODO_API_KEY` · `DODO_WEBHOOK_SECRET` · `DODO_CHECKOUT_URL` · `PAYMENT_PORTAL_URL`

### 2.8 Messaging / Notifikasi
`TELEGRAM_BOT_TOKEN` · `TELEGRAM_CHAT_ID` · `TELEGRAM_APP_API_ID` ·
`TELEGRAM_APP_API_HASH` · `WA_TOKEN` · `WA_PHONE_ID` · `WA_BUSINESS_ACCOUNT_ID` ·
`EMAIL_ADDRESS` · `EMAIL_APP_PASSWORD` · `EMAIL_IMAP_HOST` · `EMAIL_IMAP_PORT` ·
`EMAIL_CHECK_INTERVAL`

### 2.9 Browser / Scraping
`CLOAK_DEBUG_PORT` · `BRAVE_CDP_URL` · `BRAVE_PATH` · `IG_USERNAME` ·
`IG_PASSWORD` · `PHONE_NUMBER`

### 2.10 Media / Data / Game
`PEXELS_API_KEY` · `KAGGLE_API_TOKEN` · `ROBLOX_UNIVERSE_ID` · `ROBLOX_PLACE_ID` ·
`ROBLOX_OPEN_CLOUD_API_KEY` · `DNSHE_API_KEY` · `DNSHE_API_SECRET`

## 3. CHECKLIST INVENTORY — kredensial per fitur

| Fitur | Kredensial di `.env` | Status (nama saja) | Pakai? |
|---|---|---|---|
| **#1 Secrets** | `NANGO_API_KEY` | SET (len 36) — **valid, live** | ✅ **YA — provider utama** |
| | `METORIAL_API_KEY` | SET (len 124) — **valid, live** | ✅ **YA — provider MCP** |
| | `VAULT_PASSWORD`, `VAULT_SECRET_KEY` | SET (len 11, 44) | ✅ **YA — KatalirVault (Fernet)** |
| | `HASHICORP_*`, `AWS_*`, `ONEPASSWORD_*` | ABSENT | — (tidak dipakai; ada pengganti) |
| **#5 Git** | `GITHUB_TOKEN` | SET (len 40) — **valid: `login=vraafi`** | ✅ **YA** |
| | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | SET (len 20, 40) | ✅ (OAuth app) |
| **#6 Queue** | `VPS_IP`, `VPS_USERNAME`, `VPS_PASSWORD`, `VPS_OS` | SET — **SSH root OK, Ubuntu 24.04** | ✅ **YA — Redis di VPS** |
| | `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | **DIBUAT** (append ke `.env`) — Redis 7.0.15 terpasang di VPS, bind 127.0.0.1 + `requirepass`, diakses via tunnel SSH | ✅ **YA** |
| **#7 SSO** | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | SET (len 71, 35) — **pasangan client valid** | ✅ **YA — OIDC nyata** |
| | `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_JWKS` | SET | ✅ (Auth/JWKS) |
| | `OKTA_*`, `AUTH0_*` | ABSENT | — (tidak ada; Google+Supabase cukup) |
| **#10 Collab** | `VPS_*`, `AGENTGATEWAY_URL` | SET | ✅ **YA — WS di VPS** |
| | `SUPABASE_URL`, `SUPABASE_KEY` | SET | ✅ (JWT untuk auth WS) |
| | `WEBSOCKET_*` | ABSENT | — (dibuat sendiri) |

## 4. Bukti validasi kredensial NYATA (raw output, nilai di-redact)

Semua probe dijalankan dengan `ProxyHandler({})` (menghindari `HTTP_PROXY`
lokal) dan **tanpa** mencetak nilai rahasia.

### 4.1 GitHub — `GET https://api.github.com/user`
```
HTTP 200
{"login":"vraafi","id":209403877,"node_type":"User","html_url":"https://github.com/vraafi", ...}
```
→ `GITHUB_TOKEN` **valid**.

### 4.2 Google OIDC — `POST https://oauth2.googleapis.com/token` (code dummy)
```
HTTP 400
{"error":"invalid_grant","error_description":"Malformed auth code."}
```
→ Respons `invalid_grant` (bukan `invalid_client`) membuktikan
`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` adalah **pasangan client yang sah**;
hanya `code` yang sengaja dummy.

### 4.3 Nango — siklus hidup secret penuh
```
GET  /integrations                     -> HTTP 200
   {"data":[{"unique_key":"github-getting-started","provider":"github",
             "created_at":"2026-09-25T18:08:41.708Z"}, ...]}

POST /connections                       -> HTTP 201
   {"id":2664298,"connection_id":"katalir-verify-1",
    "provider_config_key":"github-getting-started","provider":"github","errors":[]}

GET  /connections?connectionId=...      -> HTTP 200
   {"connections":[{"id":2664298,"connection_id":"katalir-verify-1", ...}]}

DELETE /connections/katalir-verify-1    -> HTTP 200 {"success":true}
```
→ Nango **live**: store → retrieve → delete berhasil (token di-redact).

### 4.4 Metorial — `GET https://api.metorial.com/provider-deployments`
```
HTTP 200
{"object":"list","items":[{"object":"provider.deployment",
  "id":"pde_0mui33vb2eCetUfI9upu1G","status":"active",
  "name":"GitHub Integration Deployment", ...}]}
```
→ `METORIAL_API_KEY` **valid**. Catatan: endpoint butuh `User-Agent` browser,
jika tidak Cloudflare membalas `403 error code: 1010`.

### 4.5 VPS — SSH (paramiko, password auth)
```
whoami            -> root
uname -a          -> Linux ... 6.8.0-31-generic #31-Ubuntu SMP ... x86_64
command -v redis-server -> (kosong)  →  NO_REDIS
systemctl is-active redis-server -> inactive
ss -ltnp -> 127.0.0.1:3011 (agentgateway, python3), 127.0.0.1:8081, 127.0.0.1:8080, tailscaled:443
```
→ VPS **dapat diakses**; Redis **belum** terpasang → akan dipasang (Fitur #6).

## 5. Keputusan (web-first, Okt 2026)

| Topik | Sumber | Keputusan |
|---|---|---|
| Nango API auth & import connection | https://nango.dev/docs/reference/backend/http-api/connections/post | Pakai `POST /connections` (plural) — `raw` TIDAK boleh di body |
| Metorial API base & endpoint | https://metorial.com/docs/api-getting-started | Base `https://api.metorial.com`, `GET /provider-deployments`, butuh UA browser |
| Google OIDC token endpoint | https://developers.google.com/identity/protocols/oauth2 | Validasi client via `invalid_grant` vs `invalid_client` |
| Redis di VPS (keamanan) | https://redis.io/docs/latest/operate/oss_and_stack/management/security/ | Jangan ekspos 6379 ke internet; bind loopback + password + akses via **SSH tunnel** |

---

## 7. Verifikasi ulang — 9 Okt 2026 (fitur #3 → #6)

Scan ulang `.env` menemukan **101 pasangan nama** (sebelumnya tercatat 98).
Selisihnya bukan rahasia baru, melainkan:

| Nama | Keterangan |
|---|---|
| `GEMINI_KEY_2` … `GEMINI_KEY_12` | sudah terwakili sebagai rentang `GEMINI_KEY_1…GEMINI_KEY_13` di §2.1; kuncinya kini dijabarkan satu per satu |
| `COMPOSIO_API_KEY_consumer` | varian consumer dari `COMPOSIO_API_KEY` |
| `beatapi`, `promptpilot_mcp` | variabel kerja non-rahasia (bukan kredensial) |

**Tidak ada nilai yang dibaca atau ditulis.** Inventaris tetap memuat nama saja.

### Relevansi untuk fitur yang tersisa
* **#6 End-user credentials** — tidak butuh kredensial baru; memakai
  `VAULT_SECRET_KEY` / `VAULT_PASSWORD` yang sudah ada (Fernet).
* **#10 Custom RBAC** — tanpa kredensial baru.
* **#5 Agent sandbox isolation** — tanpa kredensial baru.
* **#2 MCP build workflow** — tanpa kredensial baru.
* **#1 n8n Agents first-class** — memakai `*_API_KEY` LLM yang sudah ada.
* **#9 Durable Execution via Dapr** — tanpa kredensial baru.

---

## 8. Verifikasi ulang — 9 Okt 2026 (fitur #10 dan seterusnya)

Scan ulang `.env` tetap **101 nama** — tidak ada kredensial baru yang
diperlukan untuk fitur #10. Yang ditambahkan hanya **variabel perilaku**
(bukan rahasia, boleh dibiarkan kosong):

| Nama | Default | Keterangan |
|---|---|---|
| `KATALIR_RBAC_STRICT` | `"1"` | Gerbang penolakan definisi peran yang mengandung risiko privilege escalation. `"0"` mematikan gerbang (tidak disarankan di produksi). |
| `KATALIR_RECOVERY_*` | lihat `docs/sandbox-production.md` | Ambang detektor self-healing (fitur #3). |
| `KATALIR_TRACING_*`, `KATALIR_LOG_SIEM_*`, `KATALIR_EUC_*` | lihat `docs/n8n-gap-closure-log.md` | Ambang/flag fitur #8, #4, #6. |

Semua variabel di atas **tidak wajib diisi**: modul terkait punya default
aman. Tidak ada nilai `.env` yang dibaca atau ditulis; inventaris tetap
memuat nama saja.
