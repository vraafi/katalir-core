# tests/test_collab.py — Fitur #10 hard test (12 skenario, Okt 2026)
# Deterministik, in-process: tanpa WebSocket nyata (transport disimulasikan).
from __future__ import annotations

import threading
import time

import pytest

import collab


def _set(client, seq, node, field, value, ts):
    return collab.Op(client, seq, "set", node, field, value, ts=ts)


# 1. 2 user edit bersamaan -> sinkron
def test_01_two_users_sync():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    r.join("alice"); r.join("bob")
    r.submit(_set("alice", 1, "n1", "x", 10, ts=100.0))
    r.submit(_set("bob", 1, "n1", "y", 20, ts=101.0))
    snap = r.doc.snapshot()
    node = [n for n in snap["nodes"] if n["id"] == "n1"][0]
    assert node["x"] == 10 and node["y"] == 20


# 2. 5 user edit -> semua sinkron
def test_02_five_users():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    for i in range(5):
        r.join(f"u{i}")
        r.submit(_set(f"u{i}", 1, f"n{i}", "v", i, ts=100.0 + i))
    snap = r.doc.snapshot()
    assert len(snap["nodes"]) == 5
    assert {n["id"] for n in snap["nodes"]} == {f"n{i}" for i in range(5)}


# 3. Conflict resolution (LWW, independen urutan)
def test_03_conflict_lww():
    ops = [_set("alice", 1, "n1", "x", "A", ts=100.0),
           _set("bob", 1, "n1", "x", "B", ts=200.0)]
    d1 = collab.CollabDoc()
    d1.apply_many(ops)                       # urutan asli
    d2 = collab.CollabDoc()
    d2.apply_many(list(reversed(ops)))       # urutan terbalik
    assert d1.node("n1")["x"] == "B"         # ts terbesar menang
    assert d2.node("n1")["x"] == "B"         # hasil KONVERGEN
    # tie-break by client id
    tie = [_set("aaa", 1, "n2", "x", "1", ts=100.0),
           _set("zzz", 1, "n2", "x", "2", ts=100.0)]
    d3 = collab.CollabDoc(); d3.apply_many(tie)
    assert d3.node("n2")["x"] == "2"


# 4. Cursor presence
def test_04_cursor_presence():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    r.set_presence("alice", cursor={"x": 10, "y": 20}, name="Alice")
    r.set_presence("bob", cursor={"x": 30, "y": 40}, name="Bob")
    assert len(r.presence()) == 2
    cur = r.cursors()
    assert cur["alice"] == {"x": 10, "y": 20}
    assert cur["bob"]["x"] == 30
    r.leave("bob")
    assert "bob" not in r.cursors()


# 5. Komentar + reply + mention
def test_05_comments():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    c1 = r.comment("alice", "n1", "Tolong cek @bob dan @carol")
    assert set(c1["mentions"]) == {"bob", "carol"}
    c2 = r.comment("bob", "n1", "sudah dicek", parent=c1["id"])
    assert c2["parent"] == c1["id"]
    assert len(r.comments(target="n1")) == 2


# 6. Undo/redo per user
def test_06_undo_redo():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    r.submit(_set("alice", 1, "n1", "x", 10, ts=100.0))
    assert r.doc.node("n1")["x"] == 10
    assert r.undo("alice") is True
    assert r.doc.node("n1")["x"] is None      # dikosongkan
    assert r.redo("alice") is True
    assert r.doc.node("n1")["x"] == 10
    # undo user lain tidak memengaruhi (tumpukan per-user)
    r.submit(_set("bob", 1, "n2", "y", 5, ts=101.0))
    assert r.undo("alice") is True            # alice masih punya 1 op
    assert r.doc.node("n2")["y"] == 5         # n2 tidak tersentuh


# 7. Offline edit -> sync saat online
def test_07_offline_merge():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    r.submit(_set("alice", 1, "n1", "x", 1, ts=100.0))
    # bob offline: buat 3 op lokal
    offline = [_set("bob", 1, "n2", "a", 1, ts=101.0),
               _set("bob", 2, "n2", "b", 2, ts=102.0),
               _set("bob", 3, "n3", "c", 3, ts=103.0)]
    hasil = srv.merge_offline("wf-1", offline)
    assert hasil["merged"] == 3
    ids = {n["id"] for n in hasil["snapshot"]["nodes"]}
    assert {"n1", "n2", "n3"} <= ids
    # merge ulang (duplikat) -> tidak ada perubahan
    assert srv.merge_offline("wf-1", offline)["merged"] == 0


# 8. Performance: 10 user concurrent
def test_08_concurrent_10_users():
    srv = collab.CollabServer()
    r = srv.room("wf-1")

    def kerja(u):
        for i in range(50):
            r.submit(_set(f"u{u}", i + 1, f"n{u}", "v", i, ts=100.0 + i))

    ts = [threading.Thread(target=kerja, args=(u,)) for u in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    snap = r.doc.snapshot()
    assert len(snap["nodes"]) == 10
    for u in range(10):
        assert snap["nodes"][u]["v"] == 49     # op terakhir menang


# 9. Latency < 100ms
def test_09_latency():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    t0 = time.perf_counter()
    for i in range(100):
        srv.submit("wf-1", _set("alice", i + 1, f"n{i}", "x", i, ts=100.0 + i))
    dt = (time.perf_counter() - t0) / 100 * 1000
    assert dt < 100, f"latensi/op terlalu tinggi: {dt:.3f}ms"


# 10. WebSocket reconnect (state bertahan)
def test_10_reconnect():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    r.join("alice")
    r.submit(_set("alice", 1, "n1", "x", 42, ts=100.0))
    r.leave("alice")                       # koneksi putus
    assert r.doc.node("n1")["x"] == 42     # state tetap ada
    r.join("alice")                        # sambung ulang
    # kirim op baru setelah reconnect
    r.submit(_set("alice", 2, "n1", "y", 7, ts=101.0))
    assert r.doc.node("n1")["x"] == 42 and r.doc.node("n1")["y"] == 7


# 11. Memory leak check (presence & op log terkendali)
def test_11_no_memory_leak():
    srv = collab.CollabServer()
    r = srv.room("wf-1")
    for i in range(200):
        r.join("alice"); r.set_presence("alice", {"x": i, "y": i})
        r.leave("alice")
    assert len(r.presence()) == 0          # tidak menumpuk
    assert len(r._members) == 0
    # idempotensi: op duplikat tidak menumbuhkan state
    op = _set("alice", 1, "n1", "x", 1, ts=100.0)
    for _ in range(1000):
        r.submit(op)
    assert len(r.doc.snapshot()["nodes"]) == 1


# 12. Security: room access control
def test_12_access_control():
    srv = collab.CollabServer()
    r = srv.room("private", allowed=["alice", "bob"])
    r.join("alice")
    with pytest.raises(collab.AccessDenied):
        r.join("mallory")
    with pytest.raises(collab.AccessDenied):
        r.submit(_set("mallory", 1, "n1", "x", 1, ts=100.0))
    with pytest.raises(collab.AccessDenied):
        r.comment("mallory", "n1", "hack")
    # room terbuka (tanpa daftar) menerima siapa pun
    r2 = srv.room("public")
    r2.join("siapa pun")
