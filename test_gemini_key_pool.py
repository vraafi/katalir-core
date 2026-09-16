"""test_gemini_key_pool.py - Kontrak pool kunci Gemini (tanpa jaringan).

Fokus: membuktikan sifat yang MEMULIHKAN jalur cadangan, bukan sekadar
"rotasi jalan":
  * cooldown PER KUNCI (kunci lain tidak ikut mati) - inti perbaikan SPOF;
  * blokir PER (KUNCI, MODEL) untuk entitlement 404;
  * TTL diambil dari payload 429 asli (RPM vs RPD), bukan angka tebakan;
  * nilai kunci tidak pernah bocor ke label/log.
"""

import json

import pytest

import gemini_key_pool as gkp

# Salinan payload 429 ASLI yang tertangkap dari Gemini (`_e_429_payload.json`).
# Dipakai apa adanya supaya tes bergantung pada bentuk nyata, bukan regex ideal.
PAYLOAD_429_RPM = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota [...] limit: 5, model: gemini-2.5-flash\\nPlease retry in "
    "5.162460926s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
    "'quotaDimensions': {'model': 'gemini-2.5-flash', 'location': 'global'}, "
    "'quotaValue': '5'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
    "'retryDelay': '5s'}]}}"
)
PAYLOAD_429_RPD = PAYLOAD_429_RPM.replace(
    "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
)
PAYLOAD_404_ENTITLEMENT = (
    "404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model "
    "models/gemini-2.5-flash-lite is no longer available to new users.', "
    "'status': 'NOT_FOUND'}}"
)


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
        (f"GEMINI_KEY_{i}", f"fake-key-{i}-{'x' * (10 + i)}", gkp.fingerprint(f"fake-key-{i}"))
        for i in range(1, n + 1)
    ]
    return gkp.KeyPool(entries=entries, now_fn=clock), clock


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def test_discover_membaca_slot_dan_mendaur_ulang_alias():
    """Alias yang menunjuk kunci sama harus jadi SATU entri (anti no-op rotasi)."""
    env = {
        "GEMINI_KEY_1": "same-secret",
        "GEMINI_KEY_2": "other-secret",
        "GEMINI_KEY_3": "",               # kosong -> diabaikan
        "GOOGLE_API_KEY": "same-secret",  # alias KEY_1
        "GEMINI_API_KEY": "",
    }
    found = gkp.discover_keys(env)
    assert [f[0] for f in found] == ["GEMINI_KEY_1", "GEMINI_KEY_2"]
    assert len({f[2] for f in found}) == 2


def test_discover_kompatibel_dengan_env_lama():
    """Tanpa `GEMINI_KEY_*`, kunci legacy tetap terbaca (backward compat)."""
    assert gkp.discover_keys({"GOOGLE_API_KEY": "legacy-secret"})[0][0] == "GOOGLE_API_KEY"


# --------------------------------------------------------------------------
# Rotasi
# --------------------------------------------------------------------------

def test_rotasi_round_robin_memakai_semua_kunci():
    pool, _ = make_pool(3)
    fps = [pool.acquire("m")[0] for _ in range(3)]
    assert len(set(fps)) == 3, "rotasi harus menggilir SEMUA kunci, bukan satu"
    assert pool.acquire("m")[0] == fps[0], "setelah putaran penuh kembali ke awal"


def test_acquire_mencatat_hit_per_kunci():
    """Bukti terukur untuk klaim '>=2 kunci dipakai' (bukan klaim kosong)."""
    pool, _ = make_pool(3)
    for _ in range(2):
        pool.acquire("m")
    used = pool.stats()["used"]
    assert len(used) == 2, f"harus ada 2 kunci tercatat terpakai, dapat {used}"


# --------------------------------------------------------------------------
# Cooldown (inti perbaikan SPOF)
# --------------------------------------------------------------------------

def test_cooldown_hanya_untuk_kunci_yang_kena():
    """Kunci kena 429 -> hanya kunci ITU yang di-skip; kunci lain tetap siap."""
    pool, _ = make_pool(3)
    fp, _key = pool.acquire("m")
    kind = pool.mark(fp, "m", exc=RuntimeError(PAYLOAD_429_RPM))
    assert kind == "rate_limited"
    assert fp not in pool.available("m")
    assert len(pool.available("m")) == 2, "cooldown TIDAK boleh global"


def test_cooldown_pulih_setelah_ttl():
    """RPM: cooldown harus lewat, bukan permanen (inilah 'recovery otomatis')."""
    pool, clock = make_pool(2)
    fp, _ = pool.acquire("m")
    pool.mark(fp, "m", exc=RuntimeError(PAYLOAD_429_RPM))
    assert fp not in pool.available("m")
    clock.advance(gkp._RPM_FLOOR_S + 1)
    assert fp in pool.available("m")


