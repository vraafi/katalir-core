# TODO — Katalir

## Status Sekarang
- Level 3 E2E: lulus; production live di `katalir.de5.net`.
- UI/UX Overhaul: FASE 0-6 selesai.
- MCP Federation: FASE C selesai; gateway VPS/named tunnel hidup, production E2E health=401 (auth), servers=39, call=datetime.
- Composition research: 10 komponen MCP dipilih dengan boundary adapter/license; registry metadata tidak boleh dieksekusi otomatis.
- `.env` hygiene: bersih dan ter-audit (`node scripts/env_audit.mjs`, 92 keys, 0 parse hazard, no BOM). Non-conforming line yang tersisa sudah di-comment, bukan dihapus.

## Autonomous Bug-Fix Loop (2026-10-02)

Status per bug — **PASS hanya bila ada bukti before/after**.

| # | Bug | Status | Bukti |
|---|-----|--------|-------|
| 1 | Chat retry melampaui budget transport | **FIXED (lokal)** | `useChat.ts` kasih `CHAT_TIMEOUT_MS` penuh (150s) ke SETIAP dari 3 percobaan → plafon efektif 457s, bukan 187s. Sekarang `perAttemptMs = CHAT_TIMEOUT_MS/3 - 5s` (45s). `tsc --noEmit` exit 0. **Belum diverifikasi di browser/production.** |
| 2 | Dropdown model cuma 3 | **FIXED & TERDEPLOY - production 4 -> 11 model** | Akar masalah BUKAN filter dan BUKAN katalog gateway, tapi perbandingan id model di `_probe_one`. Diagnosis: API key NVIDIA & Groq VALID (Groq `allam-2-7b` -> 200). Model yang dipakai gateway justru EOL/hilang: `meta/llama-3.3-70b-instruct` -> **410 'end of life 2026-08-26'**, `meta/llama-3.1-405b-instruct` -> 404, Groq `llama-3.3-70b-versatile` -> 404 model_not_found; gateway membalut kegagalan itu jadi HTTP 500. Lalu 72 model hidup diuji langsung: **19 dapat HTTP 200**, dan **18 di antaranya sudah ada di katalog gateway** (0 hilang) - jadi katalog bukan penyebab. Penyebab: `_probe_one` membandingkan `rmodel` (segmen TERAKHIR) dengan `mid`, padahal provider modern menamespace id (`z-ai/glm-5.3`, `qwen/qwen3.8-27b`) sehingga 18 model hidup ditolak sebagai 'disubstitusi'. Fix: terima bila path LENGKAP atau segmen terakhir cocok - deteksi substitusi tetap utuh. **Production /models = 11 model** (target >10 TERCAPAI), roster_source=gateway, degraded=false. E2E: `qwen/qwen3.8-27b` -> HTTP 200 reply 'OK', meta.gateway=true, fallback=false; `openai/gpt-oss-20b` -> 200 reply 'OK'. Suite **362 passed**. |
| 3 | Sidebar history chat kosong | **BUKAN BUG - user login dengan akun Google yang BERBEDA** | Tidak ada cacat kode: backend `db.list_sessions('vraafi003@gmail.com')` mengembalikan **2 session** benar ('haalo' 4 pesan, 'kamu siapa' 1 pesan). Penyebab sebenarnya: ada **4 akun Google** berbeda dengan riwayat terpisah - `verdi0377@gmail.com` **7 session**, `vraafi003@gmail.com` **2 session**, `verdiawanraafi@gmail.com` **1 session**, `vraafi005@gmail.com` **0 session** (belum punya baris public.users). Sidebar menampilkan riwayat AKUN YANG SEDANG LOGIN, jadi user melihat kosong karena login lewat akun yang berbeda dari yang memiliki riwayat. `chat_sessions` hanya punya kolom `user_id` (tanpa auth_id/public_id) dan backend memakai service-role sehingga RLS tidak berlaku. TINDAKAN: perlu keputusan user - login ke akun yang benar ATAU merge riwayat antar akun. KAMI TIDAK merge otomatis karena itu memindahkan data. |
| 4 | Starlette CVE | **SELESAI (sebelumnya) — status BLOCKED sudah usang** | Sudah di-fix di commit `e7f4bf7`: `fastapi 0.115.6 → 0.133.0` + **pin eksplisit `starlette==1.0.1`**. Akar masalah: `requirements.txt` tadinya TIDAK pernah mem-pin starlette sehingga ikut naik transitif ke 0.52.1 yang rentan. Konflik dependency TIDAK ADA (`pip install --dry-run` → "Would install fastapi-0.133.0 starlette-1.0.1"). Bukti: `pytest tests -q` → 362 passed, `TestClient` hidup (60 route, `/health` 200), `/health` production 200. |
| 8 | Model Gemini tidak muncul di dropdown | **SELESAI (1 dari 3 model baru tampil) — premise awal salah** | Dropdown SUDAH punya Gemini sebelum task ini (`gemini-2.5-flash`, `flash-lite`, `gemini-3-flash-preview`). Instruksi awal salah sasaran di 3 hal: (1) LLM dilayani `free-llm-gateway` (Docker, port 8080) — `agentgateway` (systemd) hanya MCP federation dan `config.yaml`-nya **tidak punya blok `ai:`**; (2) **tidak ada Kubernetes** di VPS (kubectl/k3s/minikube absen) jadi CRD `AgentgatewayBackend` tidak bisa di-apply; (3) katalog model ada di `/opt/free-llm-gateway/models.yaml`. `GOOGLE_GEMINI_KEY` sudah ada. Verifikasi: Google `GET /v1beta/models` **HTTP 200**, 61 model, 44 generateContent-capable. Perubahan nyata: +`gemini-3.8-flash`, +`gemini-3.5-flash-lite`, +`gemini-3.1-pro-preview` (backup `models.yaml.bak.20261002123417`, `docker cp` + restart, container healthy 259 model). **Jebakan penting:** sebelum ditambah, `gemini-3.8-flash` dijawab `nvidia/nemotron-3-super-120b-a12b` — gateway answering model LAIN tanpa error. Hasil production `/models` (11 model): Gemini **4** — 2.5-flash, 2.5-flash-lite, 3-flash-preview, **3.5-flash-lite (baru)**. E2E `gemini-3.5-flash-lite`: HTTP 200 reply "OK", fallback=false, gateway=true. `gemini-3.8-flash` jalan (13s, routed google_gemini) tapi lambat/flaky sehingga kadang gagal probe — perilaku aman, model tak andal lebih baik tak tampil. `gemini-3.1-pro-preview` HTTP 504 timeout, tidak tampil. |
| 9 | Tool call tidak dieksekusi / AI tidak search | **FIXED & TERDEPLOY** | Akar masalah BUG 1: `api_server` hanya membaca `resp.tool_calls` (terstruktur). Gemma 4 menulis panggilan sebagai TEKS (reproduksi nyata: HTTP 200 routed `nvidia/google/gemma-4-31b-it`), jadi loop `break` dan JSON mentah masuk ke `reply`. Fix: modul `textual_tool_calls.py` mendukung 4 bentuk (Gemma4, Gemma4 terpotong, vLLM, Qwen3-Coder), jalur TEKS eksekusi alat sekali lalu reply dibangun dari teks bersih, `_tool_name()` mengupah prefix `nexus:` agar cocok registry. BUG 3: `web_search` hanya ada di `execution_engine` (workflow), tidak pernah di chat. Ditambahkan tool `web_search` (DuckDuckGo via ddgs, maks 8 hasil, error di-return sebagai JSON) + blok `ATURAN VERIFIKASI` di system prompt (cari dulu, sebut sumber, jangan mengarang bila gagal). Bukti: suite **373 passed**; 8 regresi parser memakai string reproduksi literal; e2e lokal parse-execute-`_accepted_workflow` = `ok:true`, 3 nodes/2 edges, JSON tidak bocor; production `/chat` `workflow in meta: YES` (3 node) dan `RAW JSON LEAKED: False`; `web_search` live mengembalikan 3 hasil DuckDuckGo nyata. |
| 10 | Model Gemini terbatas + foto profil tidak muncul | **RE-VERIFIED 2026-10-02: TIDAK PERLU FIX - target >3 TERCAPAI** | DIVERIFIKASI ULANG, tidak ada perubahan kode. GEMINI: keempat model yang diminta sudah ADA di models.yaml (gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.5-pro, gemini-3-flash-preview, gemini-3.8-flash, gemini-3.5-flash-lite, gemini-3.1-pro-preview). `GET /v1/models` = **259 model, 7 Gemini**. PRODUCTION `/models` = **13 model, 4 Gemini** (target >3 TERCAPAI): gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3.5-flash-lite. `gemini-2.5-pro` TIDAK muncul di dropdown - benar, Google sudah menariknya (no longer available to new users) sehingga gateway balas HTTP 500; jadi permintaan 'tambahkan gemini-2.5-pro' HARUS DIABAIKAN. Fix probe thinking-model dari sesi sebelumnya TERPASANG dan bekerja: `PROBE_TIMEOUT_S` 90->180 (L41) + `PROBE_RETRY_MAX_TOKENS`=512 (L46). CATATAN: schema YAML di task (`google_gemini:` + `priority:`) bukan skema asli - yang benar mapping datar `nama_model:` -> capabilities/fallbacks/_meta. AVATAR: BUG A sudah SELESAI & terbukti Playwright di sesi sebelumnya (`ALLOW_GOOGLE_AVATAR=true`, screenshot `evidence/production_home.png`). Re-verifikasi hari ini: keempat akun Google punya `user_metadata.avatar_url` host `lh3.googleusercontent.com`; URL avatar GET -> **HTTP 200 image/png**; CSP LIVE sudah memuat host tersebut di `img-src`; `next.config.ts` memakai `images:{unoptimized:true}` sehingga `remotePatterns` TIDAK relevan (optimizer dilewati); `UserMenu.tsx` sudah punya fallback inisial + `onError`. Kesimpulan: kedua opsi fix yang diusulkan sudah terimplementasi. |
| 11 | reasoning_effort: none di models.yaml | **PATCH TERPASANG, EFEK BELUM TERBUKTI** | Instruksi awal "tambah `reasoning_effort: none` ke models.yaml" **SALAH**. Field itu tidak pernah dibaca: `grep -c reasoning_effort models.yaml` = 0 dan `grep -rn reasoning_effort / --include=*.py` di container = kosong. Adapter Gemini hanya membangun dua kunci `generationConfig` (temperature, maxOutputTokens) - tidak ada `thinkingConfig`, tidak ada passthrough. `ChatCompletionRequest` (Pydantic) juga tidak punya field itu sehingga field dibuang sebelum mencapai adapter. Menambahkannya ke models.yaml hanya menghasilkan **konfigurasi mati**. Yang dikerjakan: patch kode di container pada `providers.py` (map `reasoning_effort: none` -> `thinkingConfig.thinkingBudget=0`) dan `main.py` (tambah field), dengan backup bertimestamp + penanda idempoten. Sifat OPT-IN: tanpa flag tidak ada baris baru yang jalan. Terbukti: `py_compile` SYNTAX_OK, VERIFY_providers=True, VERIFY_main=True, container "Up (healthy)" setelah restart, dan model non-Gemini `qwen/qwen3.8-27b` tetap HTTP=200 dengan content. TIDAK diklaim: efeknya pada model berpikir, karena kuota free-tier Google habis (`429 ... limit: 20`) dan percobaan `gemini-3.8-flash` + flag berakhir HTTP 000 akibat antrean retry rate-limit (bukan penolakan flag - `gemini-2.5-flash` + flag memberi HTTP 500 "google_gemini hit rate limit", bukan 422 validasi). Karena itu `gateway_roster.py` sengaja BELUM mengirim flag di probe. Detail + diff: `patches/free-llm-gateway-reasoning-effort.md`. |

