# NEXUS — HANDOFF CONTEXT

Generated: 2026-09-16 01:46 (+07:00)
Commit kode terakhir: `6b6fe07` (`6b6fe07bfc1fae9d1919c45cdb85a4f69660d1a6`) — perbaikan kontrak 401 vs 503, sesi E2E terverifikasi, cakupan filter pindah ke unit test.
Dokumentasi (HANDOFF.md + ARCHITECTURE_REPORT.txt) diperbarui di commit **terpisah setelahnya**
yang **hanya** menyentuh dokumen — lihat `git log --oneline -1` untuk commit teratas.
Branch: `main` — **sinkron dengan `origin/main` (0 ahead / 0 behind)** setelah push.

> Dokumen ini ditulis agar pekerjaan bisa dilanjutkan di chat/sesi baru **tanpa akses
> ke history chat sebelumnya**. Semua angka di bawah diambil dari verifikasi
> langsung terhadap repo & layanan produksi (bukan asumsi). Bagian yang belum
> terverifikasi ditandai eksplisit `TODO: verifikasi`.

---

## 0. KOREKSI DOKUMEN — 2026-09-16 (verifikasi ulang oleh agen sesi baru)

> Sembilan klaim di versi dokumen sebelumnya terbukti **salah atau basi**. Badan
> dokumen sudah dikoreksi; daftar ini disimpan supaya tidak diulang.

| # | Klaim lama | Fakta terverifikasi | Bukti (perintah/keluaran nyata) |
|---|---|---|---|
| 1 | Uji produksi = `npm run build && npm run start` | `next start` **DITOLAK** oleh konfigurasi `output: "export"` | `[Error: "next start" does not work with "output: export" configuration. Use "npx serve@latest out" instead.]` → jalur sah: `npm run build` + **`npm run serve:static`** |
| 2 | Unit test backend: **27 lulus** | **26 lulus** untuk 3 file (jwt 14 + multiturn 9 + idempotent 3) — naik jadi **56 lulus** setelah `test_model_filter.py` ditambahkan, dan **61 lulus** setelah `test_chat_budget_invariant.py` (lihat §0.1) | `python -m pytest test_security_jwt.py test_multiturn_history.py test_idempotent_add_message.py -q` → `26 passed`; dengan `test_model_filter.py` → `56 passed`; dengan `test_chat_budget_invariant.py` → `61 passed in 4.62s` |
| 3 | E2E: **9 spec sehat + 3 probe** | **10 spec sehat + 3 probe** (`fix4a.spec.ts` tidak terhitung) | `npx playwright test --list` → `Total: 14 tests in 10 files` |
| 4 | `scripts/e2e-prod-server.mjs` = npm script `serve:static` | `serve:static` = `scripts/serve-out.mjs`; `e2e-prod-server.mjs` adalah **pembungkus** (build → import `serve-out.mjs`) | `package.json` scripts |
| 5 | Migrasi OpenNext tidak disebut sama sekali | OpenNext/Workers **sudah disiapkan** (commit `780fe13`) tapi **belum deployable** (KV namespace masih placeholder) | `open-next.config.ts`, `wrangler.jsonc`, `next.config.ts` komentar "TEMPORARY" |
| 6 | Spec probe `tests/_*.spec.ts` di root `tests/` | Sudah **dikarantina** ke `tests/_probes/` + `testIgnore` | `playwright.config.ts` (`E2E_PROBES=1` untuk menjalankan) |
| 7 | `ARCHITECTURE_REPORT.txt` menggambarkan state terkini | Report **basi sebagian** (HEAD `d1bfae6`, deps Next 15.1.3, "tanpa playwright", `lang=en`) | lihat §17 report |
| 8 | Groq perlu rotate karena 403 | Belum terbukti; kuota Groq justru **terbaca aktif** | `GET /api/rate-tracking` → 200, `groq rpm 0/30, rpd 0/14400` (tetap `TODO: verifikasi` via chat nyata) |
| 9 | Gateway URL "sudah jalan" | Benar **saat diperiksa**, tapi tetap quick tunnel rapuh | `GET /v1/models` → 200, **259 model / 25 provider** |

### 0.1 TEMUAN & PERBAIKAN — 2026-09-16 (sesi lanjutan: E2E merah → hijau)

> Sesi ini dimulai dari "3 E2E gagal 401/503" dan berakhir **semua hijau**. Akar
> masalahnya BUKAN produk, melainkan harness. Tiap butir di bawah punya bukti
> yang bisa dijalankan ulang.

