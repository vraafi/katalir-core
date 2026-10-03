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
# BUG/FITUR 2026-10-03 (generic): definisi TIDAK lagi ditulis di sini.
# Satu-satunya sumber kebenaran adalah `providers.credential_schemas`. Modul ini
# hanya menangani token, validasi, dan penyimpanan - jadi menambah provider
# cukup menambah satu entri di registry, tanpa menyentuh file ini maupun
# frontend (frontend menerima descriptor field apa adanya dari server).
from providers.credential_schemas import (  # noqa: E402
    CREDENTIAL_SCHEMAS,
    get_all_schemas,
    get_schema,
    providers_using_form,
    providers_using_oauth,
)

PROVIDER_FORMS: dict[str, dict[str, Any]] = {
    key: spec for key, spec in CREDENTIAL_SCHEMAS.items() if spec.get("mode") == "form"
}

OAUTH_ONLY_PROVIDERS: set[str] = set(providers_using_oauth())

__all__ = [
    "TOKEN_TTL_S",
    "PROVIDER_FORMS",
    "OAUTH_ONLY_PROVIDERS",
    "issue_resume_token",
    "verify_resume_token",
    "has_inline_form",
    "build_requires_credential",
    "build_requires_oauth",
    "validate_and_save",
    "credential_catalog",
    "get_all_schemas",
]


def has_inline_form(provider: str) -> bool:
    """True bila provider punya form inline yang bisa dirender di chat."""
    spec = get_schema(provider)
    return bool(spec and spec.get("mode") == "form")


def build_requires_oauth(provider: str, user_email: str,
                         session_id: str | None = None) -> dict:
    """Bentuk respons `requires_oauth` dari registry (bukan form token)."""
    spec = get_schema(provider)
    if not spec or spec.get("mode") != "oauth_redirect":
        raise ValueError(f"provider {provider!r} bukan mode oauth_redirect")
    return {
        "status": "requires_oauth",
        "provider": str(provider).strip().lower(),
        "display_name": spec["display_name"],
        "icon": spec.get("icon", ""),
        "oauth_url": spec.get("authorize_path", ""),
        "scopes": list(spec.get("scopes") or []),
        "session_id": session_id,
        # Penjelas jujur kenapa bukan form: user tidak bisa menempel token OAuth.
        "note": (
            "Provider ini memakai OAuth. Token-nya tidak bisa ditempel manual, "
            "jadi kamu akan diarahkan ke halaman persetujuan provider."
        ),
    }


def credential_catalog() -> str:
    """Ringkasan registry untuk disisipkan ke konteks AI."""
    lines = []
    for key, spec in CREDENTIAL_SCHEMAS.items():
        mode = spec.get("mode")
        if mode == "form":
            fields = ", ".join(f["name"] for f in spec.get("fields", []))
            lines.append(f"- {key} (form): {fields}")
        else:
            lines.append(f"- {key} (oauth_redirect): lewat tombol Connect")
    return "\n".join(lines)


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
        "icon": spec.get("icon", ""),
        # Salinan dalam, bukan reference:cefek modifikasi di tempat lain
        # tidak boleh mengubah definisi global.
        "fields": [dict(f) for f in spec["fields"]],
        "resume_token": issue_resume_token(user_email, prov, ttl_s=ttl_s),
        "expires_in": int(ttl_s),
        "tool_call_id": tool_call_id,
        "session_id": session_id,
        "secure_note": "Disimpan terenkripsi di vault Anda.",
    }


def validate_and_save(provider: str, credentials: dict, user_email: str) -> dict:
    """Validasi input form sesuai registry, lalu simpan SEMUA field terenkripsi.

    Generic: bekerja untuk provider mana pun ber-`mode: form`, bukan cuma
    Gmail. Field opsional yang tidak diisi DIHAPUS (bukan disimpan sebagai
    string kosong) supaya `vault_load` bisa membedakan "tidak diisi" dari
    "diisi string kosong".

    Mengembalikan ringkasan tanpa nilai rahasianya. Tidak pernah melempar
    error yang memuat nilai input.
    """
    prov = str(provider or "").strip().lower()
    spec = get_schema(prov)
    if not spec or spec.get("mode") != "form":
        raise ValueError(f"provider {prov!r} tidak punya form inline.")
    if prov in OAUTH_ONLY_PROVIDERS:
        raise ValueError(f"{prov} memakai OAuth, bukan form manual.")

    incoming = dict(credentials or {})
    clean: dict[str, str] = {}
    for field in spec.get("fields", []):
        name = field["name"]
        raw = str(incoming.get(name) or "")
        if field.get("transform") == "strip_spaces":
            # Google menampilkan App Password bergROUP; IMAP butuh tanpa spasi.
            raw = "".join(raw.split())
        else:
            raw = raw.strip()
        if not raw:
            if field.get("required"):
                raise ValueError(f"{field['label']} wajib diisi.")
            continue  # opsional kosong -> jangan disimpan
        min_len = int(field.get("min_length") or 0)
        if min_len and len(raw) < min_len:
            raise ValueError(
                f"{field['label']} minimal {min_len} karakter "
                f"(sekarang {len(raw)}).")
        clean[name] = raw

    if not clean:
        raise ValueError("Tidak ada credential yang diisi.")

    vault_provider = spec.get("vault_provider") or prov
    save_vault_credential(user_email, vault_provider, clean)

    # Ringkasan: field `secret` disamarkan, sisanya tampil apa adanya
    # (mis. alamat email memang perlu ditampilkan balik).
    summary = {
        k: ("***" if spec_field_is_secret(spec, k) else v)
        for k, v in clean.items()
    }
    return {
        "provider": prov,
        "display_name": spec["display_name"],
        "vault_provider": vault_provider,
        "saved": summary,
    }


def spec_field_is_secret(spec: dict, field_name: str) -> bool:
    """True bila field ditandai `secret` di registry."""
    for f in spec.get("fields", []):
        if f["name"] == field_name:
            return bool(f.get("secret"))
    return False


def save_vault_credential(user_email: str, vault_provider: str,
                          values: dict[str, str]) -> None:
    """Simpan dict credential (multi-field) sebagai SATU ciphertext JSON.

    Satu baris `user_vault` per provider. Semua field di-encode jadi JSON lalu
    dienkripsi Fernet, jadi tidak ada field yang tersimpan plaintext.
    """
    import database as db
    import vault_security as vs

    cipher = vs.encrypt_key(json.dumps(values, ensure_ascii=False, sort_keys=True))
    if not db.vault_save(user_email, vault_provider, cipher):
        raise ValueError("Gagal menyimpan credential ke vault.")


def load_vault_credential(user_email: str, vault_provider: str) -> dict | None:
    """Baca credential multi-field dari vault. None bila belum ada / rusak."""
    import database as db
    import vault_security as vs

    cipher = db.vault_get(user_email, vault_provider)
    if not cipher:
        return None
    try:
        data = json.loads(vs.decrypt_key(cipher))
    except Exception:  # noqa: BLE001 - vault rusak/rotasi kunci
        return None
    return data if isinstance(data, dict) else None


def has_credential(user_email: str, provider: str) -> bool:
    """Cek apakah user sudah punya credential untuk provider ini."""
    spec = get_schema(provider)
    if not spec:
        return False
    return load_vault_credential(user_email, spec.get("vault_provider") or provider) is not None