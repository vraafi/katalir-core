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


# ---------------------------------------------------------------------------
# BUG #1 LANJUTAN (6 Okt 2026) — jalur GEMINI LANGSUNG tidak punya gerbang.
#
# Reproduksi produksi (log deployment 85f5b190):
#   [chat/direct] tool_call name=kirim_telegram_message
#   [api_server] tool kirim_telegram_message gagal: Telegram 404
#
# Model memanggil nama NATIVE, dan `_agentic_run_direct` mengeksekusinya
# LANGSUNG lewat `tools.execute_tool` — tanpa `tool_policy_gate`. Dua cacat:
#   (1) gate hanya cocokkan nama TEKSTUAL ("TELEGRAM"), bukan native
#       ("kirim_telegram_message") -> jatuh ke ALLOW;
#   (2) jalur direct tidak memanggil gate sama sekali.
# Tes di bawah mengunci perbaikan keduanya.
# ---------------------------------------------------------------------------


def test_gate_nama_native_telegram_wajib_approval():
    """`kirim_telegram_message` harus REQUIRE_APPROVAL, bukan ALLOW."""
    from tool_policy_gate import Disposition, validate_call
    d, _ = validate_call("kirim_telegram_message", {"chat_id": "123"})
    assert d is Disposition.REQUIRE_APPROVAL, d


def test_gate_nama_native_slack_wajib_approval():
    from tool_policy_gate import Disposition, validate_call
    d, _ = validate_call("kirim_slack_message", {"channel": "#x"})
    assert d is Disposition.REQUIRE_APPROVAL, d


def test_gate_nama_native_sheets_dan_gmail_tetap_sesuai_pasangan_tekstual():
    """Nama native harus mengikuti disposisi pasangan TEKSTUAL-nya.

    `EMAIL`/`SHEETS` tekstual = ALLOW (kontrak lama, dikunci
    `test_tool_injection.py`), jadi nama native-nya pun ALLOW. Yang penting
    adalah TIDAK ada nama native yang jatuh ke DENY karena lupa didaftarkan
    di `NATIVE_TOOLS`.
    """
    from tool_policy_gate import Disposition, validate_call
    assert validate_call("write_sheets_dynamic", {})[0] is Disposition.ALLOW
    assert validate_call("trigger_gmail_imap", {})[0] is Disposition.ALLOW
    assert validate_call("kirim_email_gmail", {})[0] is Disposition.ALLOW


def test_gate_semua_tool_native_terdaftar_tidak_ada_deny_karena_lupa():
    """Setiap deklarasi native di `tools.py` harus dikenali gate.

    Regresi nyata: `NATIVE_TOOLS` hanya memuat 9 dari 13 deklarasi, sehingga
    `send_whatsapp_message` dkk. akan DENY ("tidak ada di allowlist") begitu
    gate benar-benar dijalankan di jalur direct.
    """
    import tools as T
    from tool_policy_gate import Disposition, validate_call
    names = []
    for d in T.TOOL_DECLARATIONS:
        for f in (getattr(d, "function_declarations", None) or []):
            names.append(f.name)
    assert len(names) >= 13, names
    for n in names:
        disp, reason = validate_call(n, {})
        assert disp is not Disposition.DENY, (n, reason)


def test_gate_tesktual_dan_native_konsisten():
    """Bentuk tekstual dan native harus memberi keputusan yang SAMA."""
    from tool_policy_gate import Disposition, validate_call
    pairs = [("TELEGRAM", "kirim_telegram_message"),
             ("SLACK", "kirim_slack_message")]
    for textual, native in pairs:
        a, _ = validate_call(textual, {"chat_id": "1"})
        b, _ = validate_call(native, {"chat_id": "1"})
        assert a is Disposition.REQUIRE_APPROVAL, (textual, a)
        assert b is Disposition.REQUIRE_APPROVAL, (native, b)


def test_gate_tool_tidak_terkait_tetap_allow():
    """Perbaikan tidak boleh melebarkan izin tool yang bukan pengirim data."""
    from tool_policy_gate import Disposition, validate_call
    for t in ("check_credential", "generate_workflow_json", "web_search",
              "baca_google_sheets", "VAULT"):
        d, _ = validate_call(t, {})
        assert d is Disposition.ALLOW, (t, d)


