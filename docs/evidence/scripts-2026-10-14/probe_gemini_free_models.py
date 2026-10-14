"""probe_gemini_free_models.py - Daftar model yang BENAR-BENAR bisa dipakai gratis.

Menjawab pertanyaan: setelah kebijakan Google 2026-10-09 (free tier = Flash-Lite),
model Gemini mana yang masih melayani untuk 13 kunci kita?

Dua sumber bukti:
  1. `client.models.list()` per kunci -> katalog RESMI dari Google untuk kunci itu
     (otoritatif; tidak menebak dari daftar kami sendiri).
  2. Probe `generate_content` 1 token per model -> membuktikan benar-benar
     MELAYANI, bukan sekadar terdaftar.

Kunci TIDAK pernah dicetak: hanya `NAMA#<fingerprint8>`.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import gemini_key_pool as pool_mod  # noqa: E402

OUT_DIR = ROOT / "docs" / "evidence" / "gemini-free-models-2026-10-14"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Kandidat: keluarga flash-lite (satu-satunya yang masih gratis pasca 10-09)
# DITAMBAH beberapa non-flash-lite untuk MEMBUKTIKAN statusnya (positif-kontrol
# negatif). Tanpa yang terakhir, "hanya flash-lite" hanyalah klaim.
CANDIDATES = [
    # --- keluarga Flash-Lite (diduga masih gratis) ---
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    # --- non Flash-Lite (diduga sudah tidak gratis pasca 10-09) ---
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    # --- baru, rilis 2026-09-30/10-13 ---
    "gemini-4-argon",
    "gemini-4-argon-lite",
]

PROMPT = "Balas tepat satu kata: OK"


def main() -> int:
    pool_mod.load_env_file()
    entries = pool_mod.discover_keys()
    print(f"kunci unik terlihat: {len(entries)}")
    if not entries:
        print("TIDAK ADA KUNCI")
        return 1

    from google import genai
    from google.genai import types

    name, key, fp = entries[0]
    print(f"memakai kunci: {name}#{fp} (nilai tidak dicetak)")
    print()

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=30000),
    )

    # ---- 1. katalog resmi dari Google untuk kunci ini ----
    catalog: list[str] = []
    cat_err = ""
    try:
        for m in client.models.list():
            mid = (getattr(m, "name", "") or "").replace("models/", "")
            if mid:
                catalog.append(mid)
    except Exception as exc:  # noqa: BLE001
        cat_err = f"{type(exc).__name__}: {exc}"[:300]
    print(f"katalog resmi Google: {len(catalog)} model" + (f"  (gagal: {cat_err})" if cat_err else ""))
    print()

    # ---- 2. probe layanan nyata ----
    rows: list[dict] = []
    for mid in CANDIDATES:
        row: dict = {"model": mid, "in_catalog": mid in catalog}
        t0 = time.time()
        try:
            resp = client.models.generate_content(model=mid, contents=PROMPT)
            txt = (getattr(resp, "text", "") or "").strip()[:60]
            row.update(served=True, latency_ms=int((time.time() - t0) * 1000),
                       reply=txt, error="")
        except Exception as exc:  # noqa: BLE001
            kind, ttl = pool_mod.classify_error(exc)
            row.update(served=False, latency_ms=int((time.time() - t0) * 1000),
                       reply="", error=f"[{kind}] {str(exc)[:200]}")
        rows.append(row)
        mark = "OK  " if row["served"] else "GAGAL"
        print(f"  {mark} {mid:28s} katalog={str(row['in_catalog']):5s} "
              f"{row['latency_ms']:>6d}ms  {row['reply'] or row['error'][:90]}")

    served = [r["model"] for r in rows if r["served"]]
    print()
    print(f"BISA DIPAKAI GRATIS ({len(served)}): {served}")

    payload = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "key_label": f"{name}#{fp}",
        "unique_keys": len(entries),
        "catalog_size": len(catalog),
        "catalog_error": cat_err,
        "catalog_flash_lite": sorted(m for m in catalog if "flash-lite" in m.lower()),
        "catalog_flash": sorted(m for m in catalog if "flash" in m.lower() and "flash-lite" not in m.lower()),
        "catalog_gemini4": sorted(m for m in catalog if m.startswith("gemini-4")),
        "catalog_all": sorted(catalog),
        "rows": rows,
        "served": served,
    }
    p = OUT_DIR / "probe_gemini_free_models.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"disimpan: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
