"""tests/test_bug1_telegram_approval.py — regresi Bug #1 (6 Okt 2026).

LAPORAN BUG
-----------
Pengguna menulis prompt seperti "kirim ke telegram chat 123 pesan halo".
Kredensial Telegram SUDAH tersimpan di vault. Yang diharapkan: kartu
PERSETUJUAN (requires_approval + approval_token). Yang terjadi: tidak ada
kartu persetujuan sama sekali.

AKAR MASALAH (ditemukan lewat reproduksi rantai nyata)
------------------------------------------------------
Model sering memakai nama field umum untuk isi pesan - `text`, `message`,
`msg` - bukan `pesan` yang ada di skema. Rantai lama:

  1. `textual_tool_parser.parse_textual_tools` MEMBUANG field yang tidak
     ada di ALLOWED_KEYS secara diam-diam. Jadi `{chat_id, text}` menjadi
     `{chat_id}` - pesan hilang tanpa jejak.
  2. `argument_validator.validate_args` lalu menolak sisa field yang tidak
     dikenal -> `denied`.
  3. Pengguna melihat kartu ERROR, bukan kartu persetujuan.

PERBAIKAN
---------
  a. Parser tidak lagi membuang field; seluruh `kv` diteruskan.
  b. `argument_validator` memetakan alias (`text`->`pesan`, dll.) ke nama
     kanonik SEBELUM validasi. Nilai tetap divalidasi aturan kanonik
     (max_length/pattern/enum) - izin tidak melebar.

Tes ini mengunci keduanya supaya regresi tidak datang lagi.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from argument_validator import (  # noqa: E402
    ARG_ALIASES,
    normalize_aliases,
    validate_args,
)
from textual_tool_parser import parse_textual_tools  # noqa: E402

USER = "user@example.test"
MSG = "kirim ke telegram chat 123 pesan halo"


# ---------------------------------------------------------------- parser


def test_parser_tidak_membuang_field_tak_dikenal():
    """`text` harus tetap ada di args (dulu dibuang diam-diam)."""
    calls = parse_textual_tools('[TELEGRAM: chat_id=123 text="halo"]')
    assert len(calls) == 1, calls
    args = calls[0]["args"]
    assert args == {"chat_id": "123", "text": "halo"}, args


def test_parser_field_kanonik_tetap_utuh():
    calls = parse_textual_tools('[TELEGRAM: chat_id=123 pesan="halo"]')
    assert calls[0]["args"] == {"chat_id": "123", "pesan": "halo"}


# --------------------------------------------------------------- aliases


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"chat_id": "1", "text": "hi"}, {"chat_id": "1", "pesan": "hi"}),
        ({"chat_id": "1", "message": "hi"}, {"chat_id": "1", "pesan": "hi"}),
        ({"chat_id": "1", "msg": "hi"}, {"chat_id": "1", "pesan": "hi"}),
        ({"to": "1", "pesan": "hi"}, {"chat_id": "1", "pesan": "hi"}),
        ({"chat": "1", "body": "hi"}, {"chat_id": "1", "pesan": "hi"}),
    ],
)
def test_alias_telegram_dipetakan(raw, expected):
    assert normalize_aliases("TELEGRAM", raw) == expected


def test_nama_kanonik_menang_atas_alias():
    """Bila keduanya ada, `pesan` tidak boleh ditimpa `text`."""
    out = normalize_aliases("TELEGRAM", {"pesan": "asli", "text": "lain"})
    assert out == {"pesan": "asli"}


def test_alias_tidak_melebarkan_izin():
    """Setelah dipetakan, aturan kanonik tetap berlaku (max_length)."""
    ok, reason = validate_args("TELEGRAM", {"chat_id": "1", "text": "a" * 4001})
    assert ok is False, reason
    assert "pesan" in reason  # divalidasi sebagai `pesan`, bukan `text`


def test_alias_bukan_jalan_bebas_untuk_field_asing():
    """Field yang benar-benar tidak dikenal tetap DITOLAK."""
    ok, reason = validate_args("TELEGRAM", {"chat_id": "1", "pesan": "hi",
                                            "rm_rf": "/"})
    assert ok is False, reason
    assert "rm_rf" in reason


def test_alias_valid_lolos():
    ok, reason = validate_args("TELEGRAM", {"chat_id": "123", "text": "halo"})
    assert ok is True, reason
    assert reason == "OK"


def test_alias_slack():
    out = normalize_aliases("SLACK", {"channel": "#umum", "message": "hi"})
    assert out == {"channel": "#umum", "pesan": "hi"}


def test_alias_email():
    out = normalize_aliases("EMAIL", {"subject": "Laporan", "limit": 5})
    assert out == {"subjek": "Laporan", "max": 5}


def test_alias_vault():
    out = normalize_aliases("VAULT", {"service": "telegram"})
    assert out == {"provider": "telegram"}


def test_tool_tanpa_alias_tidak_berubah():
    """Alat di luar tabel alias harus lewat apa adanya."""
    assert normalize_aliases("WORKFLOW", {"name": "x"}) == {"name": "x"}
    assert normalize_aliases("TIDAK_ADA", {"a": 1}) == {"a": 1}


def test_semua_target_alias_ada_di_skema():
    """Alias yang menunjuk field tidak-ada = bug; kunci di sini."""
    from argument_validator import ARG_SCHEMAS

    for tool, mapping in ARG_ALIASES.items():
        schema = ARG_SCHEMAS.get(tool)
        assert schema is not None, f"{tool} punya alias tapi tanpa skema"
        for alias, canonical in mapping.items():
            assert canonical in schema, f"{tool}: alias '{alias}' -> '{canonical}' tanpa field"


# ------------------------------------------------------- rantai end-to-end


def _run_chain(args, *, has_credential):
    from textual_tool_handlers import execute_textual_tool

    status = "ok" if has_credential else "missing"

    def fake_check(provider, email):
        return {"status": status, "provider": provider}

    with patch("credential_forms.check_credential", fake_check):
        return execute_textual_tool({"tool": "TELEGRAM", "args": args},
                                    USER, user_message=MSG)


def test_kredensial_ada_menghasilkan_approval():
    """Kasus yang dilaporkan: harus approval, bukan error."""
    res = _run_chain({"chat_id": "123", "pesan": "halo"}, has_credential=True)
    assert res.get("status") == "requires_approval", res
    assert res.get("approval_token"), res


def test_kredensial_belum_ada_menghasilkan_form():
    res = _run_chain({"chat_id": "123", "pesan": "halo"}, has_credential=False)
    assert res.get("status") == "requires_credential", res
    assert res.get("provider") == "telegram", res


def test_field_text_menghasilkan_approval_setelah_fix():
    """Kasus C yang dulu GAGAL — sekarang harus approval."""
    res = _run_chain({"chat_id": "123", "text": "halo"}, has_credential=True)
    assert res.get("status") == "requires_approval", res
    assert res.get("approval_token"), res


def test_field_message_juga_menghasilkan_approval():
    res = _run_chain({"chat_id": "123", "message": "halo"}, has_credential=True)
    assert res.get("status") == "requires_approval", res
    assert res.get("approval_token"), res
