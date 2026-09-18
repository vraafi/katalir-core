"""test_classify_401.py - Kredensial ditolak (401) -> `key_dead` + rotasi, BUKAN 500.

Kelas bug yang dijaga (temuan produksi 2026-09-18, tertangkap spec E2E
`chat-auth` SESUDAH assertion vakum-nya diperbaiki di commit 10862fd):

    POST /chat -> 500 {"detail": "ClientError: 401 UNAUTHENTICATED.
    {'error': {'code': 401, 'message': 'Request had invalid authentication
    credentials. Expected OAuth 2 access token...'}}"}

Rantai penyebabnya: `classify_error` hanya mengenal 429 / 404 / 5xx-transien,
sehingga 401 jatuh ke `unknown` -> pool tidak menandai apa pun -> TIDAK ada
rotasi kunci -> exception lolos ke handler generik dan produksi menjawab 500.

Kontrak yang benar (dan dikunci di sini):
  * 401 = kunci MATI (dicabut/diganti di Google AI Studio) -> bekukan kunci itu
    24 jam untuk SEMUA model, lalu rotasi ke kunci berikutnya;
  * bila SEMUA kunci mati -> hasil akhirnya **503** (kondisi layanan sementara),
    bukan 500 (bug server).

Tes ini murni lokal: tanpa jaringan, tanpa SDK Gemini, tanpa DB.
"""

import pathlib
import re

import gemini_key_pool as gkp

# Pesan ASLI dari respons produksi (`POST /chat` -> 500). Dipakai apa adanya
# supaya kelas error bergantung pada bentuk nyata, bukan regex ideal.
PAYLOAD_401_PROD = (
    "ClientError: 401 UNAUTHENTICATED. {'error': {'code': 401, 'message': "
    "'Request had invalid authentication credentials. Expected OAuth 2 access "
    "token, login cookie or other valid authentication credential.', "
    "'status': 'UNAUTHENTICATED'}}"
)
# Varian dari SDK Gemini (`API_KEY_INVALID`) - kunci dicabut/di-regenerate.
PAYLOAD_401_SDK = (
    "401 API_KEY_INVALID. {'error': {'code': 401, 'message': 'API key not "
    "valid. Please pass a valid API key.', 'status': 'UNAUTHENTICATED'}}"
)

API_SRC = pathlib.Path("api_server.py")


class Clock:
    """Jam palsu supaya tes cooldown tidak perlu tidur sungguhan."""

    def __init__(self, start: float = 10_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, sec: float) -> None:
        self.t += sec


def make_pool(n: int = 3, clock: "Clock | None" = None) -> tuple[gkp.KeyPool, Clock]:
    clock = clock or Clock()
    entries = [
        (
            "GEMINI_KEY_%d" % i,
            "fake-key-%d-%s" % (i, "x" * (10 + i)),
            gkp.fingerprint("fake-key-%d" % i),
        )
        for i in range(1, n + 1)
    ]
    return gkp.KeyPool(entries=entries, now_fn=clock), clock


def test_401_unauth_classified_as_key_dead():
    """401 UNAUTHENTICATED -> `key_dead` (24 jam), bukan `unknown`."""
    for name, payload in (("produksi", PAYLOAD_401_PROD), ("sdk", PAYLOAD_401_SDK)):
        kind, ttl = gkp.classify_error(Exception(payload))
        assert kind == "key_dead", "payload 401 (%s) dinilai %r" % (name, kind)
        assert ttl == gkp._KEY_DEAD_S == 24 * 3600.0
    # Kelas lain TIDAK boleh ikut terbawa jadi `key_dead`.
    assert gkp.classify_error(
        Exception("429 RESOURCE_EXHAUSTED quota exceeded"))[0] == "rate_limited"
    assert gkp.classify_error(
        Exception("404 NOT_FOUND no longer available to new users"))[0] == "entitlement"
    assert gkp.classify_error(Exception("503 UNAVAILABLE overloaded"))[0] == "overloaded"
    assert gkp.classify_error(Exception("halo dunia"))[0] == "unknown"


def test_key_dead_marked_cooldown_24h():
    """Kunci mati dibekukan untuk SEMUA model; kunci lain tetap dipakai."""
    pool, clock = make_pool(3)
    fp0, _ = pool.acquire("gemini-2.5-flash")
    assert fp0 is not None

    pool.mark(fp0, "gemini-2.5-flash", exc=Exception(PAYLOAD_401_PROD))

    assert pool.stats()["cooling"] == 1
    # 401 bukan soal model -> kunci mati tidak dipakai walau modelnya ditukar.
    assert fp0 not in pool.available("gemini-2.5-flash")
    assert fp0 not in pool.available("gemini-3-flash-preview")
    # Rotasi benar-benar berjalan: kunci berikutnya menggantikan yang mati.
    fp1, _ = pool.acquire("gemini-2.5-flash")
    assert fp1 is not None and fp1 != fp0
    # Setelah 24 jam kunci pulih (kalau kuncinya sudah diperbaiki di Google).
    clock.advance(24 * 3600.0 + 1)
    assert fp0 in pool.available("gemini-2.5-flash")


def test_all_keys_dead_returns_503_not_500():
    """Semua kunci mati -> `acquire` None (dipetakan ke 503), bukan error 500.

    Dua lapisan diuji sekaligus supaya tidak bisa "lulus" hanya karena pool
    benar tetapi `api_server` masih menjawab 500 (kelas bug yang nyata ini).
    """
    pool, _ = make_pool(2)
    for _ in range(2):
        got = pool.acquire("gemini-2.5-flash")
        assert got is not None, "kunci kedua seharusnya masih tersedia"
        pool.mark(got[0], "gemini-2.5-flash", exc=Exception(PAYLOAD_401_PROD))

    # Lapisan pool: habis -> None (bukan exception).
    assert pool.acquire("gemini-2.5-flash") is None
    assert pool.available("gemini-2.5-flash") == []

    # Lapisan API: kedua jalur terminal memakai helper 503, dan helper itu
    # TIDAK pernah memulangkan 500.
    src = API_SRC.read_text(encoding="utf-8")
    assert src.count("raise _final_503()") == 2, (
        "jalur terminal `_send_guarded` tidak memakai helper 503"
    )
    match = re.search(r"def _final_503\(\):.*?while True:", src, re.S)
    assert match, "helper `_final_503` hilang dari `_send_guarded`"
    body = match.group(0)
    # Kode status diambil dari ARGUMEN pemanggilan (bukan grep teks bebas):
    # komentar/docstring boleh menyebut "500" sebagai penjelasan tanpa membuat
    # guard salah menilai. Ini pola yang sama dengan guard assertion chat-auth.
    codes = re.findall(r"HTTPException\(\s*(\d+)", body)
    assert codes == ["503", "503"], "helper 503 memulangkan kode %r" % (codes,)
    # 401 harus terbaca sebagai gangguan sementara bagi user, bukan
    # "model tidak tersedia untuk tier Anda".
    assert 'dead_seen = True' in src
    assert '"overloaded"' in src