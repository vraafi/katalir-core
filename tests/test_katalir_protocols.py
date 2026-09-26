"""F3 protocol importers: what each one may claim, and what it must refuse.

The assertions here are mostly negative on purpose. A test that only proves an
importer can produce tools will pass just as happily on an importer that leaks
`file:///`, because producing tools is easy. The refusals are the contract.

Network-dependent cases use a cached real schema and skip when it is absent, so
an offline run does not turn into a false alarm about the sandbox.
"""
from __future__ import annotations

import json
import pathlib
import time

import pytest

from katalir_protocols.graphql import parse_schema
from katalir_protocols.jsandbox import run_js
from katalir_protocols.mcp_remote import import_remote
from katalir_protocols.openapi import parse_spec
from katalir_protocols.ssrf import is_public_url, require_public_url, SsrfError

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHED_SCHEMA = ROOT / "graphql_schema_countries.json"
CACHED_REMOTE = ROOT / "mcp_remote_results.json"

BLOCKED_URLS = [
    "http://example.com/x",              # plaintext downgrade
    "file:///etc/passwd",
    "file:///c:/Users/user/.env",
    "https://127.0.0.1/",
    "https://localhost/",
    "https://10.0.0.5/",
    "https://192.168.1.1/",
    "https://169.254.169.254/",          # cloud metadata
    "https://metadata.google.internal/",
    "",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_ssrf_refuses_dangerous_targets(url):
    allowed, reason = is_public_url(url)
    assert allowed is False, f"{url!r} was allowed"
    assert reason, "a refusal must say why"


def test_ssrf_allows_known_public_host():
    allowed, reason = is_public_url("https://api.github.com/repos")
    assert allowed is True, reason


def test_require_public_url_raises():
    with pytest.raises(SsrfError):
        require_public_url("http://169.254.169.254/latest/meta-data/")


def _demo_spec(server="https://api.github.com/v3"):
    return {
        "info": {"title": "Demo", "version": "1"},
        "servers": [{"url": server}],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
        "paths": {
            "/repos/{owner}/{repo}": {"get": {"operationId": "getRepo", "parameters": [
                {"name": "owner", "in": "path", "schema": {"type": "string"}},
                {"name": "repo", "in": "path", "schema": {"type": "string"}}],
                "security": [{"bearer": []}]}},
            "/broken/{id}": {"get": {"operationId": "broken", "parameters": []}},
            "/old": {"get": {"operationId": "old", "deprecated": True}},
            "no-leading-slash": {"get": {"operationId": "x"}},
        },
    }


def test_openapi_import_is_callable_only():
    r = parse_spec(_demo_spec())
    assert r["tools_count"] == 1
    assert r["skipped_count"] == 2, r["skipped"]
    assert r["deprecated_dropped"] == 1
    assert r["executable"] is True


def test_openapi_never_claims_call_verified():
    """Reading a spec is not executing it."""
    for t in parse_spec(_demo_spec())["tools"]:
        assert t["verification"] == {"discovered": True, "tools_listed": True, "call_verified": False}


def test_openapi_drops_unbindable_path_param():
    """`/broken/{id}` with no parameter[] would 404 on first call."""
    names = {t["name"] for t in parse_spec(_demo_spec())["tools"]}
    assert "broken" not in names



# --- GraphQL ---------------------------------------------------------------

@pytest.fixture(scope="module")
def countries_schema():
    if not CACHED_SCHEMA.exists():
        pytest.skip("cached GraphQL schema absent; run the importer with network")
    return json.loads(CACHED_SCHEMA.read_text(encoding="utf-8"))


def test_graphql_renders_nullability_exactly(countries_schema):
    """A depth counter flattens [ID!] and [ID] alike, which lies to the caller."""
    r = parse_schema(countries_schema, endpoint="https://countries.trevorblades.com/")
    by_field = {f"{t['type_name']}.{t['field']}": t["return_type"] for t in r["tools"]}
    assert by_field["Continent.countries"] == "[Country!]!"
    assert by_field["Country.capital"] == "String"      # nullable stays bare
    assert by_field["Country.name"] == "String!"        # non-null is not flattened


def test_graphql_excludes_introspection_meta_types(countries_schema):
    r = parse_schema(countries_schema, endpoint="https://countries.trevorblades.com/")
    assert not [t for t in r["tools"] if t["type_name"].startswith("__")]


def test_graphql_never_claims_call_verified(countries_schema):
    r = parse_schema(countries_schema, endpoint="https://countries.trevorblades.com/")
    assert all(t["verification"]["call_verified"] is False for t in r["tools"])


def test_graphql_refuses_private_endpoint(countries_schema):
    r = parse_schema(countries_schema, endpoint="https://127.0.0.1:8080/graphql")
    assert r["executable"] is False
    assert r["endpoint"] == ""



# --- refusals (offline, must never need network) ---------------------------

@pytest.fixture(scope="module")
def live():
    if not CACHED_REMOTE.exists():
        pytest.skip("no cached mcp_remote_results.json")
    return json.loads(CACHED_REMOTE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry,why", [
    ({}, "url_missing"),
    ({"id": "x", "url": ""}, "url_missing"),
    ({"id": "x", "url": "https://api.github.com", "transport": "carrier-pigeon"}, "transport_not_supported"),
    ({"id": "x", "url": "http://127.0.0.1:8000/mcp"}, "ssrf_blocked"),
    ({"id": "x", "url": "https://169.254.169.254/mcp"}, "ssrf_blocked"),
    ({"id": "x", "url": "http://api.github.com/mcp"}, "ssrf_blocked"),
])
def test_remote_import_refuses(entry, why):
    r = import_remote(entry, timeout=5)
    assert r["ok"] is False
    assert why in r["error"], r["error"]
    assert r["tools_count"] == 0
    assert r["verification"] == {"discovered": True, "tools_listed": False, "call_verified": False}


