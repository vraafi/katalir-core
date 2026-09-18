"""test_daily_quota.py - Kuota HARIAN per model (struktur bisnis final).

Mengunci keputusan bisnis 2026-09-18 supaya tidak "diam-diam" berubah:
  free 100 (Gemma) · plus 600 · pro 1.050 · ultra 3.200 (Flash 2.500, Pro 200).
Juga mengunci mekanika yang mudah salah:
  * reset memakai TANGGAL WIB (UTC+7), bukan selisih 24 jam;
  * pemetaan id model -> bucket (DeepSeek Flash/Pro vs jalur gratis);
  * auto-fallback Pro -> Flash -> Gemma saat bucket di atas habis;
  * penghitung dinaikkan HANYA lewat jalur yang menaikkannya sekali/req.

Semua tes dijalankan di jalur MEMORI (`is_configured` dipaksa False) sehingga
tidak menyentuh Supabase maupun jaringan.
"""

from datetime import datetime, timedelta, timezone

import pytest

import database as db

WIB = timezone(timedelta(hours=7))
FREE_MODEL = "google/gemma-4-31b-it"
FLASH_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
PRO_MODEL = "deepseek-ai/deepseek-v4-pro-0731"


@pytest.fixture(autouse=True)
def memory_db(monkeypatch):
    """Paksa jalur memori + state kuota bersih untuk setiap tes."""
    monkeypatch.setattr(db, "is_configured", lambda: False)
    db._LQUOTA.clear()
    yield
    db._LQUOTA.clear()


def _set_used(email, tier, **used):
    """Isi penghitung harian seolah sudah terpakai (tanpa lewat /chat)."""
    db.check_and_reset(email)
    db._LQUOTA[email].update({"daily_%s" % k: v for k, v in used.items()})


# ---------------------------------------------------------------------------
def test_quota_free_100_gemma():
    """Free: 100 Gemma/hari, tanpa DeepSeek sama sekali."""
    lim = db.get_quota_limit("free")
    assert lim == {"gemma": 100, "flash": 0, "pro": 0}
    assert db.quota_total_limit("free") == 100
    # DeepSeek tidak boleh tersedia untuk free (limit 0 -> selalu ditolak).
    allowed, info = db.check_quota("free@test.dev", FLASH_MODEL, "free")
    assert allowed is False and info["bucket"] == "flash" and info["limit"] == 0


def test_quota_plus_600_total():
    """Plus (Rp 5jt/tahun): Gemma 500 + DeepSeek Flash 100 = 600/hari."""
    lim = db.get_quota_limit("plus")
    assert lim == {"gemma": 500, "flash": 100, "pro": 0}
    assert db.quota_total_limit("plus") == 600
    _set_used("plus@test.dev", "plus", gemma=350, flash=15)
    st = db.quota_status("plus@test.dev", "plus")
    assert st["used_total"] == 365 and st["limit_total"] == 600
    assert st["buckets"]["gemma"]["remaining"] == 150
    assert st["buckets"]["flash"]["remaining"] == 85


def test_quota_pro_1050_total():
    """Pro (Rp 20jt/tahun): Gemma 500 + Flash 500 + Pro 50 = 1.050/hari."""
    lim = db.get_quota_limit("pro")
    assert lim == {"gemma": 500, "flash": 500, "pro": 50}
    assert db.quota_total_limit("pro") == 1050


def test_quota_ultra_3200_total():
    """Ultra (Rp 50jt/tahun): Gemma 500 + Flash 2.500 + Pro 200 = 3.200/hari."""
    lim = db.get_quota_limit("ultra")
    assert lim == {"gemma": 500, "flash": 2500, "pro": 200}
    assert db.quota_total_limit("ultra") == 3200
    # Prinsip "jangan pelit Gemma": SEMUA tier berbayar dapat 500, bukan lebih kecil.
    assert db.get_quota_limit("plus")["gemma"] == 500
    assert db.get_quota_limit("pro")["gemma"] == 500


def test_reset_at_midnight_wib():
    """Reset mengikuti TANGGAL WIB (UTC+7), bukan selisih 24 jam."""
    email = "reset@test.dev"
    # 23:59 WIB kemarin -> sudah lewat tengah malam WIB sekarang -> RESET.
    now = datetime(2026, 9, 18, 10, 0, tzinfo=WIB)
    assert db.quota_reset_due(datetime(2026, 9, 17, 16, 59, tzinfo=timezone.utc), now) is True
    # 00:01 WIB hari ini -> belum ganti tanggal -> TIDAK reset.
    assert db.quota_reset_due(datetime(2026, 9, 17, 17, 1, tzinfo=timezone.utc), now) is False
    # Perilaku di fungsi reset: counter kembali 0 setelah tanggal berganti.
    _set_used(email, "plus", gemma=99, flash=42)
    db._LQUOTA[email]["daily_reset_at"] = datetime(2026, 9, 17, tzinfo=timezone.utc)
    assert db.check_and_reset(email, now) is True
    assert db._LQUOTA[email]["daily_gemma"] == 0
    assert db._LQUOTA[email]["daily_flash"] == 0
    # Jam 23:59 WIB pada hari yang SAMA -> tidak reset lagi.
    _set_used(email, "plus", gemma=7)
    same_day = datetime(2026, 9, 18, 23, 59, tzinfo=WIB)
    assert db.check_and_reset(email, same_day) is False
    assert db._LQUOTA[email]["daily_gemma"] == 7


