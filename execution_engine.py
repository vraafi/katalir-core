# execution_engine.py - Execution Engine (Arsitektur Enterprise 2026)
# =============================================================================
# Stateful Orchestrator basado en State Graph (estilo LangGraph pero lightweight,
# Async DAG parser). Cada tipo de nodo (trigger/agent/mcp) se mapea a una
# ejecucion asincrona registrada en un registry (sin if/else manual).
#
# Integracion MCP nativa: tool nodes no se ejecutan con dispatcher manual,
# sino via un protocolo MCP (MCPRegistry) - en esta primera iteracion se usa
# un cliente MCP mock (MockMCPClient) hasta conectar claves reales.
#
# El endpoint POST /workflows/{id}/execute inicia una tarea asincrona en
# background y devuelve {execution_id, status: pending} inmediatamente (non-blocking).
# Los pasos de ejecucion se persisten en execution_logs (Supabase).
# =============================================================================

import asyncio
import ast
import datetime as _datetime
import json
import operator
import os
import re
import uuid
from collections import defaultdict
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from dotenv_loader import load_repo_env

load_repo_env()

from self_healing import SelfHealingAgent
import database as db
# FASE 2.6: node MCP dengan `config.provider` dirutekan ke registry tool native.
import provider_registry


# ---------------------------------------------------------------------------
# SCHEMA TIPADO (Pydantic estricto)
# ---------------------------------------------------------------------------
class NodeKind(str, Enum):
    TRIGGER = "trigger"
    AGENT = "agent"
    MCP = "mcp"


class NodeConfig(BaseModel):
    """Configuracion libre de cada nodo (guardada en flow_data por el builder)."""
    event_name: Optional[str] = None
    system_prompt: Optional[str] = None
    tool_name: Optional[str] = None
    tool_param: Optional[str] = None


class FlowNodeData(BaseModel):
    kind: NodeKind
    label: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class FlowNode(BaseModel):
    id: str
    type: Optional[str] = None  # "trigger" | "agent" | "mcp-tool" (xyflow node.type)
    position: dict[str, float] = Field(default_factory=dict)
    data: FlowNodeData


class FlowEdge(BaseModel):
    id: Optional[str] = None
    source: str
    target: str


class FlowGraph(BaseModel):
    """Modelo normalizado del flow_data {nodes, edges} proveniente de Supabase."""
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)


class ExecutionStep(BaseModel):
    node_id: str
    kind: NodeKind
    status: str  # running | completed | error
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    ts: Optional[str] = None
# ---------------------------------------------------------------------------
# MCP - Model Context Protocol (integracion nativa)
# ---------------------------------------------------------------------------
class MCPTool:
    """Contrato de un tool MCP (protocolo, no implementacion concreta)."""

    def __init__(self, name: str, description: str, fn: Callable[[dict], Awaitable[dict]]):
        self.name = name
        self.description = description
        self._fn = fn

    async def execute(self, params: dict) -> dict:
        return await self._fn(params)


class NativeMCPClient:
    """Klien MCP NATIVE (2026) - eksekusi nyata di internet, bukan simulasi.

    Mengekspos interface protokol yang sama (connect/list_tools/call_tool).
    Tools:
      - web_search    : DDGS().text() -> 3 hasil teratas nyata.
      - http_request  : httpx.AsyncClient() -> GET/POST nyata.
      - read_database : placeholder jelas (butuh kredensial DB user).
      - send_whatsapp : placeholder jelas (butuh token WhatsApp user).
    Semua kegagalan dicatat sebagai payload error (pipeline tidak crash).
    """

    _META: dict[str, str] = {
        "web_search": "Pencarian web nyata via DuckDuckGo",
        "http_request": "HTTP GET/POST nyata via httpx",
        "read_database": "Baca database user (butuh kredensial integrasi)",
        "send_whatsapp": "Kirim WhatsApp (butuh token integrasi)",
    }

    async def connect(self) -> None:
        await asyncio.sleep(0)  # handshake non-blocking (tanpa koneksi tetap)

    async def list_tools(self) -> list[dict]:
        return [{"name": n, "description": d} for n, d in self._META.items()]

    async def _web_search(self, query: str, max_results: int = 3) -> dict:
        try:
            from ddgs import DDGS
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "tool": "web_search",
                    "error": f"ddgs belum terinstal: {exc}"}
        try:
            def _run() -> list[dict]:
                out: list[dict] = []
                for r in DDGS().text(str(query), max_results=max_results):
                    out.append({
                        "title": r.get("title", ""),
                        "href": r.get("href", ""),
                        "body": (r.get("body", "") or "")[:400],
                    })
                return out
            results = await asyncio.to_thread(_run)
            return {"status": "success", "tool": "web_search",
                    "query": str(query), "count": len(results),
                    "results": results}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "tool": "web_search",
                    "query": str(query),
                    "error": f"[{type(exc).__name__}] {exc}"}

    async def _http_request(self, url: str, method: str = "GET",
                            body: Any = None, timeout: float = 20.0) -> dict:
        try:
            import httpx
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "tool": "http_request",
                    "error": f"httpx belum terinstal: {exc}"}
        method = (method or "GET").upper()
        try:
            async with httpx.AsyncClient(timeout=timeout,
                                         follow_redirects=True) as client:
                if method == "POST":
                    resp = await client.post(url, json=body)
                elif method == "PUT":
                    resp = await client.put(url, json=body)
                elif method == "DELETE":
                    resp = await client.delete(url)
                else:
                    resp = await client.get(url)
            text = resp.text or ""
            return {"status": "success" if resp.status_code < 400 else "error",
                    "tool": "http_request", "url": url, "method": method,
                    "http_status": resp.status_code,
                    "content_type": resp.headers.get("content-type", ""),
                    "body": text[:4000]}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "tool": "http_request", "url": url,
                    "method": method,
                    "error": f"[{type(exc).__name__}] {exc}"}

    async def call_tool(self, name: str, arguments: dict) -> dict:
        args = arguments or {}
        if name == "web_search":
            q = args.get("query") or args.get("q") or args.get("text") or ""
            if not q:
                return {"status": "error", "tool": name,
                        "error": "query pencarian kosong"}
            n = args.get("max_results", 3)
            try:
                n = max(1, min(10, int(n)))
            except Exception:  # noqa: BLE001
                n = 3
            return await self._web_search(str(q), n)
        if name == "http_request":
            url = args.get("url") or args.get("href") or ""
            if not url:
                return {"status": "error", "tool": name,
                        "error": "url target kosong"}
            return await self._http_request(
                str(url), str(args.get("method", "GET")),
                args.get("body"),
                float(args.get("timeout", 20.0) or 20.0))
        if name in ("read_database", "send_whatsapp"):
            need = "database" if name == "read_database" else "whatsapp"
            return {"status": "error", "tool": name,
                    "needs_credential": need,
                    "error": f"Tool '{name}' membutuhkan kredensial "
                             f"integrasi '{need}' (simpan via /integrations)."}
        raise KeyError(f"MCP tool '{name}' tidak terdaftar")


class MCPRegistry:
    """Registro de tools via protocolo MCP. Los tool nodes se invocan aqui.

    En lugar de if/else, cada herramienta es un MCPTool del catalogo expuesto
    por el cliente (list_tools) y se ejecuta por nombre con call_tool.
    """

    def __init__(self, client: Optional[Any] = None):
        self._client = client or self._build_client()

    @staticmethod
    def _build_client():
        # Native executor nyata (2026). Fallback ke SDK hanya jika dipaksa
        # eksplisit via MCP_SDK=1 dan modul tersedia.
        if os.getenv("MCP_SDK", "").strip() == "1":
            try:
                import mcp  # noqa: F401
                return _SdkMCPClient()
            except Exception:
                return NativeMCPClient()
        return NativeMCPClient()

    async def connect(self) -> None:
        await self._client.connect()

    async def catalog(self) -> list[dict]:
        return await self._client.list_tools()

    async def invoke(self, tool_name: str, params: dict) -> dict:
        """Invoca un tool MCP por nombre (protocolo, no dispatcher manual)."""
        return await self._client.call_tool(tool_name, params)


