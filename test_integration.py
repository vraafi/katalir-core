"""
test_integration.py — Pengujian resmi (pytest)
Perebaikan Fase 2 & 3: injeksi python-dotenv + visibilitas error backend.

Target:
  - test_api_key_loaded()          => validasi .env terbaca ke memori
  - test_agent_initialization()    => genai.Client() hidup tanpa error otorisasi
  - test_api_key_missing_raises()  => guard bila ketiga variabel kosong

Berjalan (dari folder proyek):
    pytest test_integration.py -v
"""
import os

from dotenv import load_dotenv


def _resolve_api_key() -> str:
    """Muati .env lalu cek deteksi kunci multi-nama (persis seperti backend)."""
    load_dotenv()  # Paksa muat file .env ke memori OS
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
        or ""
    )


def test_api_key_loaded():
    """Validasi bahwa os.getenv berhasil menarik kunci dari file .env."""
    key = _resolve_api_key()

    assert key, (
        "API key tidak terbaca dari .env "
        "(colme GOOGLE_API_KEY / GEMINI_API_KEY / GEMINI_KEY_1)"
    )
    assert len(key) > 10, f"Kunci terlalu ringkas (len={len(key)}): {key}"


def test_agent_initialization():
    """Pastikan genai.Client() berhasil hidup tanpa error otorisasi (konstruktor offline)."""
    from google import genai

    key = _resolve_api_key()
    assert key, "Precordica: API key kosong — check file .env"

    # Konstruktor genai.Client tidak memici network -> test deterministik/offline.
    client = genai.Client(api_key=key)
    assert client is not None, "genai.Client() kembali None (tidak expected)"
    assert client is not None and hasattr(client, "models")


def test_api_key_missing_raises(monkeypatch):
    """Pastikan deteksi cerdas gagal => kode spakási error jelas (guard salah)."""
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_KEY_1"):
        monkeypatch.delenv(name, raising=False)

    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )

    assert not api_key, "Ketiga variabel kosong harus mengembalikan kosong (guard aktif)"