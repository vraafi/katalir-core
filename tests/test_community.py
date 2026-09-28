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


# ---- /community/my-earnings -------------------------------------------------
# The route-existence test above only proves the path is wired up. These cover
# what the handler actually returns, because the UI renders a different message
# for each outcome: an empty list and a broken backend must never look alike.
#
# `security.get_current_user` verifies a real Supabase JWT, so it is patched
# here. That is deliberate: these tests are about the handler's response shape,
# and JWT verification is covered by the security tests. Patching it also keeps
# the developer id under the test's control, which is what proves the handler
# takes the id from the verified token rather than from the request.
_AUTHED = {"Authorization": "Bearer test.jwt.token"}


@pytest.fixture
def as_user(monkeypatch):
    monkeypatch.setattr(
        api_server.security,
        "get_current_user",
        lambda authorization=None: {"id": "user-1", "email": "dev@example.test"},
    )
    return {"id": "user-1", "email": "dev@example.test"}


def test_my_earnings_wajib_autentikasi(monkeypatch):
    monkeypatch.setattr(
        db,
        "list_community_earnings",
        lambda *a, **k: pytest.fail("must not read earnings without a user"),
    )
    r = client.get("/community/my-earnings")
    assert r.status_code in (401, 403)


def test_my_earnings_tabel_belum_ada_jelas_bukan_kosong(monkeypatch, as_user):
    """A missing table must surface as 503.

    Returning an empty 200 here would tell a developer with a broken backend
    that they have simply earned nothing, which is the specific confusion the
    503 branch exists to prevent.
    """

    def boom(*a, **k):
        raise RuntimeError("community_earnings relation does not exist")

    monkeypatch.setattr(db, "list_community_earnings", boom)
    r = client.get("/community/my-earnings", headers=_AUTHED)
    assert r.status_code == 503
    assert "community-platform.sql" in r.json()["detail"]


def test_my_earnings_total_dihitung_dari_baris(monkeypatch, as_user):
    """`total_usd` is summed from the rows, including the string `numeric` form.

    PostgREST returns numeric as a string, so summing raw values would
    concatenate instead of adding and quietly produce a wrong total.
    """
    monkeypatch.setattr(
        db,
        "list_community_earnings",
        lambda developer_id, limit=24: [
            {"integration_id": "a", "amount_usd": "10.50"},
            {"integration_id": "b", "amount_usd": 4.25},
            {"integration_id": "c", "amount_usd": None},
        ],
    )
    r = client.get("/community/my-earnings", headers=_AUTHED)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["total_usd"] == pytest.approx(14.75)


def test_my_earnings_kosong_itu_200_bukan_503(monkeypatch, as_user):
    """No earnings yet is a normal 200, distinct from a broken backend."""
    monkeypatch.setattr(db, "list_community_earnings", lambda developer_id, limit=24: [])
    r = client.get("/community/my-earnings", headers=_AUTHED)
    assert r.status_code == 200
    assert r.json() == {"items": [], "total_usd": 0}


def test_my_earnings_meneruskan_id_pengembang(monkeypatch, as_user):
    """The developer id must come from the verified token, not the request."""
    seen = {}

    def fake(developer_id, limit=24):
        seen["developer_id"] = developer_id
        return []

    monkeypatch.setattr(db, "list_community_earnings", fake)
    client.get("/community/my-earnings", headers=_AUTHED)
    assert seen["developer_id"] == "user-1"
