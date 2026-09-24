# tests/test_credential_flow.py
"""FASE 2.3 — alur kredensial: tersimpan terenkripsi, tidak pernah ke model.

Tiga hal yang dijaga (ketiganya mudah rusak tanpa terlihat):
  1. kredensial dari form chat HARUS ditemukan lagi oleh tool (vault fallback);
  2. nilai kunci TIDAK boleh ikut ke prompt/tool-result/balasan;
  3. form chat menyimpan lewat jalur terenkripsi, bukan kolom plaintext.
"""
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402
import tools  # noqa: E402

# FASE 6 final: aplikasi chat DIPINDAH dari `src/app/page.tsx` (kini landing
# ringan) ke `src/app/chat/ChatApp.tsx`. Tes ini menjaga SATU perilaku: form
# kredensial chat menyimpan lewat Brankas terenkripsi, bukan kolom plaintext.
# Karena itu berkasnya DICARI, dan tes gagal keras bila tidak ada kandidat yang
# benar-benar memuat form itu — supaya perpindahan file berikutnya tidak membuat
# tes "hijau" dengan memeriksa halaman yang salah (kelas bug palsu-hijau).
_FRONTEND_PAGE_CANDIDATES = [
    ROOT / "nexus-frontend" / "src" / "app" / "chat" / "ChatApp.tsx",
    ROOT / "nexus-frontend" / "src" / "app" / "page.tsx",
]


def _chat_app_source() -> str:
    for path in _FRONTEND_PAGE_CANDIDATES:
        if path.exists():
            src = path.read_text(encoding="utf-8")
            if "async function submitCredential" in src:
                return src
    raise AssertionError(
        "form kredensial chat tidak ditemukan di kandidat mana pun: "
        + ", ".join(str(p) for p in _FRONTEND_PAGE_CANDIDATES)
    )



def test_vault_dipakai_saat_tabel_plaintext_kosong(monkeypatch):
    """Kredensial hasil form chat (vault) harus terbaca tool."""
    monkeypatch.setattr(db, "is_configured", lambda: True)
    monkeypatch.setattr(db, "_get_client", lambda: _EmptyTable())
    monkeypatch.setattr(db, "_LINT", {})
    monkeypatch.setattr(db, "vault_get",
                        lambda email, provider: "ciphertext-abc")

    import vault_security as vs
    monkeypatch.setattr(vs, "decrypt_key", lambda c: "token-dari-vault")

    row = db.get_integration("u@katalir.id", "telegram")
    assert row is not None, "vault fallback tidak jalan -> flow minta token terus"
    assert row["api_token"] == "token-dari-vault"
    assert row["source"] == "vault"


def test_vault_rusak_tidak_melempar_dan_mengembalikan_none(monkeypatch):
    """Kunci vault berubah / cryptography hilang -> None, bukan 500 di /chat."""
    monkeypatch.setattr(db, "is_configured", lambda: True)
    monkeypatch.setattr(db, "_get_client", lambda: _EmptyTable())
    monkeypatch.setattr(db, "_LINT", {})
    monkeypatch.setattr(db, "vault_get", lambda email, provider: "ciphertext-abc")

    import vault_security as vs

    def boom(_c):
        raise ValueError("Vault ciphertext epäkelpo")

    monkeypatch.setattr(vs, "decrypt_key", boom)
    assert db.get_integration("u@katalir.id", "telegram") is None


def test_credential_missing_hanya_membawa_nama_provider():
    """Exception ke UI tidak boleh memuat token apa pun."""
    err = tools.CredentialMissingError("telegram")
    blob = f"{err} {err.provider_name} {err.args}"
    assert err.provider_name == "telegram"
    for leak in ("api_token", "Bearer", "sk-", "AIza", "ghp_"):
        assert leak not in blob, leak


def test_tool_tidak_pernah_mengembalikan_nilai_kunci(monkeypatch):
    """Tool yang butuh kredensial tidak boleh menaruh token di hasil/error."""
    monkeypatch.setattr(db, "get_integration",
                        lambda email, provider: {"api_token": "RAHASIA-123"})
    out = tools.execute_tool("send_whatsapp_message",
                             {"pesan": "hai", "nomor_tujuan": "+62811"},
                             "u@katalir.id")
    assert "RAHASIA-123" not in out, "nilai kunci bocor ke tool-result"

    monkeypatch.setattr(db, "get_integration", lambda email, provider: None)
    try:
        tools.execute_tool("send_whatsapp_message",
                           {"pesan": "hai", "nomor_tujuan": "+62811"}, "u@katalir.id")
    except tools.CredentialMissingError as exc:
        assert "RAHASIA-123" not in str(exc)
    else:
        raise AssertionError("harus melempar CredentialMissingError")


