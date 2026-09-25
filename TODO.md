# TODO — Katalir

## Status Sekarang
- Level 3 E2E: lulus; production live di `katalir.de5.net`.
- UI/UX Overhaul: FASE 0-6 selesai.
- MCP Federation: FASE C selesai; gateway VPS/named tunnel hidup, production E2E health=401 (auth), servers=39, call=datetime.

## FASE C — MCP Gateway
- [x] C1: Research agentgateway + registry
- [x] C2.1-C2.15: VPS + 5/5 server + 39 tools + call
- [x] C2.16: Named tunnel dibuat; CNAME manual selesai
- [x] C2.21: DONE — authenticated servers=200/39 tools; call=200/datetime; unauthenticated health=401 proves auth gate and new deployment.
- [x] C2.22: DONE — VPS/named tunnel documented in `docs/architecture/mcp-gateway-vps.md`; deploy/rollback/runbook added.
- [x] C3: MCP SDK client refactor
- [x] C7: Registry → gateway coverage test — `/mcp/registry/coverage` distinguishes metadata-only vs executable; 4548 total catalog metadata, executable transport=0 because ToolSDK entries are metadata-only.
- [ ] C8: Production verify

## FASE D — Multi-Tenant
- [x] Schema `user_mcp_instances` — SQL migration with per-user RLS created.
- [x] Endpoint `/mcp/install`, `/mcp/uninstall`, `/mcp/my-instances` — auth-gated.
- [x] Tenant isolation test — user A install/list/uninstall cannot affect user B.

## FASE E — AI Integration Picker
- [x] System prompt registry search — MCP picker rule added; no invented servers.
- [x] Rekomendasi MCP di chat — `/mcp/recommendations?q=...&limit=5` backed by registry metadata.
- [ ] Auto-config flow — requires explicit install confirmation and credential/config UX.

## FASE F — Marketplace UI
- [x] `/integrations` — searchable/paginated registry UI; metadata/runtime boundary shown.
- [x] `/integrations/[slug]` — detail with tools, transport, install confirmation.
- [x] `/my-integrations` — list/uninstall tenant instances.

## FASE G — Expose Katalir as MCP Server
- [ ] Workflow → MCP tool
- [ ] External MCP client test

## FASE H — Final Verify
- [ ] Production deploy
- [ ] 8-route screenshots
- [ ] Final documentation





