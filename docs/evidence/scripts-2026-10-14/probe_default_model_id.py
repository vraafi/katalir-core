"""Probe: id model mana yang BENAR-BENAR dilayani tanpa fallback (produksi).

Pertanyaan yang dijawab (menentukan nilai NEXT_PUBLIC_DEFAULT_MODEL_ID):
  Brief meminta  : "google/gemini-3.5-flash-lite"   (ber-prefix)
  Kandidat lain  : "gemini-3.5-flash-lite"          (tanpa prefix, ada di
                     DEFAULT_MODEL_PREFERENCE backend + katalog internal FE)
  Default lama   : "google/gemma-4-31b-it"          (sudah keluar dari roster)

Kriteria "BENAR": HTTP 200, reply memuat 333, fallback=False, served == requested.
Hanya id dengan fallback=False yang layak jadi DEFAULT_MODEL_ID frontend —
kalau tidak, pengguna melihat spanduk "Model yang Anda pilih tidak tersedia"
di SETIAP pesan (persis BUG-05 / P5-15).

Keluaran: docs/evidence/default-model-id-2026-10-14/probe_default_model_id.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tests" / "user_test"))

from rus_core import api, drop_user, make_user  # noqa: E402

OUT = HERE / "docs" / "evidence" / "default-model-id-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

PROMPT = "Berapa hasil 111+222? Jawab hanya angkanya."

CASES = [
    ("1. brief: google/gemini-3.5-flash-lite (BER-prefix)", "google/gemini-3.5-flash-lite"),
    ("2. bare: gemini-3.5-flash-lite (TANPA prefix)", "gemini-3.5-flash-lite"),
    ("3. FE katalog internal: gemini-3.1-flash-lite", "gemini-3.1-flash-lite"),
    ("4. default lama: google/gemma-4-31b-it", "google/gemma-4-31b-it"),
    ("5. kontrol: tanpa model", None),
]

u = make_user("probe-defaultmodel")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
TOK = u["session"]["access_token"]
print(f"akun uji: {u['email']}\n")

results = []
for name, model in CASES:
    body = {"prompt": PROMPT}
    if model is not None:
        body["model"] = model
    t0 = time.time()
    st, txt = api("POST", "/chat", body, token=TOK, timeout=120)
    dt = round(time.time() - t0, 1)
    meta, reply, detail = {}, "", ""
    try:
        d = json.loads(txt)
        meta = d.get("meta") or {}
        reply = str(d.get("reply") or "")
        detail = str(d.get("detail") or "")
    except Exception:  # noqa: BLE001
        detail = txt[:200]

    fb = meta.get("fallback")
    served = meta.get("model")
    req = meta.get("requested_model")
    answered = "333" in reply
    # Layak jadi default frontend HANYA bila dilayani apa adanya, tanpa fallback.
    layak_default = bool(st == 200 and answered and fb is False)

    results.append({
        "case": name, "requested": model, "http": st, "seconds": dt,
        "fallback": fb, "fallback_reason": meta.get("fallback_reason"),
        "requested_model": req, "served_by": served,
        "quota_bucket": meta.get("quota_bucket"),
        "answered_333": answered, "layak_jadi_default": layak_default,
        "reply": reply[:120], "detail": detail[:200],
    })
    print(f"  [{'LAYAK ' if layak_default else 'TIDAK '}] {name:50} "
          f"HTTP {st} {dt}s fb={fb} reason={meta.get('fallback_reason')} "
          f"served={served} 333={answered}")

pantas = [r["requested"] for r in results if r["layak_jadi_default"]]
print(f"\nid yang layak jadi DEFAULT_MODEL_ID: {pantas}")

(OUT / "probe_default_model_id.json").write_text(json.dumps(
    {"user": u["email"], "results": results, "layak_default": pantas},
    ensure_ascii=False, indent=1), encoding="utf-8")

drop_user(u["id"])
print(f"akun dihapus. bukti -> {OUT / 'probe_default_model_id.json'}")
