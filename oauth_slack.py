"""oauth_slack.py — OAuth v2 Slack (bot token per workspace).

KENAPA MODUL TERPISAH: alur Slack berbeda dari Google —
  * scope diminta sebagai daftar dipisah koma di URL authorize,
  * pertukaran code memakai `oauth.v2.access` yang mengembalikan objek
    `{ok, access_token, team:{id,name}, bot_user_id}` (BUKAN format Google),
  * kegagalan datang sebagai `{"ok": false, "error": "..."}` dengan HTTP 200,
    sehingga memeriksa status code saja TIDAK cukup (kelas bug yang harus dicegah).

Helper `state` (HMAC + TTL) dan PKCE TIDAK dipakai di sini: Slack OAuth v2 tidak
memakai PKCE, dan state-nya diambil dari `oauth_google` supaya hanya ada SATU
implementasi penandatanganan state di repo (menghindari dua jalur yang bisa
menyimpang).
"""
from __future__ import annotations

import os
import time
import urllib.parse

import httpx

from oauth_google import STORE_TTL_S, sign_state, verify_state  # noqa: F401 (state dipakai bersama)

AUTHORIZE_ENDPOINT = "https://slack.com/oauth/v2/authorize"
ACCESS_ENDPOINT = "https://slack.com/api/oauth.v2.access"
PROVIDER = "slack"
# Scope ditulis eksplisit & minimal: chat:write untuk kirim, channels:read untuk
# daftar kanal, users:read untuk nama pengirim. Menambah scope = user melihat
# lebih banyak izin saat consent, jadi jangan "asal lengkap".
DEFAULT_SCOPES = ("chat:write", "channels:read", "users:read")

_PENDING: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def config(redirect_base: str | None = None) -> dict:
    base = (redirect_base or os.getenv("OAUTH_REDIRECT_BASE") or "http://localhost:8000").rstrip("/")
    return {
        "client_id": (os.getenv("SLACK_CLIENT_ID") or "").strip(),
        "client_secret": (os.getenv("SLACK_CLIENT_SECRET") or "").strip(),
        "signing_secret": (os.getenv("SLACK_SIGNING_SECRET") or "").strip(),
        "app_id": (os.getenv("SLACK_APP_ID") or "").strip(),
        "redirect_uri": f"{base}/oauth/slack/callback",
    }


def configured() -> bool:
    c = config()
    return bool(c["client_id"] and c["client_secret"])


def build_authorize_url(email: str, redirect_base: str | None = None,
                        scopes: tuple[str, ...] = DEFAULT_SCOPES) -> str:
    """URL consent Slack + simpan pemilik state di server (bukan di URL)."""
    cfg = config(redirect_base)
    if not cfg["client_id"]:
        raise RuntimeError("SLACK_CLIENT_ID belum diset")
    state = sign_state(email)
    _gc()
    _PENDING[state] = {"email": email, "ts": _now()}
    params = {
        "client_id": cfg["client_id"],
        "scope": ",".join(scopes),
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
    }
    return f"{AUTHORIZE_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _gc(now: float | None = None) -> None:
    t = now if now is not None else _now()
    for k in [k for k, v in _PENDING.items() if t - v["ts"] > STORE_TTL_S]:
        _PENDING.pop(k, None)


def pop_owner(state: str) -> str:
    """Email pemilik `state` (sekali pakai)."""
    _gc()
    item = _PENDING.pop(state, None)
    if not item:
        raise ValueError("state OAuth Slack tidak dikenal/kedaluwarsa — ulangi Connect")
    email = verify_state(state)
    if email != item["email"]:
        raise ValueError("state OAuth Slack tidak cocok dengan pemiliknya")
    return email


def save_installation(email: str, data: dict) -> bool:
    """Simpan installation (bot token + identitas workspace) TERENKRIPSI di Vault."""
    import database as db
    import vault_security as vs

    import json

    payload = {k: v for k, v in (data or {}).items() if k != "email"}
    return bool(db.vault_save(email, PROVIDER, vs.encrypt_key(json.dumps(payload, separators=(",", ":")))))


def load_installation(email: str) -> dict | None:
    import database as db
    import vault_security as vs

    import json

    try:
        ct = db.vault_get(email, PROVIDER)
    except Exception:  # noqa: BLE001
        return None
    if not ct:
        return None
    try:
        return json.loads(vs.decrypt_key(ct))
    except Exception:  # noqa: BLE001
        return None


def clear_installation(email: str) -> bool:
    import database as db

    try:
        return bool(db.vault_delete(email, PROVIDER))
    except Exception:  # noqa: BLE001
        return False


def bot_token(email: str) -> str:
    """Bot token untuk kirim pesan; raise bila belum terhubung."""
    data = load_installation(email)
    token = str((data or {}).get("access_token") or "")
    if not token:
        raise RuntimeError("belum terhubung ke Slack (Connect dulu)")
    return token


def connection_status(email: str) -> dict:
    """Ringkasan untuk UI — TANPA nilai token."""
    data = load_installation(email)
    if not data:
        return {"connected": False, "provider": PROVIDER}
    return {
        "connected": True,
        "provider": PROVIDER,
        "team_name": data.get("team_name") or "",
        "team_id": data.get("team_id") or "",
        "scope": data.get("scope") or "",
        "has_bot_token": bool(data.get("access_token")),
    }



def _check(body: dict, phase: str) -> dict:
    """Slack membalas HTTP 200 walau gagal -> `ok` WAJIB diperiksa.

    Ini kelas bug yang paling mudah lolos: memeriksa `res.status_code == 200`
    saja akan menganggap token berhasil didapat padahal Slack mengirim
    `{"ok": false, "error": "invalid_code"}`.
    """
    if not body.get("ok"):
        err = str(body.get("error") or "").strip() or "error tidak disebutkan"
        raise RuntimeError(f"Slack menolak {phase}: {err}")
    return body


def exchange_code(code: str, state: str, *, client: httpx.Client | None = None) -> dict:
    """Tukar `code` menjadi bot token + identitas workspace (belum disimpan)."""
    email = pop_owner(state)
    cfg = config()
    data = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
    }
    own = client is None
    c = client or httpx.Client(timeout=20)
    try:
        res = c.post(ACCESS_ENDPOINT, data=data)
        try:
            body = res.json()
        except Exception:  # noqa: BLE001
            body = {}
        body = _check(body, f"exchange (HTTP {res.status_code})")
        team = body.get("team") or {}
        return {
            "email": email,
            "access_token": str(body.get("access_token") or ""),
            "bot_user_id": str(body.get("bot_user_id") or ""),
            "team_id": str(team.get("id") or ""),
            "team_name": str(team.get("name") or ""),
            "scope": str(body.get("scope") or ""),
            "app_id": str((body.get("app_id") or cfg["app_id"]) or ""),
            "token_type": "bot",
            "saved_at": _now(),
        }
    finally:
        if own:
            c.close()
