"""test_workflow_ops_api.py — uji endpoint `POST /workflows/{id}/ops`.

Menutup rantai: operasi -> validasi -> tersimpan (atau 422 tanpa perubahan).
Memakai transport ASGI in-process (tanpa server, tanpa Supabase).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402
import database as db  # noqa: E402
import security  # noqa: E402

FLOW = {
    "nodes": [
        {"id": "t", "type": "trigger", "position": {},
         "data": {"kind": "trigger", "label": "Manual", "config": {}}},
        {"id": "a", "type": "agent", "position": {},
         "data": {"kind": "agent", "label": "Agent", "config": {}}},
    ],
    "edges": [{"source": "t", "target": "a"}],
}


def _setup(monkeypatch, uid: str = "u-ops-api") -> str:
    monkeypatch.setattr(db, "is_configured", lambda: False)
    monkeypatch.setattr(
        security, "get_current_user",
        lambda authorization=None: {"id": uid, "email": f"{uid}@example.com"})
    db._LWORKFLOW.clear()
    return db.create_workflow(uid, "Ops WF", "", FLOW)["id"]


async def _post(wid: str, payload: dict):
    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver") as c:
        return await c.post(f"/workflows/{wid}/ops", json=payload)


# 21. jalur bahagia: operasi diterapkan + tersimpan
def test_21_api_ops_applies_and_persists(monkeypatch):
    wid = _setup(monkeypatch)
    r = asyncio.run(_post(wid, {
        "intent": "tambah node code",
        "operations": [
            {"type": "addNode",
             "node": {"id": "c", "data": {"kind": "code", "label": "Code"}}},
            {"type": "addConnection", "source": "a", "target": "c"},
        ],
    }))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["applied"] == 2, body
    saved = db.get_workflow(wid, "u-ops-api")
    ids = [n["id"] for n in saved["flow_data"]["nodes"]]
    assert ids == ["t", "a", "c"], ids
    assert {"source": "a", "target": "c"} in saved["flow_data"]["edges"]


# 22. operasi buruk -> 422 DAN tidak ada perubahan tersimpan
def test_22_api_ops_rejects_and_does_not_persist(monkeypatch):
    wid = _setup(monkeypatch)
    r = asyncio.run(_post(wid, {
        "operations": [{"type": "addConnection",
                        "source": "a", "target": "ghost"}],
    }))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "errors" in detail and any("ghost" in e for e in detail["errors"])
    saved = db.get_workflow(wid, "u-ops-api")
    assert [n["id"] for n in saved["flow_data"]["nodes"]] == ["t", "a"]
    assert saved["flow_data"]["edges"] == [{"source": "t", "target": "a"}]


# 23. dry_run -> pratinjau, TIDAK menulis
def test_23_api_ops_dry_run_preview(monkeypatch):
    wid = _setup(monkeypatch)
    r = asyncio.run(_post(wid, {
        "dry_run": True,
        "operations": [{"type": "removeNode", "id": "a"}],
    }))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "preview" and body["diff"]["nodes_removed"] == ["a"]
    saved = db.get_workflow(wid, "u-ops-api")
    assert [n["id"] for n in saved["flow_data"]["nodes"]] == ["t", "a"], \
        "dry_run tidak boleh menyimpan"


# 24. daftar kosong -> 400
def test_24_api_ops_empty_operations_400(monkeypatch):
    wid = _setup(monkeypatch)
    r = asyncio.run(_post(wid, {"operations": []}))
    assert r.status_code == 400, r.text


# 25. bukan pemilik -> 403 (workflow milik user lain)
def test_25_api_ops_owner_scoped(monkeypatch):
    wid = _setup(monkeypatch, uid="u-owner")
    monkeypatch.setattr(
        security, "get_current_user",
        lambda authorization=None: {"id": "u-intruder", "email": "i@x.com"})
    r = asyncio.run(_post(wid, {
        "operations": [{"type": "removeNode", "id": "a"}]}))
    assert r.status_code == 403, r.text
