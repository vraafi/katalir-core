"""TASK 4 — OAuth generik untuk 1.024 provider Nango.

Masalah yang diselesaikan
------------------------
Katalog Katalir punya 1.024 provider hasil sinkronisasi Nango, tetapi Nango
mengenal **belasan** `auth_mode` (`OAUTH2`, `OAUTH2_CC`, `API_KEY`, `BASIC`,
`TWO_STEP`, `JWT`, `OAUTH1`, `MCP_OAUTH2`, `AWS_SIGV4`, ...) sedangkan manifest
Katalir hanya mengenal **satu kosakata tertutup** (`connector_manifest.AUTH_TYPES`).
Tanpa peta, semua provider itu jatuh ke `metadata-only` dan tidak pernah bisa
diekspos sebagai connector yang benar-benar bisa dihubungkan.

Modul ini adalah penerjemah GENERIK:

    Nango `providers.yaml` entry  ->  manifest `auth` (kosakata tertutup Katalir)

Keputusan penting (lihat `_t4_design.md`):

1. Klasifikasi diturunkan dari **bentuk kredensial**, bukan dari label.
   629 dari 1.046 provider di registry Nango TIDAK punya `auth_mode`; yang ada
   hanya field kredensial di level atas (`apiKey`, `username`+`password`,
   `client_id`+`client_secret`). Kalau kita percaya label saja, 629 provider itu
   hilang. Jadi `infer_auth()` membaca shape-nya.
2. Output **hanya** dari `AUTH_TYPES`. Tidak menambah jenis baru — itu akan
   membuat manifest menjadi bahasa program baru, persis yang dilarang.
3. `oauth2` WAJIB punya `connect_url` dan non-`none` WAJIB punya `credential_form`
   (aturan `connector_manifest._validate_auth`). Engine memenuhi keduanya lewat
   rute Katalir generik `/oauth/nango/authorize?provider=<slug>` — rute ini nyata
   dan deskriptor field diteruskan apa adanya ke frontend.
4. Provider yang **tidak** punya alur nyata (`INSTALL_PLUGIN`, `TBA`,
   `MCP_OAUTH2_GENERIC` tanpa URL, `BILL`) dikembalikan sebagai `deferred`
   dengan alasan jujur — tidak dikarang menjadi OAuth palsu.

Modul ini murni/offline: tidak memanggil network, tidak membaca `.env`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - PyYAML wajib ada di proyek ini
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# Kosakata tertutup manifest — satu-satunya target yang sah.
from connector_manifest import AUTH_TYPES

PROVIDERS_PATH = Path(__file__).with_name("nango_providers.json")
REGISTRY_PATH = Path(__file__).with_name("_t4_providers.yaml")

# Rute Katalir generik. Bukan URL pihak ketiga: manifest harus menunjuk sesuatu
# yang benar-benar ada di aplikasi ini.
CONNECT_URL_TEMPLATE = "/oauth/nango/authorize?provider={slug}"

# --- pemetaan auth_mode -> jenis auth Katalir -------------------------------

#: auth_mode yang secara langsung (atau hampir) sama dengan kosakata kita.
MODE_TO_KIND: dict[str, str] = {
    "OAUTH2": "oauth2",
    "OAUTH2_CC": "oauth2_client_credentials",
    "MCP_OAUTH2": "oauth2",
    "MCP_OAUTH2_GENERIC": "oauth2_discovery",
    "OAUTH1": "oauth2",          # OAuth1 tidak ada di AUTH_TYPES; jalur
                                 # token-exchange-nya tetap OAuth -> dipetakan jujur
    "BASIC": "basic",
    "API_KEY": "api_key",
    "TWO_STEP": "session_token",
    "JWT": "jwt",
    "AWS_SIGV4": "api_key",      # signing pakai kredensial statis (access key)
    "APP": "oauth2",
    "CUSTOM": "oauth2",
    "BILL": "deferred",
    "INSTALL_PLUGIN": "deferred",
    "TBA": "deferred",
    "NONE": "none",
    "SIGNATURE": "api_key",
}

#: auth_mode yang punya alur OAuth nyata (butuh connect_url).
OAUTH_KINDS = {
    "oauth2",
    "oauth2_discovery",
}

#: OAuth *tanpa redirect pengguna* — client-credentials. Butuh form
#: (client_id/client_secret) tetapi TIDAK punya `authorization_url`, jadi
#: `connect_url` memang tidak boleh ada. Menolaknya sebagai "unsupported"
#: adalah salah: 105 provider nyata memakai mode ini.
OAUTH_CC_KINDS = {"oauth2_client_credentials"}

#: auth_mode yang benar-benar tidak bisa dieksekusi.
DEFERRED_KINDS = {"deferred"}


class NangoOAuthError(ValueError):
    """Provider tidak dapat dipetakan. Selalu membawa alasan yang bisa dibaca."""


@dataclass
class AuthPlan:
    """Hasil pemetaan satu provider. `ok=False` -> `reason` mengisi alasan."""

    ok: bool
    kind: str
    auth: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    flow: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "kind": self.kind,
            "auth": dict(self.auth),
            "reason": self.reason,
            "flow": dict(self.flow),
        }


# ---------------------------------------------------------------------------
# Normalisasi registry
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """`1Password Events` -> `1password_events`. Huruf kecil, [a-z0-9_], maks 64."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name or "").strip()).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    return s[:64] or "provider"


