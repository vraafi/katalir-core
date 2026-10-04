"""Test gerbang fail-closed tool call (BUG FIX 2026-10-04).

Gateway production memb-drop `tools` (HTTP 500 saat payload tools dikirim),
jadi semua tool call datang sebagai TEKS. `api_server` kini memverifikasi
bentuknya dulu dengan parser KAKAT sebelum dieksekusi.

Aturan yang diuji persis seperti di api_server:
  * bentuk rusak  -> DITOLAK, tidak dieksekusi
  * multi-call    -> tetap jalan (tidak boleh merusak alur yang sudah bisa)
  * tidak ada call-> teks biasa, apa adanya
"""

import re

import pytest

from textual_tool_calls import extract_textual_tool_calls
from tool_call_parser import ToolCallParseError, parse_tool_call

# Helper yang(api_server pakai: parsing KAKAT, "ambigu" tetap diizinkan.
def gate(text):
    """True = HARUS DITOLAK."""
    try:
        parse_tool_call(text)
    except ToolCallParseError as exc:
        return not str(exc).startswith("ambigu")
    except Exception:  # noqa: BLE001
        return False
    return False


def test_qwen3_xml_valid_boleh_jalan():
    text = ('<think>ok</think><tool_call><function=web_search>'
            '{"query":"berita"}</function></tool_call>')
    assert gate(text) is False
    assert extract_textual_tool_calls(text)


def test_hermes_valid_boleh_jalan():
    text = ('<tool_call>{"name":"web_search",'
            '"arguments":{"query":"x"}}</tool_call>')
    assert gate(text) is False


def test_json_rusak_ditolak():
    """Inilah bug "JSON mentah tampil ke user": argumen terpotong."""
    text = ('<tool_call><function=generate_workflow_json>'
            '{"spec_json": {"name": "x", "nodes": [}</tool_call>')
    assert gate(text) is True


def test_blok_tanpa_argumen_ditolak():
    text = "<tool_call><function=web_search>   </function></tool_call>"
    assert gate(text) is True


def test_hermes_tanpa_name_ditolak():
    text = '<tool_call>{"arguments":{"query":"x"}}</tool_call>'
    assert gate(text) is True


def test_data_setelah_code_fence_ditolak():
    text = ('```json\n{"tool":"web_search","args":{"query":"x"}}\n```\n'
            'lalu saya jelaskan sedikit')
    assert gate(text) is True


def test_multi_call_tidak_ditolak_regresi():
    """Dua blok = multi-call SAH. Memblokirnya merusak alur produksi."""
    text = ('<tool_call><function=web_search>{"query":"a"}</function></tool_call>'
            '<tool_call><function=check_credential>'
            '{"provider":"telegram"}</function></tool_call>')
    assert gate(text) is False
    assert len(extract_textual_tool_calls(text)) == 2


def test_teks_biasa_tidak_diapa_apakan():
    for t in ["Halo, ada yang bisa dibantu?",
              "Saya buatkan workflow untuk Anda.",
              "{\"name\":\"x\",\"nodes\":[]}"]:
        assert gate(t) is False


def test_parser_tidak_melempar_keexcept_umum():
    """Gerbang tidak boleh mematikan alur: satu tools tidak boleh的死 alur."""
    for t in ["", None, "<", "{}", "[]", "<tool_call>"]:
        try:
            parse_tool_call(t)
        except ToolCallParseError:
            pass  # memang bentuk call yang rusak -> boleh
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"parser melempar di luar kontrak: {exc!r}")


def test_api_server_mengimpor_gerbang():
    """api_server harus benar-benar mengimpor gerbang, bukan diam-diam saja."""
    src = open("api_server.py", encoding="utf-8").read()
    assert "from tool_call_parser import" in src
    assert re.search(r"except ToolCallParseError", src)