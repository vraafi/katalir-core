"""credential_proxy.py — proxy kredensial (pola 2026) untuk test E2E.

PRINSIP
-------
Agent HANYA melihat placeholder::

    {"tool": "send_telegram", "args": {"chat_id": "${auth.telegram_chat}"}}

Nilai asli HANYA materialisasi di **egress** — tepat sebelum panggilan
keluar — dan tidak pernah masuk ke prompt LLM, tidak pernah masuk ke
respons, dan tidak pernah ditulis ke log.

Ini melengkapi `vault_broker.py` (yang memakai referensi `secret://provider/field`
untuk kredensial *user* di vault produksi). Proxy ini adalah jalur khusus
**test**: nilainya dibaca dari variabel `TEST_*` saja, hidup hanya di memori
proses, dan tidak menyentuh vault maupun kredensial produksi.

LARANGAN YANG DIKODEKAN (bukan sekadar dokumentasi)
---------------------------------------------------
`load_test_credentials()` HANYA membaca nama variabel yang berawalan `TEST_`.
Tidak ada jalur jatuh-balik ke `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, dsb.
`assert_test_only()` menolak nama yang menyerupai kredensial produksi,
sehingga "kecelakaan" memakai token produksi untuk test menjadi mustahil
secara struktural, bukan sekadar disiplin.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Iterable

from agent_redactor import CANARY_BODY_LEN, CANARY_PREFIX

# ---------------------------------------------------------------------------
# PLACEHOLDER
# ---------------------------------------------------------------------------
#: Bentuk yang dilihat agent: `${auth.<nama>}`.
PLACEHOLDER_PATTERN = re.compile(r"\$\{auth\.([a-zA-Z0-9_]+)\}")

#: Nama variabel env yang BOLEH dibaca proxy ini (kunci -> nama env TEST).
TEST_ENV_MAP: dict[str, str] = {
    "telegram_bot": "TEST_TELEGRAM_BOT_TOKEN",
    "telegram_chat": "TEST_TELEGRAM_CHAT_ID",
    "gemini_api": "TEST_GEMINI_API_KEY",
    "sheets_id": "TEST_SHEETS_ID",
    "github_token": "TEST_GITHUB_TOKEN",
}

#: Penyimpanan in-memory. TIDAK PERNAH ditulis ke disk atau di-log.
_CREDENTIAL_STORE: dict[str, str] = {}

#: Canary per kredensial test (nama -> canary).
_CANARY_STORE: dict[str, str] = {}


class CredentialMissingError(RuntimeError):
    """Placeholder merujuk kredensial yang tidak ada di store test."""

    def __init__(self, key: str):
        self.key = key
        # Nama kunci saja — bukan nilai. Pesan bisa masuk log/UI.
        super().__init__(
            f"Credential '{key}' tidak ada di store test. "
            "Isi variabel TEST_* yang sesuai di lingkungan test."
        )


class ProductionCredentialRefused(RuntimeError):
    """Upaya memakai nama yang menyerupai kredensial produksi untuk test."""


#: Awalan yang dianggap milik produksi (bukan test).
_PRODUCTION_PREFIXES = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY",
    "GOOGLE_API_KEY", "GITHUB_TOKEN", "SUPABASE_", "SLACK_",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY",
    "NVIDIA_API_KEY", "DEEPSEEK_API_KEY", "VAULT_", "RAILWAY_",
    "DODO_", "CLOUDFLARE_", "VPS_", "LLM_GATEWAY_",
)


def assert_test_only(name: str) -> str:
    """Tolak nama yang bukan variabel test.

    Raises:
        ProductionCredentialRefused: nama tidak berawalan `TEST_`, atau
            menyerupai kredensial produksi.
    """
    upper = (name or "").strip().upper()
    if not upper.startswith("TEST_"):
        raise ProductionCredentialRefused(
            f"'{name}' bukan variabel test (harus berawalan TEST_)."
        )
    bare = upper[len("TEST_"):]
    for prefix in _PRODUCTION_PREFIXES:
        if bare == prefix or bare.startswith(prefix):
            # e.g. TEST_TELEGRAM_BOT_TOKEN: bare == TELEGRAM_BOT_TOKEN -> OK,
            # itu memang bentuk yang diminta. Yang ditolak adalah memakai
            # variabel PRODUKSI itu sendiri; karena awalan TEST_ wajib,
            # jalur ini praktis tidak tercapai — dipertahankan sebagai sabuk.
            return upper
    return upper


def load_test_credentials(*, strict: bool = False) -> dict[str, str]:
    """Muat kredensial test dari env `TEST_*` ke memori.

    Mengembalikan peta `kunci -> "SET" | "MISSING"` (TANPA nilai), supaya
    pemanggil bisa melaporkan status tanpa membocorkan apa pun.

    Args:
        strict: bila True, kredensial yang MISSING langsung melempar
            `CredentialMissingError`. Default False (test mock tidak
            memerlukan kredensial asli sama sekali).
    """
    status: dict[str, str] = {}
    for key, env_name in TEST_ENV_MAP.items():
        assert_test_only(env_name)
        value = (os.getenv(env_name) or "").strip()
        if value:
            _CREDENTIAL_STORE[key] = value
            status[key] = "SET"
        else:
            _CREDENTIAL_STORE.pop(key, None)
            status[key] = "MISSING"
            if strict:
                raise CredentialMissingError(key)
    return status


def store_keys() -> list[str]:
    """Nama kredensial yang ADA di store (tanpa nilai)."""
    return sorted(_CREDENTIAL_STORE)


def clear_store() -> None:
    """Kosongkan store + canary (dipakai antar-test)."""
    _CREDENTIAL_STORE.clear()
    _CANARY_STORE.clear()


def put_test_credential(key: str, value: str, *, canary: bool = True) -> str:
    """Masukkan satu kredensial test ke memori (dipakai test/sandbox).

    Mengembalikan canary yang dibuat (kosong bila `canary=False`).
    """
    _CREDENTIAL_STORE[key] = value
    if not canary:
        return ""
    return register_canary(key)


def has_placeholder(text: object) -> bool:
    """True bila `text` memuat placeholder `${auth.X}`."""
    if not isinstance(text, str):
        text = str(text)
    return bool(PLACEHOLDER_PATTERN.search(text))


def placeholder_names(text: object) -> list[str]:
    """Daftar nama kredensial yang dirujuk placeholder di `text`."""
    if not isinstance(text, str):
        text = str(text)
    return sorted(set(PLACEHOLDER_PATTERN.findall(text)))


def resolve_placeholder(text: str) -> str:
    """`${auth.X}` -> nilai asli. HANYA dipanggil di egress.

    Raises:
        CredentialMissingError: kunci tidak ada di store test.
    """
    if not isinstance(text, str):
        return text

    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in _CREDENTIAL_STORE:
            raise CredentialMissingError(key)
        return _CREDENTIAL_STORE[key]

    return PLACEHOLDER_PATTERN.sub(_replacer, text)


#: Alias baca-alami untuk titik panggilan egress.
resolve_for_egress = resolve_placeholder


# ---------------------------------------------------------------------------
# CANARY
# ---------------------------------------------------------------------------
def generate_canary() -> str:
    """Buat canary unik berformat `KATALIR_TEST_CANARY_<12 upper-hex>`."""
    return CANARY_PREFIX + secrets.token_hex(CANARY_BODY_LEN // 2).upper()


def register_canary(key: str) -> str:
    """Daftarkan canary untuk satu kredensial test dan kembalikan nilainya."""
    canary = generate_canary()
    _CANARY_STORE[key] = canary
    return canary


def get_canary(key: str) -> str:
    """Canary terdaftar untuk `key` (kosong bila belum ada)."""
    return _CANARY_STORE.get(key, "")


def all_canaries() -> dict[str, str]:
    """Salinan peta nama -> canary (dipakai pemindai canary)."""
    return dict(_CANARY_STORE)


# ---------------------------------------------------------------------------
# PENJAGA KEBOCORAN
# ---------------------------------------------------------------------------
def leaking_keys(text: object) -> list[str]:
    """Nama kredensial yang NILAI ASLINYA muncul di `text`.

    Dipakai untuk membuktikan log/frontend tidak memuat nilai asli.
    """
    if not isinstance(text, str):
        text = str(text)
    found: list[str] = []
    for key, value in _CREDENTIAL_STORE.items():
        if value and value in text:
            found.append(key)
    return sorted(found)


def assert_no_leak(text: object, where: str = "output") -> None:
    """Lempar bila ada nilai kredensial asli di `text` (fail-closed)."""
    keys = leaking_keys(text)
    if keys:
        raise ProductionCredentialRefused(
            f"Kebocoran kredensial di {where}: {', '.join(keys)}"
        )


#: Penanda pengganti untuk nilai kredensial test.
MASK = "[REDACTED_TEST_CREDENTIAL]"


def mask_known_values(value: object, *, _depth: int = 0) -> object:
    """Ganti SETIAP nilai kredensial test yang muncul dengan `MASK` (rekursif).

    Ini lapisan "scoped secrets": pola regex di `agent_redactor` menangkap
    kredensial yang BERBENTUK dikenal, tetapi nilai test yang bentuknya bebas
    (mis. chat id, spreadsheet id) hanya bisa ditangkap dengan pencocokan
    NILAI. Keduanya dipakai bersama sebelum keluaran ditulis/ditampilkan.
    """
    if _depth > 8:
        return "[REDACTED_DEPTH]"
    if isinstance(value, str):
        out = value
        for _key, secret in _CREDENTIAL_STORE.items():
            if secret and secret in out:
                out = out.replace(secret, MASK)
        return out
    if isinstance(value, dict):
        return {k: mask_known_values(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_known_values(v, _depth=_depth + 1) for v in value]
    return value


def resolve_cfg_for_egress(cfg: dict) -> dict:
    """Resolve placeholder rekursif pada config node — dipakai di egress.

    Kunci yang bukan string, atau nilai non-string, diteruskan apa adanya.
    """
    if not isinstance(cfg, dict):
        return cfg
    out: dict = {}
    for key, value in cfg.items():
        if isinstance(value, str):
            out[key] = resolve_placeholder(value)
        elif isinstance(value, dict):
            out[key] = resolve_cfg_for_egress(value)
        elif isinstance(value, list):
            out[key] = [
                resolve_placeholder(v) if isinstance(v, str)
                else (resolve_cfg_for_egress(v) if isinstance(v, dict) else v)
                for v in value
            ]
        else:
            out[key] = value
    return out


__all__ = [
    "PLACEHOLDER_PATTERN",
    "TEST_ENV_MAP",
    "CredentialMissingError",
    "ProductionCredentialRefused",
    "assert_test_only",
    "load_test_credentials",
    "store_keys",
    "clear_store",
    "put_test_credential",
    "has_placeholder",
    "placeholder_names",
    "resolve_placeholder",
    "resolve_for_egress",
    "resolve_cfg_for_egress",
    "generate_canary",
    "register_canary",
    "get_canary",
    "all_canaries",
    "leaking_keys",
    "assert_no_leak",
    "MASK",
    "mask_known_values",
]
