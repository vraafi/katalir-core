"""Fitur #8 — MCP Server Built-in (Katalir sebagai MCP server).

MASALAH YANG DISELESAIKAN
-------------------------
Sebelum fitur ini Katalir hanya menjadi MCP **client** (`mcp_gateway/`,
`mcp_registry.py`) dan punya dua permukaan MCP yang **tidak lengkap / tidak
standar**:

  1. `mcp_gateway/katalir_server.py` — hanya 2 tool (`list_workflows`,
     `run_workflow`), transport stdio, dan **mengimpor `api_server`** sehingga
     hanya bisa jalan sebagai proses terpisah. Tidak bisa dipanggil lewat HTTP
     oleh Claude Desktop / Cursor / agent apa pun di cloud.
  2. `GET /mcp/server/tools` + `POST /mcp/server/call` — permukaan HTTP biasa
     yang meniru MCP secara manual. **Bukan protokol MCP**: tidak ada
     `initialize`, tidak ada `tools/list` JSON-RPC, tidak ada
     `Mcp-Session-Id`, tidak ada SSE framing. Klien MCP asli tidak bisa
     menyambung.

Akibatnya Katalir **tidak bisa dipakai sebagai server MCP** oleh klien nyata.
Fitur ini menambahkan permukaan MCP **asli** di `/mcp/katalir`.

DESAIN
------
* **Stateless HTTP** (`stateless_http=True`). Railway menjalankan >1 instance
  dan tidak ada sticky session; stateful session akan gagal begitu request
  berikutnya mendarat di instance lain. Stateless = setiap request mandiri.
* **Auth via API key** (bukan JWT Supabase). Klien MCP tidak bisa melakukan
  alur login Supabase. Kunci adalah JWT HS256 bertanda tangan `VAULT_SECRET_KEY`
  (kunci yang sama dengan `credential_forms`), sehingga **tidak ada tabel baru**
  dan tidak ada state server. `mcp-kir_<payload>.<sig>`.
* **DNS-rebinding protection DIPERTAHANKAN** dengan allowlist host dari
  `ALLOWED_HOSTS`. Mematikannya (`enable_dns_rebinding_protection=False`)
  memang membuat tes lulus, tapi itu **menurunkan keamanan**: proteksi ini
  yang mencegah browser di jaringan lokal dipakai sebagai proxy ke server ini.
  Terbukti di probe: host Railway → 200, host asing → 421.
* **Owner-scoped**: setiap tool memakai `user_id` dari API key, tidak pernah
  dari argumen. Satu kunci tidak bisa menyentuh workflow user lain.
* **Lazy ASGI app**: `api_server` meng-import modul ini, jadi modul ini TIDAK
  boleh meng-import `api_server` balik (siklus impor). Semua akses DB lewat
  `database` dan eksekusi lewat `execution_engine`.

TOOL YANG DIEKSPOS
------------------
  * `create_workflow`      — buat workflow baru (nama, deskripsi, flow_data)
  * `update_workflow`      — ubah nama/deskripsi/flow_data milik sendiri
  * `list_workflows`       — daftar workflow milik pemilik kunci
  * `execute_workflow`     — jalankan workflow → execution_id
  * `get_execution_status` — status + log eksekusi milik sendiri

KOMPATIBILITAS
--------------
Klien MCP yang memakai Streamable HTTP (`streamablehttp_client`):
Claude Desktop (via `mcp-remote`), Cursor, Cline, Continue, dan SDK resmi.
Konfigurasi klien ada di `docs/fitur-08-mcp-server.md`.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import time
from typing import Any

# Awalan kunci sengaja mencolok supaya kunci MCP yang bocor ke log/commit
# langsung terlihat saat pemindaian rahasia (pola `mcp-kir_`).
API_KEY_PREFIX = "mcp-kir_"
API_KEY_DEFAULT_TTL_S = 90 * 24 * 3600  # 90 hari
API_KEY_MIN_TTL_S = 60


class McpAuthError(Exception):
    """Permintaan MCP tanpa API key sah (401)."""


class McpPermissionError(Exception):
    """API key sah tetapi bukan pemilik resource (404, bukan 403 — tidak
    membocorkan keberadaan resource milik user lain)."""


# ---------------------------------------------------------------------------
# Signing key — memakai kunci yang SAMA dengan credential_forms.resume_token
# supaya tidak ada env baru yang harus diisi di produksi. Derivasi domain
# dipisah ("mcp::") sehingga kunci MCP tidak bisa dipakai sebagai resume_token
# dan sebaliknya.
# ---------------------------------------------------------------------------
_EPHEMERAL_KEY: bytes | None = None


def _signing_key() -> bytes:
    global _EPHEMERAL_KEY
    secret = (os.getenv("VAULT_SECRET_KEY") or "").strip()
    if secret:
        return hashlib.sha256(f"mcp::{secret}".encode("utf-8")).digest()
    if _EPHEMERAL_KEY is None:
        _EPHEMERAL_KEY = hashlib.sha256(
            f"mcp-ephemeral::{os.urandom(32).hex()}".encode("utf-8")).digest()
    return _EPHEMERAL_KEY


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------
def issue_api_key(user_id: str, email: str = "", ttl_s: int = API_KEY_DEFAULT_TTL_S,
                  label: str = "") -> str:
    """Terbitkan API key stateless untuk satu user.

    Payload hanya memuat identitas + masa berlaku. Tidak ada rahasia user di
    dalamnya: kunci yang bocor membuka **akses atas nama user itu**, bukan
    membocorkan kredensial vault (vault tetap terenkripsi Fernet terpisah).
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id wajib untuk menerbitkan API key")
    now = int(time.time())
    payload = {
        "u": uid,
        "e": str(email or "").strip().lower(),
        "l": str(label or "")[:40],
        "iat": now,
        "exp": now + max(API_KEY_MIN_TTL_S, int(ttl_s)),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{API_KEY_PREFIX}{body}.{sig}"


def verify_api_key(token: str) -> dict[str, Any]:
    """Verifikasi API key → dict {user_id, email, label, exp}.

    Melempar `McpAuthError` untuk SEMUA kegagalan (rusak / kedaluwarsa /
    tanda tangan salah). Alasannya tidak dibedakan ke pemanggil supaya pesan
    error tidak menjadi oracle untuk memvalidasi dugaan kunci.
    """
    raw = str(token or "").strip()
    if raw.startswith("Bearer "):
        raw = raw[7:].strip()
    if not raw:
        raise McpAuthError("API key MCP wajib (X-API-Key atau Authorization: Bearer).")
    if not raw.startswith(API_KEY_PREFIX):
        raise McpAuthError("API key MCP tidak valid.")
    parts = raw[len(API_KEY_PREFIX):].split(".")
    if len(parts) != 2 or not all(parts):
        raise McpAuthError("API key MCP tidak valid.")
    body, sig = parts
    expect = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    # compare_digest: perbandingan waktu-tetap, supaya tanda tangan tidak bisa
    # ditebak byte demi byte lewat timing.
    if not hmac.compare_digest(sig, expect):
        raise McpAuthError("API key MCP tidak valid.")
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise McpAuthError("API key MCP tidak bisa dibaca.") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise McpAuthError("API key MCP sudah kedaluwarsa. Terbitkan kunci baru.")
    uid = str(payload.get("u") or "").strip()
    if not uid:
        raise McpAuthError("API key MCP tanpa identitas user.")
    return {
        "user_id": uid,
        "email": str(payload.get("e") or "").strip().lower(),
        "label": str(payload.get("l") or ""),
        "exp": int(payload.get("exp") or 0),
    }


# ---------------------------------------------------------------------------
# Flow-data validation (dipakai create_workflow / update_workflow)
# ---------------------------------------------------------------------------
# Sumber kebenaran tunggal (flow_limits.py). Dulu 200 di sini, 500 di API,
# dan 100 di workflow_templates -> workflow 300 node ditolak lewat MCP padahal
# diterima lewat API.
from flow_limits import MAX_FLOW_NODES  # noqa: E402
MAX_FIELD_CHARS = 200_000


def _validate_flow_data(flow_data: Any) -> dict:
    """Validasi flow_data SEBELUM menyentuh DB.

    Kenapa perlu: tanpa ini user bisa menyimpan `{"nodes": "bukan-list"}` atau
    node tanpa `id`, dan kerusakannya baru muncul jauh kemudian di execution
    engine — di mana penyebabnya sudah tidak terlihat. Gagal di sini = pesan
    error yang bisa ditindaklanjuti.
    """
    if flow_data is None:
        return {}
    if not isinstance(flow_data, dict):
        raise ValueError("flow_data harus object JSON")
    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])
    if not isinstance(nodes, list):
        raise ValueError("flow_data.nodes harus list")
    if not isinstance(edges, list):
        raise ValueError("flow_data.edges harus list")
    if len(nodes) > MAX_FLOW_NODES:
        raise ValueError(f"flow_data.nodes melebihi batas {MAX_FLOW_NODES}")
    if len(edges) > MAX_FLOW_NODES * 4:
        raise ValueError("flow_data.edges terlalu banyak")
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            raise ValueError(f"node[{i}] harus object")
        nid = str(n.get("id") or "").strip()
        if not nid:
            raise ValueError(f"node[{i}] tanpa id")
        if nid in ids:
            raise ValueError(f"node id duplikat: {nid}")
        ids.add(nid)
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            raise ValueError(f"edge[{i}] harus object")
        for key in ("source", "target"):
            val = str(e.get(key) or "").strip()
            if not val:
                raise ValueError(f"edge[{i}] tanpa {key}")
            # Edge yang menunjuk node tidak ada = graf rusak; engine akan
            # melewatinya diam-diam dan user melihat "workflow selesai" tanpa
            # satu pun langkah jalan. Tolak lebih awal.
            if ids and val not in ids:
                raise ValueError(f"edge[{i}].{key} menunjuk node tidak ada: {val}")
    if len(json.dumps(flow_data, default=str)) > MAX_FIELD_CHARS:
        raise ValueError(f"flow_data melebihi {MAX_FIELD_CHARS} karakter")
    return flow_data


