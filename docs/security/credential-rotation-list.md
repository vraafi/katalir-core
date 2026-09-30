# Daftar Rotasi Credential — Katalir

- **Tanggal:** 2026-09-30
- **Commit saat scan:** `8604703` (`main`)
- **Alat:** gitleaks 8.30.1 + `scripts/security/scan_secrets.py` + inspeksi manual
- **Repo:** `vraafi/katalir-core` (sudah `public` di GitHub)

> **Nilai credential TIDAK PERNAH ditulis di dokumen ini.** Yang dicatat hanya
> **nama key**, **lokasi file**, dan **panjang karakter** — cukup untuk
> menemukan baris yang harus dirotasi tanpa menyalin rahasia.

---

## Ringkasan

| Metrik | Nilai |
|---|---|
| Baris tabel | 63 |
| 🔴 P0 — rotasi wajib (infra / full DB / auth bypass) | 6 |
| 🟠 P1 — rotasi wajib (API key / service) | 34 |
| 🟡 P2 — rotasi nice (identifier / read-only) | 15 |
| ⚪ Tidak perlu dirotasi | 8 |
| File yang discan | 15 |

---

## 🔴 P0 — Rotasi WAJIB

| # | Key Name | File | Kategori | Priority | Alasan | URL Rotasi |
|---|---|---|---|---|---|---|
| 1 | `VPS_PASSWORD` (18 char) — ✅ **ROTATED 2026-09-30** | `.env`, 5 × `.env.bak-*`, **history: `vps_ssh_test.py`** | Infra | 🔴 P0 → ✅ DONE | Password **root** VPS. Kontrol penuh server. Nilai lama ada di 96 commit git. **Sudah dirotasi 2026-09-30** via `scripts/security/rotate_vps_password.py`: `chpasswd` di server → login dengan password baru **PASS** → login dengan password lama **FAIL** (`AuthenticationException`) → `.env` diperbarui → verifikasi ulang proses baru **PASS**. Sesi lama sengaja ditutup HANYA setelah sesi baru terbukti berhasil (anti-lockout). | — selesai — |
| 2 | `SUPABASE_SERVICE_ROLE_KEY` (219 char) — 🔴 **PENDING, ROTASI GAGAL** | `.env`, 4 × `.env.bak-*` | Database | 🔴 P0 | **Bypass penuh RLS** — mengabaikan seluruh policy baris, bisa baca/tulis/hapus semua tabel lintas user. **STATUS 2026-09-30: rotasi BELUM terbukti.** Fingerprint `sha256[:12]` = `fdd6d40b4880`, **identik** dengan backup 2026-09-17. Tes penentu: kunci LAMA dari backup itu masih membalas **HTTP 200** ke `/rest/v1/workflows` — jadi kunci lama **masih aktif penuh**. Dugaan: reset tidak tersimpan di project ref `qmukkphwaajzbqjrcvaz`. | **USER ACTION:** Supabase → project `qmukkphwaajzbqjrcvaz` → Settings → API → service_role → **Reset**. Lalu update `.env` + Railway. Verifikasi: `fingerprint harus berubah` DAN `kunci lama harus 401`. |
| 3 | `SUPABASE_SERVICE_KEY` (219 char) | `.env`, 4 × `.env.bak-*` | Database | 🔴 P0 | Alias lokal dari `SERVICE_ROLE` (lihat `database.py:46`), **nilai identik** dengan #2. | Reset #2 sudah cukup. Tidak perlu rotasi terpisah. |
| 4 | `SUPABASE_DB_PASSWORD` (16 char) — 🔴 **PENDING, ROTASI GAGAL** | `.env`, 4 × `.env.bak-*` | Database | 🔴 P0 | Login **Postgres langsung** — melewati RLS sepenuhnya. **STATUS 2026-09-30: rotasi BELUM terbukti.** Fingerprint `sha256[:12]` = `bbccb72a1faa`, **identik** dengan backup 2026-09-17, dan password itu **masih berhasil konek** ke pooler (`CONNECT=PASS`, `policies_total=7`). Seharusnya password lama ditolak setelah reset. | **USER ACTION:** Supabase → project `qmukkphwaajzbqjrcvaz` → Settings → Database → **Reset password**. Lalu update `.env` + Railway `SUPABASE_DB_PASSWORD`. Verifikasi: `fingerprint berubah` DAN `password lama harus FAIL`. |
| 5 | `VAULT_SECRET_KEY` (44 char) | `.env`, 5 × `.env.bak-*` | Kripto | 🔴 P0 | Kunci master **Fernet** — pembuka semua credential yang tersimpan di Vault. Rotasi tanpa re-encrypt membuat seluruh entri Vault tidak terbaca. | Tidak ada reset di provider. **Prosedur:** generate kunci baru → decrypt semua entri dengan kunci lama → re-encrypt. **Lakukan setelah #1–#4.** |
| 6 | `GITHUB_TOKEN` — **2 format berbeda** (40 char + 93 char) | 40 char: `.env` + 3 backup · 93 char: `.env.bak-20260910`, `.env.bak-20260917-014828` | CI/CD | 🔴 P0 | Dua token berbeda (classic PAT vs fine-grained). Keduanya punya write scope pada repo. Token 93 char sudah dicabut dari `.env` tapi masih hidup di 2 backup. | GitHub → **Settings → Developer settings → Personal access tokens**. Revoke keduanya secara terpisah. |

