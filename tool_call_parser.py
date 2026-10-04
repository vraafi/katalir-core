"""tool_call_parser.py — parser tool call yang FAIL-CLOSED.

Prinsip: kalau ragu, TOLAK. Jangan menebak.

Referensi pola yang diterapkan (hasil riset repo Oktober 2026):
  * factory-droid-openai — "Fail-closed parsing. Close markers inside JSON
    strings are argument data, not framing. Ambiguous repairs fail closed,
    including multiple argument aliases, trailing data after a code fence,
    missing Qwen parameter close tags".
  * unsloth — "A whole-content JSON value is a structured answer: quoted
    examples must not become calls".

BEDA DARI textual_tool_calls.py
-------------------------------
`textual_tool_calls.py` (v1.0) sengaja LENGAH dan mengembalikan call
sebagaimapun bisa, karena tujuannyaimalsa: jangan sampai JSON mentah
tampil ke user. Modul ini sengaja KAKAT: bentuk ambigu tidak
dieksekusi, tapi dilaporkan. Keduanya dipakai berlapis: yang lenient
membuang blok supaya tampilan bersih, yang ketat menolak eksekusi.

Tidak ada perubahan pada `textual_tool_calls.py` - modul ini berdiri sendiri.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Karakter zero-width (U+200B/200C/200D) muncul DI DALAM tag tool_call pada
# output produksi. Semua pola di sini memabulkannya sebagai opsional.
_ZW = "[\\u200b\\u200c\\u200d]"

_QWEN_FN = re.compile(
    "<" + _ZW + r"?\s*tool_call" + _ZW + r"?\s*>"
    r"\s*<" + _ZW + r"?\s*function" + _ZW + r"?\s*=\s*([\w.\-]+)" + _ZW + r"?\s*>"
    r"(.*?)"
    r"<" + _ZW + r"?\s*/\s*" + _ZW + r"?\s*function" + _ZW + r"?\s*>"
    r"\s*<" + _ZW + r"?\s*/\s*" + _ZW + r"?\s*tool_call" + _ZW + r"?\s*>",
    re.DOTALL | re.IGNORECASE,
)

_HERMES = re.compile(
    "<" + _ZW + r"?\s*tool_call" + _ZW + r"?\s*>(.*?)<"
    + _ZW + r"?\s*/\s*" + _ZW + r"?\s*tool_call" + _ZW + r"?\s*>",
    re.DOTALL | re.IGNORECASE,
)

_FENCE = re.compile(r"```(?:json|tool_call)?\s*\n(.*?)```", re.DOTALL)


_FN_NAME = re.compile(r"^[A-Za-z_][\w.\-]*$")
_ARG_KEYS = ("args", "arguments", "parameters")


def _looks_like_call(data: dict) -> bool:
    """Apakah dict ini benar-benar CALL, bukan sekadar jawaban terstruktur?

    Bug nyata (BUG FIX 2026-10-04): `{"name": "Ambil Data", "nodes": []}` -
    itu SPES workflow, bukan panggilan tool. Tanpa pemeriksaan ini, nama
    workflow dipakai sebagai nama tool dan dieksekusi. Persis peringatan
    unsloth: "A whole-content JSON value is a structured answer: quoted
    examples must not become calls."
    """
    if "tool" in data:
        return True
    if "name" not in data:
        return False
    if not any(k in data for k in _ARG_KEYS):
        return False
    # Nama fungsi tidak boleh mengandung spasi dan tidak boleh terlihat
    # seperti nama workflow/bisnis.
    name = str(data.get("name") or "")
    return bool(name) and bool(_FN_NAME.match(name)) and " " not in name


def _call_from_dict(data: dict, label: str) -> dict:
    name = data.get("tool") or data.get("name")
    name = str(name or "").strip()
    if not name or not _FN_NAME.match(name) or " " in name:
        raise ToolCallParseError(f"{label}: nama alat tidak valid ({name!r})")
    raw = data.get("args")
    if raw is None:
        for k in _ARG_KEYS[1:]:
            if k in data:
                raw = data[k]
                break
    if raw is None:
        raw = {}
    if isinstance(raw, str):
        raw = _loads_strict(raw, f"{name}.args")
    if not isinstance(raw, dict):
        raise ToolCallParseError(f"{name}.args harus object")
    return {"tool": name, "args": raw}


class ToolCallParseError(Exception):
    """Bentuk tool call ditemukan tapi tidak bisa dipercaya."""


def _strip_zero_width(text: str) -> str:
    return re.sub(_ZW, "", text or "")


def _loads_strict(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolCallParseError(
            f"{label}: argumen bukan JSON valid ({exc.msg} di baris {exc.lineno})"
        ) from exc


def parse_tool_call(content: str) -> dict | None:
    """Parse SATU tool call dari `content`.

    Return:
        {"tool": str, "args": dict}  bila ada tepat satu call yang valid.
        None                         bila tidak ada apa pun yang menyerupai call.
    Raises:
        ToolCallParseError bila bentuknya ambigu/rusak - JANGAN dieksekusi.
    """
    if not content or "<" not in content and "{" not in content and "`" not in content:
        return None

    text = _strip_zero_width(content)

    # --- 1. Qwen3: <tool_call><function=NAME>{...}</function></tool_call> ----
    fn_hits = list(_QWEN_FN.finditer(text))
    if len(fn_hits) > 1:
        raise ToolCallParseError(
            f"ambigu: {len(fn_hits)} blok tool_call dalam satu balasan; "
            "tidak boleh menebak mana yang benar"
        )
    if fn_hits:
        m = fn_hits[0]
        name = m.group(1)
        body = m.group(2).strip()
        if not body:
            raise ToolCallParseError(
                f"{name}: <function> tanpa argumen - model berhenti sebelum "
                "mengisi parameter"
            )
        args = _loads_strict(body, name)
        if not isinstance(args, dict):
            raise ToolCallParseError(f"{name}: argumen harus object, bukan {type(args).__name__}")
        return {"tool": name, "args": args}

    # --- 2. Hermes: <tool_call>{"name":TOOL,"arguments":{...}}</tool_call> ---
    hermes_hits = list(_HERMES.finditer(text))
    if len(hermes_hits) > 1:
        raise ToolCallParseError(
            f"ambigu: {len(hermes_hits)} blok tool_call dalam satu balasan"
        )
    if hermes_hits:
        body = hermes_hits[0].group(1).strip()
        data = _loads_strict(body, "hermes")
        if not isinstance(data, dict):
            raise ToolCallParseError("hermes: argumen harus object")
        if "name" not in data:
            raise ToolCallParseError("hermes: call tanpa field 'name'")
        data = dict(data)
        name = str(data.pop("name")).strip()
        raw = data.pop("arguments", data.pop("parameters", {}))
        if isinstance(raw, str):
            raw = _loads_strict(raw, f"{name}.arguments")
        if not isinstance(raw, dict):
            raise ToolCallParseError(f"{name}.arguments harus object")
        return {"tool": name, "args": raw}

    # --- 3. JSON murni SELURUH balasan ----------------------------------------
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        data = _loads_strict(stripped, "json")
        if isinstance(data, dict) and _looks_like_call(data):
            return _call_from_dict(data, "json")
        # JSON tanpa indikasi tool = jawaban terstruktur, BUKAN panggilan.
        # Contoh nyata dari produksi: {"name":"Ambil Data","nodes":[]}.
        return None

    # --- 4. JSON di dalam code fence -----------------------------------------
    fence_hits = list(_FENCE.finditer(text))
    if fence_hits:
        if len(fence_hits) > 1:
            raise ToolCallParseError(
                f"ambigu: {len(fence_hits)} code fence; tidak boleh menebak"
            )
        body = fence_hits[0].group(1).strip()
        trailing = text[fence_hits[0].end():].strip()
        if trailing:
            raise ToolCallParseError(
                "fail-closed: ada data setelah code fence penutup "
                f"({trailing[:40]!r}) - bisa jadiuu dua jawaban"
            )
        data = _loads_strict(body, "fence")
        if isinstance(data, dict) and _looks_like_call(data):
            return _call_from_dict(data, "fence")

    # --- 5. Tidak dikenali -> bukan error, tapi juga bukan call ---------------
    return None