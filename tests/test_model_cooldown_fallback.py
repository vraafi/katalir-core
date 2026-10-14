"""Fallback model saat SEMUA kunci model yang diminta cooldown (kuota).

Temuan 14 Okt 2026 (`docs/final-verdict-2026-10-14.md` §5.2): frontend memakai
default `google/gemma-4-31b-it` (terkonfirmasi di bundle produksi). Bila seluruh
kunci model itu sedang cooldown, `_agentic_run_direct` langsung membalas 503 —
sehingga pengguna baru melihat kartu galat pada SETIAP pesan, padahal kunci model
LAIN masih sehat. 13 dari 15 FAIL regresi 14 Okt berasal dari kondisi ini.

Kontrak yang dikunci tes ini:
  1. model diminta cooldown + ada model lain siap  -> PAKAI cadangan, BUKAN 503;
  2. SELURUH rantai kehabisan kunci                -> 503 (kapasitas nyata);
  3. rantai cadangan hanya berisi id Gemini & tidak mengulang model yang diminta.

Deterministik: `gemini_key_pool.pool()` diganti stub — tanpa jaringan, tanpa DB.
"""
from __future__ import annotations

import pathlib
import sys

import pytest
from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402

REQUESTED = "google/gemma-4-31b-it"


class _Stop(Exception):
    """Sentinel: klien dibuat -> berarti model sudah terpilih (fallback sukses)."""


class _StubPool:
    """Pool palsu: `ready` = himpunan model yang masih punya kunci siap."""

    def __init__(self, ready: set[str]) -> None:
        self.ready = ready
        self.calls: list[str] = []

    @property
    def size(self) -> int:
        return 13

    def acquire(self, model: str = ""):
        self.calls.append(model)
        return (f"fp-{model}", "kunci-palsu") if model in self.ready else None

    def label(self, fp: str) -> str:
        return fp

    def client(self, fp: str):
        raise _Stop(fp)


def _pasang(monkeypatch, ready: set[str]) -> _StubPool:
    pool = _StubPool(ready)
    monkeypatch.setattr(api_server.gemini_key_pool, "pool", lambda: pool)
    monkeypatch.setattr(api_server, "_gateway_target", lambda: None)
    # Isolasi cabang acquire: resolusi model dianggap menerima permintaan apa adanya.
    monkeypatch.setattr(api_server, "_resolve_model",
                        lambda m, t: (REQUESTED, False, None))
    return pool


def test_rantai_cadangan_hanya_gemini_dan_tanpa_model_diminta():
    chain = api_server._cooldown_fallback_chain(REQUESTED)
    assert REQUESTED not in chain
    assert "gemini-3.5-flash-lite" in chain
    assert "gemini-2.5-flash" in chain
    assert all(m.startswith("gemini-") for m in chain), chain
    assert "moonshotai/kimi-k3" not in chain  # id gateway -> 404 di genai.Client
    assert len(chain) == len(set(chain))      # tanpa duplikat


def test_model_diminta_cooldown_dilayani_cadangan_bukan_503(monkeypatch):
    """Inti perbaikan: gemma cooldown TIDAK lagi mematikan request."""
    pool = _pasang(monkeypatch, {"gemini-3.5-flash-lite", "gemini-2.5-flash"})

    with pytest.raises(_Stop):  # lanjut sampai membuat klien -> tidak ada 503
        api_server._agentic_run_direct("hai", "uji@test.dev",
                                       model=REQUESTED, user_tier="free")

    assert pool.calls[0] == REQUESTED, pool.calls
    assert "gemini-3.5-flash-lite" in pool.calls, pool.calls
    assert len(pool.calls) >= 2, pool.calls


def test_semua_rantai_habis_tetap_503(monkeypatch):
    """Kapasitas nyata habis -> 503 tetap benar (jangan ditutupi)."""
    pool = _pasang(monkeypatch, set())

    with pytest.raises(HTTPException) as info:
        api_server._agentic_run_direct("hai", "uji@test.dev",
                                       model=REQUESTED, user_tier="free")

    assert info.value.status_code == 503
    assert "kuota" in str(info.value.detail).lower()
    # sudah mencoba seluruh rantai sebelum menyerah
    assert len(pool.calls) > 1, pool.calls