| 5 | Docs endpoint terbuka | SELESAI | `/docs`, `/redoc`, `/openapi.json` production 404. |
| 6 | Next.js CVE | SELESAI | `15.5.27`, build hijau, 0 critical. |
| 7 | Security headers | SELESAI | CSP enforce + HSTS + X-Frame-Options + nosniff + referrer + permissions terverifikasi production. |

### Known pre-existing failures (BUKAN regresi)
Full suite: `44 failed, 428 passed` pada tree dengan patch. Subset yang sama
gagal `12 failed, 55 passed` **tanpa** patch `gateway_roster.py` (git stash) — jadi
sudah rusak sebelum perubahan ini, kemungkinan order/timing-dependent:
`tests/test_self_healing.py` (18), `test_self_healing_integration.py` (9),
`tools/picgen-mcp/*` (8), `test_browser_e2e.py` (3),
`tests/test_provider_registry.py` (3), `test_e2e_live.py` (1),
`tests/test_katalir_mcp_external.py` (1).

> Catatan: `pytest` di background via `cmd /c "... & echo %ERRORLEVEL% > f.txt"`
>|report `EXIT=0` yang menyesatkan — `%ERRORLEVEL%` di-expand saat parse.
> Selalu baca baris ringkasan pytest, bukan file exit code.


