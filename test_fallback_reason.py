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

DIPERBARUI (FASE 4, 2026-09-22) -- dua hal berubah dan keduanya lebih baik:
    1. Frontend TIDAK LAGI memetakan kode `fallback_reason` menjadi teks UI.
       Penerjemahan status HTTP kini terpusat di `classifyHttpError`
       (`src/lib/api.ts`), dan tuduhan tier TIDAK ADA di sana sama sekali.
       Pesan tier yang akurat sekarang hidup di pemilih model (ikon kunci +
       keterangan "Plus"), tempat user benar-benar memilih model.
    2. Karena itu assertion lama (`case "overloaded"` di page.tsx) memeriksa kode
       yang memang sudah tidak pernah ditulis lagi -> merah permanen yang
       MENYESATKAN (dilaporkan sebagai utang teknis di FASE 3, diperbaiki di
       FASE 4). Tes diganti menjadi kontrak yang MEMANG berlaku sekarang.
"""
from __future__ import annotations

import pathlib
import re

import api_server

API_TS = (
    pathlib.Path(__file__).resolve().parent / "nexus-frontend" / "src" / "lib" / "api.ts"
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


def test_5xx_tidak_pernah_diterjemahkan_sebagai_tuduhan_tier():
    """Lintas-lapisan: kegagalan gateway (5xx) -> "server sibuk", bukan tier.

    Kontrak yang berlaku sekarang (dibaca dari modul penerjemah error yang
    BENAR-BENAR dipakai UI):
      a. 503 punya pesan sendiri yang menyebut "sibuk" dan ditandai retryable
         (5xx gateway = transien, user boleh coba lagi) -- TIDAK dianggap
         masalah tier;
      b. 500 juga punya pesan sendiri (bukan angka status telanjang);
      c. modul itu tidak memuat tuduhan tier sama sekali.
    """
    assert API_TS.exists(), f"modul penerjemah error hilang: {API_TS}"
    src = API_TS.read_text(encoding="utf-8")

    # 7 Okt 2026: pesan server (`detail`) kini DIPAKAI BILA ADA, dengan pesan
    # per-status sebagai fallback -> bentuknya `message: serverMsg || "..."`.
    # Regex dibuat toleran terhadap bentuk itu (dan tetap menangkap pesan
    # fallback per-status yang menjadi kontrak asli tes ini).
    _MSG = r'message:\s*(?:serverMsg\s*\|\|\s*)?"([^"]+)"'
    busy = re.search(
        rf'case 503:\s*return \{{\s*{_MSG}\s*,\s*retryable:\s*(\w+)\s*,?\s*\}}',
        src)
    assert busy, "503 tidak punya pesan khusus di classifyHttpError (5xx tak diterjemahkan)"
    assert "sibuk" in busy.group(1), f"pesan 503 tidak menyebut sibuk: {busy.group(1)!r}"
    assert busy.group(2) == "true", "503 harus retryable (gateway transien)"

    srv = re.search(
        rf'case 500:\s*return \{{\s*{_MSG}\s*,\s*retryable:\s*(\w+)\s*,?\s*\}}',
        src)
    assert srv, "500 tidak punya pesan khusus di classifyHttpError"
    assert TIER_TEXT not in src and "tier" not in srv.group(1).lower(), (
        "error 5xx tidak boleh diterjemahkan sebagai masalah tier"
    )
    # Kontrak baru (BAGIAN 5 brief 7 Okt): `detail` server diteruskan ke UI.
    assert "detail" in src, "classifyHttpError harus menerima `detail` server"

