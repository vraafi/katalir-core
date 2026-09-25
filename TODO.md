# TODO — Katalir

## Status Sekarang
- Level 3 E2E: lulus; production live di `katalir.de5.net`.
- UI/UX Overhaul: FASE 0-6 selesai.
- MCP Federation: FASE C selesai; gateway VPS/named tunnel hidup, production E2E health=401 (auth), servers=39, call=datetime.
- Composition research: 10 komponen MCP dipilih dengan boundary adapter/license; registry metadata tidak boleh dieksekusi otomatis.

## FASE C — MCP Gateway
- [x] C1: Research agentgateway + registry
- [x] C2.1-C2.15: VPS + 5/5 server + 39 tools + call
- [x] C2.16: Named tunnel dibuat; CNAME manual selesai
- [x] C2.21: DONE — authenticated servers=200/39 tools; call=200/datetime; unauthenticated health=401 proves auth gate and new deployment.
- [x] C2.22: DONE — VPS/named tunnel documented in `docs/architecture/mcp-gateway-vps.md`; deploy/rollback/runbook added.
- [x] C3: MCP SDK client refactor
- [x] C7: Registry → gateway coverage test — `/mcp/registry/coverage` distinguishes metadata-only vs executable; 4548 total catalog metadata, executable transport=0 because ToolSDK entries are metadata-only.
- [x] C8: Production verify — authenticated servers=200/39, call=200/datetime, unauth health=401 expected; named gateway stable.
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
- [x] Auto-config flow — explicit confirmation, allowlisted executable IDs, metadata-only install rejected (409/422), tenant install lifecycle tested.

## FASE F — Marketplace UI
- [x] `/integrations` — searchable/paginated registry UI; metadata/runtime boundary shown.
- [x] `/integrations/[slug]` — detail with tools, transport, install confirmation.
- [x] `/my-integrations` — list/uninstall tenant instances.

## FASE G — Expose Katalir as MCP Server
- [x] Workflow → MCP tool — owner-scoped `GET /mcp/server/tools` + `POST /mcp/server/call`; execution delegated to existing workflow engine.
- [x] External MCP client test — official `mcp.server.fastmcp.FastMCP` stdio adapter added at `mcp_gateway/katalir_server.py`; import/compile PASS. Live owner call still requires a fresh user JWT.

## FASE H — Final Verify
- [x] Production deploy — production domain routes respond 200; gateway named tunnel and Railway E2E previously verified.
- [x] 8-route screenshots — fresh production captures in `nexus-frontend/test-results/domain_*.png`, including `domain_settings.png` (BODY=1344, errors=[]).
- [x] Final documentation — `docs/architecture/leapfrog-research.md` and `docs/architecture/mcp-gateway-vps.md`; composition boundaries and rollback documented.
- [x] Executable manifest validator — rejects metadata-only/non-allowlisted packages; targeted tests 5 passed.






## FASE P2.5 — Prioritized Features
- [x] Feature 1: export chat JSON/Markdown, owner-scoped through existing session messages endpoint; tsc passes.
- [ ] Feature 2: analytics dashboard from quota and execution logs.
- [ ] Feature 3: workflow templates with validated React Flow graph install.

