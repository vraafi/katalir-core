"""Test parser varian <parameter> Qwen3 (modul terpisah).

Modul ini sengaja TIDAK disambungkan ke textual_tool_calls.py untuk sekarang.
Dua percobaan penyambungan sebelumnya merusak format yang sudah working
(medio `git checkout` dilakukan dua kali). Parser utama sudah terbukti
menangani ZWSP dengan maupun tanpa karakter tak-terlihat, jadi tidak ada
urgensi untuk menyambungkannya.

Bukti dari produksi (Railway, qwen/qwen3.8-27b) yang menjadi sumber test ini:
    <tool_call>
    <function=trigger_gmail_imap
    </parameter=email_address
    </parameter=app_password
    </function>
    </tool_call>
Model menutup dengan `</parameter=...>` dan tidak menulis nilai - jadi argumen
kosong itu WAJAR, bukan bug parser.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qwen_param_parser import parse_qwen_parameter_format as P  # noqa: E402

Z = "\u200b"

# Salinanpersis balasan produksi.
PRODUKSI = (
    f"<{Z}tool_call>\n"
    "<function=trigger_gmail_imap\n"
    f"{Z}/parameter=email_address\n"
    f"{Z}/parameter=app_password\n"
    f"{Z}/parameter=subject_filter\n"
    "</function>\n"
    f"<{Z}/tool_call>"
)

DENGAN_NILAI = (
    f"<{Z}tool_call><function=trigger_gmail_imap"
    "<parameter=email_address>akun@contoh.com</parameter>"
    "<parameter=app_password>abcd efgh ijkl</parameter>"
    "</function>"
    f"<{Z}/tool_call>"
)


def test_bentuk_produksi_terkena():
    calls = P(PRODUKSI)
    assert len(calls) == 1, f"tidak tertangkap: {calls}"
    assert calls[0]["name"] == "trigger_gmail_imap"


def test_parameter_tanpa_nilai_menghasilkan_args_kosong():
    calls = P(PRODUKSI)
    assert calls[0]["args"] == {}, "tanpa nilai harus jadi dict kosong, bukan error"


def test_parameter_dengan_nilai_terbaca():
    calls = P(DENGAN_NILAI)
    assert len(calls) == 1
    args = calls[0]["args"]
    assert args["email_address"] == "akun@contoh.com"
    assert args["app_password"] == "abcd efgh ijkl"


def test_zwsp_tidak_mengganggu():
    tanpa = PRODUKSI.replace(Z, "")
    assert len(P(tanpa)) == len(P(PRODUKSI)) == 1


def test_format_lain_tidak_ikut_tertangkap():
    """Parser ini HANYA untuk <parameter>; format lain harus dilewati."""
    good = "<tool_call>\n<function=generate_workflow_json>\n" \
           '{"name":"X","nodes":[]}\n</function>\n</tool_call>'
    assert P(good) == []
    assert P("halo dunia") == []
    assert P("") == []


def test_blok_tanpa_function_diabaikan():
    assert P(f"<{Z}tool_call>halo saja<{Z}/tool_call>") == []