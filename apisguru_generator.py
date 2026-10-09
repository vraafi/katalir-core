"""apisguru_generator.py — TASK 3: hasilkan manifest connector dari APIs.guru.

TUJUAN
------
APIs.guru (`openapi-directory`) memuat 2.500+ spesifikasi OpenAPI publik.
Membuat tool MCP manual untuk masing-masing adalah pekerjaan yang tidak pernah
selesai. Mesin ini membaca direktori itu dan **meng-compile** spesifikasi
terpilih menjadi manifest `connector.yaml` yang sah menurut skema
`connector_manifest.py` — lalu manifest itu masuk ke pipeline yang sudah ada
(`/connectors/validate`, `/connectors/compile`, `connector_harness`).

Target brief: **100–200 connector**. Target itu dicapai tanpa satu baris pun
kode per-API: satu mesin, N spesifikasi. Itu pola "generic executor" yang
sama dengan yang dipakai Airbyte (declarative manifest) dan OpenAPI→MCP.

HASILNYA NYATA ATAU TIDAK SAMA SEKALI
-------------------------------------
Aturan yang tidak dilanggar:

1. Sebuah operasi menjadi action HANYA bila punya `path` dan `method` nyata.
2. `operation_type` diturunkan dari method: GET/HEAD → read, POST/PUT/PATCH →
   write, DELETE → delete. Tidak ada action read yang memakai POST.
3. Action dengan `{}` di path (butuh parameter) hanya dibuat bila SELURUH
   parameter path punya `example`/`default` di spesifikasi. Kalau tidak, action
   itu dibuang — bukan dibuat dengan placeholder palsu.
4. `verification.level` selalu `listed`. `callable`/`call_verified` hanya
   diberikan oleh harness setelah panggilan nyata; generator TIDAK PERNAH
   mengklaim sudah diverifikasi.
5. `auth.type` diturunkan dari `securitySchemes`. Scheme yang tidak dikenal →
   `api_key` dengan catatan, bukan `none` (jangan pernah berpura-pura terbuka).
6. Server loopback/privat di `servers[].url` ditolak.
7. Hanya operasi tanpa `security` (atau `security: []`) dan tanpa skema global
   yang boleh menjadi `credential_free: true`.

CARA PAKAI
----------
    from apisguru_generator import generate, load_directory
    directory = load_directory()         # dari _apisguru_list.json
    plan = plan_batch(directory, limit=150)
    results = generate_batch(plan, out_dir="connectors/apisguru")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from connector_manifest import host_is_blocked as _manifest_host_is_blocked
from connector_manifest import validate_manifest


def host_is_blocked(url: str) -> bool:
    """Guard SSRF untuk host/URL apa pun.

    `connector_manifest.host_is_blocked()` menerima **URL penuh** (regex-nya
    `^https?://...`) dan mengembalikan True — artinya "tolak" — untuk input
    yang tidak dikenali. Memanggilnya dengan host telanjang karena itu akan
    menolak **semua** host, termasuk host publik yang sah. Pembungkus ini
    menerima keduanya supaya pemanggil tidak dapat salah pakai.
    """
    raw = str(url or "").strip()
    if not raw:
        return True
    probe = raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
    return _manifest_host_is_blocked(probe)


DEFAULT_LIST = Path(__file__).with_name("_apisguru_list.json")
DEFAULT_OUT = Path(__file__).with_name("connectors") / "apisguru"

# Batas jumlah action per connector — manifest raksasa (GitHub punya 900+
# operasi) tidak berguna bagi agen dan membebani UI.
MAX_ACTIONS = 40
# Kedalaman path maksimum yang masih masuk akal sebagai satu tool.
MAX_PATH_SEGMENTS = 8

_METHOD_MAP = {
    "get": "read", "head": "read", "options": "read",
    "post": "write", "put": "write", "patch": "write",
    "delete": "delete", "trace": "read",
}

_ID_SAFE = re.compile(r"[^a-z0-9]+")


class GeneratorError(ValueError):
    """Spesifikasi tidak dapat diubah menjadi manifest."""


@dataclass
class GenResult:
    api: str
    title: str
    slug: str
    ok: bool
    reason: str = ""
    actions: int = 0
    credential_free: bool = False
    manifest_path: str = ""
    errors: list[str] = field(default_factory=list)
    skipped_operations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "api": self.api, "title": self.title, "slug": self.slug,
            "ok": self.ok, "reason": self.reason, "actions": self.actions,
            "credential_free": self.credential_free,
            "manifest_path": self.manifest_path, "errors": self.errors,
            "skipped_operations": self.skipped_operations,
        }


# ---------------------------------------------------------------------------
# Direktori APIs.guru
# ---------------------------------------------------------------------------


def load_directory(path: Path | str = DEFAULT_LIST) -> dict[str, Any]:
    """Baca `list.json` APIs.guru. Melempar bila berkas rusak/terpotong."""
    p = Path(path)
    if not p.exists():
        raise GeneratorError(f"direktori APIs.guru tidak ada: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GeneratorError(
            f"direktori APIs.guru rusak/terpotong ({p.name}): {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise GeneratorError("direktori APIs.guru bukan objek JSON yang berisi")
    return data


def preferred_spec(entry: dict) -> tuple[str, dict] | None:
    """Ambil versi `preferred` dari satu entri direktori."""
    if not isinstance(entry, dict):
        return None
    versions = entry.get("versions") or {}
    if not isinstance(versions, dict) or not versions:
        return None
    pref = entry.get("preferred")
    ver = versions.get(pref) if pref else None
    if not isinstance(ver, dict):
        # jatuh ke versi pertama yang punya openapiUrl
        for v in versions.values():
            if isinstance(v, dict) and v.get("openapiUrl"):
                ver = v
                break
    return (pref, ver) if isinstance(ver, dict) else None


def spec_url(entry: dict) -> str:
    """URL spesifikasi dari satu entri direktori.

    APIs.guru `list.json` memakai `swaggerUrl` / `swaggerYamlUrl` (nama historis
    dari era Swagger), BUKAN `openapiUrl` — `openapiUrl` hanya muncul di
    respons per-API `/v2/specs/...`. Memeriksa hanya `openapiUrl` membuat
    **seluruh 2.529 entri ditolak**, jadi keempat kunci diperiksa berurutan
    dengan preferensi JSON (lebih cepat & lebih mudah di-parse).
    """
    got = preferred_spec(entry)
    if not got:
        return ""
    _, ver = got
    for key in ("openapiUrl", "swaggerUrl", "openapiYamlUrl", "swaggerYamlUrl"):
        val = str(ver.get(key) or "")
        if val.startswith("https://"):
            return val
    return ""


def spec_is_eligible(entry: dict) -> tuple[bool, str]:
    """Saring cepat tanpa mengunduh: bentuk & protokol yang dapat dieksekusi."""
    got = preferred_spec(entry)
    if not got:
        return False, "tanpa versi preferred"
    url = spec_url(entry)
    if not url:
        return False, "tanpa URL spesifikasi https"
    return True, ""


# ---------------------------------------------------------------------------
# Konversi satu spesifikasi
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    s = _ID_SAFE.sub("_", str(value or "").lower()).strip("_")
    return s or "api"


def _deref(spec: dict, node: Any, depth: int = 0) -> Any:
    """Selesaikan `$ref` lokal (#/components/...) dengan batas kedalaman."""
    if depth > 6 or not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return node
    cur: Any = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict):
            return node
        cur = cur.get(part)
    if isinstance(cur, dict) and cur is not node:
        return _deref(spec, cur, depth + 1)
    return node


