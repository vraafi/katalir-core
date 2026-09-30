"""Audit RLS Supabase (Fase B).

Membaca katalog `pg_tables` + `pg_policies` lewat Supabase pooler, lalu
mencoba MENEMBAK data sebagai role `anon` pada setiap tabel.

Nilai credential TIDAK pernah dicetak - kredensial dibaca dari .env dan
langsung dipakai, hanya nama host/ref yang ditampilkan.
"""
import json
import os
import pathlib
import re
import sys

import psycopg2
import psycopg2.extras

ROOT = pathlib.Path(__file__).resolve().parents[2]


def env_value(key: str) -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{key}\s*=\s*(\S+)", text, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def main() -> int:
    ref = env_value("SUPABASE_URL").split("//")[-1].split(".")[0]
    password = env_value("SUPABASE_DB_PASSWORD")
    if not ref or not password:
        print("KONTRADIKSI: SUPABASE_URL / SUPABASE_DB_PASSWORD kosong di .env")
        return 2

    region = os.environ.get("SUPABASE_POOLER_REGION", "aws-0-ap-southeast-1")
    host = f"{region}.pooler.supabase.com"
    user = f"postgres.{ref}"
    dsn = f"host={host} port=5432 dbname=postgres user={user} password={password} sslmode=require"

    print(f"# pooler : {host}")
    print(f"# user   : {user}")
    print(f"# db     : postgres\n")

    conn = psycopg2.connect(dsn, connect_timeout=20)
    conn.autocommit = True
    out: dict = {}

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT tablename, rowsecurity FROM pg_tables "
            "WHERE schemaname='public' ORDER BY tablename"
        )
        tables = cur.fetchall()
        out["tables_total"] = len(tables)
        print(f"=== pg_tables (schemaname='public'): {len(tables)} ===")
        print(f"{'tablename':<38} {'rowsecurity'}")
        for t in tables:
            print(f"{t['tablename']:<38} {t['rowsecurity']}")

        cur.execute(
            "SELECT tablename, policyname, cmd, roles::text AS roles, qual, with_check "
            "FROM pg_policies WHERE schemaname='public' ORDER BY tablename, policyname"
        )
        policies = cur.fetchall()
        out["policies_total"] = len(policies)
        print(f"\n=== pg_policies (schemaname='public'): {len(policies)} ===")
        for p in policies:
            print(f"{p['tablename']:<38} {p['policyname']:<34} cmd={str(p['cmd']):<7} roles={p['roles']}")

        by_table: dict[str, list] = {}
        for p in policies:
            by_table.setdefault(p["tablename"], []).append(p)
        out["policies"] = [
            {k: (str(v) if v is not None else None) for k, v in p.items()} for p in policies
        ]

        # Uji bypass: role anon, SET ROLE, lalu SELECT pada setiap tabel.
        print("\n=== UJI BYPASS: SET ROLE anon -> SELECT * pada setiap tabel ===")
        print(f"{'tablename':<38} {'rls':<6} {'policies':<9} {'rows_visible_as_anon'}")
        probe = []
        for t in tables:
            name = t["tablename"]
            npol = len(by_table.get(name, []))
            try:
                cur.execute("SET ROLE anon")
                cur.execute(f'SELECT count(*) AS n FROM public."{name}"')
                n = cur.fetchone()["n"]
                visible: object = n
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).strip().splitlines()[0]
                visible = f"ERR:{msg[:60]}"
            finally:
                cur.execute("RESET ROLE")
            print(f"{name:<38} {str(t['rowsecurity']):<6} {npol:<9} {visible}")
            probe.append({
                "table": name,
                "rowsecurity": t["rowsecurity"],
                "policies": npol,
                "anon_select": str(visible),
            })

        out["probe"] = probe
        out["rls_off"] = [p["table"] for p in probe if p["rowsecurity"] is False]
        # KOREKSI BUG (lihat catatan): leak BUKAN hanya "RLS mati".
        # Tabel dengan RLS ON pun bocor kalau policynya `TO public` tanpa
        # filter - persis yang terjadi di execution_logs / executions /
        # workflows. Versi pertama skrip ini hanya mengecek `rowsecurity is
        # False` sehingga melaporkan "ANON_DATA_LEAK = none" padahal 85 baris
        # terlihat. Jangan percaya metrik yang hanya memeriksa satu penyebab.
        def _leaks(p):
            v = p["anon_select"]
            if v.startswith("ERR:") or v == "0":
                return False
            return True

        out["anon_leak"] = [p["table"] for p in probe if _leaks(p)]
        out["anon_leak_rows"] = {
            p["table"]: p["anon_select"] for p in probe if _leaks(p)
        }
        out["rls_on_no_policy"] = [
            p["table"] for p in probe
            if p["rowsecurity"] is True and p["policies"] == 0
        ]
        # Policy yang melekati role `public` (termasuk anon) dengan cmd ALL
        # dan tanpa USING restrictive = akses penuh untuk siapa pun.
        out["permissive_policies"] = [
            {"table": p["tablename"], "policy": p["policyname"], "cmd": p["cmd"],
             "roles": p["roles"], "qual": p["qual"], "with_check": p["with_check"]}
            for p in policies
            if "public" in (p["roles"] or "") and p["cmd"] == "ALL"
        ]
        conn.close()

    path = ROOT / "docs" / "security" / "rls-audit.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== RINGKASAN ===")
    print(f"TABLES_TOTAL       = {out['tables_total']}")
    print(f"POLICIES_TOTAL     = {out['policies_total']}")
    print(f"RLS_OFF            = {out['rls_off'] or 'none'}")
    print(f"ANON_DATA_LEAK     = {out['anon_leak'] or 'none'}")
    print(f"ANON_LEAK_ROWS     = {out['anon_leak_rows'] or 'none'}")
    print(f"RLS_ON_NO_POLICY   = {out['rls_on_no_policy'] or 'none'}")
    print(f"PERMISSIVE_POLICIES ({len(out['permissive_policies'])}) =")
    for p in out["permissive_policies"]:
        print(f"   {p['table']:<26} {p['policy']:<36} cmd={p['cmd']} roles={p['roles']}")
    print(f"report             = docs/security/rls-audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
