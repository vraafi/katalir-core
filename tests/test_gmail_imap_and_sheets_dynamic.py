"""tests/test_gmail_imap_and_sheets_dynamic.py — trigger Gmail (IMAP) + Sheets dinamis.

Semua test OFFLINE: tidak ada koneksi jaringan, tidak ada kredensial asli.
App password adalah kredensial nyata, jadi TIDAK PERNAH di-hardcode di sini
nilai yang terlihat seperti kredensial produksi.
"""

from __future__ import annotations

import json
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gmail_imap as gi  # noqa: E402
import sheets_dynamic as sd  # noqa: E402


# --------------------------------------------------------------------------
# gmail_imap — normalisasi & parsing (tanpa jaringan)
# --------------------------------------------------------------------------
def test_app_password_dengan_spasi_dinormalisasi():
    """Google menampilkan App Password dengan spasi; IMAP butuh tanpa spasi."""
    spaced = "abcd efgh ijkl mnop"
    assert gi.normalize_app_password(spaced) == "abcdefghijklmnop"
    assert len(gi.normalize_app_password(spaced)) == 16
    assert gi.normalize_app_password(None) == ""


def test_parse_email_polos():
    raw = (
        b"From: sender@example.com\r\n"
        b"To: user@example.com\r\n"
        b"Subject: Laporan Inventory cogniz\r\n"
        b"Date: Fri, 3 Oct 2026 10:00:00 +0700\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Total barang: 42\r\n"
    )
    m = gi.parse_message(raw, uid="101")
    assert m["id"] == "101"
    assert "Inventory" in m["subject"]
    assert m["from"] == "sender@example.com"
    assert "Total barang: 42" in m["body"]
    assert m["has_body"] is True


def test_parse_email_multipart_tidak_ganda():
    raw = (
        b"From: s@example.com\r\nSubject: Multipart\r\n"
        b'Content-Type: multipart/alternative; boundary="X"\r\n\r\n'
        b"--X\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Versi teks\r\n"
        b"--X\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>Versi html</p>\r\n"
        b"--X--\r\n"
    )
    m = gi.parse_message(raw, uid="7")
    assert "Versi teks" in m["body"]
    assert "Versi html" in m["body_html"]
    assert "<p>" not in m["body"]


def test_attachment_tidak_dianggap_body():
    """Lampiran adalah penyebab umum 'email terbaca tapi isinya kosong'."""
    raw = (
        b"From: s@example.com\r\nSubject: Ada lampiran\r\n"
        b'Content-Type: multipart/mixed; boundary="Y"\r\n\r\n'
        b"--Y\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Isi email\r\n"
        b"--Y\r\nContent-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename=\"x.pdf\"\r\n\r\n"
        b"%PDF-1.4 bogus\r\n"
        b"--Y--\r\n"
    )
    m = gi.parse_message(raw, uid="9")
    assert "Isi email" in m["body"]
    assert "%PDF" not in m["body"]
    assert "%PDF" not in m["body_html"]


def test_login_gagal_tidak_membocorkan_password():
    try:
        gi.trigger_gmail_imap("bukan-email", "abcdefghijklmnop")
    except gi.GmailImapError as exc:
        assert "abcdefghijklmnop" not in str(exc)
    else:
        raise AssertionError("alamat invalid harus raising GmailImapError")


def test_app_password_kosong_ditolak_sebelum_jaringan():
    for addr, pw in (("a@b.com", ""), ("a@b.com", "   ")):
        try:
            gi.trigger_gmail_imap(addr, pw)
        except gi.GmailImapError as exc:
            assert "App Password" in str(exc)
        else:
            raise AssertionError("password kosong harus ditolak")


# --------------------------------------------------------------------------
# vault helpers (tanpa DB sungguhan -> monkeypatch)
# --------------------------------------------------------------------------
def test_simpan_kredensial_gmail_terenkripsi(monkeypatch):
    """App password harus lewat encrypt_key, TIDAK pernah plaintext ke DB."""
    import tools

    saved = {}

    def fake_encrypt(plain: str) -> str:
        saved["plain_seen_by_encryptor"] = plain
        return "CIPHER-TEXT"

    monkeypatch.setattr("vault_security.encrypt_key", fake_encrypt)
    monkeypatch.setattr("database.vault_save",
                        lambda e, p, c: saved.__setitem__("row", (e, p, c)) or True)
    ok = tools.save_gmail_imap_credential(
        "u@example.com", "u@gmail.com", "abcd efgh ijkl mnop")
    assert ok is True
    assert saved["row"][1] == "gmail_imap"
    assert saved["row"][2] == "CIPHER-TEXT"
    # Yang dienkripsi adalah JSON multi-field. Nama key PERSIS sama dengan
    # nama field di `providers.credential_schemas` (sumber kebenaran).
    payload = json.loads(saved["plain_seen_by_encryptor"])
    assert payload["app_password"] == "abcdefghijklmnop"  # ternormalisasi
    assert payload["email"] == "u@gmail.com"