def _has_example(node: dict) -> bool:
    if not isinstance(node, dict):
        return False
    if "example" in node or "default" in node:
        return True
    if isinstance(node.get("enum"), list) and node["enum"]:
        return True
    return False


def _pick_server(spec: dict) -> tuple[str, str]:
    """Pilih server pertama yang https dan tidak diblokir. (base, alasan).

    Sebagian besar spesifikasi di APIs.guru berasal dari konversi Swagger 2.0
    dan **tidak punya `servers[]`**. Konvensi Swagger 2.0 menaruh alamat di
    `host` + `basePath` + `schemes`. Kalau itu diabaikan, ratusan API yang
    sebenarnya eksekutabel akan ditolak — jadi fallback ini wajib, bukan
    kemewahan.
    """
    servers = spec.get("servers")
    if isinstance(servers, list) and servers:
        for srv in servers:
            if not isinstance(srv, dict):
                continue
            url = str(srv.get("url") or "")
            # `url` bisa relatif (mis. "/v1") bila ada `host` di akar.
            if url.startswith("/") and spec.get("host"):
                scheme = (spec.get("schemes") or ["https"])[0]
                url = f"{scheme}://{spec['host']}{url}"
            if not url.startswith("https://"):
                continue
            host = urlparse(url).hostname or ""
            if not host or host_is_blocked(host):
                continue
            # Buang variabel template server ({env}) — tidak dapat dieksekusi.
            if "{" in url:
                continue
            return url.rstrip("/"), ""

    # Fallback Swagger 2.0.
    host = str(spec.get("host") or "").strip()
    if host and "{" not in host:
        schemes = spec.get("schemes") or []
        if not schemes or "https" in [str(s).lower() for s in schemes]:
            base_path = str(spec.get("basePath") or "").rstrip("/")
            if host_is_blocked(host):
                return "", "host Swagger 2.0 diblokir"
            return f"https://{host}{base_path}", ""

    return "", "tidak ada server https yang dapat dieksekusi"


