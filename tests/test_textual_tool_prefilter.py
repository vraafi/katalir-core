"""Prefilter parser tool-call: lebih cepat TANPA mengubah hasil.

KENAPA ADA
`_match_all` menjalankan 5 pemindaian regex (Gemma, Gemma-terpotong, vLLM, blok
`<tool_call>`, code fence) atas SELURUH teks balasan. Kasus tersering adalah
balasan yang TIDAK memuat tool call sama sekali, jadi mayoritas pekerjaan itu
mubazir.

YANG DIKUNCI
1. Prefilter TIDAK mengubah hasil: untuk tiap bentuk, jumlah/isi call sama
   seperti sebelum prefilter (regex-nya sendiri sudah mensyaratkan penanda
   literal itu, jadi melewatinya hanya mungkin saat hasilnya memang kosong).
2. Bentuk Hermes (`<tool_call>{"name":...}` tanpa `<function=`) TETAP terbaca —
   ini yang paling mudah rusak bila prefilter ditulis terlalu ketat.
3. Balasan berprosa yang memuat tool call di TENGAH/akhir tetap terbaca.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from textual_tool_calls import extract_textual_tool_calls, strip_textual_tool_calls  # noqa: E402

GEMMA = '<|tool_call>call:nexus:kirim_telegram_message({"chat_id":"-1","pesan":"halo"})<tool_call|>'
VLLM = '<start_function_call>call:kirim_telegram_message{"chat_id":"-1"}<end_function_call>'
HERMES = '<tool_call>{"name": "kirim_telegram_message", "arguments": {"chat_id": "-1"}}</tool_call>'
QWEN_FN = ('<tool_call>\n<function=generate_workflow_json>\n'
           '{"name": "Alur", "nodes": [{"id": "n1"}]}\n</function>\n</tool_call>')
FENCED = '```json\n{"name": "kirim_telegram_message", "arguments": {"chat_id": "-1"}}\n```'
PROSE = ("Tentu, saya bantu jelaskan. Workflow adalah rangkaian node yang "
         "dihubungkan oleh edge. Setiap node punya kind: trigger, agent, atau mcp. " * 20)


def test_prosa_tanpa_tool_call_tidak_menghasilkan_call():
    assert extract_textual_tool_calls(PROSE) == []
    assert strip_textual_tool_calls(PROSE) == PROSE.strip()


def test_bentuk_gemma_tetap_terbaca():
    calls = extract_textual_tool_calls(GEMMA)
    assert len(calls) == 1
    assert calls[0]["name"] == "nexus:kirim_telegram_message"
    assert calls[0]["args"]["chat_id"] == "-1"


def test_bentuk_vllm_tetap_terbaca():
    calls = extract_textual_tool_calls(VLLM)
    assert len(calls) == 1
    assert calls[0]["name"] == "kirim_telegram_message"


def test_bentuk_hermes_tetap_terbaca():
    """Paling rawan: tidak punya `<function=` dan tidak punya `<|tool_call>`."""
    calls = extract_textual_tool_calls(HERMES)
    assert len(calls) == 1, "bentuk Hermes hilang setelah prefilter"
    assert calls[0]["name"] == "kirim_telegram_message"
    assert calls[0]["args"] == {"chat_id": "-1"}


def test_bentuk_function_xml_tetap_terbaca():
    calls = extract_textual_tool_calls(QWEN_FN)
    assert len(calls) == 1
    assert calls[0]["name"] == "generate_workflow_json"


def test_bentuk_fenced_json_tetap_terbaca():
    calls = extract_textual_tool_calls(FENCED)
    assert len(calls) == 1
    assert calls[0]["name"] == "kirim_telegram_message"


def test_call_di_tengah_prosa_tetap_terbaca():
    """Deteksi TIDAK boleh bergantung pada awal teks (brief menyarankan itu)."""
    text = f"Baik, saya jalankan sekarang.\n\n{HERMES}\n\nTerima kasih."
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "kirim_telegram_message"


def test_call_di_akhir_prosa_panjang_tetap_terbaca():
    text = PROSE + "\n" + GEMMA
    assert len(extract_textual_tool_calls(text)) == 1


def test_beberapa_call_sekaligus():
    text = GEMMA + "\n" + VLLM
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 2


def test_prefilter_memberi_percepatan_pada_kasus_tanpa_call():
    """Bandingkan `_match_all` (semua pass) vs `extract_...` (ber-prefilter).

    Keduanya kini memakai prefilter, jadi yang diukur adalah biaya nyata jalur
    "tidak ada tool call" vs biaya menjalankan regex tanpa prefilter.
    """
    import re as _re
    import textual_tool_calls as ttc

    N = 200
    t0 = time.perf_counter()
    for _ in range(N):
        extract_textual_tool_calls(PROSE)
    berprefilter = time.perf_counter() - t0

    # Simulasi jalur LAMA: semua regex dijalankan tanpa memeriksa penanda.
    fenced = _re.compile(r"```(?:json|tool_call)?\s*\n(.*?)```", _re.DOTALL)
    t0 = time.perf_counter()
    for _ in range(N):
        rest = ttc._GEMMA.sub(lambda m: m.group(0), PROSE)
        ttc._GEMMA_TRUNC.search(rest)          # hasilnya memang None di kasus ini
        rest = ttc._VLLM.sub(lambda m: m.group(0), rest)
        rest = fenced.sub(lambda m: m.group(0), rest)
    lama = time.perf_counter() - t0

    print(f"\n  {N}x parse prosa ({len(PROSE)} char): lama={lama*1000:.1f}ms  "
          f"berprefilter={berprefilter*1000:.1f}ms")
    assert berprefilter < lama, "prefilter tidak lebih cepat"
