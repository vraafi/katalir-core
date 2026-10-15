"""probe_key_entitlement_v3.py - Uji klaim entitlement per (kunci, model) DENGAN
REKORD LENGKAP (perbaikan cacat probe v2: error kunci pertama TERTIMPA oleh
sukses kunci kedua — `probe_gemini_free_models_v2.py` baris 108-111).

Pertanyaan yang harus dijawab (dari audit EVL-2-revisi, 15 Okt 19:04):
  "gemma-4-31b-it OK di KEY_2, gagal di KEY_1 — TAPI error KEY_1 tidak
   terekam, jadi TIDAK BISA dibedakan 404 entitlement dari 429/503 sementara."

Desain v3:
  1. Setiap model diuji ke SEMUA kunci dalam set kuncinya — TIDAK ada
     short-circuit; SEMUA hasil (sukses & gagal) terekam per kunci.
  2. gemma-4-31b-it diuji ke SEMUA 13 kunci (klaim entitlement yang
     dipersoalkan audit harus teruji lintas seluruh pool).
  3. Model lain (kontrol + gagal-v2) diuji ke 3 kunci pertama.
  4. Kunci tidak pernah dicetak — hanya NAMA#fingerprint8.

Output: docs/evidence/verifikasi-06345af/probe_entitlement_v3.json
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import gemini_key_pool as pool_mod  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "verifikasi-06345af" / "probe_entitlement_v3.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

PROMPT = "Balas tepat satu kata: OK"

# (model, jumlah_kunci): gemma = SELURUH pool; lainnya 3 kunci.
TARGETS: list[tuple[str, int]] = [
    ("gemma-4-31b-it", 13),          # KONTROVERSIAL - semua kunci
    ("gemma-4-26b-a4b-it", 3),       # gemma kedua, kontrol
    ("gemini-3.8-flash", 3),         # varians antar-kunci dikenal (503 di v2)
    ("gemini-3.5-flash-lite", 3),    # kontrol "harus OK di mana saja" (default)
    ("gemini-2.5-flash", 3),         # kontrol served v2
    ("gemini-2.5-pro", 3),           # gagal v2: 404 entitlement
    ("gemini-3.1-pro-preview", 3),   # gagal v2: 429
    ("gemini-4-argon", 3),           # gagal v2: 429
]


def main() -> int:
    pool_mod.load_env_file()
    entries = pool_mod.discover_keys()
    print(f"kunci unik: {len(entries)}")
    if not entries:
        print("TIDAK ADA KUNCI")
        return 1

    from google import genai

    def make_client(api_key: str):
        # timeout 20 s/hard-limit 25 s: tanpa ini satu kunci bisa MENGgantung
        # proses selamanya (terjadi pada run pertama, gemma KEY_5).
        return genai.Client(api_key=api_key, http_options={"timeout": 20000})

    def attempt(client, mid: str) -> dict:
        t0 = time.time()
        result: dict = {}

        def _call():
            try:
                r = client.models.generate_content(model=mid, contents=PROMPT)
                txt = (getattr(r, "text", "") or "").strip()[:40]
                result.update({"served": True, "detail": f"OK text={txt!r}"})
            except Exception as exc:  # noqa: BLE001
                kind, _ = pool_mod.classify_error(exc)
                result.update({"served": False,
                               "detail": f"[{kind}] {str(exc)[:300]}"})

        th = threading.Thread(target=_call, daemon=True)
        th.start()
        th.join(30.0)  # batas keras per panggilan
        if th.is_alive():
            result = {"served": False, "detail": "[timeout] >30 s tanpa jawaban"}
        result["latency_ms"] = int((time.time() - t0) * 1000)
        return result

    results: list[dict] = []
    for mid, nkeys in TARGETS:
        sel = entries[:nkeys]
        attempts = []
        for name, api_key, fp in sel:
            label = f"{name}#{fp[:8]}"
            a = attempt(make_client(api_key), mid)
            a["key"] = label
            attempts.append(a)
            print(f"  {mid:28s} {label:24s} "
                  f"{'OK   ' if a['served'] else 'GAGAL'} {a['latency_ms']:>6}ms")
            time.sleep(1.2)  # jaga RPM free tier
        n_ok = sum(1 for a in attempts if a["served"])
        results.append({
            "model": mid,
            "keys_tested": len(attempts),
            "keys_served": n_ok,
            "entitlement_split": n_ok not in (0, len(attempts)),
            "attempts": attempts,
        })
        print(f"=> {mid}: {n_ok}/{len(attempts)} served, "
              f"split={'YA' if results[-1]['entitlement_split'] else 'TIDAK'}")
        print()

    payload = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": "uji ulang klaim entitlement per (kunci, model) dengan rekord "
                   "lengkap (perbaikan cacat v2: error kunci pertama tertimpa)",
        "unique_keys": len(entries),
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"tersimpan: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