def _security_schemes(spec: dict) -> dict:
    comp = spec.get("components") or {}
    sch = comp.get("securitySchemes") or {}
    return sch if isinstance(sch, dict) else {}


def _auth_for(spec: dict, op: dict) -> tuple[dict, bool]:
    """Tentukan blok `auth` + apakah connector credential_free.

    Aturan keamanan: yang tidak dikenal JANGAN pernah dianggap `none`.
    Aturan skema: auth selain `none` WAJIB punya `credential_form`; oauth2
    WAJIB punya `connect_url`. Tanpa itu manifest ditolak `validate_manifest`
    — dan itu benar, karena kredensialnya tidak dapat diminta dari pengguna.
    """
    op_sec = op.get("security", None)
    global_sec = spec.get("security", None)

    if op_sec == []:
        op_requires = False
    elif isinstance(op_sec, list) and op_sec:
        op_requires = True
    elif isinstance(global_sec, list) and global_sec:
        op_requires = True
    else:
        op_requires = False

    schemes = _security_schemes(spec)
    if not op_requires:
        return {"type": "none"}, True

    first: dict = {}
    if isinstance(op_sec, list) and op_sec:
        names = list((op_sec[0] or {}).keys())
    elif isinstance(global_sec, list) and global_sec:
        names = list((global_sec[0] or {}).keys())
    else:
        names = []
    for nm in names:
        cand = schemes.get(nm)
        if isinstance(cand, dict):
            first = cand
            break

    stype = str(first.get("type") or "").lower()
    scheme = str(first.get("scheme") or "").lower()
    header = str(first.get("name") or "").lower()

    if stype == "oauth2" or stype == "openidconnect":
        auth = {"type": "oauth2",
                "credential_form": "oauth_connect",
                "connect_url": "https://katalir.de5.net/integrations/connect"}
        flows = first.get("flows") or {}
        scopes: list[str] = []
        if isinstance(flows, dict):
            for fl in flows.values():
                if isinstance(fl, dict):
                    scopes.extend(list((fl.get("scopes") or {}).keys()))
        if scopes:
            auth["scopes"] = sorted(set(scopes))[:40]
        return auth, False

    if stype == "http" and scheme == "bearer":
        return {"type": "bearer", "credential_form": "token_paste"}, False
    if stype == "http" and scheme == "basic":
        return {"type": "basic", "credential_form": "user_pass"}, False
    if stype == "http" and scheme == "digest":
        return {"type": "basic", "credential_form": "user_pass"}, False
    if stype == "apikey":
        form = "api_key_header" if str(first.get("in")) == "header" else "api_key_query"
        return {"type": "api_key", "credential_form": form, "key_name": header or "api_key"}, False
    # Tidak dikenal: jangan pernah mengaku terbuka.
    return {"type": "api_key", "credential_form": "api_key_header",
            "key_name": header or "api_key"}, False


