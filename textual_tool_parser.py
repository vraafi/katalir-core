"""textual_tool_parser.py — pemanggilan tool lewat TEKS berkurung.

KENAPA MODUL INI ADA
-------------------
Gateway production memb-drop parameter `tools` (bukti empiris: HTTP 500
pada `qwen/qwen3.8-27b` begitu `tools` disisipkan, sementara tanpa
`tools` balas 200). Jadi Katalir TIDAK bergantung pada native tool
calling. Model menulis token teks berformat tetap, modul ini mendeteksi
dan mengeksekusinya.

Format:  [NAMA_TOOL: argumen]

    [VAULT: gmail_imap]
    [WORKFLOW: inventory_email_to_sheets]
    [EMAIL: cek subjek=inventory max=10]
    [SHEETS: write spreadsheet=laporan_verdi sheet=inventory]
    [TELEGRAM: chat_id=2109751369 pesan="Halo dunia"]
    [SLACK: channel=#general pesan=Update selesai]

KEUNGGULAN
----------
Model-agnostic (Qwen/Gemma/DeepSeek/Llama), deterministik (format kita),
dan tidak butuh dukungan tool gateway maupun model.

DESAIN FAIL-CLOSED
------------------
Mengikuti `tool_call_parser.py` (parser XML) yang sudah dipakai produksi:
  * hanya nama di `ALLOWED_TOOLS` yang dieksekusi - `[FOO: x]` diabaikan
    total, bukan dieksekusi lalu gagal;
  * argumen rusak TIDAK pernah dieksekusi, dilewati dengan diam;
  * `[TOOL: ...]` di dalam code fence / inline code DIPAKSAI sebagai
    dokumentasi contoh, bukan panggilan. Ini penting: system prompt
    berisi contoh-bercontoh, dan model bisa menyalinnya ke jawaban.

BUG YANG SUDAH DIPERBAIKI DARI SKETSA BRIEF
-------------------------------------------
`parse_kv_args` di brief memakai `s.split()`, sehingga
`pesan=Halo dunia` menghasilkan `pesan="Halo"` dan membuang `dunia`.
Test 5 di brief sendiri memverifikasi kasus itu. Di sini nilai
ber-spasi harus diapit tanda kutip; tanpa kutip, kata tambahan
diabaikan. `split()` juga memecah nilai berkutip jadi beberapa token.
"""

from __future__ import annotations

import re

#: Nama tool yang dikenali. Di luar daftar ini = bukan tool.
ALLOWED_TOOLS: frozenset[str] = frozenset({
    "VAULT", "WORKFLOW", "EMAIL", "SHEETS", "TELEGRAM", "SLACK",
})

#: `[NAME: args]` - args tidak boleh memuat `]` (batas penutup).
BRACKET_RE = re.compile(
    r"\[\s*(?P<tool>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<args>[^\]\n]*)\]",
)

#: Nama tool yang dipanggil dengan satu nilai bebas (bukan key=value).
FREE_FORM_TOOLS: frozenset[str] = frozenset({"VAULT", "WORKFLOW"})

#: Key yang boleh dipakai per tool. Mencegah model mengarang parameter
#: yang tidak ada handler-nya (mis. `token=` pada TELEGRAM).
ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "EMAIL": frozenset({"subjek", "max", "unread_only", "mailbox"}),
    "SHEETS": frozenset({"spreadsheet", "sheet", "values", "range_data"}),
    "TELEGRAM": frozenset({"chat_id", "pesan"}),
    "SLACK": frozenset({"channel", "pesan"}),
}

#: Bagian yang tidak boleh dieksekusi: contoh di dalam blok kode.
_CODE_SPAN_RE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)


