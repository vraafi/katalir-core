"""test_runtime_capability_boundary.py - BUG-1 (adversarial 2026-10-07).

Temuan BUG-1 (KRITIS): model AI mengaku membangun node IF / Split In
Batches / Supervisor padahal runtime hanya punya `trigger|agent|mcp` dan
menjalankannya linear. Tiga lapis perbaikan dikunci di sini:

1. PROMPT   - `_AGENT_SYSTEM` memuat blok BATAS KAPASITAS RUNTIME yang
              memaksa kejujuran (tidak mengaku fitur yang tidak ada).
2. VALIDASI - `workflow_spec.validate_spec` MENOLAK config mati
              (`condition`, `batch_size`, `sub_workflow`, ...) yang tidak
              pernah dibaca runner.
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


def test_prompt_menyebut_batas_kapasitas_runtime():
    api_server = pytest.importorskip("api_server")
    p = api_server._AGENT_SYSTEM
    assert "BATAS KAPASITAS RUNTIME" in p
    # Fitur yang TIDAK ada harus disebut eksplisit (S1/S2/S5).
    for kata in ("IF", "Split In Batches", "Supervisor", "TIDAK ADA"):
        assert kata in p, f"prompt tidak menyebut {kata!r}"
    # Instruksi kejujuran: jangan mengaku fitur yang tidak ada.
    assert "BELUM tersedia" in p
    assert "label palsu" in p
    # Kontrak config: instruksi agent = `prompt`, pemicu = `event_name`.
    assert "config prompt" in p
    assert "event_name" in p


# ---------------------------------------------------------------------------
# 2. VALIDASI: config mati ditolak dengan pesan yang bisa diperbaiki model
# ---------------------------------------------------------------------------
import workflow_spec as ws  # noqa: E402


def _spec(nodes):
    return json.dumps({"name": "x", "nodes": nodes,
                       "edges": [{"source": "t", "target": "a"}]})


def test_validator_menolak_condition_cabang():
    """`condition` (S1) tidak boleh lolos - runner tidak pernah membacanya."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent",
         "config": {"condition": "{{data.status}} == 'valid'", "prompt": "OK"}},
    ]))
    assert res["ok"] is False, res
    msg = " ".join(res["errors"])
    assert "condition" in msg
    assert "tidak didukung runtime" in msg
    # Hint harus mengarah ke cara jujur, bukan sekadar "salah".
    assert "prompt agent" in msg or "linear" in msg


def test_validator_menolak_batch_size_split():
    """`batch_size` (S2) tidak boleh lolos - tidak ada loop iterasi."""
    res = ws.validate_spec(_spec([
        {"id": "t", "kind": "trigger", "config": {}},
        {"id": "a", "kind": "agent", "config": {"batch_size": 1}},
    ]))
    assert res["ok"] is False, res
    assert "batch_size" in " ".join(res["errors"])


def test_validator_draf_bersih_tetap_lolos():
    """Spec tanpa config mati tidak terdampak (regresi positif)."""
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

