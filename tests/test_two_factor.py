# tests/test_two_factor.py — Fitur #11b: 2FA (TOTP + WebAuthn) + penegakan
# ======================================================================
# 18 tes / 13 skenario wajib. TOTP diuji dengan `at=` DETERMINISTIK (tanpa
# tidur, tanpa flaky). WebAuthn diuji lewat authenticator perangkat lunak
# NYATA (keypair ES256 + CBOR) — signature benar-benar diverifikasi pustaka
# `webauthn`, bukan di-stub. Kebijakan & session epoch diuji end-to-end.
# ======================================================================

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import time

import cbor2
import pyotp
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import two_factor as TF

RP_ID = "katalir.de5.net"
ORIGIN = f"https://{RP_ID}"


@pytest.fixture(autouse=True)
def _store_baru():
    TF.set_store(TF.MemoryTwoFactorStore())
    yield
    TF.set_store(None)


# ---------------------------------------------------------------------------
# Helper authenticator perangkat lunak (dipakai beberapa tes WebAuthn)
# ---------------------------------------------------------------------------
def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _auth_data(rp_id: str, flags: int, sign_count: int,
               attested: bytes | None = None, cred_id: bytes = b"") -> bytes:
    head = (hashlib.sha256(rp_id.encode()).digest() + bytes([flags])
            + struct.pack(">I", sign_count))
    if attested is None:
        return head
    return (head + b"\x00" * 16 + struct.pack(">H", len(cred_id))
            + cred_id + attested)


class SoftAuthenticator:
    """Authenticator in-process: keypair P-256 + payload WebAuthn nyata."""

    def __init__(self, rp_id: str = RP_ID, origin: str = ORIGIN):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.rp_id, self.origin = rp_id, origin

    def _client_data(self, typ: str, challenge: str) -> bytes:
        return json.dumps({"type": typ, "challenge": challenge,
                           "origin": self.origin, "crossOrigin": False},
                          separators=(",", ":")).encode()

    def registration(self, challenge: str) -> dict:
        cose = cbor2.dumps({
            1: 2, 3: -7, -1: 1,
            -2: self.key.public_key().public_numbers().x.to_bytes(32, "big"),
            -3: self.key.public_key().public_numbers().y.to_bytes(32, "big"),
        })
        att = cbor2.dumps({"fmt": "none", "attStmt": {},
                           "authData": _auth_data(self.rp_id, 0x41, 0, cose,
                                                  self.cred_id)})
        return {"id": _b64u(self.cred_id), "rawId": _b64u(self.cred_id),
                "type": "public-key",
                "response": {"clientDataJSON": _b64u(
                    self._client_data("webauthn.create", challenge)),
                    "attestationObject": _b64u(att),
                    "transports": ["internal"]},
                "clientExtensionResults": {}}

    def assertion(self, challenge: str, sign_count: int, *,
                  key=None, cred_id: bytes | None = None) -> dict:
        signing_key = key or self.key
        cid = cred_id if cred_id is not None else self.cred_id
        client_data = self._client_data("webauthn.get", challenge)
        auth_data = _auth_data(self.rp_id, 0x01, sign_count)
        sig = signing_key.sign(auth_data + hashlib.sha256(client_data).digest(),
                               ec.ECDSA(hashes.SHA256()))
        return {"id": _b64u(cid), "rawId": _b64u(cid), "type": "public-key",
                "response": {"clientDataJSON": _b64u(client_data),
                             "authenticatorData": _b64u(auth_data),
                             "signature": _b64u(sig), "userHandle": None},
                "clientExtensionResults": {}}


def _setup_totp(user_id="u1", email="u1@example.com"):
    begin = TF.begin_totp_setup(user_id, email)
    secret = begin["secret"]
    code = pyotp.TOTP(secret).now()
    done = TF.confirm_totp_setup(user_id, code)
    return secret, done, code


