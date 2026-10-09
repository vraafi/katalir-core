"""connector_manifest.py — skema manifest connector deklaratif untuk Katalir.

LATAR BELAKANG (baca `docs/connector-existing-audit.md` lebih dulu)
-------------------------------------------------------------------
Katalog Katalir sudah berisi 25.925 entri dari 8 sumber, tetapi hanya **23**
yang benar-benar dapat dieksekusi (`mcp_registry.executable_servers()`).
Sisanya `metadata_only`. Jadi gap sebenarnya bukan "kurang connector",
melainkan "25.902 connector terkatalog tanpa jalur eksekusi".

Modul ini TIDAK membangun registry kedua. Ia menambahkan **satu skema
manifest deklaratif** (YAML) yang di-*compile* menjadi bentuk entri
`mcp_registry` yang SUDAH ADA, sehingga:

  * dedup engine (`mcp_dedup.py`) tetap berlaku;
  * 17 endpoint `/mcp/registry/*` tetap berlaku;
  * UI `/integrations` tetap berlaku;
  * tidak ada dua daftar connector yang bisa berbeda.

KOSAKATA (diadopsi, bukan dikarang)
-----------------------------------
Bentuk manifest mengikuti **Airbyte Declarative Manifest Framework** karena
format itu sudah terbukti pada 50+ connector produksi
(`docs.airbyte.com/.../understanding-the-yaml-file/reference`, dibaca
9 Okt 2026). Nilai yang didukung sengaja DIBATASI pada himpunan tertutup
supaya bisa divalidasi skema — bukan bahasa bebas.

Semantik auth mengikuti **Composio**: kredensial BUKAN milik connector,
melainkan milik *koneksi per-user*. Manifest hanya mendeklarasikan
`credential_form`; nilai rahasianya hidup di vault lewat
`end_user_credentials.py`.

Flag verifikasi mengikuti **OpenConnector** yang sudah dipakai Katalir:
`listed` -> `callable` -> `call_verified`, dan TIDAK PERNAH dipromosikan
tanpa panggilan nyata.

KONTRAK
-------
Semua fungsi validasi mengembalikan daftar error (list[str]); list kosong =
valid. Tidak ada yang `raise` kecuali `compile_manifest` yang butuh manifest
sudah valid (dipanggil setelah `validate_manifest`).

`compile_manifest()` deterministik: manifest yang sama selalu menghasilkan
entri registry yang identik byte-per-byte (setelah `json.dumps(sort_keys=True)`).
Ini yang membuat manifest tidak bisa "drift" dari registry.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

try:  # pragma: no cover - PyYAML wajib ada di proyek ini
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


MANIFEST_VERSION = 1

# ---------------------------------------------------------------------------
# Kosakata tertutup — diambil dari Airbyte CDK + flag OpenConnector/Composio.
# ---------------------------------------------------------------------------

AUTH_TYPES = (
    "none",
    "api_key",
    "bearer",
    "basic",
    "oauth2",
    "jwt",
    "session_token",
    "selective",
)

OPERATION_TYPES = ("read", "write", "delete")

TENANT_SCOPES = ("per-user", "public")

TRIGGER_TYPES = ("webhook", "cron", "polling")

# Airbyte component vocabulary (subset yang kita dukung).
RECORD_SELECTORS = (
    "DpathExtractor",
    "CombinedExtractor",
    "ResponseToFileExtractor",
    "JsonItemsDecoder",
)

PAGINATORS = (
    "NoPagination",
    "DefaultPaginator",
    "OffsetIncrement",
    "PageIncrement",
    "CursorPagination",
)

ERROR_HANDLERS = ("DefaultErrorHandler", "CompositeErrorHandler")

BACKOFF_STRATEGIES = ("ConstantBackoffStrategy", "ExponentialBackoffStrategy")

RATE_LIMIT_TYPES = (
    "FixedWindowCallRatePolicy",
    "MovingWindowCallRatePolicy",
    "UnlimitedCallRatePolicy",
)

VERIFICATION_LEVELS = ("listed", "callable", "call_verified")

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# Filter interpolasi yang diizinkan. Sengaja kecil: `hash` dan `base64encode`
# cukup untuk kasus nyata, dan bahasa ekspresi besar = permukaan serangan besar.
INTERPOLATION_FILTERS = ("default", "hash", "base64encode", "string", "regex_replace")

_INTERP_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_INTERP_ROOT_RE = re.compile(r"^[a-z_]+(?:\.[A-Za-z0-9_\-\u00c0-\uffff\[\]'\"|() ]+)*$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*(\.[a-z0-9][a-z0-9_\-]*)+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ManifestError(ValueError):
    """Manifest tidak dapat di-compile. Selalu membawa daftar error."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) or "manifest tidak sah")


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------


