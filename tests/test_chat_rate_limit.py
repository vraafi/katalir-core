"""test_chat_rate_limit.py - BUG-5 (adversarial 2026-10-07): rate limit POST /chat.

Temuan BUG-5 pada `docs/security/adversarial-test-n8n-hardcore-user-2026-10-07.md`:
`POST /chat` tidak membatasi request per user - burst 8 paralel menghasilkan
8/8 HTTP 200 (median 16.7 s) tanpa satu pun HTTP 429, sehingga 13 LLM key /
27 RPM kehabisan RPM dan 503 cooldown menyebar ke SEMUA user.

Tes ini mengunci dua sisi:

  1. MEKANIKA  - sliding window `rate_limit.SlidingWindowLimiter`:
     batas per window, pelepasan setelah window bergeser, request yang
     ditolak TIDAK menambah slot (percobaan gagal tidak menunda pemulihan),
     `retry_after` bulat naik minimal 1 detik, dan `max_calls <= 0` =
     nonaktif (fail-open disengaja untuk E2E lokal).
  2. PERILAKU  - `/chat` membalas HTTP 429 dengan `detail` non-kosong
     (kontrak pesan sama seperti BUG-4) + header `Retry-After`, request
     pertama tetap 200, dan REPLAY idempoten tidak memakan slot rate limit
     (konsisten dengan penempatan kuota: replay = gratis).
"""

import pytest

import rate_limit
from rate_limit import SlidingWindowLimiter

