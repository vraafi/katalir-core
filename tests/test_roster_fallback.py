# tests/test_roster_fallback.py
"""Kontrak roster gateway (temuan 2026-09-19: fallback Gemini SENYAP).

Yang dijaga di sini bukan "apakah gateway hidup", tapi **apakah kondisi
degradasi terlihat**. User pernah melihat dropdown hanya berisi model Google
karena roster gateway kosong lalu discovery diam-diam memakai daftar Gemini —
tanpa satu pun sinyal di UI.

Semua test memalsukan HTTP (tidak menyentuh jaringan) dan memakai
`monkeypatch` pada titik yang memang sumbernya: `_get_json_retry`,
`fetch_gemini_models`, serta cache.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gateway_roster as gr  # noqa: E402
import model_discovery as md  # noqa: E402


@pytest.fixture(autouse=True)
def _bersih():
    """Reset state global sebelum/sesudah tiap test (module-level cache)."""
    def _reset():
        md._cache = {"ts": 0.0, "models": []}
        md._state = {"source": "unknown", "degraded": False, "reason": ""}
        gr._cache = {"ts": 0.0, "models": []}
        gr._state = {"source": "unknown", "reason": "", "ts": 0.0, "cache_age_s": None}
    _reset()
    yield
    _reset()


def _gateway_env(monkeypatch, url="https://gw.test"):
    monkeypatch.setenv("LLM_GATEWAY_URL", url)
    monkeypatch.setenv("LLM_GATEWAY_KEY", "kunci-uji")


def _models_api(n=3):
    return {"data": [{"id": f"uji/m{i}"} for i in range(n)]}
def test_gateway_ok_returns_gateway_source(monkeypatch):
    _gateway_env(monkeypatch)
    monkeypatch.setattr(gr, "_load_cache", lambda: {"ts": 0.0, "models": []})
    monkeypatch.setattr(gr, "_save_cache", lambda ts, models: None)

    def fake_get(client, url, hdr, attempts=gr.LIST_ATTEMPTS):
        if url.endswith("/v1/models"):
            return _models_api(2)
        raise RuntimeError("status endpoint tidak dipakai di test ini")

    monkeypatch.setattr(gr, "_get_json_retry", fake_get)
    monkeypatch.setattr(gr, "_probe_one", lambda client, url, key, cand, nonce, i: {
        "status": "PASS", "model": cand["id"], "provider": "groq", "ms": 12,
    })

    models = md.get_available_models(force_refresh=True)

    assert models, "roster harus terisi dari gateway"
    h = md.discovery_health()
    assert h["source"] == "gateway"
    assert h["degraded"] is False


def test_gateway_timeout_uses_cache_degraded(monkeypatch):
    _gateway_env(monkeypatch)
    cache_lama = {"ts": time.time() - 60,
                  "models": [{"model": "cache/roster", "provider": "groq", "ms": 5}]}
    monkeypatch.setattr(gr, "_load_cache", lambda: cache_lama)

    def fake_get(client, url, hdr, attempts=gr.LIST_ATTEMPTS):
        raise RuntimeError("timeout")

    monkeypatch.setattr(gr, "_get_json_retry", fake_get)
    monkeypatch.setattr(gr, "_save_cache", lambda ts, models: None)

    models = md.get_available_models(force_refresh=True)
    ids = [m["id"] for m in models]
    assert "cache/roster" in ids, ids
    h = md.discovery_health()
    assert h["degraded"] is True, "cache basi WAJIB ditandai degraded"
    assert h["source"] in ("cache", "gateway"), h


def test_gateway_timeout_no_cache_falls_back_gemini_degraded(monkeypatch):
    _gateway_env(monkeypatch)
    monkeypatch.setattr(gr, "_load_cache", lambda: {"ts": 0.0, "models": []})

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(gr, "_get_json_retry", boom)
    monkeypatch.setattr(gr, "_save_cache", lambda ts, models: None)
    monkeypatch.setattr(md, "fetch_gemini_models", lambda: [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash",
         "provider": "Google (Gemini)", "tier": "free"},
    ])

    models = md.get_available_models(force_refresh=True)

    ids = [m["id"] for m in models]
    # Daftar fallback = Gemini direct (+ gemini-1.5-pro dari PLUS_CHAT_MODELS);
    # yang penting: TIDAK ada satu pun model gateway, dan degradasi terlihat.
    assert "gemini-2.5-flash" in ids, ids
    assert all("Gateway" not in (m.get("provider") or "") for m in models), ids
    h = md.discovery_health()
    assert h["source"] == "gemini_fallback"
    assert h["degraded"] is True
    assert h["reason"], "degradasi tanpa alasan tidak bisa didiagnosis"


def test_gateway_not_configured_returns_gemini_only(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setattr(md, "fetch_gemini_models", lambda: [
        {"id": "gemma-4-31b-it", "name": "Gemma 4 31B",
         "provider": "Google (Gemini)", "tier": "free"},
    ])

    models = md.get_available_models(force_refresh=True)
    assert models
    h = md.discovery_health()
    assert h["source"] == "gemini_only"
    assert h["degraded"] is False, "tanpa gateway, Gemini-only bukan degradasi"


def test_retry_3x_with_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gr.time, "sleep", lambda s: sleeps.append(s))

    class _Client:
        def __init__(self):
            self.attempts = 0

        def get(self, url, headers=None):
            self.attempts += 1
            raise RuntimeError("gagal terus")

    c = _Client()
    with pytest.raises(RuntimeError):
        gr._get_json_retry(c, "https://gw.test/v1/models", {}, attempts=3)

    assert c.attempts == 3, "harus 3 percobaan"
    assert len(sleeps) == 2, "backoff hanya ANTAR percobaan"
    assert sleeps[0] < sleeps[1], "backoff harus meningkat (eksponensial)"


def test_retry_recovers_on_second_attempt(monkeypatch):
    monkeypatch.setattr(gr.time, "sleep", lambda s: None)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "pulih/model"}]}

    class _Client:
        def __init__(self):
            self.attempts = 0

        def get(self, url, headers=None):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("gagal sekali")
            return _Resp()

    c = _Client()
    out = gr._get_json_retry(c, "https://gw.test/v1/models", {}, attempts=3)
    assert c.attempts == 2, "harus berhenti begitu berhasil"
    assert out["data"][0]["id"] == "pulih/model"
