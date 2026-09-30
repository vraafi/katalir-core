"""Tes koneksi DB TANPA pooler - bandingkan direct host vs pooler.

Tujuan: membedakan "password ditolak" dari "pooler masih cache password
lama". Kalau `db.<ref>.supabase.co` (direct) menerima password yang sama
yang ditolak pooler, itu bukti cache. Kalau Keduanya menerima, berarti
password itu memang masih yang aktif di server.

Nilai password tidak pernah dicetak.
"""
import hashlib
import pathlib
import re

import psycopg2
import psycopg2.extras

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / ".env.bak-20260917-014828"


def try_connect(dsn: str) -> str:
    try:
        c = psycopg2.connect(dsn, connect_timeout=20)
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("select current_user as u, current_database() as d")
        r = cur.fetchone()
        c.close()
        return f"PASS   user={r['u']} db={r['d']}"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL   {type(exc).__name__}: {str(exc).strip().splitlines()[0][:80]}"


def main() -> int:
    text = SRC.read_text(encoding="utf-8", errors="replace")
    ref = re.search(r"SUPABASE_URL=https://([a-z0-9]+)\.supabase\.co", text).group(1)
    pw = re.search(r"^SUPABASE_DB_PASSWORD\s*=\s*(\S+)", text, re.M).group(1)
    fp = hashlib.sha256(pw.encode()).hexdigest()[:10]

    print(f"project ref = {ref}")
    print(f"password    = len={len(pw)} fp={fp}  (nilai tidak dicetak)")
    print()
    print("DIRECT host db.<ref>.supabase.co:5432  (bypass pooler)")
    print("  " + try_connect(
        f"host=db.{ref}.supabase.co port=5432 dbname=postgres "
        f"user=postgres password={pw} sslmode=require"
    ))
    print()
    print("POOLER host aws-0-ap-southeast-1.pooler.supabase.com:5432")
    print("  " + try_connect(
        f"host=aws-0-ap-southeast-1.pooler.supabase.com port=5432 dbname=postgres "
        f"user=postgres.{ref} password={pw} sslmode=require"
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
