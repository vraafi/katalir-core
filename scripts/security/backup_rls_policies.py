"""Backup SKEMA + definisi policy untuk 3 tabel R-1 sebelum DROP POLICY.

`pg_dump` tidak tersedia di environment ini, jadi definisi diambil langsung
dari katalog (`pg_get_*def`) dan ditulis ulang sebagai SQL yang bisa dijalankan
apa adanya. TIDAK ada data tabel yang ikut — hanya definisi objek.
"""
import datetime
import pathlib
import re

import psycopg2
import psycopg2.extras

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLES = ["execution_logs", "executions", "workflows"]


def env_value(key: str) -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{key}\s*=\s*(\S+)", text, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def main() -> int:
    ref = env_value("SUPABASE_URL").split("//")[-1].split(".")[0]
    password = env_value("SUPABASE_DB_PASSWORD")
    dsn = (
        f"host=aws-0-ap-southeast-1.pooler.supabase.com port=5432 dbname=postgres "
        f"user=postgres.{ref} password={password} sslmode=require"
    )
    conn = psycopg2.connect(dsn, connect_timeout=20)
    conn.autocommit = True
    out: list[str] = []
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    out.append(f"-- Backup SKEMA 3 tabel R-1 (tanpa data)")
    out.append(f"-- dibuat: {stamp}")
    out.append(f"-- tujuan: rollback DROP POLICY di docs/security/audit-report.md §B.6")
    out.append(f"-- cara restore: psql -f <file ini>  (aman diulang: CREATE OR REPLACE / DROP IF EXISTS)")
    out.append("")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for t in TABLES:
            cur.execute(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relname=%s
                """,
                (t,),
            )
            row = cur.fetchone()
            if not row:
                out.append(f"-- TABEL {t}: TIDAK DITEMUKAN (lewati)")
                continue
            out.append(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;")
            out.append(
                f"-- RLS={row['relrowsecurity']} FORCE={row['relforcerowsecurity']}"
            )
            out.append("")

            cur.execute(
                """
                SELECT policyname, permissive, roles, cmd, qual, with_check
                FROM pg_policies WHERE schemaname='public' AND tablename=%s
                ORDER BY policyname
                """,
                (t,),
            )
            for p in cur.fetchall():
                roles = p["roles"] if isinstance(p["roles"], list) else [p["roles"]]
                roles = [r for r in roles if r]
                role_sql = ", ".join(f'"{r}"' for r in roles) if roles else "public"
                qual = p["qual"] or "true"
                wc = p["with_check"] or qual
                cmds = ["ALL"] if p["cmd"] == "ALL" else [p["cmd"]]
                for c in cmds:
                    out.append(f"DROP POLICY IF EXISTS \"{p['policyname']}\" ON public.{t};")
                out.append(
                    f"CREATE POLICY \"{p['policyname']}\" ON public.{t}\n"
                    f"    FOR {'ALL' if p['cmd'] == 'ALL' else p['cmd']} TO {role_sql}\n"
                    f"    USING ({qual})\n"
                    f"    WITH CHECK ({wc});"
                )
                out.append("")
    conn.close()

    path = ROOT / "docs" / "security" / f"rls-backup-{stamp}.sql"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"backup ditulis: {path.relative_to(ROOT)}")
    print(f"baris SQL: {len(out)}")
    print("--- isi ---")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
