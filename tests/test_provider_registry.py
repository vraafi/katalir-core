# tests/test_provider_registry.py
"""FASE 2.6 — node MCP `config.provider` -> tool native.

Regresi nyata yang dijaga: executor MCP dulu mengabaikan `config.provider` dan
default ke `web_search`, sehingga workflow "kirim Telegram" tidak pernah
mengirim Telegram. Test ini mengunci pemetaan, adapter argumen, dan aturan
"provider tak dikenal = error eksplisit" (bukan fallback senyap).
"""
import asyncio
import dataclasses
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import provider_registry as pr  # noqa: E402
import tools  # noqa: E402


def _patch_provider(monkeypatch, name: str, fake) -> None:
    """Ganti fungsi provider TANPA memutasi registry (ProviderSpec frozen).

    Immutability sengaja dipertahankan: tabel provider hanya boleh berubah
    lewat kode, bukan lewat runtime. Test membangun spec baru dengan `replace`.
    """
    monkeypatch.setitem(pr.PROVIDERS, name,
                        dataclasses.replace(pr.PROVIDERS[name], fn=fake))


# ---------------------------------------------------------------------------
# Registry & resolusi nama
# ---------------------------------------------------------------------------
def test_tujuh_provider_terdaftar():
    assert set(pr.PROVIDERS) == {"telegram", "slack", "http", "gmail",
                                 "google_sheets", "whatsapp", "google_calendar"}
    listed = {p["name"] for p in pr.list_providers()}
    assert listed == set(pr.PROVIDERS)


def test_resolve_menerima_alias():
    assert pr.resolve({"provider": "sheet"}) == "google_sheets"
    assert pr.resolve({"provider": "tg"}) == "telegram"
    assert pr.resolve({"provider": "TELEGRAM"}) == "telegram"
    assert pr.resolve({"provider": "calendar"}) == "google_calendar"


def test_resolve_tanpa_provider_mengembalikan_none():
    # Tanpa provider, pemanggil memakai jalur lama (web_search) — sengaja.
    assert pr.resolve({}) is None
    assert pr.resolve({"tool_name": "web_search"}) is None


def test_provider_tak_dikenal_error_eksplisit_bukan_fallback():
    out = pr.run("zapier", {}, {}, "u@katalir.id")
    assert out["status"] == "error"
    assert out["tool"] is None
    assert "belum terdaftar" in out["error"]
    assert "telegram" in out["error"]        # daftar provider disebut


# ---------------------------------------------------------------------------
# Adapter argumen
# ---------------------------------------------------------------------------
def test_telegram_memakai_config_dan_email_owner(monkeypatch):
    seen = {}

    def fake(chat_id, pesan, email):
        seen.update(chat_id=chat_id, pesan=pesan, email=email)
        return "terkirim"

    _patch_provider(monkeypatch, "telegram", fake)
    out = pr.run("telegram", {"chat_id": "-1001", "pesan": "halo"}, {}, "budi@k.id")
    assert out["status"] == "success" and out["result"] == "terkirim"
    assert seen == {"chat_id": "-1001", "pesan": "halo", "email": "budi@k.id"}


def test_teks_pesan_diambil_dari_node_sebelumnya(monkeypatch):
    seen = {}
    _patch_provider(monkeypatch, "telegram",
                    lambda chat_id, pesan, email: seen.update(p=pesan) or "ok")
    pr.run("telegram", {"chat_id": "-1"}, {"instruction": "Ringkasan harian"}, "u@k.id")
    assert seen["p"] == "Ringkasan harian"


def test_config_menang_atas_input_node_sebelumnya(monkeypatch):
    seen = {}
    _patch_provider(monkeypatch, "slack",
                    lambda channel, pesan, email: seen.update(c=channel, p=pesan) or "ok")
    pr.run("slack", {"channel": "#laporan", "pesan": "dari config"},
           {"instruction": "dari input"}, "u@k.id")
    assert seen == {"c": "#laporan", "p": "dari config"}


def test_adapter_variasi_nama_field():
    args = pr.build_args("gmail", {"to": "a@b.c", "subject": "S", "text": "isi"}, {}, "u@k.id")
    assert args == {"tujuan": "a@b.c", "subjek": "S", "isi": "isi", "email": "u@k.id"}
    args2 = pr.build_args("http", {"endpoint": "https://x.id", "method": "post"}, {}, "u@k.id")
    assert args2["url"] == "https://x.id" and args2["method"] == "POST"


def test_slack_default_channel_dan_telegram_chat_id_kosong():
    assert pr.build_args("slack", {}, {}, "u@k.id")["channel"] == "#umum"
    assert pr.build_args("telegram", {}, {}, "u@k.id")["chat_id"] == ""



# ---------------------------------------------------------------------------
# Jalur kegagalan: kredensial hilang, error runtime, SSRF
# ---------------------------------------------------------------------------
def test_kredensial_hilang_jadi_needs_credential(monkeypatch):
    def boom(**kwargs):
        raise tools.CredentialMissingError("telegram")

    _patch_provider(monkeypatch, "telegram", lambda chat_id, pesan, email: boom())
    out = pr.run("telegram", {"chat_id": "-1", "pesan": "x"}, {}, "u@k.id")
    assert out["status"] == "needs_credential"
    assert out["credential"] == "telegram"
    assert out["provider"] == "telegram"


