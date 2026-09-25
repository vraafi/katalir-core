# MCP Registry Comparison — 25 September 2026

## Findings

| Registry | JSON/API | Runtime manifest evidence | License/terms | Result |
|---|---|---|---|---|
| Official MCP Registry | `GET https://registry.modelcontextprotocol.io/v0/servers`; response is `{servers:[...], metadata:...}`. Detail follows server schema with `remotes` (`type`, `url`) and optional `packages` in the schema. | Strongest standardized metadata. Public sample fetched successfully; remote entries provide transport URL, but current sample lacked npm/Python package execution details and tools. Preview; no self-hosting guarantee. | Preview terms/moderation apply; package registries retain code-scanning responsibility. | Best standards source; runtime install still requires package-type or remote health evidence. |
| Smithery | `GET https://api.smithery.ai/servers`; public JSON list succeeded, returns server summary fields (`qualifiedName`, `verified`, `remote`, `isDeployed`, `useCount`). | Runtime/hosted deployment is available, but summary list is not a full local install manifest. Smithery now documents Arcade.dev integration. | API/platform terms apply; not a source-code license for servers. | Good hosted runtime catalog; requires API key/terms review for bulk use. |
| mcpm.sh | GitHub repository; registry data lives in `mcp-registry/`; CLI/package manager is MIT. | Install/config-oriented and supports npm/PyPI-style workflows conceptually, but no verified public bulk JSON API was confirmed. | MIT repository. | Good operational UX/reference, insufficient evidence for a clean bulk runtime sync without inspecting the registry data. |
| mcp-hub | GitHub repository; REST `/api/*` and `/mcp` runtime coordinator; `mcp-servers.json` config. | Strong runtime coordinator and health monitoring; it consumes manifests rather than serving a complete public registry API. MIT. | MIT repository. | Best runtime orchestration reference, not the source of the 4,548 catalog. |
| Glama | `GET https://glama.ai/api/mcp/v1/servers`; detail `GET /v1/servers/{namespace}/{slug}`; requires `GLAMA_API_KEY`; 100 requests/second/IP with cursor pagination. Detail includes `tools`, `attributes`, `environmentVariablesJsonSchema`, repository, license, and listing URL. | Best catalog/tool metadata candidate, but requires API key and visible attribution/listing links under the API Data License. | API Data License; attribution and per-listing links required. | Excellent curated metadata source, not automatically executable without transport/package/credential manifest. |
| PulseMCP | Directory page returned HTTP 403 in this environment; no public JSON API confirmed. | No reliable bulk runtime manifest evidence obtained. | Terms unavailable from blocked response. | Do not automate; manual reference only. |

## Decision

Use the **Official MCP Registry** as the canonical source and **Glama** as an optional curated metadata adapter when a licensed `GLAMA_API_KEY` is configured. Do not merge Glama records into the production cache until attribution/link requirements are implemented.

Neither source proves a 20–50 local batch of installable servers from the current catalog. The official sample primarily exposes remote streamable HTTP endpoints; Glama exposes tools and source metadata but requires API key and attribution. Therefore no package install is attempted and the marketing/runtime baseline remains **5 verified targets / 39 tools**.

## Next implementation gate

A future sync adapter must require:

- explicit transport (`stdio`, `sse`, or `streamable-http`);
- package/image or remote URL;
- command/args and environment schema;
- credentials/permissions declaration;
- license and package digest;
- health probe result;
- explicit user confirmation before install.
