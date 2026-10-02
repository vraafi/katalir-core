"""textual_tool_calls.py — parser tool-call TEKS (bukan `tool_calls` terstruktur).

MASALAH YANG DISELESAIKAN (2026-10-02)
--------------------------------------
LlamaBindChat (`api_server.py`) hanya membaca `resp.tool_calls`, yaitu field
STRUKTUR dari OpenAI. Beberapa model membungkus panggilan di dalam `content`
sebagai TEKS. Bukti nyata dari `google/gemma-4-31b-it` via gateway:

    <|tool_call>call:nexus:generate_workflow_json({"spec_json":"{\\n  \\"nodes\\": [...]}"})<tool_call|>

Karena `resp.tool_calls` kosong, loop tool calling langsung `break`, dan JSON
mentah ikut ke `reply` sehingga user melihat JSON, bukan workflow di canvas.

BENTUK YANG DIDUKUNG
--------------------
1. Gemma 4  : `<|tool_call>call:NS:NAME({...})<tool_call|>`   (terverifikasi)
2. vLLM Gemma: `<start_function_call>call:NAME{...}<end_function_call>`
3. Qwen3-Coder : `<function=NAME>...</function>` (argumen XML-ish, best effort)

Sifat penting format Gemma:
* Argumen adalah JSON yang berisi JSON lain sebagai STRING
  (`{"spec_json":"{...escaped...}"}`). `json.loads`Tetap benar karena di-escape.
* `max_tokens` bisa memotong call di tengah → tag penutup tidak ada. Itu kondisi
  NYATA (reproduksi awal terpotong di tengah JSON). Karena itu pemulih brace
  dicoba sebelum menyerah; kalau tetap gagal, call diabaikan (bukan dinaikkan
  jadi exception) supaya user tetap dapat teks balasan normal.
"""

from __future__ import annotations

import json
import re

# --- Gemma 4: <|tool_call>call:NS:NAME({...})<tool_call|> -------------------
_GEMMA = re.compile(
    r"<\|tool_call>\s*call:(?P<ns>[\w.\-]+):(?P<name>[\w.\-]+)\((?P<args>.*?)\)\s*<tool_call\|>",
    re.DOTALL,
)
# Versi tanpa penutup `)` sebelum tag — untuk output terpotong.
_GEMMA_TRUNC = re.compile(
    r"<\|tool_call>\s*call:(?P<ns>[\w.\-]+):(?P<name>[\w.\-]+)\((?P<args>.*)$",
    re.DOTALL,
)
# --- vLLM Gemma: <start_function_call>call:NAME{...}<end_function_call> ------
_VLLM = re.compile(
    r"<start_function_call>\s*call:(?P<name>[\w.\-]+)\s*\{(?P<args>.*)\}\s*<end_function_call>",
    re.DOTALL,
)
# --- Qwen3-Coder: <tool_call>{"name":...,"arguments":...}</tool_call> ---------------
_QWEN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL
)

__all__ = ["extract_textual_tool_calls", "strip_textual_tool_calls"]


def _loads_lenient(raw: str) -> dict | None:
    """`json.loads` dengan pemulihan untuk output terpotong.

    Gemini/Gemma sering memotong call karena `max_tokens`.-Blangsung
    `json.loads` akan melempar; di sini braces yang hilang ditutup bertahap
    lalu dicoba lagi. Return None bila memang tidak bisa diparse.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except Exception:
        pass
    # Coba tutup kurung yang hilang (kelongkongan umum JSON terpotong).
    for suffix in ("", "}", "}}", '"}', '"}}', '"}}}"'):
        try:
            val = json.loads(raw + suffix)
            return val if isinstance(val, dict) else None
        except Exception:
            continue
    # Coba potong di objek terakhir yang lengkap (argumen pertama yang utuh).
    for cut in range(len(raw) - 1, 0, -1):
        if raw[cut - 1] != "}":
            continue
        try:
            val = json.loads(raw[:cut] + "}")
            if isinstance(val, dict):
                return val
        except Exception:
            continue
    return None


def _match_all(text: str) -> tuple[list[dict], str]:
    """Kumpulkan call dari `text`; kembalikan (calls, sisa_teks_bersih)."""
    calls: list[dict] = []
    rest = text

    # 1) Gemma 4 lengkap
    def _gemma_sub(m: re.Match) -> str:
        args = _loads_lenient(m.group("args"))
        if args is None:
            return m.group(0)
        calls.append({
            "name": f"{m.group('ns')}:{m.group('name')}",
            "args": args,
        })
        return ""
    rest = _GEMMA.sub(_gemma_sub, rest)

    # 2) Gemma 4 terpotong (tanpa tag penutup) — ambil sampai call terakhir.
    m = _GEMMA_TRUNC.search(rest)
    if m and not calls:
        # `.*$` menyertakan tanda kurung penutup argumen; buang supaya sisa
        # itu JSON yang valid, bukan `...)`.
        args = _loads_lenient(m.group("args").rstrip().rstrip(")"))
        if args is not None:
            calls.append({
                "name": f"{m.group('ns')}:{m.group('name')}",
                "args": args,
            })
            rest = rest[: m.start()]

    # 3) vLLM Gemma
    def _vllm_sub(m: re.Match) -> str:
        # Non-greedy `.*?` berhenti di `}` PERTAMA, padahal payload vLLM boleh
        # memuat objek bersarang (`{"spec_json":"{}"}`). Ambil sampai `}` TERAKHIR
        # sebelum tag penutup, lalu coba parse sebagai objek; kalau gagal,
        # bungkus ulang dengan kurung kurawal karena `{}` itu sendiri adalah
        # pembungkus argumen, bukan bagian dari JSON.
        args = _loads_lenient(m.group("args"))
        if args is None:
            args = _loads_lenient("{" + m.group("args") + "}")
        if args is None:
            return m.group(0)
        calls.append({"name": m.group("name"), "args": args})
        return ""
    rest = _VLLM.sub(_vllm_sub, rest)

    # 4) Qwen3-Coder
    def _qwen_sub(m: re.Match) -> str:
        try:
            obj = json.loads(m.group(1))
        except Exception:
            return m.group(0)
        name = str(obj.get("name") or "").strip()
        if not name:
            return m.group(0)
        raw_args = obj.get("arguments", obj.get("parameters", {}))
        args = raw_args if isinstance(raw_args, dict) else _loads_lenient(str(raw_args))
        calls.append({"name": name, "args": args or {}})
        return ""
    rest = _QWEN.sub(_qwen_sub, rest)

    return calls, rest


def extract_textual_tool_calls(text: str) -> list[dict]:
    """Ambil daftar tool call yang tertanam di TEKS balasan model.

    Mengembalikan list `{"name": str, "args": dict}`. Kosong bila tidak ada.
    """
    if not text or "<" not in text:
        return []
    calls, _ = _match_all(text)
    return calls


def strip_textual_tool_calls(text: str) -> str:
    """Buang blok tool-call dari teks supaya JSON mentah tidak tampil ke user."""
    if not text:
        return ""
    _, rest = _match_all(text)
    out = rest.strip()
    return out or text.strip()