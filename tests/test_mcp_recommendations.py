import mcp_registry


def test_recommendations_are_bounded():
    items = mcp_registry.recommend_servers("telegram", limit=3)
    assert len(items) <= 3
    assert all("id" in item and "name" in item for item in items)
