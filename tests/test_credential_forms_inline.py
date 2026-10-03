"""tests/test_credential_forms_inline.py — form credential INLINE di chat.

Kontrak yang diuji:
  * `requires_credential` membawa descriptor field + resume_token.
  * resume_token: ditandatangani, punya TTL, dan menolak user lain.
  * `validate_and_save` memvalidasi lalu menyimpan, TIDAK pernah mengembalikan
    nilai credential.
  * System prompt melarang menyuruh user membuka halaman Vault/Settings.
"""

from __future__ import annotations

import json
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
    """Tangkap payload yang masuk ke vault (tanpa DB sungguhan).

    BUG/FITUR generic 2026-10-03: `validate_and_save` tidak lagi menulis lewat
    `tools.save_gmail_imap_credential`; ia memakai helper generik
    `save_vault_credential` (JSON terenkripsi). Fixture ini karena itu
    menyambel `database.vault_save` + `vault_security.encrypt_key`.
    """
    import json as _j

    saved: dict = {}

    def fake_encrypt(plain: str) -> str:
        saved["plain"] = plain
        return "CIPHER"

    monkeypatch.setattr("vault_security.encrypt_key", fake_encrypt)
    monkeypatch.setattr(
        "database.vault_save",
        lambda e, p, c: saved.__setitem__("row", (e, p, c)) or True)
    return saved


def test_simpan_menormalisasi_spasi(fake_writer):
    out = cf.validate_and_save(
        "gmail_imap",
        {"email": "u@gmail.com", "app_password": "abcd efgh ijkl mnop"},
        "katalir@example.com")
    stored = json.loads(fake_writer["plain"])
    assert stored["app_password"] == "abcdefghijklmnop"  # 16 char, tanpa spasi
    assert stored["email"] == "u@gmail.com"
    # Baris vault memakai vault_provider dari registry.
    assert fake_writer["row"][1] == "gmail_imap"
    assert fake_writer["row"][2] == "CIPHER"
    # Ringkasan TIDAK boleh memuat password (field secret disamarkan).
    assert out["saved"]["app_password"] == "***"


def test_password_terlalu_pendek_ditolak(fake_writer):
    with pytest.raises(ValueError) as exc:
        cf.validate_and_save("gmail_imap",
                             {"email": "u@gmail.com", "app_password": "pendek"},
                             "k@e.com")
    assert "16" in str(exc.value)
    assert "plain" not in fake_writer  # TIDAK ada yang ditulis ke vault


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
    stored = json.loads(fake_writer["plain"])
    # Field tak dikenal di body HARUS diabaikan (mass assignment guard).
    assert set(stored) == {"email", "app_password"}
    assert "is_admin" not in stored


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


# --------------------------------------------------------------------------
# Registry generik (2026-10-03)
# --------------------------------------------------------------------------
def test_registry_terdaftar_lima_provider():
    from providers.credential_schemas import CREDENTIAL_SCHEMAS
    for p in ("gmail_imap", "google_sheets", "supabase", "telegram", "slack"):
        assert p in CREDENTIAL_SCHEMAS, f"{p} hilang dari registry"
        assert CREDENTIAL_SCHEMAS[p]["display_name"]
        assert CREDENTIAL_SCHEMAS[p]["mode"] in ("form", "oauth_redirect")
        assert CREDENTIAL_SCHEMAS[p]["vault_provider"]


def test_setiap_field_form_punya_label_dan_secret_flag():
    from providers.credential_schemas import providers_using_form
    for p in providers_using_form():
        spec = cf.get_schema(p)
        assert spec.get("fields"), f"{p} mode form tapi tidak punya field"
        for f in spec["fields"]:
            assert f.get("label"), f"{p}.{f['name']} tidak punya label"
            assert "secret" in f, f"{p}.{f['name']} belum ditandai secret"
            assert isinstance(f.get("required"), bool)


def test_provider_form_memang_multi_field():
    """Registry harus mendukung >2 field (bukti bukan hardcode Gmail)."""
    assert len(cf.get_schema("supabase")["fields"]) == 3
    assert len(cf.get_schema("telegram")["fields"]) == 2
    names = [f["name"] for f in cf.get_schema("supabase")["fields"]]
    assert names == ["project_url", "service_role_key", "anon_key"]


def test_oauth_provider_tidak_punya_field_form():
    from providers.credential_schemas import providers_using_oauth
    for p in providers_using_oauth():
        spec = cf.get_schema(p)
        assert spec.get("mode") == "oauth_redirect"
        assert not spec.get("fields"), (
            f"{p} mode oauth tidak boleh punya field form - user tidak bisa "
            "menempel token OAuth dengan benar")


def test_field_rahasia_ditandai_benar():
    sup = cf.get_schema("supabase")
    by_name = {f["name"]: f for f in sup["fields"]}
    assert by_name["service_role_key"]["secret"] is True
    assert by_name["anon_key"]["secret"] is True
    assert by_name["project_url"]["secret"] is False


def test_build_requires_oauth_dari_registry():
    r = cf.build_requires_oauth("google_sheets", "u@example.com")
    assert r["status"] == "requires_oauth"
    assert r["oauth_url"] == "/oauth/google/authorize"
    assert r["scopes"]
    assert "fields" not in r


def test_build_requires_oauth_menolak_provider_form():
    with pytest.raises(ValueError):
        cf.build_requires_oauth("gmail_imap", "u@example.com")


def test_catalog_mention_semua_provider():
    cat = cf.credential_catalog()
    for p in ("gmail_imap", "google_sheets", "supabase", "telegram", "slack"):
        assert p in cat


def test_prompt_memuat_katalog_dari_registry():
    import api_server as srv
    prompt = srv._AGENT_SYSTEM
    assert "PROVIDER CREDENTIAL YANG TERSEDIA" in prompt
    for p in ("gmail_imap", "google_sheets", "supabase", "telegram", "slack"):
        assert p in prompt, f"{p} tidak ada di system prompt"


def test_validasi_multi_field_supabase(fake_writer):
    """Registry-driven: validasi + penyimpanan jalan tanpa kode per-provider."""
    out = cf.validate_and_save(
        "supabase",
        {"project_url": "https://abc.supabase.co",
         "service_role_key": "eyJhbGciOi-secretkey12345"},
        "u@example.com")
    stored = json.loads(fake_writer["plain"])
    assert stored["project_url"] == "https://abc.supabase.co"
    assert stored["service_role_key"] == "eyJhbGciOi-secretkey12345"
    # `anon_key` opsional kosong -> TIDAK disimpan.
    assert "anon_key" not in stored
    # Field secret disamarkan di ringkasan, URL tidak.
    assert out["saved"]["service_role_key"] == "***"
    assert out["saved"]["project_url"] == "https://abc.supabase.co"


def test_field_opsional_kosong_tidak_disimpan(fake_writer):
    cf.validate_and_save("telegram",
                         {"bot_token": "123456:ABC", "chat_id": "42"},
                         "u@example.com")
    assert set(json.loads(fake_writer["plain"])) == {"bot_token", "chat_id"}


def test_provider_oauth_tidak_bisa_disimpan_lewat_form(fake_writer):
    with pytest.raises(ValueError):
        cf.validate_and_save("google_sheets", {"token": "x"}, "u@example.com")
    assert "plain" not in fake_writer