def test_remote_reads_url_from_install_config():
    """The official registry puts the endpoint in install_config.package."""
    r = import_remote(
        {"id": "ac.x/mcp", "install_config": {"transport": "streamable-http", "package": "https://127.0.0.1/mcp"}},
        timeout=5,
    )
    assert "ssrf_blocked" in r["error"], r["error"]


# --- live results (replay of a real registry sweep) -----------------------


def test_live_sweep_actually_listed_tools(live):
    """A sweep that only ever produced errors would still 'pass' a naive test."""
    ok = [r for r in live if r["ok"]]
    assert ok, "no remote server imported successfully"
    assert sum(r["tools_count"] for r in ok) > 0


def test_live_imports_never_claim_call_verified(live):
    """tools/list succeeding is not tools/call succeeding."""
    for r in live:
        assert r["verification"]["call_verified"] is False, r["id"]
        if r["ok"]:
            assert r["verification"]["tools_listed"] is True, r["id"]


def test_live_failures_carry_a_reason(live):
    for r in live:
        if not r["ok"]:
            assert r["error"], r["id"]


def test_live_redirect_was_resolved(live):
    """sh.inference.ac 301s to api.inference.sh; a stale URL would re-301 forever."""
    inf = [r for r in live if r["id"] == "ac.inference.sh/mcp"]
    if not inf:
        pytest.skip("entry not in this sweep")
    assert inf[0].get("redirected") is True
    assert "301" not in inf[0]["error"]


# --- JS sandbox ------------------------------------------------------------

JS_NETWORK_ESCAPES = [
    ('loopback', 'await fetch("http://127.0.0.1:8000/mcp/native"); return 1;'),
    ('metadata', 'await fetch("https://169.254.169.254/latest/meta-data/"); return 1;'),
    ('file', 'await fetch("file:///c:/Users/user/.env"); return 1;'),
    ('localhost', 'await fetch("https://localhost:8000/x"); return 1;'),
    ('private', 'await fetch("https://10.0.0.5/x"); return 1;'),
]


@pytest.mark.parametrize("name,code", JS_NETWORK_ESCAPES, ids=[n for n, _ in JS_NETWORK_ESCAPES])
def test_js_sandbox_blocks_egress(name, code):
    r = run_js(code)
    assert r["ok"] is False, name
    assert r["requests"], name
    assert r["requests"][0]["allowed"] is False, name
    assert "ssrf_blocked" in r["requests"][0]["reason"], name


@pytest.mark.parametrize("name,expr", [
    ("require", "typeof require"),
    ("process", "typeof process"),
    ("Buffer", "typeof Buffer"),
    ("globalThis.process", "typeof globalThis.process"),
    ("globalThis.require", "typeof globalThis.require"),
])
def test_js_sandbox_hides_node_globals(name, expr):
    """`fs` and `child_process` must be unreachable even though the host has them."""
    r = run_js(f"return {expr};")
    assert r["ok"] is True, r
    assert r["value"] == "undefined", f"{name} leaked: {r['value']!r}"


@pytest.mark.parametrize("name,code", [
    ("eval", 'return eval("1+1");'),
    ("Function", 'return Function("return 1")();'),
    ("import", "return typeof import;"),
])
def test_js_sandbox_blocks_code_generation(name, code):
    r = run_js(code)
    assert r["ok"] is False, f"{name} was not blocked"
    assert r["value"] is None, name


def test_js_sandbox_contains_infinite_loop():
    started = time.time()
    r = run_js("while(true){}")
    elapsed = time.time() - started
    assert r["ok"] is False
    assert elapsed < 20, f"took {elapsed:.1f}s"


def test_js_sandbox_isolates_runs():
    """One script must not be able to poison the next."""
    run_js("while(true){}")
    r = run_js("return 1+1;")
    assert r["ok"] is True, r
    assert r["value"] == 2


def test_js_sandbox_runs_pure_code():
    r = run_js("return 6*7;")
    assert r["ok"] is True, r
    assert r["value"] == 42
    assert r["verification"]["call_verified"] is True


def test_js_sandbox_rejects_empty_program():
    r = run_js("   ")
    assert r["ok"] is False
    assert r["error"] == "empty_program"

def test_openapi_carries_auth_from_security_schemes():
    tool = parse_spec(_demo_spec())["tools"][0]
    assert tool["requires_auth"] is True
    assert tool["security_schemes"] == ["bearer"]


def test_openapi_refuses_private_server():
    r = parse_spec(_demo_spec(server="https://10.0.0.1/v3"))
    assert r["base_url"] == ""
    assert r["executable"] is False
    assert "rejected" in r["base_url_status"]


def test_openapi_public_server_is_executable():
    r = parse_spec(_demo_spec())
    assert r["base_url"] == "https://api.github.com/v3"
    assert r["executable"] is True
