"use client";

import "@xyflow/react/dist/base.css";
import "@xyflow/react/dist/style.css";

import { useEffect, useRef, useState } from "react";
import {
  Edge,
  Handle,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  NodeToolbar,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import { Zap, Bot, Wrench, Save, Trash2, Plus, Play, X } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// =========================================================================
// METADATA NODOS (Trigger / Agent / MCP Tool)
// =========================================================================
const META = {
  trigger: { label: "Trigger", color: "#6C63FF", Icon: Zap, desc: "Titik inisyalisasi alur" },
  agent: { label: "Agent", color: "#16A34A", Icon: Bot, desc: "Proses via Gemini LLM" },
  mcp: { label: "MCP Tool", color: "#F59E0B", Icon: Wrench, desc: "Aksi eksternal (MCP)" },
} as const;

type Kind = keyof typeof META;
type FlowNodeData = {
  kind: Kind;
  label?: string;
  config?: Record<string, string>;
};
type FlowNode = {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: FlowNodeData;
};

// =========================================================================
// NODO CUSTOM — compacto estilo n8n (sin inputs dentro; config en sidebar)
// Hanya Ikon + Nama + Connector Tabs (Handle)
// =========================================================================
function PaletteNode(props: { id: string; data: FlowNodeData; selected?: boolean }) {
  const { deleteElements } = useReactFlow<FlowNode>();
  const id = props.id;
  const data = props.data;
  const selected = !!props.selected;
  const kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;

  function removeNode() {
    deleteElements({ nodes: [{ id }] });
  }

  return (
    <div
      className={"w-56 rounded-xl border bg-gray-800 text-[13px] text-gray-200 " +
        (selected ? " border-indigo-500 ring-2 ring-indigo-400/60 shadow-xl" : " border-gray-700 shadow-lg")}
    >
      <NodeToolbar>
        <button
          onClick={removeNode}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-red-900/60 bg-red-900/20 text-red-300 hover:bg-red-900/40"
        >
          <Trash2 size={14} />
        </button>
      </NodeToolbar>

      <div className="flex h-12 items-center gap-2.5 px-3">
        {kind !== "trigger" && (
          <Handle
            type="target"
            position={Position.Left}
            className={"!w-3 !h-10 !-left-1.5 !rounded-md !border-2 !border-gray-900 cursor-crosshair transition-colors " +
              (kind === "agent" ? "bg-green-500 hover:bg-green-400" : "bg-amber-500 hover:bg-amber-400")}
            style={{ width: "12px", height: "40px", borderRadius: "6px" }}
          />
        )}
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
          style={{ background: meta.color, color: "#fff", flexShrink: 0 }}
        >
          <Icon size={15} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold text-gray-100">{data?.label || meta.label}</span>
          <span className="block truncate text-[10px] text-zinc-500">{meta.desc}</span>
        </span>
        <Handle
          type="source"
          position={Position.Right}
          className={"!w-3 !h-10 !-right-1.5 !rounded-md !border-2 !border-gray-900 cursor-crosshair transition-colors " +
            (kind === "trigger" ? "bg-blue-500 hover:bg-blue-400" : kind === "agent" ? "bg-green-500 hover:bg-green-400" : "bg-amber-500 hover:bg-amber-400")}
          style={{ width: "12px", height: "40px", borderRadius: "6px" }}
        />
      </div>
    </div>
  );
}

// =========================================================================
// CONFIG PANEL (n8n Sidebar) — edicion por tipo de nodo mediante updateNodeData
// =========================================================================
function ConfigPanel({
  node,
  setNodeCfg,
}: {
  node: FlowNode;
  setNodeCfg: (key: string, value: string) => void;
}) {
  const data = node.data;
  const kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;
  const cfg = data?.config ?? {};

  const fieldCls =
    "nodrag mt-1 w-full rounded-md border border-gray-600 bg-gray-800 px-2.5 py-1.5 text-[13px] text-gray-100 outline-none focus:border-indigo-400 nodrag";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg"
          style={{ background: meta.color, color: "#fff" }}
        >
          <Icon size={16} />
        </span>
        <div>
          <div className="text-sm font-semibold text-gray-100">{data?.label || meta.label}</div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-500">{kind}</div>
        </div>
      </div>

      {kind === "trigger" && (
        <label className="block">
          <span className="text-[11px] text-zinc-400">Event Name</span>
          <input
            className={fieldCls}
            placeholder="Misal: Saat email masuk"
            value={cfg.event ?? ""}
            onChange={(e) => setNodeCfg("event", e.target.value)}
          />
          <span className="mt-1 block text-[10px] text-zinc-500">
            Titik yang memicu alur ini, misal event dari email atau manual.
          </span>
        </label>
      )}

      {kind === "agent" && (
        <label className="block">
          <span className="text-[11px] text-zinc-400">System Prompt</span>
          <textarea
            className={fieldCls + " h-28 resize-y"}
            placeholder="Instruksi agent (system prompt)..."
            value={cfg.prompt ?? ""}
            onChange={(e) => setNodeCfg("prompt", e.target.value)}
          />
        </label>
      )}

      {kind === "mcp" && (
        <div className="flex flex-col gap-3">
          <label className="block">
            <span className="text-[11px] text-zinc-400">Nama Tool (MCP)</span>
            <select
              className={fieldCls}
              value={cfg.tool ?? ""}
              onChange={(e) => setNodeCfg("tool", e.target.value)}
            >
              <option value="">-- Pilih tool --</option>
              <option value="web_search">Web Search</option>
              <option value="read_database">Read Database</option>
              <option value="http_request">HTTP Request</option>
              <option value="send_whatsapp">Send WhatsApp</option>
            </select>
          </label>
          <label className="block">
            <span className="text-[11px] text-zinc-400">Parameter</span>
            <input
              className={fieldCls}
              placeholder="JSON parameter / query..."
              value={cfg.param ?? ""}
              onChange={(e) => setNodeCfg("param", e.target.value)}
            />
          </label>
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = { trigger: PaletteNode, agent: PaletteNode, mcp: PaletteNode };
// =========================================================================
// BUILDER (dentro de ReactFlowProvider por useReactFlow)
// =========================================================================
function BuilderInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { screenToFlowPosition } = useReactFlow<FlowNode>();
  const seq = useRef(100);
  const [savedId, setId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runState, setRunState] = useState<"idle" | "running" | "ok" | "err">("idle");
  const [execId, setExecId] = useState<string | null>(null);
  const [execLogs, setExecLogs] = useState<any[]>([]);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const [termOpen, setTermOpen] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function renderPayload(p: any): string {
    if (p == null) return "";
    if (typeof p === "string") return p;
    try {
      const r = p.reply ?? p.instruction ?? p.result ?? p.message ?? p;
      return typeof r === "string" ? r : JSON.stringify(p).slice(0, 400);
    } catch {
      return String(p).slice(0, 400);
    }
  }

  async function pollExec(id: string) {
    try {
      const r = await fetch(`${API_URL}/executions/${id}`);
      if (!r.ok) return;
      const d = await r.json();
      const execution = d?.execution ?? d;
      const st = execution?.status ?? d?.status ?? null;
      if (st) setExecStatus(st);
      const logs = d?.logs ?? execution?.logs ?? [];
      if (Array.isArray(logs) && logs.length > 0) setExecLogs(logs);
      if (st === "completed" || st === "failed" || st === "error") {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        setExecLogs((prev) => [...prev, { step_kind: "system", status: st === "completed" ? "ok" : "error", payload: { message: `Eksekusi selesai: ${st}` } }]);
      }
    } catch {
      /* coba lagi pada interval berikutnya */
    }
  }

  function openTerminal(id: string) {
    setExecId(id);
    setExecLogs([]);
    setExecStatus("pending");
    setTermOpen(true);
    setExecLogs([{ step_kind: "system", status: "ok", payload: { message: `Memonitor execution_id: ${id}` } }]);
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => { void pollExec(id); }, 2000);
    void pollExec(id);
  }

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);
  const { updateNodeData } = useReactFlow<FlowNode>();

  function handleNodeClick(_: any, node: FlowNode) {
    setSelectedId(node.id);
  }

  // --- Cargar workflow mas reciente al montar (persistencia full) ---
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/workflows`);
        if (!res.ok) return;
        const data = await res.json();
        const list: any[] = data?.workflows ?? [];
        if (cancelled || list.length === 0) return;
        // array ya ordenado desc por created_at -> primero = mas reciente
        const latest = list[0];
        const flow = latest?.flow_data ?? {};
        if (Array.isArray(flow.nodes) && flow.nodes.length > 0) {
          setNodes(flow.nodes);
          setEdges(Array.isArray(flow.edges) ? flow.edges : []);
          console.log("Alur kerja terakhir berhasil dimuat:", flow.nodes.length, "node(s)");
        }
      } catch (err) {
        // kanvas tetap kosong, tanpa crash
        console.log("Gagal memuat workflow (kanvas kosong).", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Drag & Drop HTML5 (handlers inline -> tipo inferido por React) ---
  function onConnect(connection: { source: string; target: string }) {
    const edge: Edge = {
      id: "e_" + seq.current++,
      source: connection.source,
      target: connection.target,
      animated: true,
      style: { stroke: "#6C63FF", strokeWidth: 2 },
    };
    setEdges(addEdge(edge, edges));
  }

  function clearWork() {
    setNodes([]);
    setEdges([]);
  }

  async function save() {
    const payload = {
      name: "Draft Workflow",
      description: "Workflow creato in Builder",
      flow_data: { nodes, edges },
    };
    setSaveState("saving");
    try {
      const res = await fetch(`${API_URL}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 201) {
        const data = await res.json();
        setId(data.workflow?.id);
        setSaveState("ok");
        alert("Alur disimpan! ID: " + (data.workflow?.id ?? "?"));
      } else {
        setSaveState("err");
        alert("Gagal menyimpan alur (HTTP " + res.status + ").");
      }
    } catch (e) {
      setSaveState("err");
      alert("Gagal menyimpan alur: " + e);
    }
  }

  async function run() {
    // Guarda primero (si hay cambios) para obtener workflow_id
    setRunState("running");
    try {
      const payload = {
        name: "Draft Workflow",
        description: "Workflow creato in Builder",
        flow_data: { nodes, edges },
      };
      let workflowId = savedId;
      if (workflowId) {
        // Re-guardar para sincronizar cambios en Supabase y obtener id actual
        const res = await fetch(`${API_URL}/workflows`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (res.status === 201) {
          const data = await res.json();
          workflowId = data.workflow?.id ?? workflowId;
          setId(workflowId);
        }
      } else {
        const res = await fetch(`${API_URL}/workflows`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (res.status === 201) {
          const data = await res.json();
          workflowId = data.workflow?.id;
          setId(workflowId);
        } else {
          throw new Error("Gagal menyimpan workflow (HTTP " + res.status + ")");
        }
      }
      if (!workflowId) throw new Error("workflow_id kosong setelah save.");
      // Eksekusi backend (non-blocking, status pending)
      const execRes = await fetch(`${API_URL}/workflows/${workflowId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (execRes.status === 202) {
        const exec = await execRes.json();
        setRunState("ok");
        const eid = exec.execution_id ?? exec?.data?.execution_id ?? null;
        if (eid) openTerminal(String(eid));
        alert("Eksekusi dimulai! Task ID: " + (eid ?? "?") + " (status: " + (exec.status ?? "pending") + ")");
      } else {
        setRunState("err");
        alert("Gagal mengeksekusi alur (HTTP " + execRes.status + ").");
      }
    } catch (e) {
      setRunState("err");
      alert("Gagal mengeksekusi alur: " + e);
    }
  }

  // --- Node seleccionado para la sidebar de configuracion ---
  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;
  function setNodeCfg(key: string, value: string) {
    if (!selectedNode) return;
    updateNodeData(selectedNode.id, {
      ...selectedNode.data,
      config: { ...(selectedNode.data.config ?? {}), [key]: value },
    });
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-gray-100">
      {/* Sidebar (Palette) — DRAGGABLE SOURCE */}
      <aside className="flex w-64 flex-col gap-4 border-r border-gray-700 bg-gray-900 p-4">
        <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">Node Palette</div>
        <p className="text-[11px] leading-snug text-zinc-500">Drag a node onto the canvas, or click to place it.</p>
        {Object.keys(META).map((k) => {
          const kind: Kind = k as Kind;
          const meta = META[kind];
          const Icon = meta.Icon;
          return (
            <div
              key={kind}
              draggable
              onDragStart={(e) => {
                e.dataTransfer?.setData("application/reactflow", kind);
                if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
              }}
              onClick={() =>
                setNodes([
                  ...nodes,
                  {
                    id: `${kind}-${seq.current++}`,
                    type: kind,
                    position: { x: 80 + Math.random() * 120, y: 80 + Math.random() * 200 },
                    data: { kind, label: meta.label },
                  },
                ])
              }
              className="flex w-full cursor-grab items-center gap-3 rounded-xl border border-gray-700 bg-gray-800 px-3 py-3 text-left transition hover:border-indigo-500/60 hover:bg-gray-700"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: meta.color, color: "#fff" }}>
                <Icon size={15} />
              </span>
              <span className="flex-1 text-left">
                <span className="block text-sm font-semibold text-gray-100">{meta.label}</span>
                <span className="block text-[11px] text-zinc-500">Drag to canvas</span>
              </span>
              <Plus size={14} className="text-zinc-500" />
            </div>
          );
        })}
        <button
          onClick={clearWork}
          className="flex w-full items-center gap-2 rounded-xl border border-red-900/40 bg-red-900/10 px-3 py-2 text-sm text-red-300 hover:bg-red-900/20"
        >
          <Trash2 size={14} /> Cavira alur
        </button>
      </aside>
{/* Canvas — DROP ZONE */}
      <div
        className="flex-1 overflow-hidden"
        onDragOver={(e) => {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        }}
        onDrop={(e) => {
          e.preventDefault();
          const kind = e.dataTransfer?.getData("application/reactflow") as Kind;
          if (!kind || !META[kind]) return;
          const nodeEl = e.target as HTMLElement;
          const rect = nodeEl.getBoundingClientRect();
          const position = screenToFlowPosition({ x: e.clientX - rect.left, y: e.clientY - rect.top });
          setNodes([...nodes, { id: `${kind}-${seq.current++}`, type: kind, position, data: { kind, label: META[kind].label } }]);
        }}
      >
        <ReactFlow<FlowNode>
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={handleNodeClick}
          colorMode="dark"
          className="h-full"
        >
          <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
          <Controls position="bottom-left" />
          <MiniMap
            nodeColor="#2d3748"
            maskColor="rgba(0,0,0,0.8)"
            position="bottom-right"
          />
          <Panel position="top-right">
            <div className="flex flex-col items-end gap-1">
              {saveState === "ok" && (
                <span className="rounded-md border border-green-500/40 bg-green-500/10 px-2 py-0.5 text-[11px] text-green-300">
                  Data disimpan ✓
                </span>
              )}
              {saveState === "err" && (
                <span className="rounded-md border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-300">
                  Gagal menyimpan ✕
                </span>
              )}
              <button
                onClick={save}
                className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-lg hover:bg-blue-700"
              >
                <Save size={15} /> {saveState === "saving" ? "Simpan..." : "Simpan Alur"}
              </button>
              <button
                onClick={run}
                className="flex items-center gap-2 rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-lg hover:bg-green-700"
              >
                <Play size={15} /> {runState === "running" ? "Menjalankan..." : "Jalankan Alur"}
              </button>
              {runState === "ok" && (
                <span className="rounded-md border border-green-500/40 bg-green-500/10 px-2 py-0.5 text-[11px] text-green-300">
                  Eksekusi dimulai ✓
                </span>
              )}
              {runState === "err" && (
                <span className="rounded-md border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-300">
                  Gagal mengeksekusi ✕
                </span>
              )}
            </div>
          </Panel>
        </ReactFlow>
      </div>
      {/* Sidebar Configuración (n8n) â€” OPEN cuando un nodo es seleccionado */}
      <aside className="flex w-80 flex-col gap-4 overflow-y-auto border-l border-gray-700 bg-gray-900 p-4">
        {selectedNode ? (
          <>
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">
                Konfigurasi Node
              </div>
              <button
                onClick={() => setSelectedId(null)}
                className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 hover:bg-gray-800 hover:text-gray-100"
              >
                <X size={15} />
              </button>
            </div>
            <ConfigPanel node={selectedNode} setNodeCfg={setNodeCfg} />
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-800 text-zinc-500">
              <Zap size={18} />
            </span>
            <p className="max-w-[180px] text-[12px] leading-snug text-zinc-500">
              Klik sebuah node untuk membuka panel konfigurasinya di sini.
            </p>
          </div>
        )}
      </aside>
      {termOpen && (
        <div className="fixed inset-x-0 bottom-0 z-50 border-t border-gray-700 bg-[#1E1E1E] font-mono">
          <div className="flex items-center justify-between border-b border-gray-800 px-4 py-2">
            <span className="text-[12px] font-bold tracking-wide text-green-400">Execution Console {execStatus ? `— ${execStatus}` : ""}</span>
            <button
              onClick={() => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } setTermOpen(false); }}
              className="rounded-md px-2 py-1 text-[12px] text-gray-300 hover:bg-gray-700"
            >
              Close ✕
            </button>
          </div>
          <div className="max-h-64 space-y-0.5 overflow-y-auto p-4 text-[12px] leading-relaxed text-gray-200">
            {execLogs.length === 0 && <div className="text-gray-500">$ menunggu logs...</div>}
            {execLogs.map((l, i) => (
              <div key={i} className="whitespace-pre-wrap">
                <span className="text-gray-500">[{i + 1}]</span>{" "}
                <span className="text-cyan-300">{l?.step_kind ?? "step"}</span>{" "}
                <span className="text-gray-400">{l?.node_id ?? ""}</span>{" "}
                <span className={String(l?.status) === "error" ? "text-red-400" : "text-green-300"}>{String(l?.status ?? "")}</span>
                <span className="text-gray-200"> — {renderPayload(l?.payload)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Builder() {
  return (
    <ReactFlowProvider>
      <BuilderInner />
    </ReactFlowProvider>
  );
}