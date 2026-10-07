"""test_delegation.py — BUG #3: delegasi multi-agent (brief 7 Okt 2026).

Sebelumnya node "Supervisor"/"Research"/"Writer" hanyalah agent berderet tanpa
delegasi (skenario S5). Kini node agent dengan `config.role='supervisor'`
(boleh juga `delegates`) mendelegasikan tugas ke agent lain lewat direktif
`[DELEGATE: agent_id=<id> task="..."]` (atau JSON), lalu merangkai hasilnya.
"""
import asyncio
import json

import execution_engine as ee


def _graph(supervisor_cfg):
    return ee.FlowGraph(
        nodes=[
            {"id": "t", "type": "trigger",
             "data": {"kind": "trigger", "label": "Manual", "config": {}}},
            {"id": "sup", "type": "agent",
             "data": {"kind": "agent", "label": "Supervisor",
                      "config": supervisor_cfg}},
            {"id": "research", "type": "agent",
             "data": {"kind": "agent", "label": "Research",
                      "config": {"prompt": "riset"}}},
            {"id": "writer", "type": "agent",
             "data": {"kind": "agent", "label": "Writer",
                      "config": {"prompt": "tulis"}}},
        ],
        # Sub-agent punya edge masuk dari supervisor (bentuk workflow nyata
        # "Supervisor -> Research -> Writer").
        edges=[{"source": "t", "target": "sup"},
               {"source": "sup", "target": "research"},
               {"source": "research", "target": "writer"}],
    )


def _reasoner_scripted(responses):
    """Reasoner palsu: balasan sesuai urutan; sub-agent balas terpisah."""
    calls = {"n": 0, "prompts": []}

    async def _fake(prompt, user_input, config=None):
        calls["prompts"].append(prompt)
        # Sub-agent dipanggil dengan _from='delegate'
        if user_input.get("_from") == "delegate":
            return {"status": "success",
                    "reply": f"HASIL[{config.get('prompt') or 'sub'}]",
                    "model": "tes", "usage": {}, "cost_usd": 0.0}
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return {"status": "success", "reply": responses[idx], "model": "tes",
                "usage": {}, "cost_usd": 0.0}

    return calls, _fake


def test_supervisor_mendelegasikan_ke_sub_agent():
    responses = [
        '[DELEGATE: agent_id=research task="cari info AI terbaru"]',
        "Ringkasan akhir: AI berkembang pesat.",
    ]
    calls, fake = _reasoner_scripted(responses)
    orch = ee.StatefulOrchestrator(
        _graph({"role": "supervisor", "prompt": "koordinasikan",
                "delegates": ["research", "writer"]}),
        trigger_input={}, reasoner=fake)
    asyncio.run(orch.run())
    out = orch.outputs["sup"]
    assert out.get("role") == "supervisor", out
    assert out.get("delegated_count") == 1, out
    assert out["delegations"][0]["agent_id"] == "research", out["delegations"]
    assert "HASIL" in out["delegations"][0]["reply"], out["delegations"]
    assert "Ringkasan akhir" in out["instruction"], out


def test_supervisor_delegasi_dua_agent():
    responses = [
        '[DELEGATE: agent_id=research task="riset AI"]\n'
        '[DELEGATE: agent_id=writer task="tulis ringkasan"]',
        "Selesai.",
    ]
    calls, fake = _reasoner_scripted(responses)
    orch = ee.StatefulOrchestrator(
        _graph({"role": "supervisor", "prompt": "koord",
                "delegates": ["research", "writer"]}),
        trigger_input={}, reasoner=fake)
    asyncio.run(orch.run())
    out = orch.outputs["sup"]
    ids = [d["agent_id"] for d in out["delegations"]]
    assert ids == ["research", "writer"], ids


def test_supervisor_tanpa_delegasi_selesai_langsung():
    calls, fake = _reasoner_scripted(["Jawaban langsung tanpa delegasi."])
    orch = ee.StatefulOrchestrator(
        _graph({"role": "supervisor", "prompt": "jawab"}),
        trigger_input={}, reasoner=fake)
    asyncio.run(orch.run())
    out = orch.outputs["sup"]
    assert out.get("delegated_count") == 0, out
    assert "Jawaban langsung" in out["instruction"], out


def test_parse_delegations_bentuk_json():
    out = ee.StatefulOrchestrator._parse_delegations(
        '{"delegate":[{"agent_id":"research","task":"riset"}]}', ["research"])
    assert out == [("research", "riset")], out


def test_delegasi_ke_agent_tak_ada_mencatat_error():
    responses = ['[DELEGATE: agent_id=hantu task="x"]', "selesai"]
    calls, fake = _reasoner_scripted(responses)
    orch = ee.StatefulOrchestrator(
        _graph({"role": "supervisor", "prompt": "k"}), trigger_input={},
        reasoner=fake)
    asyncio.run(orch.run())
    d = orch.outputs["sup"]["delegations"][0]
    assert d["status"] == "error", d


def test_supervisor_menerima_hasil_delegasi_di_putaran_berikut():
    """Transcript hasil delegasi harus sampai ke putaran supervisor ke-2."""
    seen = {}

    async def _fake(prompt, user_input, config=None):
        if user_input.get("_from") == "delegate":
            return {"status": "success", "reply": "DATA-RISET-123",
                    "model": "tes", "usage": {}, "cost_usd": 0.0}
        if user_input.get("delegation_results"):
            seen["saw_results"] = user_input["delegation_results"]
            return {"status": "success", "reply": "final", "model": "tes",
                    "usage": {}, "cost_usd": 0.0}
        return {"status": "success",
                "reply": '[DELEGATE: agent_id=research task="cari"]',
                "model": "tes", "usage": {}, "cost_usd": 0.0}

    orch = ee.StatefulOrchestrator(
        _graph({"role": "supervisor", "prompt": "k", "delegates": ["research"]}),
        trigger_input={}, reasoner=_fake)
    asyncio.run(orch.run())
    assert seen.get("saw_results"), "hasil delegasi tidak diteruskan"
    assert "DATA-RISET-123" in json.dumps(seen["saw_results"], ensure_ascii=False)