def test_kredensial_belum_ada_arahkan_ke_ui(monkeypatch):
    import tools

    monkeypatch.setattr("database.vault_get", lambda e, p: None)
    try:
        tools.gmail_imap_credential("u@example.com")
    except tools.CredentialMissingError as exc:
        assert "gmail_imap" in str(exc)
    else:
        raise AssertionError("vault kosong harus jadi CredentialMissingError")


def test_tool_tidak_pernah_membocorkan_password(monkeypatch):
    """Jawaban tool tidak boleh memuat app password."""
    import tools

    monkeypatch.setattr(
        "gmail_imap.trigger_gmail_imap",
        lambda **kw: {"status": "ok", "count": 1, "emails": [{"subject": "x"}]},
    )
    out = tools.trigger_gmail_imap_tool(
        email_address="u@gmail.com", app_password="abcdefghijklmnop",
        email="u@example.com")
    assert "abcdefghijklmnop" not in out
    assert json.loads(out)["status"] == "ok"


def test_kredensial_dipakai_dari_vault_bila_kosong(monkeypatch):
    import tools

    monkeypatch.setattr(
        "tools.gmail_imap_credential",
        lambda e: {"email_address": "v@gmail.com", "app_password": "zzzzzzzzzzzzzzzz"},
    )
    seen = {}

    def fake_poll(**kw):
        seen.update(kw)
        return {"status": "ok", "count": 0, "emails": []}

    monkeypatch.setattr("gmail_imap.trigger_gmail_imap", fake_poll)
    tools.trigger_gmail_imap_tool(email_address="", email="u@example.com")
    assert seen["email_address"] == "v@gmail.com"
    assert seen["app_password"] == "zzzzzzzzzzzzzzzz"

# --------------------------------------------------------------------------
# sheets_dynamic - semantic header matching
# --------------------------------------------------------------------------
def test_normalize_header_buang_aksen_dan_spasi():
    assert sd.normalize_header("Jumlah Barang") == "jumlah_barang"
    assert sd.normalize_header("  Qty  ") == "qty"
    assert sd.normalize_header("Nomor!!") == "nomor"


def test_sheet_kosong_header_dari_kunci_data():
    matched, new = sd.semantic_match_headers({"nama": "Kopi", "qty": 10}, [])
    assert matched == {}
    assert sorted(new) == ["nama", "qty"]


def test_kunci_cocok_lintas_bahasa():
    """'qty' harus map ke header 'jumlah' - inilah gunanya semantic match."""
    matched, new = sd.semantic_match_headers(
        {"qty": 10, "harga": 25000}, ["jumlah", "harga"])
    assert matched == {"jumlah": 10, "harga": 25000}
    assert new == []


def test_kunci_baru_masuk_kolom_baru():
    matched, new = sd.semantic_match_headers(
        {"jumlah": 3, "keterangan": "baru"}, ["jumlah"])
    assert matched == {"jumlah": 3}
    assert new == ["keterangan"]


def test_duplikat_tidak_menimpa_kolom_yang_sudah_terisi():
    """Kunci yang cocok PERSIS menang; kunci sinonim lain jadi kolom baru.

    `jumlah` identik dengan header `jumlah`, jadi itu yang mengisi kolom.
    `qty` (sinonim) tidak boleh merebut kolom yang sudah terisi - kalau
    dipaksa, dia jadi kolom baru.
    """
    matched, new = sd.semantic_match_headers({"qty": 1, "jumlah": 2}, ["jumlah"])
    assert matched == {"jumlah": 2}
    assert new == ["qty"]


