"""Sync the OpenConnector catalogue into a Katalir registry file.

Read-only against OpenConnector. Never prints credentials.

OpenConnector is bound to loopback, so this script either talks to it directly
(``--base-url``) or reads a previously dumped catalogue (``--input``).

The output matches the shape of ``composio_toolkits.json`` so
``mcp_registry.load_cached()`` can merge it, with one important difference:
verification is split into three independent flags, because "seen in the
catalogue", "listable by an MCP client" and "really executed" are very
different claims:

    discovered     - present in the OpenConnector catalogue
    tools_listed   - reachable through the OpenConnector MCP meta-layer
    call_verified  - a real ``tools/call`` succeeded (only set by the batch test)

Re-running is idempotent: source keys are the stable OpenConnector action ids
and previously earned ``call_verified`` flags are preserved, never reset.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.request
from collections import Counter, defaultdict

DESC_LIMIT = 160


def load_env_token(env_file: str, name: str) -> str:
    for line in pathlib.Path(env_file).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"token {name} not found in {env_file}")


def fetch_actions(base_url: str, token: str, timeout: int = 180) -> list[dict]:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/actions",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if not isinstance(data, list):
        raise SystemExit("/api/actions did not return a list")
    return [a for a in data if isinstance(a, dict) and a.get("id")]


def load_previous(path: str) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def no_input_required(action: dict) -> bool:
    schema = action.get("inputSchema")
    if not isinstance(schema, dict):
        return True
    return not schema.get("properties") and not schema.get("required")


def credential_free(action: dict) -> bool:
    """True when the action declares no OAuth scope / provider permission.

    This is *not* the same as "runnable without a connection": use
    :func:`no_auth_runnable` for that, based on OpenConnector's own
    ``execution.noAuthRunnable`` flag.
    """
    return not action.get("requiredScopes") and not action.get("providerPermissions")


def execution_info(action: dict) -> dict:
    ex = action.get("execution")
    return ex if isinstance(ex, dict) else {}


def no_auth_runnable(action: dict) -> bool:
    """OpenConnector's own verdict: this action runs with no credentials."""
    return bool(execution_info(action).get("noAuthRunnable"))


def locally_executable(action: dict) -> bool:
    ex = execution_info(action)
    return bool(ex.get("locallyExecutable")) and not ex.get("catalogOnly")


def auth_types(action: dict) -> list:
    return list(execution_info(action).get("requiredAuthTypes") or [])



def load_verified(path: str) -> dict:
    """Map action id -> status from a batch test report."""
    if not path:
        return {}
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for rec in data.get("records") or []:
        if isinstance(rec, dict) and rec.get("action_id"):
            out[str(rec["action_id"])] = rec
    for aid in data.get("call_verified_actions") or []:
        out.setdefault(str(aid), {"action_id": str(aid), "status": "ok"})
    return out


def build(actions: list[dict], previous: dict, verified: dict | None = None) -> tuple[dict, dict]:
    by_service: dict[str, list[dict]] = defaultdict(list)
    for a in actions:
        by_service[str(a.get("service") or "unknown")].append(a)

    prev_actions: dict[str, dict] = {}
    for entry in previous.values():
        if not isinstance(entry, dict):
            continue
        for t in entry.get("tools") or []:
            if isinstance(t, dict) and t.get("name"):
                prev_actions[t["name"]] = t

    out: dict[str, dict] = {}
    verified = verified or {}
    for service, items in sorted(by_service.items()):
        items.sort(key=lambda a: str(a.get("name") or ""))
        tools = []
        for a in items:
            name = str(a.get("name") or a["id"])
            old = prev_actions.get(name) or {}
            seen = verified.get(str(a["id"])) or {}
            # a batch-test result is authoritative; otherwise keep what we had
            status = str(seen.get("status") or old.get("status") or "discovered")
            call_verified = bool(seen.get("status") == "ok") or bool(old.get("call_verified"))
            tools.append(
                {
                    "id": str(a["id"]),
                    "name": name,
                    "description": str(a.get("description") or "")[:DESC_LIMIT],
                    "operation_type": str(a.get("operationType") or ""),
                    "credential_free": credential_free(a),
                    "no_input": no_input_required(a),
                    "no_auth_runnable": no_auth_runnable(a),
                    "locally_executable": locally_executable(a),
                    "auth_types": auth_types(a),
                    "status": status,
                    "call_verified": call_verified,
                }
            )
        out[service] = {
            "id": f"openconnector/{service}",
            "slug": service,
            "name": service,
            "description": str(items[0].get("description") or f"OpenConnector provider {service}")[:DESC_LIMIT],
            "install_config": {
                "transport": "mcp-meta-layer",
                "package": "",
                "install_method": "openconnector",
                "mcp_target": "openconnector",
                "mcp_tools": [
                    "openconnector_list_apps",
                    "openconnector_list_connections",
                    "openconnector_search_actions",
                    "openconnector_get_action_guide",
                    "openconnector_execute_action",
                ],
            },
            "tenant_scope": "user",
            "validated": True,
            "tools": tools,
            "tools_count": len(tools),
            "auth_schemes": [],
            "no_auth": not any(not t["credential_free"] for t in tools),
            "no_auth_runnable_count": sum(1 for t in tools if t["no_auth_runnable"]),
            "source": "openconnector",
            "runtime_verified": any(t["call_verified"] for t in tools),
            "verification": {
                "discovered": True,
                "tools_listed": True,
                "call_verified": any(t["call_verified"] for t in tools),
            },
        }
    return out, summarize(actions)