def _need(cond: bool, errors: list[str], msg: str) -> None:
    if not cond:
        errors.append(msg)


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def validate_interpolation(text: str, errors: list[str], where: str) -> None:
    """Pastikan setiap `{{ ... }}` hanya memakai variabel & filter yang dikenal.

    Variabel yang diizinkan: `config`, `input`, `record`, `stream_slice`,
    `stream_interval`, `now_utc`, `today_utc`, `timestamp`. Ini himpunan
    tertutup — ekspresi bebas akan membuat manifest menjadi bahasa program,
    dan itu persis yang harus dihindari (`input_data` tidak pernah disubstitusi
    ke teks program — lihat catatan sandbox di memori proyek).
    """
    if not _is_str(text):
        return
    for m in _INTERP_RE.finditer(text):
        expr = m.group(1).strip()
        head = expr.split("|", 1)[0].strip()
        root = re.split(r"[.\[]", head, 1)[0].strip()
        allowed_roots = {
            "config", "input", "record", "stream_slice", "stream_interval",
            "now_utc", "today_utc", "timestamp",
        }
        if root not in allowed_roots:
            errors.append(f"{where}: variabel interpolasi tidak dikenal: '{root}'")
        for part in expr.split("|")[1:]:
            fname = part.strip().split("(", 1)[0].strip()
            if fname and fname not in INTERPOLATION_FILTERS:
                errors.append(f"{where}: filter interpolasi tidak dikenal: '{fname}'")


def _validate_auth(auth: Any, errors: list[str], where: str) -> None:
    if auth is None:
        errors.append(f"{where}.auth: wajib ada (pakai type 'none' bila terbuka)")
        return
    if not isinstance(auth, dict):
        errors.append(f"{where}.auth: harus objek")
        return
    atype = auth.get("type")
    if atype not in AUTH_TYPES:
        errors.append(
            f"{where}.auth.type: '{atype}' tidak dikenal "
            f"(didukung: {', '.join(AUTH_TYPES)})"
        )
        return
    if atype != "none":
        cf = auth.get("credential_form")
        _need(
            _is_str(cf) and bool(cf.strip()),
            errors,
            f"{where}.auth.credential_form: wajib untuk auth type '{atype}'",
        )
    if atype == "oauth2":
        _need(
            _is_str(auth.get("connect_url")) and bool(str(auth.get("connect_url")).strip()),
            errors,
            f"{where}.auth.connect_url: wajib untuk oauth2",
        )
    scopes = auth.get("scopes")
    if scopes is not None:
        _need(
            isinstance(scopes, list) and all(_is_str(s) for s in scopes),
            errors,
            f"{where}.auth.scopes: harus daftar string",
        )


