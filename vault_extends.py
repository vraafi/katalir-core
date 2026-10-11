"""vault_extends.py — pewarisan kredensial (``extends://``) untuk vault broker.

MASALAH YANG DISELESAIKAN
-------------------------
Banyak integrasi berbagi kredensial dasar tetapi butuh sedikit penyesuaian
(mis. satu akun SMTP dipakai 5 workflow, tiap workflow punya mailbox sendiri).
Menyalin nilai rahasia ke tiap entri = rotasi mimpi buruk dan memperbanyak
permukaan kebocoran. Pola ``extendsCredential`` (rujuk vault chaining 2026)
memungkinkan entri ANAK mewarisi entri INDUK dan hanya menimpa field tertentu.

BENTUK REFERENSI
----------------
    secret://<provider>/<field>      -> nilai satu field (kompatibel lama)
    secret://<provider>#<field>      -> alias (brief menulis bentuk ini)
    extends://<provider>             -> dict gabungan (induk + anak)
    extends://<provider>#<field>     -> satu field dari dict gabungan

Entri anak menyatakan induknya lewat kunci ``__extends__`` di dalam dict
kredensial (nilainya ``extends://parent``, ``secret://parent/...``, atau nama
provider polos). Aturan: **anak menang** atas induk untuk field yang sama.

KEAMANAN
--------
* **Deteksi siklus** — rantai A->B->A ditolak (``CircularCredentialError``).
* **Batas kedalaman** 5 — mencegah rantai tak terbatas / DoS.
* **Isolasi multi-tenant** — loader SELALU dipanggil dengan ``user_email``;
  kredensial tenant lain tidak pernah terlihat.
* **Audit** — ``audit`` opsional menerima jejak langkah resolusi (tanpa nilai
  rahasia) untuk log kepatuhan.
* Nilai diambil dari ``load_vault_credential`` yang mendekripsi di dalam proses
  (rahasia tidak pernah masuk prompt/LLM).
"""

from __future__ import annotations

from typing import Any, Callable

#: Kedalaman maksimum rantai pewarisan.
MAX_DEPTH = 5

#: Kunci penanda induk di dalam dict kredensial.
EXTENDS_KEY = "__extends__"

#: Nama field yang tidak pernah dianggap rahasia / diteruskan.
_META_KEYS = frozenset({EXTENDS_KEY})


class CredentialResolveError(ValueError):
    """Gagal me-resolve referensi kredensial."""


class CircularCredentialError(CredentialResolveError):
    """Rantai pewarisan membentuk siklus."""


class DepthExceededError(CredentialResolveError):
    """Rantai pewarisan melebihi ``MAX_DEPTH``."""


class MissingParentError(CredentialResolveError):
    """Induk yang dirujuk ``__extends__`` tidak ada di vault."""


class RefParseError(CredentialResolveError):
    """Bentuk referensi tidak dikenal."""


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def is_extends_ref(value: Any) -> bool:
    return isinstance(value, str) and value.lower().startswith("extends://")


def is_secret_ref(value: Any) -> bool:
    return isinstance(value, str) and value.lower().startswith("secret://")


def _split_field(rest: str) -> tuple[str, str | None]:
    """Pecah ``provider/field`` atau ``provider#field`` -> (provider, field)."""
    for sep in ("/", "#"):
        if sep in rest:
            provider, field = rest.split(sep, 1)
            return provider.strip().lower(), field.strip()
    return rest.strip().lower(), None


def parse_ref(ref: str) -> tuple[str, str, str | None]:
    """Kembalikan ``(scheme, provider, field|None)``.

    scheme = ``"secret"`` atau ``"extends"``.
    """
    if not isinstance(ref, str):
        raise RefParseError(f"referensi bukan string: {ref!r}")
    low = ref.strip().lower()
    if low.startswith("secret://"):
        provider, field = _split_field(ref.strip()[len("secret://"):])
        if not provider:
            raise RefParseError(f"provider kosong: {ref!r}")
        return "secret", provider, field
    if low.startswith("extends://"):
        provider, field = _split_field(ref.strip()[len("extends://"):])
        if not provider:
            raise RefParseError(f"provider kosong: {ref!r}")
        return "extends", provider, field
    raise RefParseError(f"skema referensi tidak dikenal: {ref[:40]!r}")


