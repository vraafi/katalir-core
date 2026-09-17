"""Regression guard: klasifikasi `fallback_reason` untuk 5xx gateway.

BUG YANG DIJAGA (2026-09-17, terbukti di produksi):
    Memilih `groq/compound` di `/models` (roster gateway) tetapi `/chat`
    menjawab lewat `gemini-2.5-flash` dengan badge *"Model tidak tersedia untuk
    tier Anda"*. Padahal itu tuduhan tier yang SALAH: `PLUS_CHAT_MODELS` hanya
    `{"gemini-1.5-pro"}`, dan id `groq/compound` ADA di daftar discovery.

    Rantai sebenarnya: `_agentic_run_gateway` selalu `bind_tools`, dan kandidat
    `groq/compound` + tools ditolak hulu dengan body polos
    **"Internal Server Error"** (500) — terbukti: tanpa tools 200, dengan tools
    500. `_fallback_reason` lalu jatuh ke default `model_unavailable` karena
    teks itu tidak memuat `"internal error"` (terpisah kata "server") maupun
    digit `"500"`, sehingga user dituduh masalah tier padahal murni 5xx gateway.

    Tes ini juga MEMBACA pemetaan frontend, karena kode ini hanya berguna bila
    benar-benar diterjemahkan ke bahasa manusia (pola sama dengan
    `test_chat_budget_invariant.py`: dua lapisan yang tidak pernah saling
    memeriksa = bug hidup diam-diam).
"""
from __future__ import annotations

import pathlib
import re

import api_server

PAGE_TSX = (
    pathlib.Path(__file__).resolve().parent / "nexus-frontend" / "src" / "app" / "page.tsx"
)

TIER_TEXT = "Model tidak tersedia untuk tier Anda"


def test_500_polos_gateway_tidak_lagi_menuduh_tier():
    """"Internal Server Error" (body polos gateway) -> `overloaded`, bukan tier."""
    err = api_server.HTTPException(500, "Internal Server Error")
    assert api_server._fallback_reason(err) == "overloaded"


def test_500_variasi_teks_lain_juga_overloaded():
    """5xx dari lapisan berbeda (SDK/LangChain/HTTPException) tetap satu kategori."""
    for text in (
        "500 Server Error: POST /v1/chat/completions",
        "InternalServerError",
        "internal server error",
        "503 Service Unavailable",
        "The model is overloaded",
    ):
        assert api_server._fallback_reason(text) == "overloaded", text


def test_teks_kosong_dan_tak_dikenal_tetap_model_unavailable():
    """Perilaku lama yang disengaja: tanpa sinyal apa pun -> tak tersedia."""
    assert api_server._fallback_reason("") == "model_unavailable"
    assert api_server._fallback_reason(None) == "model_unavailable"
    assert api_server._fallback_reason("sesuatu yang aneh") == "model_unavailable"


def test_404_dan_410_tetap_model_unavailable():
    """Id yang benar-benar tak diserve hulu tetap dilaporkan tak tersedia."""
    for text in ("404 Not Found", "410 Gone", "model tidak dikenal", "model not found"):
        assert api_server._fallback_reason(text) == "model_unavailable", text


def test_kuota_dimenangkan_atas_rate_limit():
    """Invariant terdokumentasi: 429 Gemini memuat keduanya, kuota lebih berguna."""
    text = "429 quota exceeded: rate limit reached for gemini-2.5-flash"
    assert api_server._fallback_reason(text) == "quota_exhausted"


def test_kode_overloaded_dikenali_dan_beda_dari_tuduhan_tier():
    """Lintas-lapisan: `overloaded` wajib punya terjemahan sendiri di frontend."""
    src = PAGE_TSX.read_text(encoding="utf-8")
    hit = re.search(r'case "overloaded":\s*return "([^"]+)"', src)
    assert hit, 'case "overloaded" hilang dari page.tsx (kode backend tak diterjemahkan)'
    assert hit.group(1) != TIER_TEXT, (
        "`overloaded` (5xx gateway) tidak boleh diterjemahkan sama dengan "
        "`model_unavailable` — itu justru tuduhan tier yang salah"
    )
    tier = re.search(r'case "model_unavailable":\s*return "([^"]+)"', src)
    assert tier and tier.group(1) == TIER_TEXT, (
        "`model_unavailable` harus tetap berarti masalah tier/keberadaan model"
    )
