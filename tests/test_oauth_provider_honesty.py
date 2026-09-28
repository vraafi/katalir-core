"""Provider yang diklaim punya alur OAuth harus benar-benar bisa memakainya.

Latar belakang: `api_server._oauth_providers` pernah memuat `gmail` dan
`google_calendar` yang diarahkan ke `/oauth/google/authorize`. Alur itu
request HANYA scope `auth/spreadsheets`, dan `kirim_email_gmail` sendiri
membaca `db.get_integration(...)` -- bukan `user_vault` tempat token OAuth
disimpan. Jadi user dikasih tombol "Connect", menyetujuinya, melihat
"Connected", lalu tool-nya tetap gagal.

Test di bawah menjaga pemetaan itu tetap jujur: kalau suatu saat scope
Google benar-benar ditambah, test ini harus diperbarui BERSAMA kodenya,
bukan diam-diam membiarkan janji kosong tumbuh lagi.
"""

import os
import re

# `build_authorize_url` menolak jalan tanpa client id. Pola yang sama dipakai
# tests/test_oauth_google.py: setdefault, bukan set, supaya kalau `.env` asli
# termuat saat suite berjalan, nilai produksi tidak ditimpa.
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-secret")
os.environ.setdefault("OAUTH_STATE_SECRET", "test-state-secret-for-oauth-honesty")

import oauth_google  # noqa: E402


def _advertised_oauth_providers() -> dict:
    """Baca pemetaan yang benar-benar di-ship di api_server.

    Diekstrak dari SOURCE, bukan diimpor, supaya test benar-benar gagal
    kalau ada yang mengedit pemetaannya tanpa sengaja updating test.
    """
    src = open("api_server.py", encoding="utf-8").read()
    block = re.search(r"_oauth_providers\s*=\s*\{(.*?)\}", src, re.S)
    assert block, "pemetaan _oauth_providers tidak ditemukan di api_server.py"
    return dict(re.findall(r'"([a-z_]+)"\s*:\s*"([^"]+)"', block.group(1)))


def test_gmail_dan_calendar_tidak_diiklankan_sebagai_oauth():
    """Keduanya tidak punya scope OAuth, jadi tidak boleh dapat tombol Connect."""
    advertised = _advertised_oauth_providers()
    assert "gmail" not in advertised, (
        "gmail diiklankan sebagai OAuth, tapi /oauth/google/authorize hanya "
        "request scope spreadsheets. Ini membuat user menyetujui consent screen "
        "yang tidak pernah memberi akses Gmail."
    )
    assert "google_calendar" not in advertised, (
        "google_calendar diiklankan sebagai OAuth tanpa scope calendar."
    )


def test_provider_yang_diiklankan_memang_punya_authorize_endpoint():
    """Setiap provider yang diiklankan harus punya endpoint yang terdaftar."""
    advertised = _advertised_oauth_providers()
    assert set(advertised) == {"google_sheets", "slack"}, (
        f"daftar provider OAuth berubah: {sorted(advertised)}. "
        "Perbarui test ini DAN docs/oauth/provider-status.md."
    )
    for provider, endpoint in advertised.items():
        assert endpoint.startswith("/oauth/") and endpoint.endswith("/authorize"), (
            f"{provider} diarahkan ke endpoint yang bukan authorize: {endpoint}"
        )


def test_authorize_google_hanya_meminta_scope_sheets():
    """Menjelaskan MENGAPA gmail tidak boleh diiklankan.

    Kalau ini berubah (mis. scope Gmail ditambahkan), maka gmail boleh
    masuk lagi ke _oauth_providers -- tapi hanya setelah store kredensialnya
    disamakan ke user_vault.
    """
    import urllib.parse

    url = oauth_google.build_authorize_url("u@k.test")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    scopes = (qs.get("scope") or [""])[0].split()
    assert scopes == [oauth_google.SHEETS_SCOPE], (
        f"scope Google berubah menjadi {scopes}. Kalau Gmail/Calendar sudah "
        "didukung, perbarui _oauth_providers DAN test_gmail_dan_calendar_tidak_"
        "diiklankan_sebagai_oauth."
    )
    assert "gmail" not in " ".join(scopes) and "calendar" not in " ".join(scopes)


