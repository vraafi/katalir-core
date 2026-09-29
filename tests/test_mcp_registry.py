import mcp_registry


def test_catalog_pagination_search_dan_detail():
    mcp_registry.load_cached()
    page = mcp_registry.list_servers(page=1, limit=50)
    assert len(page["items"]) <= 50
    assert page["total"] >= 500
    found = mcp_registry.list_servers(search="slack", limit=5)
    assert found["items"]
    item = found["items"][0]
    assert mcp_registry.get_server(item["id"])["id"] == item["id"]


def test_openconnector_entries_termuat_dengan_status_terpisah():
    """Catalogue entries must be reachable and must not over-claim verification."""
    mcp_registry.load_cached()
    coverage = mcp_registry.openconnector_coverage()
    assert coverage["services"] >= 1000
    assert coverage["actions"] >= 10000
    # the catalogue exposes 5 meta-tools, not one MCP tool per action
    assert coverage["meta_tools"] == 5
    # call_verified can never exceed the catalogue
    assert 0 < coverage["actions_call_verified"] <= coverage["actions"]


def test_openconnector_tidak_ditandai_executable_hanya_karena_metadata():
    """A discovered action must not become 'executable' without a real call.

    The source is pinned explicitly: the catalogue now also holds ~20k Glama
    entries, so positional assumptions about search results are not stable.
    """
    mcp_registry.load_cached()
    page = mcp_registry.list_servers(source="openconnector", search="crossref", limit=5)
    assert page["items"], "openconnector entries must be searchable"
    entry = mcp_registry.get_server(page["items"][0]["id"])
    assert entry["source"] == "openconnector"
    assert entry["install_config"]["transport"] == "mcp-meta-layer"
    unverified = [t for t in entry["tools"] if not t["call_verified"]]
    if unverified:
        assert entry["install_config"]["transport"] not in {"stdio", "http", "sse"}


def test_catalog_menolak_pagination_tidak_aman():
    import pytest
    with pytest.raises(ValueError):
        mcp_registry.list_servers(limit=101)

