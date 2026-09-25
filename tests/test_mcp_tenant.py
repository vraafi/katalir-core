import api_server
from fastapi.testclient import TestClient

client = TestClient(api_server.app)

def test_tenant_isolation(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    users = {"Bearer a": {"id": "user-a", "email": "a@example.com"}, "Bearer b": {"id": "user-b", "email": "b@example.com"}}
    monkeypatch.setattr(api_server.security, "get_current_user", lambda auth: users[auth])
    r = client.post("/mcp/install", json={"mcp_id": "time", "config": {"tz": "Asia/Jakarta"}}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 200
    assert len(client.get("/mcp/my-instances", headers={"Authorization": "Bearer a"}).json()["instances"]) == 1
    assert client.get("/mcp/my-instances", headers={"Authorization": "Bearer b"}).json()["instances"] == []
    assert client.delete("/mcp/uninstall/time", headers={"Authorization": "Bearer b"}).status_code == 404
    assert client.delete("/mcp/uninstall/time", headers={"Authorization": "Bearer a"}).status_code == 200
    assert client.get("/mcp/my-instances", headers={"Authorization": "Bearer a"}).json()["instances"] == []


