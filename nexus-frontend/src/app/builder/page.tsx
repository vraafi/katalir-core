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
export default function Builder() {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const seq = useRef(100);

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

  function save() {
    const flow = {
      version: "1.0",
      saved_at: new Date().toISOString(),
      work: { nodes, edges },
    };
    console.log("FLOW_JSON:", JSON.stringify(flow, null, 2));
    alert("Alur disimpan! JSON sent to console (dev).");
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
      <div className="absolute right-4 top-4 z-10">
        <button
          onClick={save}
          className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          <Save size={15} /> Simpan Alur
        </button>
      </div>
    </div>
  );
}