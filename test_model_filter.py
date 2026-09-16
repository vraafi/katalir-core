# test_model_filter.py — Kunci perilaku filter model (3-gerbang paid-only).
#
# KENAPA FILE INI ADA (bukti nyata, bukan teoretis):
#   Sebelumnya `is_paid_only()` / `filter_free_models()` HANYA diverifikasi lewat
#   probe scratch (`_roster_check.py`) dan lewat E2E yang memeriksa roster HASIL
#   PROBE EMPIRIS. Roster itu bergantung liveness upstream: model gratis dirotasi
#   provider. Terbukti dalam satu sesi, rotasi terjadi DUA ARAH —
#     masuk : `mistralai/mistral-nemotron`, `poolside/laguna-xs-2.1`
#     keluar: `gemini-2.5-flash-lite`, `moonshotai/kimi-k3`
#   Akibatnya E2E yang mem-`pin` id tertentu gagal-acak dan menuduh "filter
#   menghapus model valid" padahal gateway yang tidak menyajikannya. Tes flaky
#   begitu justru MENYAMARKAN bug filter sungguhan (gejala "tes hijau tapi user
#   melihat bug").
#
#   Pemisahan tanggung jawab yang benar:
#     - file INI : input terkendali, TANPA jaringan -> mengunci filter secara
#                  deterministik, termasuk jaminan "tidak over-delete".
#     - E2E      : menguji sifat yang stabil pada roster LIVE (tidak ada model
#                  paid-only yang lolos, roster tidak kerdil).
#
#   Setiap kasus di bawah berasal dari pengamatan empiris nyata: `gemini-2.5-pro`
#   & `gemini-3.1-pro-preview` = RPD 0 (paid-only), sedangkan `gemini-2.5-flash`,
#   `gemini-2.5-flash-lite`, `gemini-3-flash-preview`, dan
#   `nvidia/nemotron-3-nano-omni-*` TERBUKTI menjawab chat (X-Routed-Via cocok).

import pytest

from gateway_roster import (
    FREE_TIER_MODEL_IDS,
    chat_capable,
    filter_free_models,
    is_paid_only,
)

G = "google_gemini"   # nama provider keluarga Google di roster gateway
N = "nvidia"
Q = "groq"


# ---------------------------------------------------------------------------
# Gerbang 1 + 2: paid-only WAJIB ditolak
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mid",
    ["gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-4-advanced"],
)
def test_pro_dan_advanced_paid_only(mid):
    """Model Pro/advanced tidak boleh lolos — inti bug "jawaban model lain".

    `gemini-2.5-pro` & `gemini-3.1-pro-preview` RPD 0: gateway mengalihkan
    request ke model lain secara senyap, jadi user menerima jawaban dari model
    yang bukan pilihannya.
    """
    assert is_paid_only(mid, G) is True


def test_allowlist_google_menolak_model_di_luar_daftar():
    """Keluarga google di luar `FREE_TIER_MODEL_IDS` dianggap paid-only.

    Ini gerbang yang paling mudah salah: tanpa gerbang 2, model google BARU
    yang belum terukur (mis. paid-only) langsung muncul di selector.
    """
    assert "gemini-4-ultra" not in FREE_TIER_MODEL_IDS
    assert is_paid_only("gemini-4-ultra", G) is True


# ---------------------------------------------------------------------------
# Jaminan "JANGAN hapus model valid" (constraint tugas: flash, flash-lite, gemma)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mid",
    [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-flash-latest",
        "gemma-4-31b-it",
    ],
)
def test_flash_flashlite_gemma_bukan_paid_only(mid):
    """Model free-tier yang terbukti hidup tidak boleh dianggap paid-only.

    `gemini-2.5-flash-lite` pernah SEMPAT terbuang gerbang allowlist (audit
    before/after 41 -> 13 model). Itu regresi senyap: user kehilangan model
    gratis yang sehat, dan tidak ada tes yang menangkapnya.
    """
    assert is_paid_only(mid, G) is False


@pytest.mark.parametrize(
    "mid,provider",
    [
        ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", N),
        ("nvidia/nemotron-3-ultra-550b-a55b", N),
        ("nvidia/nemotron-3.5-lightning-30b-a3b", N),
        ("groq/compound", Q),
        ("groq/compound-mini", Q),
        ("openai/gpt-oss-20b", Q),
        ("allam-2-7b", Q),
        ("mistralai/mistral-nemotron", N),
        ("poolside/laguna-xs-2.1", N),
        ("moonshotai/kimi-k3", N),
        ("deepseek-ai/deepseek-v4-flash-0731", N),
    ],
)
def test_provider_non_google_lolos_gate_allowlist(mid, provider):
    """Provider non-google dianggap aman: liveness-nya sudah dibuktikan probe.

    Termasuk regresi pola "omni": `nemotron-3-nano-omni` mengandung "omni" dan
    TERBUKTI menjawab chat. Menambahkan "omni" ke `_PAID_ONLY_PATTERNS` akan
    menghapus model hidup — karenanya tidak dipakai.
    """
    assert is_paid_only(mid, provider) is False
    assert chat_capable(mid) is True


