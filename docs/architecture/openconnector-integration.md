
# OpenConnector Integration (Katalir v2)

Status: **Phase A + Phase B deployed and runtime-verified** (2026-09-25).
Source: `ghcr.io/oomol-lab/open-connector:latest` — license **Apache-2.0** (verified in the
official repository; the earlier MIT claim was wrong).

## TL;DR

| Fact | Value | Evidence |
| --- | --- | --- |
| Providers discovered | **1.554** | `GET /mcp/tools` metadata + `openconnector_list_apps` call |
| Actions discovered | **18.010** | OpenConnector provider/action registry |
| MCP tools exposed by OpenConnector | **5** | `tools/list` through agentgateway |
| agentgateway tool count | **38 → 43** | before/after `tools/list` on the live gateway |
| Runtime call proof | **passed** | `tools/call openconnector_list_apps` → 704 KB payload, `ok: true` |

## The important nuance (read this before writing any marketing copy)

OpenConnector does **not** expose 18.010 individual MCP tools. It exposes **5 meta-tools**:

- `openconnector_list_apps` — list providers
- `openconnector_list_connections` — list configured connections
- `openconnector_search_actions` — search the 18.010 actions
- `openconnector_get_action_guide` — fetch the guide for one action
- `openconnector_execute_action` — execute one action

So the 18.010 actions are *reachable at runtime through a meta-tool*, not enumerated as
18.010 distinct tool schemas. The only safe public claim today is:

> "18.010 OpenConnector actions discovered, exposed through a 5-tool MCP meta-layer."

Never say "18.010 executable integrations". See `docs/architecture/mcp-registry-comparison.md`.

## Phase A — container deployment

- Container: `open-connector`, `--restart unless-stopped`.
- Published on `127.0.0.1:3010` only (never exposed publicly).
- Persistent volume `open_connector_data:/app/data`.
- Health: `GET /health` → HTTP 200 `{"ok":true}`.
- Secrets live server-side in `/root/.openconnector.env` (mode 600):
  `OOMOL_CONNECT_ENCRYPTION_KEY`, `OOMOL_CONNECT_ADMIN_TOKEN`, `OOMOL_CONNECT_RUNTIME_TOKEN`.

## Phase B — agentgateway federation

### Why a proxy instead of a token in config.yaml

The first attempt put the runtime token directly in `/opt/agentgateway/config.yaml` under the
target. It failed on two counts:

1. `mcp: unknown field 'headers'` — agentgateway's MCP target schema has no `headers` field.
2. Storing a bearer token in a world-readable YAML is bad practice anyway.

The shipped design keeps the token out of the gateway config entirely:

```
agentgateway (127.0.0.1:3001)
  └─ target "openconnector" → http://127.0.0.1:3011/mcp
       └─ openconnector-proxy.service  (scripts/openconnector_proxy.py)
            └─ injects Authorization: Bearer <runtime token>
                 └─ OpenConnector (127.0.0.1:3010)
```

`scripts/openconnector_proxy.py` is a stdlib-only reverse proxy. It binds loopback only, reads the
token from `/root/.openconnector.env` at request time (so rotation needs no restart of the gateway),
and overrides `log_message` so request lines are never written to the journal.

### agentgateway target

```yaml
    - name: openconnector
      mcp:
        host: http://127.0.0.1:3011/mcp
```

### Verification performed

- `systemctl is-active agentgateway` → `active`, port 3001 listening.
- MCP `initialize` → HTTP 200 with `Mcp-Session-Id`.
- `tools/list` → **43** tools: 38 pre-existing baseline (everything/fetch/memory/filesystem/time)
  + 5 OpenConnector meta-tools. No regression.
- `tools/call openconnector_list_apps {}` → `ok: true`, 704.403 bytes, first entry `17TRACK`.

## Security incident and remediation (2026-09-25)

An inspection command ran `tail -20 /opt/agentgateway/config.yaml` on the VPS while the token was
embedded in that file, and the output was echoed into a session transcript. This leaked the
OpenConnector runtime token.

Remediation executed, in order:

1. `cp /opt/agentgateway/config.yaml.bak.oc /opt/agentgateway/config.yaml` — gateway restored.
2. Gateway restarted, `active`, port 3001 back up, tool count verified.
3. **Token rotated**: fresh `openssl rand -base64 32` for both the admin and runtime tokens;
   encryption key preserved so stored credentials stay valid.