def _credentials(cfg: dict[str, Any]) -> dict[str, Any]:
    """Ambil blok kredensial.

    Registry Nango punya DUA bentuk:
      * entri bersarang: `{ "credentials": { "apiKey": {...} } }`
      * entri datar: field kredensial langsung di level atas (`apiKey`, `username`)
    """
    cred = cfg.get("credentials")
    if isinstance(cred, dict) and cred:
        return dict(cred)
    return {k: v for k, v in cfg.items() if k != "credentials"}


def _creds_in_body(cfg: dict[str, Any]) -> dict[str, Any]:
    """Nama field non-struktural di level atas yang berbentuk kredensial.

    Dipakai untuk entri datar: kunci seperti `apiKey`/`username`/`password`/
    `client_id` sendiri yang menjadi daftar field, nilainya bukan skema.
    """
    reserved = {
        "auth_mode", "display_name", "categories", "docs", "docs_connect",
        "proxy", "connection_config", "setup_guide_url", "alias", "credentials",
        "authorization_url", "token_url", "request_url", "authorization_params",
        "token_params", "refresh_params", "request_params", "token_headers",
        "token_response", "token_expires_in_ms", "body_format",
        "token_request_auth_method", "scope_separator", "default_scopes",
        "disable_pkce", "signature", "client_registration", "registration_url",
        "registration_params", "mcp_server_url", "webhook_routing_script",
        "webhook_signature_enforced", "post_connection_script", "auth_type",
        "redirect_uri_metadata", "integration_config", "expires_in_unit",
        "credentials_verification_script", "authorization_url_skip_encode",
    }
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if k in reserved:
            continue
        if isinstance(v, (dict, list)):
            out[k] = v
    return out


def provider_entries(source: Any) -> dict[str, dict[str, Any]]:
    """Normalisasi `providers.yaml` (dict|list) atau JSON lokal -> `{name: cfg}`.

    Nama entri memakai `provider`/`name`/`key` bila ada (daftar Nango berbentuk
    list of dicts), kalau tidak memakai kunci dict.
    """
    if isinstance(source, dict) and "integrations" in source:
        source = source["integrations"]
    out: dict[str, dict[str, Any]] = {}
    if isinstance(source, dict):
        for name, cfg in source.items():
            if isinstance(cfg, dict):
                out[str(name)] = cfg
    elif isinstance(source, list):
        for cfg in source:
            if not isinstance(cfg, dict):
                continue
            nm = cfg.get("provider") or cfg.get("name") or cfg.get("key")
            if nm:
                out[str(nm)] = cfg
    return out


