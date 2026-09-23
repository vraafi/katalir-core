
import { useEffect, useRef, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { useShallow } from "zustand/react/shallow";
import { useQueryState, parseAsString } from "nuqs";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { type FlowNode, type Kind } from "./types";
import { Palette, PaletteSheet } from "./Palette";
import { Canvas } from "./Canvas";
import { ConfigPanel } from "./ConfigPanel";
import { Terminal } from "./Terminal";
import { WorkflowSidebar } from "./WorkflowSidebar";
import { useCanvasStore } from "./store/canvas-store";
import { demoWorkflow } from "./demo-workflow";
import { deriveNodeStatuses } from "./node-status";
import { HydrationReady } from "@/i18n/HydrationReady";
import { useI18n } from "@/i18n/context";
import Shell from "@/components/shell";
import {
  useWorkflowsQuery, useSaveWorkflowMutation, useDeleteWorkflowMutation,
  useRenameWorkflowMutation, useWorkflowClient, workflowKeys,
  loadWorkflowIntoCanvas, type WorkflowListItem,
} from "./hooks/useWorkflow";
import { useExecuteMutation, useExecutionPolling } from "./hooks/useExecution";
// FASE 2.2: draf dari chat (Discovery Agent) dibaca saat mount.
import { clearPendingWorkflow, peekPendingWorkflow } from "@/features/agent/workflow-spec";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function BuilderInner() {
  // FASE 5: nama landmark panel konfigurasi (lihat messages `builder.configPanelLabel`).
  const { t } = useI18n();
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
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, setNodes, setEdges, replaceWork, addNode, clearWork } =
    useCanvasStore(
      useShallow((s) => ({
        nodes: s.nodes,
        edges: s.edges,
        onNodesChange: s.onNodesChange,
        onEdgesChange: s.onEdgesChange,
        onConnect: s.onConnect,
        setNodes: s.setNodes,
        setEdges: s.setEdges,
        replaceWork: s.replaceWork,
        addNode: s.addNode,
        clearWork: s.clearWork,
      }))
    );

  const setNodeStatuses = useCanvasStore((s) => s.setNodeStatuses);
  const setFlowingEdges = useCanvasStore((s) => s.setFlowingEdges);

  const { screenToFlowPosition, updateNodeData } = useReactFlow<FlowNode>();
  const [savedId, setId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runState, setRunState] = useState<"idle" | "running" | "ok" | "err">("idle");

  const { data: workflowsData, isSuccess } = useWorkflowsQuery();
  const saveMutation = useSaveWorkflowMutation();
  const deleteMutation = useDeleteWorkflowMutation();
  const renameMutation = useRenameWorkflowMutation();
  const queryClient = useWorkflowClient();
  const execMutation = useExecuteMutation();
  const exec = useExecutionPolling();

  // FASE 3: status eksekusi backend -> status visual node + edge yang mengalir.
  // Polling sudah ada sejak Level 3 (`GET /executions/{id}` tiap 2 dtk), jadi
  // tidak ada kontrak baru — hanya pemetaan state (lihat node-status.ts).
  //
  // GUARD PENTING: kalau belum ada eksekusi sama sekali, JANGAN menulis apa
  // pun. Tanpa guard ini, menjalankan pemetaan "semua initial" akan menghapus
  // status contoh (`?demo=1` beserta edge yang mengalir) — bug yang benar-benar
  // terjadi di sesi ini: `dots=0 anim=0` pada audit pertama.
  useEffect(() => {
    const hasExecution = exec.status !== null || (exec.logs ?? []).length > 0;
    if (!hasExecution) return;
    const { byNode, flowing } = deriveNodeStatuses(nodes, exec.logs ?? [], exec.status);
    setNodeStatuses(byNode);
    setFlowingEdges(flowing);
  }, [nodes, exec.logs, exec.status, setNodeStatuses, setFlowingEdges]);

  /** Muat isi graf satu workflow (LIST hanya metadata → detail diambil di sini). */
  async function loadIntoCanvas(id: string) {
    const ok = await loadWorkflowIntoCanvas(id, setNodes, setEdges);
    if (!ok) {
      // Workflow hilang / bukan milik user: jangan tinggalkan kanvas workflow lama.
      clearWork();
    }
    return ok;
  }

  // FASE 2.2: draf dari AI punya PRIORITAS saat halaman Builder dibuka. Kalau
  // effect di bawah (daftar workflow) jalan lebih dulu, draf AI akan langsung
  // tertimpa workflow tersimpan pertama dan user melihat kanvas kosong.
  const aiDraftApplied = useRef(false);
  useEffect(() => {
    if (aiDraftApplied.current) return;
    const pending = peekPendingWorkflow();
    if (!pending) return;
    aiDraftApplied.current = true;
    replaceWork(pending.nodes, pending.edges);
    // Draf dibuang setelah diterapkan: kalau tetap tersimpan, setiap reload
    // Builder akan menimpanya lagi dan user tidak bisa membuka workflow lain.
    clearPendingWorkflow();
  }, [replaceWork]);

  // FASE 3: `?demo=1` mengisi kanvas dengan contoh workflow ber-status
  // (initial/loading/success/error). Dipakai screenshot + E2E supaya KEEMPAT
  // status bisa diukur tanpa menjalankan eksekusi nyata (yang butuh kuota LLM).
  const demoApplied = useRef(false);
  const [demoParam] = useQueryState("demo", parseAsString.withOptions({ shallow: true }));
  const demoRequested = demoParam === "1";
  useEffect(() => {
    if (demoApplied.current || demoParam !== "1") return;
    demoApplied.current = true;
    const d = demoWorkflow();
    replaceWork(d.nodes, d.edges);
  }, [demoParam, replaceWork]);

  /** CTA empty state: muat contoh workflow siap pakai. */
  function loadExample() {
    const d = demoWorkflow();
    replaceWork(d.nodes, d.edges);
  }

  // Laad workflow die in URL staat (?w=) wanneer data klaar is — NIET in render.
  useEffect(() => {
    if (!isSuccess || !Array.isArray(workflowsData) || workflowsData.length === 0) return;
    // Draf AI barusan diterapkan dan user tidak meminta workflow tertentu
    // (?w= kosong) -> hormati draf itu, jangan timpa.
    if (aiDraftApplied.current && !workflowId) return;
    // FASE 3 (race nyata): `?demo=1` = niat EKSPLISIT di URL, jadi harus
    // MENANG atas pemuatan workflow tersimpan — tanpa guard ini, daftar
    // workflow yang resolve lebih dulu (nuqs baru menyediakan `demo` setelah
    // mount, sedangkan query sudah jalan) menimpa contoh, node contoh
    // ter-unmount di tengah interaksi, dan tes connect gagal seolah bug UI.
    if (demoRequested) return;
    // FASE 3: contoh dari `?demo=1` juga tidak boleh ditimpa workflow tersimpan.
    if (demoApplied.current && !workflowId) return;
    // Zoek workflow op id uit ?w= ; als niet gevonden of geen ?w=, gebruik 'workflows[0]'
    const target = workflowId
      ? workflowsData.find((w) => w.id === workflowId)
      : workflowsData[0];
    if (target?.id) {
      // LIST tidak lagi membawa flow_data -> ambil detail lalu pasang.
      void loadIntoCanvas(target.id);
      if (workflowId !== target.id) void setWorkflowId(target.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuccess, workflowId, demoRequested]);

  const selectedNode = nodes.find((n) => n.id === (nodeId ?? selectedId)) ?? null;

  function handleNodeClick(_: unknown, node: FlowNode) {
    setSelectedId(node.id);
    void setNodeId(node.id);
  }

  function selectWorkflow(id: string | null) {
    void setWorkflowId(id);
    setSelectedId(null);
    void setNodeId(null);
    if (!id) {
      clearWork();
      return;
    }
    void loadIntoCanvas(id);
  }

  /** Ganti nama workflow (PATCH, owner-scoped) lalu segarkan daftar. */
  async function renameWorkflow(id: string, name: string) {
    try {
      await renameMutation.mutateAsync({ id, name });
      await queryClient.invalidateQueries({ queryKey: workflowKeys.list() });
    } catch (e) {
      alert("Gagal mengganti nama: " + (e instanceof Error ? e.message : e));
    }
  }

  /** Hapus workflow (DELETE, owner-scoped). Konfirmasi ada di WorkflowSidebar. */
  async function deleteWorkflow(id: string) {
    try {
      await deleteMutation.mutateAsync(id);
      // Kalau yang dihapus sedang terbuka: kosongkan kanvas + URL.
      if (savedId === id || workflowId === id) {
        setId(null);
        void setWorkflowId(null);
        clearWork();
      }
      await queryClient.invalidateQueries({ queryKey: workflowKeys.list() });
    } catch (e) {
      alert("Gagal menghapus alur: " + (e instanceof Error ? e.message : e));
    }
  }

  function onDropNode(kind: Kind, clientX: number, clientY: number) {
    const position = screenToFlowPosition({ x: clientX, y: clientY });
    addNode(kind, position);
  }

  async function save() {
    setSaveState("saving");
    try {
      // `id: savedId` -> backend UPDATE (bukan INSERT baru). Tanpa ini, setiap
      // klik "Simpan Alur" menambah baris baru bernama sama di sidebar.
      const { id, updated } = await saveMutation.mutateAsync({ id: savedId, nodes, edges });
      setId(id ?? savedId);
      setSaveState("ok");
      if (id) void setWorkflowId(id); // URL ?w= bijwerken na opslaan
      void queryClient.invalidateQueries({ queryKey: workflowKeys.list() });
      alert((updated ? "Alur diperbarui! ID: " : "Alur disimpan! ID: ") + (id ?? "?"));
    } catch (e) {
      setSaveState("err");
      alert("Gagal menyimpan alur: " + (e instanceof Error ? e.message : e));
    }
  }

  async function run() {
    setRunState("running");
    try {
      const { id } = await saveMutation.mutateAsync({ id: savedId, nodes, edges });
      const wid = id ?? savedId;
      setId(wid);
      if (id) void setWorkflowId(id);
      void queryClient.invalidateQueries({ queryKey: workflowKeys.list() });
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

  function newWorkflow() {
    clearWork();
    setId(null);
    setSelectedId(null);
    void setWorkflowId(null);
  }

  function setNodeCfg(key: string, value: string) {
    if (!selectedNode) return;
    updateNodeData(selectedNode.id, {
      ...selectedNode.data,
      config: { ...(selectedNode.data.config ?? {}), [key]: value },
    });
  }

  return (
    <Shell sessions={[]} currentSessionId={null} onSelectSession={() => {}} onNewChat={() => {}} onNewWorkflow={newWorkflow}>
    {/* TINGGI: `flex-1 min-h-0`, BUKAN `h-screen`/`h-[100dvh]`.
        Bug nyata FASE 3 (ditemukan spec C4/C11): Shell merender header sticky
        (z-10) DI ATAS `{children}` dalam kolom flex. Dengan `h-[100dvh]`, tinggi
        anak = tinggi viewport penuh sehingga kanvas meluber ke bawah header dan
        ~56px bagian atas kanvas TERTUTUP header — klik pada NodeToolbar
        (Hapus/Duplikat) node yang berada di dekat atas tidak pernah sampai ke
        kanvas (Playwright melaporkan "header intercepts pointer events").
        `flex-1 min-h-0` membuat kanvas mengisi SISA ruang di bawah header,
        sehingga tidak ada bagian kanvas yang tertutup. */}
    <div className="k-canvas flex min-h-0 flex-1 overflow-hidden">
      {/* Penanda hidrasi rute builder (lihat src/i18n/hydration-signal.ts). */}
      <HydrationReady />
      <WorkflowSidebar
        workflows={workflowsData ?? []}
        activeId={workflowId}
        onSelect={(id) => selectWorkflow(id)}
        onNew={() => selectWorkflow(null)}
        onRename={(id, name) => void renameWorkflow(id, name)}
        onDelete={(id) => void deleteWorkflow(id)}
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
        onLoadExample={loadExample}
        save={save}
        saveState={saveState}
        run={run}
        runState={runState}
      />
      {/* Panel konfigurasi desktop — muncul HANYA saat ada node terpilih.
          Sebelumnya panel ini selalu tampil (walau kosong) dengan lebar 320px,
          sehingga pada 1440px kanvas hanya tersisa 368px: kanvas jadi panel
          TERKECIL, berlawanan dengan misi ("canvas dominan, panel samping
          muted"). Terukur: kanvas 368px -> 688px saat panel tertutup.
          Di layar sempit panel ini tetap digantikan Sheet bawah. */}
      {selectedNode && (
        <aside
          data-testid="config-aside"
          aria-label={t("builder.configPanelLabel")}
          className="hidden w-80 shrink-0 flex-col gap-4 overflow-y-auto border-l p-4 lg:flex"
          style={{
            borderColor: "var(--node-border)",
            background: "var(--canvas-panel-bg)",
            color: "var(--canvas-text-primary)",
          }}
        >
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-bold uppercase tracking-wide">Konfigurasi Node</div>
            <Button variant="ghost" size="icon" aria-label="Tutup panel" onClick={() => { setSelectedId(null); void setNodeId(null); }}>
              <X size={15} strokeWidth={1.75} />
            </Button>
          </div>
          <div data-testid="config-panel-host">
            <ConfigPanel node={selectedNode} setNodeCfg={setNodeCfg} apiUrl={API_URL} workflowId={savedId} />
          </div>
        </aside>
      )}

      {/* Mobile: palette bottom-sheet (drag-up) + panel konfigurasi sebagai sheet. */}
      <PaletteSheet
        onAddNode={addNode}
        onClear={() => {
          setNodes([]);
          setEdges([]);
        }}
      />
      <Sheet
        open={!!selectedNode}
        onOpenChange={(o) => {
          if (!o) {
            setSelectedId(null);
            void setNodeId(null);
          }
        }}
        side="bottom"
        title="Konfigurasi Node"
        description={selectedNode ? (selectedNode.data?.label ?? selectedNode.data?.kind) : undefined}
      >
        {selectedNode && (
          <div data-testid="config-panel-host">
            <ConfigPanel node={selectedNode} setNodeCfg={setNodeCfg} apiUrl={API_URL} workflowId={savedId} />
          </div>
        )}
      </Sheet>
      <Terminal
        open={exec.open}
        status={exec.status}
        logs={exec.logs}
        onClose={() => { exec.stop(); exec.setOpen(false); }}
      />
    </div>
    </Shell>
  );
}
