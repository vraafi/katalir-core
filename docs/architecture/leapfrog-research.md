# Leapfrog MCP Research

Accessed 24 September 2026.

| Role | Project | Evidence | License | Decision |
|---|---|---|---|---|
| Registry | ToolSDK MCP Registry | https://github.com/ToolSDK-AI/toolsdk-mcp-registry; raw packages-list HTTP 200, 2,726,436 bytes; README reports 4547+ tools | MIT | Metadata sync first; validate before install. |
| Gateway | agentgateway | https://github.com/agentgateway/agentgateway; MCP/A2A federation and stdio/HTTP/SSE/Streamable HTTP, auth/observability | Apache-2.0 | Candidate execution gateway; separate deployment needed. |
| Multi-tenant | SageMCP | https://github.com/sagemcp/sagemcp; tenant-scoped MCP, OAuth/API-key connectors, Docker/Helm | Apache-2.0 | Pattern reference, not copied yet. |

Trade-offs: Envoy MCPRoute adds infrastructure; ToolHive is an API-spec reference; 0nMCP lifecycle/license evidence insufficient. Katalir already has an internal `MCPRegistry` protocol abstraction and native executor, but not a 500+ federated gateway. This slice adds metadata catalog and authenticated sync; it does not execute arbitrary catalog entries.