class _SdkMCPClient:
    """Esqueleto para conectar via SDK 'mcp' real cuando este disponible."""

    async def connect(self) -> None:
        pass

    async def list_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        raise NotImplementedError("MCP SDK real aun no conectado")


# Cache global del registry (una sola conexion por worker)
_MCP_REGISTRY: Optional[MCPRegistry] = None


def get_registry() -> MCPRegistry:
    global _MCP_REGISTRY
    if _MCP_REGISTRY is None:
        _MCP_REGISTRY = MCPRegistry()
    return _MCP_REGISTRY

# ---------------------------------------------------------------------------
# GEMBOK EKSEKUSI & METERED BILLING (BYOK bypass / Free / Plus)
#   - BYOK (custom_api_key)  -> unmetered, lewat semua Supabase cek.
#   - universal (FREE)       -> max 10 chati / 22 jam.
#   - deepseek-flash (PLUS)  -> min balance + max 30 chati / 24 jam.
#   - Ognia Supabase selalu in try-except (timeout ei saa merusak pipeline).
# ---------------------------------------------------------------------------
import time as _time

_FREE_WINDOW_H = 22
_PLUS_WINDOW_H = 24
_FREE_LIMIT = 10
_PLUS_LIMIT = 30
_PROFIT_MULT = 3.0
_MIN_PLUS_BALANCE = 0.005
# F-1: jatah kredit bulanan untuk tier FREE pada node agent. Ini yang membuat
# "gratis" berarti sesuatu di kanvas: user tanpa baris `user_balances` tetap
# boleh menjalankan node agent (batas efektifnya jendela 10 chat / 22 jam),
# alih-alih diblokir "Saldo habis" karena saldo terbaca 0.
_FREE_MONTHLY_CREDIT = 100.0

_METER: dict[str, dict] = {}


class BillingBlocked(Exception):
    """Halting execution halted, propagierte zum HTTP mapper (status_code)."""
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ToolExecutionError(RuntimeError):
    """Tool/provider mengembalikan status GAGAL sebagai dict, bukan exception.

    BUG-B2 (KRITIS - kegagalan senyap):
    `provider_registry.run` sengaja TIDAK pernah melempar -- ia mengembalikan
    `{"status": "error" | "needs_credential" | "needs_configuration"}`. Versi
    lama `_exec_mcp` mengembalikan dict itu apa adanya, sehingga `_run_node`
    mencatat node sebagai "completed" walau tool benar-benar gagal: eksekusi
    "sukses" padahal tidak ada yang dikerjakan, `/analytics` tidak menghitung
    error, dan kanvas tidak pernah memerah. Exception ini dinaikkan supaya node
    ditandai `error`, eksekusi `error`, dan self-healing bisa mengklasifikasi
    (404 -> abort, 5xx/network -> retry, credential -> escalate).

    Pesan WAJIB memuat teks error penyedia (mis. "404", "500", "timeout",
    "invalid JSON") supaya `self_healing.classify_error` memetakannya dengan
    benar -- pola yang sama dengan `PlaceholderResolutionError`.
    """


def _now_ts() -> float:
    return _time.time()


