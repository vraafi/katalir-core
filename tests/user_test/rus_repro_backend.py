"""Reproduksi terarah cacat BACKEND (ditemukan di REAL USER HARD TEST 13 Okt).

Tiga kelas diuji, semuanya lewat HTTP langsung (tanpa browser) supaya bukti
minimal dan bisa diulang:

  A. ID non-UUID pada endpoint ber-{id}
     Dugaan: handler tidak menjaga tipe, nilai mentah diteruskan ke Postgres,
     Postgres menolak (22P02), dan `except Exception -> HTTPException(500,
     f"...{exc}")` membocorkan pesan driver + kode SQLSTATE ke klien.
     KONTROL: endpoint yang sudah benar (404) disertakan sebagai pembanding.

  B. Batas panjang prompt (/chat)
     CHAT_MAX_CHARS = 8000 (api_server.py:706). 8000 harus diterima,
     8001 harus 422 dengan pesan yang menyebut angka batas.

  C. Null byte (\x00) di prompt
     Postgres menolak \x00 pada kolom text (22P05). Harus ditolak rapi
     (4xx berpesan jelas), bukan 5xx dengan pesan internal.

Keluaran: tests/user_test/_rus_repro_backend.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import uuid

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rus_core import TOKEN, api  # noqa: E402

LEAK_KEYS = ("invalid input syntax", "22P02", "22P05", "Traceback",
             "psycopg", "postgres", "supabase error", "unicode escape",
             "cannot be converted to text")

# ── A. kelas ID non-UUID ───────────────────────────────────────────────────
ID_CASES = [
    ("GET", "/workflows/not-a-uuid", None, "target"),
    ("PATCH", "/workflows/not-a-uuid", {"name": "x"}, "target"),
    ("DELETE", "/workflows/not-a-uuid", None, "target"),
    ("GET", "/workflows/1", None, "target"),
    ("GET", "/workflows/%20", None, "target"),
    ("GET", "/workflows/not-a-uuid/schedule", None, "target"),
    ("GET", "/workflows/not-a-uuid/redaction", None, "target"),
    ("GET", "/agents/not-a-uuid", None, "target"),
    ("GET", "/executions/not-a-uuid", None, "target"),
    ("GET", "/messages/not-a-uuid", None, "target"),
    ("GET", "/hitl/not-a-uuid", None, "target"),
    ("GET", "/evaluations/runs/not-a-uuid", None, "target"),
    # KONTROL — endpoint yang sudah menangani ID buruk dengan benar
    ("GET", "/templates/not-a-uuid", None, "kontrol"),
    ("GET", "/evidence/not-a-uuid/verify", None, "kontrol"),
    # KONTROL — UUID valid tapi tidak ada / bukan milik user ini
    ("GET", f"/workflows/{uuid.uuid4()}", None, "kontrol"),
]

results: dict[str, list] = {"id_non_uuid": [], "batas_prompt": [],
                            "null_byte": []}

print("=" * 78)
print("A. ID non-UUID pada endpoint ber-{id}")
print("=" * 78)
print(f"{'JENIS':8} {'METHOD':7} {'HTTP':5} {'PATH':38} bocor? body")
for m, p, body, kind in ID_CASES:
    st, txt = api(m, p, body, token=TOKEN, timeout=45)
    low = txt.lower()
    leaks = any(k.lower() in low for k in LEAK_KEYS)
    results["id_non_uuid"].append({
        "kind": kind, "method": m, "path": p, "http": st,
        "leaks_internal_error": leaks, "body": txt[:500]})
    print(f"{kind:8} {m:7} {st:<5} {p:38} {'YA' if leaks else '-':4} "
          f"{txt[:80]!r}")

targets = [r for r in results["id_non_uuid"] if r["kind"] == "target"]
ctrl = [r for r in results["id_non_uuid"] if r["kind"] == "kontrol"]
t5 = [r for r in targets if r["http"] >= 500]
tleak = [r for r in targets if r["leaks_internal_error"]]
c5 = [r for r in ctrl if r["http"] >= 500]
print(f"\n  target 5xx         : {len(t5)}/{len(targets)} "
      f"-> {[r['path'] for r in t5]}")
print(f"  target bocor error : {len(tleak)}/{len(targets)}")
print(f"  kontrol 5xx        : {len(c5)}/{len(ctrl)} (harus 0)")
results["summary_A"] = {
    "target_total": len(targets), "target_5xx": len(t5),
    "target_leaks": len(tleak), "kontrol_total": len(ctrl),
    "kontrol_5xx": len(c5),
    "target_5xx_paths": [f"{r['method']} {r['path']}" for r in t5],
}

# ── B. batas panjang prompt ────────────────────────────────────────────────
print("\n" + "=" * 78)
print("B. Batas panjang prompt /chat (CHAT_MAX_CHARS = 8000)")
print("=" * 78)
for n in (8000, 8001):
    st, txt = api("POST", "/chat", {"prompt": "k" * n}, token=TOKEN, timeout=120)
    menyebut = "terlalu panjang" in txt.lower() or "8000" in txt
    results["batas_prompt"].append({"n": n, "http": st,
                                    "menyebut_batas": menyebut,
                                    "body": txt[:400]})
    print(f"  {n:>5} karakter -> HTTP {st}; menyebut_batas={menyebut}; "
          f"{txt[:110]!r}")

# ── C. null byte ───────────────────────────────────────────────────────────
print("\n" + "=" * 78)
print("C. Null byte (\\x00) di prompt")
print("=" * 78)
st, txt = api("POST", "/chat", {"prompt": "tes\x00injection"}, token=TOKEN,
              timeout=120)
low = txt.lower()
leaks = any(k.lower() in low for k in LEAK_KEYS)
results["null_byte"].append({"http": st, "leaks_internal_error": leaks,
                             "body": txt[:600]})
print(f"  HTTP {st}; bocor_error_internal={leaks}")
print(f"  body: {txt[:260]!r}")

# ── ringkasan ──────────────────────────────────────────────────────────────
print("\n" + "=" * 78)
print("RINGKASAN")
print("=" * 78)
verdict = {
    "A_id_non_uuid_5xx": len(t5),
    "A_id_non_uuid_bocor": len(tleak),
    "A_kontrol_5xx": len(c5),
    "B_8000_ok": results["batas_prompt"][0]["http"] == 200,
    "B_8001_422_berpesan": (results["batas_prompt"][1]["http"] in (413, 422)
                            and results["batas_prompt"][1]["menyebut_batas"]),
    "C_null_byte_4xx": 400 <= results["null_byte"][0]["http"] < 500,
    "C_null_byte_bocor": results["null_byte"][0]["leaks_internal_error"],
}
for k, v in verdict.items():
    print(f"  {k:26} = {v}")

out = HERE / "_rus_repro_backend.json"
out.write_text(json.dumps({"results": results, "verdict": verdict},
                          ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nbukti -> {out}")
