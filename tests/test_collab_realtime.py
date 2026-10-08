# tests/test_collab_realtime.py — Fitur #10 hard test (regresi, Okt 2026)
# Deterministik, tanpa jaringan: menguji logika server/klien CRDT secara lokal.
from __future__ import annotations

import asyncio
import inspect
import os

import pytest
import pycrdt as y

import collab_realtime as cr


# 1. Nama room: normalisasi + tolak path traversal
def test_room_from_path_and_validation():
    assert cr.room_from_path("/collab/ws/tim-alpha") == "tim-alpha"
    assert cr.room_from_path("/tim") == "tim"
    assert cr.valid_room("tim-alpha") is True
    assert cr.valid_room("a.b_c:d") is True
    assert cr.valid_room("a/b") is False
    assert cr.valid_room("../etc") is False
    assert cr.valid_room("") is False
    assert cr.valid_room("x" * 65) is False


# 2. Path penyimpanan disanitasi (tak bisa keluar direktori store)
def test_store_path_sanitized(tmp_path):
    srv = cr.PersistentWebsocketServer(store_dir=str(tmp_path))
    p = srv.store_path("../../evil")
    assert os.path.dirname(p) == str(tmp_path)
    assert ".." not in os.path.basename(p)


# 3. REGRESI: `update_node` harus benar-benar mengubah CRDT
#    (bug nyata: Map.get() pycrdt mengembalikan SALINAN -> tulisan hilang)
def test_update_node_actually_changes_crdt():
    c = cr.CollabClient("ws://x/ws", "tok", "A", "r")
    c.add_node("n", label="dasar", x=1)
    c.update_node("n", label="diubah")
    assert dict(c.nodes["n"])["label"] == "diubah"
    # perubahan tercermin di update CRDT (bukan hanya objek lokal)
    other = y.Doc()
    other.apply_update(c.doc.get_update())
    assert dict(other.get("nodes", type=y.Map)["n"])["label"] == "diubah"


# 4. Hapus node + snapshot
def test_remove_node_and_snapshot():
    c = cr.CollabClient("ws://x/ws", "tok", "A", "r")
    c.add_node("a", label="A")
    c.add_node("b", label="B")
    assert set(c.snapshot()["nodes"]) == {"a", "b"}
    c.remove_node("a")
    assert set(c.snapshot()["nodes"]) == {"b"}


# 5. Komentar masuk ke array CRDT
def test_comments_are_crdt():
    c = cr.CollabClient("ws://x/ws", "tok", "Andi", "r")
    c.add_comment("halo", target="n1")
    assert c.snapshot()["comments"][0]["text"] == "halo"
    other = y.Doc()
    other.apply_update(c.doc.get_update())
    assert [dict(x) for x in other.get("comments", type=y.Array)][0]["text"] == "halo"


# 6. REGRESI: persistensi CRDT dipulihkan saat room dibuka lagi
#    (bug nyata: YRoom hanya MENULIS ke ystore; pemulihan harus eksplisit)
def test_persistence_restored(tmp_path):
    async def run():
        srv1 = cr.PersistentWebsocketServer(store_dir=str(tmp_path),
                                            auto_clean_rooms=False)
        async with srv1:
            room = await srv1.get_room("r1")
            room.ydoc.get("nodes", type=y.Map)["a"] = {"label": "tahan"}
            await asyncio.sleep(0.4)     # beri waktu ystore menulis
        srv2 = cr.PersistentWebsocketServer(store_dir=str(tmp_path),
                                            auto_clean_rooms=False)
        async with srv2:
            room2 = await srv2.get_room("r1")
            nodes = {k: dict(v) for k, v in
                     room2.ydoc.get("nodes", type=y.Map).items()}
        return nodes

    nodes = asyncio.run(run())
    assert nodes == {"a": {"label": "tahan"}}, f"state tidak dipulihkan: {nodes}"


# 7. REGRESI: `wait_for` HARUS async (versi sinkron memblokir event loop)
def test_wait_for_is_async():
    assert inspect.iscoroutinefunction(cr.CollabClient.wait_for)


# 8. `room_view` menemukan room baik dengan nama bersih maupun ber-prefix path
def test_room_view_lookup():
    class FakeServer:
        def __init__(self):
            self.rooms = {}

    srv = FakeServer()
    room = cr.YRoom(ready=True)
    room.ydoc.get("nodes", type=y.Map)["n1"] = {"label": "X"}
    srv.rooms["/collab/ws/tim"] = room

    v = cr.room_view(srv, "tim")
    assert v["exists"] is True and v["room"] == "tim"
    assert dict(v["nodes"]["n1"]) == {"label": "X"}
    # nama tak dikenal -> exists False (tidak melempar)
    assert cr.room_view(srv, "lain")["exists"] is False
    # list_rooms menormalkan nama
    assert [r["room"] for r in cr.list_rooms(srv)] == ["tim"]