def _iso_from_ts(ts: Any) -> Optional[str]:
    """Epoch detik (float) -> ISO 8601 UTC untuk kolom `timestamp` Supabase.

    F-3: `last_reset_free`/`last_reset_plus` adalah kolom timestamp, tetapi
    versi lama menulis epoch detik sebagai FLOAT. Postgres menolaknya dengan
    `22007 invalid input syntax for type timestamp`; error itu ditelan
    `except: pass`, jadi penghitung kuota gratis TIDAK PERNAH tersimpan dan
    selalu reset tiap request. Di sini float dikonversi ke ISO 8601.
    """
    if ts is None:
        return None
    if isinstance(ts, str):
        s = ts.strip()
        return s or None          # sudah string (ISO) - teruskan apa adanya
    try:
        return _datetime.datetime.fromtimestamp(
            float(ts), _datetime.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _ts_from_db(value: Any) -> Optional[float]:
    """Nilai kolom timestamp Supabase -> epoch detik (float) untuk perbandingan.

    `guard_execution` membandingkan `now - float(lr)`; kalau DB mengembalikan
    string ISO, `float()` akan meledak. Normalisasi di sini menjaga satu
    representasi internal (epoch detik) di seluruh mesin.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)                       # epoch dalam bentuk string
    except ValueError:
        pass
    try:
        dt = _datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_datetime.timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _meter_data(email: str) -> dict:
    m = _METER.get(email)
    if m is None:
        m = {"free_count": 0, "plus_count": 0,
             "last_reset_free": None, "last_reset_plus": None, "credit": None}
        _METER[email] = m
    return m


def _meter_load(email: str) -> dict:
    """Baca profil utilisasi dari Supabase (best-effort), fallback lokal."""
    m = _meter_data(email)
    try:
        import database as _db
        cc = _db._get_client()
        r = cc.table("user_usage").select("*").eq("email", email).limit(1).execute()
        d = (getattr(r, "data", None) or [])
        if d:
            row = d[0]
            m["free_count"] = int(row.get("free_chat_count", 0) or 0)
            m["plus_count"] = int(row.get("plus_chat_count", 0) or 0)
            m["last_reset_free"] = _ts_from_db(row.get("last_reset_free"))
            m["last_reset_plus"] = _ts_from_db(row.get("last_reset_plus"))
            m["credit"] = float(row.get("credit_balance", 0) or 0)
    except Exception:
        pass
    return m


def _meter_save(email: str) -> None:
    """Persist utilisasi ke Supabase.

    F-3 (KRITIS): dua cacat diperbaiki bersamaan.
      1. `last_reset_free`/`last_reset_plus` ditulis sebagai FLOAT epoch,
         padahal kolomnya `timestamp` -> Postgres menolak (22007) dan
         penghitung kuota gratis tidak pernah tersimpan. Sekarang ditulis
         sebagai ISO 8601 (lihat `_iso_from_ts`).
      2. Kegagalan ditelan `except: pass`, sehingga cacat di atas tidak
         terlihat selama berbulan-bulan. Sekarang kegagalan di-LOG dengan
         jelas dan dinaikkan sebagai `MeterPersistenceError`; pemanggil boleh
         memutuskan untuk tetap melanjutkan (metering tidak boleh membatalkan
         pekerjaan user yang sudah jadi), tetapi TIDAK BOLEH senyap lagi.
    """
    m = _METER.get(email)
    if not m:
        return
    try:
        import database as _db
        cc = _db._get_write_client()
        row = {
            "free_chat_count": int(m.get("free_count", 0)),
            "plus_chat_count": int(m.get("plus_count", 0)),
            "last_reset_free": _iso_from_ts(m.get("last_reset_free")),
            "last_reset_plus": _iso_from_ts(m.get("last_reset_plus")),
            "credit_balance": float(m.get("credit", 0) or 0),
        }
        ex = cc.table("user_usage").select("email").eq("email", email).limit(1).execute()
        if (getattr(ex, "data", None) or []):
            cc.table("user_usage").update(row).eq("email", email).execute()
        else:
            cc.table("user_usage").insert({"email": email, **row}).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[meter] GAGAL menyimpan utilisasi '{email}': "
              f"{type(exc).__name__}: {exc}")
        raise MeterPersistenceError(email, exc) from exc


class MeterPersistenceError(RuntimeError):
    """Utilisasi user tidak bisa dipersist ke Supabase (F-3: jangan senyap)."""

    def __init__(self, email: str, cause: Exception) -> None:
        super().__init__(f"gagal menyimpan utilisasi '{email}': "
                         f"{type(cause).__name__}: {cause}")
        self.email = email
        self.cause = cause


def guard_execution(cfg: dict, owner: str) -> tuple[bool, int | None, str]:
    """Gate gembok pre-eksekusi. Return (allowed, http_status, error_msg)."""
    if not owner:
        return True, None, ""
    custom = str((cfg or {}).get("custom_api_key") or "").strip()
    if custom:
        # 1) BYOK: lewat semua Supabase cek (Unmetered).
        return True, None, ""
    import database as _db
    m = _meter_load(owner)
    model = str((cfg or {}).get("model") or "universal").lower()
    now = _now_ts()

    if model == "deepseek-flash":
        # 3) PLUS
        lr = m.get("last_reset_plus")
        if lr is None or (now - float(lr)) > _PLUS_WINDOW_H * 3600:
            m["plus_count"] = 0
            m["last_reset_plus"] = now
        if m["plus_count"] >= _PLUS_LIMIT:
            return False, 403, ("Batas harian Plus Anda (30 chat) tercapai "
                                "untuk menjaga stabilitas API.")
        credit = m.get("credit")
        if credit is None:
            try:
                credit = _db.get_balance(owner)
            except Exception:
                credit = None
        if credit is not None and credit <= _MIN_PLUS_BALANCE:
            return False, 402, ("Saldo AI tidak mencukupi. Silakan Top-Up "
                                "via Dodo Payments.")
        return True, None, ""

    # 2) FREE (universal)
    lr = m.get("last_reset_free")
    if lr is None or (now - float(lr)) > _FREE_WINDOW_H * 3600:
        m["free_count"] = 0
        m["last_reset_free"] = now
    if m["free_count"] >= _FREE_LIMIT:
        return False, 403, ("Batas 10 percakapan gratis Anda telah habis. "
                            "Silakan kembali dalam 22 jam, gunakan Custom API "
                            "Key, atau upgrade ke Plus.")
    return True, None, ""

# ---------------------------------------------------------------------------
# RESOLUSI PLACEHOLDER {{...}} (adversarial BUG-3/BUG-6, triase 2026-10-06)
# ---------------------------------------------------------------------------
# Dua makna token {{...}} dibedakan SENGAJA:
#   {{tanpa_titik}}    placeholder isi-user (chat_id, url, channel, ...).
#                      Didesain utuh di config sampai user mengisinya di
#                      kanvas; runtime TIDAK menyentuhnya.
#   {{akar.segmen..}}  ekspresi antar-node. WAJIB diresolv terhadap konteks
#                      eksekusi sebelum prompt/params dipakai. Bila gagal ->
#                      PlaceholderResolutionError (kegagalan jujur), bukan
#                      string verbatim yang diam-diam masuk ke LLM atau
#                      dipanggilkan ke API eksternal (bukti skenario S3).
_PLACEHOLDER_RX = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_MISSING = object()


class PlaceholderResolutionError(ValueError):
    """Referensi {{node.path}} tak bisa diresolv -> gagal jujur (BUG-3).

    Pesan sengaja memuat penanda `PlaceholderResolutionError` supaya
    `self_healing.classify_error` mengenali error ini sebagai `abort`
    (payload identik tidak akan pernah valid; retry hanya membakar kuota).
    """


def _split_placeholder_path(expr: str) -> list[str]:
    """Pecah `http_1.items[0].id` -> ['http_1','items','0','id'].

    Mendukung indeks array `[0]`, indeks negatif `[-1]`, indeks berantai
    `[0][1]`, dan kunci berkutip `["nama"]` / `['nama']`. Tanpa ini, segmen
    `items[0]` dianggap satu kunci dan selalu "tidak ditemukan" (bug yang
    ditemukan saat bukti BAGIAN 1.3 brief 7 Okt).
    """
    segs: list[str] = []
    for part in str(expr).split("."):
        if not part:
            continue
        base = re.match(r"^([^\[\]]*)", part).group(1)
        if base:
            segs.append(base)
        for idx in re.findall(r"\[([^\]]*)\]", part):
            idx = idx.strip()
            if len(idx) >= 2 and idx[0] == idx[-1] and idx[0] in ("'", '"'):
                idx = idx[1:-1]          # kunci berkutip: items["nama"]
            if idx != "":
                segs.append(idx)
    return segs


def _dig(root: Any, segs: list[str]) -> Any:
    """Telusuri segmen titik pada dict/list; kembalikan _MISSING bila jalur tak ada."""
    cur = root
    for seg in segs:
        if isinstance(cur, dict):
            if seg in cur:
                cur = cur[seg]
                continue
            return _MISSING
        if isinstance(cur, (list, tuple)) and seg.lstrip("-").isdigit():
            idx = int(seg)
            if -len(cur) <= idx < len(cur):
                cur = cur[idx]
                continue
            return _MISSING
        return _MISSING
    return cur


# ---------------------------------------------------------------------------
# EVALUASI KONDISI (BUG #1 — IF/percabangan)
# ---------------------------------------------------------------------------
class ConditionEvaluationError(ValueError):
    """Ekspresi `config.condition` tidak valid / tidak bisa dievaluasi.

    Ditandai di pesan supaya `self_healing.classify_error` bisa mengenalinya
    sebagai kondisi non-sementara (payload identik tak akan pernah valid).
    """


#: Operator pembanding & aritmatika yang DIIZINKAN. Tidak ada atribut,
#: subscript, call, comprehension, atau nama bebas — whitelist tertutup.
_CMP_OPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_, ast.IsNot: operator.is_not,
}
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.Not: operator.not_, ast.USub: operator.neg,
              ast.UAdd: operator.pos}
#: Nama yang boleh muncul sebagai literal (bukan variabel bebas).
_ALLOWED_NAMES = {"true": True, "false": False, "null": None,
                  "none": None, "yes": True, "no": False}


def _safe_eval_node(node: ast.AST) -> Any:
    """Evaluasi AST dengan whitelist tertutup. TIDAK memakai eval()/exec()."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[key]
        raise ConditionEvaluationError(
            f"ConditionEvaluationError: nama '{node.id}' tidak dikenal di "
            f"ekspresi kondisi (hanya literal true/false/null yang boleh "
            f"berdiri sendiri; nilai lain harus lewat {{placeholder}}).")
    if isinstance(node, ast.BoolOp):
        vals = [_safe_eval_node(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        return any(vals)
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if fn is None:
            raise ConditionEvaluationError(
                "ConditionEvaluationError: operator unary tidak didukung.")
        return fn(_safe_eval_node(node.operand))
    if isinstance(node, ast.BinOp):
        fn = _BIN_OPS.get(type(node.op))
        if fn is None:
            raise ConditionEvaluationError(
                "ConditionEvaluationError: operator aritmatika tidak didukung.")
        return fn(_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.Compare):
        left = _safe_eval_node(node.left)
        for op, comp in zip(node.ops, node.comparators):
            fn = _CMP_OPS.get(type(op))
            if fn is None:
                raise ConditionEvaluationError(
                    "ConditionEvaluationError: operator pembanding tidak didukung.")
            right = _safe_eval_node(comp)
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_safe_eval_node(e) for e in node.elts]
    raise ConditionEvaluationError(
        f"ConditionEvaluationError: elemen '{type(node).__name__}' tidak "
        f"diizinkan di ekspresi kondisi (hanya literal, pembanding, "
        f"AND/OR/NOT, dan aritmatika dasar).")


def evaluate_condition(expr: str) -> bool:
    """Evaluasi ekspresi kondisi yang SUDAH diresolv (tanpa `{{...}}`).

    Aman: memakai `ast.parse` + whitelist tertutup, TIDAK memakai `eval()`.
    `simple_eval` tidak tersedia di lingkungan ini, jadi whitelist ini
    menggantikannya dengan jaminan setara (tanpa akses nama/atribut/call).

    Raises:
        ConditionEvaluationError: sintaks tidak valid / elemen terlarang.
    """
    text = str(expr or "").strip()
    if not text:
        raise ConditionEvaluationError("ConditionEvaluationError: kondisi kosong.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ConditionEvaluationError(
            f"ConditionEvaluationError: sintaks kondisi tidak valid "
            f"({exc.msg}). Contoh: \"{{{{data.status}}}} == 'valid'\"."
        ) from exc
    return bool(_safe_eval_node(tree))



# ---------------------------------------------------------------------------
# STATE GRAPH ORCHESTRATOR
# ---------------------------------------------------------------------------
class StatefulOrchestrator:
    """Ejecuta un FlowGraph como un State Graph asincrono (DAG).

    - Cada nodo pasa por estados: pending -> running -> completed/error.
    - Los nodos con out-edges propagan su output como input a los sucesores.
    - Los nodos independientes de un mismo nivel se ejecutan en paralelo
      (asyncio.gather) - no bloquea el hilo del servidor.
    """

    def __init__(self, graph: FlowGraph, registry: Optional[MCPRegistry] = None,
                 trigger_input: Optional[dict] = None,
                 owner_email: str = "",
                 healing_factory: Optional[Callable[[], Any]] = None,
                 reasoner: Optional[Callable[..., Awaitable[dict]]] = None):
        self.graph = graph
        self.registry = registry or get_registry()
        self.trigger_input = dict(trigger_input or {})
        # FASE 2.6: pemilik eksekusi (email) WAJIB diketahui node MCP — tool
        # kredensial (telegram/slack/gmail/…) membaca token dari Brankas milik
        # user. Tanpa ini setiap node ber-kredensial gagal "CredentialMissing"
        # walau user sudah menyimpannya.
        self.owner_email = owner_email or ""
        # Self-healing. `healing_factory` injectable supaya test bisa
        # menyuntikkan agent palsu (tanpa jaringan/LLM) tanpa mengubah
        # kode produksi. Default-nya constructs SelfHealingAgent sungguhan.
        self.healing_factory = healing_factory or (lambda: SelfHealingAgent())
        # BUG #3 (delegasi multi-agent): `reasoner` injectable supaya test
        # bisa menjalankan supervisor/sub-agent tanpa jaringan. Default:
        # `agent_reasoner.run_agent` sungguhan (di-resolve lazy saat dipakai).
        self._reasoner = reasoner
        self.states: dict[str, str] = {n.id: "pending" for n in graph.nodes}
        self.outputs: dict[str, dict] = {}
        # BUG #3: node yang sudah dieksekusi LEWAT DELEGASI supervisor tidak
        # boleh dijalankan ulang oleh mesin sebagai node mandiri (kalau tidak,
        # sub-agent dieksekusi dua kali: sekali via delegasi, sekali linear).
        self._delegated: set[str] = set()
        self._by_id = {n.id: n for n in graph.nodes}
        self._succs: dict[str, list[str]] = defaultdict(list)
        self._preds: dict[str, list[str]] = defaultdict(list)
        for e in graph.edges:
            self._succs[e.source].append(e.target)
            self._preds[e.target].append(e.source)

    # --- RESOLUSI PLACEHOLDER {{...}} (adversarial BUG-3) ------------------
    def _placeholder_roots(self, extra: Optional[dict] = None) -> dict[str, Any]:
        """Akar ekspresi: id node yang sudah dieksekusi + alias payload trigger.

        `extra` menimpa (overlay) akar untuk konteks TERISOLASI — dipakai
        Split In Batches supaya tiap item hanya melihat datanya sendiri.
        """
        roots: dict[str, Any] = dict(self.outputs)
        trig = next((n.id for n in self.graph.nodes
                     if n.data.kind == NodeKind.TRIGGER), None)
        if trig and trig in self.outputs:
            roots.setdefault("trigger", self.outputs[trig])
        # Alias payload input manual/webhook - dipakai model menulis
        # `{{data.status}}` / `{{payload.x}}` tanpa tahu id trigger.
        for alias in ("input", "payload", "data"):
            roots.setdefault(alias, self.trigger_input)
        if extra:
            roots.update(extra)
        return roots

    def _resolve_text(self, text: str, *, where: str,
                      extra_roots: Optional[dict] = None,
                      quote_strings: bool = False) -> str:
        """Eval semua `{{akar.segmen..}}` dalam `text` terhadap konteks run.

        - `{{tanpa_titik}}`  -> placeholder isi-user, DIBIARKAN utuh (didesain).
        - `{{akar.x.y}}`     -> nilai diganti; tak bisa diganti -> NAIKKAN
                                PlaceholderResolutionError (jujur, bukan diam).

        Args:
            quote_strings: dipakai oleh evaluasi KONDISI. Nilai string diberi
                kutip (`'valid'`) supaya ekspresi seperti
                `{{data.status}} == 'valid'` menjadi perbandingan yang sah,
                bukan nama bebas yang error. Angka/bool tetap telanjang.
        """
        if not isinstance(text, str) or "{{" not in text:
            return text
        roots = self._placeholder_roots(extra_roots)
        node_ids = {n.id for n in self.graph.nodes}

        def _sub(m) -> str:
            expr = m.group(1).strip()
            if "." not in expr:
                return m.group(0)          # placeholder isi-user: jangan disentuh
            segs = _split_placeholder_path(expr)
            if not segs:
                return m.group(0)
            head, path = segs[0], segs[1:]
            root = roots.get(head, _MISSING)
            if root is _MISSING:
                if head in node_ids:
                    raise PlaceholderResolutionError(
                        f"PlaceholderResolutionError: node '{head}' belum "
                        f"menghasilkan output ketika {where} memakai "
                        f"{{{{{expr}}}}} (bukan predesesor / belum "
                        f"dieksekusi). Susun urutan node agar data tersedia.")
                raise PlaceholderResolutionError(
                    f"PlaceholderResolutionError: akar '{head}' pada "
                    f"{{{{{expr}}}}} tidak ada di workflow (hanya id node "
                    f"atau alias trigger/input/payload/data). Perbaiki "
                    f"referensi di {where}.")
            val = _dig(root, path)
            if val is _MISSING and isinstance(root, dict) and "result" in root:
                # Node MCP membungkus hasil provider di kunci `result`.
                val = _dig(root["result"], path)
            if val is _MISSING:
                keys = (", ".join(sorted(map(str, root.keys()))[:8])
                        if isinstance(root, dict) else "-")
                raise PlaceholderResolutionError(
                    f"PlaceholderResolutionError: field '{'.'.join(path)}' "
                    f"tidak ditemukan di output '{head}' (kunci tersedia: "
                    f"{keys}). Perbaiki referensi {{{{{expr}}}}} di {where}.")
            if isinstance(val, str):
                if quote_strings:
                    # Kutip nilai supaya perbandingan kondisi sah:
                    # `{{data.status}} == 'valid'` -> `'valid' == 'valid'`.
                    return "'" + val.replace("\\", "\\\\").replace("'", "\\'") + "'"
                return val
            if val is None:
                return "null" if quote_strings else ""
            if isinstance(val, bool):
                return ("true" if val else "false") if quote_strings \
                    else json.dumps(val)
            return json.dumps(val, ensure_ascii=False)

        return _PLACEHOLDER_RX.sub(_sub, text)

    def _resolve_cfg(self, cfg: dict, *, where: str,
                     extra_roots: Optional[dict] = None) -> dict:
        """Resolv semua string di config node (salinan baru, config asli utuh)."""
        if not cfg:
            return cfg

        def walk(v: Any) -> Any:
            if isinstance(v, str):
                return self._resolve_text(v, where=where, extra_roots=extra_roots)
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x) for x in v]
            return v

        return walk(cfg)

    def _condition_gate(self, cfg: dict, node: FlowNode,
                        extra_roots: Optional[dict] = None) -> Optional[str]:
        """Kembalikan alasan SKIP bila node harus dilewati, atau None bila jalan.

        Semantik (BUG #1):
          - `condition`      : node hanya jalan bila ekspresi truthy (IF).
          - `else_condition` : node hanya jalan bila ekspresi truthy (ELSE).
        Bila keduanya ada, keduanya harus truthy. Placeholder diresolv dulu,
        lalu dievaluasi dengan whitelist aman (tanpa eval()).
        """
        where = f"node '{node.id}'"
        for key in ("condition", "else_condition"):
            raw = cfg.get(key)
            if raw is None or raw == "":
                continue
            if not isinstance(raw, str):
                raise ConditionEvaluationError(
                    f"ConditionEvaluationError: config.{key} pada node "
                    f"'{node.id}' harus string, bukan {type(raw).__name__}.")
            resolved = self._resolve_text(raw, where=where,
                                          extra_roots=extra_roots,
                                          quote_strings=True)
            if not evaluate_condition(resolved):
                return (f"kondisi '{key}' tidak terpenuhi: {resolved!r}")
        return None

    def _reason_fn(self):
        """Reasoner efektif: yang disuntikkan test, atau `agent_reasoner.run_agent`.

        Dipakai `_exec_agent` DAN `_exec_supervisor` supaya sub-agent yang
        dipanggil lewat delegasi memakai jalur yang sama (dan bisa diuji
        tanpa jaringan).
        """
        if self._reasoner is not None:
            return self._reasoner
        from agent_reasoner import run_agent as _real
        return _real

    # --- SPLIT IN BATCHES (BUG #4: isolasi multi-item) ----------------------
    @staticmethod
    def _extract_batch_items(inp: dict) -> Optional[list]:
        """Cari array input untuk di-batch.

        Menelusuri bersarang (kedalaman terbatas) karena array sering berada
        di dalam output node hulu: `{"t": {"webhook_payload": {"items": [...]}}}`.
        Kunci umum diprioritaskan, lalu list pertama yang ditemukan.
        """
        _KEYS = ("items", "batch", "array", "list", "rows", "data",
                 "results", "payload", "webhook_payload", "context",
                 "result", "output")

        def search(obj: Any, depth: int) -> Optional[list]:
            if depth > 4:
                return None
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                for k in _KEYS:
                    if k in obj:
                        v = obj[k]
                        if isinstance(v, list):
                            return v
                        found = search(v, depth + 1)
                        if found is not None:
                            return found
                for v in obj.values():
                    if isinstance(v, list):
                        return v
                    if isinstance(v, dict):
                        found = search(v, depth + 1)
                        if found is not None:
                            return found
            return None

        return search(inp, 0)

    async def _run_batched(self, node: FlowNode, inp: dict,
                           batch_size: int) -> dict:
        """Jalankan node sekali per batch dengan konteks TERISOLASI.

        Isolasi: tiap batch hanya melihat `{{item}}` dan `{{batch}}` miliknya
        sendiri — jawaban batch B tidak bisa dipengaruhi batch A. `self.outputs`
        sementara di-overlay per batch lalu dipulihkan (tidak ada state bocor
        antar batch).
        """
        items = self._extract_batch_items(inp) or []
        size = max(1, int(batch_size))
        chunks = [items[i:i + size] for i in range(0, len(items), size)]
        executor = self.EXECUTORS[node.data.kind]
        results: list[dict] = []
        saved = dict(self.outputs)
        try:
            for idx, chunk in enumerate(chunks):
                # Konteks terisolasi: `item` (batch berukuran 1) / `batch`
                # (list) hanya berisi potongan ini.
                scope = {
                    "item": chunk[0] if len(chunk) == 1 else chunk,
                    "batch": chunk,
                    "index": idx,
                }
                scoped_inp = {"_from": inp.get("_from", "trigger"),
                              "item": scope["item"], "batch": chunk,
                              "index": idx, "items": chunk}
                out = await executor(self, node, scoped_inp,
                                     _extra_roots=scope)
                results.append({"index": idx, "size": len(chunk),
                                "input": chunk, "output": out})
                # Pulihkan outputs agar batch berikutnya tidak melihat output
                # batch sebelumnya (isolasi).
                self.outputs = dict(saved)
        finally:
            self.outputs = saved
        return {"type": "batch.results", "batch_size": size,
                "batch_count": len(chunks), "item_count": len(items),
                "results": results}

    # --- DELEGASI MULTI-AGENT (BUG #3) --------------------------------------
    def _delegation_targets(self, node: FlowNode) -> list[str]:
        """ID agent yang boleh didelegasikan (config.delegates, else semua agent)."""
        cfg = node.data.config or {}
        explicit = cfg.get("delegates") or cfg.get("delegate")
        agent_ids = [n.id for n in self.graph.nodes
                     if n.data.kind == NodeKind.AGENT and n.id != node.id]
        if isinstance(explicit, (list, tuple)):
            wanted = {str(x) for x in explicit}
            return [i for i in agent_ids if i in wanted]
        if isinstance(explicit, str) and explicit.strip():
            return [i for i in agent_ids if i == explicit.strip()]
        return agent_ids

    async def _run_delegate(self, agent_id: str, task: str) -> dict:
        """Jalankan satu sub-agent dengan `task` sebagai input; kembalikan hasil."""
        target = self._by_id.get(agent_id)
        if target is None or target.data.kind != NodeKind.AGENT:
            return {"status": "error",
                    "error": f"agent '{agent_id}' tidak ada / bukan node agent."}
        sub_inp = {"_from": "delegate", "instruction": task, "task": task,
                   "reply": task}
        executor = self.EXECUTORS[NodeKind.AGENT]
        out = await executor(self, target, sub_inp)
        # Tandai sudah dieksekusi lewat delegasi supaya mesin tidak
        # menjalankannya lagi sebagai node mandiri di gelombang berikutnya.
        self._delegated.add(agent_id)
        self.outputs[agent_id] = out or {"noop": True}
        self.states[agent_id] = "completed"
        return {"status": out.get("agent_status", "success"),
                "agent_id": agent_id, "reply": out.get("instruction", ""),
                "raw": out}

    async def _exec_supervisor(self, node: FlowNode, inp: dict,
                               cfg: dict, prompt: str) -> dict:
        """Loop delegasi supervisor -> sub-agent -> supervisor (maks N putaran).

        Protokol delegasi (dibaca dari balasan LLM, bukan dieksekusi):
            [DELEGATE: agent_id=<id> task="<tugas>"]
        atau JSON: {"delegate": [{"agent_id": "...", "task": "..."}]}
        """
        reason = self._reason_fn()
        targets = self._delegation_targets(node)
        roster = ", ".join(targets) if targets else "(tidak ada agent lain)"
        sys_prompt = (
            f"{prompt}\n\n"
            "Kamu SUPERVISOR Agent. Kamu boleh mendelegasikan tugas ke agent "
            f"lain. Agent yang tersedia: {roster}.\n"
            "Untuk mendelegasikan, tulis SATU baris per tugas dengan format:\n"
            '  [DELEGATE: agent_id=<id> task="<tugas spesifik>"]\n'
            "Setelah menerima hasil delegasi, lanjutkan. Bila seluruh tugas "
            "selesai, tulis jawaban akhir TANPA baris [DELEGATE]."
        )
        transcript: list[dict] = []
        delegations: list[dict] = []
        max_rounds = int((node.data.config or {}).get("max_delegations", 5) or 5)
        reply = ""
        for _round in range(max_rounds + 1):
            turn_input = dict(inp)
            if transcript:
                turn_input["delegation_results"] = transcript
                turn_input["instruction"] = (
                    f"{prompt}\n\nHasil delegasi sejauh ini:\n"
                    + json.dumps(transcript, ensure_ascii=False))
            res = await reason(sys_prompt, turn_input, config=cfg)
            if res.get("status") != "success":
                return {"type": "agent.think", "role": "supervisor",
                        "agent_status": res.get("status", "error"),
                        "instruction": res.get("reply", ""),
                        "agent_error": res.get("error"),
                        "delegations": delegations, "usage": res.get("usage", {})}
            reply = str(res.get("reply") or "")
            directives = self._parse_delegations(reply, targets)
            if not directives:
                break
            for agent_id, task in directives:
                outcome = await self._run_delegate(agent_id, task)
                record = {"agent_id": agent_id, "task": task,
                          "status": outcome.get("status"),
                          "reply": outcome.get("reply", "")}
                transcript.append(record)
                delegations.append(record)
        return {"type": "agent.think", "role": "supervisor",
                "received_from": inp.get("_from", "trigger"),
                "instruction": reply, "delegations": delegations,
                "delegated_count": len(delegations)}

    @staticmethod
    def _parse_delegations(reply: str,
                           targets: list[str]) -> list[tuple[str, str]]:
        """Parse direktif delegasi dari balasan supervisor (aman, tanpa exec)."""
        text = str(reply or "")
        out: list[tuple[str, str]] = []
        # 1) Bentuk tekstual: [DELEGATE: agent_id=x task="..."]
        for m in re.finditer(r"\[\s*DELEGATE\s*:(.*?)\]", text, re.I | re.S):
            body = m.group(1)
            aid = re.search(r"agent_id\s*=\s*['\"]?([\w.\-]+)", body, re.I)
            task = re.search(r"task\s*=\s*['\"](.+?)['\"]", body, re.I | re.S)
            if aid and task:
                out.append((aid.group(1), task.group(1).strip()))
        if out:
            return out
        # 2) Bentuk JSON: {"delegate": [{"agent_id","task"}]}
        for m in re.finditer(r"\{.*\}", text, re.S):
            try:
                obj = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                continue
            items = obj.get("delegate") if isinstance(obj, dict) else None
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("agent_id"):
                        out.append((str(it["agent_id"]),
                                    str(it.get("task", ""))))
            if out:
                return out
        return out

    # --- executor registry (NodeKind -> async fn), sin if/else en el motor ---
    async def _exec_trigger(self, node: FlowNode, inp: dict,
                            _extra_roots: Optional[dict] = None) -> dict:
        cfg = self._resolve_cfg(node.data.config or {},
                                where=f"node '{node.id}'",
                                extra_roots=_extra_roots)
        event = cfg.get("event_name") or node.data.label or "webhook"
        payload = dict(self.trigger_input or {})
        if node.data.kind == NodeKind.TRIGGER and inp:
            merged = {k: v for k, v in inp.items() if k != "_from"}
            payload = {**merged, **payload}
        out = {"type": "trigger.fire", "event": event,
               "message": f"Trigger disparado: {event}",
               "webhook_payload": payload}
        if payload:
            out["context"] = payload
        return out

    async def _exec_agent(self, node: FlowNode, inp: dict,
                          _extra_roots: Optional[dict] = None) -> dict:
        # Reasoning Agent nyata (LangChain Core) - baca System Prompt + input Trigger.
        reason = self._reason_fn()

        cfg = node.data.config or {}
        # BUG FIX 2026-10-06 (adversarial BUG-1, silent failure): canvas
        # (ConfigPanel -> setNodeCfg("prompt", ...)) dan model chat keduanya
        # menulis instruksi agent di config `prompt`, tetapi runner hanya
        # membaca `system_prompt` -> instruksi TERSINGKIR dan diganti label
        # node tanpa error apa pun. `prompt` didahulukan (penulis saat ini),
        # `system_prompt` tetap sebagai alias legacy (NodeConfig).
        prompt = (cfg.get("prompt") or cfg.get("system_prompt")
                  or node.data.label or "instruccion por defecto")
        # BUG-3: {{akar.x}} di instruksi diresolv dulu terhadap output node
        # hulu; gagal -> PlaceholderResolutionError (bukan literal verbatim
        # yang diam-diam dikirim ke LLM).
        prompt = self._resolve_text(prompt, where=f"node '{node.id}'",
                                    extra_roots=_extra_roots)

        import database as db
        owner = getattr(self, "owner_email", None) or cfg.get("owner_email") or ""
        _custom = str((cfg or {}).get("custom_api_key") or "").strip()

        # --- VAULT RESOLVE: jos config.key tyhjä, hakee user_vault ---
        #   (Zero-Knowledge: decrypt ul 'vault_security' ja injektoi BYOK:ksi.
        #    Näin Unmetered-logiikka pätee kun avain tulee vaultista.)
        if not _custom and owner:
            try:
                import vault_security as _vs
                _provider = (str(cfg.get("provider") or "").strip()
                             or str(cfg.get("model") or "custom_llm").strip())
                _ct = db.vault_get(owner, _provider)
                if _ct:
                    _resolved = _vs.decrypt_key(_ct)
                    if _resolved:
                        cfg = dict(cfg)
                        cfg["custom_api_key"] = _resolved
                        cfg["_vault_resolved"] = True
                        _custom = _resolved
            except Exception:
                _custom = str(cfg.get("custom_api_key") or "").strip() or ""

        # --- GEMBOK EKSEKUSI & METERED BILLING (BYOK bypass / Free / Plus) ---
        _allowed, _code, _msg = guard_execution(cfg, owner)
        if not _allowed:
            raise BillingBlocked(_code, _msg)

        # Legacy fallback: blok bila saldo habis -- HANYA untuk tier PLUS.
        # F-1 (KONTRADIKSI GEMBOK, launch blocker): `guard_execution` MENGIZINKAN
        # tier FREE (batas 10 chat / 22 jam), tetapi blok lama menuntut
        # `get_balance > 0`. User gratis tidak punya baris `user_balances`
        # sehingga `get_balance` mengembalikan 0.0 -> SELALU diblokir dengan
        # "Saldo habis" walau gembok resminya mengizinkan: dua aturan yang
        # bertentangan, dan user gratis tidak pernah bisa menjalankan node
        # agent sama sekali. Paket gratis memberi jatah kredit bulanan untuk
        # node agent (`_FREE_MONTHLY_CREDIT`); batas efektifnya adalah jendela
        # 10 chat / 22 jam yang SUDAH ditegakkan `guard_execution`. Karena itu
        # cek saldo hanya relevan untuk tier PLUS, yang memang membayar per
        # pemakaian (dan `guard_execution` juga sudah mengembalikan 402 bila
        # saldo Plus di bawah ambang).
        _model_l = str((cfg or {}).get("model") or "universal").lower()
        if owner and not _custom and _model_l == "deepseek-flash":
            try:
                _bal = db.get_balance(owner)
            except Exception:
                _bal = None
            if _bal is not None and _bal <= 0:
                return {
                    "type": "agent.think",
                    "received_from": inp.get("_from", "trigger"),
                    "instruction": prompt,
                    "message": "[Agent blocked] Saldo habis. Topup via Dodo Payments.",
                    "agent_status": "blocked_no_balance",
                }
        # --- DELEGASI MULTI-AGENT (BUG #3) ----------------------------------
        # Ditempatkan SETELAH resolusi vault + guard billing supaya supervisor
        # memakai kunci BYOK user dan tetap tunduk gembok eksekusi. Tiap
        # sub-agent yang dipanggil lewat `_run_delegate` melewati `_exec_agent`
        # sendiri (meter + guard per pemanggilan LLM).
        _role = str(cfg.get("role") or "").strip().lower()
        if _role == "supervisor" or cfg.get("delegates") is not None:
            return await self._exec_supervisor(node, inp, cfg, prompt)

        res = await reason(prompt, dict(inp), config=cfg)
        status = res.get("status", "success")

        # --- METER POST-EKSEKUSI (increment count / potong saldo*3 / LEDGER) ---
        if status == "success" and owner and not _custom:
            _model = str(cfg.get("model") or "universal").lower()
            _m = _meter_load(owner)
            try:
                from billing_llm import LEDGER as _LEDGER
                _u = res.get('usage', {}) or {}
                _LEDGER.record(getattr(self, 'execution_id', '') or '', res.get('model', ''),
                               int(_u.get('prompt_tokens', 0) or 0),
                               int(_u.get('completion_tokens', 0) or 0),
                               float(res.get('cost_usd', 0) or 0))
            except Exception:
                pass
            if _model == "deepseek-flash":
                try:
                    db.deduct_balance(owner, float(res.get("cost_usd", 0) or 0) * _PROFIT_MULT)
                except Exception:
                    pass
                _m["plus_count"] = int(_m.get("plus_count", 0)) + 1
            else:
                _m["free_count"] = int(_m.get("free_count", 0)) + 1
            try:
                _meter_save(owner)
            except MeterPersistenceError as _mexc:
                # F-3: kegagalan persistensi TIDAK boleh membatalkan jawaban
                # yang sudah jadi, tetapi juga TIDAK boleh senyap -- `_meter_save`
                # sudah mencetak detailnya; di sini kita tandai node supaya
                # terlihat di laporan (tanpa mengubah status sukses LLM).
                print(f"[meter] node '{node.id}': utilisasi tidak tersimpan "
                      f"({_mexc})")
        if status == "success":
            return {
                "type": "agent.think",
                "received_from": inp.get("_from", "trigger"),
                "instruction": res.get("reply", ""),
                "message": f"Agent menerima input dari '{inp.get('_from', 'trigger')}' "
                           f"dan berpikir via {res.get('model', 'llm')}.",
                "usage": res.get("usage", {}),
                "cost_usd": res.get("cost_usd", 0.0),
            }
        # Sin LLM key / error: no crashea - catat jelas di execution_logs.
        return {
            "type": "agent.think",
            "received_from": inp.get("_from", "trigger"),
            "instruction": prompt,
            "message": f"[Agent {status}] {res.get('error', 'tanpa LLM key')}",
            "agent_status": status,
            "agent_error": res.get("error"),
        }

    @staticmethod
    def _raise_if_tool_failed(provider: str, result: Any) -> None:
        """BUG-B2: status gagal dari tool/provider -> raise, JANGAN "completed".

        Hanya dict ber-`status` yang diperiksa. Tool yang mengembalikan payload
        mentah tanpa `status` (perilaku lama) dibiarkan lewat supaya tidak ada
        regresi pada tool yang memang tidak punya konsep status.
        """
        if not isinstance(result, dict):
            return
        status = str(result.get("status") or "").strip().lower()
        if not status or status == "success":
            return
        detail = (result.get("error") or result.get("message")
                  or result.get("detail") or "")
        if not detail and result.get("missing"):
            detail = "config kurang: " + ", ".join(map(str, result["missing"]))
        where = (f"provider '{provider}'" if provider
                 else f"tool '{result.get('tool') or 'mcp'}'")
        raise ToolExecutionError(
            f"{where} status={status}: {detail or 'tanpa pesan'}")

    async def _exec_mcp(self, node: FlowNode, inp: dict,
                        _extra_roots: Optional[dict] = None) -> dict:
        """Node MCP: `config.provider` -> registry native, lalu tool bawaan mesin.

        FASE 2.6: sebelumnya executor mengabaikan `config.provider` dan memilih
        tool dari `config.tool_name` dengan default `web_search`, sehingga
        workflow "kirim Telegram" justru melakukan pencarian web. Sekarang:
          1. provider terdaftar -> `provider_registry` (Telegram/Slack/HTTP/...);
          2. provider TAK dikenal -> payload error eksplisit (tidak menebak);
          3. tanpa provider -> jalur lama (web_search/http_request) demi
             kompatibilitas workflow yang sudah tersimpan.

        BUG-B2: apa pun jalurnya, status GAGAL dinaikkan sebagai exception
        supaya node benar-benar tercatat `error` (bukan "completed" palsu).
        """
        # BUG-3: resolv {{akar.x}} di seluruh config sebelum provider
        # memakainya (chat_id/url/pesan) - config asli tidak dimutasi.
        cfg = self._resolve_cfg(node.data.config or {},
                                where=f"node '{node.id}'",
                                extra_roots=_extra_roots)
        owner = (getattr(self, "owner_email", None)
                 or cfg.get("owner_email") or "")
        provider = provider_registry.resolve(cfg, inp)
        if provider:
            result = await provider_registry.run_async(provider, cfg, inp, owner)
            self._raise_if_tool_failed(provider, result)
            return {"type": "mcp.call", "provider": provider,
                    "tool": result.get("tool"), "result": result}

        # --- jalur lama (tanpa provider) ------------------------------------
        tool = cfg.get("tool_name") or inp.get("tool") or inp.get("tool_name") or "web_search"
        param = (
            cfg.get("tool_param")
            or inp.get("instruction")
            or inp.get("reply")
            or inp.get("query")
            or ""
        )
        try:
            if tool == "web_search":
                result = await self.registry.invoke(tool, {"query": str(param), "max_results": 3})
            elif tool == "http_request":
                result = await self.registry.invoke(
                    tool, {"url": str(param), "method": str(cfg.get("method", "GET"))})
            else:
                result = await self.registry.invoke(tool, {"query": str(param)})
        except Exception as exc:  # noqa: BLE001 - target mati tidak boleh crash pipeline
            result = {"status": "error", "tool": tool,
                      "error": f"[{type(exc).__name__}] {exc}"}
        self._raise_if_tool_failed("", result)
        return {"type": "mcp.call", "tool": tool, "result": result}

    EXECUTORS: dict[NodeKind, Callable[[Any, FlowNode, dict], Awaitable[dict]]] = {
        NodeKind.TRIGGER: _exec_trigger,
        NodeKind.AGENT: _exec_agent,
        NodeKind.MCP: _exec_mcp,
    }

    def _runnable(self, remaining: set[str]) -> list[str]:
        return [
            nid for nid in remaining
            if nid not in self._delegated
            and all(self.states[p] == "completed" for p in self._preds[nid])
        ]
    async def run(self, on_step: Optional[Callable] = None) -> list[ExecutionStep]:
        await self.registry.connect()
        remaining = set(self._by_id.keys())
        steps: list[ExecutionStep] = []
        triggers = [n.id for n in self.graph.nodes if n.data.kind == NodeKind.TRIGGER]
        if not triggers:
            raise RuntimeError("Workflow tidak memiliki node Trigger (titik awal wajib).")

        while remaining:
            # Buang node yang sudah dieksekusi lewat delegasi supervisor
            # (BUG #3) - kalau tidak, mesin menjalankannya lagi secara linear
            # (eksekusi ganda). Node yang dibuang tetap membuka suksesornya.
            _done = [n for n in remaining if n in self._delegated]
            if _done:
                for nid in _done:
                    remaining.discard(nid)
                    for t in self._succs[nid]:
                        self.outputs.setdefault(t, {})
                if not remaining:
                    break
            wave = self._runnable(remaining)
            if not wave:
                raise RuntimeError("Workflow tampak buntu - kemungkinan siklus atau node yatim.")
            # Ejecutar nivel actual en paralelo (non-blocking).
            results = await asyncio.gather(
                *(self._run_node(nid, steps, on_step) for nid in wave),
                return_exceptions=True,
            )
            for nid, res in zip(wave, results):
                if isinstance(res, Exception):
                    raise RuntimeError(f"Nodo {nid} fallo: {res}") from res
                remaining.discard(nid)
                for t in self._succs[nid]:
                    self.outputs.setdefault(t, {})
        return steps

    async def _run_node(
        self,
        node_id: str,
        steps: list[ExecutionStep],
        on_step: Optional[Callable],
    ) -> None:
        """Jalankan satu node, dengan self-healing.

        Loop, bukan rekursi (draf memakai `return await self._run_node(...)`):
        rekursi menambah frame per percobaan dan membuat batas recursion
        jadi batas healing yang tidak sengaja. Loop dengan penghitung
        `attempt` eksplisit jauh lebih mudah dibaca dan diuji.

        Healing hanya untuk error dari eksekusi node. RuntimeError untuk
        graph rusak (tidak ada Trigger, workflow buntu) dilempar dari run(),
        bukan dari sini, jadi tidak masuk healing -- itu bukan sementara.
        """
        node = self._by_id[node_id]
        healing = self._healing()
        attempt = 1
        while True:
            self.states[node_id] = "running"
            step = ExecutionStep(node_id=node_id, kind=node.data.kind, status="running")
            if on_step:
                await on_step(step)
            try:
                raw_cfg = node.data.config or {}
                # --- GERBANG KONDISI (BUG #1: IF/ELSE) -----------------------
                skip_reason = self._condition_gate(raw_cfg, node)
                if skip_reason:
                    self.outputs[node_id] = {"skipped": True,
                                             "reason": skip_reason}
                    self.states[node_id] = "completed"
                    step.status = "skipped"
                    step.output = self.outputs[node_id]
                    steps.append(step)
                    if on_step:
                        await on_step(step)
                    return
                executor = self.EXECUTORS[node.data.kind]
                inps = {p: self.outputs.get(p, {}) for p in self._preds[node_id]}
                inp = dict(inps)
                inp["_from"] = next(iter(inps), "trigger")
                # --- SPLIT IN BATCHES (BUG #4) ------------------------------
                _bs = raw_cfg.get("batch_size", raw_cfg.get("split_in_batches"))
                if _bs:
                    size = 1 if isinstance(_bs, bool) else int(_bs)
                    out = await self._run_batched(node, inp, size)
                else:
                    out = await executor(self, node, inp)
                self.outputs[node_id] = out or {"noop": True}
                self.states[node_id] = "completed"
                step.status = "completed"
                step.input = inp
                step.output = self.outputs[node_id]
            except Exception as exc:  # noqa: BLE001
                plan = await healing.handle_failure(
                    node_id=node_id, error=exc, attempt=attempt)
                if plan.action == "retry":
                    # Emit SETIAP percobaan ke on_step supaya riwayat punya
                    # jejak, bukan cuma hasil akhir. Tanpa ini user hanya
                    # melihat "gagal" tanpa tahu sudah dicoba 5x.
                    retry_step = ExecutionStep(
                        node_id=node_id, kind=node.data.kind, status="retrying",
                        output={"healing": plan.to_dict()},
                    )
                    steps.append(retry_step)
                    if on_step:
                        await on_step(retry_step)
                    if plan.delay_ms:
                        await asyncio.sleep(plan.delay_ms / 1000)
                    attempt += 1
                    continue
                # Escalate / credential / abort: catat diagnosis terakhir,
                # lalu teruskan error aslinya supaya run() tetap gagal
                # dengan alasan yang benar.
                self.states[node_id] = "error"
                step.status = "error"
                step.output = {"error": str(exc), "healing": plan.to_dict()}
                steps.append(step)
                if on_step:
                    await on_step(step)
                raise
            steps.append(step)
            if on_step:
                await on_step(step)
            return

    def _healing(self):
        """SelfHealingAgent, bisa di-override test lewat healing_factory.

        Dibuat per pemanggilan, bukan sekali di __init__, supaya tidak ada
        state bersama antar eksekusi workflow yang berjalan paralel.
        """
        return self.healing_factory()
