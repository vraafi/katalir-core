"""two_factor.py — Fitur #11b: 2FA (TOTP + WebAuthn) + penegakan instance.

RISET (Okt 2026)
----------------
* `docs.n8n.io/administer/manage-users-and-access/verify-user-identity/
  require-two-factor-auth` — n8n mendukung 2FA lewat **authenticator app**
  (TOTP): Aktifkan 2FA → QR → verifikasi kode → **recovery codes**
  ditampilkan dan WAJIB disimpan. Env `N8N_MFA_ENABLED=false` mematikan
  2FA instance-wide, **tetapi diabaikan bila sudah ada user ber-2FA**.
* `docs.n8n.io/deploy/host-n8n/configure-n8n/security/
  manage-security-policies` — **Enforce two-factor authentication**:
  semua user wajib menyiapkan 2FA sebelum bisa memakai instance; user
  yang belum menyiapkan diminta saat login berikutnya. Penegakan hanya
  untuk login **email+password** — user SSO (SAML/OIDC) TIDAK terpengaruh.
  Env: `N8N_MFA_ENFORCED_ENABLED`, `N8N_SECURITY_POLICY_MANAGED_BY_ENV`.
* `webauthn` 3.0.1 (PyPI, rilis Juni 2026, duo-labs/py_webauthn) — verifikasi
  server-side WebAuthn/passkey penuh (challenge, origin, RP ID, signature,
  counter). Dipakai di sini untuk alur register/authenticate passkey.
* PyOTP 2.9.0 — TOTP yang sudah lama terpasang di proyek.

KEPUTUSAN DESAIN
----------------
1. **TOTP dulu, WebAuthn kemudian** — dua metode yang berdiri sendiri,
   bisa dipakai bersama (baik = "AND", bukan "OR", untuk login berisiko).
2. **Recovery codes disimpan sebagai HASH** (SHA-256 + salt per-user),
   sekali pakai, dan di-invalidasi saat 2FA dimatikan. Kode mentah hanya
   ditampilkan SEKALI saat setup — persis perilaku n8n.
3. **Secret TOTP dienkripsi dengan Fernet** (kunci dari vault/env yang
   sudah dipakai proyek) supaya bocornya tabel `user_2fa` tidak langsung
   memberi penyerang kemampuan membuat kode.
4. **Session invalidation**: bila 2FA wajib dan user mematikannya, semua
   token sesi miliknya dicabut lewat *epoch* per-user (`session_epoch`).
   Verifikasi token membandingkan klaim `iat` dengan epoch — tanpa perlu
   menyimpan daftar token.
5. **Penegakan ≠ kunci total**: user tetap boleh mengambil langkah
   menyiapkan 2FA (endpoint setup/enable) walau `enforced` menyala.
   Hanya endpoint produktif yang diblokir (`require_2fa_satisfied`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from typing import Any, Iterable

import pyotp

# ---------------------------------------------------------------------------
# Penyimpanan (backend yang bisa di-swap; default: memori proses)
# ---------------------------------------------------------------------------
#: Nama tabel/invarian yang dipakai bila backend Supabase tersedia.
TABLE_USERS = "user_2fa"
TABLE_POLICY = "security_policy"
TABLE_SESSIONS = "user_session_epoch"

#: Backend ditentukan lewat env supaya pengujian bisa menyuntik fake.
_BACKEND_ENV = "KATALIR_2FA_BACKEND"


class TwoFactorError(RuntimeError):
    """Kesalahan 2FA yang aman untuk ditampilkan ke operator."""


class TwoFactorRequiredError(TwoFactorError):
    """Aksi diblokir karena 2FA wajib dan belum dipenuhi."""


class InvalidCodeError(TwoFactorError):
    """Kode TOTP/backup tidak sah atau sudah kedaluwarsa."""


# ---------------------------------------------------------------------------
# Enkripsi secret TOTP
# ---------------------------------------------------------------------------
def _fernet():
    """Fernet dari `VAULT_KEY`/`SECRETS_VAULT_KEY`; None bila tak tersedia.

    Modul ini TIDAK memaksa kunci ada: bila tidak tersedia, secret disimpan
    sebagai base32 polos dengan penanda `plain:` — sehingga modul tetap
    bisa dipakai di lingkungan dev. Produksi memakai Fernet (dikunci test).
    """
    for key_name in ("VAULT_KEY", "SECRETS_VAULT_KEY", "FERNET_KEY"):
        raw = (os.getenv(key_name) or "").strip()
        if not raw:
            continue
        try:
            from cryptography.fernet import Fernet
            return Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception:  # noqa: BLE001 — kunci rusak -> fallback plain
            continue
    return None


def encrypt_secret(secret: str) -> str:
    """Simpan secret TOTP dalam bentuk terenkripsi (atau `plain:`)."""
    f = _fernet()
    if f is None:
        return "plain:" + secret
    return "fernet:" + f.encrypt(secret.encode()).decode()


def decrypt_secret(stored: str) -> str:
    """Kembalikan secret TOTP mentah dari bentuk tersimpan."""
    if stored.startswith("fernet:"):
        f = _fernet()
        if f is None:
            raise TwoFactorError(
                "secret terenkripsi tetapi kunci vault tidak tersedia"
            )
        return f.decrypt(stored[len("fernet:"):].encode()).decode()
    if stored.startswith("plain:"):
        return stored[len("plain:"):]
    return stored


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------
#: Jumlah kode cadangan yang dibuat sekali (n8n menampilkan daftar serupa).
RECOVERY_CODE_COUNT = 10
#: Panjang kode cadangan (tanpa pemisah).
RECOVERY_CODE_LEN = 10
#: Salt per-user untuk hash kode cadangan.
_RECOVERY_SALT_BYTES = 16


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def hash_recovery_code(code: str, salt: str) -> str:
    """Hash satu kode cadangan (SHA-256 + salt). Deterministik untuk test."""
    material = f"{salt}:{_normalize_code(code)}".encode()
    return hashlib.sha256(material).hexdigest()


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Buat daftar kode cadangan baru (format `XXXXX-XXXXX`)."""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(8).upper()[:RECOVERY_CODE_LEN]
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class MemoryTwoFactorStore:
    """Backend default: memori proses.

    Struktur:
      users[user_id] = {
        "user_id","email","totp_secret","totp_enabled_at",
        "webauthn":[{"credential_id","public_key","sign_count",
                     "transports","label","created_at"}],
        "recovery_salt","recovery_hashes":[...],"recovery_used":{},
        "created_at","updated_at"
      }
      policy = {"enforced":bool,"allow_webauthn":bool,"enforce_for_sso":bool,
                "updated_at","updated_by"}
      epochs[user_id] = float (unix detik; token dengan iat < epoch ditolak)
    """

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.policy: dict = {
            "enforced": False,
            "allow_webauthn": True,
            "enforce_for_sso": False,
            "updated_at": time.time(),
            "updated_by": "",
        }
        self.epochs: dict[str, float] = {}
        self.secrets_cache: dict[str, str] = {}
        self.reset_calls: int = 0

    # -- users ------------------------------------------------------------
    def get_user(self, user_id: str) -> dict | None:
        row = self.users.get(str(user_id))
        return dict(row) if row else None

    def upsert_user(self, user_id: str, **fields) -> dict:
        uid = str(user_id)
        row = self.users.setdefault(uid, {
            "user_id": uid, "email": "", "totp_secret": "",
            "totp_enabled_at": None, "webauthn": [], "recovery_salt": "",
            "recovery_hashes": [], "recovery_used": {},
            "created_at": time.time(), "updated_at": time.time(),
        })
        for k, v in fields.items():
            row[k] = v
        row["updated_at"] = time.time()
        return dict(row)

    def delete_credentials(self, user_id: str) -> None:
        uid = str(user_id)
        row = self.users.get(uid)
        if row:
            row.update({"totp_secret": "", "totp_enabled_at": None,
                        "webauthn": [], "recovery_salt": "",
                        "recovery_hashes": [], "recovery_used": {},
                        "updated_at": time.time()})
        self.secrets_cache.pop(uid, None)

    # -- policy -----------------------------------------------------------
    def get_policy(self) -> dict:
        return dict(self.policy)

    def set_policy(self, **fields) -> dict:
        self.policy.update(fields)
        self.policy["updated_at"] = time.time()
        return dict(self.policy)

    # -- epochs -----------------------------------------------------------
    def get_epoch(self, user_id: str) -> float:
        return float(self.epochs.get(str(user_id), 0.0))

    def bump_epoch(self, user_id: str) -> float:
        uid = str(user_id)
        now = time.time()
        self.epochs[uid] = max(now, self.get_epoch(uid) + 1e-6)
        return self.epochs[uid]


