import {
  Edge,
  Panel,
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
  onDropNode: (kind: Kind, localX: number, localY: number) => void;
  save: () => void;
  saveState: "idle" | "saving" | "ok" | "err";
  run: () => void;
  runState: "idle" | "running" | "ok" | "err";
}) {
  return (
    <div
      className="flex-1 min-w-0 overflow-hidden"
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
        onDropNode(kind, e.clientX - rect.left, e.clientY - rect.top);
      }}
    >
      <ReactFlow<FlowNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        colorMode="dark"
        className="h-full"
      >
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        <Controls position="bottom-left" />
        <MiniMap nodeColor="rgb(var(--surface-elevated))" maskColor="rgba(0,0,0,0.8)" position="bottom-right" />
        <Panel position="top-right">
          <div className="flex flex-col items-end gap-1">
            {saveState === "ok" && (
              <span className="rounded-md border border-success/40 bg-success/10 px-2 py-0.5 text-[11px] text-success">Data disimpan ✓</span>
            )}
            {saveState === "err" && (
              <span className="rounded-md border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] text-danger">Gagal menyimpan ✕</span>
            )}
            <Button onClick={save} className="gap-2 bg-accent text-accent-fg hover:bg-accent-hover" disabled={saveState === "saving"} loading={saveState === "saving"}>
              {saveState !== "saving" && <Save size={15} strokeWidth={1.75} />}
              {saveState === "saving" ? "Simpan..." : "Simpan Alur"}
            </Button>
            <Button onClick={run} className="gap-2 bg-success text-accent-fg hover:brightness-95" disabled={runState === "running"} loading={runState === "running"}>
              {runState !== "running" && <Play size={15} strokeWidth={1.75} />}
              {runState === "running" ? "Menjalankan..." : "Jalankan Alur"}
            </Button>
            {runState === "ok" && (
              <span className="rounded-md border border-success/40 bg-success/10 px-2 py-0.5 text-[11px] text-success">Eksekusi dimulai ✓</span>
            )}
            {runState === "err" && (
              <span className="rounded-md border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] text-danger">Gagal mengeksekusi ✕</span>
            )}
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}