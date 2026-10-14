"""Probe GET /models — daftar model yang BENAR-BENAR sampai ke picker frontend.

Dipakai dua kali (before/after) untuk membuktikan perubahan:
  * `google/gemma-4-31b-it`  -> HARUS hilang dari picker (Task 1)
  * `gemini-3.1-flash-lite`  -> HARUS tidak ada (Task 2, entri basi)

Kenapa lewat endpoint dan bukan membaca `models.ts`: picker TIDAK memakai
daftar statis. `ChatApp.tsx:220` memakai `GET /models` (discovery live) dan
`models.ts` hanya loading-fallback. Jadi "hapus dari picker" hanya bisa
dibuktikan di sini.

Jalankan:  python docs/evidence/scripts-2026-10-14/probe_models_picker.py <label>
Keluaran:  docs/evidence/models-picker-2026-10-14/models_<label>.json
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _repo_root() -> pathlib.Path:
    """Naik sampai menemukan `tests/user_test/rus_core.py`.

    Skrip ini hidup di `docs/evidence/scripts-*/`, sedangkan harness ada di
    `tests/user_test/` pada ROOT repo. Resolusi relatif sederhana (`HERE/"tests"`)
    akan salah di sini -- jadi dicari ke atas, bukan ditebak.
    """
    for cand in [HERE, *HERE.parents]:
        if (cand / "tests" / "user_test" / "rus_core.py").exists():
            return cand
    raise SystemExit("repo root tidak ditemukan (tests/user_test/rus_core.py)")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "tests" / "user_test"))

from rus_core import api, drop_user, make_user  # noqa: E402

LABEL = (sys.argv[1] if len(sys.argv) > 1 else "before").strip()
OUT = ROOT / "docs" / "evidence" / "models-picker-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

#: Id yang HARUS tidak muncul di picker setelah perbaikan.
MUST_BE_ABSENT = {
    "google/gemma-4-31b-it": "Task 1 - tak bisa dilayani (kuota habis)",
    "gemma-4-31b-it": "Task 1 - alias lama tanpa awalan penyedia",
    "gemini-3.1-flash-lite": "Task 2 - entri basi, tak ada di roster",
}

u = make_user("probe-picker")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
TOK = u["session"]["access_token"]
print(f"akun uji: {u['email']}")

try:
    st, body = api("GET", "/models", token=TOK)
    print(f"GET /models -> HTTP {st}")
    if st != 200:
        print(body[:500])
        raise SystemExit(3)

    data = json.loads(body)
    models = data.get("models") or []
    ids = [str(m.get("id") or "") for m in models]

    raw = {
        "label": LABEL,
        "http_status": st,
        "tier": data.get("tier"),
        "default": data.get("default"),
        "roster_source": data.get("roster_source"),
        "degraded": data.get("degraded"),
        "degraded_reason": data.get("degraded_reason"),
        "refreshed_at": data.get("refreshed_at"),
        "model_count": len(ids),
        "model_ids": ids,
        "not_offered_filtered": data.get("not_offered_filtered"),
        # Respons mentah penuh: bukti tidak boleh berupa ringkasan buatan sendiri.
        "raw_response": data,
    }
    (OUT / f"models_{LABEL}.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nroster_source={data.get('roster_source')} degraded={data.get('degraded')}")
    print(f"default={data.get('default')}  jumlah model={len(ids)}")
    print(f"not_offered_filtered={data.get('not_offered_filtered')}")
    print("\n--- hasil pemeriksaan ---")
    verdict = {}
    for mid, why in MUST_BE_ABSENT.items():
        present = mid in ids
        verdict[mid] = {"present": present, "expected": "ABSENT", "why": why,
                        "ok": not present}
        print(f"  [{'OK' if not present else 'STILL PRESENT'}] {mid}  ({why})")
    raw["checks"] = verdict
    (OUT / f"models_{LABEL}.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n--- semua id ({len(ids)}) ---")
    for i in ids:
        print(f"  {i}")
finally:
    if u.get("id"):
        drop_user(u["id"])
        print(f"\nakun uji dihapus: {u['email']}")
