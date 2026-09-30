"""Uji RLS Supabase dengan akses ANONIM (tanpa apikey).

Kalau RLS aktif, tabel pengguna WAJIB menolak request tanpa JWT user
(400/401/403) ATAU mengembalikan 0 baris. Respons 200 berisi data nyata
berarti tabel terbuka ke publik = temuan severity TINGGI.

Dikirim ke REST PostgREST, bukan ke browser, karena itu path yang dipakai
frontend. Hanya nama tabel, status, dan JUMLAH BARIS yang dicetak - bukan isi.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

# Diambil dari CSP `connect-src` di public/_headers (sumber kebenaran produksi).
SUPABASE = "https://qmukkphwaajzbqjrcvaz.supabase.co"
UA = {"User-Agent": "katalir-security-audit", "Accept": "application/json"}

TABLES = [
    "users", "sessions", "messages", "integrations", "workflows",
    "community_submissions", "vault", "api_keys", "profiles",
]


def probe(table: str, timeout: float = 12.0) -> tuple[int | str, int, str]:
    """Kembalikan (status, jumlah_baris, pesan_error)."""
    url = f"{SUPABASE}/rest/v1/{urllib.parse.quote(table)}?select=*&limit=3"
    req = urllib.request.Request(url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                data = json.loads(body)
                n = len(data) if isinstance(data, list) else -1
            except Exception:
                n = -1
            return r.status, n, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        # Pesan Supabase tidak memuat data user, hanya nama constraint/kolom.
        msg = raw[:120].replace("\n", " ")
        return exc.code, 0, msg
    except Exception as exc:
        return type(exc).__name__, 0, ""


def main() -> int:
    findings = []
    rows_seen = 0
    for t in TABLES:
        code, n, msg = probe(t)
        verdict = "OK"
        if code == 200 and n > 0:
            verdict = "EXPOSED"
            rows_seen += n
        elif code == 200 and n == 0:
            verdict = "RLS_EMPTY"
        print(f"{t:26} -> {code} rows={n} {verdict} {msg[:70]}")
        findings.append({"table": t, "code": code, "rows": n, "verdict": verdict, "msg": msg})

    print(f"\nEXPOSED_TABLES={[f['table'] for f in findings if f['verdict'] == 'EXPOSED']}")
    print(f"ROWS_LEAKED={rows_seen}")

    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"findings": findings, "rows_leaked": rows_seen}, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