> **Urutan rotasi P0:** mulai dari #1 dan #2. #5 bergantung transitif pada
> #1–#4 — mengubah #5 tanpa re-encrypt akan merusak Vault, bukan hanya
> membocorkan.

---

## 🟠 P1 — Rotasi WAJIB (API key / credential service)

| # | Key Name | File | Kategori | Priority | Alasan | URL Rotasi |
|---|---|---|---|---|---|---|
| 7 | `GEMINI_KEY_1` … `GEMINI_KEY_13` — **13 key** (39 & 53 char) | `.env`, 5 × `.env.bak-*` | LLM | 🟠 P1 | 13 kunci Google AI terpisah, semuanya aktif di produksi. | https://aistudio.google.com/apikey |
| 8 | `GROQ_API_KEY` (56 char) | `.env`, 5 × `.env.bak-*` | LLM | 🟠 P1 | Inferensi LLM berbayar. | https://console.groq.com/keys |
| 9 | `NVIDIA_API_KEY` (70 char) | `.env`, 5 × `.env.bak-*` | LLM | 🟠 P1 | Inferensi LLM berbayar. | https://build.nvidia.com/ → My API Keys |
| 10 | `TELEGRAM_BOT_TOKEN` (46 char) | `.env`, 5 × `.env.bak-*` | Messaging | 🟠 P1 | Token bot = kendali penuh atas bot (baca & kirim pesan, akses chat). | BotFather → `/revoke` |
| 11 | `TELEGRAM_APP_API_HASH` (32 char) | `.env`, 5 × `.env.bak-*` | Messaging | 🟠 P1 | Pasangan `TELEGRAM_APP_API_ID` (#47). Bersamaan bisa mengambil alih sesi user Telegram, bukan hanya bot. | my.telegram.org → **API development tools → Revoke** |
| 12 | `CLOUDFLARE_API_TOKEN` (53 char) | `.env`, 5 × `.env.bak-*` | Cloud | 🟠 P1 | Kalau punya izin `Edit`, bisa deploy Workers/Pages **dan membaca Workers Secrets**. | Cloudflare → **My Profile → API Tokens** |
| 13 | `CLOUDFLARE_R2_SECRET_ACCESS_KEY` (64 char) | `.env`, 5 × `.env.bak-*` | Storage | 🟠 P1 | Tulis penuh ke bucket R2 (upload / hapus objek). | Cloudflare → **R2 → Manage R2 API Tokens** |
| 14 | `CLOUDFLARE_R2_ACCESS_KEY_ID` (32 char) | `.env`, 5 × `.env.bak-*` | Storage | 🟠 P1 | Pasangan #13 — harus dirotasi bersamaan. | Sama seperti #13 |
| 15 | `RAILWAY_TOKEN` + `RAILWAY_API_TOKEN` (36 char, 2 key) | `.env`, 5 × `.env.bak-*` (3 backup lama menyimpannya sebagai `RAILWAY_projek` / `RAILWAY_akun`) | CI/CD | 🟠 P1 | Deploy ke Railway produksi. Scope `Account` = bisa menulis ke project lain milik Anda. | Railway → **Account → Tokens** |
| 16 | `DODO_API_KEY` (65 char) | `.env`, 5 × `.env.bak-*` | Billing | 🟠 P1 | API key payment processor — risiko manipulasi transaksi / refund. | Dodo Dashboard → Developer → API Keys |
| 17 | `DODO_WEBHOOK_SECRET` (38 char) | `.env`, 5 × `.env.bak-*` | Billing | 🟠 P1 | **fail-closed** — tanpa ini semua webhook dibalas 401 dan billing mati total. Rotasi harus satu commit dengan update Railway. | Dodo Dashboard → Developer → Webhooks |
| 18 | `GOOGLE_CLIENT_SECRET` (35 char) | `.env`, 5 × `.env.bak-*` | OAuth | 🟠 P1 | Dengan client ID (#52) bisa menyelesaikan token exchange atas nama aplikasi Anda. | Google Cloud Console → **APIs & Services → Credentials** |
| 19 | `SLACK_CLIENT_SECRET` (32 char) | `.env`, `.env.bak-20260926-150120` | OAuth | 🟠 P1 | Scope bot Slack. | api.slack.com/apps → Your Apps → Client Secret |
| 20 | `SLACK_SIGNING_SECRET` (32 char) | `.env`, `.env.bak-20260926-150120` | Webhook | 🟠 P1 | Memungkinkan forge webhook Slack Events API (bisa menyamar sebagai Slack). | Sama seperti #19 |
| 21 | `DNSHE_API_KEY` (37) + `DNSHE_API_SECRET` (64) | `.env`, `.env.bak-20260926-150120` | DNS | 🟠 P1 | Pair API registrar DNS — kendali penuh atas zona. | Panel registrar Anda → API Credentials |
| 23 | `NINEROUTER_KEY` (16 char) | `.env`, 5 × `.env.bak-*` | Payment | 🟠 P1 | API key payment gateway. | Panel NineRouter → API Keys |
| 24 | `LLM_GATEWAY_KEY` (46 char) | `.env`, 5 × `.env.bak-*` | LLM Gateway | 🟠 P1 | Dipakai di **6 file** kode; gateway internal yang bisa diserang dari mana saja. | Whoever deploy LLM gateway |
| 25 | `mptpilot_mcp` (47 char) | `.env`, `.env.bak-20260926-150120` | MCP | 🟠 P1 | Token gateway MCP. | Panel mptpilot |
| 26 | `COMPOSIO_API_KEY` (23 char) | `.env`, `.env.bak-20260926-150120` | MCP | 🟠 P1 | Menggabungkan 1.558 toolkit pihak ketiga. | https://app.composio.dev → Settings → API Keys |
| 27 | `COMPOSIO_API_KEY_consumer` (22 char) | `.env`, `.env.bak-20260926-150120` | MCP | 🟠 P1 | Token consumer kedua untuk Composio. | Sama seperti #26 |
| 28 | `GLAMA_API_KEY` (70 char) | `.env`, `.env.bak-20260926-150120` | MCP | 🟠 P1 | 20.000 MCP server. | https://glama.ai/mcp/servers |
| 29 | `NANGO_API_KEY` (36 char) | `.env`, `.env.bak-20260926-150120` | MCP | 🟠 P1 | 1.024 integrasi OAuth. | https://dashboard.nango.dev → Settings |
| 30 | `METORIAL_API_KEY` (124 char) | `.env`, `.env.bak-20260926-150120` | MCP | 🟠 P1 | Dipakai di 4 file kode. | Panel Metorial |
| 31 | `ROBLOX_OPEN_CLOUD_API_KEY` (968 char) | `.env`, 5 × `.env.bak-*` | Gaming | 🟠 P1 | Kunci Open Cloud Roblox. Panjang 968 ≈ JWT dengan banyak claim — cek apakah masih aktif. | https://create.roblox.com/ → Open Cloud → API Keys |
| 32 | `PEXELS_API_KEY` (56 char) | `.env`, 5 × `.env.bak-*` | Media | 🟠 P1 | Kuota API berbayar. | https://www.pexels.com/api/ |
| 33 | `KAGGLE_API_TOKEN` (37 char) | `.env`, 5 × `.env.bak-*` | Data | 🟠 P1 | Dipakai di 2 file kode. | https://www.kaggle.com/settings |
| 34 | `EMAIL_APP_PASSWORD` (16 char) | `.env`, 5 × `.env.bak-*` | Email | 🟠 P1 | App password Gmail khusus IMAP. Rotasi = memutus akses email itu saja, tidak seperti password utama. | myaccount.google.com → **App passwords** |
| 35 | `IG_PASSWORD` (11 char) | `.env`, 5 × `.env.bak-*` | Social | 🟠 P1 | **Password akun Instagram, bukan token** — bisa dipakai login langsung. | Instagram → Accounts Center → Password → aktifkan 2FA |
| 36 | `WA_TOKEN` (287 char) | `.env`, 5 × `.env.bak-*` | Messaging | 🟠 P1 | Token WhatsApp Business Cloud API. Panjang 287 = graph token bercabang; cabut dari **Meta Business Manager**. | developers.facebook.com → Business Settings → Accounts → WhatsApp |
| 37 | `GITHUB_CLIENT_SECRET` (40 char) | `.env`, `.env.bak-20260926-150120` | OAuth | 🟠 P1 | OAuth app GitHub — **berbeda** dari PAT di #6. | GitHub → Settings → Developer settings → OAuth Apps |
| 38 | E2E session JWT (818 char × **3 file**) | `_e2e_storage.json`, `_e2e_session.refreshed.json`, `_e2e_rebrand.txt` | Session | 🟠 P1 | `access_token` + `refresh_token` Supabase milik user uji. `.gitignore` sudah menutup polanya, tapi filenya masih ada di disk. **Refresh token berumur panjang** — lebih berbahaya dari access token. | Supabase → hapus user uji via Admin API (lihat `scripts/gen-test-jwt.py`) |
| 39 | Google API key literal (35 char) | `_vps_mask.py` | Google API | 🟠 P1 | Kunci `AIza` ditulis langsung di skrip masking, bukan lewat `env`. Berisiko bocor saat skrip itu dijalankan tanpa sengaja. | https://aistudio.google.com/apikey — lalu ganti pemanggilannya ke `os.getenv` |
| 40 | E2E JWT di git history (818 char × 2 commit) | history: `test-jwt.txt.txt` | Session | 🟠 P1 | **Sudah kedaluwarsa** — decode payload: `exp` = 2026-09-25 05:00 UTC (lewat ~5 hari). Tidak bisa dipakai login, tapi masih membocorkan PII: email, nama lengkap, user ID, session ID, `sub` Google. | Sudah invalid temporal. Hapus user uji, lalu bersihkan history. |

---

## 🟡 P2 — Rotasi NICE (identifier / read-only)

| # | Key Name | File | Kategori | Priority | Alasan | URL Rotasi |
|---|---|---|---|---|---|---|
| 41 | `SUPABASE_KEY` (208 char) | `.env`, 5 × `.env.bak-*` | Database | 🟡 P2 | Legacy **anon key** — sudah terekspos ke browser lewat `NEXT_PUBLIC_SUPABASE_ANON_KEY` (#57), jadi bukan rahasia. Satu-satunya perlindungannya RLS, dan audit 2026-09 membuktikan RLS anon mengembalikan 0 baris. Tetap layak dirotasi untuk contemporer. | Supabase → **API → anon/publishable → Reset** |
| 42 | `SUPABASE_PUBLISHABLE_KEY` (46 char) | `.env` | Database | 🟡 P2 | Pendant modern dari anon key. Dirancang untuk ditaruh di kode publik. | Supabase → API → publishable key |
| 43 | `SLACK_VERIFICATION_TOKEN` (23 char) | `.env`, `.env.bak-20260926-150120` | Webhook | 🟡 P2 | Hanya memverifikasi event awal, bukan otorisasi. | Slack → Your Apps → Basic Information |
| 44 | `CLOUDFLARE_ACCOUNT_ID` (32 char) | `.env`, 5 × `.env.bak-*` | Cloud | 🟡 P2 | Public identifier akun. | Tidak perlu dirotasi |
| 45 | `WA_BUSINESS_ACCOUNT_ID` (15 char) | `.env`, 5 × `.env.bak-*` | Messaging | 🟡 P2 | Public identifier. | Tidak perlu dirotasi |
| 46 | `SLACK_APP_ID` (11 char) | `.env`, `.env.bak-20260926-150120` | OAuth | 🟡 P2 | Public app identifier. | Tidak perlu dirotasi |
| 47 | `TELEGRAM_APP_API_ID` (8 char) | `.env`, 5 × `.env.bak-*` | Messaging | 🟡 P2 | Public app identifier — tidak berbahaya tanpa #11. | Tidak perlu dirotasi |
| 48 | `ROBLOX_UNIVERSE_ID` (10), `ROBLOX_PLACE_ID` (15) | `.env`, 5 × `.env.bak-*` | Gaming | 🟡 P2 | Public game identifiers. | Tidak perlu dirotasi |
| 49 | `TELEGRAM_CHAT_ID` (10 char) | `.env`, 5 × `.env.bak-*` | Messaging | 🟡 P2 | ID chat tujuan notifikasi — informational. | Tidak perlu dirotasi |
| 50 | `PHONE_NUMBER` (14 char) | `.env`, 5 × `.env.bak-*` | PII | 🟡 P2 | Nomor telepon. Bukan credential, tapi data pribadi — jangan ikut ter-commit. | N/A |
| 51 | `IG_USERNAME` (24 char) | `.env`, 5 × `.env.bak-*` | Social | 🟡 P2 | Handle Instagram — pasangan #35. | N/A |

---

## ⚪ TIDAK perlu dirotasi

| # | Key Name | File | Alasan |
|---|---|---|---|
| 56 | `NEXT_PUBLIC_API_URL` (43), `NEXT_PUBLIC_SUPABASE_URL` (40), `NEXT_PUBLIC_SUPABASE_ANON_KEY` (208), `NEXT_PUBLIC_DODO_CHECKOUT_URL` (74) | `nexus-frontend/.env.local` | Prefix `NEXT_PUBLIC_` = **harus** masuk bundle browser. Anon key sudah tercermin di build produksi. Rotasi tidak mengubah apa pun secara keamanan. |
| 57 | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (31), `NEXT_PUBLIC_DODO_CHECKOUT_URL` | `nexus-frontend/.env.example` | Sudah placeholder — tidak ada nilai nyata. |
| 58 | `OPENAI_API_KEY` (24), `OPENAI_ORG_ID` (16) | `tools/picgen-mcp/.env.example` | Placeholder. |
| 59 | `DODO_WEBHOOK_SECRET` (38), `DODO_API_KEY` (65), `DODO_PAYMENTS_ENVIRONMENT`, `DODO_CHECKOUT_URL` | `.env.example` (root) | Placeholder `xxxx` / `whsec_xxxx`. Aman. |

---

## 📁 File yang DiscAN

**9 file env / konfigurasi:**

| # | File | Jumlah key |
|---|---|---|
| 1 | `.env` | 95 |
| 2 | `.env.bak-20260910` | 60 |
| 3 | `.env.bak-20260917-014828` | 79 |
| 4 | `.env.bak-20260924-101059` | 79 |
| 5 | `.env.bak-20260924-131948` | 79 |
| 6 | `.env.bak-20260926-150120` | 92 |
| 7 | `nexus-frontend/.env.local` | 4 |
| 8 | `nexus-frontend/.env.example` | 4 (placeholder) |
| 9 | `tools/picgen-mcp/.env.example` | 2 (placeholder) |

**4 file bearer token lokal:**

| # | File | Temuan |
|---|---|---|
| 10 | `_e2e_storage.json` | JWT 818 char |
| 11 | `_e2e_session.refreshed.json` | JWT 818 char |
| 12 | `_e2e_rebrand.txt` | JWT 818 char |
| 13 | `_vps_mask.py` | Google API key 35 char |

**2 file di git history:**

| # | File | Temuan |
|---|---|---|
| 14 | `vps_ssh_test.py` | 96 commit — `VPS_PASSWORD` |
| 15 | `test-jwt.txt.txt` | 2 commit — JWT kedaluwarsa |

Sebagai pembanding, `gitleaks dir .` menandai **56 file** di seluruh working
tree (termasuk build artifact). Hanya **1** yang tracked
(`mcp_registry_cache.json`) dan sudah ditriase menjadi UUID test fixture —
false positive.

---

## 🔍 Temuan History (konteks keputusan rotasi #1)

| Item | Commit | Ref | Status |
|---|---|---|---|
| `VPS_PASSWORD` | `8dab36c0` + 95 commit lain | `refs/cline/checkpoints/1789207237236_telvw/161` | **Hanya lokal.** Bukan ancestor dari `main` / `stable-v1.5` / `level-3-experiment` / `origin/*` / tag mana pun. |
| E2E JWT | `9b7bbfbc`, `df868cc0` | `refs/cline/checkpoints/1790271966047_6ib6v/70` | **Hanya lokal.** Sudah kedaluwarsa. |

Scan `gitleaks` khusus branch + tag yang benar-benar tayang di GitHub
(`origin/main`, `origin/stable-v1.5`, `origin/level-3-experiment`,
`origin/railway/fix-deploy-77a906`, plus tags) mengembalikan **0 temuan**.

Artinya: **rotasi #1 tetap wajib** meski repo publik bersih, karena
1. passwordnya masih hidup di host tersebut, dan
2. nilainya ada di objek `.git` lokal — akan ikut ter-*mirror* atau ter-*zip*
   kalau repo ini pernah disalin utuh.

> **Belum dilakukan (menunggu keputusan Anda):** menghapus ref
> `refs/cline/checkpoints/*`, menghapus `.env.bak-*`, atau menghapus file
> `_e2e*`.

---

## ✅ Verifikasi dokumen ini

- Scan terakhir: `gitleaks dir . --redact` (nilai disamarkan oleh gitleaks)
- Ekstraksi nilai hanya membaca **panjang karakter**, dicetak sebagai `nama:len`
- **Nilai credential yang tertulis di dokumen ini: 0**
- Tidak ada baris di dokumen ini yang cocok dengan pola `ghp_`, `github_pat_`,
  `sk_live_`, `whsec_`, `AIza`, `AKIA`, `xox?`, `eyJ…`,
  atau `SUPABASE_SERVICE_ROLE_KEY=<apa pun>`

| 60 | `GOOGLE_API_KEY` (0), `GEMINI_API_KEY` (0), `DEEPSEEK_API_KEY` (0), `OPENAI_API_KEY` (0), `ANTHROPIC_API_KEY` (0) | `.env` + 4 backup | **Kosong** (`len=0`) — tidak ada nilai untuk dibocorkan. |
| 61 | `CORS_ORIGIN` (0), `MCP_SDK` (0), `PERSIST_REQUIRED` (0) | `.env` + backup | Kosong / flag boolean. |
| 62 | `SUPABASE_URL` (40), `AGENTGATEWAY_URL`, `LLM_GATEWAY_URL`, `NINEROUTER_EXTERNAL_URL`, `DODO_CHECKOUT_URL`, `PAYMENT_PORTAL_URL`, `CLOUDFLARE_R2_ENDPOINT`, `EMAIL_IMAP_HOST`, `BRAVE_CDP_URL`, `LLM_GATEWAY_MODELS` (257) | `.env` + backup | URL & config non-secret — tidak mengotorisasi apa pun. |
| 63 | `VPS_IP` (13), `VPS_USERNAME` (4), `VPS_OS` (19), `CLOAK_DEBUG_PORT` (4), `BRAVE_PATH` (72), `EMAIL_IMAP_PORT` (3), `EMAIL_CHECK_INTERVAL` (3), `EMAIL_ADDRESS` (24) | `.env` + backup | Infrastruktur non-secret. **Catatan:** `VPS_IP` + `VPS_USERNAME` berguna bagi penyerang bila `VPS_PASSWORD` bocor — itulah alasan #1 masuk P0. |

| 52 | `GOOGLE_CLIENT_ID` (71 char) | `.env`, 5 × `.env.bak-*` | OAuth | 🟡 P2 | Public client ID — pasangan #18. | Cloud Console → Credentials |
| 53 | `GITHUB_CLIENT_ID` (20 char) | `.env`, `.env.bak-20260926-150120` | OAuth | 🟡 P2 | Public client ID — pasangan #37. | GitHub → OAuth Apps |
| 54 | `SLACK_CLIENT_ID` (29 char) | `.env`, `.env.bak-20260926-150120` | OAuth | 🟡 P2 | Public client ID — pasangan #19. | Slack → Your Apps → Basic Information |
| 55 | `SUPABASE_JWKS` (240 char) | `.env`, 4 × backup 20260917+ | Auth | 🟡 P2 | **Public** JWKS — kumpulan public key, bukan private key. Aman secara desain. | N/A |


| 22 | `HYRVE_API_KEY` (70 char) | `.env`, 5 × `.env.bak-*` | Payment | 🟠 P1 | API key payment gateway. | Panel HYRVE → API Keys |

