import api_server
from fastapi.testclient import TestClient

client = TestClient(api_server.app)

def test_tenant_isolation(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    monkeypatch.setattr(api_server.db, "is_configured", lambda: False)
    users = {"Bearer a": {"id": "user-a", "email": "a@example.com"}, "Bearer b": {"id": "user-b", "email": "b@example.com"}}
    monkeypatch.setattr(api_server.security, "get_current_user", lambda auth: users[auth])
    r = client.post("/mcp/install", json={"mcp_id": "time", "config": {"tz": "Asia/Jakarta"}, "confirmed": True}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 200
    assert len(client.get("/mcp/my-instances", headers={"Authorization": "Bearer a"}).json()["instances"]) == 1
    assert client.get("/mcp/my-instances", headers={"Authorization": "Bearer b"}).json()["instances"] == []
    assert client.delete("/mcp/uninstall/time", headers={"Authorization": "Bearer b"}).status_code == 404
    assert client.delete("/mcp/uninstall/time", headers={"Authorization": "Bearer a"}).status_code == 200


def test_workflow_mcp_surface_is_owner_scoped(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    monkeypatch.setattr(api_server.db, "is_configured", lambda: False)
    rows = [{"id": "wf-1", "name": "Daily Telegram", "description": "Kirim laporan"}]
    monkeypatch.setattr(api_server.security, "get_current_user", lambda auth: {"id": "user-a" if auth == "Bearer a" else "user-b", "email": "a@example.com" if auth == "Bearer a" else "b@example.com"})
    monkeypatch.setattr(api_server.db, "list_workflows", lambda uid: rows if uid == "user-a" else [])
    monkeypatch.setattr(api_server.db, "get_workflow", lambda wid, uid: {"id": wid, "flow_data": {"nodes": [], "edges": []}})
    monkeypatch.setattr(api_server.engine, "launch_execution", lambda *a, **k: "exec-1")
    client = TestClient(api_server.app)
    listed = client.get("/mcp/server/tools", headers={"Authorization": "Bearer a"})
    assert listed.status_code == 200
    assert listed.json()["tools"][0]["name"] == "katalir_workflow__daily-telegram"
    called = client.post("/mcp/server/call", json={"tool": listed.json()["tools"][0]["name"], "arguments": {}}, headers={"Authorization": "Bearer a"})
    assert called.status_code == 202
    assert called.json()["execution_id"] == "exec-1"
    assert client.get("/mcp/server/tools", headers={"Authorization": "Bearer b"}).json()["tools"] == []
    assert client.post("/mcp/server/call", json={"tool": "katalir_workflow__daily-telegram", "arguments": {}}, headers={"Authorization": "Bearer b"}).status_code == 404
    unconfirmed = client.post("/mcp/install", json={"mcp_id": "memory", "config": {}}, headers={"Authorization": "Bearer a"})
    assert unconfirmed.status_code == 409
    metadata = client.post("/mcp/install", json={"mcp_id": "@toolsdk.ai/not-validated", "config": {}, "confirmed": True}, headers={"Authorization": "Bearer a"})
    assert metadata.status_code == 422


def test_manifest_validator_rejects_metadata_only():
    import mcp_registry
    assert mcp_registry.validate_executable_manifest({"id": "x", "install_config": {"transport": "metadata-only", "package": "x"}})["status"] == "rejected"
    assert mcp_registry.validate_executable_manifest({"id": "x", "install_config": {"transport": "stdio", "package": "x"}})["status"] == "valid"