def summarize(actions: list[dict]) -> dict:
    cf = [a for a in actions if credential_free(a)]
    both = [a for a in actions if credential_free(a) and no_input_required(a)]
    na = [a for a in actions if no_auth_runnable(a)]
    return {
        "actions_total": len(actions),
        "services_total": len({a.get("service") for a in actions}),
        "credential_free_actions": len(cf),
        "credential_free_and_no_input": len(both),
        "no_auth_runnable_actions": len(na),
        "no_auth_runnable_and_no_input": sum(1 for a in na if no_input_required(a)),
        "no_auth_runnable_services": len({a.get("service") for a in na}),
        "locally_executable_actions": sum(1 for a in actions if locally_executable(a)),
        "auth_type_histogram": dict(Counter(t for a in actions for t in auth_types(a)).most_common()),
        "operation_types": dict(Counter(str(a.get("operationType") or "") for a in actions).most_common()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="local catalogue dump (JSON list of actions)")
    ap.add_argument("--base-url", help="OpenConnector base URL, e.g. http://127.0.0.1:3010")
    ap.add_argument("--admin-token-file", default="/root/.openconnector.env")
    ap.add_argument("--admin-token-env", default="OOMOL_CONNECT_ADMIN_TOKEN")
    ap.add_argument("--out", default="openconnector_actions.json")
    ap.add_argument("--report", default="openconnector-sync-report.json")
    ap.add_argument("--previous", default="", help="registry file to preserve call_verified from")
    ap.add_argument("--verified-from", default="", help="batch test report to import call_verified from")
    args = ap.parse_args()

    if args.input:
        raw = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8"))
        actions = [a for a in raw if isinstance(a, dict)]
    elif args.base_url:
        actions = fetch_actions(args.base_url, load_env_token(args.admin_token_file, args.admin_token_env))
    else:
        ap.error("one of --input or --base-url is required")

    seen, unique = set(), []
    for a in actions:
        aid = str(a.get("id") or "")
        if aid and aid not in seen:
            seen.add(aid)
            unique.append(a)

    previous = load_previous(args.previous or args.out)
    verified = load_verified(args.verified_from)
    registry, summary = build(unique, previous, verified)
    summary["duplicate_ids_dropped"] = len(actions) - len(unique)
    summary["actions_call_verified"] = sum(
        1 for e in registry.values() for t in e["tools"] if t.get("call_verified")
    )
    summary["services_call_verified"] = sum(
        1 for e in registry.values() if (e.get("verification") or {}).get("call_verified")
    )

    pathlib.Path(args.out).write_text(json.dumps(registry, indent=1, ensure_ascii=False), encoding="utf-8")
    pathlib.Path(args.report).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"SERVICES={summary['services_total']}")
    print(f"ACTIONS={summary['actions_total']}")
    print(f"CREDENTIAL_FREE={summary['credential_free_actions']}")
    print(f"CREDENTIAL_FREE_NO_INPUT={summary['credential_free_and_no_input']}")
    print(f"NO_AUTH_RUNNABLE={summary['no_auth_runnable_actions']} (services={summary['no_auth_runnable_services']}, no_input={summary['no_auth_runnable_and_no_input']})")
    print(f"LOCALLY_EXECUTABLE={summary['locally_executable_actions']}")
    print(f"AUTH_TYPES={json.dumps(summary['auth_type_histogram'])}")
    print(f"OPERATION_TYPES={json.dumps(summary['operation_types'])}")
    print(f"OUT={args.out} ({os.path.getsize(args.out) / 1_048_576:.2f} MB)")
    print(f"ACTIONS_CALL_VERIFIED={summary['actions_call_verified']}")
    print(f"SERVICES_CALL_VERIFIED={summary['services_call_verified']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
