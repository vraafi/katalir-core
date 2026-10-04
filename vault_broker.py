"""vault_broker.py — pemisahan credential dari LLM (rujuk `secret://`).

MASALAH YANG DISELESAIKAN
-------------------------
Tanpa broker ini, model harus melihat nilai kredensial_asli untuk bisa
mengisi parameter tool. Itu berarti rahasia user masuk ke konteks LLM,
terekam di log gateway, dan bisa bocor lewat prompt injection.

BROKER
------
AI hanya pernah menulis referensi:

    {"tool": "trigger_gmail_imap",
     "args": {"email": "user@gmail.com",
              "app_password": "secret://gmail_imap/app_password"}}

Broker me-resolve referensi itu ke nilai asli TEBAK DI DALAM PROSES,
tepat sebelum handler dijalankan. Nilai asli tidak pernah masuk ke
prompt, tidak pernah masuk ke respons, dan tidak pernah ditulis ke log.

Prinsipnya sama dengan yang dipakai Infisical agent-vault ("credential
brokering") dan secret-broker ("agents get secret://... references").

CATATAN API (hasil verifikasi repo, bukan asumsi)
-------------------------------------------------
Brief awal menulis `from vault import vault_get`. Modul `vault.py` TIDAK
ADA di repo ini, dan `database.vault_get()` yang ada mengembalikan
CIPHERTEXT, bukan dict field - jadi tidak bisa dipakai untuk `resolve_secret`.
Jalur baca yang benar (sudah dipakai runtime) adalah
`credential_forms.load_vault_credential()` yang sudah mendekripsi JSON.
"""

from __future__ import annotations

import re
from typing import Any

#: `secret://<provider>/<field>` - field boleh bersarang (mis. "a.b").
SECRET_REF_PATTERN = re.compile(r"^secret://([a-z0-9_\-]+)/(.+)$", re.IGNORECASE)

#: Panjang nilai rahasia yang ditampilkan di pesan error.
_MASK = "***"


class CredentialMissingError(Exception):
    """Kredensial untuk provider/field yang diminta tidak ada di vault."""

    def __init__(self, provider: str, user_email: str = ""):
        self.provider = provider
        # Email sengaja tidak ikut pesan: pesan error bisa masuk log/UI.
        super().__init__(
            f"Credential '{provider}' belum tersimpan. "
            "Isi lewat form credential di chat."
        )


class SecretRefError(ValueError):
    """Referensi `secret://` tidak valid bentuknya."""


def is_secret_ref(value: Any) -> bool:
    """True bila `value` adalah referensi `secret://`."""
    return isinstance(value, str) and value.lower().startswith("secret://")


def resolve_secret(ref: str, user_email: str) -> str:
    """`secret://provider/field` -> nilai asli dari vault.

    Raises:
        SecretRefError: bentuk referensi salah.
        CredentialMissingError: provider/field tidak ada di vault.
    """
    if not is_secret_ref(ref):
        raise SecretRefError(f"Bukan referensi secret://: {ref[:40]!r}")
    m = SECRET_REF_PATTERN.match(ref.strip())
    if not m:
        raise SecretRefError(f"Format secret:// tidak valid: {ref[:40]!r}")
    provider, field = m.group(1).lower(), m.group(2)

    from credential_forms import load_vault_credential  # impor lokal: evitar siklus
    from providers.credential_schemas import get_schema

    spec = get_schema(provider) or {}
    vault_provider = spec.get("vault_provider") or provider
    cred = load_vault_credential(user_email, vault_provider)
    if not cred:
        raise CredentialMissingError(provider)
    if field not in cred:
        raise CredentialMissingError(f"{provider}.{field}")
    return str(cred[field])


def redact(value: Any) -> Any:
    """Salinan `args` dengan semua nilai rahasia diganti mask.

    Dipakai saat menulis args ke log/respons supaya nilai asli tidak bocor.
    """
    if isinstance(value, str):
        return _MASK if is_secret_ref(value) else value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def resolve_secrets_in_args(args: dict[str, Any], user_email: str) -> dict[str, Any]:
    """Resolve SEMUA `secret://` di dalam args (rekursif, termasuk dict/list).

    Nilai yang bukan referensi secret:// diteruskan apa adanya.
    """
    if not isinstance(args, dict):
        return args
    out: dict[str, Any] = {}
    for key, value in args.items():
        if is_secret_ref(value):
            out[key] = resolve_secret(value, user_email)
        elif isinstance(value, dict):
            out[key] = resolve_secrets_in_args(value, user_email)
        elif isinstance(value, list):
            out[key] = [
                resolve_secret(v, user_email) if is_secret_ref(v)
                else (resolve_secrets_in_args(v, user_email)
                      if isinstance(v, dict)
                      else (redact(v) if isinstance(v, list) else v))
                for v in value
            ]
        else:
            out[key] = value
    return out


__all__ = [
    "SECRET_REF_PATTERN",
    "CredentialMissingError",
    "SecretRefError",
    "is_secret_ref",
    "redact",
    "resolve_secret",
    "resolve_secrets_in_args",
]