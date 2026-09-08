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
import { Zap, Bot, Wrench, Save, Trash2, Plus } from "lucide-react";

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
// NODO CUSTOM — interactivo (input/textarea/select con sin uwguan nodrag)
// =========================================================================
function PaletteNode(props: { id: string; data: FlowNodeData; selected?: boolean }) {
  const { updateNodeData, deleteElements } = useReactFlow<FlowNode>();
  const id = props.id;
  const data = props.data;
  const selected = !!props.selected;
  const kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;
  const cfg = data?.config ?? {};

  function setCfg(key: string, value: string) {
    updateNodeData(id, { ...data, config: { ...cfg, [key]: value } });
  }

  function removeNode() {
    deleteElements({ nodes: [{ id }] });
  }

  return (
    <div
      className={"w-64 rounded-xl border bg-gray-800 text-[13px] text-gray-200" +
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

      <div className="flex items-center gap-2 border-b border-gray-700 px-3 py-2">
        {kind !== "trigger" && (
          <Handle
            type="target"
            position={Position.Left}
            className={"w-3 h-10 -left-1.5 rounded-md border-2 border-gray-900 cursor-crosshair transition-colors " +
              (kind === "agent" ? "bg-green-500 hover:bg-green-400" : "bg-amber-500 hover:bg-amber-400")}
          />
        )}
        <span
          className="flex h-6 w-6 items-center justify-center rounded-md"
          style={{ background: meta.color, color: "#fff", flexShrink: 0 }}
        >
          <Icon size={13} />
        </span>
        <span className="flex-1 font-semibold text-gray-100">{data?.label || meta.label}</span>
        <span className="rounded-md bg-gray-900 px-1.5 text-[10px] text-zinc-400">{meta.desc}</span>
        <Handle
          type="source"
          position={Position.Right}
          className={"w-3 h-10 -right-1.5 rounded-md border-2 border-gray-900 cursor-crosshair transition-colors " +
            (kind === "trigger" ? "bg-blue-500 hover:bg-blue-400" : kind === "agent" ? "bg-green-500 hover:bg-green-400" : "bg-amber-500 hover:bg-amber-400")}
        />
      </div>

      <div className="space-y-2 px-3 py-2">
        {kind === "trigger" && (
          <label className="block">
            <span className="text-[11px] text-zinc-400">Event Name</span>
            <input
              className="nodrag mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-[12px] text-gray-100 outline-none"
              placeholder="Misal: Saat email masuk"
              value={cfg.event ?? ""}
              onChange={(e) => setCfg("event", e.target.value)}
            />
          </label>
        )}

        {kind === "agent" && (
          <label className="block">
            <span className="text-[11px] text-zinc-400">System Prompt</span>
            <textarea
              className="nodrag mt-1 h-16 w-full resize-y rounded border border-gray-600 bg-gray-900 px-2 py-1 text-[12px] text-gray-100 outline-none"
              placeholder="Instruksi agent..."
              value={cfg.prompt ?? ""}
              onChange={(e) => setCfg("prompt", e.target.value)}
            />
          </label>
        )}

        {kind === "mcp" && (
          <div className="space-y-1">
            <label className="block">
              <span className="text-[11px] text-zinc-400">Nama Tool</span>
              <select
                className="nodrag mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-[12px] text-gray-100 outline-none"
                value={cfg.tool ?? ""}
                onChange={(e) => setCfg("tool", e.target.value)}
              >
                <option value="">-- Elige tool --</option>
                <option value="web_search">Web Search</option>
                <option value="read_database">Read Database</option>
                <option value="http_request">HTTP Request</option>
              </select>
            </label>
            <label className="block">
              <span className="text-[11px] text-zinc-400">Parameter</span>
              <input
                className="nodrag mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-[12px] text-gray-100 outline-none"
                placeholder="json parameter..."
                value={cfg.param ?? ""}
                onChange={(e) => setCfg("param", e.target.value)}
              />
            </label>
          </div>
        )}
      </div>
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
            </div>
          </Panel>
        </ReactFlow>
      </div>
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