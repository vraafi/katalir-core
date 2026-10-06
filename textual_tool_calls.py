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

# BUG FIX 2026-10-04: dua bug nyata di parser Qwen.
#
# BUG 1 - <function=NAME> tidak didukung sama sekali.
#   Output nyata Qwen3.8-27B (dilaporkan user):
#       <tool_call>
#       <function=generate_workflow_json>
#       {"name": "...", "nodes": [...]}
#       </function>
#       </tool_call>
#   Regex lama hanya cocokkan {...} langsung di dalam <tool_call>, jadi
#   tidak cocok -> call TIDAK diekstrak dan XML mentah tampil ke user.
#
# BUG 2 - non-greedy memotong JSON bersarang.
#   Pola lama berhenti di kurung kurawal PERTAMA. Untuk payload workflow
#   {"name":"...","nodes":[{"id":...}]} itu menghasilkan {"name":"..."}
#   saja -> spec_json hilang -> draf ditolak.
#   _scan_balanced_json mengambil sampai kurung kurawal SEIMBANG.
def _scan_balanced_json(text: str, start: int):
    """Ambil objek JSON mulai text[start] == "{" sampai kurung SEIMBANG.

    Mengembalikan (payload, index_sepanjang_hasil) atau None kalau tidak
    pernah tertutup. Menghormati string yang memuat kurung kurawal agar
    payload tidak terpotus.
    """
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == chr(92):
                esc = True
            elif ch == chr(34):
                in_str = False
            continue
        if ch == chr(34):
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None


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
    """Kumpulkan call dari `text`; kembalikan (calls, sisa_teks_bersih).

    PREFILTER (2026-10-06): tiap format punya penanda literal yang WAJIB ada,
    jadi pass yang penandanya tidak ada bisa dilewati tanpa regex sama sekali.
    Ini kasus tersering — mayoritas balasan model tidak memuat tool call —
    sehingga yang tadinya 5 pemindaian regex atas seluruh teks menjadi beberapa
    pemeriksaan substring.

    CATATAN: brief menyarankan deteksi lewat "2 karakter pertama" teks. Itu
    TIDAK dipakai karena tidak benar: balasan model umumnya berisi prosa lebih
    dulu, dan tool call-nya ada di tengah/akhir; memutuskan berdasarkan awal
    teks akan melewatkan call yang sah. Penanda literal di bawah ini kebal
    terhadap urutan tersebut (True/False-nya sama dengan menjalankan regex).
    """
    calls: list[dict] = []
    rest = text

    has_gemma = "<|tool_call>" in text
    has_vllm = "<start_function_call>" in text
    has_xml = "<tool_call>" in text
    has_fence = "```" in text

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
    if has_gemma:
        rest = _GEMMA.sub(_gemma_sub, rest)

    # 2) Gemma 4 terpotong (tanpa tag penutup) — ambil sampai call terakhir.
    if has_gemma:
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
    if has_vllm:
        rest = _VLLM.sub(_vllm_sub, rest)

    # 4a) Qwen3 dengan <function=NAME> (BUG FIX 2026-10-04, bug 1).
    #     Satu blok <tool_call> bisa memuat satu atau lebih <function=NAME>.
    _FN_BLOCK = re.compile(
        r"<\u200b?\s*tool_call\s*>(.*?)<\s*/\s*\u200b?\s*tool_call\s*>",
        re.DOTALL,
    )

    def _fn_name(name: str, payload: str) -> None:
        """`name` = nama tool dari <function=NAME>, "" = bentuk Hermes.

        BUG FIX 2026-10-04: kalau `name` sudah diketahui dari
        <function=NAME>, payload adalah ARGMEN langsung - jadi field "name"
        di dalamnya milik WORKFLOW ("Ambil Data API & Kirim ke Telegram"),
        BUKAN nama tool. Versi lama salah membacanya sebagai nama tool.
        """
        obj = _loads_lenient(payload)
        if obj is None:
            return
        if name:
            calls.append({"name": name, "args": obj})
            return
        # Bentuk Hermes: {"name": TOOL, "arguments": {...}}
        tool = str(obj.get("name") or "").strip()
        if not tool:
            return
        raw = obj.get("arguments", obj.get("parameters", {}))
        args = raw if isinstance(raw, dict) else _loads_lenient(str(raw))
        calls.append({"name": tool, "args": args or {}})

    def _fn_block_sub(m: re.Match) -> str:
        body = m.group(1)
        consumed = False
        # Ambil semua <function=NAME>...</function> di dalam blok.
        pos = 0
        for fm in re.finditer(r"<\s*function\s*=\s*([\w.\-]+)\s*>(.*?)"
                             r"<\s*/\s*function\s*>", body, re.DOTALL):
            name = fm.group(1)
            raw = fm.group(2).strip()
            brace = raw.find("{")
            if brace >= 0:
                got = _scan_balanced_json(raw, brace)
                if got:
                    _fn_name(name, got[0])
                    consumed = True
                    continue
            if raw:
                parsed = _loads_lenient(raw)
                if parsed is not None:
                    _fn_name(name, raw)
                    consumed = True
        if consumed:
            return ""
        # Tanpa <function=NAME>: cari objek JSON pertama (Hermes).
        brace = body.find("{")
        if brace >= 0:
            got = _scan_balanced_json(body, brace)
            if got:
                _fn_name("", got[0])
                return ""
        return m.group(0)

    # Prefilter cukup `<tool_call>`: blok ini menangani DUA bentuk — ber-
    # `<function=NAME>` maupun Hermes (`{"name":...,"arguments":...}`) yang tidak
    # punya `<function=` sama sekali. Menambahkan syarat `has_fn` di sini akan
    # melewatkan bentuk Hermes.
    if has_xml:
        rest = _FN_BLOCK.sub(_fn_block_sub, rest)

    # 4b) Qwen3-Coder lama: <tool_call>{...}</tool_call> tanpa wrapper.
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
    rest = _QWEN.sub(_qwen_sub, rest) if has_xml else rest

    # 4c) JSON di dalam code fence (cline PR #11272).
    _FENCED = re.compile(r"```(?:json|tool_call)?\s*\n(.*?)```", re.DOTALL)

    def _fenced_sub(m: re.Match) -> str:
        body = m.group(1).strip()
        brace = body.find("{")
        if brace < 0:
            return m.group(0)
        got = _scan_balanced_json(body, brace)
        if not got:
            return m.group(0)
        obj = _loads_lenient(got[0])
        if not obj:
            return m.group(0)
        tool = str(obj.get("name") or "").strip()
        raw = obj.get("arguments", obj.get("parameters", {}))
        args = raw if isinstance(raw, dict) else _loads_lenient(str(raw))
        if tool:
            calls.append({"name": tool, "args": args or {}})
            return ""
        return m.group(0)

    rest = _FENCED.sub(_fenced_sub, rest) if has_fence else rest

    return calls, rest


