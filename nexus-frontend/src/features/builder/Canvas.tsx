
import {
  Edge,
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type NodeChange,
  type EdgeChange,
  type NodeMouseHandler,
  type OnConnect,
} from "@xyflow/react";
import { Save, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { META, type FlowNode, type Kind } from "./types";
import { NODE_TYPES } from "./nodes";

export function Canvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onDropNode,
  save,
  saveState,
  run,
  runState,
}: {
  nodes: FlowNode[];
  edges: Edge[];
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void;
  onConnect: OnConnect;
  onNodeClick: NodeMouseHandler<FlowNode>;
  onDropNode: (kind: Kind, clientX: number, clientY: number) => void;
  save: () => void;
  saveState: "idle" | "saving" | "ok" | "err";
  run: () => void;
  runState: "idle" | "running" | "ok" | "err";
}) {
  return (
    <div className="relative h-full min-w-0 flex-1">
      <ReactFlow<FlowNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        colorMode="dark"
        panOnDrag
        panOnScroll
        zoomOnScroll
        className="h-full w-full"
        nodeOrigin={[0.5, 0.5]}
        onDragOver={(e) => {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        }}
        onDrop={(e) => {
          e.preventDefault();
          const kind = e.dataTransfer?.getData("application/reactflow") as Kind;
          if (!kind || !META[kind]) return;
          // Contoh resmi React Flow: kirim clientX/clientY MENTAH ke
          // screenToFlowPosition (sudah handle offset + zoom internal).
          onDropNode(kind, e.clientX, e.clientY);
        }}
      >
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        <Controls position="bottom-left" />
        <MiniMap nodeColor="rgb(var(--surface-elevated))" maskColor="rgba(0,0,0,0.8)" position="bottom-right" />
      </ReactFlow>

      {/* Toolbar DI LUAR ReactFlow (per rekomendasi: tombol di luar Panel) */}
      <div className="pointer-events-none absolute right-4 top-4 z-10 flex flex-col items-end gap-1">
        {saveState === "ok" && (
          <span className="pointer-events-auto rounded-md border border-success/40 bg-success/10 px-2 py-0.5 text-[11px] text-success">Data disimpan ✓</span>
        )}
        {saveState === "err" && (
          <span className="pointer-events-auto rounded-md border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] text-danger">Gagal menyimpan ✕</span>
        )}
        <div className="pointer-events-auto flex gap-2">
          <Button onClick={save} className="gap-2 bg-accent text-accent-fg hover:bg-accent-hover" disabled={saveState === "saving"} loading={saveState === "saving"}>
            {saveState !== "saving" && <Save size={15} strokeWidth={1.75} />}
            {saveState === "saving" ? "Simpan..." : "Simpan Alur"}
          </Button>
          <Button onClick={run} className="gap-2 bg-success text-accent-fg hover:brightness-95" disabled={runState === "running"} loading={runState === "running"}>
            {runState !== "running" && <Play size={15} strokeWidth={1.75} />}
            {runState === "running" ? "Menjalankan..." : "Jalankan Alur"}
          </Button>
        </div>
        {runState === "ok" && (
          <span className="pointer-events-auto rounded-md border border-success/40 bg-success/10 px-2 py-0.5 text-[11px] text-success">Eksekusi dimulai ✓</span>
        )}
        {runState === "err" && (
          <span className="pointer-events-auto rounded-md border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] text-danger">Gagal mengeksekusi ✕</span>
        )}
      </div>
    </div>
  );
}
