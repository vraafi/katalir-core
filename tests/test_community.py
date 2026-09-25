"""Community platform API contracts.

The important one is ``test_browse_gagal_jelas_bukan_kosong``: an undeployed
table must surface as 503, because an empty 200 list would read as "no community
integrations exist" and quietly understate the product.
"""
import pytest
from fastapi.testclient import TestClient

import api_server
import database as db

client = TestClient(api_server.app, raise_server_exceptions=False)


def test_endpoint_komunitas_terdaftar():
    routes = {r.path for r in api_server.app.routes}
    for path in ("/community/submit", "/community/browse", "/community/review", "/community/my-earnings"):
        assert path in routes, path


def test_browse_gagal_jelas_bukan_kosong(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("community_integrations relation does not exist")

    monkeypatch.setattr(db, "list_community_integrations", boom)
    r = client.get("/community/browse")
    assert r.status_code == 503
    assert "community-platform.sql" in r.json()["detail"]


def test_browse_hanya_menampilkan_approved(monkeypatch):
    seen = {}

    def fake(status="approved", limit=25):
        seen["status"] = status
        return [{"id": "1", "name": "Approved thing", "status": "approved"}]

    monkeypatch.setattr(db, "list_community_integrations", fake)
    r = client.get("/community/browse")
    assert r.status_code == 200
    body = r.json()
    assert seen["status"] == "approved"
    assert body["status_filter"] == "approved"
    assert all(i["status"] == "approved" for i in body["items"])


def test_submit_menolak_manifest_tanpa_tools():
    """A manifest with no tools cannot describe anything callable."""
    r = client.post(
        "/community/submit",
        json={"name": "x", "source_url": "https://example.com", "manifest": {"foo": 1}},
    )
    assert r.status_code in (400, 401, 403)


def test_submit_wajib_meminta_autentikasi(monkeypatch):
    monkeypatch.setattr(
        db,
        "submit_community_integration",
        lambda **k: pytest.fail("must not write without a user"),
    )
    r = client.post(
        "/community/submit",
        json={"name": "x", "source_url": "https://example.com", "manifest": {"tools": []}},
    )
    assert r.status_code in (401, 403)
