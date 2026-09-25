

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

## Known tenant boundary
Metadata registry is catalog-only. Runtime instance isolation is implemented in the API with a per-user in-memory store and the Supabase migration `schema/user_mcp_instances.sql`; apply the migration before relying on cross-process persistence.
