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

    Didefinisikan ulang di sini supaya test mengunci PERILAKU yang benar tanpa
    memanggil jaringan. `_probe_one` sendiri tetap sumber kebenaran produksi.
    """
    _rprov, _, rpath = routed.partition("/")
    rmodel = rpath.rsplit("/", 1)[-1]
    return rmodel == mid


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
]


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
    """Kunci pada kode produksi, bukan hanya helper test."""
    src = (ROOT / "gateway_roster.py").read_text(encoding="utf-8")
    assert 'rpath.rsplit("/", 1)[-1]' in src, (
        "gateway_roster.py harus memecah X-Routed-Via pada segmen TERAKHIR; "
        "partition('/') hanya memecah slash pertama dan menolak model hidup")