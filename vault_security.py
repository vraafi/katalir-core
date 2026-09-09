"""
vault_security.py — Zero-Knowledge Vault (Application-layer encryption).

Enkripsi API-key user pada LAYER app (Fernet) ennen Supabase storage.
- Baca VAULT_SECRET_KEY dari .env; jika puuttuu, auto-generate kerran ja
  puskee konsoli-ohjeen Arsitekille (ettei katoa restartin yhteydessä).
- Ei koskaan log/print plaintext API key.
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]


def _load_or_generate() -> bytes:
    """Palauta Fermet-key (bytes). Jos puuttuu .env, generoi + ohje."""
    env_val = os.getenv("VAULT_SECRET_KEY", "").strip()
    if env_val:
        # Tuki sekä raw base64 url-safe (arkistai) että plaintext-pohjainen key.
        try:
            return env_val.encode("utf-8") if len(env_val) == 44 else _derive(env_val)
        except Exception:
            return _derive(env_val)
    # Auto-generoi (kerran per session). Ilmoita Arsitekille.
    generated = Fernet.generate_key() if Fernet else _derive(os.urandom(32).hex())
    os.environ["VAULT_SECRET_KEY"] = generated.decode("utf-8")
    print(
        "\n[VAULT] VAULT_SECRET_KEY ei löytynyt .env:stä — generoitiin."
        "\n[VAULT] LISÄÄ TÄMÄ .env:hen (tai Railway env) jotta avaimet pysyvät:"
        f"\nVAULT_SECRET_KEY={generated.decode('utf-8')}\n",
        file=sys.stderr,
    )
    return generated if isinstance(generated, bytes) else generated.encode("utf-8")


def _derive(secret: str) -> bytes:
    """Johda 32-byte Fernet-key mielivaltaisesta salaisuudesta (SHA-256)."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_KEY: bytes | None = None


def _fernet():
    global _KEY
    if Fernet is None:
        raise RuntimeError("cryptography ei ole asennettu.")
    if _KEY is None:
        _KEY = _load_or_generate()
    return Fernet(_KEY)


def encrypt_key(plaintext: str) -> str:
    """Enkripsi API key -> url-safe-base64 (ciphertext string)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_key(ciphertext: str) -> str:
    """Dekripti ciphertext -> plaintext API key (str)."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:  # type: ignore[misc]
        raise ValueError("Vault ciphertext epäkelpo (avain muuttunut?)") from exc