# --------------------------------------------------------------------------
# Loader default (impor lokal -> hindari siklus)
# --------------------------------------------------------------------------
def _default_loader(user_email: str, provider: str) -> dict | None:
    from credential_forms import load_vault_credential
    return load_vault_credential(user_email, provider)


def _normalise_parent(value: Any) -> str | None:
    """Ambil nama provider induk dari nilai ``__extends__``."""
    if value is None:
        return None
    if is_extends_ref(value):
        return parse_ref(value)[1]
    if is_secret_ref(value):
        return parse_ref(value)[1]
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


# --------------------------------------------------------------------------
# Resolusi
# --------------------------------------------------------------------------
def resolve_extends(
    provider: str,
    user_email: str,
    *,
    loader: Callable[[str, str], dict | None] | None = None,
    max_depth: int = MAX_DEPTH,
    audit: list[dict] | None = None,
    _seen: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Kembalikan dict kredensial GABUNGAN untuk ``provider`` (induk + anak).

    Raises:
        CircularCredentialError, DepthExceededError, MissingParentError.
    """
    loader = loader or _default_loader
    prov = str(provider).strip().lower()

    if prov in _seen:
        chain = " -> ".join((*_seen, prov))
        raise CircularCredentialError(f"siklus pewarisan kredensial: {chain}")
    if len(_seen) >= max_depth:
        chain = " -> ".join((*_seen, prov))
        raise DepthExceededError(
            f"rantai pewarisan melebihi kedalaman {max_depth}: {chain}"
        )

    raw = loader(user_email, prov)
    if not isinstance(raw, dict):
        # Tidak ada entri untuk provider ini.
        if _seen:
            raise MissingParentError(
                f"induk '{prov}' tidak ada di vault (dirujuk oleh '{_seen[-1]}')"
            )
        raise CredentialResolveError(f"kredensial '{prov}' tidak ada di vault")

    parent_name = _normalise_parent(raw.get(EXTENDS_KEY))
    merged: dict[str, Any] = {}
    if parent_name:
        merged.update(resolve_extends(
            parent_name, user_email, loader=loader, max_depth=max_depth,
            audit=audit, _seen=(*_seen, prov),
        ))

    # Anak menang atas induk.
    for k, v in raw.items():
        if k in _META_KEYS:
            continue
        merged[k] = v

    if audit is not None:
        audit.append({
            "provider": prov,
            "parent": parent_name,
            "fields": sorted(k for k in raw.keys() if k not in _META_KEYS),
            "depth": len(_seen),
        })
    return merged


def resolve_ref(
    ref: str,
    user_email: str,
    *,
    loader: Callable[[str, str], dict | None] | None = None,
    max_depth: int = MAX_DEPTH,
    audit: list[dict] | None = None,
) -> str:
    """Resolve ``secret://`` atau ``extends://`` menjadi nilai string."""
    scheme, provider, field = parse_ref(ref)
    if scheme == "extends":
        merged = resolve_extends(
            provider, user_email, loader=loader, max_depth=max_depth, audit=audit,
        )
        if field is None:
            # Tanpa field: pilih field pertama yang deterministik.
            if not merged:
                raise CredentialResolveError(f"kredensial '{provider}' kosong")
            field = sorted(merged.keys())[0]
        if field not in merged:
            raise CredentialResolveError(
                f"field '{field}' tidak ada pada kredensial gabungan '{provider}'"
            )
        return str(merged[field])

    # scheme == "secret"
    if field is None:
        raise RefParseError(f"referensi secret:// tanpa field: {ref[:40]!r}")
    from vault_broker import resolve_secret  # impor lokal -> hindari siklus
    return resolve_secret(f"secret://{provider}/{field}", user_email)


__all__ = [
    "EXTENDS_KEY",
    "MAX_DEPTH",
    "CircularCredentialError",
    "CredentialResolveError",
    "DepthExceededError",
    "MissingParentError",
    "RefParseError",
    "is_extends_ref",
    "is_secret_ref",
    "parse_ref",
    "resolve_extends",
    "resolve_ref",
]