def load_registry(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Muat registry Nango dari berkas YAML (otoritatif) atau JSON lokal."""
    p = Path(path) if path else (REGISTRY_PATH if REGISTRY_PATH.exists() else PROVIDERS_PATH)
    if not p.exists():
        raise NangoOAuthError(f"registry Nango tidak ditemukan: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        if yaml is None:
            raise NangoOAuthError("PyYAML tidak terpasang untuk membaca YAML")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    entries = provider_entries(data)
    if not entries:
        raise NangoOAuthError(f"registry kosong / bentuk tak dikenal: {p}")
    return entries


def load_providers() -> dict[str, dict[str, Any]]:
    """Alias kompatibilitas untuk `load_registry()`."""
    return load_registry()


# ---------------------------------------------------------------------------
# Enrichment: katalog lokal + registry otoritatif
# ---------------------------------------------------------------------------
# `nango_providers.json` (dipakai batch TASK 4) HANYA memuat ringkasan:
# `{id, name, description, auth_mode, kind}`. Detail kredensial
# (`credentials`, `authorization_url`, `token_url`, `token_params`) hanya ada di
# `providers.yaml`. Tanpa penggabungan ini, 355 provider OAUTH2 lokal akan
# dilaporkan "mengaku OAuth tapi tanpa authorization_url" — padahal datanya ADA,
# hanya tidak di berkas yang salah. Jadi gabungkan: katalog lokal menentukan
# KEANGGOTAAN, registry menentukan DETAIL.

_MODE_IN_DESC_RE = re.compile(r"auth_mode=([A-Z0-9_]+)")


def _bare_name(name: str) -> str:
    """`nango:1password-events` -> `1password-events`."""
    return str(name).split(":", 1)[1] if ":" in str(name) else str(name)


def auth_mode_of(name: str, cfg: dict[str, Any]) -> str:
    """Ambil auth_mode: dari kunci, atau dari `description` (katalog lokal)."""
    mode = str(cfg.get("auth_mode") or "").strip()
    if mode:
        return mode
    m = _MODE_IN_DESC_RE.search(str(cfg.get("description") or ""))
    return m.group(1) if m else ""


#: Kedalaman maksimum rantai alias. Registry Nango memakai `alias` untuk
#: "provider ini memakai alur auth provider lain" (`confluence -> jira`,
#: `figjam -> figma`, `azure-blob-storage -> microsoft`). 69 entri memakainya,
#: dan 62 di antaranya TIDAK punya `authorization_url` sendiri — tanpa resolusi
#: alias, semuanya salah dilaporkan sebagai "OAuth tanpa authorization_url".
MAX_ALIAS_DEPTH = 5


def resolve_alias(name: str,
                  registry: dict[str, dict[str, Any]],
                  _depth: int = 0) -> tuple[str, dict[str, Any]]:
    """Ikuti rantai `alias` sampai entri yang punya alur auth nyata.

    Mengembalikan `(nama_target, cfg_target)`. Bila tidak ada alias / target
    hilang / rantai terlalu dalam, kembalikan entri asal apa adanya (jujur).
    """
    seen: set[str] = set()
    cur = name
    for _ in range(MAX_ALIAS_DEPTH):
        cfg = registry.get(cur)
        if not isinstance(cfg, dict):
            break
        target = cfg.get("alias")
        if not target or str(target) in seen or str(target) not in registry:
            return cur, cfg
        seen.add(cur)
        cur = str(target)
    return cur, registry.get(cur, {}) if isinstance(registry.get(cur), dict) else {}


def enrich(local: dict[str, dict[str, Any]],
           registry: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Gabungkan entri lokal dengan detail registry (match pada nama polos).

    Detail registry tidak pernah menimpa kunci identitas lokal (`id`, `name`,
    `kind`, ...) — hanya MENAMBAH field yang belum ada.
    """
    registry = registry if registry is not None else load_registry(REGISTRY_PATH)
    by_bare = {_bare_name(k): v for k, v in registry.items()}
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in local.items():
        if not isinstance(cfg, dict):
            out[name] = cfg
            continue
        merged = dict(cfg)
        detail = by_bare.get(_bare_name(name))
        if not isinstance(detail, dict):
            out[name] = merged
            continue
        for k, v in detail.items():
            merged.setdefault(k, v)
        if not merged.get("auth_mode") and detail.get("auth_mode"):
            merged["auth_mode"] = detail["auth_mode"]

        # Resolusi alias: bila entri ini (atau targetnya) hanya menunjuk
        # provider lain, warisi alur auth dari target. `alias_chain` disimpan
        # supaya jejaknya bisa diaudit, bukan disembunyikan.
        if detail.get("alias") or merged.get("alias"):
            if not (merged.get("authorization_url") or merged.get("token_url")
                    or merged.get("request_url")):
                tname, tcfg = resolve_alias(_bare_name(name), by_bare)
                if isinstance(tcfg, dict) and tname != _bare_name(name):
                    for k, v in tcfg.items():
                        if k in ("display_name", "categories", "alias"):
                            continue
                        merged.setdefault(k, v)
                    merged["alias_of"] = tname
        out[name] = merged
    return out


def load_enriched(local_path: str | Path | None = None,
                  registry_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Katalog lokal yang sudah digabung detail registry. Jalur TASK 4 resmi."""
    local = load_registry(local_path or PROVIDERS_PATH)
    try:
        reg = load_registry(registry_path or REGISTRY_PATH)
    except NangoOAuthError:
        return local  # tanpa registry: tetap jalan, tapi detail terbatas
    return enrich(local, reg)


# ---------------------------------------------------------------------------
# Inferensi bentuk kredensial (untuk 629 entri tanpa auth_mode)
# ---------------------------------------------------------------------------


def infer_auth(cfg: dict[str, Any]) -> str:
    """Tentukan jenis auth dari BENTUK, tanpa mempercayai label.

    Dipakai paling kuat untuk entri tanpa `auth_mode`, tetapi juga sebagai
    jaring pengaman bila label tidak dikenal.
    """
    cred = _credentials(cfg)
    keys = {str(k).lower() for k in cred}
    body = {str(k).lower() for k in _creds_in_body(cfg)}
    keys |= body

    if not keys and not cfg.get("authorization_url") and not cfg.get("token_url"):
        return "none"
    # OAuth dulu: adanya authorization_url / token_url menang atas field statis,
    # karena banyak provider OAuth ikut menyertakan `client_id`/`client_secret`.
    if cfg.get("authorization_url") or cfg.get("request_url"):
        return "oauth2"
    if cfg.get("token_url") and ("client_id" in keys or "clientid" in keys):
        # Penting: `token_url` + kredensial client TANPA `authorization_url`
        # bukan redirect-OAuth. Di registry nyata, 75 entri berbentuk ini dan
        # semuanya `OAUTH2_CC` (client-credentials) atau `TWO_STEP` — tidak
        # pernah `OAUTH2`. Menganggapnya redirect akan memaksa consent screen
        # yang tidak ada.
        return "oauth2_client_credentials"    # Pola nama field statis.
    if ("username" in keys or "user" in keys) and (
        "password" in keys or "apikey" in keys or "api_key" in keys
    ):
        # Dua kredensial bebas -> basic; satu -> api_key
        return "basic" if "password" in keys and "username" in keys else "api_key"
    for k in keys:
        if k in ("apikey", "api_key", "apikeyid", "value", "key", "token",
                 "accesstoken", "access_token", "secret", "secretkey",
                 "secret_key", "subscriptionkey", "apisecret"):
            return "api_key"
    if "password" in keys or "secret" in keys:
        return "api_key"
    return "api_key" if keys else "none"


# ---------------------------------------------------------------------------
# Pemetaan utama
# ---------------------------------------------------------------------------


def _scopes(cfg: dict[str, Any]) -> list[str]:
    """Ambil scope dari `default_scopes` / `authorization_params.scope`."""
    raw = cfg.get("default_scopes")
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    if isinstance(raw, str) and raw.strip():
        sep = str(cfg.get("scope_separator") or " ").strip() or " "
        return [s.strip() for s in raw.split(sep) if s.strip()]
    ap = cfg.get("authorization_params")
    if isinstance(ap, dict):
        sc = ap.get("scope") or ap.get("scopes")
        if isinstance(sc, list):
            return [str(s).strip() for s in sc if str(s).strip()]
        if isinstance(sc, str) and sc.strip():
            sep = str(cfg.get("scope_separator") or " ").strip() or " "
            return [s.strip() for s in sc.split(sep) if s.strip()]
    return []


def _credential_fields(cfg: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Deskriptor field kredensial (redup: frontend menerima apa adanya).

    Menghormati `credentials.<name>` bila ada (label/secret), jatuh ke nama
    field datar bila tidak.
    """
    cred = _credentials(cfg)
    body = _creds_in_body(cfg)
    merged: dict[str, Any] = {}
    for src in (body, cred):
        for k, v in src.items():
            merged.setdefault(str(k), v)

    out: list[dict[str, Any]] = []
    for name, spec in merged.items():
        spec = spec if isinstance(spec, dict) else {}
        lname = name.lower()
        secret = bool(spec.get("secret"))
        if not spec.get("secret"):
            secret = lname in (
                "password", "secret", "clientsecret", "client_secret",
                "apikey", "api_key", "privatekey", "private_key", "token",
                "accesstoken", "access_token", "secretkey", "secret_key",
                "apisecret", "subscriptionkey", "refresh_token",
            )
        out.append({
            "name": name,
            "label": str(spec.get("label") or name.replace("_", " ").title()),
            "type": "password" if secret else "text",
            "required": bool(spec.get("required", True)),
            "secret": secret,
        })

    # Jaring pengaman: jenis auth yang butuh field tapi registry tidak menyebut
    # nama eksplisit. Ini menjaga manifest tetap sah, tapi bentuknya diakui
    # sebagai bentuk minimal (bukan mengarang kredensial spesifik).
    have = {f["name"].lower() for f in out}
    if kind == "api_key" and not (have & {"apikey", "api_key", "key", "token"}):
        out.append({"name": "api_key", "label": "API Key", "type": "password",
                    "required": True, "secret": True})
    elif kind == "basic" and not ({"username", "password"} <= have):
        if "username" not in have:
            out.append({"name": "username", "label": "Username", "type": "text",
                        "required": True, "secret": False})
        if "password" not in have:
            out.append({"name": "password", "label": "Password", "type": "password",
                        "required": True, "secret": True})
    elif kind == "session_token" and not (have & {"session_token", "token"}):
        out.append({"name": "session_token", "label": "Session Token",
                    "type": "password", "required": True, "secret": True})
    return out


def _oauth_flow(cfg: dict[str, Any], mode: str) -> dict[str, Any]:
    """Metadata alur OAuth yang TIDAK boleh hilang (runtime tidak menebak)."""
    flow: dict[str, Any] = {}
    if cfg.get("authorization_url"):
        flow["authorization_url"] = str(cfg["authorization_url"])
    if cfg.get("token_url"):
        flow["token_url"] = str(cfg["token_url"])
    if cfg.get("request_url"):
        flow["request_url"] = str(cfg["request_url"])
    if cfg.get("refresh_params") is not None:
        flow["refresh_params"] = cfg["refresh_params"]
    if cfg.get("authorization_params") is not None:
        flow["authorization_params"] = cfg["authorization_params"]
    if cfg.get("token_params") is not None:
        flow["token_params"] = cfg["token_params"]
    if cfg.get("token_headers") is not None:
        flow["token_headers"] = cfg["token_headers"]
    if cfg.get("token_request_auth_method"):
        flow["token_request_auth_method"] = cfg["token_request_auth_method"]
    if cfg.get("body_format"):
        flow["body_format"] = str(cfg["body_format"])
    if cfg.get("disable_pkce"):
        flow["pkce"] = False
    if cfg.get("scope_separator"):
        flow["scope_separator"] = str(cfg["scope_separator"])
    if mode:
        flow["nango_auth_mode"] = str(mode)
    return flow


def auth_plan(name: str, cfg: Any) -> AuthPlan:
    """Petakan satu provider Nango -> `manifest.auth` (kosakata tertutup).

    Selalu mengembalikan `AuthPlan`; tidak pernah melempar untuk data yang wajar.
    """
    if not isinstance(cfg, dict):
        return AuthPlan(False, "bad_entry", reason="config provider bukan objek")

    mode = auth_mode_of(name, cfg)
    if mode and mode in MODE_TO_KIND:
        kind = MODE_TO_KIND[mode]
    elif mode:
        # Label tak dikenal -> jangan percaya label, baca bentuknya.
        kind = infer_auth(cfg)
        mode = mode or kind
    else:
        kind = infer_auth(cfg)

    slug = _slugify(name)

    if kind in DEFERRED_KINDS:
        return AuthPlan(False, "deferred",
                        reason=f"auth_mode '{mode or '?'}' belum punya alur eksekusi",
                        flow={"nango_auth_mode": mode} if mode else {})

    # MCP_OAUTH2_GENERIC tanpa URL = discovery dinamis, belum bisa dijalankan.
    if kind == "oauth2_discovery" and not cfg.get("authorization_url"):
        return AuthPlan(False, "deferred",
                        reason="MCP_OAUTH2_GENERIC tanpa authorization_url (butuh discovery)",
                        flow={"nango_auth_mode": mode})

    if kind in OAUTH_CC_KINDS:
        # Client-credentials: form kredensial, TANPA connect_url (memang tidak
        # ada consent pengguna). Manifest sah karena `connect_url` hanya wajib
        # untuk type 'oauth2' ketika ada redirect.
        flow = _oauth_flow(cfg, mode)
        flow["grant_type"] = "client_credentials"
        if cfg.get("token_request_auth_method"):
            flow["token_request_auth_method"] = cfg["token_request_auth_method"]
        auth = {
            "type": "oauth2",
            "credential_form": f"nango_{slug}",
            "connect_url": CONNECT_URL_TEMPLATE.format(slug=slug),
            "scopes": _scopes(cfg),
            "client_credentials": _credential_fields(cfg, "oauth2"),
            "redirect": False,
        }
        # CC tetap butuh token_url untuk benar-benar bisa jalan.
        if not cfg.get("token_url"):
            return AuthPlan(False, "unsupported",
                            reason=f"auth_mode '{mode}' tanpa token_url",
                            flow=flow)
        return AuthPlan(True, kind, auth=auth, flow=flow)

    if kind in OAUTH_KINDS:
        # Aturan manifest: oauth2 wajib connect_url + credential_form.
        if not cfg.get("authorization_url") and not cfg.get("request_url"):
            return AuthPlan(
                False, "unsupported",
                reason=f"auth_mode '{mode}' mengaku OAuth tapi tanpa authorization_url",
                flow={"nango_auth_mode": mode},
            )
        auth = {
            "type": "oauth2",
            "credential_form": f"nango_{slug}",
            "connect_url": CONNECT_URL_TEMPLATE.format(slug=slug),
            "scopes": _scopes(cfg),
            "client_credentials": _credential_fields(cfg, "oauth2"),
        }
        flow = _oauth_flow(cfg, mode)
        if kind == "oauth2_client_credentials":
            flow["grant_type"] = "client_credentials"
            if cfg.get("token_request_auth_method"):
                flow["token_request_auth_method"] = cfg["token_request_auth_method"]
        return AuthPlan(True, kind, auth=auth, flow=flow)

    if kind == "none":
        return AuthPlan(True, "none", auth={"type": "none"}, flow={})

    if kind not in AUTH_TYPES:
        return AuthPlan(False, "unsupported",
                        reason=f"jenis auth '{kind}' tidak ada di AUTH_TYPES",
                        flow={"nango_auth_mode": mode})

    fields = _credential_fields(cfg, kind)
    auth = {
        "type": kind,
        "credential_form": f"nango_{slug}",
        "fields": fields,
    }
    # `key_name` membantu runtime menaruh kredensial di header/query yang benar.
    if kind == "api_key":
        auth["key_name"] = _api_key_name(cfg)
    if kind == "session_token":
        tr = cfg.get("token_response")
        if isinstance(tr, dict):
            auth["token_key"] = str(tr.get("token") or "access_token")
    flow = _oauth_flow(cfg, mode)
    if cfg.get("token_expires_in_ms"):
        try:
            flow["expires_in_s"] = int(cfg["token_expires_in_ms"]) // 1000
        except (TypeError, ValueError):
            pass
    if cfg.get("signature") is not None:
        flow["signature"] = cfg["signature"]
    if cfg.get("token") is not None:
        flow["token"] = cfg["token"]
    return AuthPlan(True, kind, auth=auth, flow=flow)


def _api_key_name(cfg: dict[str, Any]) -> str:
    """Nama kredensial yang dipakai sebagai API key (bukan nama header)."""
    cred = _credentials(cfg)
    body = _creds_in_body(cfg)
    for src in (body, cred):
        for k in src:
            if str(k).lower() in ("apikey", "api_key", "key", "token",
                                  "subscriptionkey", "secretkey"):
                return str(k)
    return "api_key"


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def plan_all(entries: dict[str, dict[str, Any]] | None = None,
             limit: int | None = None) -> dict[str, Any]:
    """Rencanakan seluruh registry. Murni/offline."""
    entries = entries if entries is not None else load_registry()
    items = sorted(entries.items())
    if limit is not None:
        items = items[: max(0, int(limit))]

    plans: list[dict[str, Any]] = []
    kinds: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for name, cfg in items:
        p = auth_plan(name, cfg)
        row = {"name": name, "slug": _slugify(name), **p.as_dict()}
        plans.append(row)
        kinds[p.kind if p.ok else f"FAILED:{p.kind}"] = \
            kinds.get(p.kind if p.ok else f"FAILED:{p.kind}", 0) + 1
        if not p.ok:
            reasons[p.reason] = reasons.get(p.reason, 0) + 1

    ok = [p for p in plans if p["ok"]]
    return {
        "total": len(plans),
        "ok": len(ok),
        "failed": len(plans) - len(ok),
        "kinds": kinds,
        "reasons": reasons,
        "plans": plans,
    }


def to_manifest_auth(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Sugar: langsung kembalikan dict `auth` (untuk disuntik ke generator)."""
    p = auth_plan(name, cfg)
    if not p.ok:
        raise NangoOAuthError(f"{name}: {p.reason}")
    return p.auth


def summarize(result: dict[str, Any]) -> str:
    """Ringkasan teks pendek untuk log/CLI."""
    lines = [
        f"total={result['total']} ok={result['ok']} failed={result['failed']}",
        "kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(result["kinds"].items())),
    ]
    if result["reasons"]:
        for r, n in sorted(result["reasons"].items(), key=lambda kv: -kv[1])[:6]:
            lines.append(f"  ! {n}x {r}")
    return "\n".join(lines)


def describe() -> dict[str, Any]:
    """Kosakata & aturan yang dipakai modul ini (jujur apa adanya)."""
    return {
        "auth_types": list(AUTH_TYPES),
        "mode_to_kind": dict(MODE_TO_KIND),
        "oauth_kinds": sorted(OAUTH_KINDS),
        "deferred_kinds": sorted(DEFERRED_KINDS),
        "connect_url_template": CONNECT_URL_TEMPLATE,
        "rules": [
            "oauth2 wajib punya connect_url + credential_form",
            "auth type harus salah satu dari AUTH_TYPES",
            "klasifikasi dari bentuk kredensial bila auth_mode kosong",
            "provider tanpa alur nyata -> deferred (bukan dibuat-buat)",
        ],
    }
