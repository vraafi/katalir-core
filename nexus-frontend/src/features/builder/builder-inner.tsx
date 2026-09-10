import { useEffect, useRef, useState } from "react";
import {
  Edge, Panel, ReactFlow, Background, BackgroundVariant, Controls, MiniMap,
  addEdge, useEdgesState, useNodesState, useReactFlow,
} from "@xyflow/react";
import { Save, Play, Zap, Trash2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { META, type FlowNode, type Kind } from "./types";
import { NODE_TYPES } from "./nodes";
import { ConfigPanel } from "./ConfigPanel";
import { Terminal } from "./Terminal";

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
  const [execLogs, setExecLogs] = useState<any[]>([]);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const [termOpen, setTermOpen] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/workflows`);
        if (!res.ok) return;
        const data = await res.json();
        const list: any[] = data?.workflows ?? [];
        if (cancelled || list.length === 0) return;
        const latest = list[0];
        const flow = latest?.flow_data ?? {};
        if (Array.isArray(flow.nodes) && flow.nodes.length > 0) {
          setNodes(flow.nodes);
          setEdges(Array.isArray(flow.edges) ? flow.edges : []);
          console.log("Alur kerja terakhir berhasil dimuat:", flow.nodes.length, "node(s)");
        }
      } catch {
        console.log("Gagal memuat workflow (kanvas kosong).");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function onConnect(connection: { source: string; target: string }) {
    const edge: Edge = {
      id: "e_" + seq.current++,
      source: connection.source,
      target: connection.target,
      animated: true,
      style: { stroke: "rgb(var(--accent))", strokeWidth: 2 },
    };
    setEdges(addEdge(edge, edges));
  }

  function clearWork() {
    setNodes([]);
    setEdges([]);
  }

  async function save() {
    const payload = { name: "Draft Workflow", description: "Workflow creato in Builder", flow_data: { nodes, edges } };
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
    setRunState("running");
    try {
      const payload = { name: "Draft Workflow", description: "Workflow creato in Builder", flow_data: { nodes, edges } };
      let workflowId = savedId;
      const res = await fetch(`${API_URL}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 201) {
        const data = await res.json();
        workflowId = data.workflow?.id ?? workflowId;
        setId(workflowId);
      } else {
        throw new Error("Gagal menyimpan workflow (HTTP " + res.status + ")");
      }
      if (!workflowId) throw new Error("workflow_id kosong setelah save.");
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

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;
  function setNodeCfg(key: string, value: string) {
    if (!selectedNode) return;
    updateNodeData(selectedNode.id, {
      ...selectedNode.data,
      config: { ...(selectedNode.data.config ?? {}), [key]: value },
    });
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100">
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
              onClick={() => setNodes([...nodes, { id: `${kind}-${seq.current++}`, type: kind, position: { x: 80 + Math.random() * 120, y: 80 + Math.random() * 200 }, data: { kind, label: meta.label } }])}
              className="flex w-full cursor-grab items-center gap-3 rounded-xl border border-gray-700 bg-gray-800 px-3 py-3 text-left transition hover:border-accent/60 hover:bg-gray-700"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: meta.color, color: "rgb(var(--accent-fg))" }}>
                <Icon size={15} strokeWidth={1.75} />
              </span>
              <span className="flex-1 text-left">
                <span className="block text-sm font-semibold text-gray-100">{meta.label}</span>
                <span className="block text-[11px] text-zinc-500">Drag to canvas</span>
              </span>
              <Plus size={14} className="text-zinc-500" />
            </div>
          );
        })}
        <Button variant="danger" onClick={clearWork} className="w-full justify-center">
          <Trash2 size={14} strokeWidth={1.5} /> Cavira alur
        </Button>
      </aside>

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
        open={termOpen}
        status={execStatus}
        logs={execLogs}
        onClose={() => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } setTermOpen(false); }}
      />
    </div>
  );
}