def test_fallback_pro_flash_gemma():
    """Kuota Pro habis -> turun ke Flash; Flash habis -> turun ke Gemma."""
    email = "fallback@test.dev"
    tier = "pro"
    # Pro habis, Flash masih sisa -> fallback ke flash.
    _set_used(email, tier, pro=50, flash=10, gemma=0)
    assert db.quota_fallback_bucket(email, tier, "pro") == "flash"
    # Flash ikut habis -> fallback ke gemma.
    _set_used(email, tier, pro=50, flash=500, gemma=0)
    assert db.quota_fallback_bucket(email, tier, "pro") == "gemma"
    # Semua habis -> None (pemanggil wajib menolak dengan pesan jelas).
    _set_used(email, tier, pro=50, flash=500, gemma=500)
    assert db.quota_fallback_bucket(email, tier, "pro") is None
    # Dan dari Gemma tidak ada fallback lebih murah.
    assert db.quota_fallback_bucket(email, tier, "gemma") is None


# ---------------------------------------------------------------------------
# WIRING /chat: kuota ditegakkan SEBELUM pesan disimpan, dan fallback dipakai.
# ---------------------------------------------------------------------------
api_server = pytest.importorskip("api_server")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def chat_client(monkeypatch):
    """Klien /chat dengan auth + agent di-mock (tanpa DB, tanpa LLM)."""
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"email": "quota@test.dev", "id": "uid-1"})
    monkeypatch.setattr(api_server.db, "get_or_create_user",
                        lambda *a, **k: {"email": "quota@test.dev", "tier": "plus"})
    monkeypatch.setattr(api_server.db, "find_user_message_by_request", lambda *a: None)
    monkeypatch.setattr(api_server.db, "create_session",
                        lambda *a, **k: {"id": "sess-1"})
    monkeypatch.setattr(api_server, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(api_server.db, "add_message", lambda *a, **k: True)
    return TestClient(api_server.app)


def test_chat_429_saat_kuota_habis_total(chat_client, monkeypatch):
    """Semua bucket habis -> 429 dengan pesan yang menyebut sisa & reset."""
    monkeypatch.setattr(api_server.db, "check_quota",
                        lambda e, m, t: (False, {"bucket": "gemma", "used": 500,
                                                 "limit": 500, "remaining": 0}))
    monkeypatch.setattr(api_server.db, "quota_fallback_bucket", lambda *a: None)
    r = chat_client.post("/chat", json={"prompt": "halo", "model": FREE_MODEL},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 429, r.text
    assert "Kuota harian habis" in r.json()["detail"]
    assert "00:00 WIB" in r.json()["detail"]


def test_chat_fallback_ke_bucket_lebih_murah(chat_client, monkeypatch):
    """Bucket mahal habis -> /chat jalan dengan model bucket lebih murah + meta."""
    seen = {}

    def fake_run(prompt, email, model=None, user_tier="free", history=None):
        seen["model"] = model
        return {"reply": "ok", "meta": {"model": model}}

    monkeypatch.setattr(api_server, "_agentic_run_direct", fake_run)
    monkeypatch.setattr(api_server.db, "check_quota",
                        lambda e, m, t: (False, {"bucket": "pro", "used": 50,
                                                 "limit": 50, "remaining": 0}))
    monkeypatch.setattr(api_server.db, "quota_fallback_bucket",
                        lambda *a: "flash")
    monkeypatch.setattr(api_server, "_bucket_model_id", lambda b: FLASH_MODEL)
    called = {}
    monkeypatch.setattr(api_server.db, "increment_quota",
                        lambda e, m: called.setdefault("counted", m))
    monkeypatch.setattr(api_server.db, "quota_status",
                        lambda e, t: {"buckets": {}, "used_total": 0, "limit_total": 600})

    r = chat_client.post("/chat", json={"prompt": "halo", "model": PRO_MODEL},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["model"] == FLASH_MODEL, "model fallback tidak dipakai"
    assert body["meta"]["quota_fallback"] is True
    assert body["meta"]["quota_fallback_from"] == "pro"
    assert called["counted"] == FLASH_MODEL, "kuota dihitung dari model yang dipakai"
    assert body["meta"]["quota_bucket"] == "flash"
