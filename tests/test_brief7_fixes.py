#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regresi Brief 7 — 3 bug lama (Okt 2026).

Setiap tes di bawah GAGAL pada kode sebelum perbaikan:

  Bug A  judge memakai daftar model "rusak" yang HARD-CODE dan salah
         (`gemini-2.5-flash-lite` sehat ikut dibuang) + mati total bila model
         pertama mengembalikan bentuk tak terduga.
  Bug B  tidak ada backpressure in-flight untuk POST /chat -> koneksi panjang
         menumpuk -> Cloudflare Tunnel balas 502 pada konkurensi tinggi.
  Bug C  retry transien Supabase hanya 1x dengan jeda tetap 0.25s -> 58x
         `RemoteProtocolError` tetap lolos jadi 500.
"""
from __future__ import annotations

import pytest


# ===========================================================================
# Bug A — judge_harness
# ===========================================================================
def test_verified_broken_set_is_evidence_based():
    """flash-lite (SEHAT) tidak boleh ada di daftar rusak; dua yang null wajib ada."""
    import judge_harness as JH

    assert "gemini-2.5-flash-lite" not in JH.VERIFIED_BROKEN_MODELS
    assert "gemini-2.5-flash" in JH.VERIFIED_BROKEN_MODELS
    assert "gemini-3-flash-preview" in JH.VERIFIED_BROKEN_MODELS


def test_judge_drops_broken_models_from_candidates():
    import judge_harness as JH

    j = JH.LLMJudge(candidates=["gemini-2.5-flash", "allam-2-7b",
                                "gemini-3-flash-preview"])
    assert j.candidates == ["allam-2-7b"]
    assert j.model == "allam-2-7b"


def test_judge_falls_through_to_working_model(monkeypatch):
    """Model pertama rusak -> judge TETAP lulus lewat kandidat berikutnya."""
    import judge_harness as JH

    j = JH.LLMJudge(candidates=["model-a", "model-b"])
    j.available = True

    def fake_call(model, task, response):
        if model == "model-a":
            return None, "bukan JSON: ''"
        return {"correctness": 1.0, "completeness": 1.0, "safety": 1.0,
                "overall": 0.95, "reason": "ok"}, ""

    monkeypatch.setattr(j, "_call", fake_call)
    res = j.score("task", "response")
    assert res.ok is True
    assert res.scores["overall"] == 0.95
    assert j.model == "model-b"          # benar-benar berpindah model
    assert len(j.last_errors) == 1


def test_judge_all_candidates_fail_is_skip_not_pass(monkeypatch):
    import judge_harness as JH

    j = JH.LLMJudge(candidates=["model-a", "model-b"])
    j.available = True
    monkeypatch.setattr(j, "_call", lambda m, t, r: (None, "HTTP 500"))
    res = j.score("task", "response")
    assert res.ok is None                 # SKIP jujur, bukan lulus
    assert "gagal" in res.detail.lower()


def test_judge_unavailable_when_env_missing(monkeypatch):
    import judge_harness as JH

    monkeypatch.setattr(JH, "load_env", lambda: {})
    j = JH.LLMJudge()
    assert j.available is False
    assert j.score("t", "r").ok is None


def test_judge_prompt_render_safe_with_json_braces():
    """BUG NYATA: JUDGE_PROMPT.format() -> KeyError '"correctness"'.

    Prompt judge memuat contoh JSON literal; `str.format` menafsirkan kurung
    kurawalnya sebagai field. Ini yang membuat judge tak pernah aktif.
    """
    import judge_harness as JH

    out = JH.render_judge_prompt("TASK-UNIK", "RESP-UNIK")
    assert "TASK-UNIK" in out and "RESP-UNIK" in out
    assert '"correctness"' in out            # JSON contoh tetap utuh
    assert "[[TASK]]" not in out and "[[RESPONSE]]" not in out
    # bukti bug lama: memformat JUDGE_PROMPT mentah memang melempar.
    with pytest.raises(KeyError):
        JH.JUDGE_PROMPT.format(task="a", response="b")


# ===========================================================================
# Bug B — ConcurrencyGuard + middleware backpressure
# ===========================================================================
def test_concurrency_guard_bounds_inflight():
    import rate_limit as RL

    g = RL.ConcurrencyGuard(2)
    assert g.try_acquire() is True
    assert g.try_acquire() is True
    assert g.try_acquire() is False      # melebihi batas -> ditolak
    st = g.stats()
    assert st["inflight"] == 2 and st["rejected"] == 1 and st["peak"] == 2
    g.release()
    assert g.try_acquire() is True
    g.reset()
    assert g.stats()["inflight"] == 0 and g.stats()["rejected"] == 0


def test_concurrency_guard_disabled_when_nonpositive():
    import rate_limit as RL

    g = RL.ConcurrencyGuard(0)
    for _ in range(1000):
        assert g.try_acquire() is True   # fail-open
    g.release()                          # tidak error walau tak pernah acquire
    assert g.stats()["max_inflight"] == 0


def test_chat_backpressure_returns_503_retry_after():
    """Guard jenuh -> POST /chat = 503 + Retry-After (SEBELUM auth)."""
    import rate_limit as RL
    from fastapi.testclient import TestClient
    import api_server

    g = RL.chat_inflight_guard
    old = g.max_inflight
    g.max_inflight = 1
    g.reset()
    client = TestClient(api_server.app, raise_server_exceptions=False)
    assert g.try_acquire() is True       # saturasi
    try:
        r = client.post("/chat", json={"prompt": "hai"})
        assert r.status_code == 503, r.text
        assert r.headers.get("Retry-After") == "5"
        assert "sibuk" in r.json()["detail"].lower()
    finally:
        g.release()
        g.max_inflight = old
        g.reset()


def test_chat_not_backpressured_when_free():
    """Saat guard kosong, /chat TIDAK di-503-kan; jalur normal (401 tanpa JWT)."""
    import rate_limit as RL
    from fastapi.testclient import TestClient
    import api_server

    RL.chat_inflight_guard.reset()
    client = TestClient(api_server.app, raise_server_exceptions=False)
    r = client.post("/chat", json={"prompt": "hai"})
    assert r.status_code in (401, 403), r.text   # auth gate, BUKAN 503
    assert RL.chat_inflight_guard.stats()["inflight"] == 0


# ===========================================================================
# Bug C — retry transien Supabase
# ===========================================================================
class RemoteProtocolError(Exception):
    """Nama kelas sengaja identik dgn httpx (dipakai `_is_transient_net`)."""


def test_transient_attempts_default_is_three():
    import database as DB

    assert DB._TRANSIENT_ATTEMPTS >= 3


def test_transient_backoff_grows_and_is_capped():
    import database as DB

    delays = [DB._transient_backoff(i) for i in range(5)]
    # base naik (0.2, 0.4, 0.8 ...) + jitter 0..50% -> monoton naik sampai cap.
    assert delays[0] < delays[1] < delays[2]
    assert all(d <= DB._TRANSIENT_BACKOFF_MAX * 1.5 + 1e-9 for d in delays)


def test_wrap_write_retries_transient_then_succeeds(monkeypatch):
    import database as DB

    sleeps: list[float] = []
    monkeypatch.setattr(DB.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RemoteProtocolError("Server disconnected")
        return "OK"

    out = DB._wrap_write(flaky, "users.select", retry_transient=True)
    assert out == "OK"
    assert calls["n"] == 3               # 2 gagal + 1 sukses
    assert len(sleeps) == 2              # jeda antar percobaan
    assert sleeps[0] > 0 and sleeps[1] > sleeps[0]   # backoff naik


def test_wrap_write_no_retry_when_flag_off(monkeypatch):
    import database as DB

    sleeps: list[float] = []
    monkeypatch.setattr(DB.time, "sleep", lambda s: sleeps.append(s))

    def always_fail():
        raise RemoteProtocolError("Server disconnected")

    with pytest.raises(RemoteProtocolError):
        DB._wrap_write(always_fail, "x", retry_transient=False)
    assert sleeps == []                  # tanpa flag: tidak ada percobaan ulang


def test_wrap_write_gives_up_after_attempts(monkeypatch):
    import database as DB

    monkeypatch.setattr(DB.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise RemoteProtocolError("Server disconnected")

    with pytest.raises(RemoteProtocolError):
        DB._wrap_write(always_fail, "x", retry_transient=True)
    assert calls["n"] == DB._TRANSIENT_ATTEMPTS
