"""tests/test_default_model_preference.py — regresi Bug #2 (6 Okt 2026).

LATAR
-----
User melaporkan agen "mode discovery berlebihan": untuk permintaan yang
alurnya sudah jelas ("setiap pagi jam 7 ambil data dari API lalu kirim ke
telegram") agen TIDAK membangun workflow, melainkan bertanya URL/metode HTTP.
Workflow tidak pernah jadi.

AKAR MASALAH
------------
`_default_model_id()` mengembalikan `roster[0]`. Roster `probe_roster()`
diurutkan (provider, id), jadi urutan itu KEBETULAN menaruh
`gemini-2.5-flash-lite` (model terlemah) di depan. Harness loop nyata
(`_bug2_loop.py`, prompt nyata, alat nyata):

  gemini-2.5-flash-lite  -> [check_credential] lalu BERTANYA  (0/1 membangun)
  gemini-3.5-flash-lite  -> [generate_workflow_json]          (4/4 membangun)

Aturan prompt (ATURAN BUILD WORKFLOW) sudah BENAR; yang salah adalah
memilih model default secara alfabetis, bukan berdasarkan kapabilitas.

PERBAIKAN
---------
`DEFAULT_MODEL_PREFERENCE` memilih default secara sadar (kuat -> lemah),
menghormati override `AGENT_MODEL` bila ada di roster, dan jatuh ke
`roster[0]` hanya bila tidak ada preferensi yang cocok.
"""
import api_server


def test_preferensi_model_lulus_dua_bug_berada_di_depan():
    """`gemini-3.5-flash-lite` harus paling depan.

    Itu satu-satunya model roster yang LULUS dua perilaku sekaligus
    (matriks `_model_matrix.py`): memanggil `kirim_telegram_message` (Bug#1)
    DAN `generate_workflow_json` (Bug#2).
    """
    pref = api_server.DEFAULT_MODEL_PREFERENCE
    assert pref[0] == "gemini-3.5-flash-lite", pref
    # `gemini-2.5-flash-lite` (gagal Bug#2) harus berada di belakang.
    assert pref.index("gemini-3.5-flash-lite") < pref.index("gemini-2.5-flash-lite")


def test_default_memilih_model_yang_lulus_dua_bug(monkeypatch):
    roster = ["gemini-2.5-flash-lite", "gemini-2.5-flash",
              "gemini-3.5-flash-lite", "allam-2-7b"]
    monkeypatch.setattr(api_server, "_gateway_target",
                        lambda: ("http://gw", "k", roster))
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    assert api_server._default_model_id() == "gemini-3.5-flash-lite"


def test_default_env_override_menang(monkeypatch):
    """`AGENT_MODEL` yang ada di roster mengalahkan preferensi."""
    roster = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "qwen/qwen3.8-27b"]
    monkeypatch.setattr(api_server, "_gateway_target",
                        lambda: ("http://gw", "k", roster))
    monkeypatch.setenv("AGENT_MODEL", "qwen/qwen3.8-27b")
    assert api_server._default_model_id() == "qwen/qwen3.8-27b"


def test_default_env_di_luar_roster_diabaikan(monkeypatch):
    """`AGENT_MODEL` yang TIDAK ada di roster tidak dipakai (cegah 404)."""
    roster = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
    monkeypatch.setattr(api_server, "_gateway_target",
                        lambda: ("http://gw", "k", roster))
    monkeypatch.setenv("AGENT_MODEL", "model-yang-tidak-ada")
    assert api_server._default_model_id() in roster


def test_default_fallback_ke_roster_pertama(monkeypatch):
    """Bila tak ada preferensi yang cocok, pakai roster[0] (perilaku lama)."""
    roster = ["allam-2-7b", "poolside/laguna-xs-2.1"]
    monkeypatch.setattr(api_server, "_gateway_target",
                        lambda: ("http://gw", "k", roster))
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    assert api_server._default_model_id() == "allam-2-7b"


def test_default_tanpa_gateway_pakai_env(monkeypatch):
    monkeypatch.setattr(api_server, "_gateway_target", lambda: None)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    assert api_server._default_model_id() == "gemma-4-31b-it"
