"""LoopFlow-style verification gate.

Mendapat satu keputusan PASS/FAIL dari model QA dengan kunci Gemini
yang BERDAWAH dari worker, lalu mengembalikannya sebagai exit code.

Kenapa ini bukan "sekarang LLM yang menilai": supaya ada satu tempat
yang memutuskan, output-nya bisa dibaca mesin, dan kegagalan tidak
dapat disamarkan jadi "kelihatan oke". Jika panggilan API gagal, gate
mengembalikan FAIL, bukan PASS. Gate yang tidak bisa menilai lebih berbahaya
daripada gate yang menolak.

Pakai:
    python scripts/gamedev/verify_gate.py --spec GAME_SPEC.md \
        --output worker-output.log --key GEMINI_KEY_6
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from dotenv_loader import load_repo_env

MODEL = "gemini-2.5-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent"

RUBRIC = """Kamu adalah QA reviewer untuk game yang dibuat otomatis oleh AI.

Baca SPEC dan OUTPUT DIBAWAH, lalu nilai apakah output itu benar-benar
memenuhi acceptance criteria di spec.

Aturan penilaian:
- PASS hanya jika SEMUA acceptance criteria terpenuhi dan ada bukti.
- Kalau bukti tidak ada, itu FAIL. Jangan mengarang bukti.
- Kalau spec tidak punya acceptance criteria, kembalikan FAIL dan
  katakan spec-nya tidak bisa diverifikasi.

Balas HANYA dalam format ini, tanpa kalimat lain:
VERDICT: PASS
atau
VERDICT: FAIL: <alasan singkat>

SPEC:
{spec}

OUTPUT:
{output}
"""


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()[:12000]


def call_gemini_real(api_key: str, spec: str, output: str, timeout: int = 90) -> str:
    # Kunci dikirim lewat header `x-goog-api-key`, BUKAN `?key=` di query string.
    # Query string masuk ke access log, log proxy, dan bisa muncul di error
    # message - artinya kunci bocor ke tempat yang tidak kita kendalikan.
    # Guard `tests/test_key_in_header_not_url.py` menegakkan aturan ini.
    url = ENDPOINT.format(model=MODEL)
    body = {
        "contents": [{"parts": [{"text": RUBRIC.format(spec=spec, output=output)}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 300},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--key", default="GEMINI_KEY_6")
    ap.add_argument("--raw", action="store_true", help="cetak respons mentah")
    args = ap.parse_args()

    load_repo_env()
    api_key = (os.getenv(args.key) or "").strip()
    if not api_key:
        print(f"VERDICT: FAIL: {args.key} kosong di .env")
        return 1

    try:
        spec = read(args.spec)
        out = read(args.output)
    except OSError as exc:
        print(f"VERDICT: FAIL: tidak bisa membaca file - {exc}")
        return 1

    try:
        text = call_gemini_real(api_key, spec, out)
    except (urllib.error.URLError, KeyError, TimeoutError, json.JSONDecodeError) as exc:
        # Gate yang tidak bisa menilai HARUS gagal, bukan lolos diam-diam.
        print(f"VERDICT: FAIL: QA tidak dapat dihubungi - {type(exc).__name__}")
        return 1

    if args.raw:
        print(text)
    verdict = "PASS" if "VERDICT: PASS" in text.upper() else "FAIL"
    line = next((ln for ln in text.splitlines() if "VERDICT" in ln.upper()), "VERDICT: FAIL: respons QA tidak memuat verdict")
    print(line.strip())
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
