"""tests/test_credential_forms_inline.py — form credential INLINE di chat.

Kontrak yang diuji:
  * `requires_credential` membawa descriptor field + resume_token.
  * resume_token: ditandatangani, punya TTL, dan menolak user lain.
  * `validate_and_save` memvalidasi lalu menyimpan, TIDAK pernah mengembalikan
    nilai credential.
  * System prompt melarang menyuruh user membuka halaman Vault/Settings.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import credential_forms as cf  # noqa: E402


# --------------------------------------------------------------------------
# Descriptor form
# --------------------------------------------------------------------------
def test_gmail_punya_form_inline():
    assert cf.has_inline_form("gmail_imap") is True
    assert cf.has_inline_form("GMAIL_IMAP") is True  # case-insensitive


def test_provider_oauth_tidak_punya_form_token_manual():
    """Provider OAuth tidak boleh minta user menempel access token."""
    for p in ("google_sheets", "slack"):
        assert cf.has_inline_form(p) is False
        assert p in cf.OAUTH_ONLY_PROVIDERS


def test_build_requires_credential_lengkap():
    req = cf.build_requires_credential("gmail_imap", "u@example.com", session_id="s1")
    assert req["status"] == "requires_credential"
    assert req["provider"] == "gmail_imap"
    assert req["display_name"]
    assert req["session_id"] == "s1"
    assert req["resume_token"]
    assert req["expires_in"] == cf.TOKEN_TTL_S
    names = [f["name"] for f in req["fields"]]
    assert names == ["email", "app_password"]
    pw_field = next(f for f in req["fields"] if f["name"] == "app_password")
    assert pw_field["type"] == "password"
    assert pw_field["min_length"] == 16
    assert pw_field["help_url"].startswith("https://")


def test_fields_dityalin_tidak_shared():
    """Modifikasi field di satu respons tidak boleh mengubah definisi global."""
    a = cf.build_requires_credential("gmail_imap", "u@example.com")
    a["fields"][0]["label"] = "DIREKSI"
    b = cf.build_requires_credential("gmail_imap", "u@example.com")
    assert b["fields"][0]["label"] != "DIREKSI"


def test_provider_tanpa_form_menolak_build():
    with pytest.raises(ValueError):
        cf.build_requires_credential("google_sheets", "u@example.com")


# --------------------------------------------------------------------------
# resume_token
# --------------------------------------------------------------------------
def test_token_roundtrip():
    tok = cf.issue_resume_token("u@example.com", "gmail_imap")
    assert cf.verify_resume_token(tok, "u@example.com") == "gmail_imap"


def test_token_milik_user_lain_ditolak():
    tok = cf.issue_resume_token("a@example.com", "gmail_imap")
    with pytest.raises(ValueError):
        cf.verify_resume_token(tok, "b@example.com")


def test_token_rusak_ditolak():
    with pytest.raises(ValueError):
        cf.verify_resume_token("bukan-token", "u@example.com")
    tok = cf.issue_resume_token("u@example.com", "gmail_imap")
    body, sig = tok.split(".")
    with pytest.raises(ValueError):
        cf.verify_resume_token(f"{body}.{sig[:-4]}xyz", "u@example.com")


def test_token_kedaluwarsa_ditolak(monkeypatch):
    # `issue_resume_token` membulatkan TTL ke minimum 60 detik, jadi waktu
    # dimajukan lebih dari itu.
    tok = cf.issue_resume_token("u@example.com", "gmail_imap", ttl_s=1)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 120)
    with pytest.raises(ValueError):
        cf.verify_resume_token(tok, "u@example.com")


def test_token_tidak_membocorkan_credential():
    tok = cf.issue_resume_token("u@example.com", "gmail_imap")
    assert "app_password" not in tok
    assert "@" not in tok  # email di dalam payload ter-base64, bukan plaintext

# --------------------------------------------------------------------------
# validate_and_save
# --------------------------------------------------------------------------
@pytest.fixture
def fake_writer(monkeypatch):
    saved: dict = {}

    def writer(email, address, app_password):
        saved["email"] = email
        saved["address"] = address
        saved["app_password"] = app_password

    monkeypatch.setattr("tools.save_gmail_imap_credential", writer)
    return saved


def test_simpan_menormalisasi_spasi(fake_writer):
    out = cf.validate_and_save(
        "gmail_imap",
        {"email": "u@gmail.com", "app_password": "abcd efgh ijkl mnop"},
        "katalir@example.com")
    assert fake_writer["app_password"] == "abcdefghijklmnop"  # 16 char
    assert fake_writer["address"] == "u@gmail.com"
    # Ringkasan TIDAK boleh memuat password.
    assert out["saved"]["app_password"] == "***"


def test_password_terlalu_pendek_ditolak(fake_writer):
    with pytest.raises(ValueError) as exc:
        cf.validate_and_save("gmail_imap",
                             {"email": "u@gmail.com", "app_password": "pendek"},
                             "k@e.com")
    assert "16" in str(exc.value)
    assert "app_password" not in fake_writer


def test_email_kosong_ditolak(fake_writer):
    with pytest.raises(ValueError):
        cf.validate_and_save("gmail_imap",
                             {"email": "", "app_password": "abcdefghijklmnop"},
                             "k@e.com")


def test_provider_tanpa_writer_ditolak():
    with pytest.raises(ValueError):
        cf.validate_and_save("google_sheets", {}, "k@e.com")


def test_tidak_menulis_credential_asing(fake_writer):
    """Field tak dikenal di body harus diabaikan, bukan diteruskan ke writer."""
    cf.validate_and_save(
        "gmail_imap",
        {"email": "u@gmail.com", "app_password": "abcdefghijklmnop",
         "is_admin": "true"},
        "k@e.com")
    assert set(fake_writer) == {"email", "address", "app_password"}


# --------------------------------------------------------------------------
# Guard: system prompt tidak boleh mengarahkan ke Vault
# --------------------------------------------------------------------------
def test_system_prompt_larang_redirect_vault():
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "CREDENTIAL (WAJIB)" in src
    assert "JANGAN PERNAH menyuruh user membuka halaman Vault" in src
    assert "Sistem otomatis menampilkan form" in src


def test_endpoint_resume_terdaftar():
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert '@app.post("/chat/resume")' in src
    assert "verify_resume_token" in src
    assert "validate_and_save" in src


def test_chat_memakai_form_inline_bukan_redirect():
    """/chat harus mengembalikan requires_credential untuk provider ber-form."""
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "has_inline_form" in src
    assert "build_requires_credential" in src


def test_frontend_render_form_inline():
    src = (ROOT / "nexus-frontend" / "src" / "components"
           / "CredentialForm.tsx").read_text(encoding="utf-8")
    assert "/chat/resume" in src
    assert "Data disimpan terenkripsi di vault Anda." in src
    # Form tidak boleh hilang saat error -> error ditampilkan inline.
    assert 'data-testid="credential-form-error"' in src