# ---------------------------------------------------------------------------
# BASIC (3)
# ---------------------------------------------------------------------------
def test_b1_setup_totp_menghasilkan_secret_qr_dan_recovery():
    """B1: setup -> secret base32 32 char, QR SVG, URI otpauth."""
    b = TF.begin_totp_setup("u1", "u1@example.com")
    assert len(b["secret"]) == 32
    assert b["otpauth_uri"].startswith("otpauth://totp/")
    assert "Katalir" in b["otpauth_uri"]
    assert b["qr_svg"].startswith("<?xml") and "<svg" in b["qr_svg"]
    # Belum aktif sebelum konfirmasi.
    assert TF.status("u1")["enabled"] is False


def test_b2_konfirmasi_mengaktifkan_dan_menerbitkan_10_kode():
    """B2: kode valid -> aktif + 10 kode cadangan sekali-tampil."""
    secret, done, code = _setup_totp()
    assert done["enabled"] is True
    assert done["method"] == "totp"
    assert len(done["recovery_codes"]) == TF.RECOVERY_CODE_COUNT
    assert done["recovery_codes_remaining"] == 10
    st = TF.status("u1")
    assert st["enabled"] is True and st["totp_enabled"] is True
    assert st["recovery_codes_remaining"] == 10


def test_b3_verifikasi_totp_dan_kode_cadangan():
    """B3: login tahap-2 menerima TOTP DAN kode cadangan."""
    secret, done, code = _setup_totp()
    assert TF.verify_login("u1", code)["method"] == "totp"
    r = TF.verify_login("u1", done["recovery_codes"][0])
    assert r["method"] == "recovery_code"
    assert r["recovery_codes_remaining"] == 9


# ---------------------------------------------------------------------------
# DURABILITY (2)
# ---------------------------------------------------------------------------
def test_d1_kode_cadangan_sekali_pakai():
    """D1: kode cadangan tidak bisa dipakai dua kali."""
    _secret, done, _code = _setup_totp()
    first = done["recovery_codes"][3]
    assert TF.verify_login("u1", first)["method"] == "recovery_code"
    with pytest.raises(TF.InvalidCodeError):
        TF.verify_login("u1", first)
    assert TF.status("u1")["recovery_codes_remaining"] == 9


def test_d2_secret_tersimpan_terenkripsi_tidak_plain():
    """D2: secret TOTP di store BUKAN base32 polos (kecuali vault absen)."""
    secret, _done, _code = _setup_totp()
    row = TF.store().get_user("u1")
    stored = row["totp_secret"]
    assert stored != secret
    assert stored.startswith(("fernet:", "plain:"))
    # Round-trip harus mengembalikan secret asli.
    assert TF.decrypt_secret(stored) == secret


# ---------------------------------------------------------------------------
# EDGE CASE (3)
# ---------------------------------------------------------------------------
def test_e1_verifikasi_deterministik_dengan_at():
    """E1: `at=` membuat verifikasi TOTP deterministik (anti-flaky)."""
    secret = TF.generate_totp_secret()
    moment = 1_790_000_000.0
    code = pyotp.TOTP(secret).at(int(moment))
    assert TF.verify_totp(secret, code, at=moment) is True
    # 5 menit kemudian kode lama harus gugur (jendela ±1 langkah).
    assert TF.verify_totp(secret, code, at=moment + 300) is False
    # Format salah ditolak tanpa melempar.
    assert TF.verify_totp(secret, "abc", at=moment) is False
    assert TF.verify_totp(secret, "12345", at=moment) is False
    assert TF.verify_totp("", code, at=moment) is False


def test_e2_user_tanpa_2fa_tidak_bisa_verifikasi():
    """E2: verifikasi untuk user yang belum mengaktifkan 2FA -> error jelas."""
    with pytest.raises(TF.TwoFactorError):
        TF.verify_login("belum-ada", "123456")


