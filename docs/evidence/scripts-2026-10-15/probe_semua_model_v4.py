"""probe_semua_model_v4.py - Fase 0 brief DYNAMIC MODEL DISCOVERY.

Probe LENGKAP semua kandidat text-chat dari `client.models.list()` (bukan
allowlist): setiap kandidat diuji `generate_content` dengan prompt minimal,
timeout 10 s, MAKSIMAL 3 kunci per model (batasan brief). Model yang gagal
diuji ke 2 kunci lain untuk membedakan entitlement vs overloaded.

Output:
  evidence/models-list-raw.json        - katalog mentah + filter kandidat
  evidence/probe-semua-model-v4.json   - matriks probe per (model, kunci)
  evidence/probe-semua-model-v4.txt    - log run mentah
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

EV = ROOT / "evidence"
EV.mkdir(exist_ok=True)

PROMPT = "Balas tepat satu kata: OK"
TIMEOUT_HTTP_MS = 10000   # brief: timeout 10 s
JOIN_S = 15.0             # batas keras thread
MAX_KEYS = 3              # brief: maksimal 3 kunci per model

# Exclude non-text (pola yang sama dgn key_catalog/probe v2)
_EXCLUDE_SUBSTR = (
    "image", "tts", "audio", "native-audio", "live", "robotics", "computer-use",
    "lyria", "veo", "imagen", "embedding", "aqa", "deep-research", "transcribe",
    "nano-banana", "antigravity", "omni",
)


def is_text_chat(mid: str, actions: list[str]) -> bool:
    low = (mid or "").strip().lower()
    if not low or not low.startswith(("gemini", "gemma")):
        return False
    if any(s in low for s in _EXCLUDE_SUBSTR):
        return False
    return "generateContent" in (actions or [])


def main() -> int:
    pool_mod.load_env_file()
    entries = pool_mod.discover_keys()
    print(f"kunci unik: {len(entries)}")
    if not entries:
        print("TIDAK ADA KUNCI")
        return 1

    from google import genai

    name0, key0, fp0 = entries[0]
    label0 = f"{name0}#{fp0[:8]}"
    client0 = genai.Client(api_key=key0, http_options={"timeout": TIMEOUT_HTTP_MS})

    # --- langkah 4: katalog mentah ---
    catalog = []
    for entry in client0.models.list():
        catalog.append({
            "id": (getattr(entry, "name", "") or "").replace("models/", ""),
            "supported_actions": list(getattr(entry, "supported_actions", []) or []),
        })
    candidates = [c for c in catalog if is_text_chat(c["id"], c["supported_actions"])]
    print(f"katalog: {len(catalog)} model; kandidat text-chat: {len(candidates)}")
    (EV / "models-list-raw.json").write_text(json.dumps({
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "probe_key": label0,
        "catalog_size": len(catalog),
        "catalog": catalog,
        "candidates_text_chat": [c["id"] for c in candidates],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- langkah 6-7: probe per kandidat, maks 3 kunci ---
    def attempt(client, mid: str) -> dict:
        t0 = time.time()
        result: dict = {}

        def _call():
            try:
                r = client.models.generate_content(model=mid, contents=PROMPT)
                txt = (getattr(r, "text", "") or "").strip()[:40]
                result.update({"status": 200, "served": True,
                               "detail": f"OK text={txt!r}"})
            except Exception as exc:  # noqa: BLE001
                kind, _ = pool_mod.classify_error(exc)
                result.update({"status": None, "served": False,
                               "detail": f"[{kind}] {str(exc)[:220]}"})

        th = threading.Thread(target=_call, daemon=True)
        th.start()
        th.join(JOIN_S)
        if th.is_alive():
            result = {"status": None, "served": False,
                      "detail": "[timeout] >10 s tanpa jawaban"}
        result["latency_ms"] = int((time.time() - t0) * 1000)
        return result

    results = []
    for c in candidates:
        mid = c["id"]
        attempts = []
        for name, api_key, fp in entries[:MAX_KEYS]:
            label = f"{name}#{fp[:8]}"
            a = attempt(genai.Client(api_key=api_key,
                                     http_options={"timeout": TIMEOUT_HTTP_MS}), mid)
            a["key"] = label
            attempts.append(a)
            print(f"  {mid:36s} {label:24s} "
                  f"{'OK   ' if a['served'] else 'GAGAL'} {a['latency_ms']:>6}ms")
            time.sleep(1.0)
        n_ok = sum(1 for a in attempts if a["served"])
        kinds = sorted({a["detail"].split("]")[0].strip("[")
                        for a in attempts if not a["served"]})
        results.append({
            "model": mid, "keys_served": n_ok, "keys_tested": len(attempts),
            "lolos": n_ok > 0, "error_kinds": kinds, "attempts": attempts,
        })
        print(f"=> {mid}: {n_ok}/{len(attempts)} kinds={kinds}\n")

    lolos = [r["model"] for r in results if r["lolos"]]
    payload = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "max_keys_per_model": MAX_KEYS,
        "timeout_s": TIMEOUT_HTTP_MS // 1000,
        "candidates": len(candidates),
        "lolos_count": len(lolos),
        "lolos": lolos,
        "results": results,
    }
    (EV / "probe-semua-model-v4.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LOLOS: {len(lolos)}/{len(candidates)}")
    for m in lolos:
        print("   ", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
