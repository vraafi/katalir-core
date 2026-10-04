"""argument_validator.py — allowlist per-alat, per-field.

KENAPA BUKAN BLACKLIST
---------------------
`tool_policy_gate` menyaring POLA BERBAHAYA (blacklist). Blacklist
selalu bisa dikalahkan: cukup pakai payload yang belum terdaftar.
Misalnya pola untuk `;`/`&&` bisa dilewati lewat Unicode, atau lewat
field yang tidak punya pola sama sekali.

Yang dipakai di sini adalah ALLOWLIST: hanya field yang terdaftar yang
diterima, dan tiap field punya aturan sendiri. Field yang tidak
dikenal DITOLAK tanpa perlu menebak apakah berbahaya - itu prinsip
"deny by default" (OWASP ASI02: allowlist + validasi argumen).

Pola blacklist di policy gate tetap dipertahankan sebagai lapisan
kedua. Keduanya tidak saling menggantikan.

CATATAN SOAL `pesan`
-------------------
Field `pesan` (isi pesan Telegram/Slack) SENGAJA tanpa `pattern`:
isinya bebas. Persempitan pola di sini akan merusak kegunaan (pesan
sah bisa berisi tanda baca apa saja). Field pesan tetap dilindungi
oleh batas panjang, gate, dan persetujuan pengguna - bukan oleh pola.
"""

from __future__ import annotations

import re

#: Karakter yang aman untuk nama sheet/tab (Spreadsheet).
_SHEET_NAME = r"^[\w \-.]+$"

#: Karakter yang aman untuk subjek email. Sengaja ketat: subjek tidak
#: perlu tanda kutip/semicolon/backslash, dan penyaringannya murah.
#:
#: PENTING: kelas karakter TIDAK memakai `\s`. Diuji: `\s` ikut mencocokkan
#: newline, sehingga "a\nb" lolos - dan newline di subjek membuka risiko
#: header injection saat compose email. `\s` diganti space eksplisit.
#:
#: `&` sengaja IJIN. Diuji: menolak `&` juga menolak subjek sah seperti
#: "Sales & Marketing". `&&` yang berbahaya sudah ditangkap policy gate.
_SUBJECT = r"^[\w \-.,:!?()\[\]&']+$"

#: Skema per-alat. Field di luar daftar = DITOLAK.
ARG_SCHEMAS: dict[str, dict[str, dict]] = {
    "VAULT": {
        "provider": {"type": "enum",
                     "allowed": ["supabase", "gmail_imap", "telegram",
                                 "slack", "google_sheets"]},
    },
    "WORKFLOW": {
        "name": {"type": "string", "max_length": 200},
    },
    "EMAIL": {
        "subjek": {"type": "string", "max_length": 200, "pattern": _SUBJECT},
        "max": {"type": "int", "min": 1, "max": 50},
        "unread_only": {"type": "bool"},
        "mailbox": {"type": "string", "max_length": 40,
                    "pattern": r"^[A-Za-z0-9 /._-]+$"},
    },
    "SHEETS": {
        "spreadsheet": {"type": "string", "max_length": 200,
                        "pattern": r"^[\w\-]+$"},
        "sheet": {"type": "string", "max_length": 100, "pattern": _SHEET_NAME},
        "values": {"type": "list"},
        "range_data": {"type": "string", "max_length": 200,
                       "pattern": r"^[\w!:.$]+$"},
    },
    "TELEGRAM": {
        # Hanya angka (opsional tanda minus untuk grup). Panjang longgar
        # dengan sengaja: Telegram punya chat_id pendek untuk channel
        # pengujian, dan pola `^-?\d{5,15}$` yang lebih ketat MENOLAK
        # chat_id sah - breakage nyata, bukan sekadar teoritis.
        # Yang dilindungi di sini adalah "tidak ada tempat untuk payload",
        # bukan rentang digit.
        "chat_id": {"type": "string", "pattern": r"^-?\d{1,20}$"},
        "pesan": {"type": "string", "max_length": 4000},
    },
    "SLACK": {
        "channel": {"type": "string", "max_length": 120,
                    "pattern": r"^[#@A-Za-z0-9._-]+$"},
        "pesan": {"type": "string", "max_length": 4000},
    },
}


def validate_args(tool: str, args: dict) -> tuple[bool, str]:
    """Return (valid, alasan). DENY by default per field."""
    name = str(tool or "").upper()
    schema = ARG_SCHEMAS.get(name)
    if schema is None:
        return False, f"Alat '{name}' tidak punya skema argumen."

    if not isinstance(args, dict):
        return False, "Argumen harus object."

    # 1. Field tak dikenal -> DENY (bagian paling penting dari allowlist)
    for key in args:
        if key not in schema:
            return False, f"Field '{key}' tidak diizinkan untuk {name}."

    # 2. Periksa tiap field
    for key, value in args.items():
        rule = schema[key]
        kind = rule.get("type")

        if kind == "enum":
            if value not in rule["allowed"]:
                return False, (f"'{value}' tidak valid untuk {key}; "
                               f"pilihan: {rule['allowed']}")

        elif kind == "string":
            if not isinstance(value, str):
                return False, f"{key} harus berupa teks."
            if len(value) > rule.get("max_length", 1000):
                return False, (f"{key} terlalu panjang "
                               f"({len(value)} > {rule['max_length']}).")
            pat = rule.get("pattern")
            if pat and not re.match(pat, value):
                return False, f"{key} memuat karakter yang tidak diizinkan."

        elif kind == "int":
            try:
                num = int(value)
            except (TypeError, ValueError):
                return False, f"{key} harus berupa bilangan bulat."
            if not (rule["min"] <= num <= rule["max"]):
                return False, (f"{key} di luar batas "
                               f"[{rule['min']}, {rule['max']}].")

        elif kind == "bool":
            if not isinstance(value, bool):
                return False, f"{key} harus true/false."

        elif kind == "list":
            if not isinstance(value, (list, tuple)):
                return False, f"{key} harus berupa list."
            if len(value) > 100:
                return False, f"{key} memuat terlalu banyak item (maks 100)."

    return True, "OK"


__all__ = ["ARG_SCHEMAS", "validate_args"]