#: Instans default (dipakai aplikasi). Test memakai instans sendiri.
_STORE: MemoryTwoFactorStore | None = None


def store() -> MemoryTwoFactorStore:
    global _STORE
    if _STORE is None:
        _STORE = MemoryTwoFactorStore()
    return _STORE


def set_store(new_store: MemoryTwoFactorStore | None) -> None:
    """Ganti backend (dipakai test / integrasi Supabase di masa depan)."""
    global _STORE
    _STORE = new_store


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------
#: Nama issuer yang muncul di authenticator app.
ISSUER = os.getenv("KATALIR_2FA_ISSUER", "Katalir")
#: Toleransi drift ±1 langkah (30 detik) — perilaku umum authenticator.
TOTP_VALID_WINDOW = 1


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str, issuer: str = ISSUER) -> str:
    """URI `otpauth://` untuk QR code (format standar Google Authenticator)."""
    return pyotp.TOTP(secret).provisioning_uri(name=email or "user",
                                               issuer_name=issuer)


def qr_svg(uri: str) -> str:
    """Render URI ke SVG inline (tanpa dependensi jaringan/PIL)."""
    import qrcode
    import qrcode.image.svg
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(uri, image_factory=factory)
    import io
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def verify_totp(secret: str, code: str, *,
                at: float | None = None,
                window: int = TOTP_VALID_WINDOW) -> bool:
    """Verifikasi kode TOTP. `at` memungkinkan pengujian deterministik."""
    if not secret:
        return False
    cleaned = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(cleaned) != 6:
        return False
    totp = pyotp.TOTP(secret)
    if at is None:
        return bool(totp.verify(cleaned, valid_window=window))
    now = pyotp.TOTP(secret).at(int(at))
    # Periksa jendela secara manual supaya `at` benar-benar deterministik.
    for offset in range(-window, window + 1):
        moment = int(at) + offset * totp.interval
        if hmac.compare_digest(pyotp.TOTP(secret).at(moment), cleaned):
            return True
    return hmac.compare_digest(now, cleaned)