| # | Temuan | Bukti | Perbaikan |
|---|--------|-------|-----------|
| A | **Fixture E2E palsu** — `_e2e_extend.py` menyunting klaim `exp` **tanpa menandatangani ulang**, jadi signature-nya tidak sah. `kid` sengaja disamarkan sama dengan kid asli dan TTL-nya panjang (604800s), sehingga lolos semua guard berbasis TTL | `VERIFY[disk/fresh] = InvalidSignatureError` (PyJWT vs JWKS live; disk == fresh, kid cocok) + dikunci sebagai unit test `test_signature_palsu_ditolak` | `scripts/e2e-auth-setup.mjs` kini **memverifikasi signature tiap kandidat** thd JWKS: yang palsu disingkirkan ke `_e2e_session*.FORGED.json`, yang sah dipakai, jika tidak ada → **mint sesi sah** (`signInWithPassword`); `_e2e_session.extended.json` dibuang dari kandidat `chat-auth.spec.ts` |
| B | **Kontrak 401 vs 503 bocor** — `or _jwks_last_error` (flag **lengket** dari kegagalan unduhan masa lalu) membajak kasus konklusif: token bertanda tangan palsu dilaporkan **503** berpesan "Token TIDAK dinilai tidak sah" | Dikunci sebagai unit test (bukti yang bisa dijalankan ulang — probe scratch TIDAK diandalkan karena ter-`gitignore`): `test_verifikasi_lokal_konklusif_menang_atas_flag_jwks_basi` (→ 401) dan `test_kunci_tak_tersedia_503_bukan_401` (→ 503) di `test_security_jwt.py` | `security.py`: `_KeyUnavailableError` memisahkan "kunci TIDAK BISA dipegang" (DISKONKLUSIF → 503) dari "kunci ada, penilaian gagal" (KONKLUSIF → 401); `get_current_user` memakai `local_verdict` |
| C | **Filter model hanya diuji lewat roster live** → tes gagal-acak dan **menuduh filter** ("model valid hilang") padahal gateway yang tidak menyajikan. Rotasi liveness terbukti **dua arah** dalam satu sesi: masuk `mistralai/mistral-nemotron` + `poolside/laguna-xs-2.1`, keluar `gemini-2.5-flash-lite` + `moonshotai/kimi-k3` (katalog gateway 259 model TETAP memuat flash-lite) | 2 cache roster (12 vs 13 entri) + `MODELS_IDS` run E2E | Cakupan **"tidak over-delete" dipindah ke unit test deterministik** `test_model_filter.py` (30 test, input terkendali, tanpa jaringan); E2E hanya menguji sifat STABIL pada roster live (tidak ada model paid-only lolos, roster tidak kerdil, keluarga Flash terwakili) |
| D | Guard `exp` di spec E2E **tidak andal**: decoder memakai `Buffer.from(seg, "base64")` (bukan base64url) sehingga token sehat bisa terbaca `ttl=-1` → gagal dengan pesan "kedaluwarsa" yang menyesatkan. Saat diperbaiki, muncul jebakan padding `"=".repeat(-len % 4)` → `RangeError` (regresi nyata: **3 tes gagal**) | `TOKEN_TTL_S=-1` pada run pertama; `TTL_S=1601` setelah fix | `expiresInSec()` memakai base64url + `pad = (4 - len % 4) % 4` |
| E | Entri **non-dict** dari upstream (`null` di dalam array JSON) bisa menjatuhkan seluruh `/models` | `test_filter_tahan_input_kotor` | `gateway_roster.filter_free_models()` melewati entri non-dict |
| F | **Tiga timer yang saling bertabrakan** (ditemukan dari 2 E2E `/chat` timeout 60s): anggaran backend `LLM_GATEWAY_BUDGET` = **90s** SAMA PERSIS dengan abort klien `FETCH_TIMEOUT_MS` = **90s**, dan fase Gemini cadangan **tidak dibatasi sama sekali** (4 percobaan tanpa timeout + `sleep`). Akibatnya backend masih bekerja saat klien sudah membatalkan → user melihat "Server lambat, coba lagi" padahal jawabannya hampir siap, pekerjaan terbuang, dan E2E merah palsu (`status=-1, time=-1` di trace Playwright) | Trace `.network`: `POST /chat => status=-1, time=-1` (browser menunggu selamanya); reproduksi bersih: `gemini-3-flash-preview` via `_agentic_run_direct` = **49,6s** lalu fallback (`reason=model_unavailable`) walau gateway langsung menjawab **200 dalam 2,2s**; log backend `OpenAIAPIError: Internal Server Error` + `OpenAITimeoutError` (45s) | Budget jadi **TOTAL** (gateway + cadangan): default 45s dengan `_FALLBACK_RESERVE_SEC=15s` disisihkan untuk jalur Gemini, timeout per percobaan 45s→**20s**, deadline diperiksa **setiap** iterasi kandidat dan dipangkas ke sisa anggaran, fase Gemini dibatasi deadline yang dihitung dari **awal request**. Dikunci `test_chat_budget_invariant.py` (5 test, memparsing `FETCH_TIMEOUT_MS` dari sumber TS) |

**Hasil akhir sesi:** pytest **61 lulus** (jwt 14 + filter 30 + multiturn 9 + idempotent 3 + budget 5);
E2E produksi terakhir: **12 passed / 2 skipped / 0 failed** — bukti payload:
`MODELS_COUNT=12`, `FORBIDDEN_HITS=[]`. Dua test `/chat` **SKIP eksplisit**, bukan merah:
upstream Gemini jalur cadangan **RPD habis** saat run (`CHAT_STATUS=503`,
`VALID_STATUS=503`, `VALID_META={}` — kosong karena body 503 tidak membawa `meta`).
Pada run sehat di sesi sebelumnya, jalur yang sama terukur `CHAT_STATUS=200` dan
`VALID_META` lengkap (`fallback:false`). Jadi angka "14 passed" yang pernah ditulis
di sini **bukan** hasil akhir — jangan pakai sebagai baseline tanpa menjalankan ulang.
Sesi juga **terverifikasi ES256** (`ttl=1561s`) sehingga 503 itu bukan masalah auth.


---

## 1. STATUS PROYEK

- **Overall progress: ~85%** (MVP SaaS jalan; hardening & billing yang tersisa).
- **Current phase: TAHAP 6 — hardening backend & transparansi model.**
  Fokus terakhir: (a) memperbaiki konteks multi-turn yang hilang, (b) memindahkan
  verifikasi JWT Supabase dari panggilan jaringan ke verifikasi lokal (JWKS),
  (c) membuat E2E produksi hijau.

### Blocking issues

| # | Isu | Status |
|---|-----|--------|
| 1 | Gateway URL memakai **Cloudflare quick tunnel** (`trycloudflare.com`) — URL **berubah** setiap tunnel di-restart → model selector & chat mati total bila URL basi | **BELUM SELESAI** ❗ |
| 2 | `GROQ_API_KEY` dilaporkan 403 di catatan lama | `TODO: verifikasi` (di gateway, Groq justru terpakai & `rate-tracking` 200) |
| 3 | Kuota Gemini free-tier (`gemini-3.1-pro-preview` RPD 0) menyebabkan **503 transien** → 1 test E2E di-*skip* (bukan bug produk) | Sudah di-*handle* (skip eksplisit) |
| 4 | Billing Dodo belum diuji end-to-end di produksi | `TODO: verifikasi` |

**Koreksi penting terhadap catatan lama:** klaim *"push 5 commit ahead origin"*
**TIDAK AKURAT**. `git rev-list --left-right --count origin/main...main` = `0 0`.
Semua commit sudah ter-push.

---

## 2. STACK & ARSITEKTUR

| Layer | Teknologi | Versi terverifikasi |
|---|---|---|
| FE framework | Next.js (App Router, `output: "export"` static) | `^15.5.24` |
| FE UI | React | `^19.0.0` |
| FE styling | Tailwind CSS | `^3.4.17` |
| FE kanvas | `@xyflow/react` (React Flow) | terpasang |
| BE API | FastAPI + Uvicorn | 0.115.6 / 0.34.0 |
| BE DB/Auth | Supabase (Postgres + Auth) via `supabase-py` | 2.15.0 |
| LLM SDK | `google-genai`, LangChain core/google-genai/groq/openai, LiteLLM | 1.65.1 |
| Gateway | **free-llm-gateway** (multi-provider, 259 model) | live |
| Deploy FE | Cloudflare Pages (static `out/`) | `proyek-agent.pages.dev` |
| Deploy BE | Railway (`Procfile` + `railway.json`) | `web-production-dc90b.up.railway.app` |
| Gateway host | VPS (RackNerd) — **diekspos via quick tunnel** | lihat §8 |

**Multi-provider aktif di gateway:** `google_gemini` (4), `groq` (21), `nvidia` (88),
`openrouter` (33), `cerebras` (7), `github` (20), `ollama` (10), `cloudflare` (9), dst.
Total **259 model / 25 provider** (hasil `GET /v1/models`, HTTP 200).