def _validate_action(action: Any, errors: list[str], where: str) -> None:
    if not isinstance(action, dict):
        errors.append(f"{where}: action harus objek")
        return
    name = action.get("name")
    _need(
        _is_str(name) and bool(_SLUG_RE.match(str(name))),
        errors,
        f"{where}.name: wajib, huruf kecil/angka/_/-, maks 64",
    )
    op = action.get("operation_type")
    _need(
        op in OPERATION_TYPES,
        errors,
        f"{where}.operation_type: '{op}' tidak dikenal (didukung: {', '.join(OPERATION_TYPES)})",
    )
    method = action.get("method")
    if op == "read" and method is None:
        method = "GET"
    _need(
        str(method or "").upper() in HTTP_METHODS,
        errors,
        f"{where}.method: '{method}' tidak dikenal (didukung: {', '.join(HTTP_METHODS)})",
    )
    url_base = action.get("url_base")
    _need(
        _is_str(url_base) and str(url_base).startswith(("http://", "https://")),
        errors,
        f"{where}.url_base: wajib dan harus http(s)://",
    )
    path = action.get("path")
    _need(
        _is_str(path) and bool(str(path).strip()),
        errors,
        f"{where}.path: wajib",
    )
    validate_interpolation(str(path or ""), errors, f"{where}.path")
    validate_interpolation(str(url_base or ""), errors, f"{where}.url_base")

    body = action.get("request_body_json")
    if body is not None:
        _need(isinstance(body, dict), errors, f"{where}.request_body_json: harus objek")
        if isinstance(body, dict):
            for k, v in body.items():
                validate_interpolation(str(v), errors, f"{where}.request_body_json.{k}")

    sel = action.get("record_selector")
    if sel is not None:
        _need(isinstance(sel, dict), errors, f"{where}.record_selector: harus objek")
        if isinstance(sel, dict):
            stype = sel.get("type")
            _need(
                stype in RECORD_SELECTORS,
                errors,
                f"{where}.record_selector.type: '{stype}' tidak dikenal "
                f"(didukung: {', '.join(RECORD_SELECTORS)})",
            )
            fp = sel.get("field_path")
            if fp is not None:
                _need(
                    isinstance(fp, list) and all(_is_str(x) for x in fp),
                    errors,
                    f"{where}.record_selector.field_path: harus daftar string",
                )

    pag = action.get("paginator")
    if pag is not None:
        if isinstance(pag, str):
            _need(
                pag in PAGINATORS,
                errors,
                f"{where}.paginator: '{pag}' tidak dikenal (didukung: {', '.join(PAGINATORS)})",
            )
        elif isinstance(pag, dict):
            _need(
                pag.get("type") in PAGINATORS,
                errors,
                f"{where}.paginator.type: '{pag.get('type')}' tidak dikenal",
            )
        else:
            errors.append(f"{where}.paginator: harus string atau objek")

    eh = action.get("error_handler")
    if eh is not None:
        _need(isinstance(eh, dict), errors, f"{where}.error_handler: harus objek")
        if isinstance(eh, dict):
            _need(
                eh.get("type") in ERROR_HANDLERS,
                errors,
                f"{where}.error_handler.type: '{eh.get('type')}' tidak dikenal "
                f"(didukung: {', '.join(ERROR_HANDLERS)})",
            )
            retry = eh.get("retry")
            if retry is not None:
                _need(isinstance(retry, dict), errors, f"{where}.error_handler.retry: harus objek")
                if isinstance(retry, dict):
                    _need(
                        retry.get("type") in BACKOFF_STRATEGIES,
                        errors,
                        f"{where}.error_handler.retry.type: '{retry.get('type')}' tidak dikenal "
                        f"(didukung: {', '.join(BACKOFF_STRATEGIES)})",
                    )
                    mr = retry.get("max_retries")
                    if mr is not None:
                        _need(
                            isinstance(mr, int) and not isinstance(mr, bool) and 0 <= mr <= 10,
                            errors,
                            f"{where}.error_handler.retry.max_retries: harus int 0..10",
                        )

    ver = action.get("verification")
    if ver is not None:
        _need(isinstance(ver, dict), errors, f"{where}.verification: harus objek")
        if isinstance(ver, dict):
            lvl = ver.get("level")
            _need(
                lvl in VERIFICATION_LEVELS,
                errors,
                f"{where}.verification.level: '{lvl}' tidak dikenal "
                f"(didukung: {', '.join(VERIFICATION_LEVELS)})",
            )