def test_error_tool_tidak_melempar(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("Telegram menolak permintaan (HTTP 401).")

    _patch_provider(monkeypatch, "telegram", lambda chat_id, pesan, email: boom())
    out = pr.run("telegram", {"chat_id": "-1", "pesan": "x"}, {}, "u@k.id")
    assert out["status"] == "error"
    assert "401" in out["error"]


def test_http_provider_menolak_alamat_internal():
    out = pr.run("http", {"url": "http://127.0.0.1:8000/admin"}, {}, "u@k.id")
    assert out["status"] == "error"
    assert "SSRF" in out["error"]


def test_run_async_sama_hasilnya(monkeypatch):
    _patch_provider(monkeypatch, "telegram", lambda chat_id, pesan, email: "ok-async")
    out = asyncio.run(pr.run_async("telegram", {"chat_id": "-1", "pesan": "x"}, {}, "u@k.id"))
    assert out["status"] == "success" and out["result"] == "ok-async"



# ---------------------------------------------------------------------------
# Integrasi mesin eksekusi (`_exec_mcp`)
# ---------------------------------------------------------------------------
def _node(config: dict):
    import execution_engine as ee
    return ee.FlowNode(id="m1", position={"x": 0, "y": 0},
                       data=ee.FlowNodeData(kind="mcp", label="Kirim", config=config))


def _orch(owner: str = "u@katalir.id"):
    import execution_engine as ee
    graph = ee.FlowGraph(nodes=[_node({"provider": "telegram"})], edges=[])
    return ee.StatefulOrchestrator(graph, owner_email=owner)


async def _fake(seen: dict, provider: str, email: str) -> dict:
    seen.update(provider=provider, email=email)
    return {"status": "success", "provider": provider,
            "tool": "kirim_telegram_message", "result": "terkirim"}


def test_exec_mcp_merutekan_ke_provider_native(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(pr, "run_async",
                        lambda provider, cfg, params, email: _fake(seen, provider, email))
    out = asyncio.run(_orch()._exec_mcp(_node({"provider": "telegram", "chat_id": "-9"}),
                                        {"instruction": "pesan dari agent"}))
    assert out["type"] == "mcp.call"
    assert out["provider"] == "telegram"
    assert out["tool"] == "kirim_telegram_message"
    assert seen["provider"] == "telegram"
    assert seen["email"] == "u@katalir.id"      # owner diteruskan ke tool
    assert out["tool"] != "web_search", "masih jatuh ke web_search"


# ---------------------------------------------------------------------------
# Kelengkapan config (FASE 2.6 lanjutan)
# ---------------------------------------------------------------------------
def test_tujuan_wajib_di_config_bukan_dari_hulu():
    assert pr.missing_required("telegram", {"provider": "telegram"}) == ["chat_id"]
    assert pr.missing_required("http", {}) == ["url"]
    assert pr.missing_required("slack", {"provider": "slack"}) == ["channel"]


def test_konten_boleh_datang_dari_node_hulu():
    """Agent -> Telegram yang sah: teks belum ada saat validasi draf."""
    assert pr.missing_required("telegram", {"chat_id": "-1"}, None, True) == []


def test_konten_wajib_bila_node_tidak_punya_hulu():
    assert pr.missing_required("telegram", {"chat_id": "-1"}, None, False) == ["pesan"]


def test_alias_field_dihormati_saat_validasi():
    assert pr.missing_required("telegram", {"chatId": "-1", "message": "hi"}, None, False) == []
    assert pr.missing_required("http", {"endpoint": "https://x.id"}, None, False) == []


def test_run_memberi_needs_configuration_bukan_http_400():
    out = pr.run("telegram", {"provider": "telegram"}, {}, "u@katalir.id")
    assert out["status"] == "needs_configuration"
    assert out["missing"] == ["chat_id"]
    assert "belum lengkap" in out["error"]


def test_validator_menolak_draf_mcp_tanpa_tujuan():
    import workflow_spec as ws
    import json

    raw = json.dumps({"name": "x", "nodes": [
        {"id": "t", "kind": "trigger"},
        {"id": "m", "kind": "mcp", "config": {"provider": "telegram"}}],
        "edges": [{"source": "t", "target": "m"}]})
    res = ws.validate_spec(raw)
    assert res["ok"] is False
    assert any("chat_id" in e for e in res["errors"]), res


def test_exec_mcp_tanpa_provider_tetap_kompatibel():
    """Workflow lama (tool_name/web_search, tanpa provider) harus tetap jalan."""
    out = asyncio.run(_orch()._exec_mcp(_node({"tool_name": "web_search"}),
                                        {"query": ""}))
    assert out["type"] == "mcp.call"
    assert out["tool"] == "web_search"
    assert out["result"]["status"] == "error"   # query kosong -> gagal (jujur)


def test_owner_email_sampai_ke_orchestrator():
    import execution_engine as ee
    graph = ee.FlowGraph(nodes=[_node({"provider": "telegram"})], edges=[])
    assert ee.StatefulOrchestrator(graph, owner_email="verdi@k.id").owner_email == "verdi@k.id"
    assert ee.StatefulOrchestrator(graph).owner_email == ""