**Alur data chat:**
`page.tsx` → `apiFetch()` (`src/lib/api.ts`) → ambil token via `supabase.auth.getSession()`
→ `Authorization: Bearer <jwt>` → FastAPI `api_server.py`
→ verifikasi JWT **lokal** (`security.py`, JWKS) → ambil riwayat dari Supabase
→ panggil gateway Gemini (`gateway_roster.py` untuk roster) → simpan pesan → balikan `{reply, meta, session_id}`.

---

## 3. FILE STRUCTURE (yang penting)

### Backend (root repo)

| File | Fungsi |
|---|---|
| `api_server.py` | FastAPI gateway: `/chat`, `/models`, `/sessions`, `/messages/{id}`, `/integrations`, `/workflows`, `/executions`, `/health`. Berisi `_agentic_run_direct` + `_send_guarded` (fallback) |
| `security.py` | Verifikasi JWT Supabase — **lokal via JWKS** (`_decode_local`, `_seed_jwks`, `_get_jwks`), cache disk `.jwks_cache.json` |
| `database.py` | Supabase CRUD: users, chat_sessions, chat_messages, user_integrations, workflows, executions |
| `gateway_roster.py` | Roster model **berbasis probe**: `is_paid_only()` 3-gerbang, `filter_free_models()`, `gateway_config()`, cache |
| `model_discovery.py` | Discovery model Gemini langsung (`genai.list`) + cache 1 jam |
| `tools.py` | Tool registry agentic (whatsapp, sheets, gmail, calendar) + `CredentialMissingError` |
| `agent_engine.py` | Mesin agen (dipakai jalur legacy/Streamlit) |
| `app_frontend.py` | **Legacy** UI Streamlit (sudah tidak dipakai; jangan dikembangkan) |

### Frontend (`nexus-frontend/`)

| Path | Fungsi |
|---|---|
| `src/app/page.tsx` | Chat utama (Auth + Shell + ChatApp) |
| `src/app/builder/page.tsx` | Halaman `/builder` (React Flow canvas) |
| `src/components/ModelSelector.tsx` | Dropdown model + badge status + gate `mounted` (anti-hydration) |
| `src/components/shell.tsx` | Sidebar riwayat + header + tombol login |
| `src/components/VaultModal.tsx` | Modal BYOK / kredensial |
| `src/components/HydrationMonitor.tsx` | Detektor hydration mismatch |
| `src/features/builder/` | `Canvas.tsx`, `ConfigPanel.tsx`, `Palette.tsx`, `nodes.tsx`, `Terminal.tsx`, `store/canvas-store.ts`, `hooks/useWorkflow.ts`, `hooks/useExecution.ts` |
| `src/features/chat/hooks/useChat.ts` | Query/mutation chat (React Query) |
| `src/lib/api.ts` | **`apiFetch` wrapper** — satu-satunya jalur HTTP ke backend |
| `src/lib/supabase.ts` | Klien Supabase browser |
| `src/lib/models.ts` | Konstanta/allowlist model + fallback `CHAT_MODELS` |
| `src/context/auth.tsx` | `AuthProvider` (`email`, `loading`, `signInWithGoogle`, `signOut`, `getToken`) |
| `tests/*.spec.ts` | Playwright E2E — **10 spec "sehat"** (total 14 test) |
| `tests/_probes/_*.spec.ts` | 3 spec probe diagnostik **dikarantina**: dikecualikan `testIgnore`; jalankan sengaja dengan `E2E_PROBES=1` |
| `scripts/serve-out.mjs` | Server statis `out/` = **bentuk produksi app ini** (`npm run serve:static`, port 3000) |
| `scripts/e2e-prod-server.mjs` | Pembungkus E2E: `next build` (env `E2E_API_URL`) lalu import `serve-out.mjs` |
| `scripts/e2e-auth-setup.mjs` | `globalSetup` Playwright: segarkan/mint sesi Supabase → `_e2e_storage.json` |
| `playwright.config.ts` | `webServer` ganda: backend lokal (**port 8123**) + FE produksi (port 3000); `testIgnore` probe |
| `evidence/` | Bukti uji (screenshot prod + JSON) — **gitignored**, artefak lokal |
| `.reference/` | Kode referensi pihak ketiga (`xyflow`, `react-flow-example-apps`) — **gitignored**, bukan bagian build |
---

## 4. COMMIT LOG (10 terakhir)

Diambil langsung dari `git log --oneline -10` (**sampai commit `6b6fe07`**; semuanya
sudah ter-push). Daftar ini sampai commit **kode** `6b6fe07`; commit di atasnya hanya
dokumentasi (mis. `b456f13` = HANDOFF.md). Baris ini sengaja TIDAK mengklaim
"commit terakhir", karena hash berubah setiap dokumen diperbarui — pakai
`git log --oneline -3` untuk commit teratas saat ini.
`4abfeda` tetap tercatat di bawah sebagai riwayat.

```
b456f13  docs(handoff): sinkronkan commit log + status remote ke 6b6fe07
6b6fe07  fix(auth)+test(e2e): kontrak 401 vs 503 konklusif, sesi E2E terverifikasi, cakupan filter ke unit test
4abfeda  chore(git): ignore harness runner lokal _*.ps1
5c28054  test(e2e): 503 upstream transien -> SKIP eksplisit (bukan merah palsu) + ignore _*.ps1
4401e7e  fix(agent): konteks multi-turn ke LLM + verifikasi JWT lokal (JWKS)
c503aea  fix(gateway): satu sumber gateway_config + alias env FREELM_GATEWAY_URL/GATEWAY_URL
f50aa5a  fix(gateway): kembalikan gemini-3.1-flash-lite-preview ke allowlist free-tier
e3016af  feat(frontend): badge fallback transparan (TUGAS 2) + locked state selector (TUGAS 3)
bc08c0e  feat(gateway+models): roster probe empiris, filter paid-only 3-gate (TUGAS 1), meta fallback (TUGAS 2 backend)
04d8ad5  fix(hydration): render pertama deterministik — gate mounted ModelSelector + initializer page.tsx (static export, React 19)
fb5321a  chore(gitignore): ignore probe/temp scripts + secret artifacts (_vps,_rail,_gw)
2f0db27  fix(backend): NameError md crash 502 — pindah block MODEL SELECTION ke bawah import md
```

**Status remote (terverifikasi `git rev-parse HEAD` == `git rev-parse origin/main`):** `HEAD -> main`, `origin/main` = `6b6fe07`
→ **0 ahead / 0 behind**.

---

## 5. SELESAI (done — terverifikasi)