def _request_body(merged: dict) -> dict | None:
    """Bentuk `request_body_json` dari `requestBody` OpenAPI atau Swagger 2.0.

    Harness menuntut operasi write/delete punya `request_body_json`; tanpa itu
    action-nya tidak lengkap. Dua bentuk harus ditangani karena APIs.guru
    memuat campuran OpenAPI 3.x dan Swagger 2.0:

    * OpenAPI 3.x -> `requestBody.content["application/json"].schema`
    * Swagger 2.0 -> `parameters` dengan `in: body` lalu `schema`
    """
    # --- OpenAPI 3.x ---
    rb = merged.get("requestBody")
    if isinstance(rb, dict):
        content = rb.get("content")
        if isinstance(content, dict):
            for mime in ("application/json", "application/vnd.api+json"):
                media = content.get(mime)
                if isinstance(media, dict):
                    schema = media.get("schema")
                    if isinstance(schema, dict):
                        props = schema.get("properties")
                        if isinstance(props, dict):
                            return {str(k): "" for k in props}
                    return {}
            if content:
                return {}
        return None

    # --- Swagger 2.0: parameter body ---
    params = merged.get("parameters")
    if isinstance(params, dict):
        body_p = params.get("__body__")
        if isinstance(body_p, dict):
            schema = body_p.get("schema")
            if isinstance(schema, dict):
                props = schema.get("properties")
                if isinstance(props, dict):
                    return {str(k): "" for k in props}
            return {}
        for p in params.values():
            if isinstance(p, dict) and p.get("in") == "body":
                schema = p.get("schema")
                if isinstance(schema, dict):
                    props = schema.get("properties")
                    if isinstance(props, dict):
                        return {str(k): "" for k in props}
                return {}
    elif isinstance(params, list):
        for p in params:
            if isinstance(p, dict) and p.get("in") == "body":
                schema = p.get("schema")
                if isinstance(schema, dict):
                    props = schema.get("properties")
                    if isinstance(props, dict):
                        return {str(k): "" for k in props}
                return {}
    return None


