"""Hard test TASK 5 — validasi payload token SEBELUM dipakai.

12 skenario wajib: accept valid, tolak expired, tolak signature palsu,
tolak aud/iss/nbf, tolak payload >10KB, tolak sub aneh, tolak role injection,
tolak alg=none, performa <10ms, plus klaim terlarang.
"""
from __future__ import annotations

import json
import time

import jwt
import pytest

import token_guard as tg

SECRET = "test-secret-untuk-hard-test-token-guard"
ISS = "https://auth.katalir.test/"
AUD = "authenticated"


def _mk(claims: dict, secret: str = SECRET, alg: str = "HS256") -> str:
    return jwt.encode(claims, secret, algorithm=alg)


def _base(**over) -> dict:
    now = int(time.time())
    c = {
        "sub": "user_7f3b91",
        "email": "a@b.test",
        "aud": AUD,
        "iss": ISS,
        "iat": now,
        "exp": now + 600,
    }
    c.update(over)
    return c


# 1. Valid token -> accept -------------------------------------------------
def test_01_valid_token_accepted():
    tok = _mk(_base())
    claims = tg.decode_and_validate(tok, SECRET, expected_aud=AUD, expected_iss=ISS,
                                    require_aud=True, require_sub=True)
    assert claims["sub"] == "user_7f3b91"


# 2. Expired token -> reject ----------------------------------------------
def test_02_expired_rejected():
    tok = _mk(_base(exp=int(time.time()) - 3600))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "expired"


# 3. Invalid signature -> reject ------------------------------------------
def test_03_invalid_signature_rejected():
    tok = _mk(_base(), secret="penyerang")
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "bad_signature"


# 4. Missing aud (require_aud) -> reject ----------------------------------
def test_04_missing_aud_rejected():
    claims = _base()
    claims.pop("aud")
    tok = _mk(claims)
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD, require_aud=True)
    assert e.value.code == "missing_aud"


def test_04b_wrong_aud_rejected():
    tok = _mk(_base(aud="lain"))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD, require_aud=True)
    assert e.value.code == "bad_aud"


# 5. Wrong iss -> reject ---------------------------------------------------
def test_05_wrong_iss_rejected():
    tok = _mk(_base(iss="https://jahat.test/"))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_iss=ISS)
    assert e.value.code == "bad_iss"


def test_05b_missing_iss_rejected():
    claims = _base()
    claims.pop("iss")
    tok = _mk(claims)
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_iss=ISS)
    assert e.value.code == "missing_iss"


# 6. nbf in future -> reject ----------------------------------------------
def test_06_nbf_future_rejected():
    tok = _mk(_base(nbf=int(time.time()) + 3600))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "not_yet_valid"


# 7. Payload > 10KB -> reject ---------------------------------------------
def test_07_payload_too_large_rejected():
    tok = _mk(_base(pad="x" * 12000))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "payload_too_large"


# 8. Invalid sub -> reject -------------------------------------------------
def test_08_bad_sub_rejected():
    tok = _mk(_base(sub="user\x00injeksi"))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "bad_sub"


def test_08b_empty_sub_when_required_rejected():
    claims = _base()
    claims.pop("sub")
    tok = _mk(claims)
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD, require_sub=True)
    assert e.value.code == "missing_sub"


# 9. Role injection -> reject ---------------------------------------------
def test_09_role_injection_rejected():
    tok = _mk(_base(role="superadmin-root"))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "bad_role"


def test_09b_roles_list_injection_rejected():
    tok = _mk(_base(roles=["authenticated", "root"]))
    with pytest.raises(tg.TokenGuardError) as e:
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    assert e.value.code == "bad_role"


# 10. Algorithm confusion (none) -> reject --------------------------------
def test_10_alg_none_rejected():
    header = {"alg": "none", "typ": "JWT"}
    import base64
    def b64(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    tok = f"{b64(header)}.{b64(_base())}."
    with pytest.raises(tg.TokenGuardError) as e:
        tg.check_header(tok)
    assert e.value.code == "alg_none"
    with pytest.raises(tg.TokenGuardError):
        tg.decode_and_validate(tok, SECRET)


def test_10b_alg_not_allowed_rejected():
    # alg di luar allow-list (mis. HS512) -> ditolak header check.
    tok = jwt.encode(_base(), SECRET, algorithm="HS512")
    with pytest.raises(tg.TokenGuardError) as e:
        tg.check_header(tok)
    assert e.value.code == "alg_not_allowed"


# 11. Performance < 10ms ---------------------------------------------------
def test_11_performance_under_10ms():
    tok = _mk(_base())
    tg.decode_and_validate(tok, SECRET, expected_aud=AUD)  # warm
    n = 200
    t0 = time.perf_counter()
    for _ in range(n):
        tg.decode_and_validate(tok, SECRET, expected_aud=AUD)
    per_ms = (time.perf_counter() - t0) / n * 1000
    assert per_ms < 10.0, f"{per_ms:.3f} ms/validasi >= 10ms"


# 12. Forbidden claim + malformed -----------------------------------------
def test_12_forbidden_claim_rejected():
    with pytest.raises(tg.TokenGuardError) as e:
        tg.validate_claims({"__proto__": {"polluted": True}, "exp": time.time() + 60})
    assert e.value.code == "forbidden_claim"


def test_12b_malformed_token_rejected():
    for bad in ("", "abc", "a.b", "a.b.c.d"):
        with pytest.raises(tg.TokenGuardError):
            tg.check_header(bad)


def test_12c_guard_does_not_require_signature():
    # `guard` sengaja tidak memverifikasi signature (pra-saring murah).
    tok = _mk(_base(), secret="apa pun")
    claims = tg.guard(tok, expected_aud=AUD)
    assert claims["sub"] == "user_7f3b91"