def test_llm_mapper_hanya_dipakai_saat_gagal_deterministik():
    """LLM mapper boleh membantu, tapi tidak boleh menimpa pasangan yakin."""
    calls = []

    def mapper(data, headers):
        calls.append((dict(data), list(headers)))
        return {"mystery": "jumlah"}

    matched, new = sd.semantic_match_headers(
        {"qty": 5, "mystery": "x"}, ["jumlah"], llm_mapper=mapper)
    assert calls and "qty" not in calls[0][0]
    assert matched["jumlah"] == 5
    assert "mystery" in new


def test_llm_mapper_error_tidak_menjatuhkan_semua():
    def boom(data, headers):
        raise RuntimeError("LLM down")

    matched, new = sd.semantic_match_headers(
        {"qty": 5, "aneh": 1}, ["jumlah"], llm_mapper=boom)
    assert matched == {"jumlah": 5}
    assert new == ["aneh"]


# --------------------------------------------------------------------------
# Registrasi tool + CASA guard
# --------------------------------------------------------------------------
def test_kedua_tool_terdaftar_di_dua_format_skema():
    import tools

    gemini = [d.name for t in tools.TOOL_DECLARATIONS
              for d in (getattr(t, "function_declarations", None) or [])]
    openai = [s["function"]["name"] for s in tools.TOOL_SCHEMAS_OPENAI]
    for n in ("trigger_gmail_imap", "write_sheets_dynamic"):
        assert n in gemini, f"{n} hilang dari skema Gemini"
        assert n in openai, f"{n} hilang dari skema OpenAI/gateway"


def test_tidak_ada_scope_gmail_restricted():
    """CASA guard: scope Gmail RESTRICTED tidak boleh diminta sama sekali.

    Dicek di tempat scope benar-benar dideklarasikan (`oauth_google`), bukan di
    teks deskripsi tool - deskripsi boleh MENJELASKAN kenapa kita tidak
    memakainya.
    """
    import oauth_google

    scopes = " ".join(
        str(getattr(oauth_google, attr, "") or "")
        for attr in dir(oauth_google)
        if "SCOPE" in attr.upper()
    )
    assert "gmail.readonly" not in scopes
    assert "gmail.modify" not in scopes
    assert "mail.google.com" not in scopes


def test_tool_gmail_murni_imap_tanpa_token_oauth():
    """Tool Gmail tidak boleh punya field access_token/refresh_token."""
    import tools

    for t in tools.TOOL_DECLARATIONS:
        for d in (getattr(t, "function_declarations", None) or []):
            if d.name != "trigger_gmail_imap":
                continue
            props = set(tools._json_schema(d.parameters).get("properties", {}))
            assert "access_token" not in props
            assert "refresh_token" not in props
            assert "app_password" in props


# --------------------------------------------------------------------------
# Skenario end-to-end write_sheets_dynamic (client Sheets tiruan)
# --------------------------------------------------------------------------
class _FakeSheetsClient:
    """Pencermin API Sheets secukupnya untuk 3 skenario header."""

    def __init__(self, existing_headers):
        self.headers = list(existing_headers)
        self.put_calls = []
        self.appended = []

    def get(self, url, **kw):
        class R:
            status_code = 200

            def json(_s):
                return {"values": ([self.headers] if self.headers else [])}
        return R()

    def put(self, url, **kw):
        vals = kw.get("json", {}).get("values", [[]])[0]
        self.headers = list(vals)
        self.put_calls.append(list(vals))

        class R:
            status_code = 200

            def json(_s):
                return {"updatedRange": "A1"}
        return R()

    def post(self, url, **kw):
        vals = kw.get("json", {}).get("values", [[]])[0]
        self.appended.append(list(vals))

        class R:
            status_code = 200

            def json(_s):
                return {"updates": {"updatedRange": "inventory!A2"}}
        return R()


@pytest.fixture(autouse=True)
def _fake_oauth(monkeypatch):
    import oauth_google
    monkeypatch.setattr(oauth_google, "access_token", lambda e: "FAKE-TOKEN")


def test_skenario_1_sheet_kosong_header_dibuat():
    from sheets_dynamic import write_sheets_dynamic

    c = _FakeSheetsClient([])
    r = write_sheets_dynamic("SID", "inventory",
                             {"nama": "Kopi", "qty": 10, "harga": 25000},
                             "u@example.com", client=c)
    assert r["headers"] == ["nama", "qty", "harga"]
    assert c.headers == ["nama", "qty", "harga"]      # header ditulis dulu
    assert c.appended == [["Kopi", 10, 25000]]
    assert r["new_columns_added"] == ["nama", "qty", "harga"]


