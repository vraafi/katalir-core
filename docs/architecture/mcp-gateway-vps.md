

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


### OPEN RISK (2026-10-01): tunnel path still anonymous

- **Direct-IP vector: FIXED.** `agentgateway` bound `*:3001`, so the RackNerd IP was a second,
  tunnel-free exposure. Closed with ufw (`deny 3001/tcp`, `allow from 127.0.0.1`, SSH allowed first):
  ```
  2.4a DIRECT-IP TCP 3001 -> BLOCKED TimeoutError after 12.0s
  2.4a DIRECT-IP HTTP    -> REFUSED/BLOCKED ConnectTimeout
  loopback initialize    -> HTTP=200        (tunnel path intact)
  cloudflared/agentgateway -> active/active
  ```
- **Tunnel path: STILL OPEN** — needs Cloudflare Access (below). Cannot be fixed with a valid
  CF token alone, because Access is not enabled on the account:
  ```
  POST /accounts/{id}/access/service_tokens -> HTTP 403
  code 9999: "access.api.error.not_enabled: Access is not enabled."
  ```

### Cloudflare token: valid, but Access is not enabled

`/user/tokens/verify` returns 401 for account-scoped tokens and is NOT a valid validity test.
The account-scoped endpoint is authoritative:
```
GET /client/v4/user/tokens/verify              -> 401 code 1000 (user-scoped; misleading)
GET /client/v4/accounts/{id}/tokens/verify     -> 200 "This API Token is valid and active"
```
`/user/tokens/permission_groups` is also user-level and 403s ("Valid user-level authentication not
found") for a valid account token — do not read that as a scope verdict. Test scope by attempting
the real operation.

### Hardening (in order)

1. **Enable Access once**: Cloudflare Zero Trust dashboard -> "Enable Access" (or API
   `POST /accounts/{id}/access/apps`). This is a one-time account toggle and is the current blocker.
2. Access -> Applications -> `gateway.katalir.de5.net/*`, policy = Service Auth; create a Service Token.
3. Configure Railway + local env so the backend still reaches the gateway:
   `AGENTGATEWAY_TOKEN`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.
   `mcp_gateway/client.py` sends these as headers only, never in the URL.
4. Client fails closed: `GatewayClient` raises unless a credential exists
   (`MCP_GATEWAY_ALLOW_ANON=1` is a local-debug-only opt-out).
5. Verify both: naked request -> 401/403, authenticated via client -> 200 + tools/list.
6. Keep the admin UI `:15000` out of the tunnel ingress (already loopback-bound).

### Firewall rollback
```
ufw disable                       # emergency
ufw --force disable && ufw enable # keep SSH rule, drop the rest
# config backup: /tmp/config-backup.yaml
```

## Known tenant boundary
Metadata registry is catalog-only. Runtime instance isolation is implemented in the API with a per-user in-memory store and the Supabase migration `schema/user_mcp_instances.sql`; apply the migration before relying on cross-process persistence.
- Batch evidence 2026-09-25: 4,548 metadata inspected; executable candidates = 0 because ToolSDK package-list has no `install_method` runtime manifest. No batch install was attempted. Runtime verified baseline remains 5 targets / 39 tools.

