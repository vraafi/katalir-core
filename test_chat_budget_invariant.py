"""Regression guard: anggaran waktu `/chat` backend vs kesabaran klien.

BUG YANG DIJAGA (2026-09-16, terbukti di E2E produksi):
    `LLM_GATEWAY_BUDGET` (default lama) = 90s — SAMA PERSIS dengan
    `FETCH_TIMEOUT_MS` frontend (90s) — dan fase Gemini cadangan tidak dibatasi
    sama sekali. Akibatnya backend masih bekerja ketika klien sudah membatalkan
    request: user melihat "Server lambat, coba lagi" padahal jawabannya hampir
    siap, dan pekerjaan itu terbuang.

Yang membuat bug ini berbahaya adalah ia hidup di DUA lapisan (Python + TS) yang
tidak pernah saling memeriksa. Tes ini sengaja MEMBACA konstanta TS dari sumber
frontend, sehingga perubahan salah satu sisi tanpa sisi lain akan gagal di sini
— bukan diam-diam di produksi.
"""
from __future__ import annotations

import pathlib
import re

import api_server

FRONTEND_API_TS = (
    pathlib.Path(__file__).resolve().parent / "nexus-frontend" / "src" / "lib" / "api.ts"
)


def _client_timeout_ms() -> float:
    """`FETCH_TIMEOUT_MS` dari sumber frontend (satu sumber kebenaran)."""
    text = FRONTEND_API_TS.read_text(encoding="utf-8")
    m = re.search(r"FETCH_TIMEOUT_MS\s*=\s*([0-9_]+)", text)
    assert m, "FETCH_TIMEOUT_MS tidak ditemukan di src/lib/api.ts (konstanta dipindah?)"
    return float(m.group(1).replace("_", ""))


def test_budget_total_lebih_kecil_dari_timeout_klien():
    """`/chat` WAJIB selesai sebelum klien membatalkan request."""
    client_s = _client_timeout_ms() / 1000.0
    budget = api_server._llm_budget_sec()
    assert budget < client_s, (
        f"anggaran total {budget}s tidak lebih kecil dari abort klien {client_s}s "
        "-> backend masih bekerja saat klien sudah menyerah"
    )


def test_fase_gateway_menyisakan_jatah_untuk_fallback_gemini():
    """Habisnya anggaran gateway tidak mengubah outage menjadi error ke user."""
    budget = api_server._llm_budget_sec()
    gateway_phase = max(5.0, budget - api_server._FALLBACK_RESERVE_SEC)
    assert gateway_phase < budget
    assert api_server._FALLBACK_RESERVE_SEC > 0


def test_timeout_satu_percobaan_tidak_menelan_seluruh_anggaran():
    """Satu model yang menggantung tak boleh menghabiskan anggaran sendirian."""
    assert api_server._gateway_attempt_timeout_sec() < api_server._llm_budget_sec()


def test_override_env_dihormati_dan_dijepit_batas_wajar(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_BUDGET", "12")
    monkeypatch.setenv("LLM_GATEWAY_TIMEOUT", "3")
    assert api_server._llm_budget_sec() == 12.0
    assert api_server._gateway_attempt_timeout_sec() == 5.0  # dijepit minimum 5s


def test_nilai_env_rusak_tidak_mematikan_request(monkeypatch):
    """Konfigurasi salah -> pakai default, bukan crash 500 di tengah request."""
    monkeypatch.setenv("LLM_GATEWAY_BUDGET", "bukan-angka")
    monkeypatch.setenv("LLM_GATEWAY_TIMEOUT", "")
    assert api_server._llm_budget_sec() == api_server._LLM_BUDGET_DEFAULT_SEC
    assert api_server._gateway_attempt_timeout_sec() == 20.0