"""Test vault_broker (rujuk `secret://`) + tool `check_credential`.

BUG FIX 2026-10-04. Menutup dua celah:
  1. tidak ada tool untuk menanyakan status kredensial -> vault form
     tidak pernah muncul;
  2. nilai kredensial harus bisa masuk ke argumen tanpa pernah menyentuh
     konteks LLM.
"""

import json

import pytest

import tools
from vault_broker import (CredentialMissingError, SecretRefError,
                           is_secret_ref, redact, resolve_secret,
                           resolve_secrets_in_args)

USER = "vault-broker-test@katalir.test"
STASH = {}


@pytest.fixture(autouse=True)
def _isolasi_vault(monkeypatch):
    """Vault palsu supaya tes tidak menyentuh Supabase sungguhan."""
    STASH.clear()

    def fake_load(user_email, vault_provider):
        return STASH.get((user_email, vault_provider))

    import credential_forms
    monkeypatch.setattr(credential_forms, "load_vault_credential", fake_load)
    yield
    STASH.clear()


# --------------------------------------------------------------------------
# vault_broker
# --------------------------------------------------------------------------
def test_is_secret_ref():
    assert is_secret_ref("secret://gmail_imap/app_password")
    assert not is_secret_ref("hunter2")
    assert not is_secret_ref(None)
    assert not is_secret_ref(123)


def test_resolve_secret_mengambil_nilai_asli():
    STASH[(USER, "gmail_imap")] = {"email": "a@b.c", "app_password": "APP-SECRET-123"}
    assert resolve_secret("secret://gmail_imap/app_password", USER) == "APP-SECRET-123"


def test_resolve_secret_field_hilang():
    STASH[(USER, "gmail_imap")] = {"email": "a@b.c"}
    with pytest.raises(CredentialMissingError):
        resolve_secret("secret://gmail_imap/app_password", USER)


def test_resolve_secret_kredensial_hilang_tanpa_bocor_email():
    with pytest.raises(CredentialMissingError) as e:
        resolve_secret("secret://gmail_imap/app_password", USER)
    assert USER not in str(e.value)


@pytest.mark.parametrize("buruk", ["secret://", "secret://gmail_imap",
                                   "secret://gmail_imap/", "app_password",
                                   "http://x/y"])
def test_ref_bentuk_salah_ditolak(buruk):
    with pytest.raises(SecretRefError):
        resolve_secret(buruk, USER)


def test_resolve_secrets_nested():
    STASH[(USER, "gmail_imap")] = {"app_password": "SECRET-A"}
    STASH[(USER, "telegram")] = {"bot_token": "SECRET-B"}
    args = {"a": "secret://gmail_imap/app_password",
            "b": {"c": "secret://telegram/bot_token", "d": "biasa"},
            "e": ["secret://gmail_imap/app_password", 5]}
    out = resolve_secrets_in_args(args, USER)
    assert out["a"] == "SECRET-A"
    assert out["b"]["c"] == "SECRET-B"
    assert out["b"]["d"] == "biasa"
    assert out["e"][0] == "SECRET-A"
    assert out["e"][1] == 5


def test_args_biasa_tidak_diubah():
    args = {"x": "1", "y": 2, "z": None}
    assert resolve_secrets_in_args(args, USER) == args
def test_nilai_asli_tidak_ada_di_redact():
    STASH[(USER, "gmail_imap")] = {"app_password": "APP-SECRET-123"}
    real = resolve_secret("secret://gmail_imap/app_password", USER)
    assert real == "APP-SECRET-123"
    assert "APP-SECRET-123" not in json.dumps(
        redact({"pw": "secret://gmail_imap/app_password"}))


def test_execute_tool_menerima_secret_ref(monkeypatch):
    """Broker terpasang di jalur produksi `execute_tool`, bukan fungsi terpisah."""
    STASH[(USER, "telegram")] = {"chat_id": "111", "pesan": "halo"}
    seen = {}

    def fake_send(chat_id, pesan, email):
        seen.update({"chat_id": chat_id, "pesan": pesan, "email": email})
        return "ok"

    monkeypatch.setattr(tools, "kirim_telegram_message", fake_send)
    out = tools.execute_tool(
        "kirim_telegram_message",
        {"chat_id": "secret://telegram/chat_id",
         "pesan": "secret://telegram/pesan"},
        USER)
    assert out == "ok"
    assert seen["chat_id"] == "111"
    assert seen["pesan"] == "halo"


def test_execute_tool_kredensial_hilang_tidak_melempar():
    """Tool harus mengembalikan instruksi form, bukan crash."""
    out = tools.execute_tool(
        "kirim_telegram_message",
        {"chat_id": "secret://telegram/chat_id", "pesan": "x"}, USER)
    assert isinstance(out, dict)
    assert out["status"] == "requires_credential"


# --------------------------------------------------------------------------
# tool check_credential
# --------------------------------------------------------------------------
def test_check_credential_terdaftar_sebagai_tool():
    names = [s["function"]["name"] for s in tools.TOOL_SCHEMAS_OPENAI]
    assert "check_credential" in names


def test_schema_check_credential_sah():
    sch = [s for s in tools.TOOL_SCHEMAS_OPENAI
           if s["function"]["name"] == "check_credential"][0]["function"]["parameters"]
    assert sch["type"] == "object"
    assert sch["required"] == ["provider"]
    assert set(sch["properties"]["provider"]["enum"]) == {
        "gmail_imap", "google_sheets", "telegram", "slack", "supabase"}


def test_check_credential_belum_punya_kredensial():
    out = json.loads(tools.execute_tool(
        "check_credential", {"provider": "gmail_imap"}, USER))
    assert out["status"] == "requires_credential"
    # form inline butuh dua hal ini; tanpa keduanya form tidak bisa dirender
    assert out.get("fields")
    assert out.get("resume_token")


def test_check_credential_sudah_punya_kredensial():
    STASH[(USER, "gmail_imap")] = {"email": "a@b.c", "app_password": "x"}
    out = json.loads(tools.execute_tool(
        "check_credential", {"provider": "gmail_imap"}, USER))
    assert out["status"] == "ok"


def test_check_credential_provider_asing_tidak_ngaduk():
    out = json.loads(tools.execute_tool(
        "check_credential", {"provider": "tidak-ada"}, USER))
    assert out["status"] == "unknown_provider"


def test_check_credential_tidak_pernah_melempar():
    """Model harus selalu bisa membaca status, walau vault bermasalah."""
    import credential_forms
    orig = credential_forms.check_credential

    def ledak(*a, **k):
        raise RuntimeError("vault meledak")

    credential_forms.check_credential = ledak
    try:
        out = json.loads(tools.execute_tool(
            "check_credential", {"provider": "gmail_imap"}, USER))
        assert out["status"] == "error"
        # pesan tidak boleh membocorkan isi exception internal
        assert "vault meledak" not in json.dumps(out)
    finally:
        credential_forms.check_credential = orig


def test_redact_menyembunyikan_nilai_rahasia():
    out = redact({"pw": "secret://gmail_imap/app_password",
                  "nested": {"t": "secret://telegram/bot_token"},
                  "ok": "biasa"})
    assert out["pw"] == "***"
    assert out["nested"]["t"] == "***"
    assert out["ok"] == "biasa"