"""tests/test_needs_oauth.py — Task 1C: provider ber-OAuth -> tombol Connect.

KENAPA PENTING: Google Sheets/Gmail/Calendar/Slack TIDAK punya jalur token
manual. Kalau AI (atau UI) meminta user "menempel token", user akan menempel
sesuatu yang tidak mungkin benar. Karena itu `tools.execute_tool` mengembalikan
`{"status": "needs_oauth", ..., "connect_url": ...}` — sinyal yang bisa
dirender UI sebagai tombol Connect.

Yang DIKUNCI di sini:
  1. provider OAuth + Brankas kosong -> RETURN dict needs_oauth (bukan raise);
  2. provider MANUAL (whatsapp/telegram) tetap RAISE (form kredensial lama
     masih dipakai dan sudah dikunci tes lain);
  3. kedua pemanggil tool di `api_server.py` benar-benar meneruskan sinyal itu
     (kalau tidak, dict akan diperlakukan sebagai hasil tool biasa dan user
     hanya melihat teks mentah — regresi senyap).
  4. provider yang TIDAK punya scope OAuth TIDAK boleh dapat connect_url.

BUG FIX 2026-10-03: `gmail` dan `google_calendar` DIHAPUS dari daftar
needs_oauth di bawah.

Keduanya TIDAK punya scope OAuth: `/oauth/google/authorize` meng-hardcode
scope `auth/spreadsheets`, jadi consent screen tidak pernah meminta izin
Gmail maupun Calendar. Kalau tetap diiklankan, user menekan Connect,
menyetujui consent yang salah, melihat "Connected", lalu tool tetap gagal -
janji kosong yang lebih buruk daripada tidak menawarkan apa pun.

Konsekuensi yang disengaja: keduanya kini melempar CredentialMissingError
(ditemukan api_server.chat -> needs_credential). Test pengunci lain:
tests/test_gmail_multitenant.py + tests/test_oauth_provider_honesty.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402
import tools  # noqa: E402


def _empty_vault(monkeypatch) -> None:
    monkeypatch.setattr(db, "get_integration", lambda e, p: None)


@pytest.mark.parametrize("tool_name,provider,expected_url", [
    ("baca_google_sheets", "google_sheets", "/oauth/google/authorize"),
    ("kirim_slack_message", "slack", "/oauth/slack/authorize"),
])
def test_provider_oauth_mengembalikan_needs_oauth(monkeypatch, tool_name, provider, expected_url):
    _empty_vault(monkeypatch)
    out = tools.execute_tool(tool_name, {}, "u@k.test")
    assert isinstance(out, dict), f"{tool_name} harus MENGEMBALIKAN dict, bukan raise"
    assert out["status"] == "needs_oauth"
    assert out["provider"] == provider
    assert out["connect_url"] == expected_url
    assert out["message"], "pesan tidak boleh kosong (UI menampilkannya)"
    print(f"NEEDS_OAUTH={provider} url={out['connect_url']} return_not_raise=True")


def test_provider_manual_tetap_raise(monkeypatch):
    """Telegram/WhatsApp tidak punya OAuth → form kredensial tetap jalannya."""
    _empty_vault(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ENV_FALLBACK", "0")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    for name in ("send_whatsapp_message", "kirim_telegram_message"):
        with pytest.raises(tools.CredentialMissingError):
            tools.execute_tool(name, {}, "u@k.test")
    print("PROVIDER_MANUAL=raise_tetap (form kredensial utuh)")


def test_tanpa_koneksi_maka_tidak_ada_hasil_palsu(monkeypatch):
    """Sinyal OAuth TIDAK boleh menyamar sebagai hasil tool yang 'berhasil'."""
    _empty_vault(monkeypatch)
    out = tools.execute_tool("baca_google_sheets",
                             {"spreadsheet_id": "X", "range_data": "A1"}, "u@k.test")
    assert not isinstance(out, str), "teks 'berhasil dibaca' akan menipu model & user"
    assert "berhasil" not in str(out).lower()
    print("TIDAK_ADA_KLAIM_PALSU=ok")


def test_api_server_meneruskan_sinyal_needs_oauth():
    """Regresi senyap: dua jalur chat (gateway + Gemini langsung) harus sadar."""
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    hits = src.count('result.get("status") == "needs_oauth"')
    hits += src.count('tool_result.get("status") == "needs_oauth"')
    assert hits >= 2, f"hanya {hits} jalur yang meneruskan needs_oauth (butuh 2)"
    assert 'status": "needs_oauth" if connect_url else "needs_credential"' in src
    print(f"JALUR_MENERUSKAN_NEEDS_OAUTH={hits} (gateway + gemini_direct)")


def test_connect_url_menunjuk_endpoint_yang_benar_benar_ada():
    """URL di sinyal OAuth harus cocok dengan endpoint yang ada di api_server."""
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    for url in tools.OAUTH_CONNECT_URLS.values():
        assert f'@app.get("{url}")' in src, f"{url} tidak punya endpoint authorize"
    print("CONNECT_URL_COCOK_ENDPOINT=true count=" + str(len(set(tools.OAUTH_CONNECT_URLS.values()))))
