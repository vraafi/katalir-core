"""tests/test_oauth_slack.py — kunci perilaku OAuth Slack TANPA jaringan.

Yang diuji (dan kenapa):
  * URL authorize memuat `client_id`, scope yang diminta (chat:write,
    channels:read, users:read), `redirect_uri` benar, dan `state`;
  * **Slack membalas HTTP 200 walau gagal** (`{"ok": false, "error": ...}`) —
    `ok` WAJIB diperiksa, kalau tidak token sampah dianggap sukses;
  * pertukaran code mengirim client_id+client_secret+code+redirect_uri;
  * bot token + identitas workspace disimpan TERENKRIPSI; status UI tidak
    membocorkan token;
  * state sekali pakai (replay/tamper ditolak).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("VAULT_SECRET_KEY", "test-secret-untuk-oauth")
os.environ.setdefault("SLACK_CLIENT_ID", "11111.22222")
os.environ.setdefault("SLACK_CLIENT_SECRET", "slack-client-secret-test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "slack-signing-secret-test")
os.environ.setdefault("SLACK_APP_ID", "A0TESTAPPID")

import oauth_slack as osl  # noqa: E402


class _Res:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Client:
    def __init__(self, res: _Res):
        self.res = res
        self.calls: list[dict] = []

    def post(self, url, data=None, **kwargs):  # noqa: ANN001
        self.calls.append({"url": url, "data": dict(data or {})})
        return self.res

    def close(self) -> None:
        pass


def _state(url: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]


def _slack_ok(**extra) -> dict:
    body = {
        "ok": True,
        "access_token": "xoxb-BOT-TOKEN",
        "bot_user_id": "U0BOT",
        "team": {"id": "T0TEAM", "name": "Workspace Uji"},
        "scope": "chat:write,channels:read,users:read",
        "app_id": "A0TESTAPPID",
    }
    body.update(extra)
    return body


def _fake_vault(monkeypatch, store: dict) -> None:
    import database as db

    monkeypatch.setattr(db, "vault_save", lambda e, p, ct: store.__setitem__((e, p), ct) or True)
    monkeypatch.setattr(db, "vault_get", lambda e, p: store.get((e, p), ""))
    monkeypatch.setattr(db, "vault_delete", lambda e, p: store.pop((e, p), None) is not None)


def test_authorize_url_memuat_scope_redirect_dan_state():
    url = osl.build_authorize_url("a@b.c")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert urllib.parse.urlparse(url).netloc == "slack.com"
    # Bandingkan dengan config() dan BUKAN literal: saat seluruh suite dijalankan,
    # modul lain sudah memuat `.env` asli, sehingga SLACK_CLIENT_ID dapat bernilai
    # nyata. Yang penting diuji di sini adalah WIRING (nilai env benar-benar masuk
    # ke URL), bukan nilai spesifiknya.
    cfg = osl.config()
    assert qs["client_id"] == [cfg["client_id"]]
    assert qs["redirect_uri"] == [cfg["redirect_uri"]]
    scopes = qs["scope"][0].split(",")
    assert set(scopes) == {"chat:write", "channels:read", "users:read"}
    assert qs["state"], "state wajib ada (anti-CSRF)"
    assert osl.pop_owner(qs["state"][0]) == "a@b.c"
    print(f"AUTHORIZE_SLACK=ok scopes={scopes} redirect={qs['redirect_uri'][0]}")


def test_state_sekali_pakai_dan_milik_benar():
    st = _state(osl.build_authorize_url("a@b.c"))
    osl.pop_owner(st)
    with pytest.raises(ValueError):
        osl.pop_owner(st)
    bad = "A" + st[1:]
    osl._PENDING[bad] = {"email": "a@b.c", "ts": osl._now()}
    with pytest.raises(ValueError):
        osl.pop_owner(bad)
    print("SLACK_STATE_REPLAY=ditolak SLACK_STATE_TAMPER=ditolak")


def test_exchange_mengirim_kredensial_dan_mengembalikan_identity():
    st = _state(osl.build_authorize_url("a@b.c"))
    client = _Client(_Res(200, _slack_ok()))
    data = osl.exchange_code("CODE-SLACK", st, client=client)
    sent = client.calls[0]["data"]
    assert client.calls[0]["url"] == osl.ACCESS_ENDPOINT
    cfg = osl.config()
    assert sent["code"] == "CODE-SLACK"
    assert sent["client_id"] == cfg["client_id"] and sent["client_secret"]
    assert sent["redirect_uri"] == cfg["redirect_uri"]
    assert data["access_token"] == "xoxb-BOT-TOKEN"
    assert data["team_id"] == "T0TEAM" and data["team_name"] == "Workspace Uji"
    assert data["email"] == "a@b.c"
    print(f"EXCHANGE_SLACK=ok team={data['team_name']} bot_user={data['bot_user_id']}")


def test_http_200_tapi_ok_false_harus_gagal():
    """Kelas bug utama: Slack mengirim galat sebagai HTTP 200 + ok:false."""
    st = _state(osl.build_authorize_url("a@b.c"))
    client = _Client(_Res(200, {"ok": False, "error": "invalid_redirect_uri"}))
    with pytest.raises(RuntimeError) as e:
        osl.exchange_code("CODE", st, client=client)
    assert "invalid_redirect_uri" in str(e.value)
    print(f"SLACK_OK_FALSE=gagal_pesan_jujur msg={str(e.value)[:70]}")


def test_body_bukan_json_tidak_menjatuhkan_proses():
    st = _state(osl.build_authorize_url("a@b.c"))
    client = _Client(_Res(200, ValueError("bukan json")))
    with pytest.raises(RuntimeError):
        osl.exchange_code("CODE", st, client=client)
    print("SLACK_BODY_RUSAK=pesan_jujur_tanpa_crash")


def test_installation_disimpan_terenkripsi(monkeypatch):
    store: dict = {}
    _fake_vault(monkeypatch, store)
    st = _state(osl.build_authorize_url("a@b.c"))
    data = osl.exchange_code("CODE", st, client=_Client(_Res(200, _slack_ok())))
    assert osl.save_installation("a@b.c", data) is True
    ct = store[("a@b.c", osl.PROVIDER)]
    assert "xoxb-BOT-TOKEN" not in ct, "bot token tidak boleh tersimpan plaintext"
    assert osl.bot_token("a@b.c") == "xoxb-BOT-TOKEN"
    status = osl.connection_status("a@b.c")
    assert status["connected"] is True and status["team_name"] == "Workspace Uji"
    assert "xoxb-BOT-TOKEN" not in json.dumps(status), "status UI tidak boleh memuat token"
    print(f"VAULT_SLACK_STORED={osl.PROVIDER} ciphertext_len={len(ct)} plaintext_bocor=False")


def test_bot_token_tanpa_koneksi_memberi_pesan_jelas(monkeypatch):
    store: dict = {}
    _fake_vault(monkeypatch, store)
    with pytest.raises(RuntimeError) as e:
        osl.bot_token("belum@terhubung")
    assert "Connect" in str(e.value)
    print("SLACK_TANPA_KONEKSI=pesan_connect")


def test_config_membaca_redirect_uri_yang_harus_didaftarkan():
    cfg = osl.config("https://api.example.com/")
    assert cfg["redirect_uri"] == "https://api.example.com/oauth/slack/callback"
    assert osl.configured() is True
    print(f"SLACK_REDIRECT_URI={cfg['redirect_uri']}")

