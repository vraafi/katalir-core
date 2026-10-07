"""redact_execution_logs_history.py — F-2: redaksi retroaktif `execution_logs`.

Temuan F-2 (brief *"FIX 2 BUG KRITIS + 3 TEMUAN TINGGI"*, 7 Okt 2026):
webhook trigger menyalin SELURUH header HTTP ke payload node Trigger, termasuk
`Authorization: Bearer <JWT ~818 karakter>`. Payload itu dipersist apa adanya
ke `execution_logs.output_data`, sehingga token sesi user tersimpan sebagai
teks biasa di database.

Perbaikan kode (`database.execution_log_row`) menutup jalur tulis BARU. Skrip
ini menutup data LAMA:

  * membaca baris `execution_logs` secara berpaginasi (service key, read-only);
  * baris yang MENGANDUNG data sensitif -> **UPDATE** (hanya kolom yang berubah);
  * baris bersih TIDAK disentuh (hemat I/O, timestamp tidak berubah);
  * **TIDAK PERNAH MENGHAPUS** baris apa pun — jejak audit eksekusi tetap utuh;
  * memverifikasi ulang di akhir: sisa baris ber-teks-rahasia harus 0.

Pemakaian:
    python scripts/redact_execution_logs_history.py            # jalankan
    python scripts/redact_execution_logs_history.py --dry-run  # hanya laporan
    python scripts/redact_execution_logs_history.py --limit 50 # batasi baris

Credential TIDAK pernah dicetak.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import redact_log_row  # noqa: E402

ENV_PATH = ROOT / ".env"
PAGE = 1000

#: Detektor teks rahasia yang tersisa (JWT / Bearer / token provider umum).
_SECRET_RX = re.compile(
    r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
    r"|\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"
    r"|\bya29\.[A-Za-z0-9._-]{20,}",
    re.I,
)


def _read_env() -> dict:
    data: dict[str, str] = {}
    if not ENV_PATH.exists():
        return data
    for raw in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        data[k.strip()] = v.split(" #")[0].strip().strip("\"'")
    return data


_ENV = _read_env()
SUPABASE_URL = (_ENV.get("SUPABASE_URL") or "").rstrip("/")
SERVICE_KEY = (_ENV.get("SUPABASE_SERVICE_KEY")
               or _ENV.get("SUPABASE_SERVICE_ROLE_KEY")
               or _ENV.get("SUPABASE_SECRET_KEY") or "")

BASE = f"{SUPABASE_URL}/rest/v1/execution_logs"
COLS = "id,execution_id,node_id,node_type,status,output_data,error_message"


def _headers(extra: dict | None = None) -> dict:
    return {"apikey": SERVICE_KEY, "Authorization": "Bearer " + SERVICE_KEY,
            "Content-Type": "application/json",
            "User-Agent": "Katalir-Redact/1.0", **(extra or {})}


def _get(url: str, headers: dict) -> tuple[int, list | dict]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode()[:300]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"_error": f"{type(exc).__name__}: {exc}"}


def _patch(row_id, payload: dict) -> tuple[int, str]:
    url = f"{BASE}?id=eq.{row_id}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers=_headers({"Prefer": "return=minimal"}), method="PATCH")
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _scan(limit: int | None) -> tuple[list[dict], int, int]:
    """Ambil semua baris (berpaginasi). Kembalikan (rows, total, error_count)."""
    rows: list[dict] = []
    errors = 0
    offset = 0
    while True:
        end = offset + PAGE - 1
        url = f"{BASE}?select={COLS}&order=id.asc"
        st, body = _get(url, _headers({"Range": f"{offset}-{end}"}))
        if st not in (200, 206) or not isinstance(body, list):
            print(f"  ! baca gagal HTTP {st}: {body}")
            errors += 1
            break
        if not body:
            break
        rows.extend(body)
        if limit is not None and len(rows) >= limit:
            rows = rows[:limit]
            break
        if len(body) < PAGE:
            break
        offset += PAGE
    return rows, len(rows), errors


def _has_secret(row: dict) -> bool:
    blob = json.dumps({"o": row.get("output_data"),
                       "e": row.get("error_message")}, ensure_ascii=False)
    return bool(_SECRET_RX.search(blob))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="hanya laporkan, tidak menulis apa pun")
    ap.add_argument("--limit", type=int, default=None,
                    help="batasi jumlah baris yang dipindai (uji coba)")
    args = ap.parse_args()

    if not SUPABASE_URL or not SERVICE_KEY:
        print("FATAL: SUPABASE_URL / service key tidak ada di .env")
        return 2

    print("=" * 72)
    print("F-2 REDAKSI HISTORIS execution_logs")
    print(f"  target : {SUPABASE_URL}")
    print(f"  mode   : {'DRY-RUN (tanpa tulis)' if args.dry_run else 'EKSEKUSI (UPDATE saja)'}")
    print("=" * 72)

    before_rows, total, errs = _scan(args.limit)
    print(f"[1/4] dipindai            : {total} baris (error baca: {errs})")
    if errs:
        print("      -> hentikan: tidak aman mengubah data tanpa pemindaian utuh")
        return 1

    dirty = [r for r in before_rows if _has_secret(r)]
    print(f"[2/4] baris ber-teks-rahasia: {len(dirty)}")

    updated = failed = skipped = 0
    if not args.dry_run:
        for r in dirty:
            new_row, changed = redact_log_row(r)
            if not changed:
                skipped += 1
                continue
            payload = {}
            if "output_data" in new_row:
                payload["output_data"] = new_row["output_data"]
            if "error_message" in new_row:
                payload["error_message"] = new_row["error_message"]
            st, err = _patch(r.get("id"), payload)
            if st in (200, 204):
                updated += 1
            else:
                failed += 1
                print(f"      ! UPDATE gagal id={r.get('id')} HTTP {st} {err}")
        print(f"[3/4] UPDATE              : {updated} sukses, {failed} gagal, "
              f"{skipped} tanpa perubahan")
    else:
        print("[3/4] UPDATE              : dilewati (dry-run)")

    # Verifikasi ulang dari SUMBER (bukan dari memori).
    after_rows, total2, errs2 = _scan(args.limit)
    remaining = [r for r in after_rows if _has_secret(r)]
    print(f"[4/4] verifikasi ulang    : {total2} baris, sisa ber-teks-rahasia "
          f"= {len(remaining)} (error baca: {errs2})")

    if not args.dry_run:
        print(f"      baris dihapus       : 0  (skrip ini TIDAK PERNAH menghapus)")

    ok = (not args.dry_run) and not remaining and not failed
    print("-" * 72)
    print("HASIL: " + ("LULUS - 0 plaintext tersisa" if ok else
                       ("DRY-RUN selesai" if args.dry_run else "BELUM LULUS")))
    print("=" * 72)
    return 0 if (ok or args.dry_run) else 1


if __name__ == "__main__":
    raise SystemExit(main())