@pytest.mark.parametrize(
    "mid,provider,expected",
    [
        ("x/y:free", "openrouter", False),
        ("x/paid-model", "openrouter", True),
        # Provider kosong (pra-probe) hanya boleh menilai gerbang 1.
        ("some-model", "", False),
        ("some-pro-model", "", True),
    ],
)
def test_openrouter_dan_provider_kosong(mid, provider, expected):
    """Gerbang 3 (openrouter `:free`) & perilaku saat provider belum diketahui.

    Gerbang 3 saat ini inert (roster tak memuat openrouter) tetapi harus tetap
    benar: bila provider itu ditambahkan, model berbayar tidak boleh lolos.
    """
    assert is_paid_only(mid, provider) is expected


# ---------------------------------------------------------------------------
# `filter_free_models` — over-delete & non-chat, diuji pada INPUT terkendali
# ---------------------------------------------------------------------------
FREE_IDS = [
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview",
    "mistralai/mistral-nemotron", "poolside/laguna-xs-2.1",
    "moonshotai/kimi-k3", "groq/compound", "groq/compound-mini",
    "openai/gpt-oss-20b", "qwen/qwen3.8-27b",
    "deepseek-ai/deepseek-v4-flash-0731", "allam-2-7b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-lightning-30b-a3b",
]
PAID_IDS = ["gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-pro-latest"]
MEDIA_IDS = [
    "nano-banana-pro-preview", "lyria-3", "gemini-2.5-flash-transcribe",
    "gpt-image-1", "gemini-robotics-1", "imagen-4.0-generate",
]


def _prov(mid: str) -> str:
    """Provider per id, mengikuti roster nyata (google_gemini / groq / nvidia)."""
    if mid.startswith("gemini") or mid.startswith("gemma"):
        return G
    if mid.startswith("groq/") or mid in ("allam-2-7b", "openai/gpt-oss-20b"):
        return Q
    return N


def _catalog() -> list[dict]:
    return [
        {"id": m, "name": m, "provider": _prov(m), "tier": "free"}
        for m in FREE_IDS + PAID_IDS + MEDIA_IDS
    ]


def test_filter_tidak_over_delete_model_valid():
    """JUJURAN INTI: setiap model free di input harus tetap ada di output.

    Tes ini menggantikan cakupan over-deletion yang dulu dipikul E2E terhadap
    roster live. Dengan input terkendali, hasilnya deterministik: model valid
    yang hilang = BUG filter, bukan nasib rotasi provider.
    """
    ids = [m["id"] for m in filter_free_models(_catalog())]
    assert set(ids) == set(FREE_IDS), (
        "filter menghapus/menambah model tak terduga: "
        f"hilang={sorted(set(FREE_IDS) - set(ids))} ekstra={sorted(set(ids) - set(FREE_IDS))}"
    )


def test_filter_membuang_paid_only_dan_media():
    """Paid-only & non-chat/media WAJIB hilang dari output."""
    ids = [m["id"] for m in filter_free_models(_catalog())]
    for bad in PAID_IDS + MEDIA_IDS:
        assert bad not in ids, f"model paid-only/media lolos filter: {bad}"


def test_filter_mempertahankan_field_entri():
    """Field entri (name/provider/tier) tidak boleh hilang saat difilter.

    UI memakai field ini untuk menandai model terkunci per tier; entri yang
    kehilangan field merender selector dengan label kosong.
    """
    out = filter_free_models(_catalog())
    assert out, "filter mengembalikan daftar kosong"
    for m in out:
        assert {"id", "name", "provider", "tier"} <= set(m)


def test_filter_tahan_input_kotor():
    """Entri tanpa id/duplikat/None tidak boleh membuat filter meledak.

    Duplikat SENGAJA dipertahankan: filter ini menyaring jenis model, bukan
    mendeduplikasi (dedup dilakukan di sisi roster/probe). Mengubahnya di sini
    akan mengubah kontrak yang tidak diminta.
    """
    dirty = [
        {"id": "", "name": "kosong"},
        {"id": None},
        {},
        {"id": "groq/compound", "name": "a", "provider": Q},
        {"id": "groq/compound", "name": "b", "provider": Q},
        None,
    ]
    out = filter_free_models(dirty)  # type: ignore[arg-type]
    assert [m["id"] for m in out] == ["groq/compound", "groq/compound"]