def _action_from_operation(spec: dict, path: str, method: str, op: dict,
                           base: str, auth_type: str,
                           seen_ids: set[str]) -> tuple[dict | None, str]:
    """Ubah satu operasi OpenAPI menjadi action manifest. (action, alasan)."""
    if not isinstance(op, dict):
        return None, "operasi bukan objek"
    if method.lower() not in _METHOD_MAP:
        return None, f"method '{method}' tidak didukung"
    if op.get("deprecated") is True:
        return None, "operasi deprecated"

    # Parameter path harus punya nilai yang bisa diisi.
    node = _deref(spec, op)
    # `parameters` di sini adalah hasil `_collect_parameters()`: dict
    # {nama: definisi}. Sebelumnya kode memperlakukannya sebagai list, sehingga
    # setiap operasi ber-parameter-path selalu dibuang. Dukung keduanya supaya
    # fungsi ini tetap benar bila dipanggil langsung dengan list mentah.
    raw_params = node.get("parameters")
    if isinstance(raw_params, dict):
        params: dict = raw_params
    else:
        params = {}
        for it in (raw_params or []):
            d = _deref(spec, it)
            if isinstance(d, dict) and d.get("in") == "path" and d.get("name"):
                params[str(d["name"])] = d

    for name in re.findall(r"\{([^}]+)\}", path):
        if name not in params:
            return None, f"parameter path '{name}' tanpa definisi"

    # Bangun path terisi dari contoh.
    filled = path
    missing: list[str] = []
    for name in re.findall(r"\{([^}]+)\}", path):
        meta = params.get(name)
        if not isinstance(meta, dict) or not _has_example(meta):
            missing.append(name)
            continue
        val = meta.get("example", meta.get("default"))
        if val is None and isinstance(meta.get("enum"), list):
            val = meta["enum"][0]
        filled = filled.replace("{" + name + "}", str(val))
    if missing:
        return None, f"parameter path tanpa contoh: {', '.join(missing)}"

    opid = str(op.get("operationId") or "").strip()
    name = _slugify(opid or f"{method}_{path.strip('/')}")
    # path terlalu dalam -> bukan satu tool yang masuk akal
    if len([s for s in path.split("/") if s]) > MAX_PATH_SEGMENTS:
        return None, "path terlalu dalam"
    if name in seen_ids:
        return None, f"nama action duplikat: {name}"
    seen_ids.add(name)

    summary = str(op.get("summary") or op.get("description") or "").strip()
    if not summary:
        return None, "tanpa summary/description"
    summary = re.sub(r"\s+", " ", summary)[:300]

    operation_type = _METHOD_MAP[method.lower()]
    action: dict[str, Any] = {
        "name": name,
        "description": summary,
        "operation_type": operation_type,
        "method": method.upper(),
        "url_base": base,
        "path": filled,
        "record_selector": {"type": "DpathExtractor", "field_path": ["*"]},
        "paginator": "NoPagination",
        "error_handler": {
            "type": "DefaultErrorHandler",
            "retry": {"type": "ExponentialBackoffStrategy", "max_retries": 3},
        },
        # Generator TIDAK PERNAH mengklaim sudah diverifikasi.
        "verification": {"level": "listed"},
    }

    # Operasi write/delete WAJIB punya body yang BERISI.
    #
    # Harness memakai `not a.get("request_body_json")`, dan `{}` adalah falsy di
    # Python — jadi body kosong tetap dianggap "tanpa body". Aturan itu benar:
    # operasi tulis tanpa satu pun field bukan tool yang dapat dipakai.
    #
    # Karena kita dilarang mengarang field yang tidak ada di spesifikasi,
    # operasi semacam ini DIBUANG, bukan diberi body palsu. Pola yang paling
    # sering: POST yang sebenarnya *membaca* (mis. pencarian) — itu memang
    # bukan write, dan lebih jujur untuk tidak mengklaimnya sebagai write.
    if operation_type in ("write", "delete"):
        body = _request_body(node) or {}
        if not body:
            seen_ids.discard(name)
            return None, "operasi write/delete tanpa body yang berisi"
        action["request_body_json"] = body

    return action, ""


def _collect_parameters(spec: dict, path_node: dict, op: dict) -> dict[str, dict]:
    """Gabungkan parameter level-path dan level-operasi (op menang).

    Termasuk parameter `in: body` (Swagger 2.0) supaya `_request_body()` dapat
    menemukan bentuk body-nya. Sebelumnya hanya parameter `in: path` yang
    dikumpulkan, sehingga operasi write pada spesifikasi Swagger 2.0 kehilangan
    `request_body_json` dan gagal test `action_complete`.
    """
    out: dict[str, dict] = {}

    def add(items: Any) -> None:
        if not isinstance(items, list):
            return
        for it in items:
            d = _deref(spec, it)
            if not isinstance(d, dict):
                continue
            loc = str(d.get("in") or "")
            nm = d.get("name")
            if loc == "path" and nm:
                out[str(nm)] = d
            elif loc == "body":
                # disimpan dengan kunci khusus agar tidak bentrok
                out["__body__"] = d

    add(path_node.get("parameters"))
    add(op.get("parameters"))
    return out


