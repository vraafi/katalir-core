"""Hapus akun uji sementara yang dibuat oleh rus_newuser.py / J3."""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rus_core import drop_user  # noqa: E402

removed = []
for f in ("_rus_user.json",):
    p = HERE / f
    if not p.exists():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    drop_user(d.get("id"))
    removed.append(d.get("email"))
    p.unlink()

sess = HERE / "_session_rus.json"
if sess.exists():
    sess.unlink()

print(f"akun dihapus: {removed}")
print("sesi akun uji final dibersihkan.")