# ---------------------------------------------------------------------------
# Setup / aktivasi
# ---------------------------------------------------------------------------
def begin_totp_setup(user_id: str, email: str = "") -> dict:
    """Langkah 1: buat secret + QR. Belum mengaktifkan 2FA."""
    s = store()
    secret = generate_totp_secret()
    uri = provisioning_uri(secret, email)
    s.upsert_user(user_id, email=email or "", totp_secret=encrypt_secret(secret),
                  totp_pending=True)
    return {
        "user_id": str(user_id),
        "secret": secret,
        "otpauth_uri": uri,
        "qr_svg": qr_svg(uri),
        "issuer": ISSUER,
        "digits": 6,
        "period": 30,
    }


def confirm_totp_setup(user_id: str, code: str, *,
                       at: float | None = None) -> dict:
    """Langkah 2: verifikasi kode → aktifkan 2FA + terbitkan recovery codes."""
    s = store()
    row = s.get_user(user_id)
    if not row:
        raise TwoFactorError("belum ada proses setup 2FA untuk user ini")
    secret = decrypt_secret(row.get("totp_secret") or "")
    if not secret:
        raise TwoFactorError("secret TOTP tidak ditemukan")
    if not verify_totp(secret, code, at=at):
        raise InvalidCodeError("kode TOTP tidak sah")

    codes = generate_recovery_codes()
    salt = secrets.token_hex(_RECOVERY_SALT_BYTES)
    hashes = [hash_recovery_code(c, salt) for c in codes]
    s.upsert_user(user_id, totp_enabled_at=time.time(), totp_pending=False,
                  recovery_salt=salt, recovery_hashes=hashes,
                  recovery_used={})
    s.bump_epoch(user_id)   # sesi lama tidak lagi cukup syarat
    return {
        "user_id": str(user_id),
        "enabled": True,
        "method": "totp",
        "recovery_codes": codes,
        "recovery_codes_remaining": len(codes),
    }