def _clean_text(value: Any, field: str, *, required: bool = False,
                max_chars: int = 2000) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ValueError(f"{field} wajib diisi")
    if len(text) > max_chars:
        raise ValueError(f"{field} melebihi {max_chars} karakter")
    return text


# ---------------------------------------------------------------------------
# Service layer — dipakai oleh tool MCP DAN oleh endpoint HTTP biasa
# (supaya keduanya punya perilaku identik; tidak ada jalur kedua yang berbeda).
# ---------------------------------------------------------------------------
def svc_create_workflow(user_id: str, name: str = "Draft Workflow",
                        description: str = "", flow_data: Any = None) -> dict:
    import database as db
    uid = _clean_text(user_id, "user_id", required=True)
    nama = _clean_text(name, "name", required=True, max_chars=200)
    desk = _clean_text(description, "description", max_chars=2000)
    flow = _validate_flow_data(flow_data)
    row = db.create_workflow(uid, nama, desk, flow)
    if not row:
        raise RuntimeError("gagal menyimpan workflow")
    return {
        "id": str(row.get("id")),
        "name": str(row.get("name") or nama),
        "description": str(row.get("description") or desk),
        "node_count": len((flow or {}).get("nodes") or []),
    }


def svc_update_workflow(user_id: str, workflow_id: str, name: str | None = None,
                        description: str | None = None,
                        flow_data: Any = None) -> dict:
    import database as db
    uid = _clean_text(user_id, "user_id", required=True)
    wid = _clean_text(workflow_id, "workflow_id", required=True)
    owner = db.get_workflow_owner(wid)
    if owner is None or str(owner) != uid:
        raise McpPermissionError("Workflow tidak ditemukan.")
    flow = _validate_flow_data(flow_data) if flow_data is not None else None
    row = db.update_workflow(
        wid, uid,
        name=_clean_text(name, "name", max_chars=200) if name is not None else None,
        description=_clean_text(description, "description", max_chars=2000) if description is not None else None,
        flow_data=flow,
    )
    if not row:
        raise McpPermissionError("Workflow tidak ditemukan.")
    return {
        "id": str(row.get("id") or wid),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "updated": True,
    }


