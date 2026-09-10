
import { useRef, useState } from "react";
import {
  Edge, addEdge, useEdgesState, useNodesState, useReactFlow,
} from "@xyflow/react";
import { X, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type FlowNode, type Kind } from "./types";
import { Palette } from "./Palette";
import { Canvas } from "./Canvas";
import { ConfigPanel } from "./ConfigPanel";
import { Terminal } from "./Terminal";
import { useWorkflowsQuery, useSaveWorkflowMutation, applyWorkflowToCanvas } from "./hooks/useWorkflow";
import { useExecuteMutation, useExecutionPolling } from "./hooks/useExecution";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function BuilderInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { screenToFlowPosition } = useReactFlow<FlowNode>();
  const seq = useRef(100);
  const [savedId, setId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runState, setRunState] = useState<"idle" | "running" | "ok" | "err">("idle");
  const { updateNodeData } = useReactFlow<FlowNode>();

  const { data: workflowsData, isSuccess } = useWorkflowsQuery();
  const saveMutation = useSaveWorkflowMutation();
  const execMutation = useExecuteMutation();
  const exec = useExecutionPolling();

  const loadRef = useRef(false);
  if (isSuccess && !loadRef.current) {
    loadRef.current = true;
    applyWorkflowToCanvas(workflowsData ?? [], setNodes, setEdges);
  }

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;

  function handleNodeClick(_: unknown, node: FlowNode) {
    setSelectedId(node.id);
  }

  function onConnect(connection: { source: string; target: string }) {
    setEdges(addEdge({
      id: "e_" + seq.current++,
      source: connection.source,
      target: connection.target,
      animated: true,
      style: { stroke: "rgb(var(--accent))", strokeWidth: 2 },
    }, edges));
  }

  function addNode(kind: Kind) {
    setNodes([...nodes, { id: `${kind}-${seq.current++}`, type: kind, position: { x: 80 + Math.random() * 120, y: 80 + Math.random() * 200 }, data: { kind, label: kind } }]);
  }

  function onDropNode(kind: Kind, clientX: number, clientY: number) {
    const position = screenToFlowPosition({ x: clientX, y: clientY });
    setNodes([...nodes, { id: `${kind}-${seq.current++}`, type: kind, position, data: { kind, label: kind } }]);
  }

  async function save() {
    setSaveState("saving");
    try {
      const { id } = await saveMutation.mutateAsync({ nodes, edges });
      setId(id ?? savedId);
      setSaveState("ok");
      alert("Alur disimpan! ID: " + (id ?? "?"));
    } catch (e) {
      setSaveState("err");
      alert("Gagal menyimpan alur: " + (e instanceof Error ? e.message : e));
    }
  }

  async function run() {
    setRunState("running");
    try {
      const { id } = await saveMutation.mutateAsync({ nodes, edges });
      const workflowId = id ?? savedId;
      setId(workflowId);
      if (!workflowId) throw new Error("workflow_id kosong setelah save.");
      const resp = await execMutation.mutateAsync({ workflowId });
      setRunState("ok");
      const eid = resp?.execution_id ?? resp?.data?.execution_id ?? null;
      if (eid) exec.start(String(eid));
      alert("Eksekusi dimulai! Task ID: " + (eid ?? "?") + " (status: " + (resp?.status ?? "pending") + ")");
    } catch (e) {
      setRunState("err");
      alert("Gagal mengeksekusi alur: " + (e instanceof Error ? e.message : e));
    }
  }

  function setNodeCfg(key: string, value: string) {
    if (!selectedNode) return;
    updateNodeData(selectedNode.id, {
      ...selectedNode.data,
      config: { ...(selectedNode.data.config ?? {}), [key]: value },
    });
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100">
      <Palette onAddNode={addNode} onClear={() => { setNodes([]); setEdges([]); }} />
      <Canvas
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onDropNode={onDropNode}
        save={save}
        saveState={saveState}
        run={run}
        runState={runState}
      />
      <aside className="flex w-80 flex-col gap-4 overflow-y-auto border-l border-gray-700 bg-gray-900 p-4">
        {selectedNode ? (
          <>
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">Konfigurasi Node</div>
              <Button variant="ghost" size="icon" aria-label="Tutup panel" onClick={() => setSelectedId(null)}>
                <X size={15} strokeWidth={1.75} />
              </Button>
            </div>
            <ConfigPanel node={selectedNode} setNodeCfg={setNodeCfg} apiUrl={API_URL} workflowId={savedId} />
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-800 text-zinc-500">
              <Zap size={18} strokeWidth={1.25} />
            </span>
            <p className="max-w-[180px] text-[12px] leading-snug text-zinc-500">
              Klik sebuah node untuk membuka panel konfigurasinya di sini.
            </p>
          </div>
        )}
      </aside>
      <Terminal
        open={exec.open}
        status={exec.status}
        logs={exec.logs}
        onClose={() => { exec.stop(); exec.setOpen(false); }}
      />
    </div>
  );
}