def disable_totp(user_id: str, code: str, password_ok: bool = True, *,
                 at: float | None = None) -> dict:
    """Matikan 2FA. Menolak bila penegakan instance menyala."""
    s = store()
    policy = s.get_policy()
    if policy.get("enforced"):
        raise TwoFactorRequiredError(
            "2FA wajib di instance ini — tidak bisa dimatikan oleh user"
        )
    if not password_ok:
        raise TwoFactorError("konfirmasi identitas gagal")
    row = s.get_user(user_id)
    if row and row.get("totp_secret"):
        secret = decrypt_secret(row["totp_secret"])
        if not verify_totp(secret, code, at=at):
            raise InvalidCodeError("kode TOTP tidak sah")
    s.delete_credentials(user_id)
    bump = s.bump_epoch(user_id)
    return {"user_id": str(user_id), "enabled": False,
            "session_epoch": bump}


# ---------------------------------------------------------------------------
# Verifikasi saat login
# ---------------------------------------------------------------------------
def verify_login(user_id: str, code: str, *, at: float | None = None,
                 consume_backup: bool = True) -> dict:
    """Verifikasi langkah kedua: TOTP ATAU kode cadangan.

    Kode cadangan bersifat SEKALI PAKAI: setelah dipakai, hash-nya dihapus
    dari daftar (dan dicatat di `recovery_used`).
    """
    s = store()
    row = s.get_user(user_id)
    if not row or not row.get("totp_enabled_at"):
        raise TwoFactorError("2FA tidak aktif untuk user ini")

    secret = decrypt_secret(row.get("totp_secret") or "")
    if secret and verify_totp(secret, code, at=at):
        return {"user_id": str(user_id), "method": "totp", "ok": True}

    if consume_backup:
        norm = _normalize_code(code)
        salt = row.get("recovery_salt") or ""
        target = hash_recovery_code(norm, salt) if salt else ""
        used = dict(row.get("recovery_used") or {})
        for h in list(row.get("recovery_hashes") or []):
            if hmac.compare_digest(h, target):
                remaining = [x for x in row["recovery_hashes"] if x != h]
                used[h] = time.time()
                s.upsert_user(user_id, recovery_hashes=remaining,
                              recovery_used=used)
                return {"user_id": str(user_id), "method": "recovery_code",
                        "ok": True,
                        "recovery_codes_remaining": len(remaining)}
    raise InvalidCodeError("kode 2FA tidak sah")


# ---------------------------------------------------------------------------
# Penegakan (enforcement)
# ---------------------------------------------------------------------------
def set_policy(enforced: bool | None = None,
               allow_webauthn: bool | None = None,
               enforce_for_sso: bool | None = None,
               updated_by: str = "") -> dict:
    """Ubah kebijakan keamanan instance (admin).

    Menaikkan `enforced` ke True **tidak** langsung mengunci siapa pun:
    user tanpa 2FA ditandai `must_setup` dan diblokir pada endpoint
    produktif (perilaku n8n: "prompted on their next sign-in").
    """
    s = store()
    fields: dict = {}
    if enforced is not None:
        fields["enforced"] = bool(enforced)
    if allow_webauthn is not None:
        fields["allow_webauthn"] = bool(allow_webauthn)
    if enforce_for_sso is not None:
        fields["enforce_for_sso"] = bool(enforce_for_sso)
    if updated_by:
        fields["updated_by"] = str(updated_by)
    return s.set_policy(**fields)


def policy_from_env() -> dict:
    """Terapkan kebijakan dari env (pola `N8N_SECURITY_POLICY_MANAGED_BY_ENV`).

    Nilai yang didukung (default: tidak menyentuh apa pun bila env kosong):
      * `KATALIR_MFA_ENFORCED` — "true"/"1" -> wajibkan 2FA untuk semua.
      * `KATALIR_MFA_ENABLED`  — "false"/"0" -> matikan/enforcement off.
      * `KATALIR_MFA_ALLOW_WEBAUTHN` — "false"/"0" -> larang passkey.
    """
    s = store()
    changed: dict = {}
    raw_enforced = (os.getenv("KATALIR_MFA_ENFORCED") or "").strip().lower()
    raw_enabled = (os.getenv("KATALIR_MFA_ENABLED") or "").strip().lower()
    raw_wa = (os.getenv("KATALIR_MFA_ALLOW_WEBAUTHN") or "").strip().lower()
    if raw_enabled in ("false", "0", "no"):
        changed["enforced"] = False
    elif raw_enforced in ("true", "1", "yes"):
        # n8n: "n8n ignores this if existing users have 2FA enabled" —
        # kebijakan mematikan tetap tidak boleh membatalkan 2FA yang sudah
        # dipasang user; yang dimatikan hanya kewajibannya.
        changed["enforced"] = True
    if raw_wa in ("false", "0", "no"):
        changed["allow_webauthn"] = False
    if changed:
        changed["updated_by"] = "env"
        return s.set_policy(**changed)
    return s.get_policy()


