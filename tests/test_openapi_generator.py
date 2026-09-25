"""Tests for the OpenAPI -> MCP generator.

These assert the generator's honesty guarantees, not just that it runs:

* a tool exists only for a real path + HTTP method;
* the manifest says ``tools_listed`` and never ``call_verified`` by default -
  generated code has not been executed merely by existing;
* base URLs are absolute, because a relative one produced a scheme-less URL
  that failed at call time.
"""
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import openapi_to_mcp as gen  # noqa: E402


def _spec(paths: dict, servers=None) -> dict:
    return {"openapi": "3.1.0", "servers": servers or [], "paths": paths, "components": {}}


def test_extract_hanya_method_http_valid():
    spec = _spec(
        {
            "/pets": {"get": {"operationId": "listPets", "summary": "List"},
                      "head": {"operationId": "ignored"},
                      "parameters": "not-a-dict"},
            "/pets/{id}": {"get": {"operationId": "getPet",
                                   "parameters": [{"name": "id", "in": "path", "required": True}]}},
        }
    )
    ops = gen.extract_operations(spec, "demo")
    assert [o["tool"] for o in ops] == ["demo_getpet", "demo_listpets"]
    pet = next(o for o in ops if o["tool"] == "demo_getpet")
    assert pet["method"] == "GET"
    assert pet["params"][0]["in"] == "path"
    assert pet["params"][0]["required"] is True


def test_deprecated_operation_tidak_dijadikan_tool():
    spec = _spec({"/x": {"get": {"operationId": "old", "deprecated": True}}})
    assert gen.extract_operations(spec, "demo") == []


def test_base_url_hanya_mutlak_atau_kosong():
    """A relative server URL must not be silently turned into a wrong host.

    urljoin('/v3') drops the spec's own path, which is what made the first
    generated call fail, so the plain resolver refuses relative values and
    ``resolve_base`` is the one allowed to guess - with a probe as evidence.
    """
    assert gen.base_url_of(_spec({}, [{"url": "https://api.example.com/v1"}]), "") == "https://api.example.com/v1"
    assert gen.base_url_of(_spec({}, [{"url": "/v3"}]), "") == ""
    swagger = {"host": "petstore3.swagger.io", "schemes": ["https"], "basePath": "/api/v3", "paths": {}, "components": {}}
    assert gen.base_url_of(swagger, "") == "https://petstore3.swagger.io/api/v3"


def test_resolve_base_mengembalikan_bukti():
    import httpx

    client = httpx.Client(timeout=10, follow_redirects=True)
    try:
        absolute, how = gen.resolve_base(client, _spec({}, [{"url": "https://petstore3.swagger.io/api/v3"}]), "")
        assert absolute == "https://petstore3.swagger.io/api/v3"
        assert how.startswith("declared")
    finally:
        client.close()


def test_sanitize_membuat_identifier_python_valid():
    for raw in ["get pet by id", "/repos/{owner}/{repo}", "9lives", "class", ""]:
        ident = gen.sanitize(raw)
        assert ident.isidentifier(), raw


def test_manifest_hanya_call_verified_bila_ada_bukti():
    """Being generated is not being verified.

    A tool may only be call_verified when the manifest records what was
    actually executed; everything else must stay tools_listed.
    """
    manifest = ROOT / "openapi_tools_manifest.json"
    if not manifest.exists():
        return  # generator has not been run in this checkout
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["tools_total"] == len(data["tools"])
    verified = 0
    for tool in data["tools"]:
        v = tool["verification"]
        assert v["discovered"] is True
        assert v["tools_listed"] is True
        if v.get("call_verified"):
            assert tool.get("call_verified_evidence"), f"no evidence for {tool['tool']}"
            verified += 1
    assert verified == data.get("call_verified", verified)
    assert verified <= len(data["tools"])
