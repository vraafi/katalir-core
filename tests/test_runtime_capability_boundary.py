"""test_runtime_capability_boundary.py - BUG-1 (adversarial 2026-10-07).

Temuan BUG-1 (KRITIS): model AI mengaku membangun node IF / Split In
Batches / Supervisor padahal runtime hanya punya `trigger|agent|mcp` dan
menjalankannya linear.

TRIASE 2026-10-06 (kejujuran) lalu IMPLEMENTASI 2026-10-07 (brief 3-bug):
runtime KINI benar-benar mendukung ketiganya, jadi lapisan berubah:

1. PROMPT   - `_AGENT_SYSTEM` memuat blok KAPASITAS RUNTIME yang mengajari
              skema nyata: condition/else_condition, batch_size, dan
              role=supervisor + delegates. Tetap melarang label palsu.
2. VALIDASI - `workflow_spec.validate_spec` MENERIMA config tersebut dan
              memvalidasi BENTUKNYA (condition harus string, batch_size >= 1,
              delegates harus menunjuk id nyata, sub_workflow tetap ditolak).
3. RUNNER   - `_exec_agent` membaca `prompt` (yang ditulis canvas & model)
              sebelum `system_prompt`; sebelumnya instruksi di `prompt`
              TERSINGKIR dan diganti label node - silent failure turunan
              yang ditemukan saat triase BUG-1.
"""

import asyncio
import json

import pytest

# ---------------------------------------------------------------------------
# 1. PROMPT: batas kapasitas ada & lengkap
# ---------------------------------------------------------------------------


def test_prompt_menyebut_kapasitas_runtime():
    api_server = pytest.importorskip("api_server")
    p = api_server._AGENT_SYSTEM
    assert "KAPASITAS RUNTIME" in p
    # Fitur yang KINI didukung harus disebut beserta skema confignya
    # (BUG #1/#3/#4, 7 Okt 2026).
    for kata in ("condition", "batch_size", "supervisor", "delegates",
                 "DELEGATE"):
        assert kata in p, f"prompt tidak menyebut {kata!r}"
    # Kejujuran tetap: jangan memberi label palsu.
    assert "label palsu" in p
    # Kontrak config: instruksi agent = `prompt`, pemicu = `event_name`.
    assert "event_name" in p
    # sub_workflow tetap tidak didukung.
    assert "sub_workflow" in p


# ---------------------------------------------------------------------------
# 2. VALIDASI: config BUG #1/#3/#4 diterima (bentuk divalidasi), bukan ditolak
# ---------------------------------------------------------------------------
import workflow_spec as ws  # noqa: E402


def _spec(nodes):
    return json.dumps({"name": "x", "nodes": nodes,
                       "edges": [{"source": "t", "target": "a"}]})


def test_validator_menerima_condition_cabang():
    """`condition` (S1) kini DIDUKUNG runtime (BUG #1) - harus lolos."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent",
         "config": {"condition": "{{data.status}} == 'valid'", "prompt": "OK"}},
    ]))
    assert res["ok"] is True, res


def test_validator_menerima_batch_size_split():
    """`batch_size` (S2) kini DIDUKUNG runtime (BUG #4) - harus lolos."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent", "config": {"batch_size": 1}},
    ]))
    assert res["ok"] is True, res


def test_validator_menerima_role_supervisor():
    """`role=supervisor` (S5) kini DIDUKUNG runtime (BUG #3) - harus lolos."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent",
         "config": {"role": "supervisor", "delegates": ["b"], "prompt": "koord"}},
        {"id": "b", "kind": "agent", "config": {"prompt": "riset"}},
    ]))
    assert res["ok"] is True, res


def test_validator_tolak_bentuk_condition_salah():
    """Bentuk salah tetap ditolak (bukan silent failure saat eksekusi)."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent", "config": {"condition": 123}},
    ]))
    assert res["ok"] is False, res
    assert "condition" in " ".join(res["errors"])


def test_validator_tolak_batch_size_nol():
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent", "config": {"batch_size": 0}},
    ]))
    assert res["ok"] is False, res
    assert "batch_size" in " ".join(res["errors"])


def test_validator_tolak_delegates_ke_id_tak_ada():
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent",
         "config": {"role": "supervisor", "delegates": ["hantu"]}},
    ]))
    assert res["ok"] is False, res
    assert "hantu" in " ".join(res["errors"])


def test_validator_tolak_sub_workflow():
    """`sub_workflow` tetap tidak didukung -> ditolak dengan hint delegasi."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent", "config": {"sub_workflow": "wf-2"}},
    ]))
    assert res["ok"] is False, res
    msg = " ".join(res["errors"])
    assert "sub_workflow" in msg
    assert "delegasi" in msg or "supervisor" in msg


def test_validator_draf_bersih_tetap_lolos():
    """Spec tanpa config khusus tidak terdampak (regresi positif)."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {"type": "manual"}},
        {"id": "a", "kind": "agent", "config": {"prompt": "Rangkum data"}},
    ]))
    assert res["ok"] is True, res


# ---------------------------------------------------------------------------
# 3. RUNNER: instruksi di config `prompt` (canvas) benar-benar dipakai
# ---------------------------------------------------------------------------
ee = pytest.importorskip("execution_engine")


def _fake_reason(captured):
    """Buat versi `agent_reasoner.run_agent` palsu yang mencatat prompt."""
    import agent_reasoner

    async def _fake_run(prompt, user_input, config=None):
        captured["prompt"] = prompt
        return {"status": "success", "reply": "ok", "model": "tes",
                "usage": {}, "cost_usd": 0.0}

    return agent_reasoner, _fake_run


def _graph(agent_config, label="Analis Data"):
    return ee.FlowGraph(
        nodes=[
            {"id": "t", "type": "trigger",
             "data": {"kind": "trigger", "label": "Manual", "config": {}}},
            {"id": "a", "type": "agent",
             "data": {"kind": "agent", "label": label, "config": agent_config}},
        ],
        edges=[{"source": "t", "target": "a"}],
    )


def test_exec_agent_membaca_prompt_canvas(monkeypatch):
    """Config `prompt` (ditulis ConfigPanel & model) wajib sampai ke LLM.

    Regresi: runner dulu hanya membaca `system_prompt` -> instruksi canvas
    diganti label node TANPA error (silent failure turunan BUG-1).
    """
    captured: dict[str, str] = {}
    mod, fake = _fake_reason(captured)
    monkeypatch.setattr(mod, "run_agent", fake)

    orch = ee.StatefulOrchestrator(
        _graph({"prompt": "INSTRUKSI-CANVAS-UNIK"}),
        trigger_input={}, owner_email="")
    steps = asyncio.run(orch.run())
    assert captured.get("prompt") == "INSTRUKSI-CANVAS-UNIK", (
        f"instruksi canvas tidak sampai ke LLM (dapat {captured!r}); "
        f"steps={[(s.node_id, s.status) for s in steps]}"
    )


def test_exec_agent_fallback_legacy_system_prompt(monkeypatch):
    """Alias legacy `system_prompt` tetap didukung (workflow lama)."""
    captured: dict[str, str] = {}
    mod, fake = _fake_reason(captured)
    monkeypatch.setattr(mod, "run_agent", fake)

    orch = ee.StatefulOrchestrator(
        _graph({"system_prompt": "PROMPT-LEGACY-UNIK"}, label="Lama"),
        trigger_input={}, owner_email="")
    asyncio.run(orch.run())
    assert captured.get("prompt") == "PROMPT-LEGACY-UNIK"

