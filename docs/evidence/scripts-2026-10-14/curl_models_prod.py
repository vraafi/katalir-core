"""Cek GET /models PRODUKSI via curl asli (bukan library) + dump respons mentah.

Kenapa curl: brief meminta "cek endpoint produksi /models via curl". Library
helper `api()` di rus_core memakai requests; commit evidence harus menunjukkan
perintah persis yang bisa diulang. Token dinonaktifkan lagi di akhir
(drop_user) supaya tidak ada akun nyasar.

Keluaran: docs/evidence/verifikasi-06345af/prod_models_raw.json + prod_models_curl.txt
Jalankan: python docs/evidence/scripts-2026-10-14/curl_models_prod.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent


def _repo_root() -> pathlib.Path:
    for cand in [HERE, *HERE.parents]:
        if (cand / "tests" / "user_test" / "rus_core.py").exists():
            return cand
    raise SystemExit("repo root tidak ditemukan")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "tests" / "user_test"))

from rus_core import drop_user, make_user  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "verifikasi-06345af"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://gateway.katalir.de5.net/katalir-api"
# Cloudflare memblokir klien non-browser (403 code 1010) -> UA browser WAJIB.
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"

u = make_user("probe-verifikasi-06345af")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
TOK = u["session"]["access_token"]
print(f"akun uji: {u['email']}")

proc = None
try:
    # Perintah curl PERSIS (direkam sebagai bukti, bisa di-copy user).
    cmd = [
        "curl", "-s", "-w", "\nHTTP_STATUS:%{http_code}\n",
        "-H", f"Authorization: Bearer {TOK}",
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: application/json",
        f"{BASE}/models",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    out = proc.stdout
    print(f"curl exit={proc.returncode} bytes={len(out)}")

    # Pisahkan body dari status yang ditambahkan -w.
    idx = out.rfind("\nHTTP_STATUS:")
    status_line = out[idx + 1:].strip() if idx >= 0 else "HTTP_STATUS:?"
    body = out[:idx] if idx >= 0 else out
    http_code = int(status_line.split(":")[1]) if ":" in status_line else 0
    print(f"HTTP {http_code}")

    # Simpan perintah (token DISAMARKAN) + output mentah.
    (OUT / "prod_models_curl.txt").write_text(
        "curl -s -w '\\nHTTP_STATUS:%{http_code}\\n' \\\n"
        "  -H 'Authorization: Bearer <TOKEN_DISAMARKAN>' \\\n"
        f"  -H 'User-Agent: {UA}' \\\n"
        "  -H 'Accept: application/json' \\\n"
        f"{BASE}/models\n\n"
        f"--- exit={proc.returncode} {status_line} bytes={len(body)} ---\n\n"
        + body + "\n",
        encoding="utf-8")

    if http_code != 200:
        print(body[:600])
        raise SystemExit(3)

    data = json.loads(body)
    models = data.get("models") or []
    gemini = [m for m in models if "gemini" in str(m.get("id", "")).lower()]
    raw = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": f"{BASE}/models",
        "http_status": http_code,
        "model_count": len(models),
        "tier": data.get("tier"),
        "default": data.get("default"),
        "roster_source": data.get("roster_source"),
        "degraded": data.get("degraded"),
        "gemini_count": len(gemini),
        "gemini_ids": sorted(str(m.get("id")) for m in gemini),
        "not_offered_filtered": data.get("not_offered_filtered"),
        "raw_response": data,
    }
    (OUT / "prod_models_raw.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nroster_source={data.get('roster_source')} degraded={data.get('degraded')}")
    print(f"default={data.get('default')}  total={len(models)}  gemini={len(gemini)}")
    print(f"not_offered_filtered={data.get('not_offered_filtered')}")
    print("\n--- semua id ---")
    for i in sorted(str(m.get('id')) for m in models):
        print(f"  {i}")
    print("\n--- id gemini ---")
    for i in raw["gemini_ids"]:
        print(f"  {i}")
finally:
    if u.get("id"):
        drop_user(u["id"])
        print(f"\nakun uji dihapus: {u['email']}")