# ---------------------------------------------------------------------------
# API DE ORQUESTACION + PERSISTENCIA (execution_logs)
# ---------------------------------------------------------------------------
async def execute_workflow_async(workflow_id: str, flow_data: dict,
                                 trigger_input: Optional[dict] = None,
                                 execution_id: Optional[str] = None,
                                 owner_email: str = "") -> dict:
    """Ejecuta un workflow e persiste cada paso en execution_logs.

    FASE 2.5: `execution_id` boleh DIBERIKAN pemanggil. Sebelumnya fungsi ini
    selalu membuat id baru, sementara `launch_execution` sudah membuat baris
    `executions` (dan mengembalikan id itu ke klien). Akibatnya log & status
    akhir tersimpan di id yang TIDAK PERNAH di-poll klien: `GET /executions/{id}`
    selamanya "pending" tanpa satu pun langkah — laporan otomatis di chat mustahil.
    """
    graph = FlowGraph(**flow_data)
    provided = bool(execution_id)
    execution_id = execution_id or str(uuid.uuid4())
    # JEJAK: satu baris per eksekusi workflow (untuk memisahkan duplikasi
    # "mesin dieksekusi 2x" dari "agen memanggil tool 2x").
    print(f"[engine] start execution_id={execution_id} flow={workflow_id} "
          f"nodes={len(graph.nodes)} owner={'ya' if owner_email else 'kosong'}")
    if not provided:
        # Hanya pembuat barisnya yang meng-insert. Kalau id diberikan pemanggil
        # (`launch_execution`), barisnya SUDAH ada — insert ulang akan gagal
        # (PK duplikat) dan justru mematikan flag `_configured` di database.py
        # sehingga update status/log setelahnya hilang.
        db.create_execution(execution_id, workflow_id, flow_data)

    async def _log_step(step: ExecutionStep) -> None:
        db.append_execution_log(execution_id, step.node_id, step.kind.value, step.status, step.output)

    orch = StatefulOrchestrator(graph, trigger_input=trigger_input,
                                owner_email=owner_email)
    try:
        steps = await orch.run(on_step=_log_step)
        status = "completed"
        db.update_execution_status(execution_id, status)
        result = {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": status,
            "steps": [s.model_dump() for s in steps],
        }
    except Exception as exc:  # noqa: BLE001
        status = "error"
        db.update_execution_status(execution_id, status)
        result = {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": status,
            "error": str(exc),
        }
    return result