def status(user_id: str) -> dict:
    """Ringkasan keadaan 2FA satu user + kewajiban yang berlaku."""
    s = store()
    row = s.get_user(user_id) or {}
    pol = s.get_policy()
    enabled = bool(row.get("totp_enabled_at")) or bool(row.get("webauthn"))
    return {
        "user_id": str(user_id),
        "enabled": enabled,
        "totp_enabled": bool(row.get("totp_enabled_at")),
        "webauthn_count": len(row.get("webauthn") or []),
        "recovery_codes_remaining": len(row.get("recovery_hashes") or []),
        "enforced": bool(pol.get("enforced")),
        "must_setup": bool(pol.get("enforced")) and not enabled,
        "session_epoch": s.get_epoch(user_id),
    }


def require_satisfied(user_id: str, *, sso: bool = False) -> None:
    """Gerbang untuk endpoint produktif. Raise bila 2FA belum dipenuhi.

    User SSO TIDAK diwajibkan kecuali `enforce_for_sso` menyala (dokumen
    n8n: penegakan hanya berlaku untuk login email/password).
    """
    pol = store().get_policy()
    if not pol.get("enforced"):
        return
    if sso and not pol.get("enforce_for_sso"):
        return
    if not status(user_id)["enabled"]:
        raise TwoFactorRequiredError(
            "2FA wajib di instance ini — siapkan 2FA sebelum melanjutkan"
        )


# ---------------------------------------------------------------------------
# Session invalidation berbasis epoch
# ---------------------------------------------------------------------------
def token_epoch_valid(user_id: str, issued_at: float) -> bool:
    """True bila token (yang terbit pada `issued_at`) masih dianggap sah.

    Dipakai setelah kode 2FA direset/dimatikan: semua token yang terbit
    SEBELUM epoch dicabut sekaligus tanpa daftar token.
    """
    return float(issued_at or 0) >= store().get_epoch(user_id)


def reset_sessions(user_id: str) -> float:
    """Cabut semua sesi user (naikkan epoch). Kembalikan epoch baru."""
    return store().bump_epoch(user_id)


# ---------------------------------------------------------------------------
# WebAuthn (passkey)
# ---------------------------------------------------------------------------
def _rp_config(rp_id: str | None = None, origin: str | None = None) -> tuple[str, list[str]]:
    rid = (rp_id or os.getenv("KATALIR_RP_ID") or "katalir.de5.net").strip()
    org = (origin or os.getenv("KATALIR_RP_ORIGIN") or "").strip()
    origins = [o.strip() for o in org.split(",") if o.strip()]
    if not origins:
        origins = [f"https://{rid}"]
    return rid, origins


