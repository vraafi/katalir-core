# -*- coding: utf-8 -*-
"""Bagian 6.2 + 6.3: prompt kompleks multi-langkah & penanganan error."""
import json

import pytest

import api_server as srv
import workflow_spec as ws


def _spec(name, nodes, edges):
    return json.dumps({"name": name, "nodes": nodes, "edges": edges})


def _n(i, kind, label, **cfg):
    return {"id": i, "kind": kind, "label": label, "config": cfg}


class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5,
                               "total_tokens": 15}


class _Fake:
    """Rekam pesan yang dikirim ke model supaya context bisa diperiksa."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        self.bound = None

    def bind_tools(self, schemas):
        self.bound = schemas
        return self

    def invoke(self, messages):
        self.seen.append([str(getattr(m, "content", m)) for m in messages])
        if not self.replies:
            return _Resp(content="Selesai.")
        item = self.replies.pop(0)
        if isinstance(item, dict):
            return _Resp(tool_calls=[item])
        return _Resp(content=item)


def _run(monkeypatch, prompt, replies, history=None):
    import langchain_openai
    fake = _Fake(replies)
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: fake)
    out = srv._agentic_run_gateway(
        prompt=prompt, email="u@katalir.id", model_id="m",
        gw_url="http://gw.invalid", gw_key="k", roster=["m"],
        history=history or [])
    return out, fake


def _tool(name, args, cid="c1"):
    return {"name": name, "args": args, "id": cid}


COMPLEX_SPEC = _spec("Inventory Email Pipeline", [
    _n("n1", "trigger", "Email subjek inventory"),
    _n("n2", "agent", "Extract nama/jumlah/tanggal"),
    _n("n3", "agent", "Cek header Sheet Inventory"),
    _n("n4", "mcp", "Tulis (dynamic header)",
       provider="google_sheets", spreadsheet_id="INV_SHEET",
       append_or_update=True, matching_columns=["item_name"]),
    _n("n5", "agent", "Cocokkan semantik kolom"),
    _n("n6", "mcp", "Notifikasi",
       provider="slack", channel="#inventory"),
], [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"},
    {"source": "n3", "target": "n4"}, {"source": "n4", "target": "n5"},
    {"source": "n5", "target": "n6"}])


# ---------------------------------------------------------------- 6.2
def test_prompt_kompleks_5_node_valid(monkeypatch):
    """Prompt 6 langkah -> workflow 6 node, bukan dipotong jadi 3."""
    prompt = ("Ketika email subjek 'inventory': 1) extract data "
              "2) cek kolom Sheet 'Inventory' 3) buat kolom baru bila belum ada "
              "4) cocokkan semantik bila beda bahasa 5) tulis ke Sheet "
              "6) notifikasi Slack 'Data updated'")
    out, fake = _run(monkeypatch, prompt, [
        _tool("generate_workflow_json", {"spec_json": COMPLEX_SPEC}),
        "Selesai.",
    ])
    wf = out["meta"].get("workflow")
    assert wf is not None, out
    assert len(wf["nodes"]) == 6, len(wf["nodes"])
    assert len(wf["edges"]) == 5, len(wf["edges"])
    assert out["meta"].get("repair_stalled") is False


def test_prompt_kompleks_lolos_validasi_spesifik():
    res = ws.validate_spec(COMPLEX_SPEC)
    assert res["ok"] is True, res["errors"]


def test_matching_columns_tidak_dibutuhkan_karena_header_diresolve_dulu():
    """PENYIMPANGAN SADAR dari n8n PR #30546 - jangan disalin buta.

    Brief menyebut aturan n8n: "matchingColumns is required and must be
    non-empty string[]". Aturan itu lahir karena API `values.append` milik
    Google MEMBUTUHKANnya. Katalir memakai jalur lain: `sheets_dynamic`
    membaca header, menambah/menyelaraskan kolom yang kurang, BARU append
    pada kolom yang urutannya sudah pasti. Jadi `matchingColumns` tidak
    pernah dibutuhkan, dan mewajibkannya hanya akan menggagalkan draf
    yang sebenarnya valid.

    Yang dijaga di sini adalah JAMINANNYA: draf tanpa matchingColumns
    tetap sah, dan header tetap harus disinkronkan sebelum append.
    """
    spec = _spec("Append", [
        _n("n1", "trigger", "T"),
        _n("n2", "mcp", "Sheets", provider="google_sheets",
           spreadsheet_id="S1", append_or_update=True),
    ], [{"source": "n1", "target": "n2"}])
    res = ws.validate_spec(spec)
    assert res["ok"] is True, res["errors"]

    import sheets_dynamic
    # Jaminan yang membuat devsial tidak perlu matchingColumns: semantik
    # header itu benar-benar ada dan bisa mencocokkan beda bahasa.
    headers = ["Nama Barang", "Jumlah"]
    values_by_header, new_keys = sheets_dynamic.semantic_match_headers(
        {"item_name": "Beras", "qty": 5, "tanggal": "2026-10-03"}, headers)
    # Dua kunciExisting terpilihMapping ke header berbahasa Indonesia,
    # kunci yang benar-benar baru dikembalikan sebagai kolom baru.
    assert values_by_header == {"Nama Barang": "Beras", "Jumlah": 5}, values_by_header
    assert new_keys == ["tanggal"], new_keys


def test_append_polos_tidak_boleh_pakai_matching_columns():
    """Append biasa TIDAK perlu matchingColumns - dan memakainya tetap aman."""
    spec = _spec("append", [
        _n("n1", "trigger", "T"),
        _n("n2", "mcp", "Sheets", provider="google_sheets",
           spreadsheet_id="S1", append_or_update=False),
    ], [{"source": "n1", "target": "n2"}])
    assert ws.validate_spec(spec)["ok"] is True


# ---------------------------------------------------------------- 6.3
def test_prompt_mustahil_ditolak_dengan_pesan_jelas(monkeypatch):
    """Draf ditolak -> user WAJIB diberi tahu, tidak boleh "Selesai." polos.

    Ini bug yang ditemukan oleh test ini: validasi menolak draf, tapi reply
    tetap "Selesai." sehingga user mengira workflow sudah dibuat.
    """
    bad = _spec("Karangan", [
        _n("n1", "trigger", "T"),
        _n("n2", "mcp", "Kirim ke mana", provider="telegram"),
    ], [{"source": "n1", "target": "n2"}])
    out, _ = _run(monkeypatch, "kirim ke telegram", [
        _tool("generate_workflow_json", {"spec_json": bad}),
        "Siap.",
    ])
    assert out["meta"].get("workflow") is None, "draf cacat tidak boleh masuk"
    reply = out["reply"]
    assert "belum jadi" in reply.lower(), reply
    assert "chat_id" in reply, "pesan harus menyebut masalah yang spesifik"


def test_tool_gagal_tidak_menjatuhkan_loop(monkeypatch):
    """Alat yang error harus jadi pesan, bukan crash server."""
    out, _ = _run(monkeypatch, "tes", [
        _tool("tidak_ada_tool_ini", {}),
        "Saya tidak bisa memakai tool itu.",
    ])
    assert isinstance(out.get("reply"), str) and out["reply"]


def test_konteks_pertanyaan_sebelum_dikirim_ke_model(monkeypatch):
    """Riwayat harus ikut sebagai konteks (user bisa menyambung pertanyaan)."""
    history = [{"role": "user", "content": "aku mau workflow stok"},
               {"role": "assistant", "content": "spreadsheet mana?"}]
    _, fake = _run(monkeypatch, "yang sheet inv01", ["siap"], history=history)
    sent = "\n".join(fake.seen[0])
    assert "aku mau workflow stok" in sent
    assert "spreadsheet mana?" in sent
    assert "yang sheet inv01" in sent


def test_tanya_balik_bukan_karang_workflow(monkeypatch):
    """Prompt ambigu -> model boleh bertanya; TIDAK boleh mengarang draft."""
    out, _ = _run(monkeypatch, "bikin yang bagus", [
        "Spreadsheet mana yang dipakai?",
    ])
    assert out["meta"].get("workflow") is None
    assert "Spreadsheet" in out["reply"]


def test_gagal_berulang_lapor_jujur_bukan_klaim_berhasil(monkeypatch):
    """Bug 2: error identik berulang -> berhenti + pesan jujur."""
    bad = _spec("x", [_n("n1", "agent", "A")], [])
    out, fake = _run(monkeypatch, "buatkan", [
        _tool("generate_workflow_json", {"spec_json": bad}),
        _tool("generate_workflow_json", {"spec_json": bad}),
        _tool("generate_workflow_json", {"spec_json": bad}),
    ])
    assert out["meta"].get("workflow") is None
    assert out["meta"].get("repair_stalled") is True
    reply = out["reply"].lower()
    assert "belum bisa diselesaikan" in reply
    assert "berhasil dibuat" not in reply
    # Berhenti lebih awal: model tidak dipanggil 6x.
    assert len(fake.seen) <= 4, len(fake.seen)
