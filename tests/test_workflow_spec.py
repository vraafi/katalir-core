# tests/test_workflow_spec.py
"""Kontrak WorkflowSpec (FASE 2.1) — jembatan "chat → JSON → canvas".

Yang dijaga: JSON dari model TIDAK boleh sampai ke canvas kalau bentuknya
salah, dan setiap penolakan harus memberi pesan yang bisa dipakai model untuk
memperbaiki diri (repair loop). Semua test tanpa jaringan.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workflow_spec as ws  # noqa: E402


def _spec(nodes, edges=None, name="WF"):
    return json.dumps({"name": name, "nodes": nodes, "edges": edges or []})


# ---------------------------------------------------------------------------
# 1. Spec valid -> ok + bentuk final siap-canvas
# ---------------------------------------------------------------------------
def test_spec_valid_dinormalkan_untuk_canvas():
    raw = _spec(
        [
            {"id": "t1", "kind": "trigger", "label": "Jadwal 09:00",
             "config": {"schedule": "0 9 * * *"}},
            {"id": "m1", "kind": "mcp", "label": "Kirim Telegram",
             "config": {"provider": "telegram"}},
        ],
        [{"source": "t1", "target": "m1"}],
    )
    res = ws.validate_spec(raw)

    assert res["ok"] is True, res
    spec = res["spec"]
    assert spec["name"] == "WF"
    assert [n["id"] for n in spec["nodes"]] == ["t1", "m1"]
    # `type` harus = kind agar xyflow memakai custom node yang benar.
    assert [n["type"] for n in spec["nodes"]] == ["trigger", "mcp"]
    # data wajib memuat kind/label/config (bentuk FlowNodeData di frontend).
    assert set(spec["nodes"][0]["data"]) == {"kind", "label", "config"}
    assert spec["edges"][0]["source"] == "t1"
    assert spec["edges"][0]["target"] == "m1"


def test_posisi_dihitung_otomatis_dan_makin_ke_kanan():
    raw = _spec(
        [
            {"id": "t", "kind": "trigger"},
            {"id": "a", "kind": "agent"},
            {"id": "m", "kind": "mcp", "config": {"provider": "http"}},
        ],
        [{"source": "t", "target": "a"}, {"source": "a", "target": "m"}],
    )
    res = ws.validate_spec(raw)
    assert res["ok"] is True, res

    x = {n["id"]: n["position"]["x"] for n in res["spec"]["nodes"]}
    assert x["t"] < x["a"] < x["m"], x     # layout mengikuti kedalaman alur


def test_posisi_dari_model_dihormati():
    raw = _spec([{"id": "t", "kind": "trigger", "position": {"x": 500, "y": 42}}])
    res = ws.validate_spec(raw)
    assert res["ok"] is True, res
    pos = res["spec"]["nodes"][0]["position"]
    assert (pos["x"], pos["y"]) == (500.0, 42.0)


# ---------------------------------------------------------------------------
# 2. Toleransi & kebersihan input
# ---------------------------------------------------------------------------
def test_pagar_code_fence_dibuang():
    raw = "```json\n" + _spec([{"id": "t", "kind": "trigger"}]) + "\n```"
    assert ws.validate_spec(raw)["ok"] is True


def test_edge_ganda_di_dedupe():
    raw = _spec([{"id": "t", "kind": "trigger"}, {"id": "a", "kind": "agent"}],
                [{"source": "t", "target": "a"}, {"source": "t", "target": "a"}])
    res = ws.validate_spec(raw)
    assert res["ok"] is True


# ---------------------------------------------------------------------------
# 3. Penolakan HARUS actionable (umpan perbaikan untuk model)
# ---------------------------------------------------------------------------
def test_json_rusak_ditolak_dengan_posisi():
    res = ws.validate_spec('{"name": "x", "nodes": [}')
    assert res["ok"] is False
    assert any("tidak valid" in e for e in res["errors"]), res
    assert res["hint"]


def test_tanpa_trigger_ditolak():
    raw = _spec([{"id": "a", "kind": "agent"}])
    res = ws.validate_spec(raw)
    assert res["ok"] is False
    assert any("trigger" in e for e in res["errors"]), res


def test_edge_ke_node_tak_dikenal_ditolak():
    raw = _spec([{"id": "t", "kind": "trigger"}], [{"source": "t", "target": "hantu"}])
    res = ws.validate_spec(raw)
    assert res["ok"] is False
    assert any("hantu" in e for e in res["errors"]), res


def test_id_node_duplikat_ditolak():
    raw = _spec([{"id": "x", "kind": "trigger"}, {"id": "x", "kind": "agent"}])
    res = ws.validate_spec(raw)
    assert res["ok"] is False
    assert any("duplikat" in e for e in res["errors"]), res


def test_mcp_tanpa_provider_ditolak():
    raw = _spec([{"id": "t", "kind": "trigger"},
                 {"id": "m", "kind": "mcp", "label": "kirim"}])
    res = ws.validate_spec(raw)
    assert res["ok"] is False
    assert any("provider" in e for e in res["errors"]), res


def test_kosong_ditolak():
    res = ws.validate_spec("")
    assert res["ok"] is False and res["errors"]


# ---------------------------------------------------------------------------
# 4. Peringatan (tidak memblokir, tapi terlihat)
# ---------------------------------------------------------------------------
def test_provider_tak_dikenal_jadi_warning_bukan_error():
    raw = _spec([{"id": "t", "kind": "trigger"},
                 {"id": "m", "kind": "mcp", "config": {"provider": "zapier"}}])
    res = ws.validate_spec(raw)
    assert res["ok"] is True, res
    assert any("zapier" in w for w in res["warnings"]), res


def test_node_terpisah_tanpa_edge_jadi_warning():
    raw = _spec([{"id": "t", "kind": "trigger"}, {"id": "a", "kind": "agent"}])
    res = ws.validate_spec(raw)
    assert res["ok"] is True, res
    assert any("edge" in w for w in res["warnings"]), res


# ---------------------------------------------------------------------------
# 5. Siklus tidak boleh menggantung (guard topologi)
# ---------------------------------------------------------------------------
def test_siklus_tidak_membuat_hang():
    raw = _spec(
        [{"id": "t", "kind": "trigger"}, {"id": "a", "kind": "agent"},
         {"id": "b", "kind": "agent"}],
        [{"source": "t", "target": "a"}, {"source": "a", "target": "b"},
         {"source": "b", "target": "a"}],
    )
    res = ws.validate_spec(raw)
    assert res["ok"] is True, res
    assert len(res["spec"]["nodes"]) == 3


def test_id_edge_deterministik():
    raw = _spec([{"id": "t", "kind": "trigger"}, {"id": "a", "kind": "agent"}],
                [{"source": "t", "target": "a"}])
    a = ws.validate_spec(raw)["spec"]["edges"][0]["id"]
    b = ws.validate_spec(raw)["spec"]["edges"][0]["id"]
    assert a == b and a.startswith("rf-")
