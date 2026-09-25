# Glama Integration (Katalir v2)

Status: **synced + runtime-verified** (2026-09-25).
Source: `https://glama.ai/api/mcp` — licence: **Glama API Data License** (not public domain).

## TL;DR

| Fact | Value |
| --- | --- |
| Servers synced | **20.000** (API ceiling reached; directory larger) |
| Connectors synced | **1.000** (API returns exactly 1.000 unique, even when filtered) |
| Connectors advertising tools | 17.610 toolCount summed |
| `auth:none` connectors | 619 of the synced 1.000 |
| Connectors runtime-probed | 60 |
| **Connectors proven `tools_listed`** | **28** (177 real tools) |
| Registry total | **28.532** entries across 5 sources |

## Licence — the part that is not optional

Read from Glama's own reference on 2026-09-25:

- Base URL `https://glama.ai/api/mcp`
- Auth: `Authorization: Bearer <GLAMA_API_KEY>` (required for all read endpoints)
- Rate limit 100 req/s per IP, exposed via `RateLimit-*` headers
- Pagination: `?first=` (max 100) + `?after=<endCursor>`
- **"This data is licensed, not public domain."**
- Every page showing the data must carry a visible credit linking to
  `https://glama.ai`, without `rel="nofollow"`, `"sponsored"` or `"ugc"`
- Every server/connector shown must link back to its own Glama listing URL —
  *the URL the API returns for it*
- Attribution can be waived under a commercial licence

Implementation: `scripts/sync-glama.py` stamps `source`, `source_url` and
`attribution_required: true` on every record; `api_server` ships the credit text
in `/mcp/registry/sources`; the UI renders it on `/integrations`, `/`, `/docs`
and `/pricing`. `tests/test_glama_registry.py` fails if any record loses these
fields.

## Two corrections to the original plan

1. **Listing URL shape.** The plan assumed
   `https://glama.ai/mcp/servers/{namespace}/{slug}`. The API actually returns
   `https://glama.ai/mcp/servers/{id}` (e.g. `.../servers/w0op4s00ly`). We store
   the API's own `url` field, which is exactly what the licence asks for.
2. **No tool lists on the servers endpoint.** `tools` is present in the schema
   but empty in both list and detail responses (verified on 25 detail calls).
   The 843.355 "tools" figure on the website is not obtainable through
   `/v1/servers`, and `/v1/tools` is not an endpoint — it 302s to the docs.
   So `tools_count` stays 0 for Glama *servers* and the claim is not made.

## Connectors are the runtime-relevant half

`/v1/connectors` returns running remote MCP deployments:

```json
{"attributes":["auth:none","status:healthy","capability:tools", "..."],
 "connection":{"authType":"none","transport":"streamable_http","url":"https://…/mcp"},
 "healthy":true,"toolCount":5,"url":"https://glama.ai/mcp/connectors/<ns>/<slug>"}
```

Directory facet totals returned by the API (2026-09-25):

| Facet | Count |
| --- | --- |
| `auth:none` | 19.028 |
| `status:healthy` | 12.858 |
| `capability:tools` | 12.847 |
| `auth:oauth2` | 4.859 |

The API caps a single listing walk at **1.000 unique connectors** even when
filtered with `?auth=none` or `?status=healthy` — verified twice. Anything above
1.000 would need a commercial arrangement.

## Runtime verification (`scripts/batch-verify-glama-connectors.py`)

Read-only: sends `initialize` + `tools/list` only, never `tools/call`, so we
cannot write to someone else's system. Only `no_auth` connectors. HTTPS-only
with an SSRF guard that refuses non-public addresses. Sequential with a delay.

60 probed → **28 ok** (177 tools listed), **30 auth_required**, 1 protocol_error,
1 unreachable, 0 ssrf_blocked.

**Important caveat:** half the connectors labelled `auth:none` by Glama still
demanded a credential at runtime. The label is a directory hint, not a promise,
so the registry keeps the per-connector probe result rather than trusting it.

## Honest claim

> 28,500+ catalog entries from OpenConnector, Composio and Glama. 11 OpenConnector
> actions call-verified, 28 Glama connectors tools-listed, 20 Composio toolkits
> list-verified. Badges in the UI reflect exactly these numbers.

Never say "20.000 Glama integrations work" — that is a catalogue count.
