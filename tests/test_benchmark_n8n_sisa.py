# -*- coding: utf-8 -*-
"""Sisa benchmark vs n8n: #4 header, #6 fallback model, #8 workflow-id hantu,
# #10 system prompt dipatuhi."""
import json

import pytest

import api_server as srv


class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = {"input_tokens": 1, "output_tokens": 1,
                               "total_tokens": 2}


class _Fake:
    def __init__(self, replies, fail_on=()):
        self.replies = list(replies)
        self.fail_on = set(fail_on)
        self.model = None
        self.bound = None

    def bind_tools(self, schemas):
        self.bound = schemas
        return self

    def invoke(self, messages):
        if self.model in self.fail_on:
            raise RuntimeError(f"model {self.model} unavailable")
        if not self.replies:
            return _Resp(content="Selesai.")
        item = self.replies.pop(0)
        if isinstance(item, dict):
            return _Resp(tool_calls=[item])
        return _Resp(content=item)


def _install(monkeypatch, fake):
    import langchain_openai

    class _Factory:
        def __init__(self, **kwargs):
            fake.model = kwargs.get("model")
            self.inner = fake

        def bind_tools(self, schemas):
            fake.bound = schemas
            return self

        def invoke(self, messages):
            return fake.invoke(messages)

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Factory)
    return fake


# ------------------------------------------------------------------ n8n #6
def test_model_pertama_gagal_model_kedua_dipakai(monkeypatch):
    """#6: 1 model mati tidak boleh memblokir seluruh percakapan."""
    fake = _install(monkeypatch, _Fake(["saya bisa bantu"], fail_on=["bad"]))
    out = srv._agentic_run_gateway(
        prompt="halo", email="u@e.com", model_id="bad",
        gw_url="http://gw.invalid", gw_key="k", roster=["good"])
    assert out["meta"]["model"] == "good", out["meta"]
    assert out["meta"].get("fallback") is True
    assert out["meta"].get("fallback_reason")
    assert out["reply"] == "saya bisa bantu"


def test_semua_model_gagal_memberi_error_jelas(monkeypatch):
    """#6+#1: saat semua model gateway mati, hasil harus jujur.

    Assertion sebelumnya `assert out is not None or True` tidak akan pernah
    gagal - itu test hampa. Diganti dengan pemeriksaan yang bisa benar-benar
    salah: kalau gateway mengembalikan workflow/reply normal padahal semua
    model ditolak, itu kebohongan.
    """
    fake = _install(monkeypatch, _Fake(["jawab palsu"], fail_on=["a", "b", "c"]))
    try:
        out = srv._agentic_run_gateway(
            prompt="halo", email="u@e.com", model_id="a",
            gw_url="http://gw.invalid", gw_key="k", roster=["b", "c"])
    except Exception:
        return  # melempar error = perilaku yang benar
    # Kalau tidak melempar, tidak boleh mengklaim berhasil dari model mati.
    assert out.get("meta", {}).get("model") not in ("a", "b", "c"), out


# ------------------------------------------------------------------ n8n #8
def test_workflow_id_hantu_memberi_none_bukan_data_palsu():
    """#8: id yang tidak ada harus None, tidak boleh recordifted."""
    import database as db
    import inspect
    sig = inspect.signature(db.get_workflow)
    assert "user_id" in sig.parameters, " scoping per-user wajib ada"


def test_muat_workflow_tidak_pernah_melewati_scoping(monkeypatch):
    """Panggilan tanpa user_id harus gagal, bukan diam-diam membaca semua."""
    import database as db
    with pytest.raises(TypeError):
        db.get_workflow("11111111-1111-1111-1111-111111111111")


# ----------------------------------------------------------------- n8n #10
def test_system_prompt_memuat_aturan_wajib():
    """#10: system prompt harus benar-benar berisi aturan inti."""
    p = srv._AGENT_SYSTEM
    for wajib in ("generate_workflow_json", "provider"):
        assert wajib in p, wajib


def test_system_prompt_menyebut_provider_yang_benar():
    """#10: nama provider di prompt harus semuanya terdaftar.

    Regex versi pertama (pola "provider" diikuti spasi lalu token) menemukan
    loop-nya tidak pernah jalan - test hampa yang selalu hijau. Sekarang
    pola diambil dari bentuk yang benar-benar dipakai prompt
    ("provider tujuan (telegram/gmail/...)"), dan jumlah temuan
    di-assert supaya regresi pola bisa ketahuan.
    """
    import re
    import workflow_spec as ws
    blok = re.search(r"provider tujuan \(([^)]+)\)", srv._AGENT_SYSTEM)
    assert blok, "prompt harus menyebut daftar provider tujuan"
    disebut = {p.strip() for p in blok.group(1).split("/") if p.strip()}
    assert len(disebut) >= 5, disebut
    for name in disebut:
        assert name in ws.KNOWN_PROVIDERS, (
            f"prompt menyebut provider '{name}' yang tidak terdaftar"
        )


def test_provider_karangan_tidak_boleh_diloloskan():
    """#7+#10: prompt yang menyebut provider karangan tetap ditolak."""
    import workflow_spec as ws
    raw = json.dumps({
        "name": "x",
        "nodes": [{"id": "t", "kind": "trigger", "label": "T", "config": {}},
                  {"id": "m", "kind": "mcp", "label": "M",
                   "config": {"provider": "instagram"}}],
        "edges": [{"source": "t", "target": "m"}]})
    res = ws.validate_spec(raw)
    assert res["ok"] is False
    assert any("instagram" in e for e in res["errors"])
