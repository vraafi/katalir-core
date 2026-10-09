"""execution_redaction.py — Fitur #11a: Executive redaction PII per-workflow.

RISET (Okt 2026)
----------------
n8n 2.16.0 memperkenalkan *execution data redaction* per-workflow:
  * dua toggle independen — redact **production executions** dan redact
    **manual executions** (n8n docs: "Redact execution data");
  * metadata (status, timing, node names) TETAP terlihat; hanya payload
    yang diganti penanda;
  * error di-redact menyisakan tipe + HTTP status;
  * binary (file/gambar) DIBUANG, tidak di-redact sebagian;
  * n8n 2.26.0 menambah *enforcement* instance-wide: sebuah LANTAI MINIMUM
    yang **tidak boleh dilemahkan** oleh setelan workflow; workflow masih
    boleh memilih yang LEBIH KETAT (mis. enforce=production, workflow minta
    manual+production → diizinkan; sebaliknya DITOLAK);
  * scope RBAC: `workflow:enableRedaction`, `workflow:disableRedaction`,
    `execution:reveal`; reveal memancarkan audit event
    `n8n.audit.execution.data.revealed` / `...reveal_failure`;
  * redaksi diterapkan di **lapisan API** — data mentah di DB tidak berubah.

Model di modul ini mengikuti bentuk itu, tetapi menambahkan apa yang n8n
TIDAK punya: **pola PII** (email/telepon/SSN/kartu kredit) dan **regex
kustom per-workflow**, serta keputusan diterapkan **sebelum** baris log
dibentuk (bukan saat dibaca), sehingga payload sensitif tidak pernah
menyentuh disk.

HUBUNGAN DENGAN MODUL LAIN
--------------------------
* `agent_redactor` — redaksi kredensial fail-closed (10 pola + canary).
  Modul ini MEMAKAI-nya lebih dulu, lalu menambah lapisan PII. Menerapkan
  kredensial dulu berarti nilai yang sudah diganti tidak bisa "terbaca
  ulang" sebagai PII.
* `database.execution_log_row` — titik tunggal pembentukan baris
  `execution_logs`. Modul ini menyediakan `apply_to_log_row()` yang
  dipanggil di sana, sehingga tidak ada jalur tulis yang terlewat
  (prinsip yang sama dengan F-2).

FAIL-SAFE
---------
Redaksi bersifat *fail-closed pada kebijakan, fail-open pada ketersediaan*:
  * Regex kustom yang tidak bisa dikompilasi DITOLAK saat validasi
    (`RedactionPolicyError`) — bukan diam-diam diabaikan.
  * Pola kustom dibatasi panjangnya (ReDoS guard) dan diberi timeout
    eksekusi kooperatif (lihat `_regex_safe`).
  * Bila regex kustom justru gagal saat runtime, hasilnya diganti penanda
    `[REDACTED_PATTERN_ERROR]` (data disembunyikan, bukan diloloskan).
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Iterable

from agent_redactor import (
    RedactionError,
    get_stats as _cred_stats,
    redact_value as _redact_credentials,
    reset_stats as _reset_cred_stats,
)

# ---------------------------------------------------------------------------
# Kebijakan
# ---------------------------------------------------------------------------
#: Nilai kebijakan yang sah, dari paling longgar ke paling ketat.
REDACTION_LEVELS = ("off", "production", "all")

#: Urutan kekuatan — dipakai untuk membandingkan enforcement vs workflow.
_LEVEL_RANK = {"off": 0, "production": 1, "all": 2}

#: Penanda yang dipakai untuk PII yang disembunyikan.
PII_PLACEHOLDERS = {
    "email": "[REDACTED_EMAIL]",
    "phone": "[REDACTED_PHONE]",
    "ssn": "[REDACTED_SSN]",
    "credit_card": "[REDACTED_CARD]",
    "ipv4": "[REDACTED_IP]",
    "custom": "[REDACTED_CUSTOM]",
    "depth": "[REDACTED_DEPTH]",
    "pattern_error": "[REDACTED_PATTERN_ERROR]",
}

#: Batas panjang pola kustom (ReDoS guard).
MAX_PATTERN_LEN = 300

#: Batas waktu KOOPERATIF untuk satu regex kustom saat runtime (detik).
REGEX_TIME_BUDGET_SEC = 0.35


class RedactionPolicyError(ValueError):
    """Kebijakan redaksi tidak sah (level tak dikenal / regex rusak)."""


class RedactionPolicy:
    """Kebijakan redaksi untuk SATU workflow.

    Attributes dipisah supaya bisa dibandingkan dengan enforcement
    instance-wide lewat `effective_level()`.
    """

    __slots__ = ("level", "pii_types", "custom_patterns", "enabled_at",
                 "updated_by")

    def __init__(self, level: str = "off",
                 pii_types: Iterable[str] | None = None,
                 custom_patterns: Iterable[dict] | None = None,
                 enabled_at: float | None = None,
                 updated_by: str = ""):
        self.level = self._validate_level(level)
        #: Default: SEMUA jenis PII dikenali (sesuai "protect personal data"
        #: di dokumen n8n). Bisa dipersempit agar debug lebih mudah.
        self.pii_types = tuple(sorted(set(pii_types or REDACTABLE_PII)))
        bad = [t for t in self.pii_types if t not in REDACTABLE_PII]
        if bad:
            raise RedactionPolicyError(
                f"pii_types tidak dikenal: {sorted(bad)}; "
                f"pilihan: {sorted(REDACTABLE_PII)}"
            )
        self.custom_patterns = _compile_custom(custom_patterns or [])
        self.enabled_at = enabled_at if enabled_at is not None else time.time()
        self.updated_by = str(updated_by or "")

    # -- konstruksi --------------------------------------------------------
    @staticmethod
    def _validate_level(level: str) -> str:
        lvl = str(level or "off").strip().lower()
        if lvl not in _LEVEL_RANK:
            raise RedactionPolicyError(
                f"level redaksi tidak dikenal: {level!r}; "
                f"pilihan: {list(REDACTION_LEVELS)}"
            )
        return lvl

    @classmethod
    def from_dict(cls, data: dict | None) -> "RedactionPolicy":
        data = data or {}
        return cls(
            level=data.get("level", "off"),
            pii_types=data.get("pii_types"),
            custom_patterns=data.get("custom_patterns"),
            enabled_at=data.get("enabled_at"),
            updated_by=data.get("updated_by", ""),
        )

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "pii_types": list(self.pii_types),
            "custom_patterns": [
                {"name": n, "pattern": p, "placeholder": ph}
                for (n, p, ph, _rx) in self.custom_patterns
            ],
            "enabled_at": self.enabled_at,
            "updated_by": self.updated_by,
        }

    # -- semantik ----------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.level != "off"

    def redacts_production(self) -> bool:
        return self.level in ("production", "all")

    def redacts_manual(self) -> bool:
        return self.level == "all"

    def applies_to(self, trigger: str) -> bool:
        """True bila kebijakan ini menutup eksekusi dengan `trigger`.

        `trigger` = "manual" untuk eksekusi yang dijalankan pengguna dari
        editor, selain itu dianggap produksi ("production"/"webhook"/...).
        """
        t = str(trigger or "production").strip().lower()
        if t == "manual":
            return self.redacts_manual()
        return self.redacts_production()

    def covers(self, other_level: str) -> bool:
        """True bila level ini SAMA ATAU LEBIH KETAT dari `other_level`."""
        return _LEVEL_RANK[self.level] >= _LEVEL_RANK[self._validate_level(other_level)]

    # -- perbandingan dengan enforcement ------------------------------------
    def effective_level(self, enforced: str | None) -> str:
        """Level yang BENAR-BENAR berlaku setelah enforcement diterapkan.

        Enforcement adalah **lantai minimum**: workflow tidak bisa lebih
        lemah. `off` + enforced `production` -> `production`.
        """
        if not enforced or str(enforced).strip().lower() in ("", "off"):
            return self.level
        enf = self._validate_level(enforced)
        return enf if _LEVEL_RANK[enf] > _LEVEL_RANK[self.level] else self.level

    def weaker_than(self, enforced: str | None) -> bool:
        """True bila kebijakan workflow LEBIH LEMAH dari enforcement.

        Dipakai API untuk MENOLAK permintaan yang mencoba melemahkan
        lantai minimum (perilaku n8n 2.26.0 yang dikunci test).
        """
        if not enforced or str(enforced).strip().lower() in ("", "off"):
            return False
        return not self.covers(enforced)


# ---------------------------------------------------------------------------
# Pola PII
# ---------------------------------------------------------------------------
def _luhn_ok(number: str) -> bool:
    """Validasi Luhn (checksum kartu kredit).

    Tanpa ini, 16 digit acak (mis. nomor pesanan) akan salah dianggap
    kartu kredit — false positive yang membuat log tidak berguna.
    """
    digits = [int(c) for c in re.sub(r"\D", "", number)]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


#: Nama kanonik jenis PII yang bisa di-redact.
REDACTABLE_PII = ("email", "phone", "ssn", "credit_card", "ipv4")

_EMAIL_RX = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
# Telepon: E.164 (+62812...), format Indonesia (0812-3456-7890), gaya US
# dengan kurung `(021) 555-1234`, dan pemisah spasi/titik/strip.
# Sengaja TIDAK menangkap angka biasa maupun tanggal ISO (dijaga di replacer).
_PHONE_RX = re.compile(
    r"(?<![\w@.])"
    r"(?:"
    r"\+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)[\s.\-]?)?\d[\d\s.\-]{6,17}\d"
    r"|"
    r"\(\d{2,4}\)[\s.\-]?\d[\d\s.\-]{5,15}\d"
    r"|"
    r"\d{3,4}[\s.\-]\d{3,4}[\s.\-]?\d{0,4}"
    r"|"
    # Mobile Indonesia tanpa pemisah: 08xx / +628xx / 628xx (9-14 digit).
    r"(?:\+?62|0)8\d{7,11}"
    r")"
    r"(?![\w])"
)
_SSN_RX = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CARD_LOOSE_RX = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
#: Jalur tanpa pemisah (mis. `4111111111111111`).
_CARD_DIGITS_RX = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_IPV4_RX = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])"
)


def _redact_phone(text: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        # Minimal 9 digit (nomor Indonesia) atau tanda + eksplisit.
        if len(digits) < 9 and not raw.startswith("+"):
            return raw
        # Hindari menelan tanggal/versi seperti 2026-10-09.
        if re.fullmatch(r"\d{4}[\-/]\d{2}[\-/]\d{2}", raw):
            return raw
        return PII_PLACEHOLDERS["phone"]
    return _PHONE_RX.sub(repl, text)


def _redact_card(text: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if not _luhn_ok(digits):
            return raw
        # Pertahankan spasi pemisah DI LUAR kecocokan supaya kalimat tidak
        # kehilangan spasi ("card X ok" bukan "card [CARD]ok").
        lead = " " if raw and raw[0] == " " else ""
        trail = " " if raw and raw[-1] == " " else ""
        return f"{lead}{PII_PLACEHOLDERS['credit_card']}{trail}"
    out = _CARD_LOOSE_RX.sub(repl, text)
    return _CARD_DIGITS_RX.sub(
        lambda m: PII_PLACEHOLDERS["credit_card"] if _luhn_ok(m.group(0))
        else m.group(0), out)


#: (jenis, penerap) — urutan penting: kartu sebelum telepon supaya deret
#: 16 digit tidak dipotong lebih dulu oleh pola telepon.
_PII_APPLIERS = {
    "email": lambda s: _EMAIL_RX.sub(PII_PLACEHOLDERS["email"], s),
    "credit_card": _redact_card,
    "ssn": lambda s: _SSN_RX.sub(PII_PLACEHOLDERS["ssn"], s),
    "phone": _redact_phone,
    "ipv4": lambda s: _IPV4_RX.sub(PII_PLACEHOLDERS["ipv4"], s),
}

#: Urutan eksekusi yang dipakai `redact_text`.
APPLY_ORDER = ("email", "credit_card", "ssn", "phone", "ipv4")


# ---------------------------------------------------------------------------
# Regex kustom
# ---------------------------------------------------------------------------
def compile_custom_pattern(name: str, pattern: str,
                           placeholder: str = "") -> tuple:
    """Kompilasi satu pola kustom. Raise `RedactionPolicyError` bila rusak.

    Aturan (dikunci test):
      * `name` wajib, 1..64 karakter alfanumerik/`_`/`-`;
      * `pattern` wajib, <= `MAX_PATTERN_LEN`, harus **punya grup atau
        bisa dicocokkan** — pola yang cocok STRING KOSONG ditolak karena
        akan menyisipkan penanda tanpa henti (mis. `.*`, `a?`);
      * `placeholder` default `[REDACTED_CUSTOM]`.
    """
    nm = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", nm):
        raise RedactionPolicyError(
            f"nama pola kustom tidak sah: {name!r} (wajib 1-64 karakter "
            "[A-Za-z0-9_-])"
        )
    pat = str(pattern or "")
    if not pat:
        raise RedactionPolicyError(f"pola kustom '{nm}' kosong")
    if len(pat) > MAX_PATTERN_LEN:
        raise RedactionPolicyError(
            f"pola kustom '{nm}' terlalu panjang "
            f"({len(pat)} > {MAX_PATTERN_LEN} karakter) — ReDoS guard"
        )
    try:
        rx = re.compile(pat)
    except re.error as exc:
        raise RedactionPolicyError(
            f"pola kustom '{nm}' tidak bisa dikompilasi: {exc}"
        ) from exc
    # Pola yang cocok string kosong -> penyisipan tanpa henti. Tolak.
    if rx.search("") is not None:
        raise RedactionPolicyError(
            f"pola kustom '{nm}' cocok dengan string kosong — akan "
            "menyisipkan penanda tanpa henti; persempit polanya"
        )
    ph = str(placeholder or "").strip() or PII_PLACEHOLDERS["custom"]
    return (nm, pat, ph, rx)


def _compile_custom(items: Iterable[dict]) -> tuple:
    out = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise RedactionPolicyError(
                f"pola kustom harus objek {{name, pattern}}, bukan "
                f"{type(item).__name__}"
            )
        nm, pat, ph, rx = compile_custom_pattern(
            item.get("name", ""), item.get("pattern", ""),
            item.get("placeholder", ""))
        if nm in seen:
            raise RedactionPolicyError(f"nama pola kustom duplikat: {nm!r}")
        seen.add(nm)
        out.append((nm, pat, ph, rx))
    return tuple(out)


def _safe_sub(rx: "re.Pattern[str]", repl: str, text: str,
              budget: float = REGEX_TIME_BUDGET_SEC) -> tuple[str, int, bool]:
    """`rx.sub` yang aman-untuk-waktu. Kembalikan `(teks, n, ok)`.

    Python `re` tidak bisa diinterupsi, jadi sebuah pola kustom yang buruk
    (`(a+)+$`) bisa menahan proses. Yang bisa dilakukan: batasi panjang
    teks yang diproses dan periksa anggaran waktu SETELAH-nya. Bila
    anggaran terlampaui (atau `re` gagal), kembalikan `ok=False` supaya
    pemanggil menyembunyikan seluruh nilai — fail-closed, bukan
    meloloskan data mentah.
    """
    if len(text) > 200_000:
        # Teks raksasa: jangan coba-coba jalankan regex pengguna.
        return text, 0, False
    started = time.perf_counter()
    try:
        out, n = rx.subn(repl, text)
    except Exception:  # noqa: BLE001 — regex sekarat tidak boleh meloloskan data
        return text, 0, False
    if time.perf_counter() - started > budget:
        return text, 0, False
    return out, n, True


def redact_text(text: str, policy: RedactionPolicy) -> tuple[str, dict[str, int]]:
    """Redaksi satu string. Kembalikan `(teks_aman, hitungan_per_kategori)`."""
    counts: dict[str, int] = {}
    out = text
    if policy.level == "off":
        return out, counts

    # Kartu/email lebih dulu supaya deret panjang tidak dipecah pola lain.
    for kind in APPLY_ORDER:
        if kind not in policy.pii_types:
            continue
        before = out
        out = _PII_APPLIERS[kind](out)
        if out != before:
            counts[kind] = counts.get(kind, 0) + 1

    for (nm, _pat, ph, rx) in policy.custom_patterns:
        out, n, ok = _safe_sub(rx, ph, out)
        if not ok:
            # Fail-closed: sembunyikan seluruh teks daripada membocorkannya.
            counts["pattern_error"] = counts.get("pattern_error", 0) + 1
            return PII_PLACEHOLDERS["pattern_error"], counts
        if n:
            counts["custom"] = counts.get("custom", 0) + n
    return out, counts


# ---------------------------------------------------------------------------
# Penerapan ke nilai bersarang
# ---------------------------------------------------------------------------
#: Kedalaman maksimum (sama dengan agent_redactor).
MAX_DEPTH = 8

#: Ekstensi biner yang SELALU dibuang (n8n: "removes binary data").
BINARY_HINTS = ("binary", "file", "attachment", "image", "screenshot",
                "blob", "pdf_bytes")


def _looks_binary(key: str, value: Any) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    k = str(key or "").strip().lower()
    return any(h in k for h in BINARY_HINTS)


def apply_policy(value: Any, policy: RedactionPolicy, *, trigger: str = "production",
                 _depth: int = 0) -> tuple[Any, dict[str, int]]:
    """Redaksi `value` menurut `policy`. Kembalikan `(nilai, hitungan)`.

    Urutan: kredensial (`agent_redactor`, fail-closed + canary) DULU,
    lalu PII + pola kustom. Bila eksekusi tidak tertutup kebijakan,
    nilai dikembalikan apa adanya TANPA menyentuh canary (agar perilaku
    lama tetap utuh).
    """
    counts: dict[str, int] = {}
    if not policy.applies_to(trigger):
        return value, counts

    creds = dict(_cred_stats())
    value = _redact_credentials(value)
    now = dict(_cred_stats())
    for k, v in now.items():
        delta = v - creds.get(k, 0)
        if delta:
            counts[k] = counts.get(k, 0) + delta
    value = _apply_pii(value, policy, _depth, counts)
    return value, counts


def _apply_pii(value: Any, policy: RedactionPolicy, _depth: int,
               counts: dict[str, int] | None = None) -> Any:
    """Rekursi PII. `counts` diakumulasi lintas cabang (bukan per-cabang)."""
    if _depth > MAX_DEPTH:
        return PII_PLACEHOLDERS["depth"]

    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if _looks_binary(k, v):
                out[k] = "[REDACTED_BINARY]"
                continue
            out[k] = _apply_pii(v, policy, _depth + 1, counts)
        return out

    if isinstance(value, (list, tuple)):
        return [_apply_pii(v, policy, _depth + 1, counts) for v in value]

    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[REDACTED_BINARY]"

    if isinstance(value, str):
        text, sub = redact_text(value, policy)
        if counts is not None:
            for k, n in sub.items():
                counts[k] = counts.get(k, 0) + n
        return text

    return value


def redact_payload(value: Any, policy: RedactionPolicy, *,
                   trigger: str = "production") -> Any:
    """API utama: nilai siap-persist. Tanpa statistik."""
    return apply_policy(value, policy, trigger=trigger)[0]


# ---------------------------------------------------------------------------
# Titik integrasi + komparasi kebijakan
# ---------------------------------------------------------------------------
def compare(have: str, want: str) -> bool:
    """True bila `have` (kebijakan ada) menutup `want` (yang diminta)."""
    a = str(have or "off").strip().lower()
    b = str(want or "off").strip().lower()
    if a not in _LEVEL_RANK or b not in _LEVEL_RANK:
        raise RedactionPolicyError(f"level tidak dikenal: {have!r} / {want!r}")
    return _LEVEL_RANK[a] >= _LEVEL_RANK[b]


def describe(policy: RedactionPolicy) -> str:
    """Ringkasan satu baris untuk log/UI."""
    if not policy.active:
        return "redaction off"
    scope = "production" if policy.level == "production" else "manual+production"
    return (f"redact {scope} | pii={','.join(policy.pii_types) or '-'} | "
            f"custom={len(policy.custom_patterns)}")


def reset_stats() -> None:
    """Kosongkan statistik kredensial (dipakai antar-test)."""
    _reset_cred_stats()


__all__ = [
    "REDACTION_LEVELS",
    "REDACTABLE_PII",
    "PII_PLACEHOLDERS",
    "MAX_PATTERN_LEN",
    "REGEX_TIME_BUDGET_SEC",
    "RedactionPolicy",
    "RedactionPolicyError",
    "compile_custom_pattern",
    "redact_text",
    "apply_policy",
    "redact_payload",
    "compare",
    "describe",
    "reset_stats",
    "RedactionError",
]
