"""BUG FIX 2026-10-06 — kartu (kredensial/approval) BERTAHAN saat navigasi.

Gejala yang dilaporkan user: form kredensial Telegram "muncul lalu hilang"
setelah pindah sesi / refresh, sementara konfirmasi Supabase (teks biasa) tetap
ada — jadi terlihat tidak konsisten.

Akar masalah: kartu hanya hidup di cache klien (TanStack `_localId`), TIDAK
pernah dipersist. Setelah reload, `GET /messages/{id}` hanya mengembalikan
{role, content}, jadi kartunya tidak bisa dibangun ulang.

Perbaikan: kartu dipersist sebagai baris `role="system"` berisi envelope JSON
`{__katalir_card, ...}`. Baris itu AMAN karena:
  * `load_history` hanya mengirim role user/assistant -> bukan konteks LLM;
  * `get_last_assistant_reply` memfilter role=assistant -> bukan "balasan";
  * index unik `client_request_id` bersifat partial (role='user') -> tak bentrok.
"""

import json
from types import SimpleNamespace

import pytest

import api_server


# ---------------------------------------------------------------------------
# _persist_card — bentuk baris & dedup
# ---------------------------------------------------------------------------
def test_persist_card_menulis_baris_system_envelope(monkeypatch):
    calls = []

    class _DB:
        def find_card_message_by_request(self, rid):
            return None

        def add_message(self, owner, session_id, role, content,
                        auth_id=None, client_request_id=None):
            calls.append({"owner": owner, "session_id": session_id,
                          "role": role, "content": content,
                          "client_request_id": client_request_id})
            return True

    monkeypatch.setattr(api_server, "db", _DB(), raising=False)

    api_server._persist_card(
        "u@k.test", "sess-1", "u1", "req-1",
        {"type": "credential_form", "provider": "telegram",
         "display_name": "Telegram Bot", "fields": [{"name": "bot_token"}],
         "resume_token": "tok", "original": "kirim telegram"})

    assert len(calls) == 1
    row = calls[0]
    assert row["role"] == "system", "kartu HARUS role=system (bukan assistant)"
    env = json.loads(row["content"])
    assert env["__katalir_card"] == "credential_form"
    assert env["provider"] == "telegram"
    assert env["original"] == "kirim telegram"


def test_persist_card_dedup_by_request(monkeypatch):
    """Retry (req_id sama) tidak boleh menumpuk kartu ganda."""
    calls = []

    class _DB:
        def find_card_message_by_request(self, rid):
            return {"id": "existing"}

        def add_message(self, *a, **k):
            calls.append((a, k))
            return True

    monkeypatch.setattr(api_server, "db", _DB(), raising=False)
    api_server._persist_card("u@k.test", "sess-1", "u1", "req-1",
                             {"type": "approval_prompt"})
    assert calls == [], "kartu yang sudah ada tidak boleh ditulis ulang"


def test_persist_card_tidak_pernah_melempar(monkeypatch):
    class _DB:
        def find_card_message_by_request(self, rid):
            raise RuntimeError("db down")

    monkeypatch.setattr(api_server, "db", _DB(), raising=False)
    # Tidak boleh melempar - kegagalan persist kartu bukan alasan gagal giliran.
    api_server._persist_card("u@k.test", "sess-1", "u1", "req-1",
                             {"type": "credential_form"})


