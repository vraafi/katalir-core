# -*- coding: utf-8 -*-
"""tests/test_telegram_vault_multifield.py — regresi BUG 2026-10-08.

BUG: kredensial Telegram yang disimpan lewat form chat adalah SATU ciphertext
JSON `{"bot_token": ..., "chat_id": ...}` (`credential_forms.save_vault_credential`),
tetapi pembacaan legacy (`db.get_integration` -> `database._vault_integration`)
mengembalikan string terdekripsi MENTAH sebagai "api_token" — sehingga URL kirim
menjadi `https://api.telegram.org/bot<JSON-BLOB>/sendMessage` dan Telegram
menolaknya (HTTP 401).

FIX: jalur Telegram membaca vault JSON-aware lebih dulu (pola Gmail IMAP:
`credential_forms.load_vault_credential`), dengan fallback ke baris token polos.

SEMUA kredensial di file ini PALSU — tidak ada nilai rahasia nyata.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402
import tools  # noqa: E402
import vault_cache as vault_cache_mod  # noqa: E402
import vault_security as vs  # noqa: E402

FAKE_TOKEN = "123456:FAKE-TOKEN-NOT-REAL"
FAKE_CHAT = "2109751369"
EMAIL = "probe@katalir.test"


@pytest.fixture(autouse=True)
def _hermetic_vault(monkeypatch):
    """Tanpa Supabase nyata; cache vault dibersihkan sebelum & sesudah tiap uji."""
    monkeypatch.setattr(db, "is_configured", lambda: False)
    monkeypatch.setattr(db, "_LINT", {})
    monkeypatch.setattr(db, "vault_get", lambda email, provider: None)
    vault_cache_mod.invalidate()
    yield
    vault_cache_mod.invalidate()


def _vault_row_json(monkeypatch, values: dict) -> None:
    """Simulasikan PERSIS apa yang ditulis `credential_forms.save_vault_credential`."""
    plain = json.dumps(values, ensure_ascii=False, sort_keys=True)
    cipher = vs.encrypt_key(plain)
    monkeypatch.setattr(
        db, "vault_get",
        lambda email, provider: cipher if provider == "telegram" else None)


def test_1_chat_form_token_dibaca_sebagai_bot_token(monkeypatch):
    """Round-trip: save multi-field -> baca -> bot_token BUKAN JSON blob."""
    _vault_row_json(monkeypatch, {"bot_token": FAKE_TOKEN, "chat_id": FAKE_CHAT})
    token = tools._get_telegram_token(EMAIL)
    assert token == FAKE_TOKEN, f"harus bot_token murni, dapat: {token[:40]!r}"
    assert not token.lstrip().startswith("{"), "token tidak boleh JSON blob"
    print(f"TELEGRAM_MULTIFIELD_BOT_TOKEN=ok len={len(token)} (bukan JSON)")


def test_2_kirim_telegram_url_memakai_bot_token_murni(monkeypatch):
    """Bukti ujung: URL yang dibangun memuat bot token, BUKAN JSON blob."""
    _vault_row_json(monkeypatch, {"bot_token": FAKE_TOKEN, "chat_id": FAKE_CHAT})
    captured: dict = {}

    class _R:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"message_id": 777}}

    def _post(url, json=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        return _R()

    import httpx

    monkeypatch.setattr(httpx, "post", _post)
    out = tools.kirim_telegram_message(FAKE_CHAT, "Katalir Test - Manual Trigger Berfungsi", EMAIL)
    assert f"/bot{FAKE_TOKEN}/sendMessage" in captured["url"], captured["url"]
    assert "{" not in captured["url"].split("/bot")[-1].split("/")[0], \
        "segmen token di URL tidak boleh mengandung JSON"
    assert captured["json"]["chat_id"] == FAKE_CHAT
    assert "777" in out
    print(f"TELEGRAM_URL_MURNI=ok message_id=777 chat={FAKE_CHAT[:4]}***")


def test_3_token_polos_legacy_masih_dibaca(monkeypatch):
    """Baris vault token POLos (mis. dari /api/vault/save) tetap berfungsi."""
    cipher = vs.encrypt_key("PLAIN-LEGACY-TOKEN")
    monkeypatch.setattr(
        db, "vault_get",
        lambda email, provider: cipher if provider == "telegram" else None)
    monkeypatch.setattr(db, "get_integration",
                        lambda email, provider: {"api_token": "PLAIN-LEGACY-TOKEN"})
    token = tools._get_telegram_token(EMAIL)
    assert token == "PLAIN-LEGACY-TOKEN"
    print("TELEGRAM_LEGACY_PLAIN_TOKEN=ok (jalur lama tidak pecah)")


def test_4_json_blob_legacy_tidak_dikirim_sebagai_token(monkeypatch):
    """Pertahanan: baris JSON blob yang gagal di-parse TIDAK boleh jadi token."""
    blob = json.dumps({"bot_token": FAKE_TOKEN, "chat_id": FAKE_CHAT})
    monkeypatch.setattr(db, "vault_get", lambda email, provider: None)
    monkeypatch.setattr(db, "get_integration",
                        lambda email, provider: {"api_token": blob})
    monkeypatch.setenv("TELEGRAM_ENV_FALLBACK", "0")
    with pytest.raises(tools.CredentialMissingError):
        tools._get_telegram_token(EMAIL)
    print("TELEGRAM_JSON_BLOB_DITOLAK=ok (gagal jelas, bukan URL rusak)")


def test_5_vault_json_menang_atas_env(monkeypatch):
    """Precedensi tidak berubah: Brankas user SELALU menang atas `.env`."""
    _vault_row_json(monkeypatch, {"bot_token": FAKE_TOKEN, "chat_id": FAKE_CHAT})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "111:ENV-TOKEN")
    assert tools._get_telegram_token(EMAIL) == FAKE_TOKEN
    print("TELEGRAM_PRECEDENSI=ok (vault > .env)")


def test_6_tanpa_vault_dan_env_mati_tetap_butuh_kredensial(monkeypatch):
    """Perilaku lama dipertahankan: tidak ada sumber -> CredentialMissingError."""
    monkeypatch.setenv("TELEGRAM_ENV_FALLBACK", "0")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(tools.CredentialMissingError):
        tools._get_telegram_token(EMAIL)
    print("TELEGRAM_TANPA_SUMBER=ok (CredentialMissingError)")


def test_7_chat_id_tetap_dari_config_node(monkeypatch):
    """chat_id tetap dari config node (BUKAN dari vault) — perilaku tidak berubah."""
    _vault_row_json(monkeypatch, {"bot_token": FAKE_TOKEN, "chat_id": "999"})
    captured: dict = {}

    class _R:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"message_id": 1}}

    import httpx

    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, timeout=None: captured.update(
                            {"url": url, "json": json}) or _R())
    tools.kirim_telegram_message("777888", "halo", EMAIL)
    assert captured["json"]["chat_id"] == "777888", "chat_id harus dari node, bukan vault"
    print("TELEGRAM_CHAT_ID_DARI_NODE=ok")
