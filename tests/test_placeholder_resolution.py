"""test_placeholder_resolution.py - BUG-3 & BUG-6 (adversarial 2026-10-07).

BUG-3 (KRITIS): token `{{akar.segmen}}` dikirim VERBATIM ke runtime - tidak
ada kode yang menghitungnya, field yang hilang tidak memicu error, dan string
placeholder mentah masuk ke LLM / API eksternal tanpa suara (bukti S3:
`{{http_1.response.data.user.name}}` tetap utuh di semua node).

Kunci di sini:

1. RUNTIME  - `execution_engine._resolve_text` / `_resolve_cfg` mengevaluasi
              `{{node.path}}` terhadap konteks eksekusi; gagal ->
              `PlaceholderResolutionError` (kegagalan jujur, bukan diam).
2. HEALING  - error itu diklasifikasi `abort` (tidak retry membakar kuota LLM).
3. SAVE     - `workflow_spec.validate_spec` memeriksa placeholder saat save:
              akar ekspresi tak dikenal = ERROR, placeholder isi-user = WARNING.
4. DESAIN   - `{{tanpa_titik}}` (chat_id/url/channel) DIBIARKAN utuh:
              memang placeholder isi-user yang harus diisi user di kanvas
              (didesain oleh `_AGENT_SYSTEM`, bukan referensi runtime).
"""

import asyncio
import json

import pytest

ee = pytest.importorskip("execution_engine")
import self_healing  # noqa: E402
import workflow_spec as ws  # noqa: E402


def _orch(trigger_input=None, agent_cfg=None):
    """Orkestrator mini: trigger `t` -> agent `a`."""
    nodes = [
        {"id": "t", "type": "trigger",
         "data": {"kind": "trigger", "label": "Manual", "config": {}}},
        {"id": "a", "type": "agent",
         "data": {"kind": "agent", "label": "Agen",
                  "config": agent_cfg or {}}},
    ]
    return ee.StatefulOrchestrator(
        ee.FlowGraph(nodes=nodes, edges=[{"source": "t", "target": "a"}]),
        trigger_input=dict(trigger_input or {}), owner_email="")


# ---------------------------------------------------------------------------
# 1. RUNTIME: resolusi {{node.path}} terhadap konteks eksekusi
# ---------------------------------------------------------------------------

def test_resolv_ekspresi_dari_output_node():
    """{{http_1.response.data.user.name}} diganti nilai asli (S3)."""
    orch = _orch()
    orch.outputs["http_1"] = {
        "type": "mcp.call",
        "result": {"response": {"data": {"user": {"name": "Budi"}}}},
    }
    out = orch._resolve_text("Nama: {{http_1.response.data.user.name}}",
                             where="tes")
    assert out == "Nama: Budi"


def test_resolv_nilai_non_string_jadi_json():
    orch = _orch()
    orch.outputs["a"] = {"reply": {"ok": True, "n": 3}}
    assert orch._resolve_text("{{a.reply}}", where="tes") == \
        json.dumps({"ok": True, "n": 3}, ensure_ascii=False)


def test_resolv_alias_payload_trigger():
    """Alias trigger/input/payload/data dipakai model tanpa tahu id trigger."""
    orch = _orch(trigger_input={"status": "valid"})
    assert orch._resolve_text("{{data.status}}", where="tes") == "valid"
    assert orch._resolve_text("{{payload.status}}", where="tes") == "valid"


def test_placeholder_isi_user_dibiarkan_utuh():
    """{{chat_id}} tanpa titik = placeholder isi-user; runtime tak menyentuh."""
    orch = _orch()
    s = "kirim ke {{chat_id}} lewat {{url}}"
    assert orch._resolve_text(s, where="tes") == s


# ---------------------------------------------------------------------------
# 2. RUNTIME: gagal resolv -> error JUJUR, bukan string verbatim
# ---------------------------------------------------------------------------

def test_field_hilang_memicu_error_jujur():
    orch = _orch()
    orch.outputs["http_1"] = {"type": "mcp.call", "result": {"status": "ok"}}
    with pytest.raises(ee.PlaceholderResolutionError, match="tidak ditemukan"):
        orch._resolve_text("{{http_1.response.data.user.name}}", where="tes")


def test_akar_tak_dikenal_memicu_error():
    orch = _orch()
    with pytest.raises(ee.PlaceholderResolutionError,
                       match="tidak ada di workflow"):
        orch._resolve_text("{{ghost.body}}", where="tes")


def test_node_belum_dieksekusi_memicu_error():
    """Node ada di graph tapi belum menghasilkan output (bukan predesesor)."""
    orch = _orch()
    with pytest.raises(ee.PlaceholderResolutionError,
                       match="belum menghasilkan output"):
        orch._resolve_text("{{a.reply}}", where="tes")


