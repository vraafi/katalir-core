"""FASE 4 — generator connector OpenAPI (openapi_connectors).

Memakai ulang `scripts/openapi_to_mcp.py`; tes memastikan kontrak entri
sesuai yang dibaca `mcp_registry` tanpa memanggil jaringan.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import openapi_connectors as oc  # noqa: E402


# --------------------------------------------------------------------------
# B — BASIC
# --------------------------------------------------------------------------

def test_b1_slug_sanitization():
    assert oc.slug_for("ably.io:platform") == "ably-io-platform"
    assert oc.slug_for("1password.local:connect") == "1password-local-connect"
    assert oc.slug_for("6-dot-authentiqio.appspot.com") == "6-dot-authentiqio-appspot-com"


def test_b2_reuses_existing_generator():
    g = oc._load_generator()
    for fn in ("fetch_spec", "extract_operations", "resolve_base",
               "security_schemes", "sanitize"):
        assert callable(getattr(g, fn)), fn


# --------------------------------------------------------------------------
# E — EDGE
# --------------------------------------------------------------------------

def test_e1_slug_never_empty():
    assert oc.slug_for("") == "api"
    assert oc.slug_for("!!!") == "api"


def test_e2_slug_truncated():
    assert len(oc.slug_for("x" * 500)) <= 80


def test_e3_build_entry_returns_none_without_operations():
    spec = {"info": {"title": "Empty"}, "paths": {}}
    assert oc.build_entry("empty.io", spec, "https://x/spec.json") is None


# --------------------------------------------------------------------------
# X — ERROR
# --------------------------------------------------------------------------

def test_x1_build_entry_no_network_needed_for_paths(monkeypatch):
    """resolve_base gagal -> entry tetap dibuat, base_url kosong (jujur)."""
    spec = {
        "info": {"title": "Tiny", "version": "1.0"},
        "paths": {"/ping": {"get": {"operationId": "ping", "responses": {}}}},
    }
    entry = oc.build_entry("tiny.io", spec, "https://tiny.io/spec.json")
    assert entry is not None
    assert entry["id"] == "openapi/tiny-io"
    assert len(entry["tools"]) == 1


def test_x2_skips_deprecated_operations():
    spec = {
        "info": {"title": "Dep", "version": "1.0"},
        "paths": {
            "/old": {"get": {"operationId": "old", "deprecated": True, "responses": {}}},
            "/new": {"get": {"operationId": "new", "responses": {}}},
        },
    }
    entry = oc.build_entry("dep.io", spec, "https://dep.io/spec.json")
    names = [t["name"] for t in entry["tools"]]
    assert len(names) == 1
    assert "old" not in " ".join(names)


# --------------------------------------------------------------------------
# P — PERFORMANCE
# --------------------------------------------------------------------------

def test_p1_build_entry_large_spec_respects_cap():
    paths = {}
    for i in range(600):
        paths[f"/r{i}"] = {"get": {"operationId": f"op{i}", "responses": {}}}
    spec = {"info": {"title": "Big", "version": "1.0"}, "paths": paths}
    entry = oc.build_entry("big.io", spec, "https://big.io/spec.json",
                           max_per_api=220)
    assert len(entry["tools"]) == 220


def test_p2_slug_bulk_is_fast():
    import time
    t0 = time.time()
    for i in range(2000):
        oc.slug_for(f"api{i}.example.com:v1")
    assert time.time() - t0 < 3.0


# --------------------------------------------------------------------------
# S — SECURITY / HONESTY
# --------------------------------------------------------------------------

def test_s1_call_verified_always_false():
    """Tidak ada satu pun tool yang boleh diklaim sudah dieksekusi."""
    spec = {
        "info": {"title": "S", "version": "1.0"},
        "paths": {"/a": {"get": {"operationId": "a", "responses": {}}}},
    }
    entry = oc.build_entry("s.io", spec, "https://s.io/spec.json")
    assert all(t["call_verified"] is False for t in entry["tools"])
    assert entry["verification"]["call_verified"] is False
    assert entry["runtime_verified"] is False


def test_s2_no_auth_derived_from_schemes():
    spec_open = {
        "info": {"title": "O", "version": "1"},
        "paths": {"/a": {"get": {"operationId": "a", "responses": {}}}},
    }
    entry = oc.build_entry("o.io", spec_open, "https://o.io/spec.json")
    assert entry["no_auth"] is True

    spec_auth = {
        "info": {"title": "A", "version": "1"},
        "paths": {"/a": {"get": {"operationId": "a", "responses": {}}}},
        "components": {"securitySchemes": {"k": {"type": "apiKey", "name": "X"}}},
        "security": [{"k": []}],
    }
    entry2 = oc.build_entry("a.io", spec_auth, "https://a.io/spec.json")
    assert entry2["no_auth"] is False


# --------------------------------------------------------------------------
# I — INTEGRATION
# --------------------------------------------------------------------------

def test_i1_entry_matches_registry_contract():
    spec = {
        "info": {"title": "C", "version": "1.0"},
        "paths": {"/a": {"get": {"operationId": "a", "responses": {}}}},
    }
    e = oc.build_entry("c.io", spec, "https://c.io/spec.json")
    for key in ("id", "slug", "name", "description", "category", "source",
                "source_url", "tools", "no_auth", "validated"):
        assert key in e, key
    assert e["source"] == "openapi-generated"
    assert e["category"] == "mcp-openapi"
    assert e["id"].startswith("openapi/")


def test_i2_describe_contract():
    d = oc.describe()
    assert d["id_prefix"] == "openapi/"
    assert d["call_verified_policy"] == "always False"