# ---------------------------------------------------------------------------
# Endpoint /chat — kartu benar-benar dipersist
# ---------------------------------------------------------------------------
class _FakeDB:
    """DB palsu minimal untuk `api_server.chat`."""

    def __init__(self, run_result=None, raise_exc=None):
        self.rows = []
        self.run_result = run_result
        self.raise_exc = raise_exc

    # --- identitas / sesi ---
    def get_or_create_user(self, *_a, **_k):
        return {"tier": "free"}

    def effective_tier(self, t):
        return t

    def create_session(self, *_a, **_k):
        return {"id": "sess-1"}

    # --- idempotensi ---
    def find_user_message_by_request(self, *_a, **_k):
        return None

    def find_card_message_by_request(self, *_a, **_k):
        return None

    def get_last_assistant_reply(self, *_a, **_k):
        return None

    # --- kuota ---
    def check_quota(self, *_a, **_k):
        return True, {"bucket": "b"}

    def increment_quota(self, *_a, **_k):
        return None

    def quota_status(self, *_a, **_k):
        return {}

    def quota_bucket(self, *_a, **_k):
        return "b"

    # --- pesan ---
    def add_message(self, owner, session_id, role, content,
                    auth_id=None, client_request_id=None):
        self.rows.append({"role": role, "content": content})
        return True

    def get_messages(self, *_a, **_k):
        return list(self.rows)


def _run_chat(monkeypatch, db, run_fn):
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda _h: {"email": "u@k.test", "id": "u1"})
    monkeypatch.setattr(api_server, "db", db, raising=False)
    monkeypatch.setattr(api_server, "load_history", lambda *_a, **_k: [],
                        raising=False)
    monkeypatch.setattr(api_server, "_agentic_run_direct", run_fn,
                        raising=False)
    return api_server.chat(
        api_server.ChatRequest(prompt="kirim ke telegram chat 123 pesan halo",
                               session_id=None, client_request_id="req-1"),
        authorization="Bearer x",
    )


def test_endpoint_persist_kartu_approval(monkeypatch):
    db = _FakeDB()

    def run(*_a, **_k):
        return {
            "reply": "", "status": "requires_approval", "tool": "TELEGRAM",
            "args": {"chat_id": "123", "pesan": "halo"},
            "reason": "'TELEGRAM' mengirim data ke pihak luar",
            "approval_token": "tok-abc", "expires_in": 300,
            "meta": {"model": "m", "workflow": None},
        }

    resp = _run_chat(monkeypatch, db, run)
    assert resp["status"] == "requires_approval"
    assert resp["approval_token"] == "tok-abc"
    # Baris user + SATU baris kartu system (tanpa baris assistant kosong).
    roles = [r["role"] for r in db.rows]
    assert roles == ["user", "system"], roles
    env = json.loads(db.rows[1]["content"])
    assert env["__katalir_card"] == "approval_prompt"
    assert env["approval_token"] == "tok-abc"
    assert env["tool"] == "TELEGRAM"


def test_endpoint_persist_kartu_kredensial(monkeypatch):
    db = _FakeDB()

    def run(*_a, **_k):
        raise api_server.CredentialMissingError("telegram")

    resp = _run_chat(monkeypatch, db, run)
    assert resp["status"] == "requires_credential"
    assert resp["provider"] == "telegram"
    roles = [r["role"] for r in db.rows]
    assert roles == ["user", "system"], roles
    env = json.loads(db.rows[1]["content"])
    assert env["__katalir_card"] == "credential_form"
    assert env["provider"] == "telegram"
    # Deskripsi field + resume_token ikut tersimpan supaya form bisa dirender.
    assert env["fields"], "field form harus ikut dipersist"
    assert env["resume_token"], "resume_token harus ikut dipersist"


# ---------------------------------------------------------------------------
# Baris kartu tidak mengotori konteks LLM
# ---------------------------------------------------------------------------
def test_load_history_abaikan_baris_kartu(monkeypatch):
    rows = [
        {"role": "user", "content": "kirim ke telegram"},
        {"role": "system", "content": json.dumps(
            {"__katalir_card": "credential_form", "provider": "telegram"})},
        {"role": "assistant", "content": "baik"},
    ]

    class _DB:
        def get_messages(self, *_a, **_k):
            return rows

    monkeypatch.setattr(api_server, "db", _DB(), raising=False)
    hist = api_server.load_history("u@k.test", "sess-1")
    assert [h["role"] for h in hist] == ["user", "assistant"], hist
    assert all("__katalir_card" not in h["content"] for h in hist)
