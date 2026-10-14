"""Gerbang produk: model yang ADA di roster tetapi TIDAK BOLEH ditawarkan.

Latar (14 Okt 2026, `docs/final-verdict-v4-2026-10-14.md` §6.1):
`google/gemma-4-31b-it` masih ada di roster gateway (258 id) dan LULUS semua
gerbang (chat-capable, bukan paid-only, ada di allowlist), sehingga ia MUNCUL
di picker sebagai model gratis. Tetapi seluruh kunci model itu cooldown kuota:
setiap request ditandai `fallback=true / model_unavailable` dan pengguna melihat
spanduk "Model yang Anda pilih tidak tersedia" di SETIAP pesan. Latensinya di
roster juga 52985 ms.

Keputusan produk: pilihan itu DIHAPUS dari picker (`NOT_OFFERED_MODEL_IDS`),
tanpa menyentuh `model_discovery` — karena `get_available_models()` juga dipakai
`_resolve_model` dan `_bucket_model_id` (bucket kuota "gemma"). Memfilter di
sana akan mengubah perilaku kuota/resolusi, di luar maksud perubahan.

Kontrak yang dikunci tes ini:
  1. `is_offered_model()` menolak gemma (kedua bentuk id) dan meloloskan sisanya;
  2. `GET /models` MEMBUANG gemma dari daftar, dan melaporkannya di
     `not_offered_filtered` (bisa diaudit, bukan hilang senyap);
  3. `GET /models` TIDAK membuang model lain (tanpa over-delete);
  4. `md.get_available_models()` TETAP memuat gemma -> kuota & resolusi model
     tidak berubah (penjaga agar gerbang tidak "dipindah" ke discovery).

Deterministik: tanpa jaringan, tanpa DB, tanpa kunci API.
"""
from __future__ import annotations

import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402

GEMMA = "google/gemma-4-31b-it"
GEMMA_BARE = "gemma-4-31b-it"

#: Roster palsu: sengaja MENIRU produksi (gemma hadir bersama model lain).
ROSTER = [
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash",
     "provider": "Gateway · google_gemini", "tier": "free"},
    {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite",
     "provider": "Gateway · google_gemini", "tier": "free"},
    {"id": GEMMA, "name": "Gemma 4 31B It",
     "provider": "Gateway · nvidia", "tier": "free"},
    {"id": "moonshotai/kimi-k3", "name": "Kimi K3",
     "provider": "Gateway · moonshot", "tier": "free"},
]


# ---------------------------------------------------------------------------
# 1. Unit: helper gerbang
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mid", [GEMMA, GEMMA_BARE, f"  {GEMMA}  "])
def test_gemma_tidak_ditawarkan(mid: str) -> None:
    assert api_server.is_offered_model(mid) is False


@pytest.mark.parametrize("mid", [
    "gemini-3.5-flash-lite", "gemini-2.5-flash", "moonshotai/kimi-k3",
    "deepseek-ai/deepseek-v4-flash-0731", "nvidia/nemotron-3-ultra-550b-a55b",
])
def test_model_lain_tetap_ditawarkan(mid: str) -> None:
    assert api_server.is_offered_model(mid) is True


def test_id_kosong_tidak_dianggap_gemma() -> None:
    """Id kosong bukan alasan untuk menolak; pembuangan id kosong urusan roster."""
    assert api_server.is_offered_model("") is True


# ---------------------------------------------------------------------------
# 2-3. Endpoint: /models
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient dengan auth + DB + discovery di-stub (tanpa jaringan)."""
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda authorization=None: {"email": "uji@contoh.dev",
                                                    "id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(api_server.db, "get_or_create_user",
                        lambda *a, **k: {"email": "uji@contoh.dev", "tier": "free"})
    monkeypatch.setattr(api_server.db, "effective_tier", lambda t: "free")
    monkeypatch.setattr(api_server.md, "get_available_models", lambda *a, **k: [dict(m) for m in ROSTER])
    monkeypatch.setattr(api_server.md, "discovery_health",
                        lambda: {"source": "gateway", "degraded": False, "reason": ""})
    # `_default_model_id()` menembak gateway -> ganti agar tes tidak menyentuh jaringan.
    monkeypatch.setattr(api_server, "_default_model_id", lambda: "gemini-3.5-flash-lite")
    # Endpoint membaca `md._cache["ts"]` untuk `refreshed_at`.
    monkeypatch.setitem(api_server.md._cache, "ts", time.time())
    return TestClient(api_server.app)


def test_models_membuang_gemma(client: TestClient) -> None:
    r = client.get("/models")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [m["id"] for m in body["models"]]
    assert GEMMA not in ids, f"gemma masih ditawarkan di picker: {ids}"
    assert GEMMA_BARE not in ids


def test_models_melaporkan_yang_dibuang(client: TestClient) -> None:
    """Pembuangan harus TERLIHAT, bukan senyap.

    Tanpa field ini, "gemma tidak ada di /models" tidak bisa dibedakan dari
    "kebetulan roster sedang tidak memuat gemma" — dan itulah tepatnya kenapa
    bug ini lolos sekian lama.
    """
    body = client.get("/models").json()
    assert body.get("not_offered_filtered") == [GEMMA], body.get("not_offered_filtered")


def test_models_tidak_over_delete(client: TestClient) -> None:
    """Sisa roster harus UTUH — gerbang tidak boleh menyerempet model lain."""
    body = client.get("/models").json()
    ids = {m["id"] for m in body["models"]}
    assert ids == {"gemini-2.5-flash", "gemini-3.5-flash-lite", "moonshotai/kimi-k3"}
    assert body["default"] == "gemini-3.5-flash-lite"


def test_models_tetap_200_saat_roster_tanpa_gemma(
    monkeypatch: pytest.MonkeyPatch, client: TestClient,
) -> None:
    """Roster tanpa gemma -> 200 dan tidak ada yang dilaporkan dibuang."""
    tanpa = [m for m in ROSTER if m["id"] != GEMMA]
    monkeypatch.setattr(api_server.md, "get_available_models", lambda *a, **k: [dict(m) for m in tanpa])
    body = client.get("/models").json()
    assert body["not_offered_filtered"] == []
    assert len(body["models"]) == len(tanpa)


# ---------------------------------------------------------------------------
# 4. Penjaga: gerbang TIDAK boleh pindah ke discovery
# ---------------------------------------------------------------------------
def test_discovery_tidak_difilter_gerbang_produk() -> None:
    """`get_available_models()` sengaja TIDAK memuat gerbang produk.

    Ia dipakai `_resolve_model` (menandai fallback) dan `_bucket_model_id`
    (bucket kuota "gemma" -> model gratis). Memfilter di sana akan mengubah
    perilaku kuota — gerbang produk harus tetap di endpoint /models.
    """
    import inspect

    src = inspect.getsource(api_server.md.get_available_models)
    assert "NOT_OFFERED_MODEL_IDS" not in src
    assert "is_offered_model" not in src


def test_bucket_kuota_gemma_tetap_menemukan_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bucket kuota "gemma" (jalur GRATIS) tidak boleh ikut kosong.

    Inilah alasan gerbangnya dipasang di endpoint, bukan di discovery:
    `_bucket_model_id("gemma")` mencari id ber-"gemma" di roster. Bila gerbang
    dipindah ke `get_available_models()`, fungsi ini mengembalikan None dan
    penegakan kuota jalur gratis kehilangan model acuannya.
    """
    monkeypatch.setattr(api_server.md, "get_available_models",
                        lambda *a, **k: [dict(m) for m in ROSTER])
    assert api_server._bucket_model_id("gemma") == GEMMA