def build_manifest(spec: dict, api_name: str) -> tuple[dict | None, list[str], int]:
    """Bangun dict manifest dari satu spesifikasi OpenAPI.

    Mengembalikan (manifest, errors, skipped_operations).
    """
    errors: list[str] = []
    if not isinstance(spec, dict):
        return None, ["spesifikasi bukan objek"], 0

    info = spec.get("info") or {}
    title = str(info.get("title") or api_name).strip() or api_name
    version = str(info.get("version") or "1.0.0").strip() or "1.0.0"

    base, why = _pick_server(spec)
    if not base:
        return None, [why], 0

    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        return None, ["spesifikasi tanpa paths"], 0

    auth, credential_free = _auth_for(spec, {})
    slug = _slugify(api_name.replace(".", "_"))

    actions: list[dict] = []
    seen: set[str] = set()
    skipped = 0

    for path, path_node in sorted(paths.items()):
        if not isinstance(path_node, dict) or not path.startswith("/"):
            continue
        for method, op in sorted(path_node.items()):
            if method.lower() not in _METHOD_MAP:
                continue
            if not isinstance(op, dict):
                continue
            merged = dict(op)
            merged["parameters"] = _collect_parameters(spec, path_node, op)
            a, reason = _action_from_operation(
                spec, path, method, merged, base, auth["type"], seen)
            if a is None:
                skipped += 1
                continue
            # auth per-operasi: operasi credential-free di dalam API ber-auth
            # tetap boleh, tapi connector-nya tetap butuh auth.
            actions.append(a)

    if not actions:
        return None, ["tidak ada operasi yang dapat diubah menjadi action"], skipped

    actions = actions[:MAX_ACTIONS]

    manifest = {
        "manifest_version": 1,
        "id": f"apisguru.{slug}",
        "slug": f"apisguru_{slug}",
        "display_name": f"{title} (APIs.guru)"[:120],
        "description": (f"Connector dihasilkan otomatis dari spesifikasi OpenAPI "
                        f"publik {title} v{version}. Sumber: APIs.guru "
                        f"openapi-directory.")[:600],
        "category": "apisguru",
        "source": "apisguru",
        "tenant_scope": "public" if credential_free else "per-user",
        "deprecated": False,
        "minimum_supported_release": "1.0.0",
        "credential_free": bool(credential_free),
        "auth": auth,
        "actions": actions,
        "rate_limit": {"type": "FixedWindowCallRatePolicy",
                       "max_calls": 60, "window_seconds": 60},
    }
    return manifest, errors, skipped


def generate_one(spec: dict, api_name: str) -> GenResult:
    """Buat manifest + validasi dengan skema `connector_manifest`."""
    slug = _slugify(api_name.replace(".", "_"))
    title = str(((spec or {}).get("info") or {}).get("title") or api_name)
    try:
        manifest, errors, skipped = build_manifest(spec, api_name)
    except Exception as exc:  # noqa: BLE001 - satu spesifikasi rusak tidak
        return GenResult(api_name, title, slug, False,      # boleh menghentikan
                         reason=f"exception: {type(exc).__name__}: {exc}")
    if manifest is None:
        return GenResult(api_name, title, slug, False,
                         reason=errors[0] if errors else "tidak dapat dibuat",
                         skipped_operations=skipped)

    schema_errors = validate_manifest(manifest)
    if schema_errors:
        return GenResult(api_name, title, slug, False,
                         reason="manifest tidak lolos skema",
                         errors=schema_errors[:8],
                         skipped_operations=skipped)

    return GenResult(api_name, title, slug, True, reason="",
                     actions=len(manifest["actions"]),
                     credential_free=bool(manifest["credential_free"]),
                     skipped_operations=skipped)