def test_direct_policy_gate_approval_dengan_kredensial():
    """Jalur direct: kredensial ada -> requires_approval + token."""
    import api_server

    with patch("credential_forms.check_credential",
               lambda p, e: {"status": "ok", "provider": p}):
        out = api_server._direct_policy_gate(
            "kirim_telegram_message", {"chat_id": "123", "pesan": "halo"},
            USER, "kirim ke telegram chat 123 pesan halo")

    assert out is not None, "gate harus memblokir eksekusi langsung"
    assert out.get("status") == "requires_approval", out
    assert out.get("approval_token"), out
    assert out.get("tool") == "kirim_telegram_message", out


def test_direct_policy_gate_credential_dulu_bukan_approval():
    """Kredensial belum ada -> CredentialMissingError, BUKAN approval.

    Sengaja MELEMPAR (bukan mengembalikan dict): endpoint menangkapnya dan
    menyusun kartu form lengkap (fields/display_name/resume_token). Kalau
    dikembalikan sebagai dict parsial, form tampil kosong.
    """
    import api_server
    from tools import CredentialMissingError

    with patch("credential_forms.check_credential",
               lambda p, e: {"status": "missing", "provider": p}):
        try:
            api_server._direct_policy_gate(
                "kirim_telegram_message", {"chat_id": "123", "pesan": "halo"},
                USER, "kirim ke telegram chat 123 pesan halo")
            raised = False
        except CredentialMissingError as exc:
            raised = True
            assert exc.provider_name == "telegram", exc.provider_name

    assert raised, "harus melempar CredentialMissingError"


def test_direct_policy_gate_allow_tool_aman():
    """Tool yang tidak mengirim data ke luar tidak diblokir."""
    import api_server
    out = api_server._direct_policy_gate(
        "generate_workflow_json", {}, USER, "buat workflow")
    assert out is None, out


def test_direct_policy_gate_deny_pola_berbahaya():
    """Pola berbahaya tetap DENY di jalur direct."""
    import api_server
    out = api_server._direct_policy_gate(
        "http_request", {"url": "http://x/../../etc/passwd"}, USER, "ambil")
    assert out is not None, out
    assert out.get("status") == "denied", out


def test_native_tool_provider_memeta_benar():
    import api_server
    assert api_server._native_tool_provider("kirim_telegram_message") == "telegram"
    assert api_server._native_tool_provider("kirim_slack_message") == "slack"
    assert api_server._native_tool_provider("trigger_gmail_imap") == "gmail_imap"
    assert api_server._native_tool_provider("write_sheets_dynamic") == "google_sheets"
    assert api_server._native_tool_provider("generate_workflow_json") == ""


# ---------------------------------------------------------------------------
# BUG #1 lanjutan (2) — DENY palsu pada spec workflow (jalur direct).
#
# Saat gate dipasang di jalur direct, spec workflow yang SAH memuat backtick/
# markdown di nilai `pesan` jatuh ke DENY ("pola terlarang `...`") — padahal
# `generate_workflow_json` hanya MENYIMPAN data, tidak mengeksekusi shell.
# ---------------------------------------------------------------------------


def test_workflow_spec_dengan_backtick_tidak_deny():
    """Backtick di dalam nilai `pesan` adalah isi sah, bukan injeksi."""
    from tool_policy_gate import Disposition, validate_call
    spec = '{"nodes":[{"config":{"pesan":"kirim `laporan` harian"}}]}'
    d, why = validate_call("generate_workflow_json", {"spec": spec})
    assert d is Disposition.ALLOW, why


def test_workflow_spec_traversal_tetap_deny():
    """Exemption data-only TIDAK boleh memaafkan path traversal."""
    from tool_policy_gate import Disposition, validate_call
    d, why = validate_call("generate_workflow_json",
                           {"spec": '{"u":"../../etc/passwd"}'})
    assert d is Disposition.DENY, why


