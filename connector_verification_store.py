#!/usr/bin/env python3
"""connector_verification_store.py — persist 8-layer verification ke Supabase.

Memakai koneksi Postgres langsung (psycopg2) lewat pooler Supabase, karena
DDL (CREATE TABLE) tidak bisa dilakukan lewat PostgREST. Kredensial diambil
dari `.env` (SUPABASE_URL + SUPABASE_DB_PASSWORD) — tidak ada yang di-hardcode.

Tabel `connector_verification` menyimpan satu baris per konektor dengan kolom
jsonb untuk tiap layer, plus classification & next_reverify_at (untuk re-check).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent
POOLER = "aws-0-ap-southeast-1.pooler.supabase.com"

DDL = """
CREATE TABLE IF NOT EXISTS connector_verification (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id text UNIQUE NOT NULL,
  url text NOT NULL,
  source text NOT NULL,
  classification text NOT NULL,
  score integer,
  declared_auth text,
  layer1_reachable jsonb,
  layer2_handshake jsonb,
  layer3_tools jsonb,
  layer4_reality jsonb,
  layer5_contract jsonb,
  layer6_conformance jsonb,
  layer8_mock_check jsonb,
  audit_mcpjacking jsonb,
  audit_silent_drift jsonb,
  audit_unauth jsonb,
  tool_reality_check jsonb,
  tool_contract_check jsonb,
  tool_spec_test jsonb,
  tool_mcpdoctor jsonb,
  tool_mcp_probe jsonb,
  risk_flags jsonb,
  verified_at timestamptz DEFAULT now(),
  next_reverify_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_cv_classification ON connector_verification(classification);
CREATE INDEX IF NOT EXISTS idx_cv_next_reverify ON connector_verification(next_reverify_at);
"""

COLS = [
    "connector_id", "url", "source", "classification", "score", "declared_auth",
    "layer1_reachable", "layer2_handshake", "layer3_tools", "layer4_reality",
    "layer5_contract", "layer6_conformance", "layer8_mock_check",
    "audit_mcpjacking", "audit_silent_drift", "audit_unauth",
    "tool_reality_check", "tool_contract_check", "tool_spec_test",
    "tool_mcpdoctor", "tool_mcp_probe", "risk_flags",
]
JSON_COLS = {c for c in COLS if c.startswith(("layer", "audit_", "tool_", "risk_"))}


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith("SUPABASE")})
    return env


def connect():
    env = load_env()
    url = env.get("SUPABASE_URL", "")
    ref = re.sub(r"^https?://([^.]+)\..*$", r"\1", url)
    pw = env.get("SUPABASE_DB_PASSWORD")
    if not (ref and pw):
        raise RuntimeError("SUPABASE_URL / SUPABASE_DB_PASSWORD tidak lengkap di .env")
    return psycopg2.connect(host=POOLER, port=6543, user=f"postgres.{ref}",
                            password=pw, dbname="postgres", sslmode="require",
                            connect_timeout=15)


def ensure_table() -> None:
    with connect() as c, c.cursor() as cur:
        cur.execute(DDL)


def _reverify_at(classification: str) -> str:
    """Jadwal re-check: yang REAL lebih jarang, yang DEAD lebih sering diuji ulang."""
    days = {
        "REAL_GRADE_A": 30, "REAL_GRADE_B": 21, "REAL_GRADE_C": 14,
        "NON_CONFORMANT": 14, "UNAUTH_EXPOSED": 7, "DRIFT": 7,
        "JACKABLE": 3, "AUTH_REQUIRED": 30, "NOT_MCP": 60, "DEAD": 3, "FAKE": 7,
    }.get(classification, 30)
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def upsert(results: list[dict], batch: int = 200) -> int:
    ensure_table()
    rows = []
    for r in results:
        vals = []
        for c in COLS:
            v = r.get(c)
            if c in JSON_COLS:
                v = json.dumps(v, ensure_ascii=False) if v is not None else None
            vals.append(v)
        vals.append(_reverify_at(r.get("classification", "")))
        rows.append(tuple(vals))

    sql = (
        f"INSERT INTO connector_verification ({','.join(COLS)}, next_reverify_at) "
        f"VALUES %s ON CONFLICT (connector_id) DO UPDATE SET "
        + ",".join(f"{c}=EXCLUDED.{c}" for c in COLS)
        + ", next_reverify_at=EXCLUDED.next_reverify_at, verified_at=now()"
    )
    n = 0
    with connect() as c:
        with c.cursor() as cur:
            for i in range(0, len(rows), batch):
                chunk = rows[i:i + batch]
                psycopg2.extras.execute_values(cur, sql, chunk, page_size=batch)
                n += len(chunk)
        c.commit()
    return n


def stats() -> dict:
    ensure_table()
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM connector_verification")
        total = cur.fetchone()[0]
        cur.execute("SELECT classification, count(*) FROM connector_verification "
                    "GROUP BY classification ORDER BY count(*) DESC")
        by = cur.fetchall()
    return {"total_rows": total, "by_classification": {k: v for k, v in by}}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "ddl":
        ensure_table()
        print("table ensured")
        print(json.dumps(stats(), indent=1))
    elif len(sys.argv) > 2 and sys.argv[1] == "load":
        data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        rows = data.get("results", data)
        print("upserted", upsert(rows))
        print(json.dumps(stats(), indent=1))
    else:
        print(json.dumps(stats(), indent=1))
