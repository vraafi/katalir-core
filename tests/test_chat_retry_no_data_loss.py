"""tests/test_chat_retry_no_data_loss.py — retry /chat TIDAK boleh menghapus chat.

BUG ASLI (ditemukan 2026-10-01, blocker launch 6 Oktober):

  1. `ChatApp.retryMessage` memfilter SELURUH bubble user dengan
     `content === errMsg.original`. Kalau user pernah mengetik prompt yang SAMA
     di giliran sebelumnya, pesan lama ikut terhapus dari layar ->
     "seluruh percakapan hilang".
  2. Retry mengirim `clientRequestId` BARU tiap kali, sehingga idempotensi
     backend tidak berlaku -> pesan user ter-insert GANDUL di `chat_messages`
     setiap kali "Coba Lagi" ditekan.
  3. `get_last_assistant_reply(session_id)` tidak ditautkan ke
     `client_request_id`. Pada percakapan yang sudah punya giliran sukses,
     retry pesan GAGAL akan mengembalikan reply giliran SEBELUMNYA lalu
     short-circuit -> user melihat jawaban basi seolah retried-nya berhasil.

Yang DIKUNCI di sini (regresi; query di-mock, tidak butuh DB nyata):
  A. `get_last_assistant_reply` memfilter `client_request_id` saat diberi.
  B. Tanpa `client_request_id`, perilaku lama dipertahankan.
  C. `add_message` tidak meng-insert dua kali untuk UUID sama (role=user).
  D. Reply assistant dengan UUID sama TETAP disimpan (tidak ikut dedup).
  E. `api_server` meneruskan `req_id` ke `get_last_assistant_reply`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402


class _FakeQuery:
    """Mencatat rantai `.eq()` lalu menyaring baris accordingly."""

    def __init__(self, rows):
        self.rows = rows
        self.filters: list[tuple[str, object]] = []

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self



    def execute(self):
        matched = [r for r in self.rows
                   if all(r.get(c) == v for c, v in self.filters)]
        matched.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return SimpleNamespace(data=matched)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(db, "is_configured", lambda: True)
    monkeypatch.setattr(db, "_request_key_enabled", lambda: True)
# --- A/B: get_last_assistant_reply ------------------------------------------
def test_reply_difilter_oleh_client_request_id(configured, monkeypatch):
    """Reply WAJIB milik kiriman yang sama, bukan reply terakhir sesi."""
    rows = [
        {"session_id": "sess-1", "role": "assistant",
         "content": "JAWABAN GILIRAN 1", "client_request_id": "req-AAA",
         "created_at": "2026-10-01T00:00:00Z"},
        {"session_id": "sess-1", "role": "assistant",
         "content": "JAWABAN GILIRAN 2", "client_request_id": "req-BBB",
         "created_at": "2026-10-01T00:01:00Z"},
    ]
    q = _FakeQuery(rows)
    monkeypatch.setattr(db, "_get_write_client",
                        lambda: SimpleNamespace(table=lambda _t: q))

    got = db.get_last_assistant_reply("sess-1", client_request_id="req-AAA")
    assert got == "JAWABAN GILIRAN 1", (
        f"reply harus terikat ke req-AAA. Got {got!r}")
    assert ("client_request_id", "req-AAA") in q.filters


def test_reply_tanpa_request_id_perilaku_lama(configured, monkeypatch):
    """Tanpa client_request_id -> tetap 'reply terakhir sesi'."""
    rows = [
        {"session_id": "sess-1", "role": "assistant",
         "content": "LAMA", "client_request_id": "req-AAA",
         "created_at": "2026-10-01T00:00:00Z"},
        {"session_id": "sess-1", "role": "assistant",
         "content": "TERAKHIR", "client_request_id": "req-BBB",
         "created_at": "2026-10-01T00:01:00Z"},
    ]
    q = _FakeQuery(rows)
    monkeypatch.setattr(db, "_get_write_client",
                        lambda: SimpleNamespace(table=lambda _t: q))

    assert db.get_last_assistant_reply("sess-1") == "TERAKHIR"
    assert not [f for f in q.filters if f[0] == "client_request_id"]


def test_reply_giliran_baru_tidak_tertukar(configured, monkeypatch):
    """REGRESI UTAMA: retry pesan gagal tidak boleh memakai reply giliran lain."""
    rows = [
        {"session_id": "sess-1", "role": "assistant",
         "content": "JAWABAN GILIRAN 1", "client_request_id": "req-AAA",
         "created_at": "2026-10-01T00:00:00Z"},
    ]
    q = _FakeQuery(rows)
    monkeypatch.setattr(db, "_get_write_client",
                        lambda: SimpleNamespace(table=lambda _t: q))

    retried = db.get_last_assistant_reply("sess-1", client_request_id="req-BBB")
    assert retried is None, (
        "reply giliran lain TIDAK boleh dipakai untuk retry -> short-circuit "
        f"dengan jawaban basi. Got {retried!r}")


# --- C/D: add_message idempoten ---------------------------------------------
class _Chained:
    """Rantai `.eq().eq().limit().execute()` seperti PostgREST client."""

    def __init__(self, rows):
        self.rows = rows

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


def _fake_write_client(monkeypatch, inserts, session_exists=True):
    """Write client palsu.

    `chat_sessions` -> session milik user, agar gate kepemilikan lolos.
    `chat_messages` -> select() selalu mengembalikan satu baris, yaitu
    "pesan user dengan UUID ini sudah tercatat". Kondisi itu yang harus
    diuji oleh `add_message`: ia harus dedup, bukan insert lagi.
    """

    class _Msg:
        def select(self, *_a, **_k):
            return _Chained([{"id": "msg-1"}])

        def insert(self, row):
            inserts.append(row)
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[row]))

    class _Sess:
        def select(self, *_a, **_k):
            return _Chained([{"id": "s1"}] if session_exists else [])

    monkeypatch.setattr(db, "_get_write_client", lambda: SimpleNamespace(
        table=lambda n: _Sess() if n == "chat_sessions" else _Msg()))
    monkeypatch.setattr(db, "_resolve_user_id", lambda *a, **k: "u1")
    monkeypatch.setattr(db, "_wrap_write", lambda fn, _tag: fn())


def test_add_message_tidak_duplikat_uuid_sama(configured, monkeypatch):
    """Kirim ulang dengan UUID sama -> TIDAK insert (return False)."""
    inserts: list[dict] = []
    _fake_write_client(monkeypatch, inserts)

    first = db.add_message("u@k.test", "s1", "user", "halo",
                           auth_id="u1", client_request_id="req-1")
    assert first is False, "UUID sama + role=user -> harus dedup, bukan insert"
    assert not inserts, f"tidak boleh ada baris tersimpan: {inserts}"


def test_reply_asisten_tetap_disimpan(configured, monkeypatch):
    """Reply assistant dengan UUID sama TETAP disimpan.

    Kalau ikut dedup, pesan user menggantung tanpa balasan selamanya.
    """
    inserts: list[dict] = []
    _fake_write_client(monkeypatch, inserts)

    ok = db.add_message("u@k.test", "s1", "assistant", "jawaban",
                        auth_id="u1", client_request_id="req-1")
    assert ok is True
    assert len(inserts) == 1 and inserts[0]["role"] == "assistant"


# --- E: api_server meneruskan req_id ----------------------------------------
def test_api_server_teruskan_client_request_id_ke_reply_lookup(monkeypatch):
    """Regresi: `get_last_assistant_reply` HARUS dipanggil dengan req_id.

    Tanpa req_id, endpoint mengembalikan reply giliran sebelumnya lalu
    short-circuit sehingga retry tidak pernah benar-benar dijalankan.
    """
    import api_server

    calls: list[tuple] = []

    class _Query:
        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class _DB:
        def get_or_create_user(self, *_a, **_k):
            return {"tier": "free"}

        def effective_tier(self, t):
            return t

        def find_user_message_by_request(self, rid):
            return {"session_id": "sess-1", "id": "m1"} if rid == "req-XYZ" else None

        def get_last_assistant_reply(self, session_id, client_request_id=None):
            calls.append((session_id, client_request_id))
            # "reply lama" hanya muncul kalau req_id TIDAK diteruskan -
            # meniru perilaku buggy yang harus dicegah.
            return "reply lama" if client_request_id is None else None

        def check_quota(self, *_a, **_k):
            return True, {"bucket": "b"}

    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda _h: {"email": "u@k.test", "id": "u1"})
    monkeypatch.setattr(api_server, "db", _DB(), raising=False)
    monkeypatch.setattr(api_server, "load_history", lambda *_a, **_k: [], raising=False)

    def _boom(*_a, **_k):
        raise RuntimeError("LLM gagal (disengaja untuk test)")

    monkeypatch.setattr(api_server, "_agentic_run_direct", _boom, raising=False)

    with pytest.raises(Exception):
        api_server.chat(
            api_server.ChatRequest(prompt="halo", session_id=None,
                                   client_request_id="req-XYZ"),
            authorization="Bearer x",
        )

    assert calls, "get_last_assistant_reply tidak dipanggil sama sekali"
    session_id, used = calls[0]
    assert session_id == "sess-1"
    assert used == "req-XYZ", (
        "reply lookup HARUS dikunci ke req_id; tanpa itu retry memakai reply "
        f"giliran sebelumnya. req_id yang diteruskan = {used!r}")