def test_tool_pengirim_tetap_deny_backtick():
    """Alat yang MENGIRIM data tetap kena aturan backtick (bukan data-only)."""
    from tool_policy_gate import Disposition, validate_call
    d, _ = validate_call("kirim_telegram_message",
                         {"chat_id": "1", "pesan": "x `whoami`"})
    # Disposisi bisa DENY (pola) atau REQUIRE_APPROVAL; yang penting BUKAN ALLOW.
    assert d is not Disposition.ALLOW, d


def test_http_request_backtick_tetap_deny():
    from tool_policy_gate import Disposition, validate_call
    d, _ = validate_call("http_request", {"url": "x `whoami`"})
    assert d is Disposition.DENY, d


# ---------------------------------------------------------------------------
# BUG #1 lanjutan (3) — JALUR PERSETUJUAN BUNTU (defect #3, 6 Okt 2026).
#
# Setelah user menekan "Setujui", `/chat/approve` memanggil
# `execute_textual_tool(..., approved=True)`. Dua cacat ditemukan lewat
# reproduksi nyata:
#
#   (a) Token dari jalur Gemini-langsung memakai nama NATIVE
#       (`kirim_telegram_message`), sedangkan `HANDLERS` hanya mengenal nama
#       kanonik (`TELEGRAM`) -> "Tool tidak dikenal", persetujuan MUSTAHIL.
#   (b) Saat `approved=True`, seluruh cabang REQUIRE_APPROVAL dilewati -
#       termasuk cek kredensial. Akibatnya handler dipanggil tanpa kredensial,
#       `CredentialMissingError` naik TAK TERTANGKAP -> HTTP 500.
#
# Perbaikan: normalisasi nama native->kanonik SEBELUM lookup handler, dan cek
# kredensial dijalankan LEBIH DULU tanpa syarat `approved` (hanya penerbitan
# token yang dilewati saat approved=True).
# ---------------------------------------------------------------------------


def test_native_name_dinormalkan_ke_kanonik():
    """Nama native harus lolos lookup handler (bukan 'Tool tidak dikenal')."""
    from textual_tool_handlers import NATIVE_TO_TEXTUAL
    assert NATIVE_TO_TEXTUAL.get("KIRIM_TELEGRAM_MESSAGE") == "TELEGRAM"
    assert NATIVE_TO_TEXTUAL.get("KIRIM_SLACK_MESSAGE") == "SLACK"
    assert NATIVE_TO_TEXTUAL.get("KIRIM_EMAIL_GMAIL") == "EMAIL"
    assert NATIVE_TO_TEXTUAL.get("TRIGGER_GMAIL_IMAP") == "EMAIL"
    assert NATIVE_TO_TEXTUAL.get("WRITE_SHEETS_DYNAMIC") == "SHEETS"


def test_approved_true_tanpa_kredensial_tidak_meledak(monkeypatch):
    """approved=True + kredensial hilang -> requires_credential, BUKAN 500."""
    import textual_tool_handlers as th
    monkeypatch.setattr(th, "_missing_provider", lambda tool, email: "telegram")
    out = th.execute_textual_tool(
        {"tool": "kirim_telegram_message",
         "args": {"chat_id": "123", "pesan": "halo"}},
        USER, approved=True)
    assert out.get("status") == "requires_credential", out
    assert out.get("provider") == "telegram", out


def test_approved_false_tanpa_kredensial_juga_requires_credential(monkeypatch):
    """approved=False tetap minta kredensial lebih dulu (urutan lama dijaga)."""
    import textual_tool_handlers as th
    monkeypatch.setattr(th, "_missing_provider", lambda tool, email: "telegram")
    out = th.execute_textual_tool(
        {"tool": "TELEGRAM", "args": {"chat_id": "123", "pesan": "halo"}},
        USER, approved=False)
    assert out.get("status") == "requires_credential", out


