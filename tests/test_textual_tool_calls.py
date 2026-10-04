"""tests/test_textual_tool_calls.py — parser tool-call TEKS.

Bukti reproduksi (2026-10-02, `google/gemma-4-31b-it` via gateway, HTTP 200,
routed `nvidia/google/gemma-4-31b-it`) memakai string di bawah — bukan
karangan. Perhatikan `spec_json` berisi JSON lain sebagai STRING yang di-escape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from textual_tool_calls import (  # noqa: E402
    extract_textual_tool_calls,
    strip_textual_tool_calls,
)

# REPRODUKSI LITERAL dari respons Gemma 4.
GEMMA_REAL = (
    "Untuk membuat workflow ini, kita akan menggunakan tiga node utama: "
    "**Manual Trigger**, **HTTP Request**.\n\n"
    "<|tool_call>call:nexus:generate_workflow_json("
    '{"spec_json":"{\\"nodes\\": [{\\"name\\": \\"When clicking Execute Workflow\\", '
    '\\"type\\": \\"n8n-nodes-base.manualTrigger\\"}, '
    '{\\"name\\": \\"Ambil Data API\\", \\"type\\": \\"n8n-nodes-base.httpRequest\\"}]}"})'
    "<tool_call|>"
)


def test_parsing_reproduksi_nyata_gemma():
    calls = extract_textual_tool_calls(GEMMA_REAL)
    assert len(calls) == 1, calls
    assert calls[0]["name"] == "nexus:generate_workflow_json"
    # Argumen harus jadi dict, dan `spec_json` harus string JSON yang bisa di-parse
    # lagi menjadi spec workflow (memang bentuk alat generate_workflow_json).
    assert isinstance(calls[0]["args"], dict)
    spec = json.loads(calls[0]["args"]["spec_json"])
    assert len(spec["nodes"]) == 2
    assert spec["nodes"][1]["type"] == "n8n-nodes-base.httpRequest"


def test_json_mentah_tidak_lagi_ditampilkan_ke_user():
    """Blok tool-call harus hilang dari teks reply."""
    cleaned = strip_textual_tool_calls(GEMMA_REAL)
    assert "tool_call" not in cleaned
    assert "spec_json" not in cleaned
    # Narasi normal model tetap dipertahankan.
    assert "Manual Trigger" in cleaned


def test_nama_tanpa_namespace_juga_didukung():
    """vLLM Gemma: <start_function_call>call:NAME{...}<end_function_call>."""
    text = 'ok <start_function_call>call:generate_workflow_json{"spec_json":"{}"}<end_function_call>'
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "generate_workflow_json"
    assert calls[0]["args"] == {"spec_json": "{}"}


def test_qwen3_coder_function_markup():
    """Qwen3-Coder: <tool_call>{"name":...}</tool_call>."""
    text = ('<think>ok</think><tool_call>{"name": "generate_workflow_json", '
            '"arguments": {"spec_json": "{}"}}</tool_call>')
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "generate_workflow_json"
    assert calls[0]["args"] == {"spec_json": "{}"}


def test_call_terpotong_masih_diparse():
    """`max_tokens` bisa memotong call; parser harus tetap Benefits."""
    truncated = GEMMA_REAL[: GEMMA_REAL.index("<tool_call|>")]
    calls = extract_textual_tool_calls(truncated)
    assert calls, "call terpotong harus tetap menghasilkan 1 call"
    assert calls[0]["name"] == "nexus:generate_workflow_json"
    assert isinstance(calls[0]["args"], dict)


def test_teks_biasa_tidak_berubah():
    """Guard: teks tanpa tool call harus dikembalikan apa adanya."""
    plain = "Halo! Saya bisa membantu membuat workflow. Apa yang Anda butuhkan?"
    assert extract_textual_tool_calls(plain) == []
    assert strip_textual_tool_calls(plain) == plain.strip()


def test_json_rusak_tidak_melempar_exception():
    """Argumen rusak harus diabaikan, bukan menjatuhkan seluruh balasan."""
    broken = '<|tool_call>call:nexus:generate_workflow_json({NOT_JSON})<tool_call|> halo'
    assert extract_textual_tool_calls(broken) == []
    # Teks tetap utuh agar user tidak kehilangan balasan.
    assert "halo" in strip_textual_tool_calls(broken)


def test_dua_call_berurutan():
    """Model kadang memanggil 2 tool dalam satu balasan."""
    text = ('<|tool_call>call:nexus:generate_workflow_json({"spec_json":"{}"})<tool_call|> '
            '<|tool_call>call:nexus:read_database({"table":"users"})<tool_call|>')
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 2
    assert calls[0]["name"] == "nexus:generate_workflow_json"
    assert calls[1]["name"] == "nexus:read_database"
    assert calls[1]["args"] == {"table": "users"}


# ---------------------------------------------------------------------------
# BUG FIX 2026-10-04: format Qwen3.8-27B yang dilaporkan user.
#
# Keluhan: JSON tampil mentah ke user, workflow tidak dibangun. Bukti nyata:
#     <tool_call>
#     <function=generate_workflow_json>
#     {"name": "Ambil Data API & Kirim ke Telegram", "nodes": [...]}
#     </function>
#     </tool_call>
#
# Tiga bug yang ditemukan lewat pengujian:
#   1. <function=NAME> tidak didukung -> call tidak terekstrak.
#   2. pola non-greedy memotong JSON bersarang -> "nodes" hilang.
#   3. strip() mengembalikan TEKS ASLI saat sisa kosong -> JSON tetap bocor
#      meskipun parse-nya BERHASIL.
# ---------------------------------------------------------------------------

QWEN_USER_REAL = (
    "<tool_call>\n"
    "<function=generate_workflow_json>\n"
    '{"name": "Ambil Data API & Kirim ke Telegram", "nodes": ['
    '{"id":"t","kind":"trigger"},'
    '{"id":"m","kind":"mcp","config":{"provider":"telegram","chat_id":"2109751369"}}]}'
    "\n</function>\n"
    "</tool_call>"
)


def test_qwen_function_wrapper_terekstrak():
    """BUG 1: <function=NAME> harus menghasilkan tool call."""
    calls = extract_textual_tool_calls(QWEN_USER_REAL)
    assert len(calls) == 1, f"call tidak terekstrak: {calls}"
    assert calls[0]["name"] == "generate_workflow_json"


def test_nama_tool_bukan_nama_workflow():
    """Field "name" di payload milik WORKFLOW, bukan nama tool.

    Ini yang bikin versi pertama salah: tool terdeteksi bernama
    "Ambil Data API & Kirim ke Telegram".
    """
    calls = extract_textual_tool_calls(QWEN_USER_REAL)
    assert calls[0]["name"] != "Ambil Data API & Kirim ke Telegram"


def test_json_bersarang_tidak_terpotong():
    """BUG 2: "nodes" harus utuh, bukan terpotong di kurung kurawal pertama."""
    calls = extract_textual_tool_calls(QWEN_USER_REAL)
    nodes = calls[0]["args"].get("nodes") or []
    assert len(nodes) == 2, f"JSON bersarang terpotong: {nodes}"


def test_xml_tidak_bocor_ke_user_setelah_parse_berhasil():
    """BUG 3: sebelum fix, strip() mengembalikan teks asli (JSON bocor)."""
    cleaned = strip_textual_tool_calls(QWEN_USER_REAL)
    assert "tool_call" not in cleaned
    assert "function=" not in cleaned
    assert cleaned == ""


def test_teks_normal_tentang_tool_call_tetap_tersisa():
    """K окружения teks di sekitar blok tool call harus tetap tampil."""
    text = "Saya buat sekarang. " + QWEN_USER_REAL + " Sudah selesai."
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 1
    cleaned = strip_textual_tool_calls(text)
    assert "Saya buat sekarang." in cleaned
    assert "Sudah selesai." in cleaned
    assert "tool_call" not in cleaned


def test_hermes_tanpa_wrapper_juga_berjalan():
    """Hermes: <tool_call>{"name":TOOL,"arguments":{...}}</tool_call>."""
    text = ('<tool_call>{"name": "generate_workflow_json", '
            '"arguments": {"spec_json": "{}"}}</tool_call>')
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "generate_workflow_json"
    assert calls[0]["args"] == {"spec_json": "{}"}
    assert strip_textual_tool_calls(text) == ""


def test_json_di_code_fence_berjalan():
    """Format fenced JSON (tanpa "<" sama sekali) harus tertangkap."""
    text = '```json\n{"name":"generate_workflow_json","arguments":{"spec_json":"{}"}}\n```'
    calls = extract_textual_tool_calls(text)
    assert len(calls) == 1, f"fenced JSON tidak tertangkap: {calls}"
    assert calls[0]["name"] == "generate_workflow_json"
    assert "```" not in strip_textual_tool_calls(text)


def test_blok_rusak_tidak_melempar_dan_tidak_menghapus_teks():
    """Call rusak dibiarkan apa adanya - user tetap bisa baca balasannya."""
    broken = "<tool_call>{ini bukan json"
    assert extract_textual_tool_calls(broken) == []
    assert "halo" in strip_textual_tool_calls("halo " + broken)


def test_blok_berisi_teks_bukan_json_tidak_menghasilkan_call_palsu():
    """Penjelasan biasa di dalam <tool_call> tidak boleh jadi tool call."""
    text = "<tool_call>Saya tidak yakin, tolong konfirmasi dulu.</tool_call>"
    assert extract_textual_tool_calls(text) == []
