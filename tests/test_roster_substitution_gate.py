"""tests/test_roster_substitution_gate.py — gerbang substitusi X-Routed-Via.

BUG ASLI (2026-10-01): `X-Routed-Via` dari gateway bisa berlapis -
"nvidia/google/gemma-4-31b-it" berarti provider nvidia, upstream google.
Kode lama memecah dengan `routed.partition("/")` yang HANYA memisah di
slash PERTAMA, sehingga `rmodel` = "google/gemma-4-31b-it" dan tidak pernah
sama dengan `mid` = "gemma-4-31b-it". Akibatnya:

  * model yang hidup ditolak sebagai "disubstitusi" -> roster kosong
  * `/models` jatuh ke GEMINI_FALLBACK (hanya 3 model)
  * user tidak pernah melihat katalog padahal gateway punya 259 model

Yang tetap HARUS ditolak: substitusi sungguhan, mis.
gemini-1.5-pro -> nemotron-3-super-120 (beda keluarga model).

Diuji tanpa jaringan: hanya logika parsing header.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _routed_matches(routed: str, mid: str) -> bool:
    """Salinan logika gerbang di `gateway_roster._probe_one`.

    BUG FIX 2026-10-02: dulu `return rmodel == mid` saja. Itu menolak model
    hidup yang id-nya ber-namespace. Sekarang terima bila path LENGKAP atau
    segmen terakhir cocok - keduanya menunjuk model yang sama.
    """
    _rprov, _, rpath = routed.partition("/")
    rmodel = rpath.rsplit("/", 1)[-1]
    return rpath == mid or rmodel == mid


# (X-Routed-Via, id yang diminta, harus_lolos)
CASES = [
    # Header BERLAPIS -> harus LOLOS (kasus yang rusak sebelum fix)
    ("nvidia/google/gemma-4-31b-it", "gemma-4-31b-it", True),
    ("google_gemini/gemini-2.5-flash", "gemini-2.5-flash", True),
    # 2) Segmentasi tunggal -> tetap lolos
    ("google_gemini/gemini-1.5-pro", "gemini-1.5-pro", True),
    # 3) Substitusi sungguhan -> HARUS DITOLAK
    ("nvidia/nvidia/nemotron-3-super-120", "gemini-1.5-pro", False),
    ("groq/llama-3.3-70b-versatile", "gemini-1.5-pro", False),
    # 4) Alias mati yang dijawab model lain -> ditolak
    ("nvidia/gemma-4-31b-it", "gemma-3-27b-it", False),
    # 5) BUG 2026-10-02: id ber-namespace (bentuk yang DIHASILKAN gateway).
    #    Semua ini HTTP 200 saat diuji langsung, tapi lama ditolak karena
    #    segmen terakhir ("glm-5.3") != mid ("z-ai/glm-5.3").
    ("nvidia/z-ai/glm-5.3", "z-ai/glm-5.3", True),
    ("nvidia/z-ai/glm-5.3-flash", "z-ai/glm-5.3-flash", True),
    ("groq/qwen/qwen3.8-27b", "qwen/qwen3.8-27b", True),
    ("groq/openai/gpt-oss-20b", "openai/gpt-oss-20b", True),
    ("nvidia/meta/muse-glimmer-30b", "meta/muse-glimmer-30b", True),
    ("nvidia/moonshotai/kimi-k3", "moonshotai/kimi-k3", True),
    ("nvidia/nvidia/nemotron-3-ultra-550b-a55b",
     "nvidia/nemotron-3-ultra-550b-a55b", True),
    # 6) Namespaced TETAP ditolak kalau diarahkan ke model lain
    ("groq/openai/gpt-oss-120b", "z-ai/glm-5.3", False),
    ("nvidia/google/gemma-3-27b-it", "z-ai/glm-5.3", False),
]


def _probe_with_routed(routed: str, mid: str) -> dict:
    """Jalankan `_probe_one` produksi dengan response tiruan.

    Menguji helper salinan riskskip regresi: logika test bisa benar sementara
    kode produksi salah. Di sini client di-stub, jadi yang diuji adalah kode
    produksi yang sebenarnya.
    """
    import gateway_roster as gr

    class _Resp:
        status_code = 200
        headers = {"x-routed-via": routed}
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class _Client:
        def post(self, *a, **k):
            return _Resp()

    rec = gr._probe_one(_Client(), "http://gw", "k", {"id": mid, "providers": set()},
                        "123", 0)
    return rec


def test_probe_produksi_menerima_id_ber_namespace():
    """Regresi BUG #2: id ber-namespace harus PASS di `_probe_one` asli."""
    for mid, routed in [
        ("z-ai/glm-5.3", "nvidia/z-ai/glm-5.3"),
        ("qwen/qwen3.8-27b", "groq/qwen/qwen3.8-27b"),
        ("openai/gpt-oss-20b", "groq/openai/gpt-oss-20b"),
        ("meta/muse-glimmer-30b", "nvidia/meta/muse-glimmer-30b"),
        ("google/gemma-4-31b-it", "nvidia/google/gemma-4-31b-it"),
        ("allam-2-7b", "groq/allam-2-7b"),
    ]:
        rec = _probe_with_routed(routed, mid)
        assert rec["status"] == "PASS", (
            f"model hidup {mid!r} (routed={routed!r}) ditolak: {rec['error']!r}")