def test_respons_needs_credential_tidak_memuat_field_kunci():
    """Kontrak HTTP: {status, provider, connect_url?, message, session_id} — tanpa token.

    CATATAN (Task 1C): tes ini dulu mengambil jendela tetap 260 karakter setelah
    `"status": "needs_credential"`. Setelah respons ditambah `connect_url` +
    penjelasan OAuth, jendela itu bergeser sampai menyentuh kode SETELAHNYA
    (`prompt_tokens`/`completion_tokens` di meta chat) sehingga gagal padahal
    responsnya bersih. Sekarang yang diuji adalah DICT-nya sendiri (dari `return {`
    sampai `}` penutup), jadi tes menguji maksudnya: tidak ada field rahasia.
    """
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    start = src.index('"status": "needs_oauth" if connect_url else "needs_credential"')
    open_idx = src.rindex("return {", 0, start)
    end = src.index("\n        }", start)
    block = src[open_idx:end]
    assert '"provider": e.provider_name' in block
    # Hanya kunci yang memang bagian kontrak.
    keys = set(re.findall(r'"([a-z_]+)":', block))
    assert keys <= {"status", "provider", "connect_url", "message", "session_id"}, f"kunci tak terduga: {keys}"
    for leak in ("api_key", "api_token", "token"):
        assert leak not in block.lower().replace("needs_oauth", ""), f"respons memuat '{leak}'"
    print(f"NEEDS_RESPONSE_KEYS={sorted(keys)} TANPA_FIELD_KUNCI=true")



def test_form_chat_menyimpan_lewat_vault_bukan_plaintext():
    src = _chat_app_source()
    start = src.index("async function submitCredential")
    block = src[start:start + 1200]
    assert '"/api/vault/save"' in block, "form kredensial tidak memakai Brankas"
    assert '"/integrations"' not in block, "form kredensial masih menulis plaintext"


def test_putaran_penuh_enkripsi_lalu_terbaca_tool(monkeypatch):
    """Round-trip nyata: encrypt -> vault_save -> get_integration -> terdekripsi.

    Memakai jalur in-memory `_LVAULT` (is_configured=False) supaya tidak
    menyentuh Supabase, tetapi tetap melewati Fernet yang asli.
    """
    import vault_security as vs

    monkeypatch.setattr(db, "is_configured", lambda: False)
    monkeypatch.setattr(db, "_LINT", {})
    monkeypatch.setattr(db, "_LVAULT", {})

    cipher = vs.encrypt_key("token-rahasia-telegram")
    assert cipher and cipher != "token-rahasia-telegram", "tidak terenkripsi"
    db.vault_save("rt@katalir.id", "telegram", cipher)

    row = db.get_integration("rt@katalir.id", "telegram")
    assert row is not None and row["api_token"] == "token-rahasia-telegram"


def test_hapus_kredensial_membersihkan_vault_dan_tabel_lama(monkeypatch):
    """`vault_delete` = satu-satunya cara user MENCABUT kredensial.

    Membersihkan `user_vault` DAN `user_integrations` (jalur lama) supaya tidak
    ada sisa token yang masih bisa dibaca tool setelah user mencabutnya.
    """
    deleted: list[tuple[str, str]] = []

    class _Table:
        def __init__(self, name):
            self.name = name

        def delete(self):
            return self

        def eq(self, col, val):
            deleted.append((self.name, f"{col}={val}"))
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    class _Client:
        def table(self, name):
            return _Table(name)

    monkeypatch.setattr(db, "is_configured", lambda: True)
    monkeypatch.setattr(db, "_get_write_client", lambda: _Client())
    monkeypatch.setattr(db, "_LVAULT", {"u@k.id": {"telegram": "x"}})
    monkeypatch.setattr(db, "_LINT", {("u@k.id", "telegram"): {"api_token": "x"}})

    assert db.vault_delete("u@k.id", "telegram") is True
    tables = {t for t, _ in deleted}
    assert tables == {"user_vault", "user_integrations"}, tables
    assert "telegram" not in db._LVAULT["u@k.id"]        # salinan memori ikut bersih
    assert ("u@k.id", "telegram") not in db._LINT


class _EmptyTable:
    """Klien Supabase palsu: semua query mengembalikan data kosong."""

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()
