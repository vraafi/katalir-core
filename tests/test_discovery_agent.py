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
         "config": {"provider": "telegram", "chat_id": "-1001"}},
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


def test_prompt_membangun_langsung_dengan_placeholder():
    """REGRESI 2026-10-06: agen bertanya 'berapa chat_id?' padahal alur jelas.

    Aturan build-workflow harus: (a) membangun langsung saat alur sudah jelas,
    (b) memakai placeholder {{...}} untuk nilai teknis yang belum disebut,
    (c) hanya bertanya saat INTENSI ambigu - bukan karena satu nilai kosong.
    Tanpa aturan ini, MODE DISCOVERY membuat agen menahan diri terus dan
    workflow tidak pernah dibangun.
    """
    p = srv._AGENT_SYSTEM
    assert "ATURAN BUILD WORKFLOW" in p
    assert "PLACEHOLDER" in p
    assert "{{chat_id}}" in p and "{{url}}" in p
    assert "LANGSUNG bangun workflow" in p
    # Pemisahan eksplisit: kekurangan satu nilai teknis != alasan bertanya.
    assert "Kekurangan satu nilai teknis BUKAN alasan bertanya" in p


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
    """Semua jalur agent harus memuat kunci `workflow` di meta.

    Kalau salah satu lupa, canvas kosong hanya pada sebagian provider — bug
    yang sulit terlihat karena tidak ada error apa pun.

    Jalur yang dihitung:
      1. gateway + `tool_calls` terstruktur
      2. gateway + tool call TEKS (Gemma 4 / Qwen3-Coder) - BUG FIX 2026-10-02
      3. Gemini langsung (`response.function_calls`)
    """
    src = (pathlib.Path(ROOT) / "api_server.py").read_text(encoding="utf-8")
    n_workflow = src.count('"workflow": workflow_out')
    assert n_workflow >= 3, (
        f"harus ada >=3 jalur yang mengirim workflow (-structured, textual, "
        f"direct-), ditemukan {n_workflow}")
    assert src.count('_accepted_workflow(result)') + src.count('_accepted_workflow(tool_result)') >= 3


def test_jalur_textual_menjalankan_alat_dan_menyembunyikan_json():
    """Tool call TEKS harus dieksekusi, dan JSON-nya tidak boleh tampil.

    Ini regresi bug "tool call tidak dieksekusi": model seperti Gemma 4 menulis
    `<|tool_call>call:NS:NAME({...})<tool_call|>` di `content`, bukan di
    `resp.tool_calls`. Tanpa jalur ini, JSON mentah masuk ke `reply` dan
    canvas tetap kosong.
    """
    srv_path = pathlib.Path(ROOT) / "api_server.py"
    src = srv_path.read_text(encoding="utf-8")
    assert "extract_textual_tool_calls" in src
    assert "strip_textual_tool_calls" in src
    assert 'tools.execute_tool(name, c["args"], email)' in src
    # Nama alat ber-namespace harus diupah supaya cocok dengan registry.
    assert "def _tool_name(" in src


def test_web_search_terdaftar_di_kedua_format_skema():
    """Tool pencarian harus terlihat baik di jalur Gemini langsung maupun gateway."""
    src = (pathlib.Path(ROOT) / "tools.py").read_text(encoding="utf-8")
    assert 'name="web_search"' in src
    assert "_web_search_declaration" in src
    assert 'if name == "web_search":' in src
    # openai_tool_schemas() diturunkan dari TOOL_DECLARATIONS, jadi cukup
    # mendaftarkan di satu tempat untuk keduanya.
    assert "def openai_tool_schemas" in src


def test_system_prompt_meminta_verifikasi_sebelum_menjawab():
    """System prompt harus memaksa 'cari dulu' untuk pertanyaan teknis."""
    src = (pathlib.Path(ROOT) / "api_server.py").read_text(encoding="utf-8")
    assert "ATURAN VERIFIKASI (WAJIB)" in src
    assert "`web_search`" in src
    assert "Jangan berasumsi dari ingatan" in src


def test_kontrak_respons_chat_meneruskan_meta_apa_adanya():
    src = (pathlib.Path(ROOT) / "api_server.py").read_text(encoding="utf-8")
    # BUG FIX 2026-10-05: literal di atas dihapus karena endpoint tidak boleh
    # lagi hardcode "status". Kontrak yang sebenarnya diuji di sini -
    # meta diteruskan apa adanya - MASIH berlaku, hanya lewat `_response`.
    assert ('_response = {"status": "success", "reply": reply,' in src
            and '"session_id": session_id, "meta": meta}' in src)
    assert '_response["status"] = _gw_status' in src