api_server = pytest.importorskip("api_server")
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# 1. MEKANIKA - sliding window (jam tiruan, tanpa sleep nyata)
# ---------------------------------------------------------------------------
class _FakeClock:
    """Jam monotonic yang dimajukan manual - tes deterministik tanpa sleep."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, sec: float):
        self.now += sec


def test_sliding_window_batas_dan_pelepasan():
    """Sampai batas -> lolos; lewat batas -> tolak; window lewat -> lolos lagi."""
    clk = _FakeClock()
    lim = SlidingWindowLimiter(3, 60, clock=clk)

    for i in range(3):
        ok, retry = lim.check("u1")
        assert ok is True and retry == 0.0, f"permintaan ke-{i + 1} seharusnya lolos"

    ok, retry = lim.check("u1")
    assert ok is False
    assert retry >= 1.0, "retry_after harus detik bulat naik, minimal 1"

    # Ditolak TIDAK menambah slot: waktu maju 59 dtk dari stamp pertama,
    # window stamp pertama belum lewat -> masih ditolak.
    clk.advance(59)
    ok, _ = lim.check("u1")
    assert ok is False

    # Stamp pertama berumur 60 dtk penuh -> terlempar dari window, slot bebas.
    clk.advance(1)
    ok, _ = lim.check("u1")
    assert ok is True


def test_key_terpisah_antar_user():
    """Limit per-key: satu user yang memenuhi slot tidak menjatuhkan user lain."""
    clk = _FakeClock()
    lim = SlidingWindowLimiter(1, 60, clock=clk)
    assert lim.check("alice")[0] is True
    assert lim.check("alice")[0] is False
    assert lim.check("bob")[0] is True


def test_ditolak_tidak_menambah_slot():
    """Percobaan yang ditolak tidak dicatat - pemulihan tidak ditunda."""
    clk = _FakeClock()
    lim = SlidingWindowLimiter(2, 60, clock=clk)
    lim.check("u1")
    lim.check("u1")
    for _ in range(10):  # gagal beruntun tidak boleh menggeser window
        assert lim.check("u1")[0] is False
    assert lim.snapshot("u1") == 2


def test_retry_after_bulat_naik_minimal_satu_detik():
    """Retry-After header butuh integer >= 1 (RFC 7231 satuan detik)."""
    clk = _FakeClock()
    lim = SlidingWindowLimiter(1, 60, clock=clk)
    lim.check("u1")
    ok, retry = lim.check("u1")
    assert ok is False
    # Masih 60 detik tersisa -> dibulatkan ke atas.
    assert retry == 60.0
    clk.advance(59.5)
    ok, retry = lim.check("u1")
    assert ok is False and retry == 1.0


def test_limit_nol_menonaktifkan_limiter():
    """`CHAT_RATE_LIMIT<=0` = fail-open (dipakai E2E lokal yang menembak cepat)."""
    lim = SlidingWindowLimiter(0, 60, clock=_FakeClock())
    for _ in range(100):
        ok, retry = lim.check("u1")
        assert ok is True and retry == 0.0


def test_reset_membersihkan_state():
    lim = SlidingWindowLimiter(1, 60, clock=_FakeClock())
    lim.check("u1")
    assert lim.check("u1")[0] is False
    lim.reset()
    assert lim.check("u1")[0] is True


def test_env_number_default_dan_invalid(monkeypatch):
    """Env kosong -> default; env rusak -> default (tidak menonaktifkan limit)."""
    monkeypatch.delenv("CHAT_RATE_LIMIT_X", raising=False)
    assert rate_limit._env_number("CHAT_RATE_LIMIT_X", 10) == 10

    monkeypatch.setenv("CHAT_RATE_LIMIT_X", "25")
    assert rate_limit._env_number("CHAT_RATE_LIMIT_X", 10) == 25

# ---------------------------------------------------------------------------
# 2. PERILAKU - POST /chat
# ---------------------------------------------------------------------------
@pytest.fixture()
def chat_client(monkeypatch):
    """Klien /chat dengan auth + DB di-mock (pola test_503_detail_contract)."""
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"email": "rl505@test.dev", "id": "uid-rl"})
    monkeypatch.setattr(api_server.db, "get_or_create_user",
                        lambda *a, **k: {"email": "rl505@test.dev", "tier": "free"})
    monkeypatch.setattr(api_server.db, "find_user_message_by_request", lambda *a: None)
    monkeypatch.setattr(api_server.db, "create_session",
                        lambda *a, **k: {"id": "sess-rl"})
    monkeypatch.setattr(api_server, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(api_server.db, "add_message", lambda *a, **k: True)
    monkeypatch.setattr(api_server.db, "check_quota",
                        lambda e, m, t: (True, {"bucket": "gemma", "used": 0,
                                                "limit": 100, "remaining": 100}))
    monkeypatch.setattr(api_server.db, "increment_quota", lambda *a, **k: None)
    monkeypatch.setattr(api_server.db, "quota_status",
                        lambda e, t: {"used_total": 0, "limit_total": 100})
    monkeypatch.setattr(api_server, "_agentic_run_direct",
                        lambda *a, **k: {"reply": "ok", "meta": {}})
    # Instance limiter TERPISAH per tes - negara global tidak boleh bocor
    # antar test (dan test lain tidak boleh terpengaruh limit ini).
    monkeypatch.setattr(rate_limit, "chat_limiter", SlidingWindowLimiter(2, 60))
    return TestClient(api_server.app)


def _post(client, prompt="halo", **kw):
    return client.post("/chat", json={"prompt": prompt, **kw},
                       headers={"Authorization": "Bearer x"})


def test_burst_ke_tiga_mendapat_429_dengan_detail(chat_client):
    """Request melebihi limit -> 429 + `detail` non-kosong + Retry-After."""
    assert _post(chat_client).status_code == 200
    assert _post(chat_client).status_code == 200

    r = _post(chat_client)
    assert r.status_code == 429, r.text
    body = r.json()
    assert str(body.get("detail") or "").strip(), f"detail kosong: {r.text!r}"
    # Pesan HARUS manusiawi dan menyebut batasnya (bukan kode telanjang).
    assert "permintaan" in body["detail"].lower()
    assert "Batas" in body["detail"]
    # Header Retry-After wajib ada dan berupa detik bulat >= 1.
    retry_after = r.headers.get("Retry-After")
    assert retry_after is not None, (
        "Retry-After hilang - klien tidak tahu kapan boleh coba lagi")
    assert int(retry_after) >= 1


def test_limit_per_user_bukan_global(chat_client, monkeypatch):
    """User lain tidak terkena imbas limit user pertama."""
    lim = rate_limit.chat_limiter
    assert lim.check("uid-rl")[0] is True
    assert lim.check("uid-rl")[0] is True
    assert lim.check("uid-rl")[0] is False  # slot uid-rl habis

    # Request dengan JWT user berbeda tetap dilayani.
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"email": "lain@test.dev", "id": "uid-lain"})
    assert _post(chat_client).status_code == 200


def test_replay_idempoten_tidak_makan_slot_rate_limit(chat_client, monkeypatch):
    """Replay idempoten (sudah punya jawaban) wajib kembali SEBELUM rate limit.

    Menempatkan rate limit setelah early-return idempotensi = konsisten
    dengan penempatan kuota: replay tidak memanggil LLM, jadi tidak boleh
    memakan slot maupun kuota.
    """
    # Request pertama: memakan 1 dari 2 slot.
    assert _post(chat_client).status_code == 200

    # Replay dengan client_request_id yang sudah tercatat + jawaban tersimpan.
    monkeypatch.setattr(
        api_server.db, "find_user_message_by_request",
        lambda req_id: {"session_id": "sess-rl"})
    monkeypatch.setattr(
        api_server.db, "get_last_assistant_reply",
        lambda *a, **k: "jawaban tersimpan")
    r = _post(chat_client, prompt="ulang", client_request_id="req-1")
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "jawaban tersimpan"

    # Slot tinggal 1 (replay tidak menambah) -> request BARU masih dilayani,
    # lalu habis.
    assert _post(chat_client).status_code == 200
    assert _post(chat_client).status_code == 429
    assert rate_limit.chat_limiter.snapshot("uid-rl") == 2


def test_kuota_429_dan_rate_limit_429_sama_berpesan(chat_client, monkeypatch):
    """Dua jalur 429 berbeda (kuota vs rate limit) sama-sama berpesan jelas."""
    # Jalur 1: kuota habis (rate limit belum tercapai) -> pesan kuota.
    monkeypatch.setattr(api_server, "_quota_exhausted_message",
                        lambda info, tier: "Kuota harian Anda sudah habis.")
    monkeypatch.setattr(api_server.db, "check_quota",
                        lambda e, m, t: (False, {"bucket": "gemma", "used": 100,
                                                 "limit": 100, "remaining": 0}))
    monkeypatch.setattr(api_server, "_bucket_model_id",
                        lambda b: "google/gemma-4-31b-it")
    monkeypatch.setattr(api_server.db, "quota_fallback_bucket", lambda *a: None)

    r1 = _post(chat_client)
    assert r1.status_code == 429
    assert "kuota harian" in r1.json()["detail"].lower()
    # Request yang ditolak kuota TETAP memakan slot rate limit (rate limit
    # berjalan lebih dulu) - dokumentasikan urutannya secara eksplisit.
    assert rate_limit.chat_limiter.snapshot("uid-rl") == 1

    # Jalur 2: slot habis -> pesan rate limit, bukan pesan kuota.
    assert _post(chat_client).status_code == 429  # slot terakhir terpakai
    r3 = _post(chat_client)
    assert r3.status_code == 429
    detail3 = r3.json()["detail"].lower()
    assert "kuota" not in detail3
    assert "permintaan" in detail3


    monkeypatch.setenv("CHAT_RATE_LIMIT_X", "sepuluh")
    assert rate_limit._env_number("CHAT_RATE_LIMIT_X", 10) == 10, (
        "env tidak valid harus jatuh ke default, BUKAN mematikan limiter"
    )


def test_instance_global_terkonfigurasi():
    """Instance global dipakai endpoint /chat dan default-nya masuk akal."""
    assert isinstance(rate_limit.chat_limiter, SlidingWindowLimiter)
    assert rate_limit.chat_limiter.window_sec > 0
    # Default proyek: 10 pesan/menit per user (env boleh meng-override saat
    # runtime, tapi angka dasar ini yang dilindungi dari regresi "tanpa limit").
    assert rate_limit.chat_limiter.max_calls > 0
