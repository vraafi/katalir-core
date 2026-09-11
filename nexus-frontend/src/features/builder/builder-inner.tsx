
import { useEffect, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { useShallow } from "zustand/react/shallow";
import { useQueryState, parseAsString } from "nuqs";
import { X, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type FlowNode, type Kind } from "./types";
import { Palette } from "./Palette";
import { Canvas } from "./Canvas";
import { ConfigPanel } from "./ConfigPanel";
import { Terminal } from "./Terminal";
import { WorkflowSidebar } from "./WorkflowSidebar";
import { useCanvasStore } from "./store/canvas-store";
import { useWorkflowsQuery, useSaveWorkflowMutation, applyWorkflowToCanvas, type WorkflowListItem } from "./hooks/useWorkflow";
import { useExecuteMutation, useExecutionPolling } from "./hooks/useExecution";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function BuilderInner() {
  // --- URL state (nuqs): ?w=<workflowId>&n=<nodeId> = source of truth, shallow ---
  const [workflowId, setWorkflowId] = useQueryState(
    "w",
    parseAsString.withOptions({ shallow: true, clearOnDefault: true })
  );
  const [nodeId, setNodeId] = useQueryState(
    "n",
    parseAsString.withOptions({ shallow: true, clearOnDefault: true })
  );

  // --- canvas state via Zustand store (single-source-of-truth) ---
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, setNodes, setEdges, addNode, clearWork } =
    useCanvasStore(
      useShallow((s) => ({
        nodes: s.nodes,
        edges: s.edges,
        onNodesChange: s.onNodesChange,
        onEdgesChange: s.onEdgesChange,
        onConnect: s.onConnect,
        setNodes: s.setNodes,
        setEdges: s.setEdges,
        addNode: s.addNode,
        clearWork: s.clearWork,
      }))
    );

  const { screenToFlowPosition, updateNodeData } = useReactFlow<FlowNode>();
  const [savedId, setId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runState, setRunState] = useState<"idle" | "running" | "ok" | "err">("idle");

  const { data: workflowsData, isSuccess } = useWorkflowsQuery();
  const saveMutation = useSaveWorkflowMutation();
  const execMutation = useExecuteMutation();
  const exec = useExecutionPolling();

  // Laad workflow die in URL staat (?w=) wanneer data klaar is — NIET in render.
  useEffect(() => {
    if (!isSuccess || !Array.isArray(workflowsData) || workflowsData.length === 0) return;
    // Zoek workflow op id uit ?w= ; als niet gevonden of geen ?w=, gebruik 'workflows[0]'
    const target = workflowId
      ? workflowsData.find((w) => w.id === workflowId)
      : workflowsData[0];
    if (target?.id) {
      applyWorkflowToCanvas([target], setNodes, setEdges);
      if (workflowId !== target.id) void setWorkflowId(target.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuccess, workflowId]);

  const selectedNode = nodes.find((n) => n.id === (nodeId ?? selectedId)) ?? null;

  function handleNodeClick(_: unknown, node: FlowNode) {
    setSelectedId(node.id);
    void setNodeId(node.id);
  }

  function selectWorkflow(id: string | null) {
    void setWorkflowId(id);
    setSelectedId(null);
    void setNodeId(null);
    if (!id) clearWork();
  }

  function onDropNode(kind: Kind, clientX: number, clientY: number) {
    const position = screenToFlowPosition({ x: clientX, y: clientY });
    addNode(kind, position);
  }

  async function save() {
    setSaveState("saving");
    try {
      const { id } = await saveMutation.mutateAsync({ nodes, edges });
      setId(id ?? savedId);
      setSaveState("ok");
      if (id) void setWorkflowId(id); // URL ?w= bijwerken na opslaan
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
      const wid = id ?? savedId;
      setId(wid);
      if (id) void setWorkflowId(id);
      if (!wid) throw new Error("workflow_id kosong setelah save.");
      const resp = await execMutation.mutateAsync({ workflowId: wid });
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
      <WorkflowSidebar
        workflows={workflowsData ?? []}
        activeId={workflowId}
        onSelect={(id) => selectWorkflow(id)}
        onNew={() => selectWorkflow(null)}
      />
      <Palette onAddNode={addNode} onClear={() => setNodes([])} />
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
              <Button variant="ghost" size="icon" aria-label="Tutup panel" onClick={() => { setSelectedId(null); void setNodeId(null); }}>
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
