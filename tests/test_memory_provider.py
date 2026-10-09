# tests/test_memory_provider.py — Fitur #12: External Memory Provider
# ======================================================================
# 14 tes. Provider HTTP diuji terhadap MOCK TRANSPORT httpx in-process:
# kode provider benar-benar dieksekusi (request dibentuk, response diurai),
# bukan di-stub. Provider `internal` diuji dengan fake MemoryManager.
# ======================================================================

from __future__ import annotations

import json

import httpx
import pytest

import memory_provider as MP


# ---------------------------------------------------------------------------
# Mock transport: server tiruan in-process
# ---------------------------------------------------------------------------

class FakeServer:
    """Mencatat request dan mengembalikan respons yang dapat dikonfigurasi."""

    def __init__(self, routes: dict | None = None):
        self.calls: list[dict] = []
        self.routes = routes or {}
        self.default_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            try:
                body = json.loads(request.content.decode())
            except Exception:  # noqa: BLE001
                body = request.content.decode(errors="replace")
        path = request.url.path
        self.calls.append({"method": request.method, "path": path,
                           "body": body, "query": dict(request.url.params),
                           "headers": dict(request.headers)})
        for (method, prefix), resp in self.routes.items():
            if request.method == method and path.startswith(prefix):
                if callable(resp):
                    return resp(request)
                status, payload = resp
                return httpx.Response(status, json=payload)
        return httpx.Response(self.default_status, json={"ok": True})

    def transport(self) -> httpx.BaseTransport:
        return httpx.MockTransport(self.handler)


# ---------------------------------------------------------------------------
# Fake internal memory manager (tanpa Supabase)
# ---------------------------------------------------------------------------

class FakeMM:
    store: dict[str, list[dict]] = {}
    calls: list[tuple] = []

    def __init__(self, user_id, agent_id="default"):
        self.user_id, self.agent_id = user_id, agent_id

    def _bucket(self):
        return FakeMM.store.setdefault((self.user_id, self.agent_id), [])

    def remember(self, content, memory_type="semantic", metadata=None,
                 ttl_seconds=None, agent_id=None):
        FakeMM.calls.append(("remember", self.user_id, self.agent_id, content))
        row = {"id": f"m{len(self._bucket())}", "content": content}
        self._bucket().append(row)
        return row

    def recall(self, query, top_k=5, memory_type=None, agent_id=None):
        FakeMM.calls.append(("recall", self.user_id, self.agent_id, query))
        return [dict(r, similarity=1.0) for r in self._bucket() if query in r["content"]
                or query == "*"][:top_k]

    def forget(self, memory_id):
        FakeMM.calls.append(("forget", self.user_id, self.agent_id, memory_id))
        b = self._bucket()
        for r in list(b):
            if r["id"] == memory_id:
                b.remove(r)
                return True
        return False


@pytest.fixture(autouse=True)
def _reset():
    FakeMM.store = {}
    FakeMM.calls = []
    yield


def _internal():
    return MP.InternalProvider(manager_factory=lambda u, a: FakeMM(u, a))


# 1. Internal provider: remember + recall + forget bekerja
def test_internal_roundtrip():
    p = _internal()
    row = p.remember("halo dunia", user_id="u1")
    assert row["id"] and row["provider"] == "internal"
    hits = p.recall("halo", user_id="u1")
    assert len(hits) == 1 and hits[0]["content"] == "halo dunia"
    assert p.forget(row["id"], user_id="u1") is True


# 2. Isolasi multi-tenant: user A tidak melihat memori user B
def test_internal_tenant_isolation():
    p = _internal()
    p.remember("rahasia A", user_id="A")
    p.remember("rahasia B", user_id="B")
    a = p.recall("rahasia", user_id="A")
    b = p.recall("rahasia", user_id="B")
    assert [r["content"] for r in a] == ["rahasia A"]
    assert [r["content"] for r in b] == ["rahasia B"]


# 3. Supermemory: request dibentuk benar (path, containerTags, Bearer)
def test_supermemory_request_shape():
    srv = FakeServer({("POST", "/v3/documents"): (200, {"id": "doc-1"})})
    p = MP.SupermemoryProvider(api_key="sm_test", transport=srv.transport())
    out = p.remember("fakta penting", user_id="u1", agent_id="ag1")
    assert out["id"] == "doc-1"
    call = srv.calls[0]
    assert call["method"] == "POST" and call["path"] == "/v3/documents"
    assert call["headers"]["authorization"] == "Bearer sm_test"
    # Ingest mengirim tag user+agent PLUS tag gabungan untuk search.
    assert call["body"]["containerTags"] == [
        "user:u1", "agent:ag1", "user:u1:agent:ag1"]


# 4. Supermemory: search memakai /v4/search dengan q + SATU containerTag
def test_supermemory_search():
    srv = FakeServer({("POST", "/v4/search"): (
        200, {"results": [{"id": "d1", "content": "pizza", "score": 0.9}]})})
    p = MP.SupermemoryProvider(api_key="sm_x", transport=srv.transport())
    hits = p.search("pizza", user_id="u1", top_k=3)
    assert hits == [{"id": "d1", "content": "pizza", "score": 0.9,
                     "provider": "supermemory"}]
    assert srv.calls[0]["body"]["q"] == "pizza"
    assert srv.calls[0]["body"]["limit"] == 3
    # Regresi: v4/search HANYA menerima satu containerTag (server nyata
    # menolak >1 dengan HTTP 400 "v4 search is single-space").
    body = srv.calls[0]["body"]
    assert "containerTag" in body and isinstance(body["containerTag"], str)
    assert "containerTags" not in body