def test_semua_kunci_kena_cooldown_mengembalikan_none():
    """Kondisi 'semua habis' harus terdeteksi, bukan mengembalikan kunci basi."""
    pool, _ = make_pool(2)
    for _ in range(2):
        fp, _k = pool.acquire("m")
        pool.mark(fp, "m", exc=RuntimeError(PAYLOAD_429_RPM))
    assert pool.acquire("m") is None
    assert pool.available("m") == []


def test_ttl_rpd_lebih_lama_dari_rpm():
    """`PerDay` harus menahan jauh lebih lama daripada `PerMinute`."""
    rpm = gkp.classify_error(RuntimeError(PAYLOAD_429_RPM))[1]
    rpd = gkp.classify_error(RuntimeError(PAYLOAD_429_RPD))[1]
    assert rpm >= gkp._RPM_FLOOR_S
    assert rpd > rpm


def test_retry_delay_dari_payload_dipakai():
    """Payload tanpa `quotaId` -> angka `retryDelay` dihormati (bukan 5s karangan)."""
    kind, ttl = gkp.classify_error(RuntimeError("429 retryDelay: '42s'"))
    assert kind == "rate_limited"
    assert ttl >= 42.0


# --------------------------------------------------------------------------
# Entitlement (kunci x model)
# --------------------------------------------------------------------------

def test_404_memblokir_pasangan_kunci_model_saja():
    """404 model hanya menutup (kunci, model) itu; model lain tetap bisa."""
    pool, _ = make_pool(2)
    fp, _ = pool.acquire("gemini-2.5-flash-lite")
    kind = pool.mark(fp, "gemini-2.5-flash-lite", exc=RuntimeError(PAYLOAD_404_ENTITLEMENT))
    assert kind == "entitlement"
    assert fp not in pool.available("gemini-2.5-flash-lite")
    assert fp in pool.available("gemini-3-flash-preview"), (
        "entitlement berlaku per (kunci, model) - kunci itu masih sah untuk model lain"
    )


def test_503_overload_ditandai_sementara():
    kind, ttl = gkp.classify_error(RuntimeError("503 UNAVAILABLE: model overloaded"))
    assert kind == "overloaded"
    assert 0 < ttl <= 60


def test_error_tak_dikenal_tidak_menandai_apa_pun():
    """Jangan menelan bug nyata sebagai 'cooldown' (menyembunyikan sebab)."""
    kind, ttl = gkp.classify_error(RuntimeError("ValueError: payload rusak"))
    assert (kind, ttl) == ("unknown", 0.0)


# --------------------------------------------------------------------------
# Klien & keamanan
# --------------------------------------------------------------------------

def fake_genai_modules(monkeypatch, with_retry_options: bool = True) -> list[dict]:
    """Stub `google` + `google.genai` sebagai PAKET dengan submodul nyata.

    Modul pool mengimpor `from google.genai import types`; menstub `google`
    dengan objek biasa membuat Python gagal "'google' is not a package"
    (regresi nyata yang tertangkap tes ini). Mengembalikan daftar kwargs yang
    diterima `Client(...)` supaya tes bisa memeriksa opsi HTTP-nya.

    `with_retry_options=False` meniru SDK LAMA (`google-genai==1.6.0`, versi yang
    dulu dipasang Railway dari requirements.txt) yang **tidak punya**
    `types.HttpRetryOptions`.
    """
    import sys
    from types import ModuleType

    calls: list[dict] = []

    class _Opts:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    mod_google = ModuleType("google")
    mod_genai = ModuleType("google.genai")
    mod_types = ModuleType("google.genai.types")
    mod_types.HttpOptions = _Opts
    if with_retry_options:
        mod_types.HttpRetryOptions = _Opts

    def _client(**kw):
        calls.append(kw)
        return {"kw": kw}

    mod_genai.Client = _client
    mod_genai.types = mod_types
    mod_google.genai = mod_genai
    monkeypatch.setitem(sys.modules, "google", mod_google)
    monkeypatch.setitem(sys.modules, "google.genai", mod_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mod_types)
    return calls


def test_client_di_cache_per_kunci(monkeypatch):
    """Pembuatan client terukur ~0,86s -> wajib terjadi sekali per kunci."""
    calls = fake_genai_modules(monkeypatch)
    pool, _ = make_pool(2)
    fp, key = pool.acquire("m")
    assert pool.client(fp) is pool.client(fp)
    assert [c["api_key"] for c in calls] == [key]


