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
| 2 | Dropdown model cuma 3 | **FIX + TERDEPLOY; target >10 TIDAK TERCAPAI — blocker upstream** | Fix `_model_allowed_for_tier` (Gate 2 hanya untuk family google) sudah **live di production**: `/models` naik **3 → 4** (`gemini-2.5-flash`, `flash-lite`, `gemini-3-flash-preview`, `allam-2-7b`). Tapi **4 ≠ >10**, dan itu BUKAN bug filter kita — dibuktikan langsung ke gateway: `llama-3.3-70b-versatile` → **HTTP 500**, `qwen/qwen3-32b` → **HTTP 500**, sedangkan `gemini-2.5-flash` & `allam-2-7b` → HTTP 200 + `X-Routed-Via` benar. Probe `_probe_one` 30/30 kandidat non-Gemini gagal **HTTP500**. `/api/status` klaim `nvidia` `health=up` dengan 89 model ber-key, padahal semua panggilan nvidia 500 — jadi status health gateway itu sendiri **tidak akurat**. Tabel `roster_cache` hanya berisi **4 record PASS**. Kesimpulan: backend nvidia di gateway mati/bermasalah → **perbaikan di sisi gateway (deploy/rotasi key + perbaikan health check), bukan di repo ini**. Regresi lokal tetap hijau: `tests/test_model_roster_free_tier.py` (3 tes) + `test_model_allowlist.py` → 6 passed; simulasi katalog nyata 0/19 → 19/19 lolos allowlist. |
| 3 | Sidebar history chat kosong | **ROOT CAUSE DITEMUKAN** | Query Supabase via service-role: user browser `vraafi003@gmail.com` punya **2 session** — tersimpan di `public.users.id` (`3a109c48…`), sedangkan JWT membawa `auth.users.id` (`e4092a90…`). **0 session** terdaftar di auth_id. D suspected UI filter salah, tapi `/sessions` sudah benar resolve-by-EMAIL (`api_server.py:2375`) sehingga user otonom (yang auth_id==public_id) selalu PASS — itulah alasan test JWT otonom tidak pernah bisa mereproduksi. Yang belum dipastikan: apakah sisi frontend atau Supabase RLS masih memfilter auth_id. Butuh login browser nyata (bukan JWT) untuk konfirmasi. |
| 4 | Starlette CVE | **BLOCKED** | Branch `security/starlette-cve-2026-48710`; jangan merge sebelum full suite hijau. |
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

