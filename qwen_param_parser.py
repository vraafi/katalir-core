"""Parser tambahan khusus varian <parameter> Qwen3.

DITAMBAHKAN SEPISAH (2026-10-04) dan SENGAJA TIDAK MENYENTUH pola yang sudah
ada di textual_tool_calls.py. Percobaan sebelumnya gagal justru karena pola
existing diubah untuk menangani ZWSP; akibatnya format yang sudah working
ikut rusak. Jadi aturan maintenansi di sini:

    JANGAN pernah mengubah pola existing. Tambahkan fungsi terpisah,
    sambungkan HANYA sebagai fallback kalau tidak ada call yang ketemu.
"""

from __future__ import annotations

import re

# Output produksi memuat karakter zero-width (U+200B) di dalam tag, misalnya
# <tool_call>. Pola harus toleran terhadap itu, tapi HANYA di file ini.
_INVIS_CHARS = "\u200b\u200c\u200d"
_INVIS = "[" + _INVIS_CHARS + "]"
_QWEN_PARAM_BLOCK = re.compile(
    "<" + _INVIS + r"?\s*tool_call" + _INVIS + r"?\s*>(.*?)"
    "<" + _INVIS + r"?\s*/\s*" + _INVIS + r"?\s*tool_call" + _INVIS + r"?\s*>",
    re.DOTALL | re.IGNORECASE,
)

_QWEN_FUNCTION_NAME = re.compile(
    "<" + _INVIS + r"?\s*function" + _INVIS + r"?\s*=\s*([\w.\-]+)",
    re.IGNORECASE,
)

# Dua bentuk yangdilihat dari Qwen3.8-27B:
#   <parameter=email_address>akun@x</parameter>
#   </parameter=email_address>            (Qwen menutup, tidak menulis nilai)
_QWEN_PARAMETER = re.compile(
    "<" + _INVIS + r"?\s*/?\s*" + _INVIS + r"?\s*parameter" + _INVIS + r"?\s*=\s*([\w.\-]+)"
    + _INVIS + r"?\s*>(.*?)(?:"
    "<" + _INVIS + r"?\s*/\s*" + _INVIS + r"?\s*parameter" + _INVIS + r"?\s*>|$)",
    re.DOTALL | re.IGNORECASE,
)

_STRIP_INVIS = re.compile("[" + _INVIS_CHARS + "]")


def _clean(text: str) -> str:
    """Buang karakter zero-width."""
    return _STRIP_INVIS.sub("", text or "")


def parse_qwen_parameter_format(content: str) -> list:
    """Parse varian Qwen <parameter>. Bentuk hasil sama dengan parser utama.

    Mengembalikan list `{"name": str, "args": dict}`.

    Catatan jujur: model kadang menutup dengan `</parameter=NAME>` dan TIDAK
    menulis nilai. Dalam kasus itu argumennya kosong. Kita TETAP mengembalikan
    call supaya pemanggil bisa melaporkan "kredensial dibutuhkan" alih-alih
    membiarkan XML mentah tampil di chat.
    """
    if not content or "parameter" not in content:
        return []
    results = []
    for block in _QWEN_PARAM_BLOCK.finditer(content):
        body = _clean(block.group(1))
        name_match = _QWEN_FUNCTION_NAME.search(body)
        if not name_match:
            continue
        fn_name = name_match.group(1).strip()
        params = {}
        for pm in _QWEN_PARAMETER.finditer(body):
            key = (pm.group(1) or "").strip()
            val = (pm.group(2) or "").strip()
            if key and val:
                params[key] = val
        results.append({"name": fn_name, "args": params})
    return results


def strip_qwen_parameter_blocks(content: str) -> str:
    """Buang blok <parameter> yang tidak menghasilkan call sama sekali."""
    if not content:
        return ""
    out = content
    for block in list(_QWEN_PARAM_BLOCK.finditer(content)):
        if parse_qwen_parameter_format(block.group(0)):
            continue
        out = out.replace(block.group(0), "")
    return out