def test_client_dibatasi_waktu_dan_tanpa_retry_internal(monkeypatch):
    """Satu panggilan Gemini WAJIB punya batas waktu + tanpa retry SDK.

    Gejala nyata yang memicu perbaikan ini: E2E mencatat `POST /chat
    status=-1, time=-1` (klien tidak pernah menerima respons dalam 60s).
    Sebabnya ada di SDK terpasang (v1.65.0): `HttpOptions.timeout` kosong ->
    httpx dipanggil TANPA timeout; dan `_RETRY_ATTEMPTS` default 5 dengan
    backoff sampai 60s. Karena pool yang merotasi kunci/model, percobaan ulang
    internal SDK justru menghabiskan anggaran `/chat`.
    """
    calls = fake_genai_modules(monkeypatch)
    pool, _ = make_pool(1)
    fp, _ = pool.acquire("m")
    pool.client(fp)

    opts = calls[0]["http_options"]
    # HttpOptions.timeout satuannya MILIDETIK (SDK membagi /1000 ke httpx).
    assert opts.timeout == int(gkp.CALL_TIMEOUT_S * 1000)
    assert opts.retry_options.attempts == 1, "SDK tidak boleh mengulang sendiri"
    # Harus muat dalam anggaran `/chat` (45s) supaya rotasi masih punya ruang.
    assert 0 < gkp.CALL_TIMEOUT_S <= 25, f"timeout {gkp.CALL_TIMEOUT_S}s terlalu besar"


def test_client_tetap_aman_pada_sdk_lama_tanpa_HttpRetryOptions(monkeypatch):
    """REGRESI PRODUKSI: SDK tanpa `HttpRetryOptions` TIDAK boleh menjatuhkan `/chat`.

    Bukti nyata (E2E `chat-auth` yang membidik Railway, 2026-09-16):
    `POST /chat` -> **500** `AttributeError: module 'google.genai.types' has no
    attribute 'HttpRetryOptions'`. Sebabnya `requirements.txt` memasang
    `google-genai==1.6.0` (dikonfirmasi dari wheel-nya: kelas itu memang tidak
    ada), sementara mesin dev memakai 1.65.0 -> bug ini NOL kali terlihat lokal.

    Kontrak yang dikunci di sini: pool tetap membangun client dan batas waktu
    tetap terpasang. Yang hilang hanya `attempts=1` (dan itu dilaporkan lewat
    log oleh tes berikutnya, bukan dibiarkan senyap).
    """
    calls = fake_genai_modules(monkeypatch, with_retry_options=False)
    pool, _ = make_pool(1)
    fp, _ = pool.acquire("m")
    pool.client(fp)  # sebelum perbaikan: AttributeError -> HTTP 500

    assert len(calls) == 1, "client tetap harus dibangun (bukan gagal senyap)"
    opts = calls[0]["http_options"]
    assert opts.timeout == int(gkp.CALL_TIMEOUT_S * 1000), "batas waktu wajib tetap ada"
    assert not hasattr(opts, "retry_options"), "SDK lama: tidak boleh dipaksa"


def test_sdk_lama_melaporkan_bahwa_retry_belum_dimatikan(monkeypatch, caplog):
    """Ketiadaan `HttpRetryOptions` harus TERLAPOR, bukan hilang tanpa jejak.

    Tanpa peringatan ini, satu-satunya cara mengetahui prod memakai SDK lama adalah
    dengan menabrak 500 lagi.
    """
    import logging

    calls = fake_genai_modules(monkeypatch, with_retry_options=False)
    monkeypatch.setattr(gkp, "_warned_no_retry", False, raising=False)
    pool, _ = make_pool(1)
    fp, _ = pool.acquire("m")

    with caplog.at_level(logging.WARNING, logger="gemini_key_pool"):
        pool.client(fp)
        pool.client(fp)  # kedua kali: tidak boleh spam log

    pesan = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(pesan) == 1, f"peringatan harus sekali, dapat {len(pesan)}"
    assert "HttpRetryOptions" in pesan[0]
    assert len(calls) == 1


def test_label_dan_stats_tidak_membocorkan_kunci():
    """SECURITY: label hanya NAMA#fp8; tidak ada potongan nilai kunci di stats."""
    pool, _ = make_pool(3)
    fp, key = pool.acquire("m")
    blob = json.dumps(pool.stats()["used"])
    assert key not in blob
    assert key[:8] not in blob, "potongan kunci pun tidak boleh muncul"
    assert any(fp in lbl for lbl in pool.stats()["used"])


def test_mask_key_menyembunyikan_bagian_tengah():
    masked = gkp.mask_key("AIzaSyABCDEFGHIJKL1234")
    assert masked.startswith("AIza") and masked.endswith("1234")
    assert "ABCDEFGHIJKL" not in masked


def test_pool_asli_membaca_banyak_kunci_dari_env():
    """Regresi langsung: pool produksi harus melihat >1 kunci, bukan 1.

    Inilah bug yang diperbaiki tugas ini - kode lama membaca SATU kunci
    (`GOOGLE_API_KEY or GEMINI_API_KEY or GEMINI_KEY_1`) sehingga satu 429
    mematikan seluruh jalur cadangan.
    """
    p = gkp.pool()
    assert p.size == len({e[2] for e in p._entries}), "tidak boleh ada fingerprint ganda"
    assert p.size >= 2, (
        f"pool hanya melihat {p.size} kunci unik - env harus memuat GEMINI_KEY_1..N"
    )
