"""Konfigurasi pytest bersama.

WAJIB: set `ALLOWED_HOSTS` SEBELUM `api_server` diimpor.

Latar belakang (CVE-2026-48710 / Starlette BadHost):
`api_server` memasang `TrustedHostMiddleware` yang membaca `ALLOWED_HOSTS`
saat modul diimpor. `starlette.testclient.TestClient` memakai
`base_url="http://testserver"` secara default, jadi tanpa baris di bawah
SELURUH test yang memakai TestClient (24 file di repo ini) gagal dengan
`400 Invalid host header` - bukan karena ada bug, tapi karena host test tidak
berada di allowlist.

Kenapa `testserver` TIDAK ditulis ke `.env`:
`.env` adalah konfigurasi produksi. `testserver` bukan hostname yang pernah
menuju server sungguhan, dan membiarkannya di sana berarti satu kelalaian
ke depan (menyalin `.env` ke demo/public) ikut membuka nama host itu.
`load_dotenv()` tidak meng-override variabel yang sudah ada di
`os.environ`, jadi nilai di sini menang tanpa perlu `override=True`.
"""
import os

import pytest

# Host yang dipakai TestClient + host yang sudah ada di .env.
# Diambil dari .env bila ada, supaya test dan lokal tidak bisa berbeda
#keempat Kalimat tidak perlu ada di sini.
_extra = ["testserver", "localhost", "127.0.0.1"]

_existing = os.environ.get("ALLOWED_HOSTS", "").strip()
_hosts = [h.strip() for h in _existing.split(",") if h.strip()] if _existing else []
for h in _extra:
    if h not in _hosts:
        _hosts.append(h)

os.environ["ALLOWED_HOSTS"] = ",".join(_hosts)

# Scheduled Trigger (cron): loop TIDAK boleh jalan di dalam pytest — tick
# tiap 20s akan berlomba dengan test yang memanggil scheduler_manager.tick()
# secara deterministik. Test live uvicorn menyetel SCHEDULER_ENABLED=1 di
# proses servernya sendiri.
os.environ.setdefault("SCHEDULER_ENABLED", "0")


@pytest.fixture(autouse=True)
def _bersihkan_event_loop_menggantung():
    """Buang penanda "event loop sedang berjalan" yang ditinggalkan test lain.

    MASALAH NYATA (terukur 2026-10-06, full-suite `pytest -q`):
    `test_browser_e2e.py` di root memakai Playwright sync API. Di mesin tanpa
    Streamlit di :8501 ketiga test-nya gagal, dan kegagalan itu meninggalkan
    penanda running-loop di thread pemanggil. Setelah itu SETIAP
    `asyncio.run(...)` di suite gagal dengan:

        RuntimeError: Cannot run the event loop while another loop is running

    Korban yang terlihat: `tests/test_provider_registry.py`
    (`test_run_async_sama_hasilnya`, `test_exec_mcp_*`) dan
    `tests/test_mcp_gateway/test_client.py` (test `health()`). Semuanya LULUS
    saat file-nya dijalankan terpisah, dan gagal begitu dijalankan setelah
    `test_browser_e2e.py` — jadi penyebabnya urutan, bukan logika test.

    Fixture ini membersihkan STATUS THREAD saja: bila tidak ada loop yang
    menggantung, ia tidak melakukan apa pun. Ia sengaja berjalan di SETUP
    (bukan teardown) supaya dapat membersihkan sisa test mana pun yang
    dieksekusi lebih dulu, termasuk test di luar folder `tests/`.
    """
    import asyncio.events as _ev

    if _ev._get_running_loop() is not None:
        _ev._set_running_loop(None)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Kosongkan SEMUA rate limiter sebelum tiap tes.

    Rate limit bersifat in-memory per proses (rate_limit.py). Tanpa reset,
    tes yang memanggil `/chat`, `/workflows` (INSERT), atau `execute_textual_tool`
    berkali-kali dengan user yang sama bisa saling menabrak batas -> gagal
    karena urutan, bukan logika. Reset juga membuat tes rate-limit deterministik.
    """
    try:
        import rate_limit
        rate_limit.reset_all()
    except Exception:  # noqa: BLE001 - rate_limit opsional di beberapa tes
        pass
    yield


@pytest.fixture(autouse=True)
def _isolate_connector_store():
    """Matikan jalur DB connector selama tes (isolasi WAJIB).

    Kenapa perlu: `mcp_registry._activated_ids()` memprioritaskan Supabase.
    Menyetel `catalog.ACTIVATION_PATH` saja TIDAK mengisolasi tes — id
    produksi (995 baris) tetap terbaca, sehingga `report['persisted']['added']`
    selalu 0 dan `_CACHE` bersama ikut tercemar antar-tes. Bahkan lebih buruk:
    menulis ke DB produksi dari dalam tes.

    Fixture ini mematikan `connector_store.available()` (lewat env kill-switch
    `CONNECTOR_STORE_DISABLED=1`) dan mereset cache `_ACTIVATED_IDS`, sehingga
    berkas lokal (yang di-monkeypatch tiap tes) menjadi sumber tunggal.
    """
    prev = os.environ.get("CONNECTOR_STORE_DISABLED")
    os.environ["CONNECTOR_STORE_DISABLED"] = "1"
    try:
        import mcp_registry as catalog
        catalog._ACTIVATED_IDS = None
    except Exception:  # noqa: BLE001 - katalog opsional di beberapa tes
        pass
    yield
    if prev is None:
        os.environ.pop("CONNECTOR_STORE_DISABLED", None)
    else:
        os.environ["CONNECTOR_STORE_DISABLED"] = prev
    try:
        import mcp_registry as catalog
        catalog._ACTIVATED_IDS = None
    except Exception:  # noqa: BLE001
        pass
