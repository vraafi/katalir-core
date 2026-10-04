# -*- coding: utf-8 -*-
"""Bagian 6.1: 10 prompt sederhana end-to-end lewat jalur gateway sungguhan.

Yang diuji BUKAN kemampuan model menulis spec (itu butuh API key), tapi
LANGKAH PRODUKSI: tool call -> eksekusi -> validasi -> workflow masuk
`meta.workflow`. Kalau salah satu putus, user melihat JSON mentah atau
"Selesai." tanpa workflow di canvas - itu kelemahan n8n #9.

Catatan kejujuran: spec di fixture ditulis tangan sesuai provider yang
diminta tiap prompt. Test ini membuktikan pipeline kita benar, BUKAN
bahwa model selalu menghasilkan spec seperti ini.
"""
import json

import pytest

import api_server as srv


def _spec(name, nodes, edges):
    return json.dumps({"name": name, "nodes": nodes, "edges": edges})


# (prompt, nama workflow, provider, config wajib provider)
CASES = [
    ("Kirim email ke tim setiap Jumat jam 5 sore",
     "Email Jumat 17:00", "gmail",
     {"tujuan": "tim@corp.co", "subjek": "Rekap Mingguan"}),
    # Gmail adalah SUMBER data (bukan node mcp tujuan); node mcp di sini
    # adalah aksi tujuannya, yaitu menulis ke Sheets.
    ("Ambil 10 email terbaru dari Gmail, tulis ke Sheets",
     "Gmail to Sheets", "google_sheets",
     {"spreadsheet_id": "SHEET_ID_1"}),
    ("Setiap jam 9 pagi, cek cuaca Jakarta, kirim ke Slack",
     "Cuaca ke Slack", "slack", {"channel": "#alerts"}),
    ("Ketika form submission baru, tambahkan ke Sheets",
     "Form to Sheets", "google_sheets", {"spreadsheet_id": "SHEET_ID_2"}),
    ("Setiap hari jam 8, kirim ringkasan berita ke Telegram",
     "Berita ke Telegram", "telegram", {"chat_id": "12345"}),
    ("Baca RSS feed, filter 24 jam, posting ke X",
     "RSS ke X", "http",
     {"url": "https://api.x.com/2/tweets", "method": "POST"}),
    ("Ketika stok inventory < 10, kirim alert ke WhatsApp",
     "Alert Stok Menipis", "whatsapp", {"nomor_tujuan": "628123456789"}),
    ("Setiap minggu, backup data dari Airtable ke Drive",
     "Backup Mingguan", "http",
     {"url": "https://www.googleapis.com/drive/v3/files", "method": "POST"}),
    ("Ketika email subjek 'invoice', extract ke Sheets",
     "Invoice ke Sheets", "google_sheets", {"spreadsheet_id": "SHEET_ID_3"}),
    ("Setiap jam, cek API status, jika down kirim notifikasi",
     "Status Monitor", "telegram", {"chat_id": "12345"}),
]


def _build(name, provider, cfg):
    return _spec(name, [
        {"id": "n1", "kind": "trigger", "label": "Pemicu", "config": {}},
        {"id": "n2", "kind": "agent", "label": "Proses", "config": {}},
        {"id": "n3", "kind": "mcp", "label": "Kirim",
         "config": dict({"provider": provider}, **cfg)},
    ], [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"}])


class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5,
                               "total_tokens": 15}


class _Fake:
    """Panggilan 1 meminta tool, panggilan 2 menjawab ringkasan."""

    def __init__(self, spec):
        self.spec = spec
        self.i = 0
        self.bound = None

    def bind_tools(self, schemas):
        self.bound = schemas
        return self

    def invoke(self, messages):  # noqa: ARG002
        self.i += 1
        if self.i == 1:
            return _Resp(tool_calls=[{"name": "generate_workflow_json",
                                      "args": {"spec_json": self.spec},
                                      "id": "c1"}])
        return _Resp(content="Workflow sudah dibuat.")


def _run(monkeypatch, prompt, spec):
    import langchain_openai
    # Test ini sengaja menguji jalur NATIVE (`tool_calls` terstruktur),
    # jadi jalur native dinyalakan lewat flag. Default produksi adalah MATI
    # karena gateway menolak payload `tools` dengan 500 (lihat
    # `_send_tools_param` di api_server.py).
    monkeypatch.setenv("KATALIR_SEND_TOOLS", "1")
    fake = _Fake(spec)
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: fake)
    out = srv._agentic_run_gateway(
        prompt=prompt, email="u@katalir.id", model_id="m",
        gw_url="http://gw.invalid", gw_key="k", roster=["m"], history=[])
    return out, fake


@pytest.mark.parametrize("idx", range(10))
def test_prompt_sederhana_jadi_workflow_valid(monkeypatch, idx):
    prompt, name, provider, cfg = CASES[idx]
    spec = _build(name, provider, cfg)
    out, fake = _run(monkeypatch, prompt, spec)
    wf = out["meta"].get("workflow")
    assert wf is not None, f"prompt {idx + 1} tidak menghasilkan workflow: {out}"
    assert len(wf["nodes"]) == 3, f"prompt {idx + 1}: {wf['nodes']}"
    assert len(wf["edges"]) == 2, f"prompt {idx + 1}: {wf['edges']}"
    # n8n #9: tool DIEKSEKUSI -> canvas dapat workflow, reply bukan JSON mentah.
    assert fake.bound is not None, "tool schema tidak ditempel ke model"
    assert "{\"nodes\"" not in out["reply"], out["reply"]


def test_10_prompt_terdaftar_dan_unik():
    assert len(CASES) == 10
    assert len({c[0] for c in CASES}) == 10


def test_semua_prompt_diproses_di_bawah_120_detik(monkeypatch):
    """n8n #1: target <120 detik. Diukur untuk 10 prompt."""
    import time
    worst = 0.0
    for prompt, name, provider, cfg in CASES:
        t0 = time.time()
        out, _ = _run(monkeypatch, prompt, _build(name, provider, cfg))
        worst = max(worst, time.time() - t0)
        assert out["meta"].get("workflow") is not None, prompt
    assert worst < 120.0, f"terlalu lambat: {worst:.1f}s"


def test_provider_tanpa_config_wajib_ditolak():
    """Spec yang menebak-nebak tujuan harus ditolak, bukan dikirim."""
    bad = _spec("Menebak", [
        {"id": "n1", "kind": "trigger", "label": "P", "config": {}},
        {"id": "n2", "kind": "mcp", "label": "Kirim",
         "config": {"provider": "telegram"}},
    ], [{"source": "n1", "target": "n2"}])
    import workflow_spec as ws
    res = ws.validate_spec(bad)
    assert res["ok"] is False
    assert any("chat_id" in e for e in res["errors"]), res