def svc_list_workflows(user_id: str, limit: int = 50) -> dict:
    import database as db
    uid = _clean_text(user_id, "user_id", required=True)
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 50
    n = max(1, min(200, n))
    rows = db.list_workflows(uid) or []
    items = [
        {
            "id": str(r.get("id")),
            "name": str(r.get("name") or ""),
            "description": str(r.get("description") or ""),
            "created_at": str(r.get("created_at") or ""),
        }
        for r in rows[:n]
    ]
    return {"workflows": items, "count": len(items), "total": len(rows)}


def svc_execute_workflow(user_id: str, workflow_id: str,
                         input_data: Any = None) -> dict:
    import database as db
    import execution_engine as engine
    uid = _clean_text(user_id, "user_id", required=True)
    wid = _clean_text(workflow_id, "workflow_id", required=True)
    detail = db.get_workflow(wid, uid)
    if not detail:
        # 404, bukan 403: tidak membocorkan bahwa workflow itu ada.
        raise McpPermissionError("Workflow tidak ditemukan.")
    flow_data = detail.get("flow_data") or {}
    if not isinstance(flow_data, dict) or not (flow_data.get("nodes") or []):
        raise ValueError("Workflow tidak punya node untuk dijalankan.")
    trig = input_data if isinstance(input_data, dict) else None
    execution_id = engine.launch_execution(
        wid, flow_data, trigger_input=trig,
        owner_email=str(_user_email(uid) or ""))
    return {"execution_id": str(execution_id), "workflow_id": wid, "status": "pending"}