- [x] **Chat stabil + streaming/latency footer** — `/chat` menjawab, footer `model · latency · token` tampil.
- [x] **Visual refresh (DeepSeek/ChatGPT-style)** — sidebar, chat bubble, empty state, CSS konsisten.
- [x] **Highlight session aktif** — session aktif di sidebar diberi `bg-gray-200 text-gray-900 font-medium`; non-aktif `text-gray-600 hover:bg-gray-100`.
- [x] **Transparansi model (badge fallback)** — backend mengirim `meta = {model, requested_model, latency_ms, prompt_tokens, completion_tokens, total_tokens, fallback, fallback_reason}`; UI merender badge "Model yang Anda pilih tidak tersedia · diminta: X".
- [x] **Model selector multi-model (live-probe)** — roster 13 model lolos probe (dari 259 model/25 provider di gateway), **0 model Pro**.
- [x] **Hydration fix** — hydration mismatch tidak lagi muncul (`HYDRATION_HITS=0`, `PAGEERRORS=[]`) via gate `mounted` di `ModelSelector.tsx` + initializer deterministik di `page.tsx` (ADR 0016: Radix `useId` adalah risiko hydration).
- [x] **Gateway VPS live** — `GET /v1/models` → HTTP 200, **259 model / 25 provider**.
- [x] **Filter 3-gerbang (paid-only)** — `is_paid_only()` empiris: `gemini-3.1-pro-preview` → `True`, `gemini-2.5-pro` → `True`, `gemini-2.5-flash` / `gemini-2.5-flash-lite` / `gemini-3.1-flash-lite-preview` → `False`; cache roster berisi **0 entri "pro"**.
- [x] **Enhancement besar (sesi ini):** konteks **multi-turn** kini dikirim ke LLM (sebelumnya riwayat tersimpan tapi tidak dibaca model).
- [x] **Enhancement besar (sesi ini):** verifikasi JWT Supabase dipindah ke **lokal (JWKS)** — memperbaiki 401 massal akibat `ConnectTimeout` ke `{SUPABASE_URL}/auth/v1/user`.
- [x] **Alias env gateway** — sudah diperbaiki (`gateway_config()` memakai satu sumber, menerima `LLM_GATEWAY_URL` / `FREELM_GATEWAY_URL` / `GATEWAY_URL`).
- [x] **Test hygiene** — **61** unit test pytest hijau (angka "27"/"24" di versi lama dokumen ini
      SALAH; diukur ulang 2026-09-16: jwt 14 + filter 30 + multiturn 9 + idempotent 3 + budget 5).
      E2E produksi terakhir: **12 passed / 2 skipped / 0 failed** (10 spec sehat / 14 test,
      probe dikarantina) — 2 skip itu jalur `/chat` saat upstream Gemini RPD habis;
      perintah + angka baseline ada di §9.2 — jangan pakai angka warisan 16/1, 29,
      atau "14 passed" tanpa menjalankan ulang.

---

## 6. BELUM SELESAI (pending)

- [ ] **❗ PRIORITAS TERTINGGI — Gateway URL memakai Cloudflare *quick tunnel***
      (`benjamin-alloy-coins-speakers.trycloudflare.com`). URL ini **berganti setiap tunnel
      di-restart**. Jika URL basi: `/v1/models` mati, roster kosong, chat gagal ke provider
      non-Gemini. **Ini adalah bentuk kerapuhan produksi yang harus diselesaikan**
      (funnel/domain tetap), bukan bug kode.
- [ ] **Tailscale Funnel / URL gateway permanen** — butuh login user (belum tersedia untuk agent).
- [ ] **Rotate `GROQ_API_KEY`** — di catatan lama dilaporkan 403, **namun** bukti roster
      menunjukkan model `groq/*` justru **PASS** (mis. `groq/compound` 3.9s, `qwen/qwen3.8-27b` 0.35s)
      dan `rate-tracking` 200. `TODO: verifikasi` status kuota/403 sebenarnya sebelum rotate.
- [ ] **Billing Dodo end-to-end** — `DODO_API_KEY` / `DODO_CHECKOUT_URL` / `DODO_WEBHOOK_SECRET`
      ada di `.env`, tapi alur checkout→webhook→update tier belum diuji di produksi. `TODO: verifikasi`.
- [ ] **Kuota Gemini free-tier** — `gemini-3.1-pro-preview` RPD 0 → substitusi + badge (sudah
      benar perilakunya). Dampak: 1 test E2E di-skip eksplisit saat 503 transien.
- [x] **Spec probe dikarantina (2026-09-16)** — `tests/_*.spec.ts` → `tests/_probes/`,
      dikecualikan `testIgnore` di `playwright.config.ts`; jalankan sengaja dengan
      `E2E_PROBES=1`. Hasil run normal tetap **bukan** cakupan probe, dan probe tetap
      **tidak boleh** dipakai sebagai bukti hijau produksi.
- [ ] **Migrasi OpenNext / Cloudflare Workers — PENDING (tidak blocking sales)** — kerangka
      sudah ada (`open-next.config.ts`, `wrangler.jsonc`) dan `next.config.ts` masih
      `output: "export"` dengan komentar "TEMPORARY (deploy pipeline)". Belum bisa deploy:
      `wrangler.jsonc` masih memakai placeholder `REPLACE_WITH_YOUR_KV_NAMESPACE_ID`.
      Detail + konsekuensinya: §16.

---

## 7. TASK BERIKUTNYA (prioritas)

1. **Stabilkan URL gateway** (Tailscale Funnel / domain tetap / reverse proxy) supaya
   `LLM_GATEWAY_URL` tidak lagi bergantung pada quick tunnel. **Ini pembuka semua task lain.**
2. **Verifikasi kuota provider** (`groq`, `nvidia`) via `/api/rate-tracking` dan putuskan
   apakah perlu rotate `GROQ_API_KEY`.
3. **Uji billing Dodo end-to-end** (checkout → webhook → `users.tier` berubah) — lihat
   `billing_llm.py`, `dodo_verify.py`, tabel `users`.
4. ~~**Rapikan test probe** `tests/_*.spec.ts`~~ → **SELESAI 2026-09-16**: dikarantina ke
   `tests/_probes/` + `testIgnore` (dijalankan hanya dengan `E2E_PROBES=1`).
5. **Commit + push** setiap perubahan; lalu verifikasi produksi (Cloudflare Pages + Railway).

> Catatan: klaim template *"Push 5 commit ahead origin"* **salah** — sudah 0 ahead/0 behind.
> Jangan ulangi pekerjaan itu.

---

## 8. ENV VARS YANG DIPAKAI

> **Aturan:** hanya **NAMA** variabel yang boleh ditulis di dokumen ini. **JANGAN pernah**
> menyalin nilai/secret ke chat, commit, atau dokumen. File `.env` sudah di-ignore git.

### Frontend (`nexus-frontend/.env.local`)

