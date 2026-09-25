"""Tests for the catalogue deduplication engine.

The whole point of mcp_dedup is that no headline number may be inflated, so the
tests assert the *anti*-inflation properties, not just that it runs.
"""
import json
import pathlib

import mcp_dedup

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_normalize_menyatukan_variasi_nama():
    assert mcp_dedup.normalize_name("@modelcontextprotocol/server-memory") == mcp_dedup.normalize_name("Memory MCP Server")
    assert mcp_dedup.normalize_name("Google_Sheets-API") == "google sheets"
    assert mcp_dedup.normalize_name("Gmail") == mcp_dedup.normalize_name("gmail")


def test_load_registry_tidak_menimpa_antar_sumber():
    """Two sources may use the same bare key; neither may vanish."""
    reg = mcp_dedup.load_registry()
    assert reg, "registry should not be empty"
    for key in reg:
        assert ":" in key, f"key must be namespaced: {key}"
    # the raw file totals must survive the load
    raw = 0
    for name in mcp_dedup.REGISTRY_FILES.values():
        p = ROOT / name
        if p.exists():
            raw += sum(1 for v in json.loads(p.read_text(encoding="utf-8")).values() if isinstance(v, dict))
    assert len(reg) == raw, f"lost entries on load: {len(reg)} != {raw}"


def test_dedup_tidak_perbanyak_verifikasi():
    """One verified entry among duplicates yields exactly one verified group."""
    entries = {
        "a:x": {"name": "Slack", "source": "a", "verification": {"call_verified": True, "tools_listed": True, "discovered": True}},
        "b:y": {"name": "slack mcp server", "source": "b", "verification": {"call_verified": False, "tools_listed": True, "discovered": True}},
        "c:z": {"name": "Notion", "source": "c", "verification": {"call_verified": False, "tools_listed": False, "discovered": True}},
    }
    canon, stats = mcp_dedup.dedup_catalog(entries)
    assert stats["before"] == 3
    assert stats["after"] == 2
    assert stats["unique_verified"] == 1
    slack = next(e for e in canon if e["canonical_key"] == "slack")
    assert set(slack["sources"]) == {"a", "b"}
    assert len(slack["member_ids"]) == 2


def test_dedup_naik_tidak_menurunkan_bukti():
    """A verification earned by any member survives the collapse."""
    entries = {
        "a:x": {"name": "Ghost", "source": "a"},
        "b:y": {"name": "ghost", "source": "b", "verification": {"call_verified": True, "tools_listed": True, "discovered": True}},
    }
    canon, stats = mcp_dedup.dedup_catalog(entries)
    assert stats["after"] == 1
    assert canon[0]["verification"]["call_verified"] is True
    assert canon[0]["unique_verified"] is True


def test_dedup_katalog_sebenarnya_tidak_mengembang():
    """On the real catalogue the unique count must never exceed the input."""
    reg = mcp_dedup.load_registry()
    canon, stats = mcp_dedup.dedup_catalog(reg)
    assert stats["after"] <= stats["before"]
    assert 0 < stats["unique_percent"] <= 100.0
    assert stats["unique_verified"] <= stats["after"]
    # every canonical entry keeps its provenance
    assert all(e.get("sources") and e.get("member_ids") for e in canon)