def _user_email(user_id: str) -> str:
    """Email pemilik dari DB (dipakai node MCP agar kredensial user terbaca).

    Best-effort: kegagalan di sini TIDAK boleh menggagalkan eksekusi — node
    yang butuh kredensial akan melaporkan sendiri bahwa kredensial tidak ada.
    """
    try:
        import database as db
        res = db._get_write_client().table("users").select("email").eq(
            "id", user_id).limit(1).execute()
        rows = getattr(res, "data", None) or []
        if rows:
            return str(rows[0].get("email") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def svc_get_execution_status(user_id: str, execution_id: str) -> dict:
    import database as db
    uid = _clean_text(user_id, "user_id", required=True)
    eid = _clean_text(execution_id, "execution_id", required=True)
    data = db.get_execution(eid)
    ex = (data or {}).get("execution")
    if not ex:
        raise McpPermissionError("Eksekusi tidak ditemukan.")
    wid = str(ex.get("workflow_id") or "")
    owner = db.get_workflow_owner(wid) if wid else None
    if owner is None or str(owner) != uid:
        raise McpPermissionError("Eksekusi tidak ditemukan.")
    logs = (data or {}).get("logs") or []
    steps = [
        {
            "node_id": str((lg or {}).get("node_id") or ""),
            "node_type": str((lg or {}).get("node_type") or ""),
            "status": str((lg or {}).get("status") or ""),
            "ts": str((lg or {}).get("ts") or ""),
            "error": str((lg or {}).get("error_message") or ""),
        }
        for lg in logs
    ]
    return {
        "execution_id": eid,
        "workflow_id": wid,
        "status": str(ex.get("status") or "unknown"),
        "created_at": str(ex.get("created_at") or ""),
        "steps": steps,
        "step_count": len(steps),
    }


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------
SERVER_NAME = "katalir"
STREAMABLE_PATH = "/mcp"

#: Context ulang ditulis kembali dari header `X-API-Key` di setiap request.
#: `FastMCP` mengeksekusi tool secara sinkron di thread pool; menyimpan
#: identitas di ContextVar adalah cara paling andal agar tool yang berjalan di
#: thread lain tetap melihat kunci milik request yang benar. Karena setiap
#: request MCP stateless memuat kunci sendiri, tidak ada kebocoran lintas
#: request: nilai di-set pada awal request dan di-reset di `finally`.
import contextvars  # noqa: E402  (diletakkan dekat pemakaian agar jelas)

_current_key: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "katalir_mcp_key", default=None)


def current_key() -> dict:
    info = _current_key.get()
    if not info:
        raise McpAuthError("API key MCP tidak terpasang pada request ini.")
    return info


def _tool_auth_error(exc: Exception) -> ValueError:
    return ValueError(f"[401] {exc}")


