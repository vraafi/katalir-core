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
- [x] C2.21: DONE — authenticated servers=200/39 tools; call=200/datetime; unauthenticated health=401 proves auth gate and new deployment.
- [x] C2.22: DONE — VPS/named tunnel documented in `docs/architecture/mcp-gateway-vps.md`; deploy/rollback/runbook added.
- [ ] C2.22: Dokumentasi final VPS/named tunnel
- [x] C3: MCP SDK client refactor
- [ ] C7: Registry → gateway coverage test
- [ ] C8: Production verify

## FASE D — Multi-Tenant
- [ ] Schema `user_mcp_instances`
- [ ] Endpoint `/mcp/install`, `/mcp/uninstall`
- [ ] Tenant isolation test

## FASE E — AI Integration Picker
- [ ] System prompt registry search
- [ ] Rekomendasi MCP di chat
- [ ] Auto-config flow

## FASE F — Marketplace UI
- [ ] `/integrations`
- [ ] `/integrations/[slug]`
- [ ] `/my-integrations`

## FASE G — Expose Katalir as MCP Server
- [ ] Workflow → MCP tool
- [ ] External MCP client test

## FASE H — Final Verify
- [ ] Production deploy
- [ ] 8-route screenshots
- [ ] Final documentation