def test_probe_produksi_masih_menolak_substitusi():
    """Dilonggarnya perbandingan TIDAK boleh membocorkan model lain."""
    for mid, routed in [
        ("gemini-1.5-pro", "nvidia/nvidia/nemotron-3-super-120"),
        ("z-ai/glm-5.3", "groq/openai/gpt-oss-120b"),
        ("gemma-3-27b-it", "nvidia/gemma-4-31b-it"),
    ]:
        rec = _probe_with_routed(routed, mid)
        assert rec["status"] != "PASS", (
            f"substitusi nyata {mid!r} <- {routed!r} TIDAK BOLEH lolos")
        assert "disubstitusi" in rec["error"], rec["error"]


def test_gate_lolos_untuk_header_berlapis():
    """Regresi utama: header berlapis TIDAK boleh salah ditolak."""
    for routed, mid, expected in CASES:
        got = _routed_matches(routed, mid)
        assert got is expected, (
            f"X-Routed-Via={routed!r} vs id={mid!r} -> harus "
            f"{'LOLOS' if expected else 'DITOLAK'}, hasil={got}")


def test_substitusi_asli_masih_ditolak():
    """Gerbang tidak boleh dilonggarkan sampai membiarkan model lain lolos."""
    for routed, mid in [
        ("nvidia/nvidia/nemotron-3-super-120", "gemini-1.5-pro"),
        ("groq/llama-3.3-70b-versatile", "gemini-1.5-pro"),
    ]:
        assert not _routed_matches(routed, mid), (
            f"substitusi nyata tidak boleh lolos: {routed!r} untuk {mid!r}")


def test_kode_repo_memakai_segmen_terakhir():
    """Kunci pada kode produksi, bukan hanya helper test.

    WAJIB menerima dua bentuk: path LENGKAP (id ber-namespace seperti
    "z-ai/glm-5.3") dan segmen TERAKHIR (id polos seperti "gemma-4-31b-it").
    Kalau hanya salah satu, salah satu kelas model hilang dari UI.
    """
    src = (ROOT / "gateway_roster.py").read_text(encoding="utf-8")
    assert 'rpath.rsplit("/", 1)[-1]' in src, (
        "gateway_roster.py harus memecah X-Routed-Via pada segmen TERAKHIR; "
        "partition('/') hanya memecah slash pertama dan menolak model hidup")
    assert "if _rpath != mid and rmodel != mid:" in src, (
        "gerbang harus menerima path LENGKAP _rpath (= id ber-namespace) ATAU "
        "segmen terakhir; hanya segmen terakhir membuang semua model "
        "ber-namespace seperti z-ai/glm-5.3 dan qwen/qwen3.8-27b")


# ---------------------------------------------------------------------------
# BUG 2026-10-02: model "berpikir" (thinking) hilang dari /models
# ---------------------------------------------------------------------------
# Gejala: hanya 3 model Gemini tampil di dropdown walau models.yaml punya 7.
#
# Akar masalah (diukur langsung ke gateway, bukan ditebak):
#   gemini-3.8-flash @ max_tokens=64  -> HTTP 200, content=null,
#                                      completion_tokens=0, finish_reason=length
#   gemini-3.8-flash @ max_tokens=512 -> HTTP 200, content="OK",
#                                      finish_reason=stop
#
# Model berpikir memakai `max_tokens` sebagai anggaran OUTPUT dan membakar
# entirety-nya untuk token penalaran sebelum menulis karakter jawaban pertama.
# Probe lama (`max_tokens: 64`) lalu menerima `content` kosong dan menandai
# model SEHAT sebagai FAIL -> whitelist /models menyusut.

