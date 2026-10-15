"""probe_allowlist_v3b.py - Probe FRESH 7 id allowlist key_catalog.

Pertanyaan gerbang Fase 2: apakah 7 id yang mau ditambahkan ke picker
(3.7/3.6/3.5-flash, 3.1-flash-lite, 3.1-flash-lite-preview, flash-latest,
flash-lite-latest) BISA dilayani HARI INI? gemma-4-31b-it & 3.8-flash
terbukti 200 OK kemarin tapi 0/N hari ini (503 overloaded) — jadi bukti
kemarin saja TIDAK cukup untuk menawarkan model di picker.

Setiap id diuji ke 3 kunci; SEMUA hasil terekam (tanpa short-circuit).
Output: docs/evidence/verifikasi-06345af/probe_allowlist_v3b.json
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

OUT = ROOT / "docs" / "evidence" / "verifikasi-06345af" / "probe_allowlist_v3b.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

PROMPT = "Balas tepat satu kata: OK"

ALLOWLIST = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]
N_KEYS = 3


def main() -> int:
    pool_mod.load_env_file()
    entries = pool_mod.discover_keys()
    print(f"kunci unik: {len(entries)}")
    if not entries:
        print("TIDAK ADA KUNCI")
        return 1

    from google import genai

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
        th.join(30.0)
        if th.is_alive():
            result = {"served": False, "detail": "[timeout] >30 s tanpa jawaban"}
        result["latency_ms"] = int((time.time() - t0) * 1000)
        return result

    results = []
    for mid in ALLOWLIST:
        attempts = []
        for name, api_key, fp in entries[:N_KEYS]:
            label = f"{name}#{fp[:8]}"
            a = attempt(genai.Client(api_key=api_key,
                                     http_options={"timeout": 20000}), mid)
            a["key"] = label
            attempts.append(a)
            print(f"  {mid:30s} {label:24s} "
                  f"{'OK   ' if a['served'] else 'GAGAL'} {a['latency_ms']:>6}ms")
            time.sleep(1.2)
        n_ok = sum(1 for a in attempts if a["served"])
        results.append({"model": mid, "keys_served": n_ok,
                        "keys_tested": len(attempts), "attempts": attempts})
        print(f"=> {mid}: {n_ok}/{len(attempts)}\n")

    OUT.write_text(json.dumps(
        {"probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "purpose": "probe fresh 7 id allowlist key_catalog sebelum gerbang Fase 2",
         "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"tersimpan: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
