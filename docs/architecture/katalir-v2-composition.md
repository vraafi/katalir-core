# Katalir v2 Composition — 7 Repository Evaluation

Date: 25 September 2026. This is a composition contract, not a source dump. Target: 1,000+ runtime integrations, AI-first workflow creation, MCP-native federation, no-code canvas.

## Selected repositories

| # | Repository | Language | License | Role in Katalir | Integration boundary | Trade-off / weakness |
|---|---|---|---|---|---|---|
| 1 | LangGraph | Python/TS | MIT | Durable orchestration, retries, HITL, checkpoint state | Optional `langgraph` adapter behind the existing `execution_engine.py`; workflow graph stays owner-scoped in Supabase | Extra dependency and state model; do not replace the working engine until a shadow-run comparison passes |
| 2 | LoomFlow | TypeScript/Next | MIT | NL→workflow pattern, workflow evaluation/evolution ideas | Reference for `workflow_spec.py` + AI picker prompts; no source merge | Small project (222 stars); production limitations documented (no long-running worker in Vercel mode) |
| 3 | agentgateway | Rust/Go tooling | Apache-2.0 | MCP federation runtime already on the VPS | Keep as the only runtime MCP boundary; add Composio/Katalir MCP backends to its config | Gateway config/runtime ops; no arbitrary registry execution |
| 4 | Composio | TypeScript + Python | MIT | 1,000+ toolkits, auth, tool search, MCP remote server | Adapter source behind `/mcp/registry` and a tenant-scoped install flow; requires `COMPOSIO_API_KEY` | Hosted API dependency, credential model and quota must be reviewed; not offline |
| 5 | Kestra | Java | Apache-2.0 | Event-driven scheduling/queue/retry patterns | Architecture reference only; do not embed the JVM platform | Heavy JVM stack; overlaps existing FastAPI/worker design |
| 6 | Mastra | TypeScript | Apache-2.0 core, EE directories separate | TS agent/workflow/eval patterns, MCP server | Reference for AI-native workflow/eval UX; EE code must never be copied | Dual license: `ee/` requires enterprise terms |
| 7 | ToolRegistry | Python | MIT | Protocol-neutral tool contract, permissions, schemas | Adapter-interface reference for the registry schema; keep Katalir policy in `mcp_gateway/policy.py` | Small community; permission model still needs Katalir-side enforcement |

## Non-negotiable composition rules

1. Registry is not runtime. A record becomes executable only after a manifest validator records transport, package/image or remote URL, digest, permissions, credential policy, license and health probe.
2. agentgateway remains the only MCP runtime boundary. Katalir never installs or executes registry packages inside the API process.
3. Tenant identity, quota, billing and chat history stay in Katalir. External toolkits receive scoped credentials, never user secrets or raw JWTs.
4. License separation. Apache/MIT components can be adopted behind adapters. Mastra enterprise directories and n8n Sustainable Use code remain reference-only.
5. Adapters are replaceable. Composio, Official MCP Registry, Glama and future sources normalize into one internal record shape.
6. Every user-visible claim must distinguish catalog metadata from verified runtime.

## Runtime claim target

Current verified baseline:

- 5 MCP runtime targets
- 39 executable tools
- 4,548 metadata catalog entries
- 0 automated registry batch candidates because ToolSDK lacks `install_method`

The "1000+ integrations" target is therefore **not yet achieved** and must not be marketed as working. The fastest legitimate path is Composio: its toolkit catalog plus hosted auth/MCP surface can raise the runtime count, but only after:

- `COMPOSIO_API_KEY` is configured;
- toolkit sync maps into the internal manifest schema;
- 20 sampled toolkits pass `list_tools` plus `call_tool`;
- failures are recorded and excluded from the verified badge.

## Phase status (25 September 2026)

- Phase 1 research: complete (this document).
## Composio verification (25 September 2026)

Project API key (`ak_...`, header `x-api-key`) verified successful:

- `GET /api/v3.1/toolkits` → HTTP 200, `total_items=1562`
- `scripts/composio_sync.py` synced 1,562 toolkits into `composio_toolkits.json`
- 20/20 target toolkits passed live `list_tools` (`GET /api/v3.1/tools?toolkit_slug=...`)
- `POST /api/v3.1/tools/execute/COMPOSIO_LIST_TOOLKITS` → `successful: true` (no-auth toolkit, real execution)
- Verification results are in `composio-verify.json`; only these 20 are marked `runtime_verified` and show the `Ready` badge

Auth-required toolkits (Gmail, Slack, WhatsApp, etc.) still need a per-user connected account before `call_tool`; listing tools and catalog sync are verified. Never print or commit the API key.
- Phase 3 LangGraph: evaluated as optional adapter; production engine deliberately not replaced without shadow-run evidence.
- Phase 4 agentgateway: existing verified runtime kept; Composio backend cannot be configured without Composio credentials.
- Phase 5 NL→workflow: Katalir already has a validated `generate_workflow_json` tool and `workflow_spec.py`; LoomFlow is a pattern reference, not a required dependency.
- Phase 6 E2E: blocked on Phase 2/4.
