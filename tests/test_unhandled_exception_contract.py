# -*- coding: utf-8 -*-
"""Kontrak exception TAK TERTANGANI: 5xx wajib berpesan + status yang benar.

LATAR (insiden 11 Okt 2026). Saat 10 request `/chat` konkuren, `/chat` membalas
**`500 Internal Server Error` tanpa `detail`** (body teks polos = jalur default
Starlette, artinya exception lolos dari endpoint tanpa handler). Terukur di
`/root/api_server.log`: 71 `Exception in ASGI application`, didominasi
`httpx.RemoteProtocolError: Server disconnected` dari
`database._quota_write` -> `user_usage.insert`.

Jalur bocornya spesifik: `db.check_quota(...)` di `api_server.py` TIDAK berada
di dalam `try/except` mana pun, sehingga kegagalan tulis kuota naik sampai
Starlette. Akibatnya `classifyHttpError(500)` di frontend menandai
`retryable: false` dan tombol "Coba Lagi" tidak muncul, padahal gangguannya
sementara.

Yang dikunci di sini:
  1. exception TRANSPORT (`RemoteProtocolError` dkk) -> 503 + `detail` berisi;
  2. exception lain (kemungkinan bug)             -> 500 + `detail` berisi;
  3. `HTTPException` TIDAK ikut tertelan handler global (401/403 tetap asli).
"""
import pytest

api_server = pytest.importorskip("api_server")
from fastapi.testclient import TestClient  # noqa: E402


class RemoteProtocolError(Exception):
    """Nama kelas SENGAJA sama dengan `httpx.RemoteProtocolError`.

    Handler memetakan berdasarkan NAMA kelas (`_TRANSIENT_EXC_NAMES`) supaya
    `api_server` tidak perlu mengimpor httpx hanya untuk ini. Memakai kelas
    lokal di sini membuktikan pemetaan itu bekerja apa adanya.
    """


def _client(monkeypatch):
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"email": "unh@test.dev", "id": "uid-1"})
    monkeypatch.setattr(api_server.db, "get_or_create_user",
                        lambda *a, **k: {"email": "unh@test.dev", "tier": "free"})
    monkeypatch.setattr(api_server.db, "find_user_message_by_request", lambda *a: None)
    monkeypatch.setattr(api_server, "load_history", lambda *a, **k: [])
    return TestClient(api_server.app, raise_server_exceptions=False)


def test_exception_transport_menjadi_503_berpesan(monkeypatch):
    """Gangguan koneksi = SEMENTARA -> 503 (retryable) + detail, bukan 500 hampa."""
    c = _client(monkeypatch)

    def _boom(*a, **k):
        raise RemoteProtocolError("Server disconnected")

    monkeypatch.setattr(api_server.db, "check_quota", _boom)
    r = c.post("/chat", json={"prompt": "halo"}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 503, f"harus 503 (retryable), dapat {r.status_code}: {r.text}"
    body = r.json()
    assert str(body.get("detail") or "").strip(), f"detail kosong: {r.text!r}"
    assert "RemoteProtocolError" in body["detail"]


def test_exception_bug_biasa_tetap_500_tapi_berpesan(monkeypatch):
    """Bug nyata TIDAK boleh disamarkan jadi 'coba lagi nanti'.

    Status tetap 500, tetapi `detail` WAJIB ada supaya klien punya teks untuk
    ditampilkan (kontrak yang sama dengan test_503_detail_contract.py).
    """
    c = _client(monkeypatch)

    def _boom(*a, **k):
        raise ValueError("bug nyata")

    monkeypatch.setattr(api_server.db, "check_quota", _boom)
    r = c.post("/chat", json={"prompt": "halo"}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 500, f"harus tetap 500, dapat {r.status_code}: {r.text}"
    body = r.json()
    assert str(body.get("detail") or "").strip(), f"detail kosong: {r.text!r}"
    assert "ValueError" in body["detail"]


def test_httpexception_tidak_tertelan_handler_global(monkeypatch):
    """`HTTPException` harus tetap memakai status aslinya.

    Kalau handler `Exception` ikut menangkapnya, 401 akan berubah menjadi 503
    dan seluruh kontrak status API rusak.
    """
    c = TestClient(api_server.app, raise_server_exceptions=False)
    r = c.post("/chat", json={"prompt": "halo"})  # tanpa Authorization
    assert r.status_code == 401, f"harus 401, dapat {r.status_code}: {r.text}"
