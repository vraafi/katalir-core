"""Generate a real MCP server from public OpenAPI specifications.

Why one server instead of one per API: a Python MCP process costs ~60-80 MB and
the VPS has ~1.7 GB free while serving production. Fifty separate wrappers would
not fit. A single process exposing tools for every API costs one interpreter and
still gives the agent every endpoint, which is what an integration layer is for.

Honesty rules baked into the output:

* an operation only becomes a tool if it has a real path and a real HTTP method;
* the manifest records ``tools_listed`` - never ``call_verified`` - because
  nothing here has been executed yet;
* credential requirements are carried through from the spec's security schemes
  so the UI can badge them instead of pretending they are open.

Known issues in the naive version of this script, fixed here:

* nested same-quote f-strings (``f"{BASE}{tool["path"]}"``) are a SyntaxError;
* FastMCP cannot derive a schema from ``**kwargs``, so each tool gets an
  explicit signature built from the spec's parameters.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
from urllib.parse import urljoin

import httpx

MAX_TOOLS_PER_API = 220
HTTP_METHODS = ("get", "post", "put", "delete", "patch")
RESERVED = {"self", "class", "def", "return", "import", "async", "await", "id", "type"}

SPECS = {
    "github": "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json",
    "kubernetes": "https://raw.githubusercontent.com/kubernetes/kubernetes/master/api/openapi-spec/swagger.json",
    "stripe": "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
    "slack": "https://raw.githubusercontent.com/slackapi/slack-api-specs/master/web-api/slack_web_openapi_v2.json",
    "replicate": "https://api.replicate.com/openapi.json",
    "petstore": "https://petstore3.swagger.io/api/v3/openapi.json",
}



def sanitize(name: str) -> str:
    ident = re.sub(r"[^0-9a-zA-Z_]", "_", str(name or "")).strip("_").lower()
    if not ident or ident[0].isdigit():
        ident = "op_" + ident
    if ident in RESERVED:
        ident += "_"
    return ident[:60]


def fetch_spec(client: httpx.Client, url: str, tries: int = 3):
    """Fetch a spec. Returns (spec, reason)."""
    last = "unknown"
    for attempt in range(1, tries + 1):
        try:
            r = client.get(url)
            if r.status_code in (525, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(min(2**attempt, 8))
                continue
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            return json.loads(r.text), None
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
            time.sleep(min(2**attempt, 8))
    return None, last


def base_url_of(spec: dict, spec_url: str = "") -> str:
    """Resolve the API base URL.

    Relative values are common: the Petstore spec declares ``/v3``, which would
    produce a request URL with no scheme and fail at call time. Those are
    resolved against the origin the spec was fetched from.
    """
    candidates = []
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        candidates.append(str(servers[0].get("url") or ""))
    host = spec.get("host")
    if host:
        scheme = "https"
        for s in spec.get("schemes") or ["https"]:
            if s in ("http", "https"):
                scheme = s
                break
        base_path = str(spec.get("basePath") or "")
        candidates.append(f"{scheme}://{host}{base_path}")
    if spec.get("basePath") and spec_url:
        candidates.append(spec_url.rsplit("/", 1)[0])
    for cand in candidates:
        if not cand:
            continue
        if cand.startswith("http://") or cand.startswith("https://"):
            return cand.rstrip("/")
    return ""


def resolve_base(client: httpx.Client, spec: dict, spec_url: str) -> tuple[str, str]:
    """Pick a base URL that actually answers, not just one that parses.

    Relative ``servers[].url`` values are ambiguous: urljoin drops the spec's own
    path (Petstore's ``/v3`` became ``https://petstore3.swagger.io/v3`` and the
    call failed). So candidates are probed and the first that responds wins.
    Returns (base_url, how) where ``how`` records the evidence.
    """
    declared = ""
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        declared = str(servers[0].get("url") or "")
    absolute = base_url_of(spec, spec_url)
    tries = []
    if absolute:
        tries.append((absolute, "declared"))
    if declared.startswith("/") and spec_url.startswith("http"):
        origin = spec_url.split("://", 1)[0] + "://" + spec_url.split("://", 1)[1].split("/")[0]
        directory = spec_url.rsplit("/", 1)[0]
        tries.append((origin + declared, "origin+declared"))
        tries.append((directory + declared, "spec_dir+declared"))
    for base, how in tries:
        try:
            r = client.get(base, timeout=12, follow_redirects=True)
            if r.status_code < 500:
                return base.rstrip("/"), f"{how}:{r.status_code}"
        except Exception:  # noqa: BLE001
            continue
    return absolute, "declared:unverified"


def security_schemes(spec: dict) -> list[str]:
    return sorted({str(k) for k in (spec.get("components", {}).get("securitySchemes") or {})})


def extract_operations(spec: dict, api: str) -> list[dict]:
    out: list[dict] = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            raw = op.get("operationId") or f"{method}_{path}"
            params = []
            for p in op.get("parameters") or []:
                if not isinstance(p, dict) or p.get("in") not in ("path", "query"):
                    continue
                params.append(
                    {
                        "name": sanitize(p.get("name")),
                        "original": p.get("name"),
                        "in": p.get("in"),
                        "required": bool(p.get("required")) or p.get("in") == "path",
                    }
                )
            out.append(
                {
                    "api": api,
                    "tool": f"{api}_{sanitize(raw)}",
                    "method": method.upper(),
                    "path": path,
                    "summary": (op.get("summary") or op.get("description") or "").strip()[:200],
                    "params": params[:20],
                    "has_body": bool((op.get("requestBody") or {}).get("content")),
                    "deprecated": bool(op.get("deprecated")),
                    "deprecated": bool(op.get("deprecated")),
                }
            )
    out.sort(key=lambda t: t["tool"])
    # filter here, at the source, so no caller can accidentally include
    # operations the spec itself marks as deprecated
    return [o for o in out if not o["deprecated"]]

TOOL_TEMPLATE = '''

@mcp.tool(name="{tool}", description={summary!r})
async def {func}({signature}):
    """{summary}

    {method} {path} on the {api} API. Generated from the public OpenAPI spec;
    tools_listed=True, call_verified=False until an agent actually calls it.
    """
    _current[0] = "{tool}"
    url = _expand(BASE_URLS["{api}"], {path!r}, locals())
    headers = {{"Accept": "application/json"}}
    token = _token_for("{api}")
    if token:
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        if {method!r} == "GET":
            response = await client.get(url, params=_query(locals()), headers=headers)
        elif {method!r} == "DELETE":
            response = await client.delete(url, headers=headers)
        else:
            response = await client.request(
                {method!r}, url, json=_body(locals()), headers=headers
            )
    return {{"status": response.status_code, "body": _safe(response)}}
'''


def render_server(apis: dict[str, dict]) -> str:
    parts = [
        '"""AUTO-GENERATED by scripts/openapi_to_mcp.py - do not edit by hand.\n\n'
        "One MCP process exposing every operation of the configured public OpenAPI\n"
        "specs. Tools are generated from real specs, but nothing here has been\n"
        "executed yet, so the manifest records tools_listed, never call_verified.\n"
        '"""\n'
        "from __future__ import annotations\n\n"
        "import os\nimport re\nfrom typing import Any\n\n"
        "import httpx\nfrom mcp.server.fastmcp import FastMCP\n\n"
        'mcp = FastMCP("katalir-openapi")\n\n'
        "import json as _json\nfrom pathlib import Path as _Path\n\n"
        "_HERE = _Path(__file__).resolve().parent\n"
        'API_META = _json.loads((_HERE / "apis.json").read_text(encoding="utf-8"))\n\n'
        "BASE_URLS = {k: v['base_url'] for k, v in API_META.items()}\n"
        "TOOL_INDEX = {t['tool']: t for v in API_META.values() for t in v['tools']}\n\n"
        "ENV_TOKENS = {\n"
        '    "github": "GITHUB_API_KEY",\n'
        '    "stripe": "STRIPE_API_KEY",\n'
        '    "slack": "SLACK_API_KEY",\n'
        '    "kubernetes": "KUBERNETES_API_KEY",\n'
        '    "replicate": "REPLICATE_API_TOKEN",\n'
        "}\n\n"
        'def _token_for(api: str) -> str:\n'
        '    return os.environ.get(ENV_TOKENS.get(api, ""), "") or ""\n\n'
        'def _expand(base: str, path: str, scope: dict) -> str:\n'
        "    for key, meta in TOOL_INDEX.items():\n"
        '        if key != _current[0]:\n'
        "            continue\n"
        "        for p in meta['params']:\n"
        "            if p['in'] == 'path':\n"
        "                val = scope.get(p['name'])\n"
        "                if val is not None:\n"
        "                    path = path.replace('{' + p['original'] + '}', str(val))\n"
        "    return (base or '') + path\n\n"
        "_current = ['']\n\n"
        'def _query(scope: dict) -> dict:\n'
        "    meta = TOOL_INDEX.get(_current[0], {})\n"
        "    return {p['original']: scope[p['name']] for p in meta.get('params', [])\n"
        "            if p['in'] == 'query' and scope.get(p['name']) is not None}\n\n"
        'def _body(scope: dict) -> dict:\n'
        "    return scope.get('body') or {}\n\n"
        'def _safe(response) -> Any:\n'
        "    try:\n"
        "        return response.json()\n"
        "    except Exception:\n"
        "        return response.text[:2000]\n"
    ]
    for api, meta in apis.items():
        for tool in meta["tools"]:
            required = [p for p in tool["params"] if p["required"]]
            optional = [p for p in tool["params"] if not p["required"]]
            parts_sig = [f"{p['name']}: str = ''" for p in required]
            if tool["has_body"]:
                parts_sig.append("body: dict | None = None")
            parts_sig += [f"{p['name']}: str | None = None" for p in optional]
            # a bare "*" is only legal when something follows it
            signature = ("*, " + ", ".join(parts_sig)) if parts_sig and any(
                "=" in s for s in parts_sig
            ) and not required else ", ".join(parts_sig)
            func = tool["tool"]
            parts.append(
                TOOL_TEMPLATE.format(
                    tool=tool["tool"],
                    func=func,
                    summary=tool["summary"] or f"{tool['method']} {tool['path']}",
                    signature=signature,
                    method=tool["method"],
                    path=tool["path"],
                    api=api,
                ).replace(f"async def {func}(", f"async def {func}(")
            )
    parts.append('\n\nif __name__ == "__main__":\n    mcp.run()\n')
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="generated_mcp")
    ap.add_argument("--max-per-api", type=int, default=MAX_TOOLS_PER_API)
    ap.add_argument("--manifest", default="openapi_tools_manifest.json")
    ap.add_argument("--specs", default="", help="comma separated subset of APIs")
    args = ap.parse_args()

    wanted = [s.strip() for s in args.specs.split(",") if s.strip()] or list(SPECS)
    client = httpx.Client(timeout=40, follow_redirects=True, headers={"User-Agent": "katalir-openapi-gen"})
    apis: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for api in wanted:
        url = SPECS.get(api)
        if not url:
            skipped[api] = "no spec url configured"
            continue
        spec, err = fetch_spec(client, url)
        if spec is None:
            skipped[api] = err
            print(f"{api}: SKIP {err}")
            continue
        ops = extract_operations(spec, api)
        ops = [o for o in ops if not o["deprecated"]][: args.max_per_api]
        if not ops:
            skipped[api] = "no operations"
            continue
        base, how = resolve_base(client, spec, url)
        apis[api] = {
            "base_url": base,
            "base_url_evidence": how,
            "spec_url": url,
            "security_schemes": security_schemes(spec),
            "tools": ops,
        }
        print(f"{api}: {len(ops)} tools generated")
    client.close()

    if not apis:
        print("NOTHING_GENERATED")
        return 1

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    server = out_dir / "katalir_openapi_server.py"
    server.write_text(render_server(apis), encoding="utf-8")
    (out_dir / "apis.json").write_text(json.dumps(apis, indent=1, ensure_ascii=False), encoding="utf-8")

    tools = [t for meta in apis.values() for t in meta["tools"]]
    manifest = {
        "generated_by": "scripts/openapi_to_mcp.py",
        "apis": {a: {"base_url": m["base_url"], "spec_url": m["spec_url"],
                     "security_schemes": m["security_schemes"], "tools_count": len(m["tools"])}
                 for a, m in apis.items()},
        "skipped": skipped,
        "tools_total": len(tools),
        "tools": [
            {**t, "source": "openapi-generated", "attribution_required": False,
             "verification": {"discovered": True, "tools_listed": True, "call_verified": False}}
            for t in tools
        ],
    }
    pathlib.Path(args.manifest).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"TOOLS_TOTAL={len(tools)}")
    print(f"APIS={len(apis)} SKIPPED={len(skipped)}")
    print(f"SERVER={server}")
    print(f"MANIFEST={args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
