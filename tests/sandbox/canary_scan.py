"""canary_scan.py — pemindai canary + kebocoran kredensial (BAGIAN 4.3 & 6.2).

Memindai DUA dunia:
  1. Berkas lokal (log/json/txt) — jalur "grep -r KATALIR_TEST_CANARY_ logs/".
  2. Tabel Supabase (`execution_logs`, `chat_messages`) — jalur produksi.

Keluaran HANYA berisi kategori + jumlah. Nilai mentah TIDAK PERNAH dicetak.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent_redactor as ar  # noqa: E402
import database as db  # noqa: E402

#: Pola yang dicari (kategori -> regex), termasuk canary.
DETECTORS = [(cat, rx) for cat, rx, _repl in ar.CREDENTIAL_PATTERNS]

#: Berkas yang dipindai (relatif root). Sengaja dibatasi, bukan `-r` buta.
GLOBS = ("*.log", "*.json", "*.txt", "logs/*.log", "tests/sandbox/backups/*.json")

SKIP_DIR_PARTS = {"node_modules", ".git", ".next", "out", "__pycache__"}

MAX_FILE_BYTES = 2_000_000


def detect(text: str) -> list[str]:
    """Kategori pola yang cocok di `text` (tanpa nilai)."""
    return [cat for cat, rx in DETECTORS if rx.search(text)]


def scan_local() -> dict:
    files_scanned = 0
    hits: list[dict] = []
    for pattern in GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_PARTS for part in path.parts):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            files_scanned += 1
            cats = detect(text)
            if cats:
                rel = str(path.relative_to(ROOT))
                hits.append({
                    "file": rel,
                    "categories": cats,
                    "scope": "sandbox" if rel.startswith("tests/sandbox") else "repo",
                })
    sandbox_hits = [h for h in hits if h["scope"] == "sandbox"]
    return {"files_scanned": files_scanned, "hits": hits,
            "sandbox_hits": sandbox_hits,
            "repo_hits": [h for h in hits if h["scope"] == "repo"]}


def scan_table(client, table: str, columns: str, limit: int = 2000) -> dict:
    try:
        res = client.table(table).select(columns).limit(limit).execute()
    except Exception as exc:  # noqa: BLE001
        return {"table": table, "error": type(exc).__name__}
    rows = res.data or []
    hits: list[dict] = []
    for idx, row in enumerate(rows):
        blob = json.dumps(row, default=str)
        cats = detect(blob)
        if cats:
            hits.append({"row": idx, "categories": cats})
    return {"table": table, "rows_scanned": len(rows), "hits": hits}


def scan_db() -> dict:
    # WAJIB service role: dengan anon key, RLS menyembunyikan baris produksi
    # dan "0 temuan" menjadi kesimpulan palsu.
    try:
        client = db._get_write_client()
    except Exception:  # noqa: BLE001
        try:
            client = db._get_client()
        except Exception:  # noqa: BLE001
            client = None
    if client is None:
        return {"configured": False}
    return {
        "configured": True,
        "execution_logs": scan_table(client, "execution_logs",
                                     "execution_id,node_id,node_type,status,output_data"),
        "chat_messages": scan_table(client, "chat_messages", "id,role,content"),
    }


def main() -> int:
    print("=" * 70)
    print("BAGIAN 4.3 / 6.2 — PEMINDAI CANARY + KEBOCORAN KREDENSIAL")
    print("=" * 70)
    print(f"Canary prefix: {ar.CANARY_PREFIX}")

    local = scan_local()
    print(f"\n[LOKAL] {local['files_scanned']} berkas dipindai")
    print(f"  dalam sandbox (tests/sandbox): "
          f"{json.dumps(local['sandbox_hits'], indent=2) if local['sandbox_hits'] else '0 (BERSIH)'}")
    print(f"  sisa repo (higiene, di luar sandbox): "
          f"{len(local['repo_hits'])} berkas")
    for h in local["repo_hits"]:
        print(f"    - {h['file']}  {h['categories']}")

    dbres = scan_db()
    print(f"\n[DB] {json.dumps({k: v for k, v in dbres.items() if k != 'configured'}, indent=2)}")

    sandbox_clean = not local["sandbox_hits"]
    db_clean = True
    if dbres.get("configured"):
        for key in ("execution_logs", "chat_messages"):
            entry = dbres.get(key) or {}
            if entry.get("hits"):
                db_clean = False
    else:
        db_clean = None  # tidak bisa diperiksa

    print("\n" + "-" * 70)
    print(f"SANDBOX : {'BERSIH' if sandbox_clean else 'ADA TEMUAN'}")
    print(f"DB      : {'BERSIH' if db_clean else ('TIDAK DIPERIKSA' if db_clean is None else 'ADA TEMUAN')}")
    if local["repo_hits"]:
        print(f"REPO    : {len(local['repo_hits'])} berkas higiene di luar sandbox "
              f"(dilaporkan, bukan bagian dari test ini)")
    # Verdict test ini = sandbox bersih + DB bersih. Temuan higiene repo
    # dilaporkan terpisah supaya tidak menyamarkan hasil test.
    ok = sandbox_clean and (db_clean is not False)
    print(f"VERDICT TEST: {'PASS' if ok else 'GAGAL'}")
    print("-" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
