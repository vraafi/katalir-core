#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terapkan patch BEDAH (anchored) ke `api_server.py` di VPS — idempoten.

KENAPA SKRIP, BUKAN `scp`:
`api_server.py` di VPS TIDAK identik dengan HEAD repo — di sana sudah ada
patch `/status` (deep health) yang disisipkan pasca-deploy. Menimpa berkas itu
dengan versi repo akan:
  * menghapus patch `/status`, dan
  * membuat modul mengimpor berkas yang BELUM ada di VPS (`mcp_compat.py`,
    `chat_stream.py`, `evidence_ledger.py`, `workflow_ops.py`) -> service gagal
    start.

Jadi tiap perubahan diterapkan sebagai REPLACEMENT BERANCHOR. Skrip MENOLAK
jalan bila anchor tidak ditemukan TEPAT satu kali (mencegah patch parsial /
salah tempat), melewati patch yang sudah terpasang, menulis backup
bertimestamp, lalu memverifikasi hasilnya + `py_compile`.

`database.py` TIDAK perlu di sini: berkas itu byte-identik dengan HEAD repo,
jadi aman di-`scp` langsung.

Jalankan di VPS:
    /root/katalir-core/venv/bin/python3 -u ops/patch_vps.py
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import py_compile
import sys

TARGET = pathlib.Path("/root/katalir-core/api_server.py")

# ---------------------------------------------------------------------------
# PATCH 1 — penjaga `session_id` non-UUID (FIX 2026-10-11, HTTP 503 / 22P02)
# ---------------------------------------------------------------------------
P1_ANCHOR = '''    session_id = req.session_id or prior_session
    if not session_id:
'''

P1_PATCHED = '''    session_id = req.session_id or prior_session
    # FIX 2026-10-11 (503 `22P02` saat chat): `session_id` dari KLIEN tidak
    # dipercaya. Nilai non-UUID (mis. "local_2" dari fallback memori versi
    # lama, atau klien yang salah kirim) dulu diteruskan apa adanya ke
    # `chat_sessions.own_check` yang mem-filter kolom `uuid` -> PostgREST
    # 22P02 -> HTTP 503 "Supabase error saat chat_sessions.own_check".
    # Sekarang id non-UUID DIABAIKAN (dianggap belum punya sesi) sehingga
    # sesi baru dibuat dan chat tetap berhasil.
    # Bukti: `ops/repro_uuid_bug.py` (K1/K2 503 sebelum, 200 sesudah).
    if session_id and not db.is_uuid(session_id):
        print(f"[api_server] /chat: session_id non-UUID diabaikan: "
              f"{str(session_id)[:40]!r}")
        session_id = None
    if not session_id:
'''

# ---------------------------------------------------------------------------
# PATCH 2 — jaring pengaman exception tak tertangani (FIX 2026-10-11, HTTP 500)
# ---------------------------------------------------------------------------
P2_ANCHOR = '''app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS,
    # API gateway tidak dilayani via `www`, jadi fail-closed (400) lebih
    # dapat di_debug daripada redirect diam-diam yang bisa jadi loop.
    www_redirect=False,
)
'''

