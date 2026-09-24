"""oauth_google.py — OAuth 2.1 Authorization Code + PKCE untuk Google Sheets.

KENAPA MODUL SENDIRI: alur ini punya tiga hal yang mudah salah dan harus bisa
diuji TANPA browser:
  1. **PKCE** — `code_verifier` disimpan di sisi SERVER (state → verifier),
     karena kalau ia ikut ke URL, PKCE kehilangan gunanya.
  2. **refresh_token** — hanya dikirim Google bila `access_type=offline` DAN
     `prompt=consent`. Ini satu-satunya cara token 1 jam diperpanjang otomatis;
     `tests/test_oauth_google.py` mengunci keduanya.
  3. **state bertanda tangan** — backend tidak punya sesi cookie, jadi identitas
     user dibawa di `state` yang ditandatangani HMAC supaya callback tidak bisa
     menyimpan token ke akun orang lain.

BATASAN YANG SAYA SADARI (ditulis supaya tidak menyesatkan): `_PENDING`
(state → verifier) adalah penyimpanan **in-memory** ber-TTL. Cukup untuk
dev/self-hosted satu worker; deployment multi-worker butuh Redis/DB. Kalau
proses restart di tengah consent, user harus klik Connect ulang.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse

import httpx

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
PROVIDER = "google_sheets"
STATE_TTL_S = 600
STORE_TTL_S = 900
# Token dianggap perlu refresh 120 detik sebelum jatuh (hindari balapan jam).
REFRESH_LEEWAY_S = 120

_PENDING: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def config(redirect_base: str | None = None) -> dict:
    base = (redirect_base or os.getenv("OAUTH_REDIRECT_BASE") or "http://localhost:8000").rstrip("/")
    return {
        "client_id": (os.getenv("GOOGLE_CLIENT_ID") or "").strip(),
        "client_secret": (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip(),
        "redirect_uri": f"{base}/oauth/google/callback",
    }


def configured() -> bool:
    c = config()
    return bool(c["client_id"] and c["client_secret"])


def _state_secret() -> bytes:
    raw = (
        os.getenv("OAUTH_STATE_SECRET")
        or os.getenv("VAULT_SECRET_KEY")
        or os.getenv("VAULT_PASSWORD")
        or ""
    ).strip()
    if not raw:
        # Gagal keras: state yang bisa ditempa = token bisa ditulis ke akun lain.
        raise RuntimeError(
            "OAUTH_STATE_SECRET/VAULT_SECRET_KEY/VAULT_PASSWORD belum diset: "
            "state OAuth tidak bisa ditandatangani dengan aman."
        )
    return hashlib.sha256(("oauth-state:" + raw).encode()).digest()


def sign_state(email: str, now: float | None = None) -> str:
    ts = int(now if now is not None else _now())
    nonce = secrets.token_urlsafe(12)
    payload = f"{email}|{ts}|{nonce}"
    mac = hmac.new(_state_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{mac}".encode()).decode().rstrip("=")


def verify_state(state: str, now: float | None = None) -> str:
    """Email bila `state` sah & belum kedaluwarsa; selain itu `ValueError`."""
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        email, ts, nonce, mac = raw.rsplit("|", 3)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"state OAuth tidak dapat dibaca: {type(exc).__name__}") from exc
    payload = f"{email}|{ts}|{nonce}"
    expect = hmac.new(_state_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, expect):
        raise ValueError("state OAuth tidak sah (tanda tangan tidak cocok)")
    if (now if now is not None else _now()) - int(ts) > STATE_TTL_S:
        raise ValueError("state OAuth kedaluwarsa (>10 menit)")
    return email


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def build_authorize_url(email: str, redirect_base: str | None = None) -> str:
    """URL consent + simpan verifier di server (dipakai saat callback)."""
    cfg = config(redirect_base)
    if not cfg["client_id"]:
        raise RuntimeError("GOOGLE_CLIENT_ID belum diset")
    state = sign_state(email)
    verifier, challenge = _pkce_pair()
    _gc_pending()
    _PENDING[state] = {"verifier": verifier, "email": email, "ts": _now()}
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": SHEETS_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Dua parameter ini WAJIB agar Google mengirim refresh_token.
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _gc_pending(now: float | None = None) -> None:
    t = now if now is not None else _now()
    for key in [k for k, v in _PENDING.items() if t - v["ts"] > STORE_TTL_S]:
        _PENDING.pop(key, None)


def pop_verifier(state: str) -> tuple[str, str]:
    """(email, verifier) untuk `state`, lalu dibuang (sekali pakai)."""
    _gc_pending()
    item = _PENDING.pop(state, None)
    if not item:
        raise ValueError("state OAuth tidak dikenal/kedaluwarsa — ulangi proses Connect")
    email = verify_state(state)
    if email != item["email"]:
        raise ValueError("state OAuth tidak cocok dengan pemiliknya")
    return email, item["verifier"]


def _json(res) -> dict:
    try:
        return res.json()
    except Exception:  # noqa: BLE001
        return {}


def _token_error(status: int, body: dict, phase: str) -> str:
    """Pesan galat yang aman dibaca user (tanpa membocorkan token/secret)."""
    err = str(body.get("error") or "").strip()
    desc = str(body.get("error_description") or "").strip()[:160]
    tail = f" — {desc}" if desc else ""
    return f"Google menolak {phase} token (HTTP {status}): {err or 'tanpa kode'}{tail}"


def _normalize(body: dict) -> dict:
    expires_in = body.get("expires_in")
    try:
        expires_in = int(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_in = None
    return {
        "access_token": body.get("access_token") or "",
        "refresh_token": body.get("refresh_token") or "",
        "scope": body.get("scope") or "",
        "token_type": body.get("token_type") or "Bearer",
        "expires_at": (_now() + expires_in) if expires_in else None,
    }


def exchange_code(code: str, state: str, *, client: httpx.Client | None = None) -> dict:
    """Tukar `code` menjadi token (belum disimpan)."""
    email, verifier = pop_verifier(state)
    cfg = config()
    data = {
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"],
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }
    own = client is None
    c = client or httpx.Client(timeout=20)
    try:
        res = c.post(TOKEN_ENDPOINT, data=data)
        body = _json(res)
        if res.status_code != 200 or "access_token" not in body:
            raise RuntimeError(_token_error(res.status_code, body, "exchange"))
        tokens = _normalize(body)
        tokens["email"] = email
        return tokens
    finally:
        if own:
            c.close()


def refresh_tokens(tokens: dict, *, client: httpx.Client | None = None) -> dict:
    """Perbarui access_token memakai refresh_token. Raise bila tidak bisa."""
    rt = (tokens or {}).get("refresh_token")
    if not rt:
        raise RuntimeError(
            "refresh_token tidak ada: user harus Connect ulang (Google hanya mengirim "
            "refresh_token saat prompt=consent & access_type=offline)"
        )
    cfg = config()
    data = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": rt,
        "grant_type": "refresh_token",
    }
    own = client is None
    c = client or httpx.Client(timeout=20)
    try:
        res = c.post(TOKEN_ENDPOINT, data=data)
        body = _json(res)
        if res.status_code != 200 or "access_token" not in body:
            raise RuntimeError(_token_error(res.status_code, body, "refresh"))
        merged = dict(tokens)
        merged.update(_normalize(body))
        # Saat refresh, Google TIDAK mengirim ulang refresh_token: pertahankan lama.
        merged["refresh_token"] = rt
        return merged
    finally:
        if own:
            c.close()


def needs_refresh(tokens: dict, now: float | None = None) -> bool:
    exp = (tokens or {}).get("expires_at")
    if not exp:
        return True  # tanpa info kedaluwarsa: anggap perlu (aman)
    return (now if now is not None else _now()) >= float(exp) - REFRESH_LEEWAY_S


# ---------------------------------------------------------------------------
# PENYIMPANAN: satu blob JSON terenkripsi Fernet di kolom `user_vault` yang
# sudah ada (provider `google_sheets`) => TIDAK perlu migrasi skema.
# ---------------------------------------------------------------------------
def save_tokens(email: str, tokens: dict) -> bool:
    """Simpan token (terenkripsi). Mengembalikan True bila tersimpan."""
    import database as db  # import lokal: hindari siklus impor saat modul di-test
    import vault_security as vs

    payload = {k: v for k, v in (tokens or {}).items() if k != "email"}
    blob = json.dumps(payload, separators=(",", ":"))
    return bool(db.vault_save(email, PROVIDER, vs.encrypt_key(blob)))


def load_tokens(email: str) -> dict | None:
    """Baca token; None bila belum ada / rusak (tidak melempar ke pemanggil)."""
    import database as db
    import vault_security as vs

    try:
        ct = db.vault_get(email, PROVIDER)
    except Exception:  # noqa: BLE001 - DB sesaat bermasalah != user harus connect ulang
        return None
    if not ct:
        return None
    try:
        return json.loads(vs.decrypt_key(ct))
    except Exception:  # noqa: BLE001
        return None


def clear_tokens(email: str) -> bool:
    import database as db

    try:
        return bool(db.vault_delete(email, PROVIDER))
    except Exception:  # noqa: BLE001
        return False


def access_token(email: str, *, client: httpx.Client | None = None) -> str:
    """access_token yang masih berlaku, dengan refresh otomatis bila hampir jatuh.

    Raise RuntimeError dengan pesan manusiawi bila user belum Connect atau
    refresh_token sudah tidak berlaku (mis. dicabut user di Google).
    """
    tokens = load_tokens(email)
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError("belum terhubung ke Google Sheets (Connect dulu)")
    if needs_refresh(tokens):
        tokens = refresh_tokens(tokens, client=client)
        save_tokens(email, tokens)
    return str(tokens.get("access_token") or "")


def connection_status(email: str) -> dict:
    """Ringkasan untuk UI `/settings` TANPA membocorkan nilai token."""
    tokens = load_tokens(email)
    if not tokens:
        return {"connected": False, "provider": PROVIDER}
    exp = tokens.get("expires_at")
    return {
        "connected": True,
        "provider": PROVIDER,
        "scope": tokens.get("scope") or "",
        "has_refresh_token": bool(tokens.get("refresh_token")),
        "expires_in_s": int(float(exp) - _now()) if exp else None,
    }


