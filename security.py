# security.py - Autentikasi JWT Supabase (server-side)
# PENTING: tidak bisa spoof — pemotongan user TARGET dari JWT signature
# bukan dari query param / body / header non-authenticated.

import os
from fastapi import HTTPException

from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
# anon key cukup untuk auth.get_user (verify JWT + nacti leta user profil).
# Service role key BIASA bikin get_user bypass — pakai anon untuk verify proper.
SUPABASE_ANON = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()

_auth_client = None


def _get_auth_client():
    global _auth_client
    if _auth_client is None:
        from supabase import create_client
        if not (SUPABASE_URL and SUPABASE_ANON):
            raise HTTPException(500, "Supabase belum dikonfigurasi.")
        _auth_client = create_client(SUPABASE_URL, SUPABASE_ANON)
    return _auth_client


def get_current_user(authorization: str | None = None):
    """Pemotong user dari JWT Supabase. JANGAN pernah pakai email param/body.

    Returns:
        dict {id, email} verified dari token.
    Raises:
        HTTPException 401 jika token kosong / invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token wajib (Authorization: Bearer <jwt>).")
    token = authorization.replace("Bearer ", "", 1).strip()
    if not token:
        raise HTTPException(401, "Token kosong.")
    try:
        client = _get_auth_client()
        resp = client.auth.get_user(token)
        user = resp.user
        if not user or not getattr(user, "id", None):
            raise HTTPException(401, "User tidak zaustav v token.")
        return {
            "id": str(user.id),
            "email": (getattr(user, "email", None) or "").lower().strip(),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - token invalid / network
        raise HTTPException(401, f"Token invalid: {exc.__class__.__name__}")