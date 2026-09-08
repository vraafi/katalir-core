"use client";

import "@xyflow/react/dist/base.css";
import "@xyflow/react/dist/style.css";

import { useRef, useState } from "react";
import {
  Edge,
  Handle,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { Zap, Bot, Wrench, Save, Trash2, Plus } from "lucide-react";

// =========================================================================
// METADATA NODOS
// =========================================================================
const META = {
  trigger: { label: "Trigger", color: "#6C63FF", Icon: Zap, desc: "Titik inisyalisasi alur" },
  agent: { label: "Agent", color: "#16A34A", Icon: Bot, desc: "Proses via Gemini LLM" },
  mcp: { label: "MCP Tool", color: "#F59E0B", Icon: Wrench, desc: "Aksi eksternal (MCP)" },
} as const;

type Kind = keyof typeof META;
type FlowNodeData = { kind: Kind; label?: string };
// Tipo de nodo compatible con la constraint `Node` de xyflow
type FlowNode = {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: { kind: Kind; label?: string }; // obligatorio (Record dexyflow)
};

// =========================================================================
// NODO CUSTOM via BaseNode + Handle
// =========================================================================
function Palette({ data }: { data?: FlowNodeData }) {
  const kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;
  return (
    <div style={{ background: "#18181b", border: `1px solid ${meta.color}`, borderRadius: 14, padding: "10px 14px", minWidth: "230px" }} className="rounded-lg">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ background: meta.color, color: "#fff", flexShrink: 0 }}>
          <Icon size={13} />
        </span>
        <span className="text-[13px] font-semibold text-gray-200" style={{ whiteSpace: "nowrap" }}>
          {data?.label || meta.label}
        </span>
        <span className="flex-1" />
        <Handle type="source" position={Position.Right} />
      </div>
      <div className="text-[11px] text-zinc-500" style={{ lineHeight: 1.3 }}>{meta.desc}</div>
    </div>
  );
}

const NODE_TYPES = { trigger: Palette, agent: Palette, mcp: Palette };

// =========================================================================
// PAGINA BUILDER
// =========================================================================
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Builder() {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const seq = useRef(100);
  const [savedId, setId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "ok" | "err">("idle");

  function addFromMenu(kind: Kind) {
    const id = `${kind}-${seq.current++}`;
    const meta = META[kind];
    setNodes([
      ...nodes,
      {
        id,
        type: kind,
        position: { x: 60 + Math.random() * 120, y: 60 + Math.random() * 220 },
        data: { kind, label: meta.label },
      },
    ]);
  }

  function onConnect(connection: { source: string; target: string }) {
    const edge: Edge = {
      id: "e_" + seq.current++,
      source: connection.source,
      target: connection.target,
    };
    setEdges(addEdge(edge, edges));
  }

  function clearWork() {
    setNodes([]);
    setEdges([]);
  }

  async function save() {
    const flow_data = { nodes, edges };
    const payload = {
      name: "Draft Workflow",
      description: "Workflow creato in Builder",
      flow_data,
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
      {/* Sidebar palette */}
      <aside className="flex w-60 flex-col gap-4 border-r border-zinc-800 bg-zinc-900 p-4">
        <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">Node Palette</div>
        {Object.keys(META).map((k) => {
          const kind: Kind = k as Kind;
          const meta = META[kind];
          const Icon = meta.Icon;
          return (
            <button
              key={kind}
              onClick={() => addFromMenu(kind)}
              className="flex w-full items-center gap-3 rounded-xl border border-zinc-700 bg-zinc-800 px-3 py-3 text-left transition hover:bg-zinc-700"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: meta.color, color: "#fff" }}>
                <Icon size={15} />
              </span>
              <span className="flex-1 text-left">
                <span className="block text-sm font-semibold text-gray-100">{meta.label}</span>
                <span className="block text-[11px] text-zinc-500">Click to addo</span>
              </span>
              <Plus size={14} className="text-zinc-500" />
            </button>
          );
        })}
        <button
          onClick={clearWork}
          className="flex w-full items-center gap-2 rounded-xl border border-red-900/40 bg-red-900/10 px-3 py-2 text-sm text-red-300 hover:bg-red-900/20"
        >
          <Trash2 size={14} /> Cavira alur
        </button>
      </aside>

      {/* Canvas */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        className="flex-1"
        colorMode="dark"
      />

      {/* Top action */}
      <div className="absolute right-4 top-4 z-10 flex flex-col items-end gap-1">
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
          className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          <Save size={15} /> {saveState === "saving" ? "Simpan..." : "Simpan Alur"}
        </button>
      </div>
    </div>
  );
}