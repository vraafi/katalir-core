"""Glama registry contract tests (licence + honesty, not volume)."""
import json
import pathlib

import mcp_registry


ROOT = pathlib.Path(__file__).resolve().parent.parent
GLAMA = ROOT / "glama_servers.json"
CONNECTORS = ROOT / "glama_connectors.json"


def _load(name):
    return json.loads(pathlib.Path(name).read_text(encoding="utf-8"))


def test_glama_entries_ada_dan_bertanda_atribusi():
    """Every Glama record must carry source + source_url + attribution flag.

    This is the API Data License contract: without these three fields the UI
    cannot render the required credit and backlink.
    """
    data = _load(GLAMA)
    assert len(data) > 0
    for rec in list(data.values())[:200]:
        assert rec["source"] == "glama"
        assert rec["attribution_required"] is True
        assert rec["source_url"].startswith("https://glama.ai/")


def test_entri_glama_tidak_otomatis_executable():
    """Metadata presence must never upgrade a Glama entry to executable."""
    mcp_registry.load_cached()
    page = mcp_registry.list_servers(source="glama", limit=50)
    assert page["total"] > 0
    for item in page["items"]:
        if item["source"] == "glama" and not item.get("runtime_verified"):
            assert item["install_config"]["transport"] == "metadata-only"


def test_filter_source_memisahkan_glama_dan_lainnya():
    mcp_registry.load_cached()
    counts = mcp_registry.source_counts()
    assert "glama" in counts and "glama-connector" in counts
    glama_only = mcp_registry.list_servers(source="glama", limit=1)
    assert all(i["source"] in {"glama", "glama-connector"} for i in glama_only["items"])
    composio_only = mcp_registry.list_servers(source="composio", limit=5)
    assert all(i["source"] == "composio" for i in composio_only["items"])


def test_konektor_hanya_tools_listed_bukan_call_verified():
    """The batch verifier only calls initialize + tools/list.

    It must therefore never set call_verified, or the marketing claim would
    outrun the evidence.
    """
    data = _load(CONNECTORS)
    probed = [r for r in data.values() if r.get("verification", {}).get("tools_listed")]
    assert probed, "expected at least one runtime-verified connector"
    for rec in probed:
        assert rec["verification"].get("call_verified") is not True


def test_endpoint_native_diturunkan_dari_kode():
    """The Native tab must reflect provider_registry, never a hardcoded number.

    A hardcoded count is exactly how the "Native" tab came to mean the ToolSDK
    catalogue; deriving it here keeps the UI honest by construction.
    """
    import provider_registry as pr
    from fastapi.testclient import TestClient

    import api_server

    client = TestClient(api_server.app)
    r = client.get("/mcp/native")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(pr.PROVIDERS)
    assert body["total"] >= 5
    names = {i["name"] for i in body["items"]}
    assert names == set(pr.PROVIDERS)
    for item in body["items"]:
        assert item["source"] == "native"
        assert "call_verified" in item["verification"]
    # only providers that need no secret may claim runtime_verified
    for item in body["items"]:
        assert item["runtime_verified"] is (not item["needs_credential"])


def test_endpoint_sources_menyertakan_native():
    from fastapi.testclient import TestClient

    import api_server
    import provider_registry as pr

    body = TestClient(api_server.app).get("/mcp/registry/sources").json()
    assert body["sources"]["native"] == len(pr.PROVIDERS)
    assert body["attribution"]["glama"]["required"] is True

def test_ssrf_guard_menolak_url_non_publik():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gv", ROOT / "scripts" / "batch-verify-glama-connectors.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.is_public_https("http://example.com/mcp")[0] is False
    assert mod.is_public_https("https://127.0.0.1/mcp")[0] is False
