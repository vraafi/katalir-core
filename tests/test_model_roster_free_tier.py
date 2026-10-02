"""Regresi BUG #2 (2026-10-02): roster gateway hanya 3 model.

Gate 2 (`FREE_TIER_MODEL_IDS`) hanya berisi id Gemini, tapi ia diterapkan ke
seluruh model termasuk roster gateway yang serves llama/gemma/qwen/deepseek.
Hasilnya 259 model gateway terbuang -> `/models` hanya mengembalikan 3.

Test ini mengunci perilaku: model google tetap kena allowlist ketat, model
non-google (gateway) lolos Gate 2 tapi tetap harus lolos Gate 1 + chat_capable.
"""
import gateway_roster as gr


def test_google_tetap_kena_allowlist_ketat():
    assert gr._model_allowed_for_tier("gemini-2.5-flash-lite", "free", "google") is True
    # Di luar allowlist keluarga google -> tetap DITOLAK (rezeki gate 2).
    assert gr._model_allowed_for_tier("gemini-3.9-pro-ultra", "free", "google") is False


def test_model_gateway_lolos_gate2():
    """Model non-google tidak lagi dibuang oleh allowlist Gemini."""
    for mid, prov in [
        ("llama-3.3-70b", "Gateway · groq"),
        ("gemma-4-31b", "Gateway · nvidia"),
        ("qwen3-coder", "Gateway · groq"),
        ("deepseek-r1", "Gateway · nvidia"),
    ]:
        assert gr._model_allowed_for_tier(mid, "free", prov) is True, mid


def test_filter_tetap_membuang_paid_only_dan_non_chat():
    """Membuka Gate 2 tidak boleh membuka paid-only / non-chat."""
    models = [
        {"id": "llama-3.3-70b", "provider": "Gateway · groq"},
        {"id": "gemini-3.1-pro-preview", "provider": "google_gemini"},
        {"id": "text-embedding-3-small", "provider": "Gateway · openai"},
    ]
    kept = {m["id"] for m in gr.filter_free_models(models)}
    assert "llama-3.3-70b" in kept
    assert "gemini-3.1-pro-preview" not in kept
    assert "text-embedding-3-small" not in kept