def build_server():
    """Bangun FastMCP + daftarkan kelima tool.

    Dipisah dari pembuatan ASGI app supaya tes bisa memeriksa daftar tool
    tanpa menyalakan server.
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = FastMCP(
        SERVER_NAME,
        instructions=(
            "Katalir — platform otomasi workflow. Tool di sini mengelola "
            "workflow MILIK pemilik API key: buat, ubah, daftar, jalankan, "
            "dan periksa status eksekusi. Semua operasi terbatas pada akun "
            "pemilik kunci."
        ),
        stateless_http=True,
        streamable_http_path=STREAMABLE_PATH,
        transport_security=_transport_security(),
    )

    @mcp.tool()
    def create_workflow(name: str, description: str = "",
                        flow_data: dict | None = None) -> dict:
        """Buat workflow Katalir baru milik pemilik API key.

        Args:
            name: Nama workflow.
            description: Deskripsi singkat (opsional).
            flow_data: Graf workflow `{"nodes": [...], "edges": [...]}`
                (opsional). Node wajib punya `id`; edge wajib punya
                `source`/`target` yang menunjuk node yang ada.

        Returns:
            `{id, name, description, node_count}`.
        """
        return svc_create_workflow(current_key()["user_id"], name, description, flow_data)

    @mcp.tool()
    def update_workflow(workflow_id: str, name: str | None = None,
                        description: str | None = None,
                        flow_data: dict | None = None) -> dict:
        """Ubah workflow yang SUDAH ada dan milik pemilik API key.

        Args:
            workflow_id: ID workflow.
            name: Nama baru (opsional).
            description: Deskripsi baru (opsional).
            flow_data: Graf baru (opsional).

        Returns:
            `{id, name, description, updated}`.
        """
        return svc_update_workflow(current_key()["user_id"], workflow_id,
                                   name, description, flow_data)

    @mcp.tool()
    def list_workflows(limit: int = 50) -> dict:
        """Daftar workflow milik pemilik API key (terbaru dulu).

        Args:
            limit: Jumlah maksimum (1–200, default 50).

        Returns:
            `{workflows: [{id, name, description, created_at}], count, total}`.
        """
        return svc_list_workflows(current_key()["user_id"], limit)

    @mcp.tool()
    def execute_workflow(workflow_id: str, input_data: dict | None = None) -> dict:
        """Jalankan workflow milik pemilik API key. Non-blocking.

        Args:
            workflow_id: ID workflow yang akan dijalankan.
            input_data: Payload trigger (opsional).

        Returns:
            `{execution_id, workflow_id, status}` — status awal `pending`.
            Pantau dengan `get_execution_status`.
        """
        return svc_execute_workflow(current_key()["user_id"], workflow_id, input_data)

    @mcp.tool()
    def get_execution_status(execution_id: str) -> dict:
        """Status + log langkah dari satu eksekusi milik pemilik API key.

        Args:
            execution_id: ID eksekusi dari `execute_workflow`.

        Returns:
            `{execution_id, workflow_id, status, created_at, steps, step_count}`.
        """
        return svc_get_execution_status(current_key()["user_id"], execution_id)

    return mcp


def _transport_security():
    """Proteksi DNS-rebinding DENGAN allowlist host (bukan dimatikan).

    Temuan penting: `FastMCP` default hanya mengizinkan `127.0.0.1`/`localhost`.
    Di Railway Host header = domain Railway, sehingga **setiap** request kena
    `421 Misdirected Request`. Mematikan proteksi (`False`) memang "bisa jalan"
    tapi membuang pertahanan terhadap DNS-rebinding — browser korban di jaringan
    lokal bisa dipakai memanggil server ini. Jadi: tetap aktif, host diambil
    dari `ALLOWED_HOSTS` (env yang sudah wajib diisi untuk TrustedHostMiddleware).

    Format `allowed_hosts` MCP memakai wildcard port `host:*`, sedangkan
    `ALLOWED_HOSTS` berisi host polos — jadi keduanya didaftarkan.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    allowed: list[str] = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]
    raw = (os.getenv("ALLOWED_HOSTS") or "").strip()
    for host in (h.strip() for h in raw.split(",")):
        if not host or host == "*":
            continue
        # `*.example.com` → `example.com` + `*.example.com` (format MCP
        # membandingkan host mentah, jadi wildcard subdomain didaftarkan apa
        # adanya juga).
        base = host[2:] if host.startswith("*.") else host
        for candidate in (base, f"{base}:*", host):
            if candidate not in allowed:
                allowed.append(candidate)
    origins = [f"https://{h}" for h in allowed if "*" not in h and h not in ("127.0.0.1", "localhost")]
    origins += ["https://127.0.0.1", "https://localhost"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed,
        allowed_origins=origins,
    )