4. Container recreated with the new tokens; `GET /health` → HTTP 200.
5. Config no longer holds any secret — the proxy injects it at request time.
6. `_vps_gw_inspect.py` no longer prints raw config; it greps only name/host/port/cmd and masks
   `Bearer|token|key` values.
7. All `oc-*.log` / `gw-*.log` artifacts from the session were deleted; `.gitignore` already
   covers `*.log` and `_vps_*.py`.

## Rule for future sessions

Never run `cat`/`tail` on files that may hold credentials. Inspect with a masked grep, and rotate
any secret that ever reaches a transcript, a log file, or a commit.

## Phase C — registry sync + batch runtime test

### Scripts

- `scripts/sync-openconnector.py` — reads `GET /api/actions` (admin token), writes
  `openconnector_actions.json` (1.554 service entries) + `openconnector-sync-report.json`.
  Stdlib only, so it runs on the VPS next to the container.
- `scripts/batch-test-openconnector.py` — real `tools/call` through the gateway.
  Stdlib only, writes `batch-test-openconnector.json`.

### Honest numbers from the sync

| Metric | Value |
| --- | --- |
| Services | 1.554 |
| Actions | 18.010 (all ids unique) |
| Operation types | 12.051 read / 4.013 write / 1.946 destructive |
| `execution.locallyExecutable` | 18.010 |
| **`execution.noAuthRunnable`** | **170** (across 24 services) |
| Auth types | api_key 13.780, oauth2 2.918, custom_credential 2.731, no_auth 170 |
| Locally executable **and** runnable with no input | 19 |

`locallyExecutable` being true for all 18.010 is *not* a runtime claim: it only means
OpenConnector ships an executor for the action. The action still needs a connected
account unless `noAuthRunnable` is true.

### Batch test result (gateway → meta-tool → real upstream API)

Selection was deliberately narrow: `read` + `noAuthRunnable` + empty input schema,
sequential, 1.5 s delay, no writes of any kind. That yields 19 candidates, not 50 —
widening it would have meant inventing arguments or touching credentialed APIs.

| Status | Count | Example |
| --- | --- | --- |
| `ok` (really executed) | **11** | `clinicaltrials_gov.get_api_version`, `crossref.list_works`, `dealnews.list_latest_deals`, `indiegogo.list_active_crowdfunding_projects`, `ossinsight.list_collections` |
| `auth_required` | 4 | `fundzwatch.*` — provider is flagged no_auth but the API key is still needed |
| `invalid_input` | 3 | `crossref.list_resources`, `ossinsight.list_hot_collections` — empty input rejected upstream |
| `no_connection` | 1 | `npm.get_current_user` — needs an npm token connection |

So: 11 actions across 5 services are genuinely `call_verified`. The other 8 failures
are real, informative results, not test noise — they prove the error path, the auth
detection and the schema validation all work end to end.

### Registry integration

`mcp_registry.py` merges `openconnector_actions.json` under `openconnector/<service>`.
Entries use `transport: mcp-meta-layer`, so `executable_servers()` does **not** treat
them as runnable just because they exist. `coverage()` now reports
`openconnector_services`, `openconnector_actions` and `openconnector_actions_call_verified`
separately from the Composio numbers.

Current `coverage()`:

```json
{
  "total": 7532, "executable": 25, "metadata_only": 7507,
  "composio_toolkits": 1562, "official_remote": 0,
  "openconnector_services": 1554,
  "openconnector_actions": 18010,
  "openconnector_actions_call_verified": 11
}
```

Idempotency was verified by running the sync twice and comparing md5: identical, and
`DIFF_SERVICES 0`. Previously earned `call_verified` flags survive every re-run.

## Safe claim, final wording

> 18.010 OpenConnector actions discovered across 1.554 providers, reached through a
> 5-tool MCP meta-layer on our gateway. 11 actions are call-verified end to end today.

## Not done yet

- Nango: no verified deployment / `NANGO_URL` yet.
- Glama: licence and API-key/attribution terms still unconfirmed.
- Public surface for OpenConnector: still loopback-only, intentionally.
- Screenshot of the federated tool list: not captured yet.
