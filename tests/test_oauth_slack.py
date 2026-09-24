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


# ---------------------------------------------------------------------------
# ENDPOINT HTTP (TestClient) — misi meminta bukti jalur /callback & /status
# ---------------------------------------------------------------------------
def _endpoint_client(monkeypatch, store: dict):
    """TestClient + JWT palsu + Vault palsu.

    JWT di-patch di modul `security` (bukan di api_server) karena api_server
    memanggil `security.get_current_user(...)` secara dinamis — jadi patch ini
    berlaku untuk SEMUA endpoint yang butuh login.
    """
    import api_server
    import security
    from fastapi.testclient import TestClient

    _fake_vault(monkeypatch, store)
    monkeypatch.setattr(security, "get_current_user",
                        lambda authorization=None: {"email": "u@k.test"})
    # Header JWT default: `/oauth/slack/status` sengaja hanya memuat status
    # per-user bila Authorization dikirim (tanpa itu ia ramah-probe: connected
    # false). Pakai header supaya tes menguji jalur UI yang berlogin.
    return TestClient(api_server.app, headers={"Authorization": "Bearer uji-jwt"}), api_server



def test_callback_state_tidak_dikenal_ditolak(monkeypatch):
    """State asing (CSRF/replay) TIDAK boleh menukar code apa pun."""
    store: dict = {}
    client, srv = _endpoint_client(monkeypatch, store)
    r = client.get("/oauth/slack/callback?code=CODE&state=STATE-PALSU",
                   follow_redirects=False)
    assert r.status_code == 302
    assert "slack=error" in r.headers["location"]
    assert "reason=exchange_failed" in r.headers["location"]
    assert store == {}, "tidak boleh ada apa pun tersimpan saat state ditolak"
    print(f"CALLBACK_STATE_PALSU=302 {r.headers['location']}")


def test_callback_menyimpan_ke_vault_dan_status_jadi_connected(monkeypatch):
    """Jalur UTUH: /authorize -> /callback -> Vault terenkripsi -> /status."""
    store: dict = {}
    client, srv = _endpoint_client(monkeypatch, store)
    # State asli dari endpoint authorize, tapi klien Slack-nya palsu (tanpa jaringan).
    state = _state(osl.build_authorize_url("u@k.test"))
    monkeypatch.setattr(osl, "httpx", type("H", (), {"Client": lambda *a, **k: _Client(_Res(200, _slack_ok()))}))

    r = client.get(f"/oauth/slack/callback?code=CODE&state={state}",
                   follow_redirects=False)
    assert r.status_code == 302
    assert "slack=connected" in r.headers["location"], r.headers["location"]
    ct = store[("u@k.test", "slack")]
    assert "xoxb-BOT-TOKEN" not in ct, "Vault harus terenkripsi"

    st = client.get("/oauth/slack/status").json()
    assert st["connected"] is True and st["team_name"] == "Workspace Uji"
    assert "xoxb-BOT-TOKEN" not in json.dumps(st)
    print(f"CALLBACK_TO_VAULT=ok redirect={r.headers['location']} "
          f"status_connected={st['connected']} team={st['team_name']}")


def test_status_kosong_berarti_belum_connect(monkeypatch):
    store: dict = {}
    client, _ = _endpoint_client(monkeypatch, store)
    st = client.get("/oauth/slack/status").json()
    assert st["implemented"] is True and st["connected"] is False
    assert st["team_name"] == "" and st["slack"]["connected"] is False
    assert st["keys_total"] == 5
def test_callback_exchange_gagal_tidak_bocor_secret(monkeypatch):
    """Slack `ok:false` (HTTP 200) → laporan gagal JUJUR, secret tidak bocor.

    Dua hal diuji: (a) tidak ada yang tersimpan; (b) `client_secret` tidak
    pernah muncul di URL redirect (kelas kebocoran klasik saat pesan error
    ditempel mentah ke query string).
    """
    store: dict = {}
    client, _ = _endpoint_client(monkeypatch, store)
    state = _state(osl.build_authorize_url("u@k.test"))
    monkeypatch.setattr(osl, "httpx", type("H", (), {
        "Client": lambda *a, **k: _Client(_Res(200, {"ok": False, "error": "invalid_code"}))}))

    r = client.get(f"/oauth/slack/callback?code=CODE&state={state}",
                   follow_redirects=False)
    loc = r.headers["location"]
    assert r.status_code == 302 and "reason=exchange_failed" in loc
    secret = osl.config()["client_secret"]
    assert "client_secret" not in loc.lower()
    if secret:
        assert secret not in loc, "client_secret bocor ke URL redirect"
    assert store == {}, "exchange gagal tidak boleh menyimpan apa pun"
    print(f"CALLBACK_GAGAL=302 reason=exchange_failed secret_bocor=False secret_dicek={bool(secret)}")


def test_disconnect_slack_menghapus_vault_dan_status_kembali_kosong(monkeypatch):
    store: dict = {}
    client, _ = _endpoint_client(monkeypatch, store)
    state = _state(osl.build_authorize_url("u@k.test"))
    monkeypatch.setattr(osl, "httpx", type("H", (), {"Client": lambda *a, **k: _Client(_Res(200, _slack_ok()))}))
    client.get(f"/oauth/slack/callback?code=CODE&state={state}", follow_redirects=False)
    assert store, "prasyarat: instalasi tersimpan"

    d = client.delete("/oauth/slack")
    assert d.status_code == 200 and d.json()["disconnected"] is True
    assert store == {}, "Disconnect harus menghapus bot token dari Vault"
    assert client.get("/oauth/slack/status").json()["connected"] is False
    print("DISCONNECT_SLACK=vault_kosong status=connected_false")


def test_disconnect_google_menghapus_token(monkeypatch):
    store: dict = {}
    client, _ = _endpoint_client(monkeypatch, store)
    import oauth_google as og

    og.save_tokens("u@k.test", {"access_token": "AT-X", "refresh_token": "RT-X"})
    assert store, "prasyarat: token tersimpan"
    d = client.delete("/oauth/google")
    assert d.status_code == 200 and d.json()["provider"] == "google_sheets"
    assert store == {}
    print("DISCONNECT_GOOGLE=vault_kosong")


def test_authorize_mode_json_mengembalikan_url(monkeypatch):
    """Tombol Connect butuh URL, dan JWT harus tetap di header (bukan URL)."""
    store: dict = {}
    client, _ = _endpoint_client(monkeypatch, store)
    r = client.get("/oauth/slack/authorize?mode=json")
    assert r.status_code == 200
    url = r.json()["url"]
    parsed = urllib.parse.urlparse(url)
    assert parsed.netloc == "slack.com"
    assert urllib.parse.parse_qs(parsed.query)["state"], "state tetap wajib"
    assert "Bearer" not in url and "uji-jwt" not in url, "JWT tidak boleh ikut ke URL"
    print(f"AUTHORIZE_MODE_JSON=ok host={parsed.netloc}")


def test_authorize_mode_json_google_juga(monkeypatch):
    store: dict = {}
    client, _ = _endpoint_client(monkeypatch, store)
    r = client.get("/oauth/google/authorize?mode=json")
    assert r.status_code == 200
    url = r.json()["url"]
    assert urllib.parse.urlparse(url).netloc == "accounts.google.com"
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["code_challenge_method"] == ["S256"]
    print("AUTHORIZE_MODE_JSON_GOOGLE=ok host=accounts.google.com pkce=S256")




