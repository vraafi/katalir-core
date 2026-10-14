"""probe_gemini_free_models_v2.py - Daftar DEFINITIF model Gemini yang gratis.

Menjawab: "model Gemini mana yang benar-benar bisa dipakai GRATIS dengan 13 kunci
kita, per Oktober 2026?"

Pendekatan (EVAL-FIRST, bukan klaim):
  1. `client.models.list()` -> katalog otoritatif Google untuk kunci ini.
  2. Saring ke model TEKS-CHAT saja (buang image/tts/audio/video/embedding/live/
     robotics/computer-use/lyria/veo/deep-research/aqa).
  3. Probe `generate_content` 1 kata per model.
  4. Model yang GAGAL diuji ulang dengan 2 kunci BERBEDA -> membedakan
     "entitlement kunci ini" dari "memang tidak tersedia".

Kunci tidak pernah dicetak (hanya NAMA#fingerprint8).
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import gemini_key_pool as pool_mod  # noqa: E402

OUT_DIR = ROOT / "docs" / "evidence" / "gemini-free-models-2026-10-14"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROMPT = "Balas tepat satu kata: OK"
TIMEOUT_MS = 25000

# Buang non-teks-chat. Sengaja eksplisit (bukan regex longgar) supaya model baru
# tidak diam-diam terbuang ATAU diam-diam lolos.
_EXCLUDE_SUBSTR = (
    "image", "tts", "audio", "native-audio", "live", "robotics", "computer-use",
    "lyria", "veo", "imagen", "embedding", "aqa", "deep-research", "transcribe",
    "nano-banana", "antigravity", "omni",
)
# Model yang memang berbayar (Pro) -> tidak diharapkan gratis.
_PAID_HINT = ("-pro", "pro-latest", "pro-preview")


def is_text_chat(mid: str) -> bool:
    low = mid.lower()
    if any(s in low for s in _EXCLUDE_SUBSTR):
        return False
    return low.startswith("gemini") or low.startswith("gemma")


def main() -> int:
    pool_mod.load_env_file()
    entries = pool_mod.discover_keys()
    print(f"kunci unik: {len(entries)}")
    if not entries:
        return 1

    from google import genai
    from google.genai import types

    def client_for(i: int):
        name, key, fp = entries[i % len(entries)]
        return genai.Client(api_key=key,
                            http_options=types.HttpOptions(timeout=TIMEOUT_MS)), f"{name}#{fp}"

    client, label0 = client_for(0)
    print(f"kunci probe utama: {label0}")
    print()

    # 1. katalog
    catalog: list[str] = []
    try:
        for m in client.models.list():
            mid = (getattr(m, "name", "") or "").replace("models/", "")
            if mid:
                catalog.append(mid)
    except Exception as exc:  # noqa: BLE001
        print(f"GAGAL list models: {exc}")
        return 1

    candidates = sorted(m for m in catalog if is_text_chat(m))
    print(f"katalog={len(catalog)}  kandidat teks-chat={len(candidates)}")
    print()

    def attempt(c: "genai.Client", mid: str) -> tuple[bool, str, int]:
        t0 = time.time()
        try:
            r = c.models.generate_content(model=mid, contents=PROMPT)
            return True, (getattr(r, "text", "") or "").strip()[:40], int((time.time() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            kind, _ = pool_mod.classify_error(exc)
            return False, f"[{kind}] {str(exc)[:260]}", int((time.time() - t0) * 1000)

    rows: list[dict] = []
    for mid in candidates:
        ok, detail, ms = attempt(client, mid)
        row = {"model": mid, "served": ok, "detail": detail, "latency_ms": ms,
               "retried_keys": [], "paid_hint": any(h in mid.lower() for h in _PAID_HINT)}
        # Gagal -> uji 2 kunci lain supaya klasifikasinya kuat.
        if not ok:
            for i in (1, 2):
                c2, lab2 = client_for(i)
                ok2, detail2, ms2 = attempt(c2, mid)
                row["retried_keys"].append({"key": lab2, "served": ok2, "detail": detail2})
                if ok2:
                    row["served"] = True
                    row["detail"] = f"{detail2} (via {lab2})"
                    row["latency_ms"] = ms2
                    break
        rows.append(row)
        print(f"  {'OK   ' if row['served'] else 'GAGAL'} {mid:36s} "
              f"{row['latency_ms']:>6d}ms  {row['detail'][:80]}")

    served = sorted(r["model"] for r in rows if r["served"])
    failed = sorted(r["model"] for r in rows if not r["served"])
    print()
    print(f"=== BISA DIPAKAI GRATIS ({len(served)}) ===")
    for m in served:
        print("   ", m)
    print()
    print(f"=== TIDAK BISA ({len(failed)}) ===")
    for m in failed:
        print("   ", m)

    payload = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "unique_keys": len(entries),
        "probe_key": label0,
        "catalog_size": len(catalog),
        "catalog_all": sorted(catalog),
        "candidates_text_chat": candidates,
        "rows": rows,
        "served": served,
        "failed": failed,
    }
    p = OUT_DIR / "probe_gemini_free_models_v2.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"disimpan: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