def test_approved_true_dengan_kredensial_benar_benar_eksekusi(monkeypatch):
    """Jalur bahagia: approved=True + kredensial ada -> handler dipanggil."""
    import textual_tool_handlers as th
    monkeypatch.setattr(th, "_missing_provider", lambda tool, email: "")
    sent = {}

    def fake_handler(args, user_email):
        sent["args"] = args
        sent["email"] = user_email
        return {"status": "success", "message": "terkirim"}

    monkeypatch.setitem(th.HANDLERS, "TELEGRAM", fake_handler)
    out = th.execute_textual_tool(
        {"tool": "kirim_telegram_message",
         "args": {"chat_id": "123", "pesan": "halo"}},
        USER, approved=True)
    assert out.get("status") == "success", out
    assert sent["args"] == {"chat_id": "123", "pesan": "halo"}, sent
    assert sent["email"] == USER, sent


def test_approved_true_tidak_menerbitkan_token_lagi(monkeypatch):
    """Saat approved=True gate TIDAK boleh mengembalikan requires_approval."""
    import textual_tool_handlers as th
    monkeypatch.setattr(th, "_missing_provider", lambda tool, email: "")
    monkeypatch.setitem(th.HANDLERS, "SLACK",
                        lambda a, e: {"status": "success"})
    out = th.execute_textual_tool(
        {"tool": "KIRIM_SLACK_MESSAGE",
         "args": {"channel": "#umum", "pesan": "halo"}},
        USER, approved=True)
    assert out.get("status") != "requires_approval", out
    assert "approval_token" not in out, out


def test_deny_tetap_deny_walau_approved_true():
    """Kontrol keamanan: DENY tidak boleh dilunakkan oleh approved=True."""
    from tool_policy_gate import Disposition, validate_call
    d, _ = validate_call("kirim_telegram_message",
                         {"chat_id": "1", "pesan": "x /etc/passwd"})
    assert d is Disposition.DENY, d


def test_approve_endpoint_normalkan_nama_native_sebelum_validasi(monkeypatch):
    """Defect #4 (6 Okt 2026, bukti live): /chat/approve memvalidasi ulang
    argumen dengan nama ASLI dari token (`KIRIM_TELEGRAM_MESSAGE`),
    sedangkan `argument_validator` hanya punya skema kanonik -> HTTP 400
    "tidak punya skema argumen" dan persetujuan buntu lagi.

    Uji ini memanggil `approve_tool_call` sungguhan dengan payload token
    native; handler kanonik harus menerima eksekusi.
    """
    import api_server
    import approval_flow
    import textual_tool_handlers as th

    monkeypatch.setattr(
        api_server.security, "get_current_user",
        lambda auth: {"email": USER})

    monkeypatch.setattr(
        approval_flow, "verify_approval_token",
        lambda tok, email: {"tool": "KIRIM_TELEGRAM_MESSAGE",
                            "args": {"chat_id": "123", "pesan": "halo"}})

    # Kredensial anggap ada; handler palsu menangkap eksekusi kanonik.
    monkeypatch.setattr(th, "_missing_provider", lambda tool, email: "")
    seen = {}
    monkeypatch.setitem(
        th.HANDLERS, "TELEGRAM",
        lambda a, e: (seen.update(tool=a, email=e) or
                      {"status": "success", "message": "terkirim"}))

    req = api_server.ApproveRequest(approval_token="x", decision="approve")
    out = api_server.approve_tool_call(req, authorization="Bearer dummy")
    assert out.get("status") == "executed", out
    assert out.get("tool") == "TELEGRAM", out
    assert seen.get("tool") == {"chat_id": "123", "pesan": "halo"}, seen


def test_approve_endpoint_tetap_tolak_argumen_invalid(monkeypatch):
    """Normalisasi tidak boleh melemahkan validasi ulang argumen."""
    import api_server
    import approval_flow
    import pytest as _pytest

    monkeypatch.setattr(
        api_server.security, "get_current_user",
        lambda auth: {"email": USER})
    monkeypatch.setattr(
        approval_flow, "verify_approval_token",
        lambda tok, email: {"tool": "KIRIM_TELEGRAM_MESSAGE",
                            "args": {"chat_id": "123",
                                     "pesan": "x" * 99999}})

    req = api_server.ApproveRequest(approval_token="x", decision="approve")
    with _pytest.raises(Exception) as ei:
        api_server.approve_tool_call(req, authorization="Bearer dummy")
    assert "Argumen tidak lagi valid" in str(ei.value), ei.value
