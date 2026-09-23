# -*- coding: utf-8 -*-
"""Migrasi tabel `user_preferences` (FASE 5) -- aditif, bisa dibalik, ada dry-run.

KENAPA SKRIP TERPISAH, BUKAN "CREATE TABLE" DI database.py SAAT STARTUP:
database produksi dipakai bersama aplikasi lain, jadi skema TIDAK boleh berubah
diam-diam saat server menyala. Perubahan skema harus tindakan yang disengaja,
terlihat, dan bisa dibatalkan.

SIFAT PERUBAHAN (baca dulu sebelum --apply):
  * ADITIF: hanya `CREATE TABLE IF NOT EXISTS` + satu index. Tidak ada
    DROP/ALTER/UPDATE/DELETE terhadap tabel yang sudah ada.
  * IDEMPOTEN: dijalankan dua kali = tidak ada efek kedua kali.
  * REVERSIBLE: `--rollback` menjalankan `DROP TABLE IF EXISTS user_preferences`
    (hanya membuang tabel ini; users/chat_*/integrations TIDAK disentuh).

MODE:
  python migrate_user_preferences.py --dry-run   (DEFAULT: tidak mengubah apa pun)
  python migrate_user_preferences.py --apply
  python migrate_user_preferences.py --verify
  python migrate_user_preferences.py --rollback --yes-rollback
"""
import argparse
import json
import os
import re
import sys
import time
from urllib.parse import quote

import database as db

