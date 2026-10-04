# tests/test_discovery_agent_live_loop.py
"""FASE 2.1 — integrasi loop tool: tool_calls -> execute_tool -> meta.workflow.

TANPA jaringan: model diganti objek palsu yang meniru respons LangChain
(attribute `tool_calls`, `content`, `usage_metadata`). Yang diuji adalah kabel
di `_agentic_run_gateway`: apakah draf workflow yang diterima alat benar-benar
sampai ke `meta.workflow` (kalau tidak, canvas akan selalu kosong walau agen
"berhasil" membangun workflow).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api_server as srv  # noqa: E402

SPEC = json.dumps({
    "name": "Kirim Telegram 09:00",
    "nodes": [
        {"id": "trg", "kind": "trigger", "config": {"schedule": "0 9 * * *"}},
        {"id": "tg", "kind": "mcp", "config": {"provider": "telegram",
                                              "chat_id": "-1001"}},
    ],
    "edges": [{"source": "trg", "target": "tg"}],
})


class _Resp:
    def __init__(self, content="", tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = usage or {"input_tokens": 10, "output_tokens": 5,
                                       "total_tokens": 15}


class _FakeModel:
    """Panggilan pertama minta tool; panggilan kedua menjawab ringkasan."""

    def __init__(self, args):
        self.args = args
        self.invokes = 0
        self.bound_schemas = None

    def bind_tools(self, schemas):
        self.bound_schemas = schemas
        return self

    def invoke(self, messages):  # noqa: ARG002
        self.invokes += 1
        if self.invokes == 1:
            return _Resp(tool_calls=[{
                "name": "generate_workflow_json",
                "args": self.args,
                "id": "call-1",
            }])
        return _Resp(content="Workflow 2 node sudah dibuat.")


def _run(monkeypatch, args) -> dict:
    """Jalankan jalur gateway dengan ChatOpenAI diganti model palsu.

    Seam-nya adalah kelas `ChatOpenAI` (bukan `_bound`, yang merupakan closure
    di dalam fungsi): `_agentic_run_gateway` mengimpornya di dalam fungsi, jadi
    menambal modul `langchain_openai` menangkap semua pembuatan klien.
    """
    import langchain_openai

    fake = _FakeModel(args)
    # Jalur native diuji di sini; nyalakan lewat flag (default produksi MATI,
    # gateway menolak payload `tools` dengan HTTP 500).
    monkeypatch.setenv("KATALIR_SEND_TOOLS", "1")
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kwargs: fake)
    out = srv._agentic_run_gateway(
        prompt="bikin workflow kirim telegram tiap jam 9",
        email="u@katalir.id",
        model_id="m", gw_url="http://gw.invalid", gw_key="k",
        roster=["m"], history=[],
    )
    assert fake.bound_schemas is not None, "tool schema tidak ditempel ke model"
    return out


def test_draf_diterima_muncul_di_meta_workflow(monkeypatch):
    out = _run(monkeypatch, {"spec_json": SPEC, "summary": "kirim telegram"})
    wf = out["meta"].get("workflow")
    assert wf is not None, out
    assert wf["name"] == "Kirim Telegram 09:00"
    assert [n["type"] for n in wf["nodes"]] == ["trigger", "mcp"]
    assert len(wf["edges"]) == 1
    assert out["reply"] == "Workflow 2 node sudah dibuat."


def test_draf_ditolak_tidak_mengisi_canvas(monkeypatch):
    bad = json.dumps({"name": "rusak", "nodes": [{"id": "a", "kind": "agent"}]})
    out = _run(monkeypatch, {"spec_json": bad})
    assert out["meta"].get("workflow") is None, out


def test_tanpa_draf_workflow_none_bukan_error(monkeypatch):
    # Argumen salah nama -> alat mengembalikan penolakan, bukan exception.
    out = _run(monkeypatch, {"spec_json": ""})
    assert out["meta"]["workflow"] is None
    assert out["reply"]
