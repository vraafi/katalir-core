"""test_workflow_lifecycle.py — 8 interaksi lifecycle workflow (FASE B).

Mengunci bug yang benar-benar terjadi di produksi (2026-09-21):
  * POST /workflows SELALU INSERT -> setiap "Simpan Alur" menumpuk baris baru
    (bukti nyata: 8 baris bernama sama "Draft Workflow", 6x "L3 auto-run probe");
  * tidak ada cara menghapus / mengganti nama workflow dari aplikasi;
  * GET /workflows mengirim `flow_data` SEMUA workflow (payload besar).

Semua tes di jalur MEMORI (`is_configured` dipaksa False) sehingga tidak
menyentuh Supabase maupun jaringan.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402

A = "user-a-uuid"
B = "user-b-uuid"


@pytest.fixture(autouse=True)
def memory_db(monkeypatch):
    monkeypatch.setattr(db, "is_configured", lambda: False)
    db._LWORKFLOW.clear()
    yield
    db._LWORKFLOW.clear()


def _flow(n=2, tag="x"):
    return {"nodes": [{"id": "%s-%d" % (tag, i)} for i in range(n)], "edges": []}


# 1. CREATE -> tersimpan
def test_1_create_menyimpan_workflow():
    row = db.create_workflow(A, "Pertama", "desc", _flow(3))
    assert row["id"] and row["name"] == "Pertama"
    assert len(db.list_workflows(A)) == 1


# 2. LIST -> metadata saja, urut terbaru, tidak ada flow_data
def test_2_list_metadata_tanpa_flow_data():
    for i in range(3):
        db.create_workflow(A, "WF-%d" % i, "", _flow(i + 1))
    rows = db.list_workflows(A)
    assert len(rows) == 3
    for r in rows:
        assert "flow_data" not in r, "list masih membawa flow_data (payload besar)"
    assert {r["name"] for r in rows} == {"WF-0", "WF-1", "WF-2"}


# 3. SAVE ULANG (update in place) -> TIDAK menambah baris
def test_3_update_tidak_menambah_baris():
    row = db.create_workflow(A, "Draft Workflow", "", _flow(1))
    wid = row["id"]
    before = len(db.list_workflows(A))
    again = db.update_workflow(wid, A, name="Draft Workflow", flow_data=_flow(5))
    assert again and again["id"] == wid
    assert len(db.list_workflows(A)) == before, "update malah membuat baris baru"
    assert db.count_nodes(db.get_workflow(wid, A)["flow_data"]) == 5


# 4. GET detail -> flow_data lengkap
def test_4_detail_membawa_flow_data():
    row = db.create_workflow(A, "Detail", "", _flow(4))
    got = db.get_workflow(row["id"], A)
    assert got and isinstance(got["flow_data"], dict)
    assert db.count_nodes(got["flow_data"]) == 4


# 5. RENAME
def test_5_rename_mengubah_nama():
    row = db.create_workflow(A, "Nama Lama", "", _flow(1))
    upd = db.update_workflow(row["id"], A, name="Nama Baru")
    assert upd["name"] == "Nama Baru"
    assert db.get_workflow(row["id"], A)["name"] == "Nama Baru"


# 6. DELETE
def test_6_delete_menghapus_dari_list():
    row = db.create_workflow(A, "Hapus Aku", "", _flow(1))
    keep = db.create_workflow(A, "Tetap", "", _flow(1))
    assert db.delete_workflow(row["id"], A) is True
    names = [r["name"] for r in db.list_workflows(A)]
    assert names == ["Tetap"]
    assert db.get_workflow(keep["id"], A) is not None


# 7. OWNER SCOPE -> user lain tidak bisa baca/ubah/hapus
def test_7_owner_scope_menolak_user_lain():
    row = db.create_workflow(A, "Milik A", "", _flow(1))
    wid = row["id"]
    assert db.get_workflow(wid, B) is None
    assert db.update_workflow(wid, B, name="Dibajak") is None
    assert db.delete_workflow(wid, B) is False
    # dan data milik A tidak berubah
    assert db.get_workflow(wid, A)["name"] == "Milik A"
    assert db.get_workflow_owner(wid) == A  # penolakan tidak menghapus kepemilikan


# 8. RESTORE setelah "reload" (list ulang) tetap konsisten
def test_8_list_stabil_setelah_operasi():
    a = db.create_workflow(A, "Satu", "", _flow(2))
    db.create_workflow(A, "Dua", "", _flow(2))
    db.update_workflow(a["id"], A, flow_data=_flow(7))
    db.delete_workflow(a["id"], A)
    rows = db.list_workflows(A)
    assert [r["name"] for r in rows] == ["Dua"]
    assert len(db.list_workflows(B)) == 0