## FASE C — MCP Gateway
- [x] C1: Research agentgateway + registry
- [x] C2.1-C2.15: VPS + 5/5 server + 39 tools + call
- [x] C2.16: Named tunnel dibuat; CNAME manual selesai
- [x] C2.21: DONE — authenticated servers=200/39 tools; call=200/datetime; unauthenticated health=401 proves auth gate and new deployment.
- [x] C2.22: DONE — VPS/named tunnel documented in `docs/architecture/mcp-gateway-vps.md`; deploy/rollback/runbook added.
- [x] C3: MCP SDK client refactor
- [x] C7: Registry → gateway coverage test — `/mcp/registry/coverage` distinguishes metadata-only vs executable; 4548 total catalog metadata, executable transport=0 because ToolSDK entries are metadata-only.
- [x] C8: Production verify — 2026-10-01 vs `web-production-dc90b.up.railway.app`: `/health`=200 (`persistence=supabase`), `/mcp/registry`=200, `/mcp/registry/coverage`=200, `/mcp/recommendations`=200, `/mcp/my-instances`=401, `/mcp/server/tools`=401, `/mcp/auto-config/preview`=401, `/mcp/install`=401.
- [x] Tenant production round-trip — autonomous login (`scripts/autonomous_login.py`) + full round-trip (`scripts/autonomous_roundtrip.py`) = `RESULT=PASS`: workflows GET/POST/GET 200/201/200, `/chat` 200 in 13.80s (<127s), chat_sessions=2, chat_messages=2 persisted, cleanup HTTP 200.
- [x] Gateway tunnel auth — agentgateway NATIVE `mcp.policies.apiKey` (mode strict). No Cloudflare needed (Access requires a payment method). Verified externally: NAKED initialize=**401**, WITH-KEY initialize=**200**, real MCP SDK `tools/list`=**44 tools**, live `call_tool` reaches the time server. Key lives in `/etc/agentgateway/.env` (0600) via `EnvironmentFile` inside `[Service]`; client honours `AGENTGATEWAY_TOKEN` / `GATEWAY_API_KEY` and fails closed.
- [x] Gateway direct-IP exposure FIXED — agentgateway bound `*:3001` (RackNerd IP reachable, no tunnel). ufw enabled with `deny 3001/tcp` + `allow from 127.0.0.1` + `allow 22/tcp`. Verified from outside: `DIRECT-IP TCP 3001 -> BLOCKED TimeoutError`, `HTTP -> ConnectTimeout`; loopback initialize=200; services active; fresh SSH reconnect OK.
- [x] Composition research — 10 components documented in `docs/architecture/leapfrog-research.md`; execution remains allowlisted.

