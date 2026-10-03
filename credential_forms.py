"""credential_forms.py — form credential INLINE di dalam chat.

MASALAH UX YANG DISELESAIKAN (2026-10-03)
------------------------------------------
Sebelumnya saat tool butuh credential, chat ikut melakukan redirect:
user diminta membuka halaman Vault/Settings, mengisi credential di sana, lalu
kembali ke chat. Itu memutus alur berpikir user dan mudah dilupakan
("jadi di mana dulu?"). Pola 2026 yang dipakai di sini:

    model butuh credential -> server balas `requires_credential` + DESKRIPSI
    FIELD -> frontend merender <CredentialForm /> DI DALAM bubble chat ->
    user isi -> POST /chat/resume -> credential disimpan terenkripsi -> tool
    langsung jalan (frontend mengirim ulang prompt aslinya).

Pola ini setara MCP (server balas CredentialMissing, client render form) dan
Vercel AI SDK v5 (tool part berstatus `requires-action`).

DESIGN: resume_token TANPA state server
---------------------------------------
`resume_token` sengaja stateless (HMAC, TTL 30 menit), bukan baris database
yang menyimpan prompt/percakapan:
  * tidak ada data percakapan user yang mendarat di tabel baru,
  * tetap valid walau instance Railway restart atau diskalakan,
  * bocor token hanya membuka form - bukan membocorkan isi chat.
Frontend sudah memegang prompt aslinya di message list-nya, jadi
"melanjutkan workflow" = mengirim ulang prompt itu. Tidak perlu server
menyimpan apa pun.

SECURITY
--------
  * Token ditandatangani, memuat email user + provider + masa berlaku.
    `/chat/resume` menolak token milik user lain.
  * Credential tidak pernah masuk token, tidak pernah di-log, dan tidak
    pernah dikembalikan ke klien.
  * Penyimpanan tetap `vault_security` (Fernet) -> `user_vault`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Callable

TOKEN_TTL_S = 30 * 60  # 30 menit, sesuai brief.


# ---------------------------------------------------------------------------
# Signing key
# ---------------------------------------------------------------------------
_EPHEMERAL_KEY: bytes | None = None


def _signing_key() -> bytes:
    """Kunci HMAC untuk resume_token.

    Pakai `VAULT_SECRET_KEY` yang sama dengan enkripsi vault. Kalau env itu
    kosong, vault sendiri sudah otomatis generate kunci per-session (dan
    credential lama tidak akan terbaca) - jadi ketergantungan ini bukan hal
    baru: di produksi `VAULT_SECRET_KEY` wajib di-set.

    Tanpa env, kunci ephemeral di-cache per-PROCESS (bukan per-panggilan):
    kalau di-generate tiap call, `issue` dan `verify` akan memakai kunci
    berbeda dan setiap token otomatis ditolak - fitur mati total. Sifat
    across-instance tetap fail-closed: token dari instance lain ditolak.
    """
    global _EPHEMERAL_KEY
    secret = (os.getenv("VAULT_SECRET_KEY") or "").strip()
    if secret:
        return hashlib.sha256(f"resume::{secret}".encode("utf-8")).digest()
    if _EPHEMERAL_KEY is None:
        _EPHEMERAL_KEY = hashlib.sha256(
            f"resume-ephemeral::{os.urandom(32).hex()}".encode("utf-8")).digest()
    return _EPHEMERAL_KEY


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ---------------------------------------------------------------------------
# resume_token
# ---------------------------------------------------------------------------
def issue_resume_token(user_email: str, provider: str, ttl_s: int = TOKEN_TTL_S) -> str:
    """Terbitkan token opaque bertanda tangan untuk satu provider."""
    payload = {
        "e": str(user_email or "").strip().lower(),
        "p": str(provider or "").strip().lower(),
        "exp": int(time.time() + max(60, int(ttl_s))),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_resume_token(token: str, user_email: str) -> str:
    """Verifikasi token dan kembalikan `provider`.

    Melempar `ValueError` bila rusak, kedaluwarsa, atau milik user lain.
    """
    parts = str(token or "").split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError("resume_token tidak valid.")
    body, sig = parts
    expect = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        raise ValueError("resume_token tidak valid.")
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("resume_token tidak bisa dibaca.") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError("resume_token sudah kedaluwarsa. Kirim ulang permintaan.")
    if str(payload.get("e") or "").lower() != str(user_email or "").strip().lower():
        # Token milik user lain: tolak tanpa membocorkan detail apa pun.
        raise ValueError("resume_token tidak milik akun ini.")
    provider = str(payload.get("p") or "").strip().lower()
    if not provider:
        raise ValueError("resume_token tanpa provider.")
    return provider


# ---------------------------------------------------------------------------
# Definisi form per provider
# ---------------------------------------------------------------------------
# `fields` dikirim apa adanya ke frontend - satu sumber kebenaran untuk label,
# tipe input, validasi minimum, dan tautan bantuan. Menambah provider baru =
# menambah satu entri di sini, tanpa menyentuh frontend.
PROVIDER_FORMS: dict[str, dict[str, Any]] = {
    "gmail_imap": {
        "display_name": "Gmail (via App Password)",
        # Password adalah kredensial nyata: TIDAK pernah dikembalikan ke klien.
        "writer": "gmail_imap",
        "fields": [
            {
                "name": "email",
                "label": "Alamat Gmail",
                "type": "email",
                "placeholder": "nama@gmail.com",
                "required": True,
                "min_length": 3,
            },
            {
                "name": "app_password",
                "label": "App Password (16 karakter)",
                "type": "password",
                "placeholder": "xxxx xxxx xxxx xxxx",
                "required": True,
                "min_length": 16,
                # Spasi boleh diketik user (Google menampilkannya bergROUP);
                # normalisasi terjadi di server.
                "transform": "strip_spaces",
                "help_url": "https://myaccount.google.com/apppasswords",
                "help_text": "Buat App Password di Google Account Anda (butuh 2FA aktif).",
            },
        ],
    },
}

# Provider yang authenticate lewat OAuth: TIDAK boleh pakai form token manual
# (user tidak bisa menempel access token Google dengan benar). Provider ini
# tetap memakai jalur tombol Connect seperti sebelumnya.
OAUTH_ONLY_PROVIDERS = {"google_sheets", "slack"}


def has_inline_form(provider: str) -> bool:
    """True bila provider punya form inline yang bisa dirender di chat."""
    return str(provider or "").strip().lower() in PROVIDER_FORMS


def build_requires_credential(
    provider: str,
    user_email: str,
    session_id: str | None = None,
    tool_call_id: str | None = None,
    ttl_s: int = TOKEN_TTL_S,
) -> dict:
    """Bentuk respons `requires_credential` lengkap dengan form + token."""
    prov = str(provider or "").strip().lower()
    spec = PROVIDER_FORMS.get(prov)
    if spec is None:
        raise ValueError(f"tidak ada form inline untuk provider {prov!r}")
    return {
        "status": "requires_credential",
        "provider": prov,
        "display_name": spec["display_name"],
        # Salinan dalam, bukan reference:cefek modifikasi di tempat lain
        # tidak boleh mengubah definisi global.
        "fields": [dict(f) for f in spec["fields"]],
        "resume_token": issue_resume_token(user_email, prov, ttl_s=ttl_s),
        "expires_in": int(ttl_s),
        "tool_call_id": tool_call_id,
        "session_id": session_id,
        "secure_note": "Disimpan terenkripsi di vault Anda.",
    }


def _save_gmail_imap(creds: dict, user_email: str) -> None:
    import tools

    tools.save_gmail_imap_credential(
        user_email,
        str(creds.get("email") or "").strip(),
        str(creds.get("app_password") or ""),
    )


CREDENTIAL_WRITERS: dict[str, Callable[[dict, str], None]] = {
    "gmail_imap": _save_gmail_imap,
}


def validate_and_save(provider: str, credentials: dict, user_email: str) -> dict:
    """Validasi input form lalu simpan terenkripsi. Kembalikan ringkasan aman.

    Tidak pernah mengembalikan nilai credential.
    """
    prov = str(provider or "").strip().lower()
    writer = CREDENTIAL_WRITERS.get(prov)
    spec = PROVIDER_FORMS.get(prov)
    if writer is None or spec is None:
        raise ValueError(f"provider {prov!r} tidak punya form inline.")

    creds = dict(credentials or {})
    clean: dict[str, str] = {}
    for field in spec["fields"]:
        name = field["name"]
        val = str(creds.get(name) or "")
        if field.get("transform") == "strip_spaces":
            val = "".join(val.split())
        val = val.strip() if field.get("type") != "password" else val
        if field.get("required") and not val:
            raise ValueError(f"{field['label']} wajib diisi.")
        min_len = int(field.get("min_length") or 0)
        if min_len and len(val) < min_len:
            raise ValueError(
                f"{field['label']} minimal {min_len} karakter "
                f"(sekarang {len(val)}).")
        clean[name] = val

    writer(clean, user_email)
    # Ringkasan TANPA nilai credential.
    summary = {k: v for k, v in clean.items() if k not in ("app_password", "api_key")}
    summary["app_password"] = "***" if "app_password" in clean else None
    return {"provider": prov, "display_name": spec["display_name"], "saved": summary}