| Nama | Fungsi |
|---|---|
| `NEXT_PUBLIC_API_URL` | Base URL backend FastAPI (produksi: `https://web-production-dc90b.up.railway.app`) |
| `NEXT_PUBLIC_SUPABASE_URL` | URL project Supabase (milik user) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon key Supabase (publik, aman di bundle) |

### Backend / root `.env` (nama saja)

| Nama | Catatan |
|---|---|
| `LLM_GATEWAY_URL` | **variabel yang benar-benar dipakai** (berisi host `*.trycloudflare.com`) |
| `LLM_GATEWAY_KEY` | key gateway (format `fgk-...`) |
| `LLM_GATEWAY_MODELS` | override daftar model gateway (opsional) |
| `FREELM_GATEWAY_URL`, `GATEWAY_URL` | alias **didukung** oleh `gateway_config()` — saat ini kosong |
| `GEMINI_API_KEY`, `GEMINI_KEY_1`..`GEMINI_KEY_10`, `GOOGLE_API_KEY` | multi-key Gemini |
| `NVIDIA_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY` | provider lain |
| `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_DB_PASSWORD` | Supabase |
| `SUPABASE_JWKS` | **public key JWKS** hasil seed (memungkinkan verifikasi JWT offline saat DNS bermasalah) |
| `CORS_ORIGIN` | origin yang diizinkan FastAPI |
| `DODO_API_KEY`, `DODO_CHECKOUT_URL`, `DODO_WEBHOOK_SECRET` | billing Dodo |
| `PAYMENT_PORTAL_URL` | link portal pembayaran |
| `NINEROUTER_EXTERNAL_URL`, `NINEROUTER_KEY` | konfigurasi Ninerouter |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | deploy Cloudflare Pages |
| `GITHUB_TOKEN` | **fine-grained PAT, TIDAK punya akses ke repo ini** (lihat §13). Push memakai kredensial embedded di `.git/config` |
| `VAULT_PASSWORD`, `VAULT_SECRET_KEY` | vault kredensial user |
| `VPS_IP`, `VPS_USERNAME`, `VPS_PASSWORD`, `VPS_OS` | akses VPS |

**Peringatan env alias:** kode menerima **ketiga** nama (`LLM_GATEWAY_URL`,
`FREELM_GATEWAY_URL`, `GATEWAY_URL`). Jangan "memperbaiki" alias ini lagi — sudah beres.
Jangan pula menambah nama keempat tanpa alasan.

---

## 9. TEST METHODOLOGY (PENTING)

### 9.1 Aturan dasar

- **WAJIB uji di build produksi**, bukan `next dev`.
  - `next dev` menyajikan perilaku berbeda: env `NEXT_PUBLIC_*` di-inline saat build,
    kode terminifikasi, dan hydration berjalan beda. Bug (mis. hydration mismatch,
    bundle membidik origin salah) **hanya muncul di produksi**.
  - Karena app ini `output: "export"` (static export untuk Cloudflare Pages), `next start`
    **DITOLAK** oleh Next.js (terbukti empiris: `[Error: "next start" does not work with
    "output: export" configuration. Use "npx serve@latest out" instead.]`). Bentuk produksi
    setara = "build lalu serve `out/` statis": `npm run build` + **`npm run serve:static`**
    (= `scripts/serve-out.mjs`, port 3000).
  - `scripts/e2e-prod-server.mjs` adalah **pembungkus** untuk E2E: menjalankan `next build`
    dengan `NEXT_PUBLIC_API_URL` ditimpa ke backend lokal, lalu import `serve-out.mjs`.
- **Port: 3000 (FE) dan 8123 (BE — DEDIKAT E2E).** Port 8000 hanya untuk backend dev/manual.
  Jangan pakai 3001 — CORS backend menolaknya.
- **Playwright = sumber kebenaran E2E.** `playwright.config.ts` menyalakan **dua** `webServer`:
  backend lokal (`python -m uvicorn api_server:app --app-dir .. --host 127.0.0.1 --port 8123`)
  dan FE produksi (`node scripts/e2e-prod-server.mjs`). Probe dikecualikan lewat
  `testIgnore: ["**/_probes/**"]`, sehingga run normal = 10 spec sehat / 14 test.
  Keduanya `reuseExistingServer: false` **secara sengaja**: server lama yang masih hidup pernah
  membuat hasil tes menyesatkan (lulus dari kode basi).
- **Selalu tangkap response body sebelum memperbaiki apa pun.** Trace Playwright
  (`trace: "retain-on-failure"`) menyimpan `trace.zip` berisi `.network`, `.trace`, dan DOM
  snapshot — dari sana bisa dibaca header `Authorization` dan body error asli.
- **Jangan percaya gejala, percaya payload.** Contoh nyata di sesi ini: "Ada masalah, coba lagi"
  ternyata `HTTP 503 {"detail":"Model sedang sibuk (quota/overload)"}`, bukan bug UI.

### 9.2 Perintah uji

```bash
# Unit test backend (tanpa jaringan) — 61 test
cd c:/Users/user/Proyek_AI
python -m pytest test_security_jwt.py test_model_filter.py test_multiturn_history.py test_idempotent_add_message.py test_chat_budget_invariant.py -q

# E2E produksi (build + serve out/ + backend lokal) — 12 passed / 2 skipped / 0 failed
cd c:/Users/user/Proyek_AI/nexus-frontend
npm run e2e:prod

# Sesi Supabase untuk E2E (harness; mint sesi SAH, menyingkirkan fixture palsu)
node scripts/e2e-auth-setup.mjs
```

### 9.3 Menyuntik sesi auth untuk E2E

Playwright menyuntik `localStorage` key `sb-<ref>-auth-token` = **JSON session Supabase**
(bukan base64) lewat `page.addInitScript` di `tests/model-filter.spec.ts::seedSession()`.
Harness mint sesi memakai `e2e-auth-setup.mjs` → `_e2e_storage.json`.
Harness ini **memverifikasi signature tiap kandidat** terhadap JWKS sebelum dipakai:
fixture yang `exp`-nya disunting tanpa tanda tangan baru (mis. buatan `_e2e_extend.py`)
dipindahkan ke `_e2e_session*.FORGED.json` dan TIDAK dipakai. Bila tidak ada kandidat
yang sah, sesi di-mint baru secara sah (`admin.createUser` + `signInWithPassword`).
Catatan GoTrue: `hashed_token` berada di **top-level** respons `generate_link`
(bukan di dalam `properties`) di versi ini.

### 9.4 Peringatan instrumen

- `AppTest` Streamlit sudah **tidak relevan** (UI legacy `app_frontend.py`).
- Spec probe sekarang berada di `tests/_probes/_*.spec.ts` dan **dikecualikan** dari run
  normal (`testIgnore`); jalankan sengaja dengan `E2E_PROBES=1`. Isinya tetap probe
  diagnostik **lokal** — jangan dipakai sebagai bukti produksi hijau.
