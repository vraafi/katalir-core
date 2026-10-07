"""test_split_batches.py — BUG #4: Split In Batches + isolasi antar item.

Brief 7 Okt 2026: node dengan `config.batch_size` membaca array input, memecah
jadi batch, dan menjalankan node SEKALI PER BATCH dengan konteks TERISOLASI
(jawaban item B tidak boleh dipengaruhi item A).

Sebelumnya `batch_size` disimpan tapi tidak pernah dibaca (skenario S2).
"""
import asyncio

import execution_engine as ee


def _graph(agent_config, trigger_input):
    return ee.FlowGraph(
        nodes=[
            {"id": "t", "type": "trigger",
             "data": {"kind": "trigger", "label": "Manual", "config": {}}},
            {"id": "a", "type": "agent",
             "data": {"kind": "agent", "label": "Proses",
                      "config": agent_config}},
        ],
        edges=[{"source": "t", "target": "a"}],
    )


def _patch_reason(monkeypatch, captured):
    import agent_reasoner

    async def _fake(prompt, user_input, config=None):
        # Catat item yang DILIHAT tiap pemanggilan -> bukti isolasi.
        captured.append({"prompt": prompt,
                         "item": user_input.get("item"),
                         "batch": user_input.get("batch")})
        return {"status": "success", "reply": f"jawab:{user_input.get('item')}",
                "model": "tes", "usage": {}, "cost_usd": 0.0}

    monkeypatch.setattr(agent_reasoner, "run_agent", _fake)


def test_batch_memecah_array_jadi_batches(monkeypatch):
    cap: list = []
    _patch_reason(monkeypatch, cap)
    items = ["A", "B"]
    orch = ee.StatefulOrchestrator(
        _graph({"batch_size": 1, "prompt": "jawab {{item}}"}, items),
        trigger_input={"items": items})
    asyncio.run(orch.run())
    out = orch.outputs["a"]
    assert out["type"] == "batch.results", out
    assert out["batch_count"] == 2, out
    assert out["item_count"] == 2, out
    assert len(cap) == 2, f"LLM harus dipanggil 2x (1 per batch), dapat {len(cap)}"


def test_batch_size_2_menghasilkan_1_batch(monkeypatch):
    cap: list = []
    _patch_reason(monkeypatch, cap)
    items = ["A", "B"]
    orch = ee.StatefulOrchestrator(
        _graph({"batch_size": 2, "prompt": "x"}, items),
        trigger_input={"items": items})
    asyncio.run(orch.run())
    out = orch.outputs["a"]
    assert out["batch_count"] == 1, out
    assert out["batch_size"] == 2, out


def test_isolasi_tiap_batch_hanya_melihat_itemnya(monkeypatch):
    """INTI BUG #4: batch B tidak boleh melihat item A."""
    cap: list = []
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"batch_size": 1, "prompt": "jawab {{item}}"}, None),
        trigger_input={"items": ["A", "B"]})
    asyncio.run(orch.run())
    seen = [c["item"] for c in cap]
    assert seen == ["A", "B"], f"item yang dilihat tiap batch salah: {seen}"
    # Tiap batch menerima HANYA itemnya sendiri (list berukuran 1).
    for c in cap:
        assert c["batch"] == [c["item"]], c


def test_batch_tanpa_array_tidak_meledak(monkeypatch):
    """Tidak ada array -> 0 batch, bukan error."""
    cap: list = []
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"batch_size": 1, "prompt": "x"}, None), trigger_input={})
    asyncio.run(orch.run())
    out = orch.outputs["a"]
    assert out["batch_count"] == 0, out
    assert cap == [], "LLM tidak boleh dipanggil bila tidak ada item"


def test_batch_mengembalikan_hasil_per_item(monkeypatch):
    cap: list = []
    _patch_reason(monkeypatch, cap)
    orch = ee.StatefulOrchestrator(
        _graph({"batch_size": 1, "prompt": "jawab {{item}}"}, None),
        trigger_input={"items": ["A", "B"]})
    asyncio.run(orch.run())
    replies = [r["output"].get("instruction") for r in orch.outputs["a"]["results"]]
    assert replies == ["jawab:A", "jawab:B"], replies
