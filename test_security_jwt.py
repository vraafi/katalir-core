"""
test_security_jwt.py — Pengujian resmi (pytest) untuk verifikasi JWT LOKAL.

Latar belakang (insiden produksi):
    `/models` dan `/chat` menjawab 401 `{"detail":"Token invalid: ConnectTimeout"}`
    walau access token browser sah dan DB sehat. Penyebabnya verifikasi token
    bergantung JARINGAN (`client.auth.get_user()` memanggil
    `<ref>.supabase.co`), sehingga gangguan DNS/connect mematikan SELURUH API.

Perbaikan yang dikunci oleh tes ini:
    Verifikasi signature dilakukan LOKAL memakai public key dari JWKS yang
    ter-cache (disk/env `SUPABASE_JWKS`) -> SETELAH cache terisi, verifikasi
    TIDAK memanggil jaringan sama sekali.

Semua tes deterministik & offline: key pair dibuat di dalam tes, dan `httpx.get`
dipaksa GAGAL agar terbukti tidak ada ketergantungan jaringan.

Berjalan (dari folder proyek):
    pytest test_security_jwt.py -v
"""
import json
import os
import sys
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")

import security as sec  # noqa: E402

KID = "test-kid-0001"
EMAIL = "user@nexus-local.test"
SUB = "4de98c10-1111-2222-3333-444455556666"


