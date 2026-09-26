"""F3.1 — OpenAPI document → MCP tool descriptors.

`scripts/openapi_to_mcp.py` already generates a *runnable server*; this module is
the import path that feeds the registry instead, so an OpenAPI-described API can
appear in the marketplace alongside MCP entries with the same shape.

The rule that shapes the output: **nothing here is executed.** These are
descriptions, so a tool is `tools_listed` and never `call_verified`. Generating
a JSON schema from a spec proves we can read the spec, not that the endpoint
answers.

Three things are deliberately refused rather than attempted:

* an operation with no real path or no real HTTP method — a tool that cannot be
  called is a lie in a tool list;
* a spec whose `servers[0].url` is not public HTTPS — the guard runs at import,
  before the entry is ever shown, so a private target never reaches the catalogue;
* a path parameter that cannot be bound, which is the usual cause of a
  generated tool that only fails at call time.
"""
from __future__ import annotations

import re
from typing import Any

from .ssrf import require_public_url, SsrfError

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_PATH_PARAM = re.compile(r"\{([^{}]+)\}")
_NAME_BAD = re.compile(r"[^0-9a-zA-Z_]+")

MAX_TOOLS = 400


def _clean_name(raw: str) -> str:
    ident = _NAME_BAD.sub("_", str(raw or "")).strip("_").lower()
    if not ident:
        return "operation"
    if ident[0].isdigit():
        ident = "op_" + ident
    return ident[:64]


def _server_url(spec: dict[str, Any]) -> str:
    """First `servers` entry, or "" — a spec may legitimately have none."""
    servers = spec.get("servers")
    if isinstance(servers, list):
        for entry in servers:
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
    return ""


def _security_names(spec: dict[str, Any], op: dict[str, Any]) -> list[str]:
    """Security schemes in force for one operation.

    Operation-level `security` overrides the global list, including when it is
    an empty list (which is how a spec marks an endpoint public), so the global
    value is only a fallback.
    """
    comps = spec.get("components")
    schemes = comps.get("securitySchemes", {}) if isinstance(comps, dict) else {}
    req = op.get("security")
    if req is None:
        req = spec.get("security")
    if not isinstance(req, list) or not req:
        return []
    names: list[str] = []
    for entry in req:
        if not isinstance(entry, dict):
            continue
        for name in entry:
            if name not in names:
                names.append(str(name))
    # Only count a scheme we can see defined; a dangling reference is not auth.
    return [n for n in names if n in schemes]


def _parameters(spec: dict[str, Any], op: dict[str, Any], path_item: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (path_item.get("parameters") or [], op.get("parameters") or []):
        if isinstance(source, list):
            for p in source:
                if isinstance(p, dict) and p.get("name"):
                    merged[str(p["name"])] = p
    return list(merged.values())


def _schema_of(spec: dict[str, Any], raw: Any) -> dict[str, Any]:
    """Resolve a `$ref` one level deep; anything deeper stays a generic object.

    Full dereferencing is not worth the failure modes here: a spec that references
    itself must not send this into a loop, and an unresolved ref is still a valid
    (if untyped) parameter rather than a crash.
    """
    if isinstance(raw, dict) and "$ref" in raw:
        ref = str(raw["$ref"])
        node: Any = spec
        for part in ref.lstrip("#/").split("/"):
            if not part:
                continue
            if not isinstance(node, dict) or part not in node:
                return {"type": "object"}
            node = node[part]
        return node if isinstance(node, dict) else {"type": "object"}
    return raw if isinstance(raw, dict) else {"type": "object"}


def _bound_params(spec: dict[str, Any], op: dict[str, Any], path_item: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Split path parameters into (unbound, arg descriptors).

    A path template mentioning `{id}` with no matching parameter declared is the
    single most common reason a generated tool 404s on first call, so it is
    surfaced here instead of being left for the caller to discover.
    """
    template = set(_PATH_PARAM.findall(str(op.get("_path") or "")))
    unbound = sorted(template)
    args: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in _parameters(spec, op, path_item):
        name = str(p.get("name"))
        if name in seen:
            continue
        seen.add(name)
        if name in template:
            unbound = [u for u in unbound if u != name]
        args.append(
            {
                "name": name,
                "in": str(p.get("in") or "query"),
                "required": name in template or bool(p.get("required")),
                "schema": _schema_of(spec, p.get("schema")),
                "description": str(p.get("description") or "")[:400],
            }
        )
    return unbound, args


def operation_to_tool(spec: dict[str, Any], path: str, method: str, op: dict[str, Any], path_item: dict[str, Any]) -> dict[str, Any] | None:
    """One operation → one descriptor, or ``None`` if it is not callable."""
    if not path.startswith("/") or method not in HTTP_METHODS:
        return None
    op = dict(op)
    op["_path"] = path
    unbound, args = _bound_params(spec, op, path_item)
    if unbound:
        # Declared nowhere in parameters[]: a tool here would be a trapdoor.
        return None
    sec = _security_names(spec, op)
    op_id = str(op.get("operationId") or f"{method}_{_clean_name(path)}")
    return {
        "name": _clean_name(op_id),
        "protocol": "openapi",
        "method": method.upper(),
        "path": path,
        "summary": str(op.get("summary") or op.get("description") or f"{method.upper()} {path}")[:300],
        "description": str(op.get("description") or "")[:1000],
        "args": args,
        "deprecated": bool(op.get("deprecated")),
        "requires_auth": bool(sec),
        "security_schemes": sec,
        "verification": {"discovered": True, "tools_listed": True, "call_verified": False},
    }


def parse_spec(spec: dict[str, Any], *, max_tools: int = MAX_TOOLS) -> dict[str, Any]:
    """Turn a whole document into an import result.

    Returns counts plus ``skipped`` reasons rather than raising on a bad spec: a
    generator that dies on the first malformed operation is useless for a
    catalogue sweep, and "we skipped 12 operations for these reasons" is more
    useful than a stack trace.
    """
    spec = spec if isinstance(spec, dict) else {}
    base = _server_url(spec)
    base_url, base_reason = "", "no_servers_declared"
    if base:
        try:
            require_public_url(base)
            base_url, base_reason = base, "public_https"
        except SsrfError as exc:
            base_reason = f"rejected:{exc}"

    tools: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    deprecated = 0
    paths = spec.get("paths")
    if isinstance(paths, dict):
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in HTTP_METHODS:
                op = path_item.get(method)
                if not isinstance(op, dict):
                    continue
                tool = operation_to_tool(spec, str(path), method, op, path_item)
                if tool is None:
                    skipped.append({"path": str(path), "method": method, "reason": "not_callable"})
                    continue
                if tool["deprecated"]:
                    deprecated += 1
                    continue
                if len(tools) >= max_tools:
                    skipped.append({"path": str(path), "method": method, "reason": "max_tools_reached"})
                    continue
                tools.append(tool)
    info = spec.get("info")
    info = info if isinstance(info, dict) else {}
    return {
        "protocol": "openapi",
        "title": str(info.get("title") or ""),
        "version": str(info.get("version") or ""),
        "base_url": base_url,
        "base_url_status": base_reason,
        "tools": tools,
        "tools_count": len(tools),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "deprecated_dropped": deprecated,
        "auth_required_count": sum(1 for t in tools if t["requires_auth"]),
        # An entry that cannot be reached must not be offered as executable.
        "executable": bool(base_url) and bool(tools),
    }


__all__ = ["parse_spec", "operation_to_tool", "HTTP_METHODS", "MAX_TOOLS"]
