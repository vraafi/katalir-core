

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


### CLOSED (2026-10-01): native apiKey auth, no Cloudflare

Cloudflare Zero Trust Access requires a payment method, so it is not an available path. The
gateway is instead protected by **agentgateway's own `mcp.policies.apiKey`** (mode `strict`).

```yaml
mcp:
  policies:
    apiKey:
      mode: strict
      keys:
        - key: "${KATALIR_GATEWAY_API_KEY}"
          metadata: { user: katalir-client, role: admin }
  port: 3001
  targets: [ ...existing 6 targets preserved... ]
```

Gotchas learned the hard way (both caused a production outage on first attempt):
1. The field is **`key:`**, not `value:` — the schema type is the untagged enum `LocalAPIKey`.
   `value:` / `secret:` / `string:` / bare-string all fail validation.
2. For **MCP server mode** the policy belongs under `mcp.policies.apiKey`. Putting it under
   `binds[].listeners[].routes[].policies` is the LLM/HTTP gateway path, and mixing both on
   port 3001 errors with "configured by both binds[0] and mcp".
3. `EnvironmentFile=` **must sit inside `[Service]`**. Appending it to the end of the unit file
   lands it after `[Install]`, where systemd silently ignores it — the service then crash-loops
   with `environment variable not found`.

Verified from outside the VPS:
```
3a NAKED initialize    -> HTTP 401
3c WITH-KEY initialize -> HTTP 200
   real MCP SDK: tools/list = 44 tools; call_tool reached the time server
```
Key storage: `/etc/agentgateway/.env` mode 0600, referenced via `EnvironmentFile`. It is never
printed, never committed, and never placed in a URL. `mcp_gateway/client.py` reads
`AGENTGATEWAY_TOKEN` or `GATEWAY_API_KEY`, sends `Authorization: Bearer` + `x-api-key`, and
raises unless a credential exists (`MCP_GATEWAY_ALLOW_ANON=1` is a local-debug-only opt-out).

### Direct-IP vector: also fixed

agentgateway bound `*:3001`, so the RackNerd IP was a second, tunnel-free exposure. Closed with
ufw (`allow 22/tcp` first, then `deny 3001/tcp`, then `enable`):
```
2.4a DIRECT-IP TCP 3001 -> BLOCKED TimeoutError
2.4a DIRECT-IP HTTP     -> REFUSED/BLOCKED ConnectTimeout
loopback initialize     -> HTTP=200      (tunnel path intact)
```

### Cloudflare token notes (for future work)

`/user/tokens/verify` returns 401 for account-scoped tokens and is NOT a validity test. Use
`/accounts/{id}/tokens/verify`. Likewise `/user/tokens/permission_groups` is user-level and 403s
for a valid account token — never read that as a scope verdict; attempt the real operation instead.

### Rollback
```
cp /tmp/config-good.bak /opt/agentgateway/config.yaml && systemctl restart agentgateway
cp /tmp/unit-good.bak /etc/systemd/system/agentgateway.service && systemctl daemon-reload
ufw disable
```

## Known tenant boundary
Metadata registry is catalog-only. Runtime instance isolation is implemented in the API with a per-user in-memory store and the Supabase migration `schema/user_mcp_instances.sql`; apply the migration before relying on cross-process persistence.
- Batch evidence 2026-09-25: 4,548 metadata inspected; executable candidates = 0 because ToolSDK package-list has no `install_method` runtime manifest. No batch install was attempted. Runtime verified baseline remains 5 targets / 39 tools.

