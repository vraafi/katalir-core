"""Siapkan AKUN UJI KHUSUS untuk run final (kuota harian penuh).

Akun `otonom-t-...` sudah terpakai 64/100 request oleh run diagnostik. Run
final butuh ~40 request lagi, jadi akun itu akan kena batas dan menghasilkan
kegagalan PALSU. Solusinya sama seperti uji beban sebelumnya: buat akun
Supabase NYATA baru (lewat Admin API), pakai, lalu hapus setelah selesai.

Keluaran:
  tests/user_test/_session_rus.json  (sesi akun baru; dipakai rus_core)
  tests/user_test/_rus_user.json     (id + email, untuk pembersihan)
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rus_core import (ANON, REF, SB, drop_user, make_user)  # noqa: E402

# bersihkan akun final sebelumnya (kalau skrip dijalankan ulang)
prev = HERE / "_rus_user.json"
if prev.exists():
    try:
        old = json.loads(prev.read_text(encoding="utf-8"))
        drop_user(old.get("id"))
        print(f"akun final sebelumnya dihapus: {old.get('email')}")
    except Exception as exc:  # noqa: BLE001
        print(f"peringatan: gagal hapus akun lama: {exc}")

u = make_user("rus-final")
if not (u and u.get("session")):
    print("GAGAL membuat akun uji final")
    raise SystemExit(2)

tok = u["session"]
payload = {
    "storage_key": f"sb-{REF}-auth-token",
    "session": {
        "access_token": tok["access_token"],
        "token_type": tok.get("token_type", "bearer"),
        "expires_in": tok.get("expires_in", 3600),
        "expires_at": tok.get("expires_at"),
        "refresh_token": tok.get("refresh_token"),
        "user": tok.get("user"),
    },
    "supabase_url": SB,
    "anon_key": ANON,
}
(HERE / "_session_rus.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
(HERE / "_rus_user.json").write_text(
    json.dumps({"id": u["id"], "email": u["email"]}, ensure_ascii=False,
               indent=1), encoding="utf-8")

print(f"akun uji final : {u['email']}")
print(f"user id        : {u['id']}")
print(f"sesi           -> {HERE / '_session_rus.json'}")
print("JANGAN LUPA hapus akun ini setelah run final (rus_cleanup.py).")