def _key_pair(kid=KID):
    """EC P-256 (algoritma yang dipakai Supabase sekarang: ES256)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(priv.public_key()))
    jwk["kid"] = kid
    jwk["alg"] = "ES256"
    jwk["use"] = "sig"
    return priv, {"keys": [jwk]}


@pytest.fixture()
def offline(monkeypatch):
    """Paksa jaringan SELALU gagal -> verifikasi wajib jalan tanpa jaringan.

    Dua jalur jaringan ditutup: unduhan JWKS (`httpx.get`) DAN jalur cadangan
    `auth.get_user()` (`_get_auth_client`). Tanpa menutup yang kedua, tes yang
    mengharapkan 401 pada token tidak sah masih menembak jaringan sungguhan —
    hasilnya lambat dan tidak deterministik.
    """
    def _no_network(*a, **kw):
        raise RuntimeError("jaringan dilarang (DNS/ConnectTimeout disimulasikan)")

    def _no_auth_client(*a, **kw):
        raise RuntimeError("jaringan dilarang (auth.get_user diblokir)")

    monkeypatch.setattr(sec.httpx, "get", _no_network)
    monkeypatch.setattr(sec, "_get_auth_client", _no_auth_client)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setattr(sec, "SUPABASE_JWT_SECRET", "", raising=False)
    monkeypatch.setattr(sec, "_JWKS_RETRY_COOLDOWN_SEC", 0.0)
    return _no_network


@pytest.fixture()
def seeded(offline, monkeypatch):
    """Tanam JWKS via env SUPABASE_JWKS (mekanisme yang dipakai produksi)."""
    priv, jwks = _key_pair()
    monkeypatch.setattr(sec, "_jwks_cache", None, raising=False)
    monkeypatch.setattr(sec, "_jwks_fetched_at", 0.0, raising=False)
    monkeypatch.setenv("SUPABASE_JWKS", json.dumps(jwks))
    assert sec._seed_jwks(), "seed dari env SUPABASE_JWKS gagal"
    return priv


def _token(priv, *, exp_offset=3600, sub=SUB, email=EMAIL, aud="authenticated", kid=KID):
    claims = {
        "sub": sub,
        "email": email,
        "role": "authenticated",
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()) - 10,
    }
    # `aud=None` mensimulasikan token lama yang BENAR-BENAR tanpa klaim `aud`.
    # Bukan `"aud": None`: PyJWT menuliskannya sebagai klaim `null` yang TETAP ADA,
    # sehingga (benar) ditolak sebagai aud tidak cocok — bukan kasus yang diuji.
    if aud is not None:
        claims["aud"] = aud
    # `kid=None` -> header `kid` benar-benar ABSEN (klien lama). Bukan string
    # kosong: `kid: ""` tetap "ada" bagi `_key_for` dan mengubah jalur kode yang
    # diuji, sehingga tes tidak lagi mengukur kompatibilitas token tanpa kid.
    headers = {"kid": kid} if kid else None
    return jwt.encode(claims, priv, algorithm="ES256", headers=headers)


def test_token_sah_terverifikasi_lokal_tanpa_jaringan(seeded):
    """INTI PERBAIKAN: token sah diterima walau jaringan ke Supabase mati total."""
    user = sec.get_current_user(f"Bearer {_token(seeded)}")
    assert user["id"] == SUB
    assert user["email"] == EMAIL


def test_seed_dari_env_mengisi_cache_tanpa_unduh(seeded):
    """`SUPABASE_JWKS` mengisi cache; tidak ada percobaan unduh ke jaringan."""
    jwks = sec._get_jwks()
    assert jwks and jwks["keys"][0]["kid"] == KID


def test_token_kedaluwarsa_401(seeded):
    """Expiry tetap ditegakkan secara lokal (bukan diterima mentah)."""
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(seeded, exp_offset=-60)}")
    assert e.value.status_code == 401
    assert "kedaluwarsa" in str(e.value.detail).lower()


def test_signature_palsu_ditolak(seeded):
    """Token yang ditandatangani kunci LAIN harus ditolak (anti-spoofing)."""
    other, _ = _key_pair()  # kunci berbeda, kid sama
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(other)}")
    assert e.value.status_code == 401


def test_verifikasi_lokal_konklusif_menang_atas_flag_jwks_basi(seeded, monkeypatch):
    """REGRESI (bug nyata, 2026-09-16): signature PALSU tidak boleh dilaporkan 503.

    Bukti asal bug (probe `_e_bug503_probe.py`, dan token fixture E2E yang
    `exp`-nya disunting `_e2e_extend.py`): `kid` COCOK dan kuncinya ADA, jadi
    verifikasi lokal sudah KONKLUSIF menolak signature. Tetapi syarat
    `or _jwks_last_error` pada klasifikasi 401/503 membuat flag LENGKET dari
    kegagalan unduhan masa lalu membajak kasus ini: responsnya menjadi 503
    berpesan "Token TIDAK dinilai tidak sah". Pesan itu menyembunyikan sebab
    sebenarnya (token memang palsu) dan mengarahkan investigasi ke jaringan —
    persis jebakan yang membuat 3 tes E2E terlihat seperti gangguan infra.
    """
    other, _ = _key_pair()  # kunci berbeda, kid sama -> signature palsu
    monkeypatch.setattr(sec, "_jwks_last_error", "ConnectTimeout", raising=False)
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(other)}")
    assert e.value.status_code == 401, (
        "verifikasi lokal yang konklusif harus menang atas flag JWKS basi"
    )
    assert "verifikasi lokal" in str(e.value.detail)


def test_kunci_tak_tersedia_503_bukan_401(offline, monkeypatch, tmp_path):
    """Sisi lain kontrak: kunci TIDAK BISA dipegang -> 503 (infra), bukan 401.

    Bila JWKS belum pernah ter-cache dan unduhan gagal, kita TIDAK TAHU tokennya
    sah atau tidak — menuduhnya tidak sah (401) akan mengeluarkan user dari sesi
    yang sebenarnya sehat. Kasus inilah yang memang pantas 503 "coba lagi";
    membedakannya dari signature palsu adalah inti perbaikan.
    """
    monkeypatch.setattr(sec, "_JWKS_PATH", str(tmp_path / "tidak-ada.json"))
    monkeypatch.setattr(sec, "_jwks_cache", None, raising=False)
    monkeypatch.setattr(sec, "_jwks_fetched_at", 0.0, raising=False)
    monkeypatch.setattr(sec, "_jwks_last_error", "", raising=False)
    monkeypatch.setattr(sec, "_jwks_last_fail_at", 0.0, raising=False)
    monkeypatch.delenv("SUPABASE_JWKS", raising=False)
    assert sec._seed_jwks() is None, "tidak boleh ada kunci yang bisa dipegang"
    priv, _ = _key_pair()
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(priv)}")
    assert e.value.status_code == 503, (
        "kunci tak tersedia = hasil diskonklusif, jangan mengklaim token tidak sah"
    )
    assert "TIDAK dinilai tidak sah" in str(e.value.detail)


def test_kid_tidak_dikenal_ditolak(seeded):
    """`kid` tak ada di JWKS -> tidak boleh "menebak" kunci yang benar."""
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(seeded, kid='kid-entah')}")
    assert e.value.status_code == 401


def test_kid_absen_tetap_diverifikasi_satu_kunci(seeded):
    """Kompatibilitas: token TANPA `kid` tetap sah via satu-satunya kunci.

    Kasus ini yang membuat fallback `keys[0]` tetap diperlukan. Tanpa tes ini,
    pengetatan `kid` (menolak kid tak dikenal) berisiko ikut mematikan token
    klien lama — regresi senyap yang hanya muncul di produksi.
    """
    assert sec.get_current_user(f"Bearer {_token(seeded, kid=None)}")["id"] == SUB


def test_kid_absen_multikey_ditolak(offline, monkeypatch):
    """`kid` absen + JWKS berisi >1 kunci -> pilihan ambigu, token DITOLAK.

    Menebak salah satu kunci saat ada beberapa kandidat berarti menerima token
    yang tidak jelas kunci penandatanganannya. Menolak adalah sikap aman.
    """
    priv, jwks = _key_pair()
    _, extra = _key_pair("test-kid-0002")
    jwks["keys"].append(extra["keys"][0])
    monkeypatch.setattr(sec, "_jwks_cache", None, raising=False)
    monkeypatch.setattr(sec, "_jwks_fetched_at", 0.0, raising=False)
    monkeypatch.setenv("SUPABASE_JWKS", json.dumps(jwks))
    assert sec._seed_jwks()
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(priv, kid=None)}")
    assert e.value.status_code == 401


def test_tanpa_header_atau_token_kosong_401(seeded):
    for bad in (None, "", "Bearer ", "token-tanpa-prefix"):
        with pytest.raises(HTTPException) as e:
            sec.get_current_user(bad)
        assert e.value.status_code == 401


def test_email_dinormalkan_huruf_kecil(seeded):
    """Email dari klaim dinormalkan -> kepemilikan sesi konsisten (anti-bypass)."""
    user = sec.get_current_user(f"Bearer {_token(seeded, email='User@Nexus-Local.TEST')}")
    assert user["email"] == "user@nexus-local.test"


def test_token_tanpa_aud_signature_tetap_wajib_sah(seeded):
    """Token lama tanpa aud lolos-jalur-aud, tapi signature WAJIB sah."""
    ok = sec.get_current_user(f"Bearer {_token(seeded, aud=None)}")
    assert ok["id"] == SUB

    other, _ = _key_pair()
    with pytest.raises(HTTPException) as e:
        sec.get_current_user(f"Bearer {_token(other, aud=None)}")
    assert e.value.status_code == 401


def test_hs256_memakai_secret_env(monkeypatch, offline):
    """Proyek Supabase lama (HS256) diverifikasi memakai SUPABASE_JWT_SECRET."""
    # >=32 byte: PyJWT memperingatkan kunci HMAC pendek (RFC 7518 §3.2). Kunci
    # pendek membuat output tes berisik dan menyamarkan peringatan sungguhan.
    secret = "super-secret-shared-value-0123456789abcdef"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    monkeypatch.setattr(sec, "SUPABASE_JWT_SECRET", secret, raising=False)
    claims = {"sub": SUB, "email": EMAIL, "aud": "authenticated",
              "exp": int(time.time()) + 3600}
    token = jwt.encode(claims, secret, algorithm="HS256")
    assert sec.get_current_user(f"Bearer {token}")["id"] == SUB


def test_cache_disk_dipakai_saat_env_kosong(offline, monkeypatch, tmp_path):
    """Fallback: file `.jwks_cache.json` tetap membuat verifikasi offline jalan."""
    priv, jwks = _key_pair()
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps(jwks), encoding="utf-8")
    monkeypatch.setattr(sec, "_JWKS_PATH", str(path))
    monkeypatch.setattr(sec, "_jwks_cache", None, raising=False)
    monkeypatch.setattr(sec, "_jwks_fetched_at", 0.0, raising=False)
    monkeypatch.delenv("SUPABASE_JWKS", raising=False)

    assert sec._seed_jwks(), "seed dari disk cache gagal"
    assert sec.get_current_user(f"Bearer {_token(priv)}")["id"] == SUB