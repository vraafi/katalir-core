"""test_workflow_ops.py — Hard test untuk editor workflow berbasis OPERASI.

Fitur: `workflow_ops.apply_operations` (referensi: n8n-autopilot SKILL.md
Phase 3.2 `n8n_update_partial_workflow`). Brief 11 Okt 2026 mewajibkan
>=10 hard test (batas, error, performa, keamanan) dan 100% lulus.

Setiap test menguji SATU sifat. Tidak ada klaim tanpa assert.
"""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import workflow_ops as wo  # noqa: E402


def _doc():
    """Dokumen xyflow (bentuk `flow_data` yang disimpan Supabase)."""
    return {
        "nodes": [
            {"id": "t", "type": "trigger", "position": {"x": 0, "y": 0},
             "data": {"kind": "trigger", "label": "Manual", "config": {}}},
            {"id": "a", "type": "agent", "position": {"x": 200, "y": 0},
             "data": {"kind": "agent", "label": "Agent",
                      "config": {"prompt": "halo"}}},
        ],
        "edges": [{"source": "t", "target": "a"}],
    }


# ===========================================================================
# 1. JALUR BAHAGIA — tambah node + sambungkan
# ===========================================================================
def test_1_add_node_and_connection_happy_path():
    res = wo.apply_operations(_doc(), [
        {"type": "addNode", "node": {"id": "c", "data": {"kind": "code",
                                                         "label": "Code",
                                                         "config": {}}}},
        {"type": "addConnection", "source": "a", "target": "c"},
    ])
    assert res["ok"] is True, res["errors"]
    assert res["applied"] == 2
    ids = [n["id"] for n in res["flow_data"]["nodes"]]
    assert ids == ["t", "a", "c"], ids
    assert "a->c" in res["diff"]["edges_added"]
    assert "c" in res["diff"]["nodes_added"]


# ===========================================================================
# 2. UPDATE node — merge config, bukan menimpa
# ===========================================================================
def test_2_update_node_merges_config():
    res = wo.apply_operations(_doc(), [
        {"type": "updateNode", "id": "a",
         "updates": {"label": "Agent Baru", "config": {"prompt": "baru"}}},
    ])
    assert res["ok"] is True, res["errors"]
    node = [n for n in res["flow_data"]["nodes"] if n["id"] == "a"][0]
    assert node["data"]["label"] == "Agent Baru"
    assert node["data"]["config"]["prompt"] == "baru"
    assert "a" in res["diff"]["nodes_changed"]


# ===========================================================================
# 3. REMOVE node -> edge yang menggantung ikut dibuang
# ===========================================================================
def test_3_remove_node_cascades_edges():
    res = wo.apply_operations(_doc(), [{"type": "removeNode", "id": "a"}])
    assert res["ok"] is True, res["errors"]
    assert [n["id"] for n in res["flow_data"]["nodes"]] == ["t"]
    assert res["flow_data"]["edges"] == [], res["flow_data"]["edges"]
    assert res["diff"]["edges_removed"] == ["t->a"]


# ===========================================================================
# 4. ATOMIK — satu op gagal => dokumen ASLI kembali utuh
# ===========================================================================
def test_4_atomic_rollback_on_failure():
    doc = _doc()
    before = copy.deepcopy(doc)
    res = wo.apply_operations(doc, [
        {"type": "addNode", "node": {"id": "x", "data": {"kind": "code"}}},
        {"type": "addConnection", "source": "x", "target": "GHOST"},  # gagal
    ])
    assert res["ok"] is False
    assert res["applied"] == 0
    assert res["flow_data"] == before, "dokumen harus kembali utuh (atomik)"
    assert any("GHOST" in e for e in res["errors"])


# ===========================================================================
# 5 + 6. EDGE KE NODE ASING DITOLAK (halusinasi id model)
# ===========================================================================
def test_5_reject_dangling_edge_target():
    res = wo.apply_operations(_doc(), [
        {"type": "addConnection", "source": "a", "target": "ghost_node"}])
    assert res["ok"] is False
    assert any("ghost_node" in e for e in res["errors"])


def test_6_reject_dangling_edge_source():
    res = wo.apply_operations(_doc(), [
        {"type": "addConnection", "source": "ghost_node", "target": "a"}])
    assert res["ok"] is False
    assert any("ghost_node" in e for e in res["errors"])


# ===========================================================================
# 7. ID NODE DUPLIKAT DITOLAK
# ===========================================================================
def test_7_reject_duplicate_node_id():
    res = wo.apply_operations(_doc(), [
        {"type": "addNode", "node": {"id": "a", "data": {"kind": "code"}}}])
    assert res["ok"] is False
    assert any("sudah ada" in e for e in res["errors"])


# ===========================================================================
# 8. JENIS OPERASI TIDAK DIKENAL DITOLAK
# ===========================================================================
def test_8_reject_unknown_op_type():
    res = wo.apply_operations(_doc(), [{"type": "dropDatabase"}])
    assert res["ok"] is False
    assert any("tidak dikenal" in e for e in res["errors"])


# ===========================================================================
# 9. KIND TIDAK DIKENAL DITOLAK
# ===========================================================================
def test_9_reject_unknown_kind():
    res = wo.apply_operations(_doc(), [
        {"type": "addNode", "node": {"id": "z", "data": {"kind": "rootkit"}}}])
    assert res["ok"] is False
    assert any("kind" in e and "rootkit" in e for e in res["errors"])