def test_e3_reset_admin_mencabut_sesi_dan_kredensial():
    """E3: reset paksa -> 2FA mati, epoch naik (sesi lama gugur)."""
    _secret, _done, _code = _setup_totp()
    before = TF.status("u1")["session_epoch"]
    out = TF.reset_user_2fa("u1", reason="laptop hilang")
    assert out["enabled"] is False
    assert out["session_epoch"] > before
    st = TF.status("u1")
    assert st["enabled"] is False
    assert st["recovery_codes_remaining"] == 0
    # Token yang terbit sebelum reset tidak lagi sah.
    assert TF.token_epoch_valid("u1", before) is False
    assert TF.token_epoch_valid("u1", out["session_epoch"] + 1) is True


# ---------------------------------------------------------------------------
# PERFORMANCE (2)
# ---------------------------------------------------------------------------
def test_p1_verifikasi_cepat_banyak_kali():
    """P1: 300 verifikasi TOTP selesai di bawah 2 detik."""
    secret, _done, code = _setup_totp()
    t0 = time.perf_counter()
    for _ in range(300):
        assert TF.verify_login("u1", code)["ok"] is True
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"terlalu lambat: {elapsed:.3f}s"


def test_p2_qr_svg_dan_secret_generation_murah():
    """P2: 100 pembuatan secret+QR tetap di bawah 3 detik."""
    t0 = time.perf_counter()
    for _ in range(100):
        s = TF.generate_totp_secret()
        TF.qr_svg(TF.provisioning_uri(s, "x@example.com"))
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"terlalu lambat: {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# SECURITY (2)
# ---------------------------------------------------------------------------
def test_s1_penegakan_memblokir_user_tanpa_2fa():
    """S1: `enforced=true` -> user tanpa 2FA ditandai must_setup & diblokir;
    setelah menyiapkan 2FA, gerbangnya terbuka."""
    TF.set_policy(enforced=True, updated_by="admin@x.com")
    st = TF.status("u1")
    assert st["enforced"] is True and st["must_setup"] is True
    with pytest.raises(TF.TwoFactorRequiredError):
        TF.require_satisfied("u1")

    _secret, _done, _code = _setup_totp("u1")
    assert TF.status("u1")["must_setup"] is False
    TF.require_satisfied("u1")          # tidak melempar


def test_s2_sso_dikecualikan_dan_disable_ditolak_saat_enforced():
    """S2: user SSO tidak diwajibkan (kecuali `enforce_for_sso`), dan
    mematikan 2FA ditolak selama penegakan menyala."""
    TF.set_policy(enforced=True)
    # SSO dikecualikan secara default.
    TF.require_satisfied("user-sso", sso=True)
    with pytest.raises(TF.TwoFactorRequiredError):
        TF.require_satisfied("user-sso", sso=False)

    TF.set_policy(enforce_for_sso=True)
    with pytest.raises(TF.TwoFactorRequiredError):
        TF.require_satisfied("user-sso", sso=True)

    # 2FA yang sudah aktif tidak bisa dimatikan saat penegakan menyala.
    secret, done, code = _setup_totp("u2")
    with pytest.raises(TF.TwoFactorRequiredError):
        TF.disable_totp("u2", code)

    # Begitu penegakan dimatikan, disable berhasil dan epoch naik.
    TF.set_policy(enforced=False)
    out = TF.disable_totp("u2", code, at=None)
    assert out["enabled"] is False
    assert TF.status("u2")["enabled"] is False


# ---------------------------------------------------------------------------
# TAMBAHAN: sesi, kebijakan dari env, dan WebAuthn nyata
# ---------------------------------------------------------------------------
def test_x1_epoch_token_dan_reset_sessions():
    """X1: `reset_sessions` mencabut token lama; token baru tetap sah."""
    _secret, _done, _code = _setup_totp()
    issued = time.time()
    assert TF.token_epoch_valid("u1", issued) is True
    epoch = TF.reset_sessions("u1")
    assert epoch > issued
    assert TF.token_epoch_valid("u1", issued) is False
    assert TF.token_epoch_valid("u1", epoch + 0.001) is True


