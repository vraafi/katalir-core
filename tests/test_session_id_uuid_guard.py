# -*- coding: utf-8 -*-
"""Regresi untuk BUG FIX 2026-10-11: `session_id` non-UUID -> HTTP 503.

Insiden: chat di katalir.de5.net gagal. Salah satu akar yang terbukti
reproducible adalah `session_id` non-UUID (mis. `"local_2"` dari fallback
memori `create_session`) yang diteruskan ke `chat_sessions.own_check` yang
mem-filter kolom `uuid` -> PostgREST `22P02` -> 503
"Supabase error saat chat_sessions.own_check".

Bukti mentah (sebelum perbaikan) ada di `docs/backend-recovery-2026-10-11.md`
dan dapat direproduksi dengan `ops/repro_uuid_bug.py`.

Test di sini mengunci INVARIAN-nya, bukan sekadar "tidak crash":
  1. `is_uuid` menolak semua bentuk id sintetis.
  2. `create_session` TIDAK PERNAH mengembalikan id non-UUID, bahkan saat
     jatuh ke fallback memori.
  3. `add_message` / `delete_session` / `get_messages` /
     `get_last_assistant_reply` / `rename_session` TIDAK menyentuh Postgres
     untuk id non-UUID (dibuktikan dengan klien yang sengaja diledakkan).
"""
import pytest

import database


def _boom():
    raise AssertionError("Postgres TIDAK boleh disentuh untuk session_id non-UUID")


# --------------------------------------------------------------------------
# 1. is_uuid
# --------------------------------------------------------------------------
def test_is_uuid_terima_uuid_sah():
    assert database.is_uuid("72ba7e48-c973-40ad-ba96-56bc50db32f7") is True
    assert database.is_uuid("72BA7E48-C973-40AD-BA96-56BC50DB32F7") is True  # huruf besar
    assert database.is_uuid("72ba7e48c97340adba9656bc50db32f7") is True      # tanpa strip


def test_is_uuid_tolak_id_sintetis():
    for bad in ["local_2", "bukan-uuid", "", "chat", "0", "123",
                "local_1", "72ba7e48-c973-40ad-ba96-56bc50db32f", None, 12345]:
        assert database.is_uuid(bad) is False, f"harus ditolak: {bad!r}"


def test_is_uuid_alias_publik():
    assert database.is_uuid is database._is_uuid


# --------------------------------------------------------------------------
# 2. create_session: fallback memori WAJIB tetap UUID sah
# --------------------------------------------------------------------------
def test_create_session_fallback_mengembalikan_uuid_sah(monkeypatch):
    monkeypatch.setattr(database, "_configured", False)  # paksa mode memori
    s = database.create_session("uuidtest@test.dev", "Judul")
    sid = s["id"]
    assert database.is_uuid(sid), f"fallback harus UUID sah, dapat {sid!r}"
    assert sid in database._LSESS, "sesi fallback harus terdaftar sebagai sesi memori"
    assert not sid.startswith("local_"), "id sintetis 'local_' sudah dihapus"


def test_create_session_fallback_unik(monkeypatch):
    monkeypatch.setattr(database, "_configured", False)
    ids = {database.create_session("uuidtest@test.dev", "J")["id"] for _ in range(5)}
    assert len(ids) == 5, "setiap sesi fallback harus punya id unik"


# --------------------------------------------------------------------------
# 3. Jalur tulis: id non-UUID -> memori, TANPA Postgres
# --------------------------------------------------------------------------
def test_add_message_non_uuid_tidak_sentuh_postgres(monkeypatch):
    monkeypatch.setattr(database, "_configured", True)
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    # Tidak boleh raise; dulu ini melempar HTTPException 503 (22P02).
    assert database.add_message("uuidtest@test.dev", "local_2", "user", "hai") is True


def test_add_message_sesi_fallback_memori_tidak_403(monkeypatch):
    """Sesi yang dibuat saat Postgres gagal menulis harus tetap bisa diisi.

    Kalau `_LSESS` tidak dicek, id UUID sesi memori akan dicari di Postgres,
    tidak ketemu, lalu request dibalas 403 "Session bukan milik user" --
    regresi berbeda dari bug aslinya, tapi tetap memutus chat.
    """
    monkeypatch.setattr(database, "_configured", False)
    sid = database.create_session("uuidtest@test.dev", "J")["id"]

    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    assert database.add_message("uuidtest@test.dev", sid, "user", "hai") is True


@pytest.mark.parametrize("bad", ["local_2", "bukan-uuid", "chat"])
def test_add_message_berbagai_id_sintetis(monkeypatch, bad):
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    assert database.add_message("uuidtest@test.dev", bad, "assistant", "x") is True


# --------------------------------------------------------------------------
# 4. Jalur baca/hapus/rename: id non-UUID -> hasil kosong, bukan 503
# --------------------------------------------------------------------------
def test_delete_session_non_uuid_return_false(monkeypatch):
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    assert database.delete_session("uuidtest@test.dev", "local_2") is False


def test_get_messages_non_uuid_return_kosong(monkeypatch):
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    assert database.get_messages("uuidtest@test.dev", "local_2") == []


def test_get_last_assistant_reply_non_uuid_return_none(monkeypatch):
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    assert database.get_last_assistant_reply("local_2") is None


def test_rename_session_non_uuid_tidak_raise(monkeypatch):
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", _boom)
    assert database.rename_session("uuidtest@test.dev", "local_2", "Baru") is None
