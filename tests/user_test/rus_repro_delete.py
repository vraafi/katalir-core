"""Reproduksi terarah: DELETE /workflows/{id} dengan id non-UUID.

Temuan (14 Okt 2026): `remove_workflow` adalah SATU-SATUNYA handler
ber-`{workflow_id}` yang tidak memanggil `_require_uuid_or_404()`. Akibatnya
PostgREST menolak id non-UUID dengan 22P02, handler membalas 500 — padahal
input klien seharusnya 4xx. GET / PATCH / ops sudah dijaga (BUG-04).

Skenario:
  utama   : DELETE/PATCH/GET id non-UUID  -> harus 404 (bukan 500)
  kontrol : POST workflow valid           -> 201
            DELETE workflow valid         -> 200
            DELETE id yang sama lagi      -> 404 (idempotent)

Pakai:
  python tests/user_test/rus_repro_delete.py before|after

Keluaran: docs/evidence/fix-delete-2026-10-14/probe_<label>.json
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rus_core import api, drop_user, make_user  # noqa: E402

LABEL = sys.argv[1] if len(sys.argv) > 1 else "before"
OUT = HERE.parent.parent / "docs" / "evidence" / "fix-delete-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

u = make_user("repro-del")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
TOK = u["session"]["access_token"]
print(f"akun uji: {u['email']}")

results = []


def rec(name, method, path, body, expect):
    st, txt = api(method, path, body, token=TOK, timeout=45)
    leaks = any(k in txt for k in ("invalid input syntax", "22P02",
                                   "Traceback", "psycopg", "postgres"))
    ok = st == expect
    results.append({"case": name, "method": method, "path": path,
                    "http": st, "expected": expect, "ok": ok,
                    "leaks_internal_error": leaks, "body": txt[:300]})
    print(f"  [{'OK ' if ok else 'BAD'}] {name:34} {method:6} {path:32} "
          f"HTTP {st} (harap {expect}) leak={leaks}")
    return st, txt


print("--- kasus utama (id non-UUID) ---")
rec("DELETE id non-UUID", "DELETE", "/workflows/not-a-uuid", None, 404)
rec("PATCH id non-UUID", "PATCH", "/workflows/not-a-uuid", {"name": "x"}, 404)
rec("GET id non-UUID", "GET", "/workflows/not-a-uuid", None, 404)
rec("DELETE id numerik '1'", "DELETE", "/workflows/1", None, 404)

print("--- kontrol positif (tidak boleh ikut rusak) ---")
st, txt = rec("POST workflow baru (valid)", "POST", "/workflows",
              {"name": "repro-del", "flow_data": {"nodes": [], "edges": []}}, 201)
wf_id = None
try:
    payload = json.loads(txt)
    wf_id = (payload.get("workflow") or {}).get("id") or payload.get("id")
except Exception:  # noqa: BLE001
    pass
print(f"  workflow id = {wf_id}")
if wf_id:
    rec("DELETE workflow valid (milik)", "DELETE", f"/workflows/{wf_id}", None, 200)
    rec("DELETE workflow sama lagi", "DELETE", f"/workflows/{wf_id}", None, 404)

count_5xx = sum(1 for r in results if r["http"] >= 500)
leaks = sum(1 for r in results if r["leaks_internal_error"])
print(f"\n5xx={count_5xx}  leaks={leaks}")

(OUT / f"probe_{LABEL}.json").write_text(json.dumps(
    {"label": LABEL, "user": u["email"], "results": results,
     "count_5xx": count_5xx, "count_leaks": leaks},
    ensure_ascii=False, indent=1), encoding="utf-8")

drop_user(u["id"])
print(f"akun dihapus. bukti -> {OUT / f'probe_{LABEL}.json'}")
