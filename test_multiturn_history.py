"""
test_multiturn_history.py — Pengujian resmi (pytest) untuk KONTEKS MULTI-TURN.

Latar belakang (bug yang diperbaiki):
    Bukti E2E produksi: pesan pertama "Halo, ingat ini: apel merah" dijawab benar,
    TETAPI turn kedua ("kamu siapa" / "apel warnanya apa?") dijawab
    "Anda belum meminta saya untuk mengingat apa pun". Yang membuktikan bukan
    masalah database: `prompt_tokens` hanya naik +1 (547 -> 548) antar turn.

    Akar masalah: `/chat` memanggil `_agentic_run_direct(req.prompt, ...)` sehingga
    daftar pesan ke model hanya [system, prompt-terakhir]. Riwayat memang TERSIMPAN
    di Supabase tapi tidak pernah DIKIRIM sebagai konteks.

Yang diuji di sini (deterministik, tanpa jaringan):
  - load_history()        => bentuk, urutan, pembatasan jumlah & panjang pesan
  - _to_genai_history()   => peran Gemini ("model", bukan "assistant")
  - _to_lc_history()      => HumanMessage/AIMessage untuk jalur gateway

Berjalan (dari folder proyek):
    pytest test_multiturn_history.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-import")

import api_server as srv  # noqa: E402


ROWS = [
    {"role": "user", "content": "Halo, ingat ini: apel merah"},
    {"role": "assistant", "content": "Baik, saya ingat: apel merah."},
    {"role": "user", "content": "apel warnanya apa?"},
]


@pytest.fixture()
def fake_db(monkeypatch):
    """db.get_messages -> ROWS, tanpa menyentuh Supabase."""
    captured = {}

    def _fake_get_messages(email, session_id, *a, **kw):
        captured["email"] = email
        captured["session_id"] = session_id
        return list(ROWS)

    monkeypatch.setattr(srv.db, "get_messages", _fake_get_messages)
    monkeypatch.setenv("AGENT_HISTORY_MESSAGES", "20")
    monkeypatch.setenv("AGENT_HISTORY_CHARS", "4000")
    return captured


def test_load_history_membawa_konteks_turn_sebelumnya(fake_db):
    """INTI BUG: riwayat sesi harus ikut dikirim ke model (bukan hanya prompt terakhir)."""
    hist = srv.load_history("user@test.app", "sess-1", current_prompt="apel warnanya apa?")

    # Prompt yang SEDANG dikirim tidak boleh ikut sebagai riwayat (hindari dobel).
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert hist[0]["content"] == "Halo, ingat ini: apel merah"
    assert hist[1]["content"] == "Baik, saya ingat: apel merah."

    joined = " ".join(h["content"] for h in hist)
    assert "apel merah" in joined, "fakta dari turn sebelumnya hilang dari konteks"

    # Bukti pemanggilan DB memakai identitas yang benar (kepemilikan sesi).
    assert fake_db == {"email": "user@test.app", "session_id": "sess-1"}


def test_load_history_tanpa_session_id_kosong(fake_db):
    """Sesi baru (belum ada id) -> riwayat kosong, tidak memanggil DB."""
    assert srv.load_history("user@test.app", None) == []
    assert srv.load_history("user@test.app", "") == []
    assert fake_db == {}, "DB tidak boleh disentuh saat session_id kosong"


def test_load_history_gagal_db_tidak_melempar(monkeypatch):
    """Gangguan riwayat tidak boleh mematikan fitur chat (harus return [])."""

    def _boom(*a, **kw):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(srv.db, "get_messages", _boom)
    assert srv.load_history("user@test.app", "sess-1") == []


def test_load_history_membatasi_jumlah_pesan(fake_db, monkeypatch):
    """Percakapan panjang dipotong ke N pesan TERAKHIR (kendali biaya/latensi)."""
    monkeypatch.setenv("AGENT_HISTORY_MESSAGES", "2")
    hist = srv.load_history("user@test.app", "sess-1", current_prompt="apel warnanya apa?")
    assert len(hist) == 2
    assert hist[-1]["content"] == "Baik, saya ingat: apel merah."


def test_load_history_memotong_pesan_sangat_panjang(fake_db, monkeypatch):
    """Satu balasan raksasa tidak boleh menghabiskan jendela konteks."""
    monkeypatch.setenv("AGENT_HISTORY_CHARS", "200")
    monkeypatch.setattr(
        srv.db,
        "get_messages",
        lambda *a, **kw: [{"role": "assistant", "content": "x" * 5000}],
    )
    hist = srv.load_history("user@test.app", "sess-1")
    assert len(hist) == 1
    assert len(hist[0]["content"]) == 201  # 200 + elipsis
    assert hist[0]["content"].endswith("…")


def test_load_history_menyaring_role_bukan_obrolan(fake_db, monkeypatch):
    """role 'system'/'tool'/kosong tidak dikirim sebagai konteks obrolan."""
    monkeypatch.setattr(
        srv.db,
        "get_messages",
        lambda *a, **kw: [
            {"role": "system", "content": "instruksi internal"},
            {"role": "tool", "content": "output alat"},
            {"role": "", "content": "tanpa role"},
            {"role": "user", "content": "pesan asli"},
        ],
    )
    hist = srv.load_history("user@test.app", "sess-1")
    assert hist == [{"role": "user", "content": "pesan asli"}]


def test_to_genai_history_memakai_peran_model():
    """Gemini memakai role 'model' untuk balasan asisten, bukan 'assistant'."""
    contents = srv._to_genai_history(ROWS[:2])
    assert [c.role for c in contents] == ["user", "model"]
    assert contents[1].parts[0].text == "Baik, saya ingat: apel merah."


def test_to_lc_history_human_dan_ai_message():
    """Jalur free-llm-gateway memakai HumanMessage/AIMessage."""
    msgs = srv._to_lc_history(ROWS[:2])
    assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]
    assert msgs[0].content == "Halo, ingat ini: apel merah"


def test_konversi_history_kosong_aman():
    """None/[] -> tanpa pesan (perilaku lama tetap valid)."""
    assert srv._to_genai_history(None) == []
    assert srv._to_genai_history([]) == []
    assert srv._to_lc_history(None) == []