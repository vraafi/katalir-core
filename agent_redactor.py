"""agent_redactor.py — redaksi FAIL-CLOSED untuk semua keluaran agent.

KONTEKS (brief E2E sandbox, 7 Okt 2026 — pola n8n PR #31929)
-----------------------------------------------------------
Keluaran agent (balasan chat, hasil tool, baris log workflow) bisa memuat
kredensial: token yang dikutip model, header yang disalin ke payload, URL
yang membawa `?token=...`, atau canary test yang bocor. Semua jalur itu
harus melewati SATU redaktor sebelum sampai ke user / disk.

FAIL-CLOSED
-----------
Arti "fail-closed" di sini konkret:
  * Tipe tak terduga tidak diteruskan apa adanya — ia dikonversi ke string
    lalu tetap dipindai. Kalau konversi pun gagal, kita MELEMPAR
    `RedactionError` (menahan data) alih-alih meneruskan data mentah.
  * Canary yang terdeteksi MELEMPAR `CanaryDetectedError` (bukan sekadar
    di-mask), karena kemunculannya berarti kredensial test benar-benar
    bocor dan harus dicabut.
  * Struktur bersarang dipindai sampai kedalaman terbatas; melewatinya
    menghasilkan `[REDACTED_DEPTH]`, bukan data mentah.

HUBUNGAN DENGAN `database.redact_sensitive`
-------------------------------------------
`database.py` sudah punya redaktor untuk baris `execution_logs` (F-2).
Modul ini adalah lapisan yang LEBIH LUAS (keluaran agent, canary, kunci
sensitif) dan SENGAJA tidak mengimpor `database` (yang menarik koneksi
Supabase) supaya tetap ringan dan bisa dipakai di mana saja. Kesetaraan
keduanya DIKUNCI OLEH TEST (`tests/test_agent_redactor.py::
TestParityDenganDatabase`), jadi tidak ada dua sumber kebenaran yang
diam-diam menyimpang.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# CANARY — konstanta dipakai juga oleh `credential_proxy`
# ---------------------------------------------------------------------------
CANARY_PREFIX = "KATALIR_TEST_CANARY_"

#: Panjang badan canary (hex 6 byte -> 12 karakter, upper).
CANARY_BODY_LEN = 12

CANARY_PATTERN_SRC = rf"{CANARY_PREFIX}[A-Z0-9]{{{CANARY_BODY_LEN}}}"

_CANARY_RX = re.compile(CANARY_PATTERN_SRC)
#: Pencarian longgar: cukup prefiks, supaya canary cacat/terpotong pun tertangkap.
_CANARY_LOOSE_RX = re.compile(re.escape(CANARY_PREFIX))


class CanaryDetectedError(RuntimeError):
    """Canary test muncul di keluaran — kredensial test BOCOR.

    Sengaja TIDAK mewarisi `ValueError` supaya tidak tertelan blok
    `except ValueError` yang lazim di sekitar pemanggilan tool.
    """

    def __init__(self, where: str = "output"):
        self.where = where
        super().__init__(
            "CANARY TERDETEKSI — kredensial test bocor! "
            "Cabut kredensial test sekarang, lalu perbaiki jalur kebocorannya."
        )


class RedactionError(RuntimeError):
    """Redaksi tidak bisa dijalankan — data DITAHAN (fail-closed)."""


# ---------------------------------------------------------------------------
# KUNCI yang nilainya SELALU diganti utuh (mirror `database._SENSITIVE_KEYS`)
# ---------------------------------------------------------------------------
SENSITIVE_KEYS = frozenset({
    "authorization", "auth", "proxy-authorization", "cookie", "set-cookie",
    "api_key", "apikey", "api-key", "x-api-key", "access_token",
    "refresh_token", "id_token", "token", "bearer", "secret", "client_secret",
    "password", "passwd", "private_key", "service_key", "service_role_key",
    "supabase_service_key", "session_token", "webhook_secret", "signature",
})

#: Nilai pengganti untuk kunci sensitif.
REDACTED = "[REDACTED]"

# ---------------------------------------------------------------------------
# 10 POLA KREDENSIAL + canary
#   (kategori, pola, pengganti) — kategori dipakai untuk STATISTIK (tanpa nilai)
# ---------------------------------------------------------------------------
CREDENTIAL_PATTERNS: tuple[tuple[str, "re.Pattern[str]", str], ...] = (
    # 1. Telegram bot token: <bot_id>:<35 char>
    ("telegram_bot",
     re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
     "[TELEGRAM_BOT_REDACTED]"),
    # 2. Google API key (Gemini/Cloud)
    ("google_api",
     re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
     "[GOOGLE_API_REDACTED]"),
    # 3. Slack token
    ("slack",
     re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
     "[SLACK_REDACTED]"),
    # 4. GitHub token
    ("github",
     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
     "[GITHUB_REDACTED]"),
    # 5. JWT (3 segmen base64url)
    ("jwt",
     re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"),
     "[JWT_REDACTED]"),
    # 6. Bearer generik (Authorization header mentah)
    ("bearer",
     re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
     "Bearer [REDACTED]"),
    # 7. API key di query-string URL.
    #    CATATAN: brief menulis pengganti `r'?\1=[REDACTED]'`. Itu BUG —
    #    pemisah `&` ikut berubah jadi `?` sehingga URL rusak. Diperbaiki
    #    dengan menangkap pemisahnya (`\1`) dan mempertahankannya.
    ("url_api_key",
     re.compile(r"([?&])(api[_-]?key|access[_-]?token|token|secret)=([^&\s\"']+)",
                re.IGNORECASE),
     r"\1\2=[REDACTED]"),
    # 8. OpenAI-style key
    ("openai",
     re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
     "[OPENAI_KEY_REDACTED]"),
    # 9. Google OAuth access token
    ("google_oauth",
     re.compile(r"\bya29\.[A-Za-z0-9._-]{20,}"),
     "[GOOGLE_OAUTH_REDACTED]"),
    # 10. AWS access key id
    ("aws",
     re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
     "[AWS_KEY_REDACTED]"),
    # 11. CANARY — terakhir, supaya saat `raise_on_canary=False` pun ia terganti.
    ("canary",
     _CANARY_RX,
     "[CANARY_DETECTED_ALERT]"),
)

#: Batas kedalaman rekursi (payload aneh/bersiklus tidak boleh membekukan server).
MAX_DEPTH = 8

#: Statistik redaksi: kategori -> jumlah penggantian. TANPA nilai mentah.
_STATS: dict[str, int] = {}
_STATS["canary_alerts"] = 0


def reset_stats() -> None:
    """Kosongkan penghitung statistik (dipakai antar-test)."""
    _STATS.clear()
    _STATS["canary_alerts"] = 0


def get_stats() -> dict[str, int]:
    """Salinan statistik redaksi (kategori -> jumlah). Tanpa nilai mentah."""
    return dict(_STATS)


def scan_canary(text: Any) -> bool:
    """True bila `text` memuat prefiks canary (pencarian longgar)."""
    if not isinstance(text, str):
        text = str(text)
    return bool(_CANARY_LOOSE_RX.search(text))


def redact(text: Any, *, raise_on_canary: bool = True) -> str:
    """Redaksi satu nilai skalar -> string aman.

    Fail-closed: tipe tak terduga dikonversi lalu dipindai; bila konversi
    gagal, `RedactionError` dilempar (data DITAHAN).
    """
    if isinstance(text, bytes):
        # decode lossless-ish: latin-1 tidak pernah gagal
        text = text.decode("latin-1")
    elif not isinstance(text, str):
        try:
            text = str(text)
        except Exception as exc:  # noqa: BLE001
            raise RedactionError(
                f"Tidak bisa mengonversi {type(text).__name__} untuk redaksi"
            ) from exc

    if not text:
        return text

    # Canary DULU: kemunculannya harus menggagalkan operasi, bukan di-mask.
    if raise_on_canary and _CANARY_LOOSE_RX.search(text):
        _STATS["canary_alerts"] = _STATS.get("canary_alerts", 0) + 1
        raise CanaryDetectedError()

    for category, rx, repl in CREDENTIAL_PATTERNS:
        text, n = rx.subn(repl, text)
        if n:
            _STATS[category] = _STATS.get(category, 0) + n

    return text


def redact_value(value: Any, *, raise_on_canary: bool = True,
                 _depth: int = 0) -> Any:
    """Redaksi rekursif untuk nilai apa pun (dict/list/tuple/str/skalar).

    * dict  -> kunci sensitif diganti utuh, sisanya rekursi
    * list/tuple -> tiap item rekursi (tuple kembali sebagai list)
    * str/bytes  -> `redact`
    * skalar aman (int/float/bool/None) -> diteruskan
    * objek lain -> dikonversi ke string lalu di-redact
    """
    if _depth > MAX_DEPTH:
        return "[REDACTED_DEPTH]"

    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, val in value.items():
            if isinstance(key, str) and key.strip().lower() in SENSITIVE_KEYS:
                out[key] = REDACTED
            else:
                out[key] = redact_value(val, raise_on_canary=raise_on_canary,
                                        _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        return [redact_value(v, raise_on_canary=raise_on_canary, _depth=_depth + 1)
                for v in value]

    if isinstance(value, (str, bytes)):
        return redact(value, raise_on_canary=raise_on_canary)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    # Objek lain: konversi lalu redact (fail-closed — jangan lewatkan mentah).
    return redact(value, raise_on_canary=raise_on_canary)


def redact_agent_output(output: Any, *, raise_on_canary: bool = True) -> Any:
    """Alias baca-alami: redaksi SEMUA field keluaran agent."""
    return redact_value(output, raise_on_canary=raise_on_canary)


__all__ = [
    "CANARY_PREFIX",
    "CANARY_BODY_LEN",
    "CANARY_PATTERN_SRC",
    "CanaryDetectedError",
    "RedactionError",
    "SENSITIVE_KEYS",
    "REDACTED",
    "CREDENTIAL_PATTERNS",
    "MAX_DEPTH",
    "reset_stats",
    "get_stats",
    "scan_canary",
    "redact",
    "redact_value",
    "redact_agent_output",
]