def extract_textual_tool_calls(text: str) -> list[dict]:
    """Ambil daftar tool call yang tertanam di TEKS balasan model.

    Mengembalikan list `{"name": str, "args": dict}`. Kosong bila tidak ada.
    """
    # Guard awal: hanya lewati bila memang tidak ada penanda sama sekali.
    # Dulu hanya "<" yang dicek, padahal JSON di dalam code fence tidak punya
    # "<" sama sekali -> parser tidak pernah sempat jalan.
    if not text or ("<" not in text and "{" not in text):
        return []
    calls, _ = _match_all(text)
    return calls


def strip_textual_tool_calls(text: str) -> str:
    """Buang blok tool-call dari teks supaya JSON mentah tidak tampil ke user.

    BUG FIX 2026-10-04, bug 3 - kebocoran JSON ke user.
    Versi lama: `return out or text.strip()`.—when SELURUH balasan model adalah
    satu tool call, `rest` jadi kosong, `out` falsy, lalu fungsi mengembalikan
    TEKS ASLI. Akibatnya parse-nya BERHASIL tapi user tetap melihat JSON/XML
    mentah persis keluhan yang dilaporkan. Contoh nyata:

        HERMES = '<tool_call>{"name":...}</tool_call>'
        extract -> [call]        (berhasil)
        strip   -> teks aslinya  ( bocor )

    Perbaikan: kalau ada call yang berhasil diekstrak, sisa yang kosong itu
    memang jawaban yang benar - kembalikan "". `text.strip()` hanya dipakai
    sebagai fallback saat TIDAK ada call sama sekali.
    """
    if not text:
        return ""
    calls, rest = _match_all(text)
    out = rest.strip()
    if calls:
        # Ada call yang diproses: sisa kosong = tidak ada teks lain untuk user.
        return out
    return text.strip()