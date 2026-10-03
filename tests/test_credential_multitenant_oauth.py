# -*- coding: utf-8 -*-
"""Bagian 3 + 5: credential registry, resume OAuth, isolasi multi-tenant."""
import json

import pytest

import api_server as srv
import credential_forms as cf


# ------------------------------------------------------------ check_credential
def test_check_credential_provider_form_belum_ada(monkeypatch):
    monkeypatch.setattr(cf, "has_credential", lambda u, p: False)
    r = cf.check_credential("gmail_imap", "a@b.co")
    assert r["status"] == "requires_credential"
    assert r["fields"], "descriptor form harus ikut"


def test_check_credential_sudah_ada_tidak_minta_form(monkeypatch):
    """Credential yang sudah ada TIDAK boleh memunculkan form lagi."""
    monkeypatch.setattr(cf, "has_credential", lambda u, p: True)
    r = cf.check_credential("gmail_imap", "a@b.co")
    assert r["status"] == "ok"
    assert "fields" not in r


def test_check_credential_provider_oauth(monkeypatch):
    monkeypatch.setattr(cf, "_oauth_connected", lambda p, u: False)
    r = cf.check_credential("google_sheets", "a@b.co")
    assert r["status"] == "requires_oauth"
    assert r["oauth_url"]


def test_check_credential_oauth_sudah_terhubung(monkeypatch):
    monkeypatch.setattr(cf, "_oauth_connected", lambda p, u: True)
    assert cf.check_credential("google_sheets", "a@b.co")["status"] == "ok"


def test_check_credential_provider_tak_dikenal():
    r = cf.check_credential("provider_ngarang", "a@b.co")
    assert r["status"] == "unknown_provider"


# --------------------------------------------------- isolasi multi-tenant
def test_vault_terpisah_per_user(monkeypatch):
    """User A dan B punya record sendiri; tidak boleh saling baca.

    Pakai `monkeypatch` untuk menambal vault: assigning langsung pernah
    membocorkan stub ke test lain (terbukti - 5 test OAuth/vault ikut
    gagal karena `_encrypt_key` tidak dikembalikan setelah test ini).
    """
    import database as db
    import vault_security as vs

    store = {}
    monkeypatch.setattr(vs, "encrypt_key", lambda v: "C:" + v)
    monkeypatch.setattr(vs, "decrypt_key", lambda v: v[2:])
    monkeypatch.setattr(db, "vault_save",
                        lambda e, p, c: store.__setitem__((e, p), c) or True)
    monkeypatch.setattr(db, "vault_get", lambda e, p: store.get((e, p)))

    cf.validate_and_save("gmail_imap",
                         {"email": "A@gmail.com",
                          "app_password": "AAAABBBBCCCCDDDD"},
                         "A@gmail.com")
    cf.validate_and_save("gmail_imap",
                         {"email": "B@gmail.com",
                          "app_password": "EEEEFFFFGGGGHHHH"},
                         "B@gmail.com")

    a = cf.load_vault_credential("A@gmail.com", "gmail_imap")
    b = cf.load_vault_credential("B@gmail.com", "gmail_imap")
    assert a["email"] == "A@gmail.com" and a["app_password"] == "AAAABBBBCCCCDDDD"
    assert b["email"] == "B@gmail.com" and b["app_password"] == "EEEEFFFFGGGGHHHH"
    assert "EEEEFFFFGGGGHHHH" not in json.dumps(a), "A bocor data B"
    assert "AAAABBBBCCCCDDDD" not in json.dumps(b), "B bocor data A"
    # C belum punya apa pun.
    assert cf.load_vault_credential("C@gmail.com", "gmail_imap") is None


def test_resume_token_tidak_lintas_user():
    tok_a = cf.issue_resume_token("A@gmail.com", "gmail_imap")
    assert cf.verify_resume_token(tok_a, "A@gmail.com") == "gmail_imap"
    # Token A tidak boleh dipakai user B.
    with pytest.raises(ValueError):
        cf.verify_resume_token(tok_a, "B@gmail.com")


# ------------------------------------------------------- resume OAuth (3.2c)
def test_resume_destination_membawa_token():
    url = srv._resume_destination("TOK123")
    assert "/chat" in url
    assert "resume=TOK123" in url


def test_resume_destination_kosong_tanpa_token():
    assert srv._resume_destination("") == ""


def test_state_asing_ditolak_untuk_open_redirect():
    """`state` dari provider tidak boleh mengarahkan ke situs lain."""
    evil = "https://evil.example/steal"
    assert srv._safe_resume_target(evil) == ""
    assert srv._safe_resume_target("") == ""
    assert srv._safe_resume_target("javascript:alert(1)") == ""


def test_state_asli_kembali_ke_chat():
    dest = srv._resume_destination("TOK9")
    from urllib.parse import urlencode
    state = "https://accounts.google.com/o/oauth2/auth?" + urlencode(
        {"redirect_to": dest})
    assert srv._safe_resume_target(state) == dest


def test_append_query_menjaga_param_lama():
    url = srv._append_query("https://x.test/a?b=1&c=2", {"d": "3", "b": "9"})
    assert "d=3" in url and "b=9" in url and "c=2" in url
