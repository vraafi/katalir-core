# Katalir MCP Composition ? Research & Integration Contract

Accessed 25 September 2026. This is a composition contract, not a code dump: Katalir keeps its own API, store, security policy, and UX while adopting proven protocols and operational patterns behind adapters.

## Selected components

| Component | Source | Language/protocol | License | Adopted boundary | Why it fits |
|---|---|---|---|---|---|
| Official MCP Registry | https://github.com/modelcontextprotocol/registry | Go / registry API | Verify repository license | registry schema/API adapter | Canonical discovery vocabulary and package metadata. |
| ToolSDK Registry | https://github.com/ToolSDK-AI/toolsdk-mcp-registry | JSON catalog / MCP metadata | MIT | seed + sync adapter | 4,548 catalog entries; metadata only, never promoted to runtime automatically. |
| agentgateway | https://github.com/agentgateway/agentgateway | Go / MCP stdio, HTTP, SSE, Streamable HTTP | Apache-2.0 | external gateway | Verified on VPS: 5 targets, 39 tools, MCP SDK. |
| SageMCP | https://github.com/sagemcp/sagemcp | Python/FastAPI / MCP + OAuth | Apache-2.0 | tenant lifecycle patterns | RLS, tenant-scoped instances, connector credential boundaries. |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | Python / MCP Streamable HTTP | MIT | gateway client | Current Katalir client; no REST adapter for MCP operations. |
| MCP reference servers | https://github.com/modelcontextprotocol/servers | TypeScript/Python / MCP stdio | MIT (verify per package) | five safe test targets | Verified runtime: everything, fetch, memory, filesystem, time. |
| mcpm.sh | https://github.com/pathintegral-institute/mcpm.sh | Python / registry + config | MIT | install/config UX pattern | Search and configuration workflow reference; no arbitrary catalog execution. |
| agentic-community/mcp-gateway-registry | https://github.com/agentic-community/mcp-gateway-registry | TypeScript / registry + gateway | Verify license | registry API/auth reference | Registration gates, metadata search, virtual federation design. |
| Oaklight/ToolRegistry | https://github.com/oaklight/ToolRegistry | Python / protocol abstraction | Verify license | adapter interface reference | Protocol-neutral tool contract; Katalir keeps its own gateway client. |
| n8n | https://github.com/n8n-io/n8n | TypeScript / MCP server trigger | Sustainable Use License | workflow-as-MCP pattern | Reference only; do not copy source or imply license compatibility. |
| xpack | https://github.com/xpack-mcp/xpack | TypeScript / marketplace | Verify license | marketplace UX reference | Discovery pattern; Katalir marketplace remains first-party. |

## Composition rules

1. Registry is not execution. An item is metadata-only until a validator records executable transport, package/image digest, permissions, health result, and policy decision.
2. Gateway is the only runtime boundary. Katalir never runs arbitrary registry commands in the API process. agentgateway owns process/transport lifecycle.
3. Tenant identity stays in Katalir. Supabase JWT maps to tenant-scoped instance/config; gateway receives a short-lived scoped request, never a user secret.
4. Adapters are replaceable. ToolSDK, official Registry, and future sources implement the same normalized record shape.
5. No license laundering. Apache/MIT/verified licenses are tracked; Sustainable Use License and unknown licenses remain reference-only.
6. Metadata boundaries are visible. Marketplace shows metadata-only, validated, and runtime-enabled separately.

## Implemented Katalir composition

- `mcp_registry.py`: normalized metadata catalog plus coverage/recommendation API; `executable_candidates()` is the honest batch-test filter and currently returns zero for ToolSDK metadata lacking runtime manifests.
- `mcp_gateway/client.py`: MCP Streamable HTTP SDK client and raw initialize health probe.
- `mcp_gateway/policy.py`: transport allowlist and SSRF guard.
- `api_server.py`: authenticated gateway proxy, tenant install lifecycle, recommendations, coverage.
- `schema/user_mcp_instances.sql`: RLS migration for persistent tenant instances.
- `nexus-frontend/src/app/integrations/**`: marketplace and tenant instance UX.
- VPS agentgateway plus named Cloudflare tunnel: verified 5/5 targets, 39 tools, 5/5 direct calls.

## Remaining integration milestones

- Apply the RLS migration to production with a reviewed dry-run; current API tenant store is in-memory.
- Add a validator producing signed executable manifests; do not install ToolSDK metadata directly.
- Add auto-config only for validated manifests and require explicit user confirmation.
- Expose selected workflows as MCP tools behind tenant-scoped authorization.
- Add registry contract fixtures for the official Registry API and mcpm.sh-compatible install metadata.

## Sources and caveats

All URLs above were searched/accessed on 25 September 2026. Stars are not evidence of production readiness. License, protocol version, dependency health, and security posture must be rechecked before vendoring or automatic execution. The 4,548 ToolSDK records are a catalog count, not 4,548 verified runnable servers.
