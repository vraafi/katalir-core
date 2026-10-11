"""token_guard.py — validasi payload JWT SEBELUM dipakai untuk memotong user.

MASALAH YANG DISELESAIKAN
-------------------------
Verifikasi signature saja TIDAK cukup. Pola serangan yang masih lazim pada
2026 (rujuk OWASP API Security + panduan JWT 2026):

  * **algorithm confusion** — `alg: none` (atau `alg` di luar allow-list)
    diterima verifier yang tidak membatasi algoritma.
  * **claim yang tidak diperiksa** — `exp`/`nbf`/`aud`/`iss` absen atau salah
    tetapi token tetap diterima; `nbf` di masa depan (token "belum berlaku")
    dipakai lebih awal.
  * **payload gemuk / sub aneh** — payload > 10 KB atau `sub` berisi karakter
    kontrol / terlalu panjang; ini vektor DoS dan injeksi.
  * **role injection** — klaim `role`/`roles` berisi nilai di luar whitelist
    yang kemudian dipercaya lapisan otorisasi.

Modul ini memisahkan dua langkah yang sering tercampur:

  1. ``check_header``  — periksa header TANPA memverifikasi signature
     (allow-list algoritma, tolak ``none``).
  2. ``validate_claims`` — aturan klaim setelah signature DINYATAKAN sah oleh
     pemanggil (mis. ``security._decode_local``).

Kontrak penting: modul ini **tidak** memverifikasi signature. Ia dipanggil
SETELAH signature sah. Ia menolak payload yang bentuknya tidak masuk akal,
sehingga tidak ada klaim yang dipakai sebelum melewati semua pemeriksaan.

Kompatibilitas
--------------
``require_aud`` default ``False`` mengikuti kebijakan proyek yang sudah
terdokumentasi (token Supabase lama bisa tidak membawa ``aud``); setel
``True`` untuk kebijakan ketat. Semua aturan lain aman untuk token Supabase
normal.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from typing import Any, Iterable

# --------------------------------------------------------------------------
# Kebijakan
# --------------------------------------------------------------------------
#: Panjang maksimum payload ter-decode (byte JSON kanonik).
MAX_PAYLOAD_BYTES = 10 * 1024

#: Algoritma yang boleh. ``none`` DILARANG mutlak.
ALLOWED_ALGS = frozenset({"HS256", "RS256", "ES256", "ES384", "RS384"})

#: ``sub`` wajib cocok pola ini (id Supabase / UUID / slug aman).
SUB_PATTERN = re.compile(r"^[A-Za-z0-9._:@|+-]{1,255}$")

#: Nilai ``role``/``roles`` yang dikenal. Nilai lain ditolak.
DEFAULT_ROLE_WHITELIST = frozenset({
    "authenticated", "anon", "service_role",
    "free", "plus", "pro", "ultra", "admin", "owner", "member",
})

#: Klaim yang tidak pernah boleh ada di payload (jejak injeksi).
FORBIDDEN_CLAIMS = frozenset({"__proto__", "constructor", "prototype"})

#: Toleransi jam (detik) untuk ``exp``/``nbf``.
DEFAULT_LEEWAY = 30


class TokenGuardError(Exception):
    """Payload token ditolak. ``code`` = alasan ringkas yang stabil."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# --------------------------------------------------------------------------
# Helper
# --------------------------------------------------------------------------
def _b64url_decode(segment: str) -> bytes:
    """Decode base64url JWT (padding opsional). Raise TokenGuardError."""
    if not isinstance(segment, str) or not segment:
        raise TokenGuardError("malformed", "segmen token kosong")
    pad = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except (binascii.Error, ValueError) as exc:
        raise TokenGuardError("malformed", f"base64url tidak valid: {exc}") from exc


def split_token(token: str) -> tuple[str, str, str]:
    """Pecah JWT menjadi (header_b64, payload_b64, signature_b64)."""
    if not isinstance(token, str):
        raise TokenGuardError("malformed", "token bukan string")
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise TokenGuardError("malformed", f"JWT harus 3 segmen, dapat {len(parts)}")
    return parts[0], parts[1], parts[2]


def payload_bytes(token: str) -> bytes:
    """Byte JSON payload mentah (tanpa verifikasi)."""
    _, payload_b64, _ = split_token(token)
    return _b64url_decode(payload_b64)