def webauthn_available() -> bool:
    """True bila pustaka `webauthn` ada dan passkey diizinkan kebijakan."""
    if not store().get_policy().get("allow_webauthn", True):
        return False
    try:
        import webauthn  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def webauthn_register_begin(user_id: str, email: str = "",
                            rp_id: str | None = None,
                            origin: str | None = None) -> dict:
    """Mulai registrasi passkey. Kembalikan opsi + challenge tersimpan."""
    from webauthn import generate_registration_options
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    rid, origins = _rp_config(rp_id, origin)
    s = store()
    row = s.get_user(user_id) or {}
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor
    descriptors = []
    for c in (row.get("webauthn") or []):
        raw = c.get("credential_id") or ""
        try:
            descriptors.append(PublicKeyCredentialDescriptor(
                id=base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))))
        except Exception:  # noqa: BLE001
            continue
    opts = generate_registration_options(
        rp_id=rid,
        rp_name=ISSUER,
        user_id=str(user_id).encode(),
        user_name=email or f"user-{user_id}",
        exclude_credentials=descriptors or None,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    challenge = base64.urlsafe_b64encode(opts.challenge).decode().rstrip("=")
    s.upsert_user(user_id, webauthn_challenge=challenge,
                  webauthn_origins=origins, webauthn_rp_id=rid)
    return {
        "rp_id": rid, "rp_name": ISSUER, "origins": origins,
        "challenge": challenge,
        "options": json.loads(_options_to_json(opts)),
    }


def _options_to_json(opts) -> str:
    """Serialisasi opsi WebAuthn (bytes -> base64url) tanpa bawaan SDK."""
    from webauthn.helpers import options_to_json
    try:
        return options_to_json(opts)
    except Exception:  # noqa: BLE001 — fallback minimal
        return json.dumps({"challenge": base64.urlsafe_b64encode(
            getattr(opts, "challenge", b"")).decode().rstrip("=")})


def webauthn_register_complete(user_id: str, credential: dict,
                               label: str = "", rp_id: str | None = None,
                               origin: str | None = None) -> dict:
    """Verifikasi respons registrasi passkey, lalu simpan kredensial."""
    from webauthn import verify_registration_response
    s = store()
    row = s.get_user(user_id) or {}
    rid = rp_id or row.get("webauthn_rp_id") or _rp_config()[0]
    origins = [origin] if origin else (row.get("webauthn_origins") or _rp_config()[1])
    challenge = row.get("webauthn_challenge") or ""
    try:
        res = verify_registration_response(
            credential=_credential_json(credential),
            expected_challenge=base64.urlsafe_b64decode(
                challenge + "=" * (-len(challenge) % 4)),
            expected_rp_id=rid,
            expected_origin=origins,
        )
    except Exception as exc:  # noqa: BLE001 — semua kegagalan verifikasi
        raise InvalidCodeError(f"registrasi passkey ditolak: {exc}") from exc

    helper = base64.urlsafe_b64encode(res.credential_id).decode().rstrip("=")
    creds = list(row.get("webauthn") or [])
    creds.append({
        "credential_id": helper,
        "public_key": base64.b64encode(res.credential_public_key).decode(),
        "sign_count": int(res.sign_count or 0),
        "transports": list(credential.get("transports") or []),
        "label": label or f"passkey-{len(creds) + 1}",
        "created_at": time.time(),
    })
    s.upsert_user(user_id, webauthn=creds, webauthn_challenge="",
                  totp_pending=False,
                  totp_enabled_at=row.get("totp_enabled_at"))
    s.bump_epoch(user_id)
    return {"user_id": str(user_id), "enabled": True, "method": "webauthn",
            "credential_id": helper, "webauthn_count": len(creds)}


def _credential_json(credential: dict) -> str:
    """Normalisasi payload browser menjadi JSON yang diterima `webauthn`."""
    payload = {k: v for k, v in (credential or {}).items()
               if k in ("id", "rawId", "type", "response",
                        "clientExtensionResults", "authenticatorAttachment")}
    payload.setdefault("type", "public-key")
    if "rawId" not in payload and payload.get("id"):
        payload["rawId"] = payload["id"]
    return json.dumps(payload)


def webauthn_auth_begin(user_id: str, rp_id: str | None = None,
                        origin: str | None = None) -> dict:
    """Mulai autentikasi passkey (challenge baru)."""
    from webauthn import generate_authentication_options
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor, UserVerificationRequirement,
    )
    rid, origins = _rp_config(rp_id, origin)
    s = store()
    row = s.get_user(user_id) or {}
    descriptors = []
    for c in (row.get("webauthn") or []):
        raw = c.get("credential_id") or ""
        try:
            descriptors.append(PublicKeyCredentialDescriptor(
                id=base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))))
        except Exception:  # noqa: BLE001
            continue
    opts = generate_authentication_options(
        rp_id=rid, allow_credentials=descriptors or None,
        user_verification=UserVerificationRequirement.PREFERRED)
    challenge = base64.urlsafe_b64encode(opts.challenge).decode().rstrip("=")
    s.upsert_user(user_id, webauthn_challenge=challenge,
                  webauthn_origins=origins, webauthn_rp_id=rid)
    return {"challenge": challenge, "rp_id": rid, "origins": origins,
            "options": json.loads(_options_to_json(opts))}


