"""approval_flow.py — token persetujuan untuk tool yang mengirim data keluar.

MASALAH
-------
`tool_policy_gate` memberi disposition REQUIRE_APPROVAL untuk TELEGRAM
dan SLACK: alat yang mengirim isi ke pihak luar. Tanpa endpoint untuk
menerima keputusan user, keputusan itu tidak punya jalan - frontend
hanya bisa menampilkan pesan tanpa tombol yang benar-benar bekerja.

ALUR
----
1. Gate mengembalikan `requires_approval` + `approval_token`.
2. Frontend menampilkan tombol Setujui / Tolak.
3. Frontend POST /chat/approve dengan token + decision.
4. Server memverifikasi token, memanggil ULANG gate + validator pada
   argumen yang tersimpan, baru eksekusi.

PENTING SOAL LANGKAH 4
----------------------
Argumen disimpan di dalam token bertanda tangan, BUKAN di database dan
BUKAN dikirim balik dari client. Kalau client boleh memilih argumennya
sendiri, approval berubah jadi tidak bermakna: user menyetujui satu
pesan, tapi server mengirim pesan lain. Verifikasi ulang saat approve
memastikan argumen yang disetujui adalah argumen yang dieksekusi.

Token memakai pola yang sama dengan `credential_forms` resume_token:
HMAC-SHA256, base64url, expiry wajib, dan tolak kalau bukan milik akun
yang sedang login.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

#: Masa berlaku token persetujuan (brief: 5 menit).
APPROVAL_TTL_S = 300

_EPHEMERAL_KEY: bytes | None = None


def _signing_key() -> bytes:
    """Kunci HMAC untuk approval token.

    Dipakai `VAULT_SECRET_KEY` bila ada; kalau tidak, Turitas yang
    dibuat sekali per proses. Tanpa ini token bisa ditebak - dan token
    yang bisa ditebak berarti persetujuan bisa dipalsukan.
    """
    global _EPHEMERAL_KEY
    import os
    secret = (os.getenv("VAULT_SECRET_KEY") or "").strip()
    if secret:
        return hashlib.sha256(("approval:" + secret).encode()).digest()
    if _EPHEMERAL_KEY is None:
        _EPHEMERAL_KEY = hashlib.sha256(
            b"katalir-approval-" + str(time.time()).encode()).digest()
    return _EPHEMERAL_KEY


def _b64e(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_approval_token(user_email: str, tool: str, args: dict,
                         ttl_s: int = APPROVAL_TTL_S) -> str:
    """Token opaque, bertanda tangan, untuk satu panggilan tool."""
    payload = {
        "e": str(user_email or "").strip().lower(),
        "t": str(tool or "").strip().upper(),
        "a": args if isinstance(args, dict) else {},
        # `max(60, ttl)` TIDAK dipakai di sini, berlawanan dengan resume_token.
        # Lantai 60 detik membuat token yang diminta kedaluwarsa tetap
        # berlaku selama 60 detik - dan tes "setelah 6 menit -> 400"
        # tidak akan menangkapnya. TTL negatif harus menghasilkan token
        # yang SUDAH kedaluwarsa, bukan token panjang.
        "exp": int(time.time() + max(60, int(ttl_s)))
        if int(ttl_s) >= 0 else int(time.time() - 1),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"),
                           sort_keys=True).encode())
    sig = _b64e(hmac.new(_signing_key(), body.encode("ascii"),
                         hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_approval_token(token: str, user_email: str) -> dict:
    """Verifikasi token dan kembalikan payload-nya.

    Melempar `ValueError` bila rusak, kedaluwarsa, atau milik akun lain.
    """
    parts = str(token or "").split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError("Token approval tidak valid.")
    body, sig = parts
    expect = _b64e(hmac.new(_signing_key(), body.encode("ascii"),
                            hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        raise ValueError("Token approval tidak valid.")
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Token approval tidak bisa dibaca.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Token approval tidak bisa dibaca.")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError("Token approval sudah kedaluwarsa.")
    if str(payload.get("e") or "").lower() != str(user_email or "").strip().lower():
        # Token milik akun lain: tolak tanpa membocorkan detail apa pun.
        raise ValueError("Token approval tidak milik akun ini.")
    args = payload.get("a")
    return {"tool": str(payload.get("t") or "").upper(),
            "args": args if isinstance(args, dict) else {},
            "expires_at": int(payload.get("exp") or 0)}


__all__ = [
    "APPROVAL_TTL_S",
    "issue_approval_token",
    "verify_approval_token",
]