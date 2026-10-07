"""test_condition_eval.py — BUG #1: evaluasi kondisi IF/ELSE (brief 7 Okt 2026).

Sebelumnya `config.condition` tidak pernah dibaca runner -> semua node jalan
linear, tidak ada percabangan, tidak ada error (bukti: skenario S1 adversarial).
Kini node dengan `condition` yang tidak terpenuhi DILEWATI (status=skipped).

Keamanan: evaluator memakai AST whitelist tertutup, TIDAK memakai eval().
"""
import asyncio
import json

import pytest

import execution_engine as ee


# --------------------------------------------------------------- evaluator
def test_eval_perbandingan_sederhana():
    assert ee.evaluate_condition("'valid' == 'valid'") is True
    assert ee.evaluate_condition("'a' == 'b'") is False


def test_eval_numerik():
    assert ee.evaluate_condition("200 == 200") is True
    assert ee.evaluate_condition("500 > 200") is True
    assert ee.evaluate_condition("3 <= 2") is False


def test_eval_and_or_not():
    assert ee.evaluate_condition("true and 1 == 1") is True
    assert ee.evaluate_condition("false or 1 == 1") is True
    assert ee.evaluate_condition("not false") is True


def test_eval_in_operator():
    assert ee.evaluate_condition("'ok' in ['ok', 'valid']") is True
    assert ee.evaluate_condition("'x' not in ['ok']") is True


def test_eval_menolak_pemanggilan_fungsi():
    """Tidak boleh ada call/atribut (bukan sekadar eval() yang dibungkus)."""
    with pytest.raises(ee.ConditionEvaluationError):
        ee.evaluate_condition("__import__('os').system('echo hi')")


def test_eval_menolak_nama_bebas():
    with pytest.raises(ee.ConditionEvaluationError):
        ee.evaluate_condition("status == 'valid'")


def test_eval_menolak_subscript_dan_attribute():
    with pytest.raises(ee.ConditionEvaluationError):
        ee.evaluate_condition("data['x'] == 1")
    with pytest.raises(ee.ConditionEvaluationError):
        ee.evaluate_condition("data.x == 1")


def test_eval_sintaks_rusak_jelas():
    with pytest.raises(ee.ConditionEvaluationError):
        ee.evaluate_condition("== ==")


# --------------------------------------------------------------- runner
def _graph(agent_config, trigger_input=None):
    return ee.FlowGraph(
        nodes=[
            {"id": "t", "type": "trigger",
             "data": {"kind": "trigger", "label": "Manual", "config": {}}},
            {"id": "a", "type": "agent",
             "data": {"kind": "agent", "label": "Kirim",
                      "config": agent_config}},
        ],
        edges=[{"source": "t", "target": "a"}],
    )


def _patch_reason(monkeypatch, captured):
    import agent_reasoner

    async def _fake(prompt, user_input, config=None):
        captured["called"] = captured.get("called", 0) + 1
        captured["prompt"] = prompt
        return {"status": "success", "reply": "terkirim", "model": "tes",
                "usage": {}, "cost_usd": 0.0}

    monkeypatch.setattr(agent_reasoner, "run_agent", _fake)


def test_condition_false_melewati_node(monkeypatch):
    """status=500 -> node di-skip, LLM TIDAK dipanggil."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"condition": "{{data.status}} == 200",
                "prompt": "kirim telegram"},
               trigger_input={"status": 500}),
        trigger_input={"status": 500})
    steps = asyncio.run(orch.run())
    by = {s.node_id: s for s in steps}
    assert by["a"].status == "skipped", [(s.node_id, s.status) for s in steps]
    assert "called" not in cap, "LLM dipanggil padahal kondisi false"
    assert orch.outputs["a"].get("skipped") is True


def test_condition_true_menjalankan_node(monkeypatch):
    """status=200 -> node jalan normal."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"condition": "{{data.status}} == 200",
                "prompt": "kirim telegram"},
               trigger_input={"status": 200}),
        trigger_input={"status": 200})
    steps = asyncio.run(orch.run())
    by = {s.node_id: s for s in steps}
    assert by["a"].status == "completed", [(s.node_id, s.status) for s in steps]
    assert cap.get("called") == 1


def test_else_condition_gerbang_kebalikan(monkeypatch):
    """else_condition juga menggerbang (hanya jalan bila ekspresi truthy)."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"else_condition": "{{data.status}} == 200", "prompt": "x"},
               trigger_input={"status": 500}),
        trigger_input={"status": 500})
    steps = asyncio.run(orch.run())
    assert {s.node_id: s for s in steps}["a"].status == "skipped"


def test_condition_salah_bentuk_memicu_error_jujur(monkeypatch):
    """condition bukan string -> ConditionEvaluationError (bukan silent)."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"condition": 123, "prompt": "x"}), trigger_input={})
    with pytest.raises(Exception) as ei:
        asyncio.run(orch.run())
    assert "ConditionEvaluationError" in str(ei.value) or \
           "condition" in str(ei.value).lower()


def test_condition_string_dari_placeholder_dikutip(monkeypatch):
    """REGRESI (ditemukan saat rerun adversarial): `{{data.status}} == 'valid'`
    harus jadi `'valid' == 'valid'`. Tanpa pengutipan, nilai `valid` menjadi
    nama bebas -> ConditionEvaluationError (S1 gagal)."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"condition": "{{data.status}} == 'valid'", "prompt": "x"},
               trigger_input={"status": "valid"}),
        trigger_input={"status": "valid"})
    steps = asyncio.run(orch.run())
    assert {s.node_id: s for s in steps}["a"].status == "completed", \
        [(s.node_id, s.status) for s in steps]


def test_condition_numerik_tanpa_kutipan(monkeypatch):
    """Angka tidak boleh dikutip: `{{data.count}} > 5` harus tetap numerik."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"condition": "{{data.count}} > 5", "prompt": "x"},
               trigger_input={"count": 10}),
        trigger_input={"count": 10})
    steps = asyncio.run(orch.run())
    assert {s.node_id: s for s in steps}["a"].status == "completed"

    orch2 = ee.StatefulOrchestrator(
        _graph({"condition": "{{data.count}} > 5", "prompt": "x"},
               trigger_input={"count": 3}),
        trigger_input={"count": 3})
    steps2 = asyncio.run(orch2.run())
    assert {s.node_id: s for s in steps2}["a"].status == "skipped"


def test_condition_dengan_placeholder_field_hilang_jujur(monkeypatch):
    """Placeholder ke field yang tidak ada -> PlaceholderResolutionError."""
    cap: dict = {}
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"condition": "{{data.tidak_ada}} == 'x'", "prompt": "x"},
               trigger_input={"status": 200}),
        trigger_input={"status": 200})
    with pytest.raises(Exception) as ei:
        asyncio.run(orch.run())
    assert "PlaceholderResolutionError" in str(ei.value)
