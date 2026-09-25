
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

## Not done yet

- Registry sync of the 18.010 actions (`scripts/sync-openconnector.py`) — pending.
- Batch runtime test of 50 credential-free actions — pending.
- Public surface for OpenConnector: still loopback-only, intentionally.
