"""Reproduksi terarah: 500 + bocoran error basis data pada ID non-UUID.

Temuan: GET /workflows/<bukan-uuid> -> HTTP 500 dengan pesan driver Postgres
mentah (`invalid input syntax for type uuid`, kode 22P02). Kelas yang sama
diuji pada PATCH/DELETE dan pada endpoint lain ber-{id} sebagai KONTROL, supaya
jelas apakah ini cacat terisolasi atau pola.

Keluaran: tests/user_test/_rus_repro_500.json
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rus_core import TOKEN, api  # noqa: E402

CASES = [
    ("GET", "/workflows/not-a-uuid", None),
    ("PATCH", "/workflows/not-a-uuid", {"name": "x"}),
    ("DELETE", "/workflows/not-a-uuid", None),
    ("GET", "/workflows/1", None),
    ("GET", "/workflows/%20", None),
    ("GET", "/templates/not-a-uuid", None),          # KONTROL (sudah benar)
    ("GET", "/evidence/not-a-uuid/verify", None),    # KONTROL (sudah benar)
]

results = []
print(f"{'METHOD':7} {'HTTP':5} {'PATH':40} body")
for m, p, body in CASES:
    st, txt = api(m, p, body, token=TOKEN, timeout=45)
    leaks = any(k in txt for k in ("invalid input syntax", "22P02",
                                   "Traceback", "psycopg", "postgres"))
    results.append({"method": m, "path": p, "http": st,
                    "leaks_internal_error": leaks, "body": txt[:400]})
    print(f"{m:7} {st:<5} {p:40} {txt[:100]!r}")

bad = [r for r in results if r["http"] >= 500]
leak = [r for r in results if r["leaks_internal_error"]]
print(f"\n5xx: {len(bad)} -> {[r['path'] for r in bad]}")
print(f"bocoran error internal: {len(leak)} -> {[r['path'] for r in leak]}")

(HERE / "_rus_repro_500.json").write_text(json.dumps(
    {"results": results, "count_5xx": len(bad),
     "count_leaks": len(leak)}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {HERE / '_rus_repro_500.json'}")