def test_skenario_2_header_beda_bahasa_dipetakan_semantik():
    """Sheet berheader Indonesia, data model pakai Inggris."""
    from sheets_dynamic import write_sheets_dynamic

    c = _FakeSheetsClient(["Nama Barang", "Jumlah", "Harga"])
    r = write_sheets_dynamic("SID", "inventory",
                             {"name": "Kopi", "qty": 10, "harga": 25000},
                             "u@example.com", client=c)
    # Tidak ada kolom baru: semua kunci punya pasangan header.
    assert r["new_columns_added"] == []
    assert r["headers"] == ["Nama Barang", "Jumlah", "Harga"]
    assert c.appended == [["Kopi", 10, 25000]]


def test_skenario_3_kunci_baru_menambah_kolom():
    from sheets_dynamic import write_sheets_dynamic

    c = _FakeSheetsClient(["nama", "qty"])
    r = write_sheets_dynamic("SID", "inventory",
                             {"nama": "Teh", "qty": 3, "supplier": "PT A"},
                             "u@example.com", client=c)
    assert r["new_columns_added"] == ["supplier"]
    assert r["headers"] == ["nama", "qty", "supplier"]
    # Kolom lama tidak ditulis ulang, kolom baru ditambahkan di kanan.
    assert c.headers == ["nama", "qty", "supplier"]
    assert c.appended == [["Teh", 3, "PT A"]]


def test_data_kosong_ditolak():
    from sheets_dynamic import write_sheets_dynamic

    c = _FakeSheetsClient(["a"])
    try:
        write_sheets_dynamic("SID", "inventory", {}, "u@example.com", client=c)
    except ValueError as exc:
        assert "data" in str(exc)
    else:
        raise AssertionError("data kosong harus ditolak")
    assert c.appended == []


# ---------------------------------------------------------------------------
# BUG FIX 2026-10-04: field `sender` tidak pernah ada di parse_message.
#
# parse_message hanya mengembalikan key "from" (header mentah seperti
# "Nama <surel@x>"). Pemanggil yang membaca m["sender"] selalu dapat None.
# Sekarang ada `sender` terstruktur {"name", "email"} hasil parseaddr.
# ---------------------------------------------------------------------------


def _raw(from_header: bytes) -> bytes:
    return from_header + b"Subject: Uji\r\n\r\nisi\r\n"


def test_sender_dipisah_jadi_name_dan_email():
    from gmail_imap import parse_message

    m = parse_message(_raw(b"From: Budi <budi@contoh.co.id>\r\n"), uid="1")
    assert m["sender"] == {"name": "Budi", "email": "budi@contoh.co.id"}


def test_sender_nama_terenkode_rfc2047_didekode():
    from gmail_imap import parse_message

    # Header harus dib-built dari base64 UTF-8 yang BENAR. Fixture sebelumnya
    # memakai base64 byte Latin-1 yang dilabeli utf-8, jadi tidak bisa didekode
    # dan karakter non-ASCII-nya jadi replacement char.
    import base64

    name = "Jos\u00e9 Wahari"
    b64 = base64.b64encode(name.encode("utf-8")).decode()
    header = f"From: =?utf-8?B?{b64}?= <andi@contoh.co.id>\r\n".encode()
    m = parse_message(_raw(header), uid="1")
    assert m["sender"]["email"] == "andi@contoh.co.id"
    assert m["sender"]["name"] == name


def test_sender_hanya_email_tanpa_nama():
    from gmail_imap import parse_message

    m = parse_message(_raw(b"From: sari@contoh.co.id\r\n"), uid="1")
    assert m["sender"] == {"name": "", "email": "sari@contoh.co.id"}


def test_sender_kosong_bila_header_tidak_ada():
    from gmail_imap import parse_message

    m = parse_message(b"Subject: Uji\r\n\r\nisi\r\n", uid="1")
    assert m["sender"] == {"name": "", "email": ""}


def test_sender_rusak_tidak_melempar():
    from gmail_imap import parse_message

    m = parse_message(_raw(b"From: <<<rusak\r\n"), uid="1")
    assert isinstance(m["sender"], dict)


def test_key_from_utuh_tetap_ada_untuk_kompatibilitas():
    """Field lama `from` tidak boleh hilang - pemanggil lama bergantung."""
    from gmail_imap import parse_message

    m = parse_message(_raw(b"From: Budi <budi@contoh.co.id>\r\n"), uid="1")
    assert "budi@contoh.co.id" in m["from"]