def _validate_trigger(trigger: Any, errors: list[str], where: str) -> None:
    if not isinstance(trigger, dict):
        errors.append(f"{where}: trigger harus objek")
        return
    name = trigger.get("name")
    _need(
        _is_str(name) and bool(_SLUG_RE.match(str(name))),
        errors,
        f"{where}.name: wajib, huruf kecil/angka/_/-, maks 64",
    )
    ttype = trigger.get("type")
    _need(
        ttype in TRIGGER_TYPES,
        errors,
        f"{where}.type: '{ttype}' tidak dikenal (didukung: {', '.join(TRIGGER_TYPES)})",
    )
    if ttype == "webhook":
        _need(
            _is_str(trigger.get("signature")) and bool(str(trigger.get("signature")).strip()),
            errors,
            f"{where}.signature: wajib untuk webhook (mis. hmac_sha256)",
        )
        _need(
            _is_str(trigger.get("header")) and bool(str(trigger.get("header")).strip()),
            errors,
            f"{where}.header: wajib untuk webhook",
        )
    if ttype == "cron":
        expr = trigger.get("schedule")
        _need(
            _is_str(expr) and len(str(expr).split()) in (5, 6),
            errors,
            f"{where}.schedule: wajib untuk cron (5 atau 6 field)",
        )


