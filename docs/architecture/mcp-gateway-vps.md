

# MCP Federation — VPS / named tunnel

## Runtime
- Agentgateway v1.5.0 runs on Ubuntu VPS under `agentgateway.service`.
- MCP: `http://localhost:3001/mcp`; admin UI: `http://localhost:15000/ui`.
- Targets: everything, fetch, memory, filesystem, time (5/5, 39 tools).
- Named Cloudflare tunnel: `gateway.katalir.de5.net` → VPS `localhost:3001`.

## Deploy/rollback
1. Verify the VPS agentgateway and cloudflared systemd services.
2. Check `https://gateway.katalir.de5.net/mcp` with an MCP initialize request.
3. Roll back tunnel routing by restoring the previous Cloudflare ingress; do not delete the VPS service while validating.
4. Roll back application changes with a git revert and redeploy Railway.

## Security
MCP Gateway health uses a raw initialize probe with a five-second timeout. Production API routes require Supabase JWT. Never print or commit JWTs, VPS passwords, tunnel tokens, or Slack/Google credentials.


### OPEN RISK (2026-09-26): gateway reachable anonymously

Unauthenticated probe against the public hostname:

```
POST https://gateway.katalir.de5.net/mcp   (no credentials)
  initialize  -> 200  serverInfo=agentgateway/1.5.0
  tools/list  -> 200  (57 "name" occurrences; filesystem/time/fetch/memory exposed)
```

Earlier handoff notes claimed "unauthenticated health=401 proves auth gate". The tenant API routes
*are* gated (`/mcp/my-instances` -> 401), but the gateway's own `/mcp` endpoint is public: anyone
can enumerate and call the tools. Treat as P1 before declaring the platform done.

### Hardening (in order)

1. Cloudflare Zero Trust -> Access -> Applications -> `gateway.katalir.de5.net/*`, policy = Service Auth.
   Create a Service Token and record id/secret.
2. Configure Railway + local env so the backend still reaches the gateway:
   `AGENTGATEWAY_TOKEN`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.
   `mcp_gateway/client.py` sends these as headers only, never in the URL.
3. Client fails closed: `GatewayClient` raises unless a credential exists
   (`MCP_GATEWAY_ALLOW_ANON=1` is a local-debug-only opt-out), preventing silent downgrade.
4. Verify both: naked request -> 401/403, authenticated via client -> 200 + tools/list.
5. Keep the admin UI `:15000` out of the tunnel ingress.

## Known tenant boundary
Metadata registry is catalog-only. Runtime instance isolation is implemented in the API with a per-user in-memory store and the Supabase migration `schema/user_mcp_instances.sql`; apply the migration before relying on cross-process persistence.
- Batch evidence 2026-09-25: 4,548 metadata inspected; executable candidates = 0 because ToolSDK package-list has no `install_method` runtime manifest. No batch install was attempted. Runtime verified baseline remains 5 targets / 39 tools.