def webauthn_auth_complete(user_id: str, credential: dict,
                           rp_id: str | None = None,
                           origin: str | None = None) -> dict:
    """Verifikasi assertion passkey + perbarui `sign_count` (clone guard)."""
    from webauthn import verify_authentication_response
    s = store()
    row = s.get_user(user_id) or {}
    rid = rp_id or row.get("webauthn_rp_id") or _rp_config()[0]
    origins = [origin] if origin else (row.get("webauthn_origins") or _rp_config()[1])
    challenge = row.get("webauthn_challenge") or ""
    raw_id = credential.get("rawId") or credential.get("id") or ""
    match = next((c for c in (row.get("webauthn") or [])
                  if c.get("credential_id") == raw_id), None)
    if match is None:
        raise InvalidCodeError("kredensial passkey tidak dikenal")
    try:
        res = verify_authentication_response(
            credential=_credential_json(credential),
            expected_challenge=base64.urlsafe_b64decode(
                challenge + "=" * (-len(challenge) % 4)),
            expected_rp_id=rid,
            expected_origin=origins,
            credential_public_key=base64.b64decode(match["public_key"]),
            credential_current_sign_count=int(match.get("sign_count") or 0),
        )
    except Exception as exc:  # noqa: BLE001
        raise InvalidCodeError(f"autentikasi passkey ditolak: {exc}") from exc

    new_count = int(res.new_sign_count or 0)
    creds = []
    for c in (row.get("webauthn") or []):
        if c.get("credential_id") == raw_id:
            c = dict(c, sign_count=new_count, last_used_at=time.time())
        creds.append(c)
    s.upsert_user(user_id, webauthn=creds, webauthn_challenge="")
    return {"user_id": str(user_id), "ok": True, "method": "webauthn",
            "sign_count": new_count}


# ---------------------------------------------------------------------------
# Utilitas admin
# ---------------------------------------------------------------------------
def reset_user_2fa(user_id: str, reason: str = "") -> dict:
    """Paksa reset 2FA seorang user (admin) — dan cabut sesinya."""
    s = store()
    s.delete_credentials(user_id)
    epoch = s.bump_epoch(user_id)
    s.reset_calls += 1
    return {"user_id": str(user_id), "enabled": False,
            "session_epoch": epoch, "reason": reason}


def overview() -> dict:
    """Ringkasan instance untuk dashboard admin."""
    s = store()
    users = s.users
    enabled = [u for u, r in users.items()
               if r.get("totp_enabled_at") or r.get("webauthn")]
    return {
        "policy": s.get_policy(),
        "users_total": len(users),
        "users_with_2fa": len(enabled),
        "users_without_2fa": len(users) - len(enabled),
        "webauthn_available": webauthn_available(),
        "issuer": ISSUER,
        "totp_window": TOTP_VALID_WINDOW,
        "libraries": _library_versions(),
    }


def _library_versions() -> dict:
    import importlib.metadata as md
    out = {}
    for name in ("pyotp", "qrcode", "webauthn", "cryptography"):
        try:
            out[name] = md.version(name)
        except Exception:  # noqa: BLE001
            out[name] = ""
    return out


__all__ = [
    "TwoFactorError",
    "TwoFactorRequiredError",
    "InvalidCodeError",
    "MemoryTwoFactorStore",
    "store",
    "set_store",
    "encrypt_secret",
    "decrypt_secret",
    "generate_totp_secret",
    "provisioning_uri",
    "qr_svg",
    "verify_totp",
    "begin_totp_setup",
    "confirm_totp_setup",
    "disable_totp",
    "verify_login",
    "generate_recovery_codes",
    "hash_recovery_code",
    "set_policy",
    "policy_from_env",
    "status",
    "require_satisfied",
    "token_epoch_valid",
    "reset_sessions",
    "reset_user_2fa",
    "overview",
    "webauthn_available",
    "webauthn_register_begin",
    "webauthn_register_complete",
    "webauthn_auth_begin",
    "webauthn_auth_complete",
    "ISSUER",
    "TOTP_VALID_WINDOW",
    "RECOVERY_CODE_COUNT",
]
