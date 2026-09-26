"""Auto-config: entri katalog metadata-only tidak boleh jadi server runtime."""
import api_server
import mcp_autoconfig as ac
import pytest
from fastapi.testclient import TestClient

client = TestClient(api_server.app)

USERS = {"Bearer a": {"id": "a"}, "Bearer b": {"id": "b"}}


def _auth(monkeypatch):
    """User nyata + storage in-memory (Supabase dimatikan agar test offline)."""
    monkeypatch.setattr(api_server.db, "is_configured", lambda: False)
    monkeypatch.setattr(api_server.security, "get_current_user", lambda a: USERS.get(a, {"id": "unknown"}))


def test_metadata_only_ditolak():
    with pytest.raises(ac.AutoConfigError) as e:
        ac.plan("@toolsdk.ai/aws-ses-mcp", {})
    assert "metadata-only" in str(e.value)


def test_resolve_runtime_menoppelkan_server_prefix():
    assert ac.resolve_runtime("@modelcontextprotocol/server-time") == "time"
    assert ac.resolve_runtime("everything") == "everything"
    assert ac.resolve_runtime("@kazuph/mcp-screenshot") is None


def test_plan_melaporkan_konfigurasi_kurang():
    p = ac.plan("@modelcontextprotocol/server-filesystem", {"roots": "/tmp"})
    assert p.executable and p.missing_config == []
    q = ac.plan("@modelcontextprotocol/server-filesystem", {})
    assert q.missing_config == ["roots"]
    assert any("belum lengkap" in w for w in q.warnings)


def test_secret_tidak_ikut_ke_plan():
    p = ac.plan("time", {"timezone": "Asia/Jakarta", "api_key": "sk-live-secret"})
    assert "sk-live-secret" not in str(p.to_dict())


def test_preview_ditolak_metadata_only(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    _auth(monkeypatch)
    r = client.post("/mcp/auto-config/preview", json={"mcp_id": "@kazuph/mcp-screenshot"}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 400


def test_preview_allowlist_berhasil(monkeypatch):
    _auth(monkeypatch)
    r = client.post("/mcp/auto-config/preview", json={"mcp_id": "time", "config": {"timezone": "Asia/Jakarta"}}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 200
    body = r.json()
    assert body["requires_confirmation"] is True
    assert body["plan"]["runtime"] == "time"


def test_install_tanpa_konfirmasi_ditolak(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    _auth(monkeypatch)
    r = client.post("/mcp/install", json={"mcp_id": "time", "config": {"timezone": "Asia/Jakarta"}}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 409
    assert api_server._MCP_INSTANCES == {}


def test_install_metadata_only_ditolak(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    _auth(monkeypatch)
    r = client.post("/mcp/install", json={"mcp_id": "@kazuph/mcp-screenshot", "confirmed": True}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 422
    assert api_server._MCP_INSTANCES == {}


def test_install_dengan_konfirmasi_menyimpan_instance(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    _auth(monkeypatch)
    r = client.post("/mcp/install", json={"mcp_id": "@modelcontextprotocol/server-time", "config": {"timezone": "Asia/Jakarta"}, "confirmed": True}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 200
    body = r.json()["instance"]
    assert body["runtime"] == "time" and body["transport"] == "stdio" and body["status"] == "active"
    assert len(client.get("/mcp/my-instances", headers={"Authorization": "Bearer a"}).json()["instances"]) == 1


def test_install_konfigurasi_kurang_berstatus_needs_config(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    _auth(monkeypatch)
    r = client.post("/mcp/install", json={"mcp_id": "filesystem", "config": {}, "confirmed": True}, headers={"Authorization": "Bearer a"})
    assert r.status_code == 200
    body = r.json()["instance"]
    assert body["status"] == "needs_config"
    assert body["missing_config"] == ["roots"]


def test_tenant_isolasi_pada_install(monkeypatch):
    api_server._MCP_INSTANCES.clear()
    _auth(monkeypatch)
    client.post("/mcp/install", json={"mcp_id": "time", "config": {"timezone": "UTC"}, "confirmed": True}, headers={"Authorization": "Bearer a"})
    assert client.get("/mcp/my-instances", headers={"Authorization": "Bearer b"}).json()["instances"] == []