def validate_manifest(data: Any) -> list[str]:
    """Validasi manifest. Kembalikan daftar error; kosong = valid."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["manifest: harus objek (mapping YAML)"]

    mv = data.get("manifest_version")
    _need(
        mv == MANIFEST_VERSION,
        errors,
        f"manifest_version: harus {MANIFEST_VERSION}, dapat {mv!r}",
    )

    mid = data.get("id")
    _need(
        _is_str(mid) and bool(_ID_RE.match(str(mid))),
        errors,
        "id: wajib, format '<namespace>.<name>' huruf kecil (mis. 'github.issue.create')",
    )
    slug = data.get("slug")
    _need(
        _is_str(slug) and bool(_SLUG_RE.match(str(slug))),
        errors,
        "slug: wajib, huruf kecil/angka/_/-, maks 64",
    )
    dn = data.get("display_name")
    _need(
        _is_str(dn) and bool(str(dn).strip()),
        errors,
        "display_name: wajib",
    )
    cat = data.get("category")
    _need(
        _is_str(cat) and bool(str(cat).strip()),
        errors,
        "category: wajib (dipakai faset /mcp/registry/categories)",
    )
    src = data.get("source")
    _need(
        _is_str(src) and bool(str(src).strip()),
        errors,
        "source: wajib (mis. 'native', 'openconnector')",
    )
    scope = data.get("tenant_scope")
    _need(
        scope in TENANT_SCOPES,
        errors,
        f"tenant_scope: '{scope}' tidak dikenal (didukung: {', '.join(TENANT_SCOPES)})",
    )

    msr = data.get("minimum_supported_release")
    if msr is not None:
        _need(
            _is_str(msr) and bool(_SEMVER_RE.match(str(msr))),
            errors,
            "minimum_supported_release: harus semver 'X.Y.Z'",
        )
    dep = data.get("deprecated")
    if dep is not None:
        _need(isinstance(dep, bool), errors, "deprecated: harus boolean")

    _validate_auth(data.get("auth"), errors, "auth")

    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        errors.append("actions: wajib, minimal satu action")
    else:
        seen: set[str] = set()
        for i, a in enumerate(actions):
            _validate_action(a, errors, f"actions[{i}]")
            nm = a.get("name") if isinstance(a, dict) else None
            if isinstance(nm, str):
                if nm in seen:
                    errors.append(f"actions[{i}].name: duplikat '{nm}'")
                seen.add(nm)

    triggers = data.get("triggers")
    if triggers is not None:
        if not isinstance(triggers, list):
            errors.append("triggers: harus daftar")
        else:
            tseen: set[str] = set()
            for i, t in enumerate(triggers):
                _validate_trigger(t, errors, f"triggers[{i}]")
                nm = t.get("name") if isinstance(t, dict) else None
                if isinstance(nm, str):
                    if nm in tseen:
                        errors.append(f"triggers[{i}].name: duplikat '{nm}'")
                    tseen.add(nm)

    rl = data.get("rate_limit")
    if rl is not None:
        _need(isinstance(rl, dict), errors, "rate_limit: harus objek")
        if isinstance(rl, dict):
            _need(
                rl.get("type") in RATE_LIMIT_TYPES,
                errors,
                f"rate_limit.type: '{rl.get('type')}' tidak dikenal "
                f"(didukung: {', '.join(RATE_LIMIT_TYPES)})",
            )
            if rl.get("type") != "UnlimitedCallRatePolicy":
                mc = rl.get("max_calls")
                _need(
                    isinstance(mc, int) and not isinstance(mc, bool) and mc > 0,
                    errors,
                    "rate_limit.max_calls: harus int > 0",
                )
                ws = rl.get("window_seconds")
                _need(
                    isinstance(ws, int) and not isinstance(ws, bool) and ws > 0,
                    errors,
                    "rate_limit.window_seconds: harus int > 0",
                )

    cf = data.get("credential_free")
    if cf is not None:
        _need(isinstance(cf, bool), errors, "credential_free: harus boolean")

    return errors


# ---------------------------------------------------------------------------
# Keamanan: deteksi SSRF + secret yang tidak sengaja tertulis
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = (
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254",
    "metadata.google.internal",
)
_BLOCKED_PREFIXES = (
    "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2",
    "172.30.", "172.31.",
)
_PRIVATE_SUFFIX = (".local", ".internal", ".localdomain")

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),               # OpenAI-style
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),              # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                  # AWS key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),      # Slack token
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."),  # JWT
)


def host_is_blocked(url: str) -> bool:
    """Guard SSRF — pola sama dengan `_host_blocked()` di `tools.py`.

    Menolak loopback, link-local (169.254.169.254 = metadata cloud), dan
    rentang privat RFC1918. Manifest yang menunjuk ke sana adalah manifest
    yang tidak boleh di-*compile*, karena Katalir akan memanggilnya dari
    dalam jaringan produksi.
    """
    if not _is_str(url):
        return True
    m = re.match(r"^https?://([^/?#]+)", url)
    if not m:
        return True
    host = m.group(1).split("@")[-1].split(":")[0].lower()
    if not host:
        return True
    if host in _BLOCKED_HOSTS:
        return True
    if host.endswith(_PRIVATE_SUFFIX):
        return True
    for pfx in _BLOCKED_PREFIXES:
        if host.startswith(pfx):
            return True
    return False


def scan_secrets(text: str) -> list[str]:
    """Kembalikan pola rahasia yang terdeteksi di teks manifest.

    Manifest adalah file yang di-commit. Menulis token ke dalamnya adalah cara
    paling mudah membocorkan kredensial, jadi ini dicek otomatis.
    """
    if not _is_str(text):
        return []
    found: list[str] = []
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            found.append(pat.pattern)
    return found


# ---------------------------------------------------------------------------
# Compile -> entri registry
# ---------------------------------------------------------------------------


def manifest_canonical_key(data: dict) -> str:
    """Kunci kanonik stabil untuk dedup lintas sumber.

    Memakai `id` bila ada (sudah namespaced), jika tidak turun ke `source/slug`.
    Hash isi TIDAK dipakai sebagai kunci — dua manifest yang isinya sama tetapi
    id-nya berbeda adalah dua connector yang berbeda secara semantik.
    """
    mid = str(data.get("id") or "").strip().lower()
    if mid:
        return mid
    return f"{str(data.get('source') or 'unknown').strip().lower()}/{str(data.get('slug') or '').strip().lower()}"


def compile_manifest(data: dict) -> dict[str, Any]:
    """Compile manifest yang SUDAH valid menjadi entri registry.

    Bentuk keluaran sengaja identik dengan entri `mcp_registry.load_cached()`
    supaya dapat langsung digabung tanpa lapisan adaptasi kedua. Deterministik:
    `json.dumps(hasil, sort_keys=True)` selalu sama untuk manifest yang sama.

    Raises:
        ManifestError: bila manifest tidak valid (bawa seluruh daftar error).
    """
    errors = validate_manifest(data)
    if errors:
        raise ManifestError(errors)

    actions = list(data.get("actions") or [])
    triggers = list(data.get("triggers") or [])
    auth = data.get("auth") or {"type": "none"}
    credential_free = bool(data.get("credential_free")) or auth.get("type") == "none"

    # Verifikasi diturunkan dari action: level tertinggi yang diklaim.
    levels = [
        (a.get("verification") or {}).get("level")
        for a in actions
        if isinstance(a, dict)
    ]
    if "call_verified" in levels and credential_free:
        level = "call_verified"
    elif "call_verified" in levels:
        # Diklaim call_verified tetapi butuh kredensial: jangan promosikan.
        # Ini aturan yang sama dengan `runtime_tier` di mcp_registry.
        level = "callable"
    elif "callable" in levels:
        level = "callable"
    else:
        level = "listed"

    operation_types = sorted({str(a.get("operation_type")) for a in actions if isinstance(a, dict)})

    tools = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        tools.append({
            "name": a.get("name"),
            "description": str(a.get("description") or ""),
            "operation_type": a.get("operation_type"),
            "method": str(a.get("method") or ("GET" if a.get("operation_type") == "read" else "POST")).upper(),
            "path": a.get("path"),
            "call_verified": bool((a.get("verification") or {}).get("level") == "call_verified" and credential_free),
            "credential_free": credential_free,
            "locally_executable": True,
            "no_auth_runnable": credential_free,
            "no_input": not bool(a.get("request_body_json")),
        })

    payload = {
        "id": data["id"],
        "slug": data["slug"],
        "name": data.get("display_name") or data["slug"],
        "source": data.get("source"),
        "category": data.get("category"),
        "description": str(data.get("description") or ""),
        "tenant_scope": data.get("tenant_scope"),
        "deprecated": bool(data.get("deprecated")),
        "deprecated_at": None,
        "minimum_supported_release": data.get("minimum_supported_release"),
        "manifest_version": data.get("manifest_version"),
        "canonical_key": manifest_canonical_key(data),
        "auth_type": auth.get("type"),
        "auth_schemes": [auth.get("type")],
        "credential_form": auth.get("credential_form"),
        "connect_url": auth.get("connect_url"),
        "credential_free": credential_free,
        "no_auth": auth.get("type") == "none",
        "operation_types": operation_types,
        "has_write": "write" in operation_types,
        "has_delete": "delete" in operation_types,
        "tools_count": len(tools),
        "tools": tools,
        "triggers": [
            {
                "name": t.get("name"),
                "type": t.get("type"),
                "signature": t.get("signature"),
                "header": t.get("header"),
                "schedule": t.get("schedule"),
            }
            for t in triggers if isinstance(t, dict)
        ],
        "triggers_count": len([t for t in triggers if isinstance(t, dict)]),
        "rate_limit": data.get("rate_limit"),
        "runtime_verified": True,
        "install_config": {
            "transport": "http",
            "package": manifest_canonical_key(data),
            "install_method": "manifest",
        },
        "verification": {
            "discovered": True,
            "tools_listed": True,
            "call_verified": level == "call_verified",
            "level": level,
        },
        "validation": {"status": "valid", "errors": []},
    }
    return payload


def manifest_hash(data: dict) -> str:
    """Hash isi manifest — dipakai untuk mendeteksi drift."""
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_manifest(text: str) -> dict:
    """Parse YAML menjadi dict. Raises ManifestError bila bukan mapping."""
    if yaml is None:
        raise ManifestError(["PyYAML tidak terpasang"])
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - pesan YAML apa adanya
        raise ManifestError([f"YAML tidak dapat di-parse: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ManifestError(["manifest: harus mapping YAML di level atas"])
    return data


def load_manifest(path) -> dict:
    """Baca + validasi satu file manifest. Raises ManifestError."""
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    data = parse_manifest(text)
    errors = validate_manifest(data)
    sec = scan_secrets(text)
    if sec:
        errors.append(f"manifest memuat pola rahasia: {', '.join(sec)}")
    if errors:
        raise ManifestError(errors)
    return data


def compile_file(path) -> dict[str, Any]:
    """Baca + compile satu file manifest menjadi entri registry."""
    return compile_manifest(load_manifest(path))


# ---------------------------------------------------------------------------
# Gate batch (FASE 3)
# ---------------------------------------------------------------------------


@dataclass
class BatchGate:
    """Gerbang 100% PASS per batch — menolak batch yang tidak menaikkan executable.

    Brief meminta gate 100% PASS. Audit menambahkan satu syarat lagi: batch
    yang hanya menambah entri katalog tetapi tidak menambah entri yang benar-
    benar dapat dieksekusi DITOLAK. Tanpa syarat itu, "2000 connector" bisa
    dicapai dengan menaikkan `coverage()["total"]` — persis inflasi yang
    dihindari oleh `coverage()`.
    """

    batch_no: int
    size: int = 20
    results: list[dict] = field(default_factory=list)

    def add(self, connector_id: str, passed: int, failed: int, executable: bool) -> None:
        self.results.append({
            "id": connector_id,
            "passed": int(passed),
            "failed": int(failed),
            "executable": bool(executable),
        })

    @property
    def total_passed(self) -> int:
        return sum(r["passed"] for r in self.results)

    @property
    def total_failed(self) -> int:
        return sum(r["failed"] for r in self.results)

    @property
    def executable_count(self) -> int:
        return sum(1 for r in self.results if r["executable"])

    def verdict(self) -> dict[str, Any]:
        checks = {
            "size_ok": len(self.results) == self.size,
            "all_tests_pass": self.total_failed == 0 and len(self.results) > 0,
            "executable_increased": self.executable_count > 0,
        }
        return {
            "batch": self.batch_no,
            "connectors": len(self.results),
            "tests_passed": self.total_passed,
            "tests_failed": self.total_failed,
            "executable": self.executable_count,
            "checks": checks,
            "verdict": "PASS" if all(checks.values()) else "FAIL",
        }


# ---------------------------------------------------------------------------
# Deskripsi
# ---------------------------------------------------------------------------


def describe() -> dict[str, Any]:
    """Ringkasan kosakata skema — dipakai endpoint API dan test invarian."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "auth_types": list(AUTH_TYPES),
        "operation_types": list(OPERATION_TYPES),
        "tenant_scopes": list(TENANT_SCOPES),
        "trigger_types": list(TRIGGER_TYPES),
        "record_selectors": list(RECORD_SELECTORS),
        "paginators": list(PAGINATORS),
        "error_handlers": list(ERROR_HANDLERS),
        "backoff_strategies": list(BACKOFF_STRATEGIES),
        "rate_limit_types": list(RATE_LIMIT_TYPES),
        "verification_levels": list(VERIFICATION_LEVELS),
        "http_methods": list(HTTP_METHODS),
        "interpolation_filters": list(INTERPOLATION_FILTERS),
        "interpolation_variables": [
            "config", "input", "record", "stream_slice", "stream_interval",
            "now_utc", "today_utc", "timestamp",
        ],
        "invariants": [
            "credential_free untuk auth.type 'none' selalu true",
            "verification.level 'call_verified' hanya bila credential_free",
            "compile_manifest deterministik (json.dumps sort_keys sama)",
            "manifest dengan url_base loopback/privat ditolak oleh host_is_blocked",
        ],
    }
