"""test_workflow_api.py — kontrak HTTP lifecycle workflow (FASE B).

Menguji lewat FastAPI TestClient pada jalur MEMORI (tanpa Supabase/jaringan):
  1. create -> 201
  2. list -> metadata saja (TANPA flow_data)
  3. detail -> flow_data lengkap
  4. save ulang dengan `id` -> UPDATE (updated=true), jumlah baris TIDAK naik
  5. PATCH rename
  6. DELETE
  7. owner-scope: user lain -> 403 (PATCH/DELETE) dan 404 (detail)
  8. validasi: id tak ada -> 404, body kosong -> 400
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_server  # noqa: E402
import database as db  # noqa: E402

USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
CUR = {"id": USER_A}


@pytest.fixture(autouse=True)
def memory_and_auth(monkeypatch):
    monkeypatch.setattr(db, "is_configured", lambda: False)
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda authorization=None: {"id": CUR["id"], "email": "t@example.com"})
    db._LWORKFLOW.clear()
    CUR["id"] = USER_A
    yield
    db._LWORKFLOW.clear()
    CUR["id"] = USER_A


@pytest.fixture
def client():
    return TestClient(api_server.app)


def _flow(n=2):
    return {"nodes": [{"id": "n%d" % i} for i in range(n)], "edges": []}


def test_1_create_dan_list_metadata(client):
    r = client.post("/workflows", json={"name": "A1", "description": "", "flow_data": _flow(3)})
    assert r.status_code == 201, r.text
    wid = r.json()["workflow"]["id"]
    assert r.json()["updated"] is False

    lst = client.get("/workflows").json()["workflows"]
    assert len(lst) == 1 and lst[0]["id"] == wid
    assert "flow_data" not in lst[0], "list masih mengirim flow_data"


def test_2_detail_membawa_flow_data(client):
    wid = client.post("/workflows", json={"name": "A2", "flow_data": _flow(4)}).json()["workflow"]["id"]
    d = client.get("/workflows/%s" % wid)
    assert d.status_code == 200
    assert len(d.json()["workflow"]["flow_data"]["nodes"]) == 4


def test_3_save_ulang_dengan_id_tidak_menambah_baris(client):
    first = client.post("/workflows", json={"name": "Draft Workflow", "flow_data": _flow(1)})
    wid = first.json()["workflow"]["id"]

    second = client.post("/workflows", json={"id": wid, "name": "Draft Workflow", "flow_data": _flow(5)})
    assert second.status_code == 201, second.text
    assert second.json()["updated"] is True
    assert second.json()["workflow"]["id"] == wid

    lst = client.get("/workflows").json()["workflows"]
    assert len(lst) == 1, "save ulang membuat baris baru (bug lama)"
    assert len(client.get("/workflows/%s" % wid).json()["workflow"]["flow_data"]["nodes"]) == 5


def test_4_rename_via_patch(client):
    wid = client.post("/workflows", json={"name": "Nama Lama", "flow_data": _flow(1)}).json()["workflow"]["id"]
    r = client.patch("/workflows/%s" % wid, json={"name": "Nama Baru"})
    assert r.status_code == 200, r.text
    assert client.get("/workflows/%s" % wid).json()["workflow"]["name"] == "Nama Baru"
    assert client.get("/workflows").json()["workflows"][0]["name"] == "Nama Baru"


def test_5_delete_menghapus_dari_list(client):
    wid = client.post("/workflows", json={"name": "Hapus", "flow_data": _flow(1)}).json()["workflow"]["id"]
    r = client.delete("/workflows/%s" % wid)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert client.get("/workflows").json()["workflows"] == []
    assert client.get("/workflows/%s" % wid).status_code == 404


def test_6_owner_scope_user_lain_ditolak(client):
    wid = client.post("/workflows", json={"name": "Milik A", "flow_data": _flow(1)}).json()["workflow"]["id"]

    CUR["id"] = USER_B  # sekarang bertindak sebagai user B
    assert client.get("/workflows").json()["workflows"] == []
    assert client.get("/workflows/%s" % wid).status_code == 404
    assert client.patch("/workflows/%s" % wid, json={"name": "Bajak"}).status_code == 403
    assert client.delete("/workflows/%s" % wid).status_code == 403

    CUR["id"] = USER_A  # data A tidak berubah
    assert client.get("/workflows/%s" % wid).json()["workflow"]["name"] == "Milik A"


def test_7_id_tidak_ada_404_dan_body_kosong_400(client):
    assert client.get("/workflows/tidak-ada").status_code == 404
    assert client.delete("/workflows/tidak-ada").status_code == 404
    wid = client.post("/workflows", json={"name": "X", "flow_data": _flow(1)}).json()["workflow"]["id"]
    assert client.patch("/workflows/%s" % wid, json={}).status_code == 400
    assert client.patch("/workflows/%s" % wid, json={"name": "   "}).status_code == 400
    upd = client.post("/workflows", json={"id": "tidak-ada", "name": "X", "flow_data": _flow(1)})
    assert upd.status_code == 404
