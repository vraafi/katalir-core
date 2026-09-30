"""Pemuat `.env` yang aman untuk repo Katalir.

KENAPA MODUL INI ADA
-------------------
`python-dotenv` versi ini mencari `.env` mulai dari **folder tempat modul
berada**, lalu merayap **naik ke folder induk** sampai ketemu. Itu berarti
`load_dotenv()` tanpa argumen bisa diam-diam membaca file milik program LAIN.

Kasus nyata di mesin ini (2026-09-30): `Proyek_AI/.env` dihapus, lalu
`load_dotenv(override=True)` di `scripts/ai_tools_mcp.py` merayap sampai
`C:\\Users\\user\\.env` - file UTF-16 milik program lain - dan crash:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff
    20 errors during collection  (seluruh suite test mati)

Jadi semua pemanggilan `load_dotenv()` di repo ini WAJIB memakai
`load_repo_env()` dari modul ini, yang:

1. Menekan path ke `<repo-root>/.env` secara deterministik - tidak pernah
   merayap ke luar repo.
2. Tidak crash kalau `.env` tidak ada (mis. di CI, atau user memang belum
   membuatkannya) - hanya memberi peringatan.
3. Mengembalikan `Path` yang ditemukan supaya pemanggil bisa melaporkannya.

`override=True` dipakai karena skrip operasional perlu env yang di-explicit
override variabel shell, sesuai perilaku lama.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


def load_repo_env(*, override: bool = True) -> Path | None:
    """Muat `<repo-root>/.env` saja. Kembalikan path-nya, atau None.

    Tidak pernah mencari ke luar repo. Tidak pernah crash kalau file tidak ada.
    """
    if ENV_PATH.is_file():
        load_dotenv(dotenv_path=ENV_PATH, override=override)
        return ENV_PATH

    # Fallback diam-diam: kalau env sudah ada di environment (Railway, CI,
    # docker), itu sah - jangan error, cukup beri tahu sekali.
    if os.environ.get("SUPABASE_URL") or os.environ.get("RAILWAY_ENVIRONMENT"):
        print(
            f"[dotenv] .env tidak ada di {ROOT}; memakai environment yang sudah ada.",
            file=sys.stderr,
        )
        return None

    print(
        f"[dotenv] WARNING: .env tidak ditemukan di {ENV_PATH}. "
        "Variabel dari environment proses tetap dipakai, tapi credential "
        "wajib diisi manual. Lihat .env.template untuk daftar key.",
        file=sys.stderr,
    )
    return None


__all__ = ["ROOT", "ENV_PATH", "load_repo_env"]