# tests/test_mcp_registry.py
"""FASE 2.4 — MCP registry native: registry, token, dan SSRF guard.

Yang diuji di sini bukan "apakah Telegram hidup" (butuh token asli), melainkan
kontrak yang bisa merusak produksi tanpa error apa pun:
  * provider terdaftar di KEDUA format schema (Gemini + OpenAI-compatible);
  * token dibaca dari kredensial user dan TIDAK pernah muncul di hasil tool;
  * `http_request` menolak alamat internal (SSRF).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import database as db  # noqa: E402
import tools as t  # noqa: E402

EXPECTED = {
    "send_whatsapp_message", "baca_google_sheets", "kirim_email_gmail",
    "tambah_agenda_calendar", "generate_workflow_json",
    "kirim_telegram_message", "kirim_slack_message", "http_request",
}


def _names_openai():
    return {s["function"]["name"] for s in t.TOOL_SCHEMAS_OPENAI}


def _names_gemini():
    return {d.name for tool in t.TOOL_DECLARATIONS
            for d in (getattr(tool, "function_declarations", None) or [])}


def test_registry_lengkap_di_kedua_format():
    assert EXPECTED <= _names_openai(), EXPECTED - _names_openai()
    assert EXPECTED <= _names_gemini(), EXPECTED - _names_gemini()
    # Minimal 5 MCP provider sesuai target sub-fase.
    assert len(EXPECTED) >= 5


def test_mcp_provider_minimal_lima():
    """Provider yang bisa dipakai workflow: telegram, slack, http, gmail, sheets."""
    import workflow_spec as ws
    providers = {"telegram", "slack", "http", "gmail", "google_sheets"}
    assert providers <= set(ws.KNOWN_PROVIDERS)


def test_telegram_mengirim_payload_benar_tanpa_membocorkan_token(monkeypatch):
    captured = {}

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"message_id": 42}}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _R()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(db, "get_integration",
                        lambda e, p: {"api_token": "123:RAHASIA"})

    out = t.execute_tool("kirim_telegram_message",
                         {"chat_id": "-1001", "pesan": "halo"}, "u@katalir.id")

    assert captured["json"] == {"chat_id": "-1001", "text": "halo"}
    assert "sendMessage" in captured["url"]
    assert "RAHASIA" not in out, "token bocor ke hasil tool"
    assert "42" in out


def test_telegram_tanpa_kredensial_meminta_form(monkeypatch):
    """SaaS multi-tenant: tanpa token di Brankas HARUS minta kredensial.

    Task 4A menambah fallback `.env` untuk dev/self-hosted, jadi tes ini
    menyalakan mode produksinya (`TELEGRAM_ENV_FALLBACK=0`) — justru itu jalur
    yang benar-benar mencegah user A memakai bot user B.
    """
    monkeypatch.setattr(db, "get_integration", lambda e, p: None)
    monkeypatch.setenv("TELEGRAM_ENV_FALLBACK", "0")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    try:
        t.execute_tool("kirim_telegram_message",
                       {"chat_id": "1", "pesan": "x"}, "u@katalir.id")
    except t.CredentialMissingError as exc:
        assert exc.provider_name == "telegram"
    else:
        raise AssertionError("harus CredentialMissingError")



def test_slack_menolak_webhook_bukan_slack(monkeypatch):
    monkeypatch.setattr(db, "get_integration",
                        lambda e, p: {"api_token": "https://jahat.example.com/hook"})
    try:
        t.execute_tool("kirim_slack_message",
                       {"channel": "#umum", "pesan": "x"}, "u@katalir.id")
    except RuntimeError as exc:
        assert "hooks.slack.com" in str(exc)
    else:
        raise AssertionError("webhook asing harus ditolak")


def test_slack_token_bot_pakai_header_authorization(monkeypatch):
    captured = {}

    class _R:
        status_code = 200
        text = "ok"

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers") or {}
        captured["json"] = kwargs.get("json")
        return _R()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(db, "get_integration",
                        lambda e, p: {"api_token": "xoxb-RAHASIA"})

    out = t.execute_tool("kirim_slack_message",
                         {"channel": "#umum", "pesan": "hai"}, "u@katalir.id")
    assert captured["headers"]["Authorization"] == "Bearer xoxb-RAHASIA"
    assert captured["json"] == {"channel": "#umum", "text": "hai"}
    assert "RAHASIA" not in out


def test_ssrf_guard_menolak_alamat_internal():
    for url in ("http://localhost:8000/admin", "http://127.0.0.1/",
                "http://10.0.0.5/", "http://192.168.1.1/",
                "http://169.254.169.254/latest/meta-data/",
                "http://[::1]/", "http://metadata.google.internal/computeMetadata/v1/"):
        try:
            t.http_request(url=url, method="GET", body="", email="u@katalir.id")
        except ValueError as exc:
            assert "SSRF" in str(exc) or "http/https" in str(exc), (url, exc)
        else:
            raise AssertionError(f"alamat internal tidak ditolak: {url}")


def test_ssrf_guard_mengizinkan_host_publik(monkeypatch):
    class _R:
        status_code = 200
        text = '{"ok":true}'

    import httpx
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _R())
    out = t.http_request(url="https://example.com/v1/ping",
                         method="GET", body="", email="u@katalir.id")
    assert out.startswith("HTTP 200 dari example.com")
    assert json.loads(_R.text) == {"ok": True}


def test_http_request_menolak_method_aneh():
    try:
        t.http_request(url="https://api.example.com", method="TRACE",
                       body="", email="u@katalir.id")
    except ValueError as exc:
        assert "Method" in str(exc)
    else:
        raise AssertionError("method tak didukung harus ditolak")


def test_capabilities_melapor_keberadaan_artefak_dedup(monkeypatch):
    """`/mcp/registry/capabilities` harus jujur soal view `unique`.

    Artefak `dedup_canonical.json` sengaja tidak di-commit, jadi ada deploy yang
    booting tanpa file itu. `GET /mcp/registry?view=unique` waktu itu balas 400
    dan toggle "Unique (dedup)" di UI jadi kontrol yang pasti gagal.

    Endpoint capabilities ini yang dipakai frontend untuk menyembunyikan toggle,
    jadi ia harus mengembalikan `unique_view=false` - bukan `true` yang berbohong
    - ketika artefaknya memang tidak ada. Test ini mengunci kedua arah.
    """
    from fastapi.testclient import TestClient

    import api_server

    client = TestClient(api_server.app)
    seen = []
    try:
        response = client.get("/mcp/registry/capabilities")
        assert response.status_code == 200, response.text
        body = response.json()
        seen.append(body)
        # whatever the environment holds, the flag must be a real bool and must
        # agree with the file the backend actually consults
        assert isinstance(body["unique_view"], bool)
        assert body["unique_view"] == mcp_registry.CANONICAL_PATH.exists()
        if body["unique_view"]:
            assert body["reason"] is None
        else:
            # must explain itself instead of failing silently later
            assert body["reason"] and "mcp_dedup.py" in body["reason"]

        # Now force the "artifact missing" branch and confirm the flag flips.
        # `Path.exists` is read-only, so the whole Path object is swapped for one
        # pointing at a name that cannot exist. The endpoint reads
        # `CANONICAL_PATH.exists()`, so swapping the module attribute is the seam.
        monkeypatch.setattr(
            mcp_registry, "CANONICAL_PATH", mcp_registry.CANONICAL_PATH.with_name("__absent__.json")
        )
        body2 = client.get("/mcp/registry/capabilities").json()
        seen.append(body2)
        assert body2["unique_view"] is False
        assert body2["reason"]
    finally:
        print("capabilities saw:", seen)