# ---------------------------------------------------------------------------
# ASGI wrapper — auth + lifespan
# ---------------------------------------------------------------------------
#: Instance `FastMCP` proses-wide. Satu instance = satu `session_manager`, dan
#: manager itu hanya boleh `run()` SEKALI. Karena itu server di-cache, dan
#: `api_server` menyalakan manager-nya lewat `session_manager_lifespan()`
#: yang mengikat ke instance ini.
_MCP_SINGLETON = None


def get_server():
    global _MCP_SINGLETON
    if _MCP_SINGLETON is None:
        _MCP_SINGLETON = build_server()
    return _MCP_SINGLETON


def reset_server() -> None:
    """Buang instance server (dipakai test yang butuh siklus hidup baru).

    Tanpa ini, test kedua dalam satu proses mewarisi manager yang sudah
    di-`run()` dan gagal `can only be called once per instance`.
    """
    global _MCP_SINGLETON
    _MCP_SINGLETON = None


def _extract_api_key(raw_headers) -> str:
    """Ambil kunci dari `X-API-Key` dulu, lalu `Authorization: Bearer`.

    `scope["headers"]` di ASGI adalah **list pasangan bytes** (`[(b'x-api-key',
    b'...')]`), BUKAN dict — `.get()` pada objek itu melempar AttributeError dan
    setiap request MCP gagal 500. Header juga case-insensitive menurut spec,
    sementara Starlette meneruskan apa adanya, jadi pencocokan nama header
    dilakukan dalam lowercase.
    """
    headers: dict[str, str] = {}
    for pair in raw_headers or []:
        try:
            name, value = pair
        except (TypeError, ValueError):
            continue
        if isinstance(name, (bytes, bytearray)):
            name = name.decode("latin-1")
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("latin-1")
        headers[str(name).strip().lower()] = str(value).strip()

    key = headers.get("x-api-key") or ""
    if not key:
        auth = headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            key = auth[7:]
    return key.strip()


class McpAuthMiddleware:
    """ASGI middleware: verifikasi API key, lalu jalankan app MCP.

    Auth ditegakkan DI SINI, bukan di dalam tool, karena:
      * `initialize`/`tools/list` juga harus ditolak tanpa kunci — kalau tidak,
        daftar tool Katalir bisa dienumerasi tanpa autentikasi;
      * satu tempat = tidak mungkin ada tool baru yang lupa memeriksa.
    Tool tetap menerima identitas lewat ContextVar yang di-set di sini.
    """

    def __init__(self, app, *, require_auth: bool = True):
        self.app = app
        self.require_auth = require_auth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.responses import JSONResponse

        if self.require_auth:
            try:
                key = _extract_api_key(scope.get("headers") or [])
                info = verify_api_key(key)
            except McpAuthError as exc:
                body = JSONResponse(
                    {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32001, "message": str(exc)}},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="katalir-mcp"'},
                )
                await body(scope, receive, send)
                return
            token = _current_key.set(info)
        else:
            token = None
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                _current_key.reset(token)


class _BarePathShim:
    """Samakan path root mount dengan bentuk yang dipakai routing internal.

    TEMUAN NYATA (ditemukan lewat probe, bukan dugaan):

    1. `app.mount("/mcp/katalir", sub)` membalas **307 Temporary Redirect**
       untuk `POST /mcp/katalir` (tanpa garis miring) → `/mcp/katalir/`.
       Klien MCP **tidak mengikuti redirect POST** (body JSON-RPC hilang), jadi
       URL tanpa garis miring tampak "mati". Itu diperbaiki di `api_server`
       dengan route eksplisit yang didaftarkan sebelum mount.
    2. Karena route eksplisit itu, sub-app menerima path **lengkap**
       (`/mcp/katalir`, `root_path=""`), sedangkan lewat jalur mount ia
       menerima path **relatif** (`/`, `root_path="/mcp/katalir"`).
       Routing internal `FastMCP` hanya mengenali `streamable_http_path`
       (`/mcp`) plus `root_path`-nya. Dua bentuk masukan itu menghasilkan
       satu 404 dan satu 200 — perilaku yang sama sekali tidak konsisten.

    Shim ini menormalkan KE DUA bentuk menjadi path yang dikenali routing
    internal, sehingga `/mcp/katalir` dan `/mcp/katalir/` berperilaku identik.
    """

    def __init__(self, app, *, prefix: str):
        self.app = app
        self.prefix = "/" + prefix.strip("/")

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path.rstrip("/") == self.prefix:
                scope = dict(scope)
                inner = getattr(get_server().settings, "streamable_http_path", "/mcp") or "/mcp"
                if not inner.startswith("/"):
                    inner = "/" + inner
                scope["path"] = inner
                scope["raw_path"] = inner.encode("ascii")
                # root_path dikosongkan: routing internal membandingkan path
                # mentah, jadi menyisakan prefix akan menggandakan segmennya.
                scope["root_path"] = ""
        await self.app(scope, receive, send)