TABLE = "user_preferences"

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  user_email text PRIMARY KEY,
  prefs jsonb NOT NULL DEFAULT '{{}}'::jsonb,
  updated_at timestamptz DEFAULT now()
);
"""

INDEX_DDL = f"CREATE INDEX IF NOT EXISTS {TABLE}_updated_at_idx ON {TABLE} (updated_at DESC);"

ROLLBACK_SQL = f"DROP TABLE IF EXISTS {TABLE};"


def _rpc(sql: str):
    """Jalankan SQL lewat RPC exec_sql (service key). Gagal -> alasan terbaca."""
    try:
        client = db._get_write_client()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"tidak bisa membuat client tulis: {exc}"}
    try:
        res = client.rpc("exec_sql", {"sql": sql}).execute()
        return {"ok": True, "data": getattr(res, "data", None), "via": "rpc"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:400]}


def _dsn() -> str:
    """DSN Postgres untuk menjalankan DDL bila RPC exec_sql tidak ada.

    DUA bentuk host, dicoba berurutan oleh `_psql`:
      1. pooler  : postgresql://postgres.<ref>:<pw>@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
      2. legacy  : postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres

    Kenapa dua: host legacy `db.<ref>.supabase.co` SUDAH TIDAK DIRESOLUSI DNS
    untuk project ini (dibuktikan dengan probe: "could not translate host name").
    Host pooler ditemukan dengan mencoba kandidat region dan hanya menerima yang
    benar-benar lolos autentikasi (`_probe_supabase_pooler.py`) — bukan tebakan.
    Pooler memakai username `postgres.<project-ref>` (wajib menyertakan ref).
    """
    pw = (os.getenv("SUPABASE_DB_PASSWORD") or "").strip()
    ref = ""
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.co", db.SUPABASE_URL or "")
    if m:
        ref = m.group(1)
    if not (pw and ref):
        return ""
    return "postgresql://postgres.{r}:{p}@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres".format(
        r=ref, p=quote(pw, safe="")
    )


def _dsn_legacy() -> str:
    pw = (os.getenv("SUPABASE_DB_PASSWORD") or "").strip()
    ref = ""
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.co", db.SUPABASE_URL or "")
    if m:
        ref = m.group(1)
    if not (pw and ref):
        return ""
    return f"postgresql://postgres:{quote(pw, safe='')}@db.{ref}.supabase.co:5432/postgres"


def _psql(sql: str):
    """Jalankan SQL lewat psycopg2 (bila terpasang). Jujur bila tidak ada."""
    try:
        import psycopg2  # type: ignore
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "psycopg2 tidak terpasang (pip install psycopg2-binary)"}
    errors = []
    for dsn in (d for d in (_dsn(), _dsn_legacy()) if d):
        try:
            conn = psycopg2.connect(dsn, connect_timeout=15)
            try:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(sql)
                    rows = cur.fetchall() if cur.description else None
                return {"ok": True, "rows": rows, "via": "psql"}
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc).splitlines()[0][:160])
    return {"ok": False, "reason": " | ".join(errors)[:400]}


def _exec_sql(sql: str):
    """Coba RPC dulu (service key), lalu koneksi Postgres langsung."""
    res = _rpc(sql)
    if res.get("ok"):
        return res
    res2 = _psql(sql)
    if res2.get("ok"):
        return res2
    return {"ok": False, "reason": f"rpc: {res.get('reason')} | psql: {res2.get('reason')}"}


def _table_exists() -> tuple[bool, str]:
    """Cek keberadaan tabel lewat PostgREST (SELECT LIMIT 1)."""
    try:
        client = db._get_write_client()
    except Exception as exc:  # noqa: BLE001
        return False, f"client tulis gagal: {exc}"
    try:
        client.table(TABLE).select("user_email").limit(1).execute()
        return True, "tabel menjawab SELECT"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:300]


def cmd_dry_run() -> int:
    print("=== DRY RUN (TIDAK mengubah apa pun) ===")
    print(f"SUPABASE_URL  : {db.SUPABASE_URL or '(kosong)'}")
    print(f"write client  : {'SIAP' if db.SUPABASE_SERVICE_KEY else 'TIDAK ADA service key'}")
    exists, why = _table_exists()
    print(f"tabel saat ini: {'SUDAH ADA' if exists else 'BELUM ADA'} ({why})")
    print("\nRencana perubahan (hanya bila --apply dipakai):")
    print(DDL.strip())
    print(INDEX_DDL)
    print("\nRollback yang tersedia:")
    print(ROLLBACK_SQL)
    print("\nSifat: ADITIF + idempoten + reversible. Tidak ada DROP/ALTER tabel lain.")
    if not db.SUPABASE_SERVICE_KEY:
        print("\nCATATAN: tanpa service key, --apply akan gagal (RLS). Isi SUPABASE_SERVICE_KEY.")
        return 2
    return 0


def cmd_apply() -> int:
    print("=== APPLY (aditif: CREATE TABLE IF NOT EXISTS + index) ===")
    for sql in (DDL, INDEX_DDL):
        res = _exec_sql(sql)
        if res["ok"]:
            print("OK   : " + sql.strip().splitlines()[0] + f" (via {res.get('via')})")
        else:
            print(f"GAGAL: {res['reason']}")
            print("  -> jalankan SQL ini MANUAL di Supabase SQL Editor:")
            print("     " + sql.strip().replace("\n", "\n     "))
            return 3
    exists, why = _table_exists()
    print(f"verifikasi SELECT: {'tabel hidup' if exists else 'MASIH GAGAL'} ({why})")
    return 0 if exists else 4


def cmd_verify() -> int:
    print("=== VERIFY ===")
    # PostgREST menyimpan cache skema: tabel yang baru dibuat lewat koneksi
    # Postgres belum tentu langsung terlihat lewat REST (gejala nyata:
    # PGRST205 'Could not find the table ... in the schema cache'). Perintah
    # NOTIFY di bawah ini adalah cara resmi PostgREST memuat ulang cache.
    reload = _exec_sql("NOTIFY pgrst, 'reload schema'")
    print(f"reload skema PostgREST: {'OK' if reload['ok'] else 'GAGAL: ' + str(reload.get('reason'))[:120]}")
    print("kolom via psql: " + str(_psql(
        "select column_name, data_type from information_schema.columns "
        "where table_schema='public' and table_name='user_preferences' order by ordinal_position"
    ).get("rows")))
    exists, why = False, ""
    for attempt in range(1, 4):
        exists, why = _table_exists()
        print(f"percobaan {attempt}: tabel {'ADA' if exists else 'belum terlihat'}")
        if exists:
            break
        time.sleep(3)
    if not exists:
        return 4
    print("--- round-trip tulis/baca lewat kode aplikasi (database.save/get_user_preferences) ---")
    email = "migration-probe@katalir.local"
    saved = db.save_user_preferences(email, {"canvasTheme": "midnight", "probe": True})
    loaded = db.get_user_preferences(email)
    print(f"round-trip backend={saved.get('backend')} nilai={json.dumps(loaded)}")
    ok = loaded.get("canvasTheme") == "midnight"
    if ok:
        try:
            db._get_write_client().table(TABLE).delete().eq("user_email", email).execute()
            print("probe dibersihkan")
        except Exception as exc:  # noqa: BLE001
            print(f"peringatan: gagal membersihkan probe: {exc}")
    return 0 if ok else 5


def cmd_rollback(yes: bool) -> int:
    if not yes:
        print("Rollback butuh flag --yes-rollback (destruktif untuk SATU tabel ini saja).")
        return 6
    print("=== ROLLBACK ===")
    res = _exec_sql(ROLLBACK_SQL)
    print(("OK   : " if res["ok"] else "GAGAL: ") + ROLLBACK_SQL)
    if not res["ok"]:
        print("  -> jalankan manual: " + ROLLBACK_SQL)
        return 3
    exists, why = _table_exists()
    print(f"setelah rollback: {'MASIH ADA' if exists else 'sudah tidak ada'} ({why})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrasi user_preferences (aditif, reversible).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="tampilkan rencana; tidak mengubah apa pun (default)")
    g.add_argument("--apply", action="store_true", help="buat tabel + index (aditif, idempoten)")
    g.add_argument("--verify", action="store_true", help="cek tabel + round-trip tulis/baca")
    g.add_argument("--rollback", action="store_true", help="DROP TABLE user_preferences")
    ap.add_argument("--yes-rollback", action="store_true", help="konfirmasi untuk --rollback")
    args = ap.parse_args()

    if args.apply:
        return cmd_apply()
    if args.verify:
        return cmd_verify()
    if args.rollback:
        return cmd_rollback(args.yes_rollback)
    return cmd_dry_run()


if __name__ == "__main__":
    sys.exit(main())