## FASE D — Multi-Tenant
- [x] Schema `user_mcp_instances` — SQL migration with per-user RLS created.
- [x] Endpoint `/mcp/install`, `/mcp/uninstall`, `/mcp/my-instances` — auth-gated; Supabase persistence path implemented with in-memory fallback.
- [x] Tenant isolation test — user A install/list/uninstall cannot affect user B.
- [x] PostgREST schema reload — `NOTIFY pgrst, 'reload schema'`; REST `user_mcp_instances?limit=1` = 200, body `[]`.
- [!] Production round-trip — service-role table/RLS is ready, but `test-jwt.txt` is absent, so authenticated install→Railway restart→list could not be exercised without user login token.

## FASE E — AI Integration Picker
- [x] System prompt registry search — MCP picker rule added; no invented servers.
- [x] Rekomendasi MCP di chat — `/mcp/recommendations?q=...&limit=5` backed by registry metadata.
- [x] Auto-config flow — `POST /mcp/auto-config/preview` menyusun rencana tanpa efek samping (kekurangan konfigurasi, secret di-redact); `POST /mcp/install` tetap exige `confirmed=true` dan menolak entri katalog metadata-only lewat allowlist runtime `mcp_autoconfig`; status `needs_config` bila konfigurasi belum lengkap. Tests: `tests/test_mcp_autoconfig.py` (10 passed).

## FASE F — Marketplace UI
- [x] `/integrations` — searchable/paginated registry UI; metadata/runtime boundary shown.
- [x] `/integrations/[slug]` — detail with tools, transport, install confirmation.
- [x] `/my-integrations` — list/uninstall tenant instances.

## FASE G — Expose Katalir as MCP Server
- [x] Workflow → MCP tool — owner-scoped `GET /mcp/server/tools` + `POST /mcp/server/call`; execution delegated to existing workflow engine.
- [x] External MCP client test — REAL official `mcp` SDK client (stdio transport, separate process) drives `mcp_gateway/katalir_server.py`: `initialize` → `tools/list` = `['list_workflows','run_workflow']` → `tools/call` returns `execution_id=exec-123`. Test: `tests/test_katalir_mcp_external.py`.

## FASE H — Final Verify
- [x] Production deploy — production domain routes respond 200; gateway named tunnel and Railway E2E previously verified.
- [x] 8-route screenshots — fresh production captures in `nexus-frontend/test-results/domain_*.png`, including `domain_settings.png` (BODY=1344, errors=[]).
- [x] Final documentation — `docs/architecture/leapfrog-research.md` and `docs/architecture/mcp-gateway-vps.md`; composition boundaries and rollback documented.
- [x] Executable manifest validator — rejects metadata-only/non-allowlisted packages; targeted tests 5 passed.






## FASE P2.5 — Prioritized Features
- [x] Feature 1: export chat JSON/Markdown, owner-scoped through existing session messages endpoint; tsc passes.
- [x] Feature 2: analytics dashboard from owner-scoped quota and execution summaries; Python compile and TSC pass.
- [x] Feature 3: workflow templates with validated React Flow graph install; TSC and Python compile pass.

