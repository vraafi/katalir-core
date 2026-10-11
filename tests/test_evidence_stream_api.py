"""test_evidence_stream_api.py — uji endpoint `POST /chat/stream` + `/evidence`.

Transport ASGI in-process (tanpa server, tanpa Supabase). Auth dan `chat`
di-monkeypatch agar fokus pada lapisan streaming/ledger.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402
import chat_stream as cs  # noqa: E402
import security  # noqa: E402


def _auth(monkeypatch, uid: str = "u-stream"):
    monkeypatch.setattr(
        security, "get_current_user",
        lambda authorization=None: {"id": uid, "email": f"{uid}@example.com"})


async def _req(method: str, path: str, **kw):
    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        return await getattr(c, method)(path, **kw)


# 1. /chat/stream mengirim frame chunk + done ------------------------------
def test_stream_endpoint_frames(monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(api_server, "chat",
                        lambda req, authorization=None: {
                            "status": "success", "reply": "Halo dunia", "session_id": "s1"})
    r = asyncio.run(_req("post", "/chat/stream", json={"prompt": "hi"}))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [cs.parse_frame(f) for f in r.text.split("\n\n") if f.strip()]
    events = [f["event"] for f in frames]
    assert "chunk" in events and events[-1] == "done"
    text = "".join(f["data"]["data"] for f in frames if f["event"] == "chunk")
    assert text == "Halo dunia"


# 2. /chat/stream tanpa auth -> 401 ---------------------------------------
def test_stream_endpoint_requires_auth(monkeypatch):
    def boom(authorization=None):
        raise HTTPException(401, "Token wajib.")
    monkeypatch.setattr(security, "get_current_user", boom)
    r = asyncio.run(_req("post", "/chat/stream", json={"prompt": "hi"}))
    assert r.status_code == 401, r.text


# 3. /evidence append lalu verify -> valid ---------------------------------
def test_evidence_append_and_verify(monkeypatch):
    _auth(monkeypatch)
    import evidence_ledger as el
    el.set_ledger(el.EvidenceLedger(key=b"api-test-key"))
    r = asyncio.run(_req("post", "/evidence", json={"content": {"test": "x", "ok": True}}))
    assert r.status_code == 200, r.text
    entry_id = r.json()["entry"]["id"]
    v = asyncio.run(_req("get", f"/evidence/{entry_id}/verify"))
    assert v.status_code == 200, v.text
    body = v.json()
    assert body["found"] is True and body["valid"] is True and body["chain_ok"] is True


# 4. /evidence/{id}/verify untuk id tak dikenal -> found False --------------
def test_evidence_verify_unknown(monkeypatch):
    _auth(monkeypatch)
    v = asyncio.run(_req("get", "/evidence/00000000-0000-0000-0000-000000000000/verify"))
    assert v.status_code == 200, v.text
    assert v.json()["found"] is False


# 5. /evidence butuh auth --------------------------------------------------
def test_evidence_requires_auth(monkeypatch):
    def boom(authorization=None):
        raise HTTPException(401, "Token wajib.")
    monkeypatch.setattr(security, "get_current_user", boom)
    r = asyncio.run(_req("post", "/evidence", json={"content": "x"}))
    assert r.status_code == 401, r.text
