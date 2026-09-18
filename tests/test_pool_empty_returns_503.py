"""test_pool_empty_returns_503.py - Pool kunci kosong -> 503, bukan 500.

Kelas bug (temuan 2026-09-18): `_agentic_run_direct` memulangkan
`HTTPException(500, "API key tidak ditemukan.")` ketika pool kosong. Itu
kondisi KONFIGURASI (env server tidak memuat `GEMINI_KEY_*`), bukan bug server,
sehingga 500 menyesatkan UI ("Terjadi kesalahan internal") dan menyembunyikan
penyebab sebenarnya. Kontrak yang benar: 503 + ajakan coba lagi.

Dua lapisan diuji supaya tidak bisa "lulus" hanya karena pool benar:
  * pool kosong -> `size == 0` dan `acquire()` -> None (tanpa exception);
  * cabang `if not _pool.size:` di api_server memakai 503 (bukan 500).
"""

import pathlib
import re

import gemini_key_pool as gkp

API = pathlib.Path(__file__).resolve().parent.parent / "api_server.py"


def _branch_src() -> str:
    """Ambil potongan source di sekitar cabang pool kosong."""
    src = API.read_text(encoding="utf-8")
    idx = src.find("if not _pool.size:")
    assert idx != -1, "cabang `if not _pool.size:` hilang dari api_server.py"
    # 12 baris setelah cabang cukup untuk memeriksa raise-nya.
    return "\n".join(src[idx:].splitlines()[:12])


def test_pool_kosong_tidak_melempar_dan_acquire_none():
    pool = gkp.KeyPool(entries=[])
    assert pool.size == 0
    assert pool.acquire("gemini-2.5-flash") is None
    assert pool.available("gemini-2.5-flash") == []


def test_cabang_pool_kosong_memakai_503_bukan_500():
    chunk = _branch_src()
    codes = re.findall(r"HTTPException\(\s*(\d+)", chunk)
    assert codes, "tidak menemukan HTTPException di cabang pool kosong"
    assert "500" not in codes, (
        "cabang pool kosong masih memulangkan 500 (%s); harus 503" % codes
    )
    assert codes[0] == "503", "kode pertama harus 503, dapat %s" % codes[0]
    assert '"Semua kunci API tidak tersedia' in chunk, (
        "pesan 503 tidak menyebut penyebab yang berguna bagi user"
    )