def payload_size(token: str) -> int:
    """Ukuran payload ter-decode dalam byte."""
    return len(payload_bytes(token))


def check_header(token: str) -> dict[str, Any]:
    """Periksa header: tolak ``alg`` kosong/``none``/di luar allow-list."""
    header_b64, _, _ = split_token(token)
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenGuardError("malformed_header", f"header bukan JSON: {exc}") from exc
    if not isinstance(header, dict):
        raise TokenGuardError("malformed_header", "header bukan objek JSON")
    alg = header.get("alg")
    if not isinstance(alg, str) or not alg:
        raise TokenGuardError("missing_alg", "header tanpa 'alg'")
    if alg.lower() == "none":
        raise TokenGuardError("alg_none", "algoritma 'none' ditolak")
    if alg not in ALLOWED_ALGS:
        raise TokenGuardError("alg_not_allowed", f"algoritma {alg!r} tidak diizinkan")
    return header


def _aud_values(aud: Any) -> list[str]:
    if isinstance(aud, str):
        return [aud]
    if isinstance(aud, (list, tuple)):
        return [str(a) for a in aud]
    return []


def validate_claims(
    claims: Any,
    *,
    expected_iss: str | None = None,
    expected_aud: str | None = None,
    require_aud: bool = False,
    require_exp: bool = True,
    require_sub: bool = False,
    allowed_roles: Iterable[str] = DEFAULT_ROLE_WHITELIST,
    now: float | None = None,
    leeway: int = DEFAULT_LEEWAY,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> dict[str, Any]:
    """Validasi aturan klaim. Raise TokenGuardError bila ditolak.

    Dipanggil SETELAH signature dinyatakan sah oleh pemanggil.
    """
    if not isinstance(claims, dict):
        raise TokenGuardError("malformed_payload", "payload bukan objek JSON")

    # 1) Klaim terlarang (jejak prototype pollution / injeksi).
    bad = FORBIDDEN_CLAIMS.intersection(claims.keys())
    if bad:
        raise TokenGuardError("forbidden_claim", f"klaim terlarang: {sorted(bad)}")

    # 2) Batas ukuran payload.
    try:
        encoded = json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TokenGuardError("malformed_payload", f"payload tidak serializable: {exc}") from exc
    if len(encoded) > max_payload_bytes:
        raise TokenGuardError(
            "payload_too_large",
            f"payload {len(encoded)} byte > batas {max_payload_bytes}",
        )

    ts = time.time() if now is None else float(now)

    # 3) exp — wajib (opsional dimatikan) dan belum kedaluwarsa.
    exp = claims.get("exp")
    if exp is None:
        if require_exp:
            raise TokenGuardError("missing_exp", "klaim 'exp' wajib ada")
    else:
        try:
            exp_f = float(exp)
        except (TypeError, ValueError) as exc:
            raise TokenGuardError("bad_exp", f"'exp' bukan angka: {exp!r}") from exc
        if ts > exp_f + leeway:
            raise TokenGuardError("expired", "token kedaluwarsa")

    # 4) nbf — bila ada, tidak boleh di masa depan.
    nbf = claims.get("nbf")
    if nbf is not None:
        try:
            nbf_f = float(nbf)
        except (TypeError, ValueError) as exc:
            raise TokenGuardError("bad_nbf", f"'nbf' bukan angka: {nbf!r}") from exc
        if ts + leeway < nbf_f:
            raise TokenGuardError("not_yet_valid", "token belum berlaku (nbf)")

    # 5) iss — bila diminta, harus cocok persis.
    if expected_iss is not None:
        iss = claims.get("iss")
        if iss is None:
            raise TokenGuardError("missing_iss", "klaim 'iss' wajib ada")
        if str(iss) != str(expected_iss):
            raise TokenGuardError("bad_iss", f"'iss' tidak cocok: {iss!r}")

    # 6) aud — bila diminta, harus memuat aud yang diharapkan.
    if expected_aud is not None:
        auds = _aud_values(claims.get("aud"))
        if not auds:
            if require_aud:
                raise TokenGuardError("missing_aud", "klaim 'aud' wajib ada")
        elif str(expected_aud) not in auds:
            raise TokenGuardError("bad_aud", f"'aud' tidak memuat {expected_aud!r}")

    # 7) sub — bila ada (atau diwajibkan) harus aman.
    sub = claims.get("sub")
    if sub is None:
        if require_sub:
            raise TokenGuardError("missing_sub", "klaim 'sub' wajib ada")
    else:
        if not isinstance(sub, str) or not SUB_PATTERN.match(sub):
            raise TokenGuardError("bad_sub", f"'sub' tidak valid: {sub!r}")

    # 8) role/roles — bila ada, tiap nilai harus di whitelist.
    wl = set(allowed_roles)
    for key in ("role", "roles"):
        if key not in claims:
            continue
        raw = claims[key]
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        for v in values:
            if not isinstance(v, str) or v not in wl:
                raise TokenGuardError("bad_role", f"klaim {key!r} memuat {v!r} di luar whitelist")

    return claims


def decode_and_validate(
    token: str,
    key: Any,
    *,
    algorithms: Iterable[str] = ("HS256",),
    **claim_kwargs: Any,
) -> dict[str, Any]:
    """Verifikasi signature (allow-list eksplisit) LALU validasi klaim.

    Inilah pemakaian yang benar: JANGAN pernah ``jwt.decode(..., options={
    "verify_signature": False})`` lalu memakai klaimnya. Semua kegagalan PyJWT
    dipetakan ke ``TokenGuardError`` dengan ``code`` yang stabil.
    """
    import jwt

    # Tolak ``alg: none`` sebelum menyentuh PyJWT.
    check_header(token)
    # PyJWT melempar ``InvalidAudienceError`` bila token BER-``aud`` tetapi
    # ``audience`` tidak diberikan. Kita matikan pemeriksaan aud/iss di PyJWT
    # dan menyerahkannya ke ``validate_claims`` supaya kode error presisi
    # (``missing_aud`` vs ``bad_aud``, ``missing_iss`` vs ``bad_iss``).
    try:
        claims = jwt.decode(
            token, key, algorithms=list(algorithms),
            options={"verify_aud": False, "verify_iss": False},
        )
    except jwt.InvalidAlgorithmError as exc:
        raise TokenGuardError("alg_not_allowed", str(exc)) from exc
    except jwt.ExpiredSignatureError as exc:
        raise TokenGuardError("expired", str(exc)) from exc
    except jwt.ImmatureSignatureError as exc:
        raise TokenGuardError("not_yet_valid", str(exc)) from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenGuardError("bad_aud", str(exc)) from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenGuardError("bad_iss", str(exc)) from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenGuardError("bad_signature", str(exc)) from exc
    except jwt.MissingRequiredClaimError as exc:
        raise TokenGuardError("missing_claim", str(exc)) from exc
    except jwt.InvalidTokenError as exc:
        raise TokenGuardError("invalid_token", str(exc)) from exc
    return validate_claims(claims, **claim_kwargs)


def guard(token: str, **claim_kwargs: Any) -> dict[str, Any]:
    """Header + ukuran payload + aturan klaim, TANPA verifikasi signature.

    Berguna sebagai pra-saring murah sebelum verifikasi kriptografis, atau
    untuk memvalidasi token yang signature-nya sudah diperiksa di tempat lain
    (mis. ``security._decode_local`` memakai PyJWT yang memverifikasi, lalu
    memanggil ``validate_claims`` atas klaim hasilnya).
    """
    check_header(token)
    size = payload_size(token)
    limit = claim_kwargs.get("max_payload_bytes", MAX_PAYLOAD_BYTES)
    if size > limit:
        raise TokenGuardError("payload_too_large", f"payload {size} byte > batas {limit}")
    try:
        claims = json.loads(payload_bytes(token).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenGuardError("malformed_payload", f"payload bukan JSON: {exc}") from exc
    return validate_claims(claims, **claim_kwargs)


__all__ = [
    "ALLOWED_ALGS",
    "DEFAULT_LEEWAY",
    "DEFAULT_ROLE_WHITELIST",
    "FORBIDDEN_CLAIMS",
    "MAX_PAYLOAD_BYTES",
    "SUB_PATTERN",
    "TokenGuardError",
    "check_header",
    "decode_and_validate",
    "guard",
    "payload_bytes",
    "payload_size",
    "split_token",
    "validate_claims",
]