def test_resolve_cfg_salinan_tanpa_mengubah_config_asli():
    orch = _orch(trigger_input={"base": "https://api.example.com"})
    original = {"provider": "http", "url": "{{payload.base}}/x",
                "chat_id": "{{chat_id}}"}
    cfg = orch._resolve_cfg(original, where="tes")
    assert cfg["url"] == "https://api.example.com/x"
    assert cfg["chat_id"] == "{{chat_id}}"          # placeholder isi-user utuh
    assert original["url"] == "{{payload.base}}/x"  # config asli tidak dimutasi


# ---------------------------------------------------------------------------
# 3. HEALING: error placeholder = abort (tanpa retry / search forum)
# ---------------------------------------------------------------------------

def test_healing_mengklasifikasi_placeholder_sebagai_abort():
    rule = self_healing.classify_error(
        "PlaceholderResolutionError: akar 'ghost' tidak ada di workflow")
    assert rule.name == "placeholder_invalid"
    assert rule.action == "abort"
    assert rule.max_attempts == 0
    assert rule.search is False


# ---------------------------------------------------------------------------
# 4. RUNNER END-TO-END: prompt agent benar-benar diresolv sebelum LLM
# ---------------------------------------------------------------------------

def _fake_reason(captured):
    import agent_reasoner

    async def _fake_run(prompt, user_input, config=None):
        captured["prompt"] = prompt
        return {"status": "success", "reply": "ok", "model": "tes",
                "usage": {}, "cost_usd": 0.0}

    return agent_reasoner, _fake_run


def test_exec_agent_resolv_prompt_sebelum_ke_llm(monkeypatch):
    captured: dict[str, str] = {}
    mod, fake = _fake_reason(captured)
    monkeypatch.setattr(mod, "run_agent", fake)

    orch = _orch(trigger_input={"name": "Budi"},
                 agent_cfg={"prompt": "Sapa {{payload.name}} sekarang"})
    asyncio.run(orch.run())
    assert captured.get("prompt") == "Sapa Budi sekarang"


def test_exec_agent_field_hilang_gagal_bukan_kirim_verbatim(monkeypatch):
    """Placeholder tak teresolusi NAIK error; LLM tidak pernah melihatnya."""
    captured: dict[str, str] = {}
    mod, fake = _fake_reason(captured)
    monkeypatch.setattr(mod, "run_agent", fake)

    orch = _orch(trigger_input={},
                 agent_cfg={"prompt": "nilai {{payload.tidak_ada.x}}"})
    # run() membungkus error node jadi RuntimeError; penyebabnya tetap
    # PlaceholderResolutionError (via `raise ... from res`).
    with pytest.raises(RuntimeError, match="PlaceholderResolutionError") as exc:
        asyncio.run(orch.run())
    assert isinstance(exc.value.__cause__, ee.PlaceholderResolutionError)
    assert "prompt" not in captured, (
        "LLM menerima placeholder mentah (verbatim) - BUG-3 terulang")


# ---------------------------------------------------------------------------
# 5. SAVE: validasi placeholder saat simpan workflow (BUG-6)
# ---------------------------------------------------------------------------

def _spec(nodes, edges=None):
    return json.dumps({
        "name": "x", "nodes": nodes,
        "edges": edges if edges is not None else [{"source": "t", "target": "a"}],
    })


def test_save_warning_placeholder_isi_user():
    """{{chat_id}} belum diisi = warning (bukan error) - desain kanvas."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "m", "kind": "mcp",
         "config": {"provider": "telegram", "chat_id": "{{chat_id}}",
                    "pesan": "halo"}},
    ], edges=[{"source": "t", "target": "m"}]))
    assert res["ok"] is True, res
    assert any("{{chat_id}}" in w and "belum diisi" in w
               for w in res["warnings"]), res["warnings"]


def test_save_error_ekspresi_akar_tak_dikenal():
    """Ekspresi {{ghost.body}} - akar tak ada di graph -> ditolak saat save."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent",
         "config": {"prompt": "pakai {{ghost.body}}"}},
    ]))
    assert res["ok"] is False, res
    msg = " ".join(res["errors"])
    assert "ghost" in msg and "{{ghost.body}}" in msg


def test_save_ekspresi_akar_valid_lolos():
    """Ekspresi ke id node yang ada (pola normalizer produksi) tetap lolos."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "fetch_data", "kind": "agent", "config": {"prompt": "ambil"}},
        {"id": "a", "kind": "agent",
         "config": {"prompt": "pakai {{fetch_data.body}}"}},
    ]))
    assert res["ok"] is True, res


def test_save_ekspresi_alias_trigger_lolos():
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent",
         "config": {"prompt": "status {{payload.status}}"}},
    ]))
    assert res["ok"] is True, res