def get_asgi_application(*, require_auth: bool = True, mount_prefix: str = "/mcp/katalir",
                         server=None):
    """ASGI app MCP (stateless) + auth middleware + shim path.

    `server` boleh diberikan agar app di-bind ke instance `FastMCP` tertentu.
    Itu penting untuk **restart dalam satu proses**: `FastMCP` memakai
    `streamable_http_app()` yang membuat satu `StreamableHTTPSessionManager`,
    dan manager itu menolak `run()` kedua kali dengan
    `RuntimeError: StreamableHTTPSessionManager .run() can only be called once
    per instance`. Kalau app meng-cache manager lama, restart (atau test kedua
    dalam proses yang sama) berakhir dengan **setiap** request MCP 500.

    Tanpa `server`, instance global dari `get_server()` dipakai.
    """
    mcp = server if server is not None else get_server()
    inner = mcp.streamable_http_app()
    authed = McpAuthMiddleware(inner, require_auth=require_auth)
    return _BarePathShim(authed, prefix=mount_prefix)


@contextlib.asynccontextmanager
async def session_manager_lifespan(mcp=None):
    """Nyalakan `session_manager.run()` untuk SATU siklus hidup.

    Dipisah dari `get_asgi_application` supaya pemanggil bisa menyalakan
    manager yang benar-benar terikat ke app yang di-mount, dan supaya
    dimatikan dengan aman (tanpa menahan proses saat shutdown).
    """
    srv = mcp if mcp is not None else get_server()
    ctx = srv.session_manager.run()
    await ctx.__aenter__()
    try:
        yield srv
    finally:
        with contextlib.suppress(Exception):
            await ctx.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Metadata untuk UI/dokumentasi
# ---------------------------------------------------------------------------
def describe() -> dict:
    """Ringkasan permukaan MCP untuk `/mcp/katalir/info` dan UI."""
    return {
        "server": SERVER_NAME,
        "protocol": "mcp",
        "protocol_version": "2025-06-18",
        "transport": "streamable-http",
        "endpoint": STREAMABLE_PATH,
        "stateless": True,
        "auth": {
            "type": "api_key",
            "header": "X-API-Key",
            "alternate": "Authorization: Bearer <key>",
            "prefix": API_KEY_PREFIX,
            "issue_endpoint": "/mcp/katalir/key",
        },
        "dns_rebinding_protection": True,
        "allowed_hosts": list(getattr(_transport_security(), "allowed_hosts", [])),
        "tools": [
            {"name": "create_workflow", "args": ["name", "description", "flow_data"]},
            {"name": "update_workflow", "args": ["workflow_id", "name", "description", "flow_data"]},
            {"name": "list_workflows", "args": ["limit"]},
            {"name": "execute_workflow", "args": ["workflow_id", "input_data"]},
            {"name": "get_execution_status", "args": ["execution_id"]},
        ],
        "clients": ["Claude Desktop (mcp-remote)", "Cursor", "Cline", "Continue", "MCP SDK"],
    }


__all__ = [
    "API_KEY_PREFIX", "API_KEY_DEFAULT_TTL_S",
    "McpAuthError", "McpPermissionError",
    "issue_api_key", "verify_api_key",
    "build_server", "get_server", "get_asgi_application", "describe",
    "svc_create_workflow", "svc_update_workflow", "svc_list_workflows",
    "svc_execute_workflow", "svc_get_execution_status",
]
