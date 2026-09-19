# tests/test_discovery_agent.py
"""FASE 2.1 — Discovery Agent: prompt klarifikasi + alat generate_workflow_json.

Dua hal yang mudah "membusuk" tanpa test: (a) instruksi klarifikasi dihapus
saat prompt diedit, dan (b) alat tidak lagi terdaftar di salah satu format
schema. Keduanya mematikan kemampuan chat->canvas tanpa error apa pun.
"""
import json
import os
import pathlib
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api_server as srv  # noqa: E402
import tools as t  # noqa: E402

GOOD_SPEC = json.dumps({
    "name": "Notif Telegram",
    "nodes": [
        {"id": "trg", "kind": "trigger", "label": "Tiap jam 9",
         "config": {"schedule": "0 9 * * *"}},
        {"id": "ai", "kind": "agent", "label": "Ringkas"},
        {"id": "tg", "kind": "mcp", "label": "Kirim Telegram",
         "config": {"provider": "telegram"}},
    ],
    "edges": [{"source": "trg", "target": "ai"}, {"source": "ai", "target": "tg"}],
})


def _tool_names_openai() -> list[str]:
    return [s["function"]["name"] for s in t.TOOL_SCHEMAS_OPENAI]


def _tool_names_gemini() -> list[str]:
    return [d.name for tool in t.TOOL_DECLARATIONS
            for d in (getattr(tool, "function_declarations", None) or [])]


def test_alat_workflow_terdaftar_di_kedua_format():
    assert "generate_workflow_json" in _tool_names_openai()
    assert "generate_workflow_json" in _tool_names_gemini()


def test_prompt_meminta_klarifikasi_sebelum_membangun():
    p = srv._AGENT_SYSTEM
    assert "MODE DISCOVERY" in p
    assert "klarifikasi" in p
    # Harus ada larangan membangun sebelum detail lengkap.
    assert "JANGAN langsung membangun" in p or "jangan langsung" in p.lower()


def test_prompt_wajib_lewat_alat_bukan_json_di_chat():
    p = srv._AGENT_SYSTEM
    assert "generate_workflow_json" in p
    assert "Jangan menulis JSON di balasan" in p


def test_alat_menolak_spec_tanpa_trigger():
    bad = json.dumps({"name": "x", "nodes": [{"id": "a", "kind": "agent"}]})
    out = json.loads(t.execute_tool("generate_workflow_json", {"spec_json": bad}, "u@k.id"))
    assert out["ok"] is False
    assert any("trigger" in e for e in out["errors"]), out


def test_alat_mengembalikan_spec_siap_canvas():
    out = json.loads(t.execute_tool(
        "generate_workflow_json", {"spec_json": GOOD_SPEC}, "u@k.id"))
    assert out["ok"] is True, out
    assert out["node_count"] == 3 and out["edge_count"] == 2
    spec = out["spec"]
    # Bentuk yang langsung dipakai canvas-store: type=kind, data.kind, position.
    assert [n["type"] for n in spec["nodes"]] == ["trigger", "agent", "mcp"]
    assert all("position" in n and "data" in n for n in spec["nodes"])
    assert all({e["source"], e["target"]} for e in spec["edges"])
    assert spec["nodes"][0]["data"]["kind"] == "trigger"


def test_alat_menyertakan_owner_tapi_tidak_membocorkan_apa_pun():
    out = json.loads(t.execute_tool(
        "generate_workflow_json",
        {"spec_json": json.dumps({"name": "n", "nodes": [{"id": "t", "kind": "trigger"}]})},
        "user@katalir.id"))
    assert out["owner"] == "user@katalir.id"
    # Tidak ada field kredensial yang ikut terkirim ke model.
    blob = json.dumps(out).lower()
    for leak in ("api_token", "api_key", "secret", "password"):
        assert leak not in blob, leak


def test_jembatan_ke_canvas_hanya_untuk_draf_yang_diterima():
    """`_accepted_workflow` = satu-satunya pintu spec masuk ke respons /chat."""
    accepted = json.dumps({"ok": True, "spec": {"name": "n", "nodes": [], "edges": []}})
    assert srv._accepted_workflow(accepted) == {"name": "n", "nodes": [], "edges": []}

    rejected = json.dumps({"ok": False, "errors": ["tanpa trigger"]})
    assert srv._accepted_workflow(rejected) is None
    assert srv._accepted_workflow("{bukan json}") is None
    assert srv._accepted_workflow(None) is None
    assert srv._accepted_workflow(json.dumps({"ok": True})) is None


def test_kedua_jalur_agent_mengirim_workflow_di_meta():
    """Gateway DAN jalur Gemini langsung harus memuat kunci `workflow`.

    Kalau salah satu lupa, canvas kosong hanya pada sebagian provider — bug
    yang sulit terlihat karena tidak ada error apa pun.
    """
    src = (pathlib.Path(ROOT) / "api_server.py").read_text(encoding="utf-8")
    assert src.count('"workflow": workflow_out') == 2, "satu jalur agent tidak mengirim workflow"
    assert src.count('_accepted_workflow(result)') + src.count('_accepted_workflow(tool_result)') >= 2


def test_kontrak_respons_chat_meneruskan_meta_apa_adanya():
    src = (pathlib.Path(ROOT) / "api_server.py").read_text(encoding="utf-8")
    assert '"status": "success", "reply": reply, "session_id": session_id, "meta": meta' in src