def _strip_code(text: str) -> str:
    """Blank-out blok kode (tanpa mengubah jumlah karakter).

    Offset harus dijaga karena `strip_textual_tools` memakai `re.sub`
    pada teks ASLI; kalau panjang berubah, sisa blok ikut terhapus.
    """
    return _CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), text)


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v
def parse_kv_args(s: str) -> tuple[dict, list]:
    """Parse `key=value key2="value dengan spasi"`.

    Return: (args, kata_yang_diabaikan)

    Kata tanpa `=` diabaikan (bukan error) karena kalimat pembuka model
    seperti "cek email subjek=inventory" wajar terjadi. Nilai tanpa
    kutip TIDAK boleh mengandung spasi.
    """
    args: dict[str, str] = {}
    ignored: list[str] = []
    # PENTING 1: pakai NON-CAPTURING group. Kalau ada `(` biasa,
    # `findall` mengembalikan TUPLE per grup, bukan teks utuh, sehingga
    # `pesan="Halo dunia"` jadi terpisah weird.
    # PENTING 2: `key="value dengan spasi"` harus jadi SATU token, jadi
    # bentuk key=quoted diuji SEBELUM `\S+`; kalau tidak, spasi
    # memisahkan `pesan=` dari `"Halo dunia"`.
    token_re = re.compile(
        r'[\w.]+\s*=\s*"[^"]*"'      # key="dengan spasi"
        r"|[\w.]+\s*=\s*'[^']*'"
        r"|[\w.]+\s*=\s*\S+"
        r'|"[^"]*"|\'[^\']*\'|\S+'
    )
    for tok in token_re.findall(s or ""):
        if "=" not in tok:
            ignored.append(_unquote(tok))
            continue
        key, _, raw = tok.partition("=")
        args[key.strip().lower()] = _unquote(raw)
    return args, ignored


def parse_textual_tools(content: str) -> list[dict]:
    """Parse semua `[TOOL: args]` yang aman dieksekusi.

    Return: list of {"tool", "args", "raw", "index"}

    Yang DILEWATI (bukan error):
      * nama di luar `ALLOWED_TOOLS` -> teks biasa milik user;
      * call di dalam code fence / inline code -> contoh dokumentasi.
    """
    if not content:
        return []
    scannable = _strip_code(content)

    out: list[dict] = []
    for m in BRACKET_RE.finditer(scannable):
        tool = m.group("tool").upper()
        if tool not in ALLOWED_TOOLS:
            continue

        raw_args = m.group("args").strip()
        if tool in FREE_FORM_TOOLS:
            # [VAULT: gmail_imap] -> {"provider": "gmail_imap"}
            kv, _ = parse_kv_args(raw_args)
            key = "provider" if tool == "VAULT" else "name"
            value = kv.get(key) or (raw_args if not kv else None)
            if not value:
                continue
            args = {key: _unquote(value)}
        else:
            # Buang kata kerja di depan ("cek", "write") yang bukan key.
            head = raw_args.split(None, 1)
            body = head[1] if (head and "=" not in head[0]) else raw_args
            kv, _ignored = parse_kv_args(body)
            # BUG FIX 2026-10-06 (approval card Telegram tidak muncul):
            # field yang TIDAK dikenal JANGAN dibuang diam-diam.
            #
            # Versi lama menyaring `k in allowed` lalu `if not args: continue`.
            # Akibatnya `[TELEGRAM: chat_id=123 text="halo"]` (model memakai
            # `text` alih-alih `pesan`) menghasilkan `args={"chat_id":"123"}`
            # dan `pesan` HILANG tanpa peringatan apa pun - parser menelan
            # datanya, lalu alat dijalankan dengan argumen tidak lengkap.
            # Dari sisi user gejalanya: persetujuan tidak pernah muncul, atau
            # terkirim tanpa isi, dan tidak ada error yang bisa ditelusuri.
            #
            # Sekarang SELURUH field diteruskan apa adanya. Yang menilai
            # adalah `argument_validator` (allowlist per-alat), yang memang
            # dirancang untuk menolak field asing dengan alasan eksplisit -
            # bukan menyembunyikannya.
            args = dict(kv)
            if not args:
                continue

        out.append({"tool": tool, "args": args, "raw": m.group(0),
                    "index": m.start()})
    return out


def strip_textual_tools(content: str) -> str:
    """Hapus blok `[TOOL: ...]` dari teks yang ditampilkan ke user.

    Call di dalam code fence TETAP dipertahankan: di situ blok itu
    dokumentasi yang sedang diperiksa user, bukan noise.
    """
    if not content:
        return ""
    scannable = _strip_code(content)
    spans = [m.span() for m in BRACKET_RE.finditer(scannable)
             if m.group("tool").upper() in ALLOWED_TOOLS]
    if not spans:
        return content.strip()
    chars = list(content)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars).strip()


__all__ = [
    "ALLOWED_KEYS",
    "ALLOWED_TOOLS",
    "BRACKET_RE",
    "FREE_FORM_TOOLS",
    "parse_kv_args",
    "parse_textual_tools",
    "strip_textual_tools",
]