import mcp_registry


def test_registry_coverage_does_not_promote_metadata():
    c = mcp_registry.coverage()
    assert c["total"] == c["executable"] + c["metadata_only"]
    assert all(s["install_config"]["transport"] != "metadata-only" for s in mcp_registry.executable_servers())


def test_recommendations_are_bounded():
    items = mcp_registry.recommend_servers("telegram", limit=3)
    assert len(items) <= 3
    assert all("id" in item and "name" in item for item in items)