# 5. Mem0: /memories dengan messages + user_id; ids diurai
def test_mem0_remember_and_parse_ids():
    srv = FakeServer({("POST", "/memories"): (
        200, {"results": [{"id": "mem-9", "memory": "kopi"}]})})
    p = MP.Mem0Provider(api_key="m0_test", transport=srv.transport())
    out = p.remember("suka kopi", user_id="u2", agent_id="ag")
    assert out["id"] == "mem-9"
    body = srv.calls[0]["body"]
    assert body["user_id"] == "u2" and body["agent_id"] == "ag"
    assert body["messages"][0]["content"] == "suka kopi"


# 6. Mem0: search mengurai `memory` -> `content`
def test_mem0_search_normalizes_content():
    srv = FakeServer({("POST", "/search"): (
        200, {"results": [{"id": "x", "memory": "teh manis", "score": 0.4}]})})
    p = MP.Mem0Provider(api_key="k", transport=srv.transport())
    hits = p.recall("teh", user_id="u1")
    assert hits[0]["content"] == "teh manis"


# 7. Zep: sesi deterministik + path benar
def test_zep_session_and_search_path():
    srv = FakeServer({
        ("POST", "/api/v2/sessions"): (200, {"ok": True}),
        ("GET", "/api/v2/sessions"): (200, {"results": [{"uuid": "z1", "fact": "fakta"}]}),
    })
    p = MP.ZepProvider(api_key="z", transport=srv.transport())
    p.remember("catatan", user_id="u9", agent_id="agX")
    assert srv.calls[0]["path"] == "/api/v2/sessions/u9::agX/memory"
    hits = p.recall("catatan", user_id="u9", agent_id="agX")
    assert srv.calls[1]["path"] == "/api/v2/sessions/u9::agX/memory/search"
    assert hits[0]["content"] == "fakta"


# 8. Letta: blok memori + filter query lokal
def test_letta_blocks_and_filter():
    srv = FakeServer({("GET", "/v1/agents"): (
        200, [{"id": "b1", "value": "tinggal di Jakarta"},
             {"id": "b2", "value": "suka Python"}])})
    p = MP.LettaProvider(api_key="l", transport=srv.transport())
    hits = p.recall("jakarta", user_id="u1", agent_id="a1")
    assert len(hits) == 1 and "Jakarta" in hits[0]["content"]


# 9. Routing config: provider eksternal tanpa kunci -> fallback internal
def test_resolve_falls_back_without_key():
    assert MP.resolve_provider(None, manager_factory=lambda u, a: FakeMM(u, a)).name == "internal"
    got = MP.resolve_provider({"provider": "supermemory", "api_key": ""},
                              manager_factory=lambda u, a: FakeMM(u, a))
    assert got.name == "internal"
    got2 = MP.resolve_provider({"provider": "mem0", "enabled": False},
                               manager_factory=lambda u, a: FakeMM(u, a))
    assert got2.name == "internal"


# 10. Routing config: provider eksternal dengan kunci -> dipakai
def test_resolve_uses_external_with_key():
    got = MP.resolve_provider({"provider": "mem0", "api_key": "k",
                               "base_url": "https://api.mem0.ai"},
                              transport=FakeServer().transport(),
                              manager_factory=lambda u, a: FakeMM(u, a))
    assert got.name == "mem0" and got.is_external


# 11. Fallback saat provider eksternal error (500)
def test_service_fallback_on_error():
    srv = FakeServer({("POST", "/memories"): (500, {"error": "boom"})})
    prov = MP.Mem0Provider(api_key="k", transport=srv.transport())
    svc = MP.MemoryService(prov, fallback=_internal(), user_id="u1")
    out = svc.remember("penting")
    assert out["primary_ok"] is False
    assert out["fallback"]["provider"] == "internal"
    # recall harus tetap menemukan salinan internal
    hits = svc.recall("penting")
    assert hits and hits[0]["provider"] == "internal"


# 12. Sinkronisasi eksternal -> internal
def test_sync_external_to_internal():
    srv = FakeServer({("POST", "/v4/search"): (
        200, {"results": [
            {"id": "r1", "content": "alfa"}, {"id": "r2", "content": "beta"}]})})
    prov = MP.SupermemoryProvider(api_key="sm", transport=srv.transport())
    fb = _internal()
    svc = MP.MemoryService(prov, fallback=fb, user_id="u1")
    res = svc.sync(query="*")
    assert res["synced"] == 2
    local = fb.recall("*", user_id="u1")
    assert {r["content"] for r in local} == {"alfa", "beta"}


# 13. Tanpa kunci eksternal: semua operasi tetap jalan lewat internal
def test_no_key_still_works_end_to_end():
    svc = MP.service_for({"provider": "zep"},
                         user_id="u1", manager_factory=lambda u, a: FakeMM(u, a))
    assert svc.provider.name == "internal"
    out = svc.remember("catatan tanpa kunci")
    assert out["primary_ok"] is True
    assert svc.recall("catatan")[0]["content"] == "catatan tanpa kunci"


# 14. Performa: 200 remember internal < 1 s + tidak ada kebocoran tag
def test_performance_and_tags():
    import time
    p = _internal()
    t0 = time.perf_counter()
    for i in range(200):
        p.remember(f"item-{i}", user_id="u1")
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"terlalu lambat: {dt:.3f}s"
    assert MP._scope_tags("u1", "ag") == ["user:u1", "agent:ag"]