def test_x2_kebijakan_dari_env(monkeypatch):
    """X2: env `KATALIR_MFA_ENFORCED`/`_ENABLED` mengatur penegakan
    (pola `N8N_SECURITY_POLICY_MANAGED_BY_ENV`)."""
    monkeypatch.setenv("KATALIR_MFA_ENFORCED", "true")
    monkeypatch.delenv("KATALIR_MFA_ENABLED", raising=False)
    TF.policy_from_env()
    assert TF.store().get_policy()["enforced"] is True

    # `KATALIR_MFA_ENABLED=false` menang -> penegakan dimatikan.
    monkeypatch.setenv("KATALIR_MFA_ENABLED", "false")
    TF.policy_from_env()
    assert TF.store().get_policy()["enforced"] is False


def test_x3_webauthn_round_trip_signature_nyata():
    """X3: registrasi + autentikasi passkey NYATA (signature diperiksa)."""
    auth = SoftAuthenticator()
    begin = TF.webauthn_register_begin("wa1", "wa1@example.com",
                                       rp_id=RP_ID, origin=ORIGIN)
    done = TF.webauthn_register_complete(
        "wa1", auth.registration(begin["challenge"]), label="laptop",
        rp_id=RP_ID, origin=ORIGIN)
    assert done["enabled"] is True and done["webauthn_count"] == 1
    assert TF.status("wa1")["enabled"] is True

    ab = TF.webauthn_auth_begin("wa1", rp_id=RP_ID, origin=ORIGIN)
    res = TF.webauthn_auth_complete("wa1", auth.assertion(ab["challenge"], 1),
                                    rp_id=RP_ID, origin=ORIGIN)
    assert res["ok"] is True and res["sign_count"] == 1


def test_x4_webauthn_menolak_replay_origin_palsu_signature_dan_counter():
    """X4: empat serangan passkey wajib ditolak."""
    auth = SoftAuthenticator()
    begin = TF.webauthn_register_begin("wa2", "wa2@example.com",
                                       rp_id=RP_ID, origin=ORIGIN)
    TF.webauthn_register_complete("wa2", auth.registration(begin["challenge"]),
                                  rp_id=RP_ID, origin=ORIGIN)

    # (a) challenge lama (replay)
    ab1 = TF.webauthn_auth_begin("wa2", rp_id=RP_ID, origin=ORIGIN)
    TF.webauthn_auth_complete("wa2", auth.assertion(ab1["challenge"], 1),
                              rp_id=RP_ID, origin=ORIGIN)
    ab2 = TF.webauthn_auth_begin("wa2", rp_id=RP_ID, origin=ORIGIN)
    with pytest.raises(TF.InvalidCodeError):
        TF.webauthn_auth_complete("wa2", auth.assertion(ab1["challenge"], 2),
                                  rp_id=RP_ID, origin=ORIGIN)

    # (b) origin palsu
    with pytest.raises(TF.InvalidCodeError):
        TF.webauthn_auth_complete(
            "wa2", auth.assertion(ab2["challenge"], 2),
            rp_id=RP_ID, origin="https://evil.example")

    # (c) signature dari kunci lain
    lain = SoftAuthenticator()
    ab3 = TF.webauthn_auth_begin("wa2", rp_id=RP_ID, origin=ORIGIN)
    with pytest.raises(TF.InvalidCodeError):
        TF.webauthn_auth_complete(
            "wa2", auth.assertion(ab3["challenge"], 3, key=lain.key),
            rp_id=RP_ID, origin=ORIGIN)

    # (d) counter mundur (indikasi kloning)
    ab4 = TF.webauthn_auth_begin("wa2", rp_id=RP_ID, origin=ORIGIN)
    with pytest.raises(TF.InvalidCodeError):
        TF.webauthn_auth_complete("wa2", auth.assertion(ab4["challenge"], 0),
                                  rp_id=RP_ID, origin=ORIGIN)