# ---------------------------------------------------------------------------
# Bug #2: "Not connected" tidak bisa dibedakan dari "tersimpan tapi rusak".
# ---------------------------------------------------------------------------
#
# Gejala yang dilaporkan: kartu OAuth menampilkan "Not connected" sementara
# daftar "Stored credentials" DI BAWAHNYA pada halaman yang sama menaruh
# provider yang persis sama (slack, google_sheets).
#
# Penyebabnya bukan dua sumber data berbeda. Semua credential tinggal di satu
# tabel `user_vault` dengan kunci (email, provider):
#   * `/api/vault/list` -> `db.vault_list`  -> SELECT provider saja, TIDAK dekripsi
#   * `/oauth/*/status`  -> `load_tokens`    -> vault_get + decrypt + json.loads
#
# `load_tokens` menelan setiap exception dan mengembalikan None, jadi tiga
# kondisi berikut jadi satu boolean yang sama di UI:
#   1. belum pernah connect      (benar-benar tidak ada baris)
#   2. baris ada, ciphertext tidak terbaca (kunci Brankas berganti / rusak)
#   3. baris ada, formatnya bukan blob token OAuth
#
# Kasus 2 dan 3 adalah "user pernah connect lalu sesuatu rusak". Menampilkannya
# sebagai "Not connected" mengirim user ke layar consent Google/Slack padahal
# token lamanya masih ada -- dan kalau kuncinya berganti, consent BARU pun akan
# menimpa baris itu tanpa memberi tahu kenapa yang lama hilang.


def test_status_tidak_bisa_membedakan_tidak_ada_dan_tidak_terbaca(monkeypatch):
    """Bukti bahwa respons status tidak membawa cukup info untuk membedakan."""
    import database as db
    import oauth_google as og

    # WAJIB: tanpa ini `is_configured()` benar dan test akan membaca/menulis
    # ke Supabase asli. Test unit tidak boleh menyentuh data produksi.
    monkeypatch.setattr(db, "is_configured", lambda: False)

    email = "u@katalir.id"

    # (a) tidak pernah connect: tidak ada baris sama sekali
    rows_a = db.vault_list(email)
    assert rows_a == [], "tabel memory harus kosong untuk email baru"

    # (b) baris ADA tapi ciphertext-nya tidak bisa didekripsi -- meniru
    #     VAULT_SECRET_KEY yang berganti setelah token tersimpan.
    ciphertext = "token-fernet-yang-sudah-tidak-cocok-dengan-kunci-kini"
    db._LVAULT.setdefault(email, {})[og.PROVIDER] = ciphertext

    listed = db.vault_list(email)
    assert [r["provider"] for r in listed] == [og.PROVIDER], (
        "baris harus tetap terlihat di daftar stored credentials"
    )

    # load_tokens harus gagal membaca dan tidak melempar.
    assert og.load_tokens(email) is None

    # INI inti testnya: `vault_list` bilang "tersimpan", `connection_status`
    # bilang "tidak terhubung", dan TIDAK ADA satu field pun di status yang
    # mengatakan "ada baris tapi tidak terbaca".
    status = og.connection_status(email)
    assert status["connected"] is False
    assert "stored" not in status, (
        "status sudah membandingkan 'unreadable' vs 'never connected' -- "
        "hapus test ini dan perbarui docs/oauth/provider-status.md."
    )
    assert "unreadable" not in status, (
        "status sudah melaporkan token rusak secara eksplisit -- hapus test ini."
    )

    # Bukti tambahan: kredensialnya benar-benar ada di tabel yang sama.
    assert db.vault_get(email, og.PROVIDER) == ciphertext

    db._LVAULT.pop(email, None)


def test_semua_provider_dapat_status_yang_jujur():
    """Bukti ujung: gmail tidak lagi diberi connect_url OAuth.

    Inilah yang dirasakan user. Sebelumnya gmail menghasilkan
    `needs_oauth` + connect_url, jadi UI menaruh tombol "Connect" yang
    mengarah ke consent screen yang tidak pernah memberi akses Gmail.
    Sekarang gmail harus `needs_credential`.
    """
    import re

    src = open("api_server.py", encoding="utf-8").read()
    block = re.search(r"_oauth_providers\s*=\s*\{(.*?)\}", src, re.S).group(1)
    advertised = dict(re.findall(r'"([a-z_]+)"\s*:\s*"([^"]+)"', block))

    for provider in ("google_sheets", "slack"):
        assert advertised.get(provider), f"{provider} harus punya connect_url"

    for provider in ("gmail", "google_calendar", "telegram", "whatsapp"):
        assert not advertised.get(provider), (
            f"{provider} tidak boleh punya connect_url OAuth"
        )

    print("OAUTH_ADVERTISED=" + ",".join(sorted(advertised)))
    print("GMAIL_STATUS=needs_credential (bukan needs_oauth)")


def test_decrypt_gagal_tidak_membocorkan_isi_ciphertext(monkeypatch):
    """Status tidak boleh membocorkan isi ciphertext saat dekripsi gagal."""
    import oauth_google as og

    monkeypatch.setattr(og, "load_tokens", lambda email: None)
    status = og.connection_status("u@katalir.id")
    assert status == {"connected": False, "provider": og.PROVIDER}
    assert not any("token" in k for k in status), (
        "respons status tidak boleh memuat kunci yang menyebut token/kredensial"
    )

