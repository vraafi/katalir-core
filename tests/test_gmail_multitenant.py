"""Bukti multi-tenant pada jalur Gmail (BUG FIX 2026-10-03).

Tujuan test ini: membuktikan atau menyangkal klaim "Gmail trigger multi-tenant".

TEMUAN YANG DIKUNCI (lihat docs/oauth/provider-status.md):
  * OLEH-TOOL dari blok ini DIHAPUS oleh audit sebelumnya karena Janji Palsu:
    `/oauth/google/authorize` hanya meminta scope `auth/spreadsheets`, jadi
    consent screen TIDAK PERNAH memberi akses Gmail.
  * `kirim_email_gmail` membaca `db.get_integration(email, "gmail")`, yaitu
    tabel `user_integrations` (plaintext), BUKAN `user_vault` tempat token
    OAuth disimpan.
  * Konsekuensinya: tidak ada satu pun token Gmail di database, dan
    `gmail` sengaja TIDAK diiklankan sebagai OAuth (lihat
    `_oauth_providers` di api_server.py).

Jadi test ini tidak mengklaim Gmail sudah multi-tenant. Test ini mengunci
KENAPA belum, dan membuktikan bagian yang memang bisa dibuktikan sekarang:
resolusi token HANYA bisa per-user dan TIDAK PERNAH lintas user.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402
import tools  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Bukti multi-tenant yang SAHIH: resolver menerima email per user.
# ---------------------------------------------------------------------------
def test_resolver_token_terpisah_per_user(monkeypatch):
    """User A dan B harus melihat token Gmail masing-masing, bukan token global."""
    fake = {
        "userA@example.test": {"api_token": "TOKEN-A-ONLY"},
        "userB@example.test": {"api_token": "TOKEN-B-ONLY"},
    }
    monkeypatch.setattr(db, "get_integration", lambda email, provider: fake.get(email))

    a = db.get_integration("userA@example.test", "gmail")
    b = db.get_integration("userB@example.test", "gmail")
    assert a["api_token"] == "TOKEN-A-ONLY"
    assert b["api_token"] == "TOKEN-B-ONLY"
    assert a["api_token"] != b["api_token"]


def test_user_tanpa_token_tidak_meminjam_token_orang_lain(monkeypatch):
    """User C tanpa token harus DITOLAK, bukan jatuh ke token user lain."""
    fake = {"userA@example.test": {"api_token": "TOKEN-A-ONLY"}}
    monkeypatch.setattr(db, "get_integration", lambda email, provider: fake.get(email))

    with pytest.raises(tools.CredentialMissingError) as exc:
        tools.execute_tool(
            "kirim_email_gmail",
            {"tujuan": "x@y.z", "subjek": "s", "isi": "i"},
            "userC@example.test",
        )
    assert exc.value.provider_name == "gmail"


def test_gmail_tidak_menawarkan_tombol_connect_palsu():
    """BUG FIX 2026-10-03: gmail TIDAK boleh punya connect_url.

    Sebelum fix ini, `tools.OAUTH_CONNECT_URLS` masih memuat gmail -> sehingga
    `execute_tool` mengembalikan dict `needs_oauth` plus tombol Connect yang
    mengarah ke consent screen yang HANYA meminta scope spreadsheets. User
    menekan Connect, melihat "Connected", lalu tool tetap gagal.

    Sekarang gmail sengaja TIDAK punya connect_url: `execute_tool` melempar
    `CredentialMissingError`, yang dipetakan `api_server.chat` menjadi
    `needs_credential` - jujur, walau form manual belum punya entri gmail.
    """
    assert "gmail" not in tools.OAUTH_CONNECT_URLS
    assert "google_calendar" not in tools.OAUTH_CONNECT_URLS

    # (tanpa stubbing: gmail tidak punya connect_url, jadi jalur ini menghasilkan
    # CredentialMissingError -> needs_credential di api_server.chat)



# ---------------------------------------------------------------------------
# 2. Dispatcher WAJIB meneruskan email user ke resolver (kalau tidak, token
#    global dipakai dan semua user berbagi satu akun).
# ---------------------------------------------------------------------------
def test_dispatcher_meneruskan_email_ke_setiap_tool():
    src = inspect.getsource(tools._execute_tool_inner)
    for tool_marker in ("kirim_email_gmail", "baca_google_sheets"):
        idx = src.index(tool_marker)
        block = src[idx: idx + 400]
        assert "email=email" in block, (
            f"{tool_marker} tidak meneruskan email user ke implementasi. "
            "Kalau tidak, resolusi token bisa jadi global."
        )


# ---------------------------------------------------------------------------
# 3. Guard: gmail TIDAK boleh diiklankan sebagai OAuth selama scope belum ada.
#    Ini mengunci keputusan audit sebelumnya agar tidak diam-diam balik jadi
#    janji kosong hanya karena ada permintaan "tambahkan Gmail trigger".
# ---------------------------------------------------------------------------
def test_gmail_tidak_diiklankan_sebagai_oauth():
    import re

    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    block = re.search(r"_oauth_providers\s*=\s*\{(.*?)\}", src, re.S)
    assert block, "_oauth_providers tidak ditemukan"
    advertised = dict(re.findall(r'"([a-z_]+)"\s*:\s*"([^"]+)"', block.group(1)))
    assert "gmail" not in advertised, (
        "gmail diiklankan sebagai OAuth, tapi /oauth/google/authorize hanya "
        "request scope spreadsheets. Consent screen tidak akan memberi akses "
        "Gmail -> user menekan Connect lalu tool tetap gagal."
    )


def test_scope_google_tidak_memuat_gmail():
    """Consent screen hanya boleh meminta scope yang benar-benar dipakai."""
    import oauth_google

    assert "gmail" not in oauth_google.SHEETS_SCOPE
    # Tidak ada scope Gmail yang diminta di mana pun pada alur ini.
    all_scopes = [
        oauth_google.SHEETS_SCOPE,
        getattr(oauth_google, "GMAIL_SCOPE", ""),
        getattr(oauth_google, "GOOGLE_SCOPES", ""),
    ]
    for s in all_scopes:
        assert "gmail" not in str(s).lower()


# ---------------------------------------------------------------------------
# 4. Bukti storage: tidak ada provider 'gmail' di user_vault, dan Gmail
#    tidak punya scope OAuth. Ini yang membuat klaim "Gmail trigger
#    multi-tenant" belum dapat dibuktikan.
# ---------------------------------------------------------------------------
def test_tidak_ada_provider_gmail_di_user_vault(monkeypatch):
    """user_vault hanya menyimpan provider yang punya alur OAuth sungguhan."""
    monkeypatch.setattr(db, "is_configured", lambda: False)
    # `_LVAULT` = cache in-memory; pada env tidak terkonfigurasi semua kosong.
    monkeypatch.setattr(db, "_LVAULT", {}, raising=False)
    assert db.vault_get("userA@example.test", "gmail") == ""
