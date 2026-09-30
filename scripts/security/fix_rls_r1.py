"""DROP 3 policy R-1 (CRITICAL) + verifikasi before/after. WAJIB approval user.

Hanya menyentuh 3 policy yang teridentifikasi di audit-report.md §B.6:
  execution_logs / "Izinkan semua akses ke execution_logs"
  executions     / "Izinkan semua akses ke executions"
  workflows      / "Allow public read and write"

Policy LAIN (workflows_owner_all, user_own_prefs, dll) TIDAK disentuh.
"""
import json
import pathlib
import re

import psycopg2
import psycopg2.extras

ROOT = pathlib.Path(__file__).resolve().parents[2]

TARGETS = [
    ("execution_logs", "Izinkan semua akses ke execution_logs"),
    ("executions", "Izinkan semua akses ke executions"),
    ("workflows", "Allow public read and write"),
]

# Dijalankan SEBELUM dan SESUDAH drop, sebagai PoC.
PROBE_TABLES = ["execution_logs", "executions", "workflows"]


def env_value(key: str) -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{key}\s*=\s*(\S+)", text, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def main() -> int:
    ref = env_value("SUPABASE_URL").split("//")[-1].split(".")[0]
    password = env_value("SUPABASE_DB_PASSWORD")
    conn = psycopg2.connect(
        f"host=aws-0-ap-southeast-1.pooler.supabase.com port=5432 dbname=postgres "
        f"user=postgres.{ref} password={password} sslmode=require",
        connect_timeout=20,
    )
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def probe(label: str) -> dict:
        rows = {}
        for t in PROBE_TABLES:
            cur.execute("SET ROLE anon")
            try:
                cur.execute(f"SELECT count(*) AS n FROM public.{t}")
                rows[t] = cur.fetchone()["n"]
            except Exception as exc:  # noqa: BLE001
                rows[t] = f"DENIED: {str(exc).strip().splitlines()[0][:50]}"
            finally:
                cur.execute("RESET ROLE")
        print(f"--- anon SELECT count(*) {label} ---")
        for t, v in rows.items():
            print(f"  {t:18s} -> {v}")
        return rows

    before = probe("(BEFORE drop)")

    print("\n--- DROP POLICY ---")
    for table, policy in TARGETS:
        # Kunci: hanya drop kalau policy itu persis yang teridentifikasi.
        cur.execute(
            "SELECT policyname FROM pg_policies "
            "WHERE schemaname='public' AND tablename=%s AND policyname=%s",
            (table, policy),
        )
        if not cur.fetchone():
            print(f"  SKIP (tidak ada): {table}.{policy}")
            continue
        cur.execute(f'DROP POLICY "{policy}" ON public."{table}"')
        print(f"  DROPPED: {table}.{policy}")

    print("\n--- rowsecurity masih aktif? ---")
    cur.execute(
        "SELECT tablename, rowsecurity FROM pg_tables "
        "WHERE schemaname='public' AND tablename = ANY(%s) ORDER BY tablename",
        (PROBE_TABLES,),
    )
    rls = {r["tablename"]: r["rowsecurity"] for r in cur.fetchall()}
    for t, v in rls.items():
        print(f"  {t:18s} rowsecurity={v}")

    after = probe("(AFTER drop)")

    print("\n--- policy tersisa per tabel ---")
    cur.execute(
        "SELECT tablename, policyname, qual FROM pg_policies "
        "WHERE schemaname='public' AND tablename = ANY(%s) ORDER BY tablename, policyname",
        (PROBE_TABLES,),
    )
    remaining = [dict(r) for r in cur.fetchall()]
    for r in remaining:
        print(f"  {r['tablename']:18s} {r['policyname']:38s} qual={r['qual']}")

    conn.close()
    path = ROOT / "docs" / "security" / "rls-r1-before-after.json"
    path.write_text(
        json.dumps({"before": before, "after": after, "rowsecurity": rls,
                    "remaining_policies": remaining}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nreport: docs/security/rls-r1-before-after.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
