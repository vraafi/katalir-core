"""F3.2 — GraphQL introspection schema → MCP tool descriptors.

A GraphQL schema is a better description of an API than an OpenAPI document: one
endpoint, the type system gives real argument types, and introspection returns
it in a single round trip. That also makes it a hazard, because introspection is
often enabled on hosts that are otherwise closed, and a schema is an invitation
to send arbitrary queries.

So the OpenAPI rule holds: reading a schema produces *descriptions*, and a
description is `tools_listed`, never `call_verified`. This module does not send
the queries it generates.
"""
from __future__ import annotations

import re
from typing import Any

from .ssrf import require_public_url, SsrfError

MAX_TOOLS = 300
_NAME_BAD = re.compile(r"[^0-9a-zA-Z_]+")

INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind name description
      fields(includeDeprecated: false) {
        name description
        args { name description type { ...TypeRef } }
        type { ...TypeRef }
      }
    }
  }
}
fragment TypeRef on __Type {
  kind name ofType { kind name ofType { kind name ofType { kind name } } }
}
""".strip()


def _clean_name(raw: str) -> str:
    ident = _NAME_BAD.sub("_", str(raw or "")).strip("_").lower()
    if not ident or ident[0].isdigit():
        ident = "q_" + ident
    return ident[:64]


def _type_name(node: Any) -> str:
    """Render a GraphQL type reference exactly, e.g. ``[ID!]!``.

    The wrappers are walked recursively rather than by counting depth. A depth
    counter flattens ``[ID!]`` and ``[ID]`` to the same ``[ID]``, which tells a
    caller that a non-null element is nullable — and the caller then generates
    null-handling the schema forbids, or worse, a value the server rejects at
    runtime. Getting the nullability right is the whole point of reading the
    type system.
    """
    cur = node if isinstance(node, dict) else {}
    kind = cur.get("kind")
    if kind == "NON_NULL":
        return _type_name(cur.get("ofType")) + "!"
    if kind == "LIST":
        return "[" + _type_name(cur.get("ofType")) + "]"
    return str(cur.get("name") or "Unknown")


def _required(node: Any) -> bool:
    cur = node if isinstance(node, dict) else {}
    return cur.get("kind") == "NON_NULL"


def parse_schema(schema: dict[str, Any], *, endpoint: str = "", max_tools: int = MAX_TOOLS) -> dict[str, Any]:
    """Introspection result → import result.

    `__schema.types` is walked rather than reading only the root `queryType`.
    Reading only the root would expose one field per top-level query and nothing
    reachable below it; the walker descends into every object type, which is
    where most real operations actually live.
    """
    schema = schema if isinstance(schema, dict) else {}
    root = schema.get("__schema")
    root = root if isinstance(root, dict) else {}

    base_url, base_reason = "", "no_endpoint"
    if endpoint:
        try:
            require_public_url(endpoint)
            base_url, base_reason = endpoint, "public_https"
        except SsrfError as exc:
            base_reason = f"rejected:{exc}"

    tools: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    types = root.get("types")
    reserved = {"__schema", "__type", "__typename"}
    if isinstance(types, list):
        for t in types:
            if not isinstance(t, dict):
                continue
            tname = str(t.get("name") or "")
            if not tname or tname.startswith("__") or t.get("kind") != "OBJECT":
                continue
            fields = t.get("fields")
            if not isinstance(fields, list):
                continue
            for f in fields:
                if not isinstance(f, dict):
                    continue
                fname = str(f.get("name") or "")
                if not fname or fname in reserved or fname.startswith("_"):
                    continue
                if len(tools) >= max_tools:
                    skipped.append({"type": tname, "field": fname, "reason": "max_tools_reached"})
                    continue
                args = f.get("args") if isinstance(f.get("args"), list) else []
                tools.append(
                    {
                        "name": _clean_name(f"{tname}_{fname}"),
                        "protocol": "graphql",
                        "type_name": tname,
                        "field": fname,
                        "return_type": _type_name(f.get("type")),
                        "summary": str(f.get("description") or f"{tname}.{fname}")[:300],
                        "description": str(f.get("description") or "")[:1000],
                        "args": [
                            {
                                "name": str(a.get("name") or ""),
                                "type": _type_name(a.get("type")),
                                "required": _required(a.get("type")),
                                "description": str(a.get("description") or "")[:400],
                            }
                            for a in args
                            if isinstance(a, dict)
                        ],
                        "deprecated": bool(f.get("isDeprecated")),
                        # Introspection says nothing about how to authenticate,
                        # so this stays True rather than being guessed at.
                        "requires_auth": True,
                        "verification": {"discovered": True, "tools_listed": True, "call_verified": False},
                    }
                )
    return {
        "protocol": "graphql",
        "query_type": str((root.get("queryType") or {}).get("name") or ""),
        "has_mutation": bool(root.get("mutationType")),
        "endpoint": base_url,
        "endpoint_status": base_reason,
        "tools": tools,
        "tools_count": len(tools),
        "skipped": skipped,
        "skipped_count": len(skipped),
        # No endpoint means nothing can be called, and the badge must say so.
        "executable": bool(base_url) and bool(tools),
    }


__all__ = ["parse_schema", "INTROSPECTION_QUERY", "MAX_TOOLS"]
