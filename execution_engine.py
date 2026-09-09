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


class MockMCPClient:
    """Cliente MCP mock para primera iteracion (sin claves API reales).

    Expone la misma interfaz que un MCPClient real (connect/list_tools/call_tool)
    para que el Registry solo dependa del protocolo MCP, no de if/else.
    """

    _TOOLS: dict[str, dict] = {
        "web_search": {"name": "web_search", "message": "Mock: busqueda web ejecutada"},
        "read_database": {"name": "read_database", "message": "Mock: lectura de base de datos ejecutada"},
        "http_request": {"name": "http_request", "message": "Mock: peticion HTTP enviada"},
        "send_whatsapp": {"name": "send_whatsapp", "message": "Mock: mensaje WhatsApp enviado"},
    }

    async def connect(self) -> None:
        await asyncio.sleep(0)  # handshake simulado (non-blocking)

    async def list_tools(self) -> list[dict]:
        return [{"name": v["name"], "description": v["message"]} for v in self._TOOLS.values()]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        desc = self._TOOLS.get(name)
        if not desc:
            raise KeyError(f"MCP tool '{name}' tidak terdaftar")
        return {"status": "success", "tool": name, "message": desc["message"], "input": arguments}


class MCPRegistry:
    """Registro de tools via protocolo MCP. Los tool nodes se invocan aqui.

    En lugar de if/else, cada herramienta es un MCPTool del catalogo expuesto
    por el cliente (list_tools) y se ejecuta por nombre con call_tool.
    """

    def __init__(self, client: Optional[Any] = None):
        self._client = client or self._build_client()

    @staticmethod
    def _build_client():
        # En esta primera iteracion se usa el Mock (sin claves reales).
        # Para usar el SDK 'mcp' estandar, definir MCP_SDK=1 (requiere conexion real).
        if os.getenv("MCP_SDK", "").strip() == "1":
            try:
                import mcp  # noqa: F401
                return _SdkMCPClient()
            except Exception:
                return MockMCPClient()
        return MockMCPClient()

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

    def __init__(self, graph: FlowGraph, registry: Optional[MCPRegistry] = None):
        self.graph = graph
        self.registry = registry or get_registry()
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
        event = cfg.get("event_name") or node.data.label or "manual"
        return {"type": "trigger.fire", "event": event, "message": f"Trigger disparado: {event}"}

    async def _exec_agent(self, node: FlowNode, inp: dict) -> dict:
        # Reasoning Agent nyata (LangChain Core) - baca System Prompt + input Trigger.
        from agent_reasoner import run_agent as reason

        cfg = node.data.config or {}
        prompt = cfg.get("system_prompt") or node.data.label or "instruccion por defecto"
        res = await reason(prompt, dict(inp))
        status = res.get("status", "success")
        if status == "success":
            return {
                "type": "agent.think",
                "received_from": inp.get("_from", "trigger"),
                "instruction": res.get("reply", ""),
                "message": f"Agent menerima input dari '{inp.get('_from', 'trigger')}' "
                           f"dan berpikir via {res.get('model', 'llm')}.",
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
        cfg = node.data.config or {}
        tool = cfg.get("tool_name") or "web_search"
        param = cfg.get("tool_param") or inp.get("instruction") or ""
        result = await self.registry.invoke(tool, {"query": param})
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
async def execute_workflow_async(workflow_id: str, flow_data: dict) -> dict:
    """Ejecuta un workflow e persiste cada paso en execution_logs."""
    graph = FlowGraph(**flow_data)
    execution_id = str(uuid.uuid4())
    db.create_execution(execution_id, workflow_id, flow_data)

    async def _log_step(step: ExecutionStep) -> None:
        db.append_execution_log(execution_id, step.node_id, step.kind.value, step.status, step.output)

    orch = StatefulOrchestrator(graph)
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


async def _spawn_execution(workflow_id: str, flow_data: dict, execution_id: str) -> dict:
    try:
        return await execute_workflow_async(workflow_id, flow_data)
    except Exception as exc:  # noqa: BLE001
        return {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": "error",
            "error": str(exc),
        }


def launch_execution(workflow_id: str, flow_data: dict) -> str:
    """Inicia la ejecucion en background y devuelve execution_id al instante.

    Non-blocking: retorna inmediatamente con status 'pending'.
    """
    execution_id = str(uuid.uuid4())
    db.create_execution(execution_id, workflow_id, flow_data)
    task = asyncio.create_task(_spawn_execution(workflow_id, flow_data, execution_id))
    _BG_TASKS[execution_id] = task
    return execution_id