- `pytest-playwright` ada di `requirements.txt` untuk E2E Python lama; E2E aktif sekarang
  memakai **Playwright TS** di `nexus-frontend/tests`.

---

## 10. JANGAN DILAKUKAN (larangan keras)

| # | Larangan | Alasan (dari pengalaman nyata sesi ini) |
|---|----------|------------------------------------------|
| 1 | **JANGAN** menguji hanya dengan `next dev` | `next dev` tidak meng-inline env `NEXT_PUBLIC_*`, tidak terminifikasi, dan hydration-nya berbeda. Bug hydration + "bundle membidik origin lain" hanya muncul di build produksi. Playwright repo ini sudah benar: `scripts/e2e-prod-server.mjs` = build + serve `out/`. |
| 2 | **JANGAN** hardcode allowlist model | Roster model harus berasal dari probe empiris (`gateway_roster.py` + `.gw_roster_cache.json`). Model gratis hidup/mati berubah setiap hari; allowlist statis akan langsung basi. |
| 3 | **JANGAN** menyalin kode dari OmniRoute | Hanya dipakai sebagai *referensi pola* (3-gate filter, issue #6495). Menyalin utuh membawa lisensi & beban maintenance yang tidak diinginkan. |
| 4 | **JANGAN** memigrasi gateway | Gateway VPS sudah live (259 model / 25 provider). Migrasi = downtime + risiko kehilangan roster hasil probe. |
| 5 | **JANGAN** menempel API key ke chat | Semua kredensial ada di `.env` (root) dan `nexus-frontend/.env.local`. Di dokumen ini hanya **nama** variabel yang ditulis. |
| 6 | **JANGAN** melewati verifikasi endpoint | "Sudah jalan" tanpa `curl`/trace = asumsi. Kasus nyata: mode gagal terlihat seperti bug UI ("Ada masalah, coba lagi") padahal HTTP 503 upstream. |
| 7 | **JANGAN** mengandalkan `reuseExistingServer: true` | Server lama (dev server di :3000, atau backend yang di-start sebelum edit terakhir) pernah membuat hasil tes **hijau palsu** dari kode basi. |
| 8 | **JANGAN** memakai port 3001 untuk FE | CORS backend mengizinkan `:3000` (dan origin Cloudflare); `:3001` diblokir browser. |
| 9 | **JANGAN** mematikan verifikasi JWT demi "biar jalan" | Verifikasi lokal (JWKS) **bukan** pengganti keamanan: signature tetap diverifikasi, hanya jalur jaringan yang dihilangkan. |
| 10 | **JANGAN** menganggap `pytest-playwright` sebagai E2E aktif | E2E aktif sekarang = **Playwright TS** di `nexus-frontend/tests`. `pytest-playwright` hanya warisan E2E Python lama. |

---

## 11. FILES YANG SERING DIUBAH

### Backend (root repo)

| File | Perannya | Sentuh saat |
|------|----------|-------------|
| `api_server.py` | FastAPI gateway: `/chat`, `/models`, `/sessions`, `/messages`, `/integrations`, `/health`. Menyusun prompt + `meta` transparansi. | Menambah field meta, mengubah kontrak endpoint, memperbaiki alur history. |
| `security.py` | Verifikasi JWT Supabase. Berisi `get_supabase_user()` (jaringan) + `_decode_local()`/`_get_jwks()` (lokal, cache disk + env `SUPABASE_JWKS`). | Menyentuh autentikasi/otorisasi. **Wajib** jalankan `test_security_jwt.py`. |
| `database.py` | Lapisan Supabase: `list_sessions`, `get_messages`, `add_message` (idempoten), `save_integration`, `get_integration`. | Perubahan skema/kueri DB. |
| `gateway_roster.py` | Roster model berbasis probe + `is_paid_only()` (3-gate) + cache `.gw_roster_cache.json`. | Filter model, daftar model di selector. |
| `model_discovery.py` | Discovery model Gemini langsung dari API. | Model Gemini baru/berubah. |
| `agent_engine.py` / `tools.py` | Mesin agen + tool calling (WhatsApp, Sheets, Gmail, Calendar) + `CredentialMissingError`. | Menambah tool/agentic loop. |
| `app_frontend.py` | UI Streamlit **legacy** (bukan entry produksi lagi). | Hanya untuk demo/arsip. |

### Frontend (`nexus-frontend/`)

| File | Perannya | Sentuh saat |
|------|----------|-------------|
| `src/app/page.tsx` | Halaman chat utama: state pesan, submit prompt, render bubble + **credential form** inline. | Logika chat / UX empty-state. |
| `src/components/ModelSelector.tsx` | Dropdown model (gate `mounted` untuk hydration) + badge locked. | Persoalan hydration / daftar model UI. |
| `src/lib/api.ts` | `apiFetch` — wrapper fetch + `Authorization: Bearer <token>` dari sesi Supabase. | Perubahan header/endpoint/CORS. |
| `src/lib/models.ts` | Metadata model + fallback lokal `CHAT_MODELS`. | Model baru, label/badge. |
| `src/features/builder/` | Kanvas React Flow (node Trigger/Agent/MCP Tool) + simpan alur JSON. | Fitur Builder. |
| `src/context/auth.tsx` | AuthContext Supabase (`email`, `loading`, `getToken`, sign-in/out). | Alur login/logout. |
| `playwright.config.ts` | Dua `webServer` (BE **8123** — port DEDIKAT E2E; FE produksi via `e2e-prod-server.mjs`) — sumber kebenaran E2E. Port 8000 hanya untuk BE dev/manual. | Cara menjalankan tes. |

### Test (jangan dihapus)

| File | Isi |
|------|-----|
| `test_security_jwt.py` | 14 test JWT offline (HS256/ES256, JWKS seed, kontrak 401 vs 503, path invalid). |
| `test_multiturn_history.py` | Membuktikan riwayat dikirim ulang ke LLM. |
| `test_idempotent_add_message.py` | Anti-duplikasi pesan. |
| `nexus-frontend/tests/*.spec.ts` | Suite E2E produksi: **10 spec sehat** (14 test) — `npm run e2e:prod` → **12 passed / 2 skipped / 0 failed** (2 skip = `/chat` saat upstream 503). |
| `nexus-frontend/tests/_probes/_*.spec.ts` | 3 probe diagnostik, **dikarantina** (`E2E_PROBES=1`). |
| `test_model_filter.py` | **30** test deterministik filter paid-only + input kotor (tanpa jaringan/JWKS). Pengganti cakupan "tidak over-delete" yang dulu digantungkan pada roster live yang flaky. |
| `test_chat_budget_invariant.py` | **5** test anggaran waktu `/chat` ↔ kesabaran klien. **Membaca `FETCH_TIMEOUT_MS` langsung dari `src/lib/api.ts`**, jadi drift antara konstanta backend (Python) dan frontend (TS) GAGAL di sini — bukan diam-diam di produksi. |

---

## 12. KNOWLEDGE BASE (hasil riset & temuan empiris)

Semua butir di bawah **sudah terpakai di kode** kecuali yang ditandai `TODO: verifikasi`.
Butir 6–8 berasal dari riset eksternal (rujukan pola) dan **wajib diverifikasi ulang**
sebelum dijadikan dasar keputusan besar.

1. **Kuota Gemini free-tier (keluarga `google_gemini`, bukan `google`)**
   - Flash: ~20 RPD · Flash-Lite: ~500 RPD · **Pro: 0 RPD** → karena itu filter
     `is_paid_only()` **wajib**: model Pro tidak boleh muncul sebagai pilihan hidup.
   - Nama keluarga provider yang benar adalah **`google_gemini`**; memakai `"google"`
     membuat pencocokan provider gagal diam-diam.
   - `TODO: verifikasi` angka RPD persisnya (Google mengubah kuota tanpa pengumuman).

2. **Model paid-only harus disaring berlapis (3-gerbang)** — pola dari OmniRoute #6495:
   (a) **pola nama** (mis. regex `pro`, `nano-banana`, `lyria`, `robotics`, `transcribe`),
   (b) **allowlist keluarga gratis** yang diketahui hidup, (c) **flag pricing** dari gateway.
   Satu gerbang saja pernah meloloskan model Pro ke selector produksi.

3. **Fallback senyap = masalah kepercayaan** (pola dari hermes #60046).
   Jika gateway mensubstitusi model tanpa memberi tahu user, user mengira memakai model
   yang ia pilih. Solusi yang sudah diterapkan: `meta.requested_model` + `meta.fallback` +
   `meta.fallback_reason`, lalu badge UI **"Model yang Anda pilih tidak tersedia"**.

4. **Radix `Slot` + `useId` = risiko hydration** (ADR 0016).
   `useId` menghasilkan id berbeda antara server dan client pada React 19 + static export.
   Solusi: gate `mounted` (render pertama deterministik) + initializer deterministik di
   `page.tsx`. Bukti: `HYDRATION_HITS=0`, `PAGEERRORS=[]`.

5. **Verifikasi JWT Supabase jangan bergantung pada jaringan.**
   `client.auth.get_user()` memanggil `{SUPABASE_URL}/auth/v1/user`. Bila DNS/ISP
   bermasalah → `ConnectTimeout` → **semua endpoint ber-JWT balas 401** (gejala user:
   "Ada masalah, coba lagi"). Solusi: verifikasi **lokal** dengan JWKS (cache disk +
   env `SUPABASE_JWKS`); signature tetap diverifikasi, hanya jalur jaringan yang hilang.
   Dua bug nyata yang muncul saat pindah ke jalur lokal:
   - `_decode_local` memanggil `jwt.decode` **tanpa** `audience` → token Supabase asli
     (selalu membawa `aud: "authenticated"`) ditolak `InvalidAudienceError` (kasus HS256).
   - `aud=None` **memasukkan** klaim `aud: null` alih-alih menghilangkannya.

6. **Gateway free-llm-gateway menyediakan** `GET /v1/models` (roster) dan
   `GET /api/rate-tracking` (kuota per provider). Terverifikasi: `/v1/models` → HTTP 200,
   **259 model / 25 provider**.

7. **Playwright untuk app `output: "export"`** — `next build && next start` **tidak berlaku**
   (Next menolak `next start` tanpa server render; pesan errornya literal:
   `"next start" does not work with "output: export" configuration`). Bentuk produksi setara:
   `next build` lalu serve `out/` statis. Untuk E2E dipakai pembungkus
   `scripts/e2e-prod-server.mjs` (build + serve); untuk uji manual: `npm run build` +
   `npm run serve:static`.

8. **Tunnel `trycloudflare` bersifat sementara** — URL berganti setiap restart dan tidak
   cocok untuk produksi. Pilihan permanen: Tailscale Funnel, Cloudflare Named Tunnel,
   atau reverse proxy di VPS dengan domain sendiri.

9. **`hashed_token` GoTrue berada di top-level** respons `generate_link` (bukan di dalam
   `properties`) pada versi SDK yang dipakai. Salah baca → mint sesi E2E gagal.

10. **Idempotensi penyimpanan pesan** diperlukan karena UI melakukan retry/refetch;
    tanpa guard, satu pesan bisa tersimpan dua kali (lihat `test_idempotent_add_message.py`).

---

## 13. RESOURCES / REFERENSI

| Sumber daya | Nilai |
|-------------|-------|
| Repo GitHub | `github.com/vraafi/nexus-agent-core` (branch `main`) |
| Frontend produksi | `https://proyek-agent.pages.dev` (Cloudflare Pages, static export) |
| Backend produksi | `https://web-production-dc90b.up.railway.app` (Railway; auto-deploy dari `main`) |
| Gateway LLM | **Cloudflare quick tunnel** `benjamin-alloy-coins-speakers.trycloudflare.com` — lihat `.env` (`LLM_GATEWAY_URL`). **Rentan berganti.** |
| Supabase | `https://qmukkphwaajzbqjrcvaz.supabase.co` (nilai di `.env` / `nexus-frontend/.env.local`) |
| Dokumen internal | `ARCHITECTURE_REPORT.txt` (arsitektur + gap analysis), `HANDOFF.md` (dokumen ini) |
| Konfigurasi frontend | `nexus-frontend/.env.local` (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`) |
| Log/trace E2E | `nexus-frontend/test-results/**` (`trace.zip`, `error-context.md`, screenshot) |
| Cache runtime (tidak di-commit) | `.jwks_cache.json` (JWKS, TTL 6 jam) · `nexus-frontend/.gw_roster_cache.json` (roster) |

> **Catatan keamanan (penting):** `GITHUB_TOKEN` di `.env` adalah **fine-grained PAT tanpa
> akses ke repo ini** (HTTP 404 saat mengakses repo). Push berhasil karena remote `origin`
> menyimpan kredensial token lain yang masih valid.
> `TODO: verifikasi` umur token tersebut sebelum mengandalkannya.

---
## 14. QUICK START (untuk chat baru)

Urutan yang disarankan, jangan dilompati:

1. **Baca dua dokumen ini lebih dulu**: `HANDOFF.md` (dokumen ini) dan
   `ARCHITECTURE_REPORT.txt`. Dokumen ini memuat status + larangan; laporan arsitektur
   memuat peta sistem dan gap analysis.
2. **Cek riwayat commit** agar tahu titik terakhir pekerjaan:
   ```bash
   git --no-pager log --oneline -5
   ```
3. **Cek working tree bersih atau tidak** (jangan menimpa pekerjaan yang belum di-commit):
   ```bash
   git --no-pager status -sb
   ```
4. **Verifikasi klaim di section 6 & 7 secara empiris** sebelum mengerjakan — beberapa
   butir di dokumen ini bisa sudah usang karena sprint ini banyak perubahan. Jangan
   percaya pada klaim tanpa bukti; jalankan perintah/probe yang relevan lebih dulu.
5. **Jalankan unit test backend** (cepat, tanpa jaringan) sebagai baseline sehat:
   ```bash
   python -m pytest test_security_jwt.py test_multiturn_history.py test_idempotent_add_message.py -q
   ```
   Baseline terakhir (diukur 2026-09-16): **61 test lulus** — jwt 14 + filter 30
   + multiturn 9 + idempotent 3 + budget 5. Jalankan perintah LENGKAP di atas (jangan
   menghilangkan `test_model_filter.py`, akibatnya hitungan jadi 26 dan
   cakupan filter hilang). Angka warisan "27"/"24"/"25+4 diagnostik" SALAH.
6. **Jalankan E2E produksi** hanya bila mengubah frontend/endpoint:
   ```bash
   cd nexus-frontend && npm run e2e:prod
   ```
   Baseline terakhir: **12 passed / 2 skipped / 0 failed** (10 spec sehat; 3 spec probe
   dikecualikan). **Baca arti skip-nya**: kedua test `/chat` memanggil model roster dan
   akan SKIP bila upstream menjawab 503 (`CHAT_STATUS=503`), karena RPD Gemini jalur
   cadangan habis — itu perilaku yang DISENGAJA (bukti payload tercetak di log), bukan
   lulus. Run sehat pernah tercatat `CHAT_STATUS=200`. Ingat: E2E butuh sesi Supabase segar
   (lihat section 9.3) dan `webServer` akan membangun ulang aplikasi.
7. **Tanya user: task mana yang mau dilanjutkan** (rujuk section 7) — jangan mengarang
   prioritas sendiri karena ada dependency antar-butir (mis. perbaikan filter menyentuh
   `gateway_roster.py` yang dipakai badge/selector).

### Alur kerja yang terbukti efektif di sesi sebelumnya

1. **Kumpulkan bukti dulu, jangan menebak.** Gejala UI sering menyesatkan
   (contoh nyata: "Ada masalah, coba lagi" ternyata bukan bug frontend, melainkan
   401 backend karena verifikasi JWT butuh jaringan).
2. **Tuliskan hipotesis, lalu uji dengan probe kecil** (skrip `_*.py` sekali pakai,
   sudah masuk `.gitignore`) sebelum mengubah kode produksi.
3. **Ubah kode sesedikit mungkin**, lalu jalankan verifikasi yang sama dengan yang
   dipakai untuk menemukan masalah (A/B: jalur rusak vs jalur benar).
4. **Commit + push** per perbaikan logis (pesan commit menjelaskan *mengapa*, bukan hanya apa):
   ```bash
   git add <file> && git -c user.name='Nexus Agent' -c user.email='deploy@nexus.local' \
     commit -m "fix(<scope>): <alasan singkat>"
   git push origin main
   ```
5. **Perhatikan efek deploy**: backend Railway auto-deploy dari `main`
   (±1–3 menit); frontend Cloudflare Pages **static export** sehingga
   perubahan `NEXT_PUBLIC_*` **butuh build + deploy ulang**, bukan sekadar push.

---

## 15. KONTAK / USER INFO

Tabel di bawah menjelaskan **cara berkomunikasi** — mohon disesuaikan agar jawaban
langsung berguna, bukan sekadar teknis benar.

| Aspek | Kondisi | Implikasi untuk agent |
|-------|---------|-----------------------|
| Bahasa | **Bahasa Indonesia** (istilah teknis boleh Inggris) | Jawab dalam Bahasa Indonesia; jelaskan istilah asing singkat. |
| Latar belakang | SMK otomotif, **bukan** lulusan IT formalk | Hindari jargon tanpa penjelasan; pakai analogi bila perlu. |
| Kemampuan teknis | Praktis, cepat menangkap perintah & alur terminal | Boleh langsung memberi perintah/alat; tidak perlu menyederhanakan berlebihan. |
| Bahasa Inggris | Terbatas | Jangan sajikan dokumentasi berbahasa Inggris mentah tanpa ringkasan Indonesia. |
| Gaya belajar | Lebih suka **bukti empiris** (output terminal, screenshot, trace) | Selalu tunjukkan keluaran nyata, bukan klaim. |
| Sensitivitas biaya | **Tinggi** (modal dari orang tua) | Prioritaskan solusi gratis/murah; jelaskan biaya sebelum menyarankan layanan berbayar. |
| Target waktu | Penjualan pertama **±Rp 1 juta dalam 15 hari** | Utamakan fitur yang menghasilkan penjualan (onboarding, billing, keandalan) di atas refactor kosmetik. |
| Pasar awal | Agency di Indonesia dulu, baru pasar US | Prioritas fitur & bahasa UI: Indonesia dulu. |
| Preferensi kerja | Aktif, ingin agent bekerja otonom lalu melapor | Kerjakan sampai tuntas, laporkan hasil dengan bukti; tanya hanya bila benar-benar ambigu. |

### Cara melaporkan hasil (disukai user)

- **Ringkas + bukti**: apa yang berubah (file), apa hasilnya (angka/output terminal).
- **Sebutkan koreksi**: bila klaim lama ternyata salah, katakan **"koreksi"** secara
  eksplisit beserta buktinya — user menghargai kejujuran ini.
- **Jangan mengklaim tanpa menjalankan**; kalau belum diuji, tulis `TODO: verifikasi`.
- **Hindari menyebutkan isi rahasia**: untuk `.env`, tulis **nama variabel saja**,
  jangan pernah menempelkan nilainya.

### Yang perlu dikonfirmasi user di chat baru

1. Task mana dari section 7 yang dikerjakan lebih dulu.
2. Apakah ada perubahan keadaan di luar repo (mis. URL tunnel gateway berubah,
   token/kredensial dirotasi, atau VPS/Tailscale sudah login).
3. Apakah targetnya "fitur jalan" (demo/sales) atau "rapi/aman" (hardening) —
   keduanya memberi kompromi berbeda.

---

> **Status dokumen:** ditulis ulang pada sprint ini berdasarkan **verifikasi langsung**
> terhadap repo, `.env` (nama variabel saja), hasil unit test, dan hasil E2E. Butir yang
> tidak dapat diverifikasi dari dalam repo ditandai `TODO: verifikasi` — jangan
> memperlakukannya sebagai fakta.

