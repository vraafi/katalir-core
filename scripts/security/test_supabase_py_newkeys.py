"""Uji kompatibilitas supabase-py dengan key format BARU (`sb_*`).

Tujuan: membuktikan apakah `database.py:102` (`create_client(SUPABASE_URL, key)`)
perlu diubah saat migrasi ke `sb_secret_`, atau cukup ganti NILAI di `.env`.

Yang diuji: `create_client` + publishable key baru -> query nyata ke PostgREST.
Kalau jalan, migrasi tidak memerlukan perubahan kode di `database.py`.
"""
import importlib.metadata as md
import pathlib
import re

from supabase import create_client

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / ".env.bak-20260917-014828"


def main() -> int:
    try:
        print(f"supabase-py = {md.version('supabase')}")
    except Exception as exc:  # noqa: BLE001
        print(f"supabase-py tidak terbaca: {exc}")

    text = SRC.read_text(encoding="utf-8", errors="replace")
    url = re.search(r"^SUPABASE_URL\s*=\s*(\S+)", text, re.M).group(1).strip()
    pub = re.search(r"^SUPABASE_PUBLISHABLE_KEY\s*=\s*(\S+)", text, re.M).group(1).strip()
    legacy = re.search(r"^SUPABASE_SERVICE_ROLE_KEY\s*=\s*(\S+)", text, re.M).group(1).strip()

    print()
    print("=== create_client() dengan key format BARU (sb_publishable_) ===")
    try:
        c = create_client(url, pub)
        r = c.table("workflows").select("id").limit(1).execute()
        print(f"  -> OK, rows={len(r.data)}  (RLS ditegakkan, publishable bukan elevated)")
    except Exception as exc:  # noqa: BLE001
        print(f"  -> GAGAL {type(exc).__name__}: {str(exc)[:110]}")

    print()
    print("=== create_client() dengan key LAMA (service_role JWT) ===")
    try:
        c = create_client(url, legacy)
        r = c.table("workflows").select("id").limit(1).execute()
        print(f"  -> OK, rows={len(r.data)}  (bypass RLS)")
    except Exception as exc:  # noqa: BLE001
        print(f"  -> GAGAL {type(exc).__name__}: {str(exc)[:110]}")

    print()
    print("KESIMPULAN: kalau kedua baris OK, `create_client()` di database.py:102")
    print("tidak perlu diubah - hanya NILAI di .env yang berganti format.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
