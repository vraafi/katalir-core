# TODO — Katalir

## Status Sekarang
- Level 3 E2E: lulus; production live di `katalir.de5.net`.
- UI/UX Overhaul: FASE 0-6 selesai.
- MCP Federation: FASE C, gateway VPS dan named tunnel hidup; Railway backend E2E masih blocked.

## FASE C — MCP Gateway
- [x] C1: Research agentgateway + registry
- [x] C2.1-C2.15: VPS + 5/5 server + 39 tools + call
- [x] C2.16: Named tunnel dibuat; CNAME manual selesai
- [!] C2.21: BUILD FIXED, DEPLOYMENT NOT YET CONFIRMED — Railway diagnosis 4193d397 showed pydantic==2.10.4 conflicted with mcp==1.26.0; requirements now pins pydantic==2.11.4 in commit 397b00b. Deployment polling could not retrieve a new deployment record; user action: verify latest deployment status in Railway dashboard, then re-run health/MCP.
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




