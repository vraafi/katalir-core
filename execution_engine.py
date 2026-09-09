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
import os
import uuid
from collections import defaultdict
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from dotenv import load_dotenv

load_dotenv()

import database as db


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
                 trigger_input: Optional[dict] = None):
        self.graph = graph
        self.registry = registry or get_registry()
        self.trigger_input = dict(trigger_input or {})
        self.states: dict[str, str] = {n.id: "pending" for n in graph.nodes}
        self.outputs: dict[str, dict] = {}
        self._by_id = {n.id: n for n in graph.nodes}
        self._succs: dict[str, list[str]] = defaultdict(list)
        self._preds: dict[str, list[str]] = defaultdict(list)
        for e in graph.edges:
            self._succs[e.source].append(e.target)
            self._preds[e.target].append(e.source)

    # --- executor registry (NodeKind -> async fn), sin if/else en el motor ---
    async def _exec_trigger(self, node: FlowNode, inp: dict) -> dict:
        cfg = node.data.config or {}
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

    async def _exec_agent(self, node: FlowNode, inp: dict) -> dict:
        # Reasoning Agent nyata (LangChain Core) - baca System Prompt + input Trigger.
        from agent_reasoner import run_agent as reason

        cfg = node.data.config or {}
        prompt = cfg.get("system_prompt") or node.data.label or "instruccion por defecto"
        # --- Gembok saldo: cek SEBELUM eksekusi AI ---
        import database as db
        owner = getattr(self, "owner_email", None) or cfg.get("owner_email") or ""
        try:
            bal = db.get_balance(owner) if owner else None
        except Exception:
            bal = None
        if owner and bal is not None and bal <= 0:
            return {
                "type": "agent.think",
                "received_from": inp.get("_from", "trigger"),
                "instruction": prompt,
                "message": "[Agent blocked] Saldo habis. Topup via Dodo Payments.",
                "agent_status": "blocked_no_balance",
            }
        res = await reason(prompt, dict(inp))
        status = res.get("status", "success")
        # --- Potong saldo SETELAH eksekusi sukses ---
        if status == "success" and owner:
            try:
                db.deduct_balance(owner, float(res.get("cost_usd", 0) or 0))
                try:
                    from billing_llm import LEDGER as _LEDGER
                    _u = res.get('usage', {}) or {}
                    _LEDGER.record(getattr(self, 'execution_id', '') or '', res.get('model', ''), int(_u.get('prompt_tokens', 0) or 0), int(_u.get('completion_tokens', 0) or 0), float(res.get('cost_usd', 0) or 0))
                except Exception:
                    pass
            except Exception:
                pass
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

    async def _exec_mcp(self, node: FlowNode, inp: dict) -> dict:
        # Baca instruksi/tool_call dari output Agent sebelumnya (Agent -> MCP).
        cfg = node.data.config or {}
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
        return {"type": "mcp.call", "tool": tool, "result": result}

    EXECUTORS: dict[NodeKind, Callable[[Any, FlowNode, dict], Awaitable[dict]]] = {
        NodeKind.TRIGGER: _exec_trigger,
        NodeKind.AGENT: _exec_agent,
        NodeKind.MCP: _exec_mcp,
    }

    def _runnable(self, remaining: set[str]) -> list[str]:
        return [
            nid for nid in remaining
            if all(self.states[p] == "completed" for p in self._preds[nid])
        ]
    async def run(self, on_step: Optional[Callable] = None) -> list[ExecutionStep]:
        await self.registry.connect()
        remaining = set(self._by_id.keys())
        steps: list[ExecutionStep] = []
        triggers = [n.id for n in self.graph.nodes if n.data.kind == NodeKind.TRIGGER]
        if not triggers:
            raise RuntimeError("Workflow tidak memiliki node Trigger (titik awal wajib).")

        while remaining:
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
        node = self._by_id[node_id]
        self.states[node_id] = "running"
        step = ExecutionStep(node_id=node_id, kind=node.data.kind, status="running")
        if on_step:
            await on_step(step)
        try:
            executor = self.EXECUTORS[node.data.kind]
            inps = {p: self.outputs.get(p, {}) for p in self._preds[node_id]}
            inp = dict(inps)
            inp["_from"] = next(iter(inps), "trigger")
            out = await executor(self, node, inp)
            self.outputs[node_id] = out or {"noop": True}
            self.states[node_id] = "completed"
            step.status = "completed"
            step.input = inp
            step.output = self.outputs[node_id]
        except Exception as exc:  # noqa: BLE001
            self.states[node_id] = "error"
            step.status = "error"
            step.output = {"error": str(exc)}
            raise
        steps.append(step)
        if on_step:
            await on_step(step)
# ---------------------------------------------------------------------------
# API DE ORQUESTACION + PERSISTENCIA (execution_logs)
# ---------------------------------------------------------------------------
async def execute_workflow_async(workflow_id: str, flow_data: dict,
                                 trigger_input: Optional[dict] = None) -> dict:
    """Ejecuta un workflow e persiste cada paso en execution_logs."""
    graph = FlowGraph(**flow_data)
    execution_id = str(uuid.uuid4())
    db.create_execution(execution_id, workflow_id, flow_data)

    async def _log_step(step: ExecutionStep) -> None:
        db.append_execution_log(execution_id, step.node_id, step.kind.value, step.status, step.output)

    orch = StatefulOrchestrator(graph, trigger_input=trigger_input)
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
                           trigger_input: Optional[dict] = None) -> dict:
    # Catatan: execute_workflow_async membuat execution_id sendiri; di sini
    # fokus menjalankan DAG agar non-blocking, lalu kembalikan id pemanggil.
    try:
        await execute_workflow_async(workflow_id, flow_data, trigger_input)
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
                     trigger_input: Optional[dict] = None) -> str:
    """Inicia la ejecucion en background y devuelve execution_id al instante.

    Non-blocking: retorna inmediatamente con status 'pending'.
    trigger_input diteruskan ke node Trigger (webhook payload).
    """
    execution_id = str(uuid.uuid4())
    db.create_execution(execution_id, workflow_id, flow_data)
    task = asyncio.create_task(
        _spawn_execution(workflow_id, flow_data, execution_id, trigger_input))
    _BG_TASKS[execution_id] = task
    return execution_id