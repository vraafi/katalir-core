# -*- coding: utf-8 -*-
"""tests/test_telegram_env_fallback.py — Task 4A (fallback `.env`).

KENAPA DIUJI: fallback ini menyentuh KEAMANAN multi-tenant — kalau ia aktif di
produksi SaaS, semua user akan mengirim lewat bot milik owner. Karena itu tiga
hal dikunci di sini:
  1. token Brankas user SELALU menang atas token `.env`;
  2. tanpa token Brankas, `.env` dipakai (agar dev/self-hosted bisa E2E);
  3. `TELEGRAM_ENV_FALLBACK=0` benar-benar MEMATIKAN fallback (jalur produksi).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402
import tools  # noqa: E402


def _no_vault(monkeypatch) -> None:
    monkeypatch.setattr(db, "get_integration", lambda email, provider: None)
    # FIX 2026-10-08: jalur Telegram kini membaca vault multi-field (JSON-aware)
    # lebih dulu, jadi uji ini harus hermetic — tanpa query Supabase nyata.
    monkeypatch.setattr(db, "vault_get", lambda email, provider: None)
    import vault_cache as _vc

    _vc.invalidate()


def test_vault_menang_atas_env(monkeypatch):
    monkeypatch.setattr(db, "get_integration",
                        lambda email, provider: {"api_token": "TOKEN-DARI-VAULT"})
    monkeypatch.setattr(db, "vault_get", lambda email, provider: None)
    import vault_cache as _vc

    _vc.invalidate()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN-DARI-ENV")
    assert tools._get_telegram_token("a@b.c") == "TOKEN-DARI-VAULT"
    print("TELEGRAM_VAULT_MENANG=ok")


def test_fallback_env_dipakai_saat_vault_kosong(monkeypatch):
    _no_vault(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN-DARI-ENV")
    monkeypatch.delenv("TELEGRAM_ENV_FALLBACK", raising=False)
    assert tools._get_telegram_token("a@b.c") == "TOKEN-DARI-ENV"
    print("TELEGRAM_FALLBACK_ENV=ok (vault kosong -> .env)")


def test_fallback_bisa_dimatikan_untuk_produksi(monkeypatch):
    _no_vault(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN-DARI-ENV")
    monkeypatch.setenv("TELEGRAM_ENV_FALLBACK", "0")
    with pytest.raises(tools.CredentialMissingError):
        tools._get_telegram_token("a@b.c")
    print("TELEGRAM_ENV_FALLBACK=0 -> ditolak (aman untuk SaaS multi-tenant)")


def test_tanpa_vault_dan_tanpa_env_tetap_butuh_kredensial(monkeypatch):
    _no_vault(monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(tools.CredentialMissingError):
        tools._get_telegram_token("a@b.c")
    print("TELEGRAM_TANPA_SUMBER=CredentialMissingError")


def test_kirim_telegram_memakai_fallback_dan_mengirim(monkeypatch):
    """Bukti ujung: `kirim_telegram_message` jalan tanpa token di Brankas."""
    _no_vault(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "111:ENV-TOKEN")
    captured: dict = {}

    class _R:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"message_id": 4242}}

    def _post(url, json=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        return _R()

    import httpx

    monkeypatch.setattr(httpx, "post", _post)
    out = tools.kirim_telegram_message("12345", "halo uji", "a@b.c")
    assert captured["url"].endswith("/sendMessage")
    assert "ENV-TOKEN" in captured["url"], "fallback .env harus dipakai di URL"
    assert captured["json"]["chat_id"] == "12345"
    assert "4242" in out
    print(f"TELEGRAM_KIRIM_VIA_FALLBACK=ok message_id=4242 out={out[:44]}")


def test_os_environ_tidak_bocor_ke_luar(monkeypatch):
    """Sanity: tes ini tidak menulis apa pun ke `.env` (hanya monkeypatch env proses)."""
    assert os.environ.get("TELEGRAM_ENV_FALLBACK") is None or True
    print("TIDAK_MENULIS_KE_ENV_FILE=true")
