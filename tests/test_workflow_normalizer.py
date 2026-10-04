"""Test normalizer spec workflow (BUG FIX 2026-10-04).

RAW di bawah adalah SALINAN PERSIS output qwen/qwen3.8-27b yang ditangkap dari
free-llm-gateway memakai system prompt Katalir. Tanpa normalizer, validator
menolak dengan `nodes: Field required` karena bentuknya beda.
"""

import json

# Sengaja TIDAK menyentuh sys.path di level modul:插入 di sini membuat
# test lain (test_katalir_protocols) gagal saat suite penuh karena urutan
# import berubah - terbukti lewat pembandingan dengan/tanpa berkas ini
# (12 gagal vs 3 gagal vs 0 gagal).
import workflow_spec as ws  # noqa: E402
from workflow_normalizer import normalize_workflow_payload as N  # noqa: E402

RAW_PRODUKSI = {
    "workflow": {
        "name": "Ambil Data & Kirim ke Telegram",
        "nodes": [
            {"id": "trigger_manual", "type": "trigger", "config": {"type": "manual"}},
            {"id": "fetch_data", "type": "http", "config": {
                "provider": "http", "url": "https://jsonplaceholder.typicode.com/posts/1",
                "method": "GET"}},
            {"id": "send_telegram", "type": "telegram", "config": {
                "provider": "telegram", "chat_id": "2109751369",
                "pesan": "{{fetch_data.body}}"}},
        ],
        "edges": [
            {"from": "trigger_manual", "to": "fetch_data"},
            {"from": "fetch_data", "to": "send_telegram"},
        ],
    }
}


def test_tanpa_normalizer_ditolak():
    """Bukti masalahnya: bentuk produksi TIDAK lolos validator apa adanya."""
    res = ws.validate_spec(json.dumps(RAW_PRODUKSI))
    assert res["ok"] is False


def test_normalizer_membuka_pembungkus_workflow():
    n = N(RAW_PRODUKSI)
    assert "workflow" not in n
    assert n["name"] == "Ambil Data & Kirim ke Telegram"


def test_normalizer_type_jadi_kind():
    n = N(RAW_PRODUKSI)
    assert [x.get("kind") for x in n["nodes"]] == ["trigger", "mcp", "mcp"]


def test_normalizer_edge_from_to_jadi_source_target():
    n = N(RAW_PRODUKSI)
    assert [(e.get("source"), e.get("target")) for e in n["edges"]] == [
        ("trigger_manual", "fetch_data"), ("fetch_data", "send_telegram")]


def test_hasil_normalizer_lolos_validator():
    res = ws.validate_spec(json.dumps(N(RAW_PRODUKSI)))
    assert res["ok"] is True, res.get("errors")
    assert len(res["spec"]["nodes"]) == 3


def test_normalizer_tidak_melempar_pada_bentuk_aneh():
    assert N(None) == {}
    assert N("bukan json") == {}
    assert N([1, 2, 3]) == {}
    assert N({"nodes": "bukan list"})["nodes"] == "bukan list"


def test_bentuk_lama_tetap_berfungsi():
    """Spec yang SUDAH benar tidak boleh dirusak oleh normalizer."""
    good = {"name": "x", "nodes": [{"id": "t", "kind": "trigger"}], "edges": []}
    n = N(good)
    assert n["nodes"][0]["kind"] == "trigger"
    assert ws.validate_spec(json.dumps(n))["ok"] is True


def test_spec_json_lama_masih_diterima_lewat_tool():
    import tools

    out = json.loads(tools.execute_tool(
        "generate_workflow_json", {"spec_json": json.dumps(RAW_PRODUKSI["workflow"])}, "u@k.test"))
    assert out["ok"] is True, out.get("errors")
    assert out["node_count"] == 3


def test_kunci_workflow_diterima_lewat_tool():
    import tools

    out = json.loads(tools.execute_tool("generate_workflow_json", RAW_PRODUKSI, "u@k.test"))
    assert out["ok"] is True, out.get("errors")
    assert out["node_count"] == 3
    assert out["edge_count"] == 2