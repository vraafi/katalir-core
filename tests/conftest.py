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