class _Resp:
    """Response tiruan yang meniru perilaku nyata model berpikir."""

    def __init__(self, status_code, payload, routed):
        self.status_code = status_code
        self._payload = payload
        self.text = "{}"
        self.headers = {"x-routed-via": routed}

    def json(self):
        return self._payload


def _thinking_client(sequences):
    """Client yang mengembalikan response berurutan sesuai `sequences`."""
    class _Client:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, json=None):
            self.calls.append(dict(json or {}))
            return sequences[min(len(self.calls) - 1, len(sequences) - 1)]

    return _Client()


def test_model_berpikir_lolos_setelah_retry_anggaran_token():
    """Regresi utama: `content` kosong di stage-1 harus dicoba ulang."""
    import gateway_roster as gr

    empty_then_ok = [
        _Resp(200, {"choices": [{"message": {"content": None},
                                 "finish_reason": "length"}]},
              "google_gemini/gemini-3.8-flash"),
        _Resp(200, {"choices": [{"message": {"content": "OK"},
                                 "finish_reason": "stop"}]},
              "google_gemini/gemini-3.8-flash"),
    ]
    client = _thinking_client(empty_then_ok)
    rec = gr._probe_one(client, "http://gw", "k",
                        {"id": "gemini-3.8-flash", "providers": set()}, "1", 0)

    assert rec["status"] == "PASS", (
        f"gemini-3.8-flash (model berpikir) HARUS PASS setelah retry; "
        f"error={rec['error']!r}")
    assert rec["retried"] is True, "retry harus ditandai"
    assert len(client.calls) == 2, (
        f"harus ada 2 pemanggilan, dapat {len(client.calls)}")
    # Bukti anggaran token dinaikkan pada panggilan kedua.
    assert client.calls[0]["max_tokens"] == 64, client.calls[0]
    assert client.calls[1]["max_tokens"] == gr.PROBE_RETRY_MAX_TOKENS, client.calls[1]
    assert gr.PROBE_RETRY_MAX_TOKENS >= 512, (
        "512 adalah angka terukur; di bawah itu gemini-3.8-flash tidak "
        "pernah selesai menulis jawaban")


def test_model_yang_selalu_kosong_tetap_gagal():
    """Gerbang 'ISI NYATA' TIDAK boleh dilonggarkan sama sekali."""
    import gateway_roster as gr

    always_empty = [
        _Resp(200, {"choices": [{"message": {"content": None},
                                 "finish_reason": "length"}]},
              "google_gemini/gemini-3.5-flash-lite"),
        _Resp(200, {"choices": [{"message": {"content": ""},
                                 "finish_reason": "length"}]},
              "google_gemini/gemini-3.5-flash-lite"),
    ]
    rec = gr._probe_one(_thinking_client(always_empty), "http://gw", "k",
                        {"id": "gemini-3.5-flash-lite", "providers": set()},
                        "1", 0)
    assert rec["status"] == "FAIL", "model tanpa isi nyata TIDAK BOLEH lolos"
    assert rec["error"] == "content kosong", rec["error"]


def test_model_mati_http_500_tidak_berubah_status():
    """gemini-2.5-pro sudah ditarik Google -> harus tetap HTTP 500, FAIL."""
    import gateway_roster as gr

    dead = [_Resp(500, {}, "google_gemini/gemini-2.5-pro")]
    rec = gr._probe_one(_thinking_client(dead), "http://gw", "k",
                        {"id": "gemini-2.5-pro", "providers": set()}, "1", 0)
    assert rec["status"] == "FAIL", rec
    assert rec["error"].startswith("HTTP500"), rec["error"]


def test_model_normal_tidak_perlu_retry():
    """Model biasa harus tetap satu panggilan (retry bukan biaya semua orang)."""
    import gateway_roster as gr

    normal = [_Resp(200, {"choices": [{"message": {"content": "OK"},
                                       "finish_reason": "stop"}]},
                    "google_gemini/gemini-2.5-flash")]
    client = _thinking_client(normal)
    rec = gr._probe_one(client, "http://gw", "k",
                        {"id": "gemini-2.5-flash", "providers": set()}, "1", 0)
    assert rec["status"] == "PASS", rec
    assert len(client.calls) == 1, "model biasa tidak boleh memicu retry"
    assert rec["retried"] is False