P2_PATCHED = P2_ANCHOR + '''

# ---------------------------------------------------------------------------
# JARING PENGAMAN TERAKHIR: exception tak tertangani -> SELALU berpesan
#
# BUG PRODUKSI 2026-10-11 (terukur, bukan dugaan). `/root/api_server.log`
# mencatat 71 `Exception in ASGI application` dari burst `/chat` konkuren,
# didominasi gangguan transport ke PostgREST:
#     58x httpx.RemoteProtocolError: Server disconnected
#      2x httpx.WriteError: EOF occurred in violation of protocol (_ssl.c:2417)
#      2x httpx.RemoteProtocolError: <ConnectionTerminated error_code:1 ...>
# plus balapan `23505 duplicate key ... user_usage_pkey`.
#
# Jalur bocornya: `db.check_quota(...)` TIDAK berada di dalam try/except mana
# pun di endpoint `/chat`, sehingga kegagalan tulis kuota naik sampai Starlette
# dan menjadi `500 Internal Server Error` TANPA `detail`. Itu merusak dua hal:
#   1. kontrak "5xx wajib berpesan" (tests/test_503_detail_contract.py);
#   2. `classifyHttpError(500)` di frontend menandai `retryable: false`
#      sehingga tombol "Coba Lagi" TIDAK muncul padahal gangguannya sementara.
#
# Status DIBEDAKAN dengan sengaja supaya bug nyata tidak tersamarkan:
#   * gangguan transport/timeout -> 503 (retryable);
#   * exception lain (bug)       -> 500 + `detail` (pesannya tetap terbaca).
#
# `HTTPException` TIDAK terpengaruh (Starlette memilih handler paling spesifik).
# ---------------------------------------------------------------------------
_TRANSIENT_EXC_NAMES = frozenset({
    "RemoteProtocolError", "ConnectError", "ReadError", "WriteError",
    "ReadTimeout", "ConnectTimeout", "PoolTimeout", "NetworkError",
    "ConnectionTerminated", "ConnectionResetError", "ConnectionAbortedError",
    "BrokenPipeError", "IncompleteRead", "LocalProtocolError",
    "ConnectionError", "TimeoutError",
})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    from fastapi.responses import JSONResponse

    _name = type(exc).__name__
    transient = _name in _TRANSIENT_EXC_NAMES or isinstance(
        exc, (ConnectionError, TimeoutError))
    status = 503 if transient else 500
    print(f"[api_server] UNHANDLED {request.method} {request.url.path} -> "
          f"{status} | {_name}: {str(exc)[:300]}")
    detail = (f"Gangguan sementara pada server ({_name}). Coba lagi sebentar."
              if transient else
              f"Terjadi kesalahan internal ({_name}). Tim sudah diberi tahu.")
    return JSONResponse(status_code=status, content={"detail": detail})
'''

PATCHES = [
    ("session_id-guard", P1_ANCHOR, P1_PATCHED, "db.is_uuid(session_id)"),
    ("unhandled-exception-handler", P2_ANCHOR, P2_PATCHED,
     "_unhandled_exception_handler"),
]


def main() -> int:
    if not TARGET.exists():
        print(f"FATAL: {TARGET} tidak ada")
        return 2
    src = TARGET.read_text(encoding="utf-8")
    original = src
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for name, anchor, patched, marker in PATCHES:
        if marker in src:
            print(f"[{name}] SUDAH ADA — dilewati")
            continue
        n = src.count(anchor)
        if n != 1:
            print(f"[{name}] FATAL: anchor ditemukan {n}x (harus 1x). DIBATALKAN.")
            return 3
        src = src.replace(anchor, patched)
        print(f"[{name}] diterapkan (+{len(patched) - len(anchor)} byte)")

    if src == original:
        print("Tidak ada perubahan. Selesai.")
        return 0

    backup = TARGET.with_name(f"api_server.py.bak-{stamp}")
    backup.write_text(original, encoding="utf-8")
    print(f"backup: {backup} ({len(original)} byte)")

    TARGET.write_text(src, encoding="utf-8")
    print(f"tulis: {TARGET} ({len(src)} byte)")

    check = TARGET.read_text(encoding="utf-8")
    for name, _a, _p, marker in PATCHES:
        assert marker in check, f"[{name}] marker hilang setelah patch"
    try:
        py_compile.compile(str(TARGET), doraise=True)
        print("py_compile: OK")
    except py_compile.PyCompileError as exc:
        TARGET.write_text(original, encoding="utf-8")
        print(f"FATAL: py_compile gagal -> dipulihkan dari backup\n{exc}")
        return 4
    print("SELESAI: semua patch terpasang & terverifikasi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