def to_yaml(manifest: dict) -> str:
    header = (
        "# Dihasilkan otomatis oleh apisguru_generator.py (TASK 3).\n"
        "# Sumber: APIs.guru openapi-directory.\n"
        "# verification.level = 'listed': BELUM dijalankan. Tingkat 'callable'/\n"
        "# 'call_verified' hanya diberikan harness setelah panggilan nyata.\n"
    )
    return header + yaml.safe_dump(manifest, sort_keys=False,
                                   allow_unicode=True, width=100)


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def plan_batch(directory: dict, *, limit: int = 150,
               prefer_credential_free: bool = True) -> list[str]:
    """Pilih `limit` API yang layak, diutamakan yang tanpa auth.

    Tanpa mengunduh: urutan ini hanya memakai metadata direktori. Yang
    credential-free diutamakan karena connector itulah yang dapat dibuktikan
    sampai `call_verified`.
    """
    eligible = [name for name, entry in directory.items()
                if spec_is_eligible(entry)[0]]

    def rank(name: str) -> tuple[int, str]:
        entry = directory[name]
        _, ver = preferred_spec(entry) or (None, {})
        sec = bool(ver.get("security"))
        # 0 = tanpa auth (paling berguna), 1 = ber-auth
        return (1 if sec else 0) if prefer_credential_free else (0, name)

    eligible.sort(key=lambda n: (rank(n) if prefer_credential_free else 0, n))
    return eligible[:limit]

def generate_batch(specs: Iterable[tuple[str, dict]], *,
                   out_dir: Path | str = DEFAULT_OUT,
                   write: bool = True) -> list[GenResult]:
    """Hasilkan manifest untuk sekumpulan (nama, spesifikasi)."""
    out = Path(out_dir)
    if write:
        out.mkdir(parents=True, exist_ok=True)
    results: list[GenResult] = []
    for name, spec in specs:
        r = generate_one(spec, name)
        if r.ok and write:
            p = out / f"{r.slug}.yaml"
            p.write_text(to_yaml(build_manifest(spec, name)[0]),
                         encoding="utf-8")
            r.manifest_path = str(p)
        results.append(r)
    return results


def summarize(results: list[GenResult]) -> dict[str, Any]:
    ok = [r for r in results if r.ok]
    return {
        "total": len(results),
        "ok": len(ok),
        "failed": len(results) - len(ok),
        "actions_total": sum(r.actions for r in ok),
        "credential_free": sum(1 for r in ok if r.credential_free),
        "skipped_operations": sum(r.skipped_operations for r in results),
        "reasons": _reason_hist([r.reason for r in results if not r.ok]),
    }


def _reason_hist(reasons: list[str]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for r in reasons:
        key = re.sub(r":.*$", "", str(r))[:80]
        hist[key] = hist.get(key, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: -kv[1]))


def verify_batch(results: list[GenResult], *, timeout: float = 8.0
                 ) -> tuple[list[GenResult], list[GenResult]]:
    """Pisahkan manifest yang host-nya hidup dari yang menunjuk host mati.

    APIs.guru memuat spesifikasi yang menunjuk sandbox host yang sudah
    dihentikan (mis. `test.api.amadeus.com` sudah tidak resolve). Manifest
    semacam itu lolos skema tetapi akan gagal saat dipanggil, jadi ia HARUS
    dipisahkan — bukan dihitung sebagai connector yang dapat dieksekusi.

    Mengembalikan (hidup, mati). Urutan hasil dipertahankan.
    """
    import socket
    from pathlib import Path

    alive: list[GenResult] = []
    dead: list[GenResult] = []
    cache: dict[str, bool] = {}

    for r in results:
        if not r.ok or not r.manifest_path:
            continue
        try:
            data = yaml.safe_load(Path(r.manifest_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dead.append(r)
            continue
        host = ""
        for a in (data.get("actions") or []):
            u = str((a or {}).get("url_base") or "")
            host = urlparse(u).hostname or ""
            if host:
                break
        if not host:
            dead.append(r)
            continue
        if host not in cache:
            try:
                socket.getaddrinfo(host, None)
                cache[host] = True
            except Exception:  # noqa: BLE001 - tidak dapat dipastikan -> mati
                cache[host] = False
        (alive if cache[host] else dead).append(r)
    return alive, dead

