"""tool_policy_gate.py — gerbang kebijakan deterministik untuk tool call.

PRINSIP (dari mcp-guardrails / gatehouse-ai / pydantic-ai-toolguard)
----------------------------------------------------------------------
  * Fungsi MURNI: tidak ada I/O, tidak ada LLM, tidak ada jaringan.
  * DENY by default: tanpa aturan ALLOW yang cocok, hasilnya DENY.
  * DENY diperiksa lebih dulu, lalu REQUIRE_APPROVAL, lalu ALLOW.
  * Setiap keputusan bisa dijelaskan dalam satu kalimat.

Kenapa perlu (hasil audit, lihat docs/security/threat-model-tool-injection.md):
Selama ini satu-satunya gerbang adalah "apakah string cocok regex".
Regex bukan kontrol akses. Siapa pun bisa menulis `[TELEGRAM: ...]` di
pesan dan bergantung pada model untuk mengikutinya. Gate ini menutup
celah itu secara deterministik: daftar alat dan syaratnya ditegakkan di
kode, bukan bergantung pada kesetiaan LLM.
"""

from __future__ import annotations

import re
from enum import Enum


class Disposition(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


#: Nama alat tekstual yang boleh dipanggil model.
TEXTUAL_TOOLS = frozenset({
    "VAULT", "WORKFLOW", "EMAIL", "SHEETS", "TELEGRAM", "SLACK",
})

#: Nama alat native (dipanggil lewat `tools.execute_tool`) yang diizinkan.
#: CATATAN (6 Okt 2026): disamakan dengan `TOOL_DECLARATIONS` di `tools.py`
#: (13 deklarasi). Sebelumnya daftar ini hanya 9 -> 4 alat nyata
#: (`send_whatsapp_message`, `kirim_email_gmail`, `tambah_agenda_calendar`,
#: `buat_google_spreadsheet`) jatuh ke "tidak ada di allowlist" -> DENY total
#: bila gate benar-benar dijalankan. Dengan gate kini aktif di jalur direct,
#: ketidaksinkronan itu akan memblokir alat yang sah.
NATIVE_TOOLS = frozenset({
    "check_credential",
    "generate_workflow_json",
    "kirim_telegram_message",
    "kirim_slack_message",
    "kirim_email_gmail",
    "send_whatsapp_message",
    "trigger_gmail_imap",
    "write_sheets_dynamic",
    "buat_google_spreadsheet",
    "tambah_agenda_calendar",
    "baca_google_sheets",
    "http_request",
    "web_search",
})

#: Alat yang MENGIRIM DATA KE PIHAK LUAR -> wajib persetujuan user.
#:
#: BUG FIX 2026-10-06 (approval card tidak pernah muncul di produksi):
#: sebelumnya baris REQUIRE_APPROVAL hanya membandingkan nama TEKSTUAL
#: (`("TELEGRAM", "SLACK")`). Model di jalur Gemini langsung memanggil nama
#: NATIVE (`kirim_telegram_message`), yang setelah `_tool_name()` menjadi
#: `KIRIM_TELEGRAM_MESSAGE` dan TIDAK cocok -> jatuh ke `ALLOW`, lalu
#: `_agentic_run_direct` mengeksekusinya tanpa kartu persetujuan.
#:
#: Perbaikan ini SENGAJA hanya menyamakan nama native dengan pasangan
#: TEKSTUAL-nya yang SUDAH `REQUIRE_APPROVAL` (TELEGRAM, SLACK). Disposisi
#: alat tekstual lain (EMAIL, SHEETS) TIDAK diubah: itu keputusan keamanan
#: terpisah yang sudah dikunci `tests/test_tool_injection.py`
#: (`test_vektor7_d_subjek_normal_boleh` menuntut EMAIL normal = ALLOW).
#: Mengubahnya di sini = memperlebar scope Bug #1 dan memecah kontrak lama.
#: (Celah EMAIL/SHEETS dicatat sebagai temuan terpisah, bukan diperbaiki
#: diam-diam di commit ini.)
EXTERNAL_SEND_TOOLS = frozenset({
    # tekstual (bracket) — hanya yang memang sudah REQUIRE_APPROVAL
    "TELEGRAM", "SLACK",
    # native (function-call Gemini) — pasangan dari TELEGRAM/SLACK
    "KIRIM_TELEGRAM_MESSAGE", "KIRIM_SLACK_MESSAGE",
})

#: Prefix yang SELALU ditolak, apa pun konteksnya.
DENY_PREFIXES = ("delete_", "drop_", "execute_", "truncate_", "revoke_",
                 "admin_", "impersonate_", "reset_")

#: Alat DATA-ONLY: hanya MENYIMPAN/MEMVALIDASI data, tidak menjalankan
#: perintah shell apa pun. Untuk alat ini, pola injeksi SHELL di dalam nilai
#: teks (backtick, `$(...)`, `;`/`|`) adalah isi sah, bukan serangan — spec
#: workflow sering memuat markdown. Pola path-traversal/SQL/kredensial TETAP
#: berlaku (lihat `_DATA_SAFE_PATTERNS`).
DATA_ONLY_TOOLS = frozenset({
    "GENERATE_WORKFLOW_JSON", "WORKFLOW",
})

#: Batas keras per giliran (anti loop injection / DoS).
MAX_CALLS_PER_TURN = 5
MAX_ARG_BYTES = 4096
MAX_ARGS_PER_CALL = 12

#: Pola yang tidak boleh muncul di argumen apa pun. Ini yang menangkap
#: path traversal dan command injection di dalam nilai string.
#:
#: Catatan: daftar ini PUNGLING, bukan lengkap. Tujuannya memblokir kelas
#: serangan yang jelas, bukan menjadi filter universal. allowlist per-alat
#: (lihat `ARG_SCHEMAS` di argument_validator) yang menutup sisanya.
_DENY_PATTERNS = (
    re.compile(r"\.\./", re.I),
    re.compile(r"\.\.\\", re.I),
    # Substitusi perintah: $(...), backtick, pipe, dan titik koma.
    # Nama perintah dibuat longgar agar `whoami`/`id`/`env` pun tertangkap,
    # bukan hanya rm/cat.
    re.compile(r"\$\([^)]*\)"),
    re.compile(r"`[^`]*`"),
    # `&&` (dua ampersand berturut) tetap ditolak: itu operator shell.
    # Satu `&` SAH (umum di teks like "Sales & Marketing"), jadi tidak
    # ikut diblokir: false positive pada teks user yang valid adalah
    # kerusakan nyata, bukan sekadar theoretis.
    re.compile(r"&&", re.I),
    # Hanya `;` dan `|`, BUKAN `&` tunggal.
    re.compile(r"[;|]\s*\S+", re.I),
    re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"),
    re.compile(r"/etc/(passwd|shadow)", re.I),
    # SQL: SELECT..FROM, INSERT..INTO, DELETE/UPDATE/DROP..FROM, OR/AND '1'='1
    re.compile(r"\bselect\b.+\bfrom\b", re.I | re.S),
    re.compile(r"\b(insert|update|delete|drop|truncate)\b.+\b(into|set|from|table)\b",
               re.I | re.S),
    re.compile(r"(or|and)\s+'?[\w-]+'?\s*=\s*'?[\w-]+'?", re.I),
    re.compile(r"(--|#)\s*$", re.I),
    re.compile(r";\s*(drop|delete|update|insert|truncate)\b", re.I),
    re.compile(r"^\s*-{1,2}[a-z]+\s+http", re.I),
    # --- SSRF (2026-10-06) --------------------------------------------------
    # TEMUAN chaos test: `validate_call("http_request", {"url":
    # "http://169.254.169.254/latest/meta-data/"})` mengembalikan **ALLOW**.
    # Alatnya sendiri (`tools.http_request`) memang sudah menolak host
    # internal/loopback, jadi ini BUKAN celah yang bisa dieksploitasi — tetapi
    # gerbang seharusnya gagal-tertutup LEBIH DULU: penolakan di lapisan alat
    # muncul sebagai error runtime, bukan sebagai keputusan kebijakan.
    # Pola ini hanya ditambahkan ke daftar PENUH, bukan ke `_DATA_SAFE_PATTERNS`:
    # alat data-only boleh memuat teks apa pun (mis. spec workflow yang
    # menyebut "localhost" sebagai dokumentasi) tanpa DENY palsu.
    re.compile(r"https?://(?:localhost|127\.|0\.0\.0\.0|\[::1\]|10\.|192\.168\.|"
               r"172\.(?:1[6-9]|2\d|3[01])\.|169\.254\.)", re.I),
    # Skema selain http/https (file://, gopher://, ...) tidak pernah sah untuk
    # alat HTTP; menolaknya di gerbang menjaga perilaku tetap seragam.
    re.compile(r"\b(?:file|gopher|dict|ftp|ldap|tftp)://", re.I),
)

#: Subset pola yang TETAP berlaku untuk alat data-only.
#:
#: Alat data-only tidak mengeksekusi apa pun, jadi pola injeksi SHELL
#: (backtick, `$(...)`, `;`/`|`, `${VAR}`, flag CLI) tidak relevan dan
#: menghasilkan DENY palsu pada spec workflow yang sah. Yang tetap
#: berbahaya walau hanya disimpan: path traversal, akses berkas sistem,
#: dan pola SQL (spec bisa dipakai di langkah berikutnya).
_DATA_SAFE_PATTERNS = (
    re.compile(r"\.\./", re.I),
    re.compile(r"\.\.\\", re.I),
    re.compile(r"/etc/(passwd|shadow)", re.I),
    re.compile(r"\bselect\b.+\bfrom\b", re.I | re.S),
    re.compile(r"\b(insert|update|delete|drop|truncate)\b.+\b(into|set|from|table)\b",
               re.I | re.S),
    re.compile(r";\s*(drop|delete|update|insert|truncate)\b", re.I),
)


def _looks_like_secret(text: str) -> bool:
    """Deteksi kebocoran nilai rahasia ke dalam argumen.

    Sengaja konservatif: hanya pola yang jelas (GitHub/Slack/Telegram
    token, app password). Tujuannya menangkap kebocoran, bukan
    menyaring teks biasa milik user.
    """
    if re.search(r"\bghp_[A-Za-z0-9]{20,}", text):
        return True
    if re.search(r"\bxox[baprs]-[A-Za-z0-9-]{10,}", text):
        return True
    if re.search(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}", text):
        return True
    if re.search(r"\b[A-Za-z]{16}\b", text) and "password" in text.lower():
        return True
    return False


def validate_call(tool: str, args: dict, user_context: dict | None = None
                  ) -> tuple[Disposition, str]:
    """Kembalikan (disposition, alasan) untuk satu panggilan.

    Fungsi murni: hasil hanya bergantung pada argumennya.
    """
    name = _tool_name(tool)
    ctx = user_context or {}
    args = args if isinstance(args, dict) else {}

    # -- 1. DENY: nama alat
    if not name:
        return Disposition.DENY, "Nama alat kosong."
    low = name.lower()
    for pfx in DENY_PREFIXES:
        if low.startswith(pfx):
            return Disposition.DENY, f"Nama alat berawalan terlarang '{pfx}'."
    if name not in TEXTUAL_TOOLS and low not in NATIVE_TOOLS:
        return Disposition.DENY, f"Alat '{name}' tidak ada di allowlist."

    # -- 2. DENY: pola berbahaya di argumen
    # BUG FIX 2026-10-06 (false positive di jalur direct): `generate_workflow_json`
    # membawa SPEC JSON yang sah memuat backtick/markdown di dalam nilai
    # (`pesan`, `isi`). Pola injeksi shell (`\`...\``, `$(...)`, `;`/`|`) dibuat
    # untuk alat yang MENJALANKAN sesuatu, bukan untuk alat yang hanya
    # MENYIMPAN data. Jalur gateway dulu tak pernah terkena karena spec
    # workflow tiba lewat jalur tekstual terpisah; begitu gate dipasang di
    # jalur direct, spec JSON yang sah jadi DENY palsu.
    # Untuk alat data-only: lewati subset pola SHELL, tetap jalankan pola
    # path-traversal / SQL / kredensial (yang tetap relevan untuk data).
    flat = _flatten(args)
    _patterns = (_DATA_SAFE_PATTERNS if name in DATA_ONLY_TOOLS
                 else _DENY_PATTERNS)
    for pat in _patterns:
        if pat.search(flat):
            return Disposition.DENY, (
                f"Argumen memuat pola terlarang ({pat.pattern[:32]}).")
    if _looks_like_secret(flat):
        return Disposition.DENY, "Argumen memuat nilai yang mirip kredensial."

    # -- 3. DENY: ukuran (anti DoS)
    if len(args) > MAX_ARGS_PER_CALL:
        return (Disposition.DENY,
                f"Jumlah argumen {len(args)} melebihi batas {MAX_ARGS_PER_CALL}.")
    for k, v in args.items():
        if len(str(v).encode("utf-8", "ignore")) > MAX_ARG_BYTES:
            return Disposition.DENY, f"Argumen '{k}' melebihi {MAX_ARG_BYTES} byte."

    # -- 4. Cross-tenant: identitas tidak boleh datang dari argumen.
    for k in ("email", "user_email", "owner", "user", "as_user"):
        if k in args and str(args[k]).strip().lower() != str(
                ctx.get("email", "")).strip().lower():
            return Disposition.DENY, f"Argumen '{k}' mencoba menunjuk identitas lain."

    # -- 5. REQUIRE_APPROVAL: alat yang mengirim data ke luar
    # BUG FIX 2026-10-06: bandingkan terhadap SATU himpunan yang memuat
    # bentuk tekstual maupun native. Nama sudah di-upper oleh `_tool_name()`,
    # jadi cukup bandingkan `name` langsung.
    if name in EXTERNAL_SEND_TOOLS:
        return (Disposition.REQUIRE_APPROVAL,
                f"'{name}' mengirim data ke pihak luar; perlu persetujuan user.")

    # -- 6. Default ALLOW (hanya tercapai setelah semua DENY lolos)
    return Disposition.ALLOW, "Lolos seluruh aturan DENY dan batas ukuran."


class TurnBudget:
    """Batas jumlah panggilan tool per satu giliran percakapan.

    In-memory: cukup untuk menutup loop injection tanpa menambah
    dependensi. Untuk multi-instance Railway, ganti dengan store
    bersama (Redis) - antarmukanya tetap sama: `consume()`.
    """

    def __init__(self, limit: int = MAX_CALLS_PER_TURN):
        self.limit = limit
        self._used: dict[str, int] = {}

    def consume(self, turn_id: str) -> tuple[bool, str]:
        used = self._used.get(turn_id, 0)
        if used >= self.limit:
            return False, f"Anggaran {self.limit} tool call per giliran habis."
        self._used[turn_id] = used + 1
        return True, f"Tool call {self._used[turn_id]}/{self.limit}."

    def reset(self, turn_id: str) -> None:
        self._used.pop(turn_id, None)


#: Instance bersama untuk jalur chat.
TURN_BUDGET = TurnBudget()


__all__ = [
    "DENY_PREFIXES",
    "Disposition",
    "EXTERNAL_SEND_TOOLS",
    "MAX_ARG_BYTES",
    "MAX_ARGS_PER_CALL",
    "MAX_CALLS_PER_TURN",
    "NATIVE_TOOLS",
    "PolicyViolation",
    "TEXTUAL_TOOLS",
    "TURN_BUDGET",
    "TurnBudget",
    "validate_call",
]

class PolicyViolation(Exception):
    """Ditolak oleh gate. Pesannya aman ditampilkan ke pengguna."""


def _tool_name(tool_name: str) -> str:
    return str(tool_name or "").strip().upper()


def _flatten(value, depth: int = 0) -> str:
    """Ratakan argumen jadi teks untuk pemeriksaan pola."""
    if depth > 4:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten(v, depth + 1)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v, depth + 1) for v in value)
    return str(value)