_BG_TASKS: dict[str, asyncio.Task] = {}


async def _spawn_execution(workflow_id: str, flow_data: dict, execution_id: str,
                           trigger_input: Optional[dict] = None,
                           owner_email: str = "") -> dict:
    # FASE 2.5: id dari `launch_execution` DITERUSKAN ke runner supaya log dan
    # status akhir menempel pada baris `executions` yang di-pegang klien.
    try:
        await execute_workflow_async(workflow_id, flow_data, trigger_input,
                                     execution_id=execution_id,
                                     owner_email=owner_email)
        return {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": "completed",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": "error",
            "error": str(exc),
        }


def launch_execution(workflow_id: str, flow_data: dict,
                     trigger_input: Optional[dict] = None,
                     owner_email: str = "") -> str:
    """Inicia la ejecucion en background y devuelve execution_id al instante.

    Non-blocking: retorna inmediatamente con status 'pending'.
    trigger_input diteruskan ke node Trigger (webhook payload).
    owner_email diteruskan ke node MCP agar kredensial user bisa dibaca.
    """
    execution_id = str(uuid.uuid4())
    db.create_execution(execution_id, workflow_id, flow_data)
    task = asyncio.create_task(
        _spawn_execution(workflow_id, flow_data, execution_id, trigger_input,
                         owner_email))
    _BG_TASKS[execution_id] = task
    return execution_id
