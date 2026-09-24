# MCP Federated Gateway

Accessed 25 September 2026.

## Boundary

Katalir metadata registry is live locally, but remote execution is disabled until an independently verified agentgateway deployment exists. The gateway adapter does not execute registry packages or spawn arbitrary processes.

## Upstream allowlist

Allowed transports: `stdio`, `http`, `sse`. HTTP/SSE URLs must be explicit https/http, reject localhost, metadata hosts, private, loopback, link-local, reserved, and multicast addresses. OWASP recommends allowlists and DNS/IP validation; see https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html.

## Katalir contract

- `GET /mcp/gateway/health`
- `GET /mcp/gateway/servers`
- `POST /mcp/gateway/call`

All require a Katalir JWT. Configure `AGENTGATEWAY_URL` and `AGENTGATEWAY_API_KEY`; values are never logged. The client uses bearer auth, timeout 10 seconds, and no redirects.

## agentgateway deployment notes

Official docs: https://agentgateway.dev/docs. The project is Apache-2.0 and supports standalone Docker/binary and MCP federation. A deployment must provide a real service URL, health endpoint, authenticated upstream config, and a reproducible five-server test before it can be enabled in production. Reference servers are educational/reference implementations, not automatically production-safe; see https://github.com/modelcontextprotocol/servers.

## Five-server plan

`sequential-thinking`, `filesystem`, `fetch`, `memory`, and `time` are candidate reference servers. Their actual tools and calls are not claimed until a gateway service is deployed and health/tools/call are observed. Native Telegram, Gmail, Sheets, Slack, and HTTP tools are separate and untouched.