# ===========================================================================
# 10. KEAMANAN — prototype pollution DITOLAK (rekursif)
# ===========================================================================
def test_10_reject_prototype_pollution():
    res = wo.apply_operations(_doc(), [
        {"type": "addNode",
         "node": {"id": "p", "data": {"kind": "code"},
                  "config": {"__proto__": {"admin": True}}}}])
    assert res["ok"] is False
    assert any("__proto__" in e for e in res["errors"])
    # Kunci lain juga.
    res2 = wo.apply_operations(_doc(), [
        {"type": "updateNode", "id": "a",
         "updates": {"config": {"constructor": {"x": 1}}}}])
    assert res2["ok"] is False
    assert any("constructor" in e for e in res2["errors"])


# ===========================================================================
# 11. SELF-LOOP DITOLAK
# ===========================================================================
def test_11_reject_self_loop():
    res = wo.apply_operations(_doc(), [
        {"type": "addConnection", "source": "a", "target": "a"}])
    assert res["ok"] is False
    assert any("dirinya" in e for e in res["errors"])


# ===========================================================================
# 12. UPDATE KUNCI TERLARANG (mis. rename id) DITOLAK
# ===========================================================================
def test_12_reject_update_forbidden_key():
    res = wo.apply_operations(_doc(), [
        {"type": "updateNode", "id": "a", "updates": {"id": "a2"}}])
    assert res["ok"] is False
    assert any("tidak boleh diubah" in e for e in res["errors"])


# ===========================================================================
# 13. BATAS JUMLAH OPERASI (anti-DoS)
# ===========================================================================
def test_13_reject_op_limit_exceeded():
    ops = [{"type": "removeNode", "id": "nope"} for _ in range(wo.MAX_OPS + 1)]
    res = wo.apply_operations(_doc(), ops)
    assert res["ok"] is False
    assert any("terlalu banyak operasi" in e for e in res["errors"])


# ===========================================================================
# 14. DRY-RUN tidak mengubah apa pun, tapi diff dihitung
# ===========================================================================
def test_14_dry_run_no_mutation():
    doc = _doc()
    before = copy.deepcopy(doc)
    res = wo.apply_operations(
        doc, [{"type": "removeNode", "id": "a"}], dry_run=True)
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert doc == before, "dry_run tidak boleh mengubah input"
    assert res["diff"]["nodes_removed"] == ["a"]
    assert wo.validate_operations(doc, [{"type": "removeNode", "id": "a"}])["ok"]


# ===========================================================================
# 15. INPUT TIDAK DIUBAH saat sukses (immutability)
# ===========================================================================
def test_15_input_not_mutated_on_success():
    doc = _doc()
    before = copy.deepcopy(doc)
    res = wo.apply_operations(doc, [{"type": "removeNode", "id": "a"}])
    assert res["ok"] is True
    assert doc == before, "input asli tidak boleh berubah"
    assert res["flow_data"] is not doc, "hasil harus dokumen BARU"


# ===========================================================================
# 16. PERFORMA — 200 operasi valid < 1 detik
# ===========================================================================
def test_16_performance_200_ops_under_1s():
    doc = _doc()
    ops = []
    for i in range(0, 199):
        ops.append({"type": "addNode",
                    "node": {"id": f"n{i}", "data": {"kind": "code"}}})
    # 199 addNode + 1 addConnection = 200 (batas)
    ops.append({"type": "addConnection", "source": "n0", "target": "n1"})
    t0 = time.perf_counter()
    res = wo.apply_operations(doc, ops)
    dt = time.perf_counter() - t0
    assert res["ok"] is True, res["errors"]
    assert res["applied"] == 200
    assert dt < 1.0, f"terlalu lambat: {dt:.3f}s"


# ===========================================================================
# 17. DETERMINISME — hasil sama untuk input sama
# ===========================================================================
def test_17_deterministic():
    ops = [{"type": "addNode", "node": {"id": "c", "data": {"kind": "code"}}},
           {"type": "addConnection", "source": "a", "target": "c"}]
    r1 = wo.apply_operations(_doc(), ops)
    r2 = wo.apply_operations(_doc(), ops)
    assert r1["flow_data"] == r2["flow_data"]
    assert r1["diff"] == r2["diff"]


# ===========================================================================
# 18. BENTUK SPEC (bukan xyflow) juga didukung
# ===========================================================================
def test_18_spec_shape_supported():
    spec = {"nodes": [{"id": "t", "kind": "trigger"},
                      {"id": "a", "kind": "agent", "config": {}}],
            "edges": [{"source": "t", "target": "a"}]}
    res = wo.apply_operations(spec, [
        {"type": "updateNode", "id": "a", "updates": {"config": {"x": 1}}}])
    assert res["ok"] is True, res["errors"]
    node = [n for n in res["flow_data"]["nodes"] if n["id"] == "a"][0]
    assert node["config"] == {"x": 1}


# ===========================================================================
# 19. REMOVE CONNECTION yang tidak ada -> galat
# ===========================================================================
def test_19_remove_missing_connection():
    res = wo.apply_operations(_doc(), [
        {"type": "removeConnection", "source": "a", "target": "t"}])
    assert res["ok"] is False
    assert any("tidak ditemukan" in e for e in res["errors"])


# ===========================================================================
# 20. DAFTAR OPERASI KOSONG = no-op sukses
# ===========================================================================
def test_20_empty_operations_is_noop():
    res = wo.apply_operations(_doc(), [])
    assert res["ok"] is True
    assert res["applied"] == 0
    assert res["diff"]["changed"] is False
    assert wo.describe()["atomic"] is True
