"""tests/test_oauth_google.py — kunci perilaku OAuth Google TANPA jaringan.

Yang diuji (dan kenapa penting):
  * PKCE S256 benar-benar dipakai dan `code_verifier` TIDAK ikut ke URL;
  * `access_type=offline` + `prompt=consent` ada (tanpa keduanya Google tidak
    mengirim refresh_token -> token mati setelah 1 jam dan user harus klik ulang);
  * `state` bertanda tangan: state yang diubah / kedaluwarsa HARUS ditolak
    (kalau tidak, callback bisa menulis token ke akun orang lain);
  * token disimpan TERENKRIPSI (ciphertext tidak memuat access_token);
  * refresh otomatis saat token hampir jatuh, dan `refresh_token` lama
    dipertahankan karena Google tidak mengirim ulang saat refresh.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("VAULT_SECRET_KEY", "test-secret-untuk-oauth")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-secret")

import oauth_google as og  # noqa: E402


class _Res:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Client:
    """httpx.Client palsu; merekam request untuk diperiksa."""

    def __init__(self, res: _Res):
        self.res = res
        self.calls: list[dict] = []

    def post(self, url, data=None, **kwargs):  # noqa: ANN001
        self.calls.append({"url": url, "data": dict(data or {})})
        return self.res

    def close(self) -> None:
        pass


def _state_of(url: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]


# ---------------------------------------------------------------------------
# authorize
# ---------------------------------------------------------------------------
def test_authorize_url_memakai_pkce_s256_dan_mode_offline():
    url = og.build_authorize_url("a@b.c")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["access_type"] == ["offline"], "tanpa offline, Google tidak memberi refresh_token"
    assert qs["prompt"] == ["consent"], "tanpa consent, refresh_token tidak dikirim ulang"
    assert qs["redirect_uri"] == ["http://localhost:8000/oauth/google/callback"]
    assert qs["scope"] == [og.SHEETS_SCOPE]
    # PKCE: challenge = SHA256(verifier) base64url tanpa padding, dan verifier
    # TIDAK boleh muncul di URL (kalau muncul, PKCE tidak berguna).
    email, verifier = og.pop_verifier(_state_of(url))
    assert email == "a@b.c"
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert qs["code_challenge"] == [expect]
    assert verifier not in url
    print(f"AUTHORIZE_PKCE=ok challenge_len={len(qs['code_challenge'][0])} verifier_in_url=False")


def test_state_tidak_bisa_ditempa_dan_kedaluwarsa():
    state = og.sign_state("a@b.c")
    assert og.verify_state(state) == "a@b.c"
    bad = ("A" if state[-1] != "A" else "B") + state[1:]
    with pytest.raises(ValueError):
        og.verify_state(bad)
    old = og.sign_state("a@b.c", now=og._now() - og.STATE_TTL_S - 5)
    with pytest.raises(ValueError):
        og.verify_state(old)
    print("STATE_TAMPER=ditolak STATE_EXPIRED=ditolak")


def test_pop_verifier_sekali_pakai():
    state = og.sign_state("a@b.c")
    og._PENDING[state] = {"verifier": "v" * 10, "email": "a@b.c", "ts": og._now()}
    og.pop_verifier(state)
    with pytest.raises(ValueError):
        og.pop_verifier(state)  # replay state harus gagal
    print("STATE_REPLAY=ditolak")


# ---------------------------------------------------------------------------
# exchange + refresh
# ---------------------------------------------------------------------------
def test_exchange_mengirim_verifier_dan_menormalkan_token():
    state = _state_of(og.build_authorize_url("a@b.c"))
    client = _Client(_Res(200, {"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600, "scope": og.SHEETS_SCOPE}))
    tokens = og.exchange_code("CODE-1", state, client=client)
    sent = client.calls[0]["data"]
    assert sent["code"] == "CODE-1"
    assert sent["grant_type"] == "authorization_code"
    assert sent["code_verifier"], "code_verifier wajib dikirim saat menukar code"
    assert sent["redirect_uri"] == "http://localhost:8000/oauth/google/callback"
    assert tokens["access_token"] == "AT-1"
    assert tokens["refresh_token"] == "RT-1"
    assert tokens["email"] == "a@b.c"
    assert tokens["expires_at"] > og._now()
    print(f"EXCHANGE=ok expires_at_set={bool(tokens['expires_at'])} email_binding=ok")


def test_exchange_gagal_memberi_pesan_jujur_tanpa_membocorkan_token():
    state = _state_of(og.build_authorize_url("a@b.c"))
    client = _Client(_Res(400, {"error": "invalid_grant", "error_description": "Bad Request"}))
    with pytest.raises(RuntimeError) as e:
        og.exchange_code("CODE", state, client=client)
    msg = str(e.value)
    assert "invalid_grant" in msg and "HTTP 400" in msg
    assert "test-secret" not in msg
    print(f"EXCHANGE_GAGAL=pesan_jujur msg={msg[:80]}")


def test_refresh_mempertahankan_refresh_token_lama():
    client = _Client(_Res(200, {"access_token": "AT-2", "expires_in": 3600}))
    out = og.refresh_tokens(
        {"access_token": "AT-1", "refresh_token": "RT-1", "expires_at": og._now() - 10}, client=client
    )
    assert out["access_token"] == "AT-2"
    assert out["refresh_token"] == "RT-1", "Google tidak mengirim ulang refresh_token saat refresh"
    assert client.calls[0]["data"]["grant_type"] == "refresh_token"
    print("REFRESH=ok refresh_token_dipertahankan=True")


def test_refresh_tanpa_refresh_token_menyuruh_connect_ulang():
    with pytest.raises(RuntimeError) as e:
        og.refresh_tokens({"access_token": "AT"})
    assert "Connect ulang" in str(e.value)
    print("REFRESH_TANPA_RT=pesan_connect_ulang")


def test_needs_refresh_memakai_leeway():
    assert og.needs_refresh({"expires_at": og._now() + 3600}) is False
    assert og.needs_refresh({"expires_at": og._now() + 60}) is True   # < leeway 120s
    assert og.needs_refresh({}) is True
    print("REFRESH_LEEWAY_S=" + str(og.REFRESH_LEEWAY_S))


# ---------------------------------------------------------------------------
# penyimpanan Vault (terenkripsi, tanpa DB nyata)
# ---------------------------------------------------------------------------
def _fake_vault(monkeypatch, store: dict) -> None:
    import database as db

    monkeypatch.setattr(db, "vault_save", lambda e, p, ct: store.__setitem__((e, p), ct) or True)
    monkeypatch.setattr(db, "vault_get", lambda e, p: store.get((e, p), ""))
    monkeypatch.setattr(db, "vault_delete", lambda e, p: store.pop((e, p), None) is not None)


def test_token_disimpan_terenkripsi_dan_bisa_dibaca_ulang(monkeypatch):
    store: dict = {}
    _fake_vault(monkeypatch, store)
    payload = {
        "access_token": "AT-SECRET",
        "refresh_token": "RT-SECRET",
        "scope": og.SHEETS_SCOPE,
        "expires_at": og._now() + 3600,
    }
    assert og.save_tokens("a@b.c", payload) is True
    ct = store[("a@b.c", og.PROVIDER)]
    assert "AT-SECRET" not in ct, "access_token tidak boleh tersimpan plaintext"
    assert "RT-SECRET" not in ct, "refresh_token tidak boleh tersimpan plaintext"
    assert og.load_tokens("a@b.c")["access_token"] == "AT-SECRET"
    status = og.connection_status("a@b.c")
    assert status["connected"] is True and status["has_refresh_token"] is True
    assert "AT-SECRET" not in json.dumps(status), "status UI tidak boleh memuat token"
    print(f"VAULT_STORED={og.PROVIDER} ciphertext_len={len(ct)} plaintext_bocor=False")


def test_access_token_refresh_otomatis_saat_hampir_jatuh(monkeypatch):
    store: dict = {}
    _fake_vault(monkeypatch, store)
    og.save_tokens("a@b.c", {"access_token": "AT-LAMA", "refresh_token": "RT-1", "expires_at": og._now() - 5})
    client = _Client(_Res(200, {"access_token": "AT-BARU", "expires_in": 3600}))
    assert og.access_token("a@b.c", client=client) == "AT-BARU"
    assert og.load_tokens("a@b.c")["access_token"] == "AT-BARU", "hasil refresh harus tersimpan"
    print("REFRESH_AUTO=ok token_baru_tersimpan=True")


def test_access_token_tanpa_koneksi_menyuruh_connect(monkeypatch):
    import database as db

    monkeypatch.setattr(db, "vault_get", lambda e, p: "")
    with pytest.raises(RuntimeError) as e:
        og.access_token("belum@terhubung")
    assert "Connect" in str(e.value)
    print("ACCESS_TOKEN_TANPA_KONEKSI=pesan_connect")


def test_config_membaca_redirect_uri_yang_harus_didaftarkan():
    cfg = og.config("https://api.example.com/")
    assert cfg["redirect_uri"] == "https://api.example.com/oauth/google/callback"
    assert og.configured() is True
    print(f"REDIRECT_URI={cfg['redirect_uri']}")

