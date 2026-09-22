"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type NodeMouseHandler,
  type OnConnect,
} from "@xyflow/react";
import { Maximize2, Minus, Plus } from "lucide-react";
import { CanvasEmptyState } from "./CanvasEmptyState";
import { CanvasToolbar } from "./CanvasToolbar";
import { META, type FlowNode, type Kind } from "./types";
import { NODE_TYPES } from "./nodes";
import { EDGE_TYPES } from "./edges";
import { useCanvasStore } from "./store/canvas-store";
import { useCanvasTheme } from "./themes/CanvasThemeProvider";
import { useAutoLayout } from "./hooks/useAutoLayout";

/**
 * Kanvas Builder (FASE 3 — rebuild).
 *
 * Prinsip: SEMUA warna berasal dari token tema kanvas (`--canvas-*`, `--node-*`,
 * `--edge-*`) sehingga 4 tema berganti tanpa satu pun cabang `if (theme === …)`
 * di komponen. Nilai TS tema hanya dipakai untuk hal yang tidak bisa dibaca CSS
 * oleh library (colorMode, warna Background, warna MiniMap).
 *
 * MOBILE (kontrak misi "pan default = satu jari geser canvas, BUKAN drag node"):
 * - `nodesDraggable` dimatikan saat `pointer: coarse`; drag per-node baru aktif
 *   setelah long-press (state `armedNodeId` di store).
 * - Minimap auto-hide di layar sempit, muncul lewat tombol toggle.
 * - Handle 20px + tap target 44x44 (CSS `@media (pointer: coarse)`).
 */

/**
 * Deteksi perangkat sentuh (pointer: coarse) — BUKAN lebar viewport: tablet
 * layar lebar juga butuh perilaku sentuh, dan window sempit di desktop tidak
 * boleh kehilangan drag node.
 */
export function useIsCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(pointer: coarse)");
    setCoarse(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setCoarse(e.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  return coarse;
}

export function Canvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onDropNode,
  onLoadExample,
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
  onLoadExample: () => void;
  save: () => void;
  saveState: "idle" | "saving" | "ok" | "err";
  run: () => void;
  runState: "idle" | "running" | "ok" | "err";
}) {
  const { theme } = useCanvasTheme();
  const { screenToFlowPosition, fitView, zoomIn, zoomOut } = useReactFlow<FlowNode>();
  const coarse = useIsCoarsePointer();
  const { run: runAutoLayout } = useAutoLayout();

  const armedNodeId = useCanvasStore((s) => s.armedNodeId);
  const disarmNodeDrag = useCanvasStore((s) => s.disarmNodeDrag);
  const armed = useRef<string | null>(null);
  armed.current = armedNodeId;

  const undo = useCanvasStore((s) => s.undo);
  const redo = useCanvasStore((s) => s.redo);
  const canUndo = useCanvasStore((s) => s.past.length > 0);
  const canRedo = useCanvasStore((s) => s.future.length > 0);
  const addNode = useCanvasStore((s) => s.addNode);

  // Minimap: tampil default di desktop, auto-hide di sentuh/layar sempit.
  const [minimapOpen, setMinimapOpen] = useState(true);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const check = () => setNarrow(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  const showMinimap = coarse || narrow ? minimapOpen : true;

  // Undo/redo keyboard (Cmd/Ctrl+Z, Cmd/Ctrl+Shift+Z). Diabaikan saat fokus di
  // input/textarea/contenteditable supaya tidak merampas undo teks.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || target?.isContentEditable) return;
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() !== "z") return;
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // Node yang boleh digeser: desktop semua; perangkat sentuh hanya node yang
  // sudah di-long-press (drag mode).
  const draggableNodes = useMemo(
    () => nodes.map((n) => (coarse ? { ...n, draggable: n.draggable || n.id === armedNodeId } : n)),
    [nodes, coarse, armedNodeId]
  );

  const addFirstNode = useCallback(() => {
    // Titik tengah kanvas: node mendarat di depan mata, bukan koordinat acak.
    const el = document.querySelector(".react-flow") as HTMLElement | null;
    if (!el) {
      addNode("trigger");
      return;
    }
    const box = el.getBoundingClientRect();
    const p = screenToFlowPosition({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
    addNode("trigger", p);
  }, [addNode, screenToFlowPosition]);


  return (
    <div className="k-canvas relative h-full min-w-0 flex-1" data-testid="canvas-root">
      <ReactFlow<FlowNode>
        nodes={draggableNodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={() => disarmNodeDrag()}
        colorMode={theme.colorMode}
        // Desktop: drag node langsung. Sentuh: `nodesDraggable={false}` ->
        // satu jari = pan kanvas (kontrak misi); drag per-node setelah long-press.
        nodesDraggable={!coarse}
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        // Touch: klik-untuk-menarik handle (tanpa hover) — kontrak misi.
        connectOnClick={coarse}
        selectionKeyCode="Shift"
        multiSelectionKeyCode="Control"
        // Hapus elemen terpilih: `Delete` (Windows) DAN `Backspace`.
        // Default React Flow v12 hanya `Backspace`, sehingga pengguna Windows
        // menekan Delete dan tidak terjadi apa-apa (probe: edge terseleksi=1,
        // tekan Delete -> 0 elemen terhapus; dengan Backspace -> terhapus).
        deleteKeyCode={["Delete", "Backspace"]}
        defaultEdgeOptions={{ type: "flow" }}
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
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} color={theme.gridColor} />
        <Controls position="bottom-left" showInteractive={false}>
          <ControlButton onClick={() => void zoomIn()} aria-label="Zoom In" title="Zoom In (+)">
            <Plus size={14} strokeWidth={1.75} />
          </ControlButton>
          <ControlButton onClick={() => void zoomOut()} aria-label="Zoom Out" title="Zoom Out (-)">
            <Minus size={14} strokeWidth={1.75} />
          </ControlButton>
          <ControlButton
            onClick={() => void fitView({ padding: 0.2, duration: 300 })}
            aria-label="Fit View"
            title="Fit View (0)"
          >
            <Maximize2 size={14} strokeWidth={1.75} />
          </ControlButton>
        </Controls>
        {showMinimap && (
          <MiniMap
            position="bottom-right"
            pannable
            zoomable
            maskColor={theme.minimapMask}
            nodeColor={(n) => {
              const data = (n as FlowNode).data;
              if (data?.status === "loading") return theme.pulse;
              if (data?.status === "success") return theme.successGlow;
              if (data?.status === "error") return theme.errorGlow;
              return theme.minimapNode;
            }}
          />
        )}
      </ReactFlow>

      {/* Toolbar DI LUAR ReactFlow: tombol di dalam <Panel> ikut kena transform
          viewport, sedangkan toolbar harus tetap menempel di layar. */}
      <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex flex-col items-end gap-1.5">
        {saveState === "ok" && (
          <span
            className="pointer-events-auto rounded-md border px-2 py-0.5 text-[11px]"
            style={{ borderColor: "var(--node-success-glow)", color: "var(--node-success-glow)" }}
          >
            Data disimpan ✓
          </span>
        )}
        {saveState === "err" && (
          <span
            className="pointer-events-auto rounded-md border px-2 py-0.5 text-[11px]"
            style={{ borderColor: "var(--node-error-glow)", color: "var(--node-error-glow)" }}
          >
            Gagal menyimpan ✕
          </span>
        )}
        <CanvasToolbar
          onAutoLayout={() => runAutoLayout("TB")}
          onFitView={() => void fitView({ padding: 0.2, duration: 300 })}
          onZoomIn={() => void zoomIn()}
          onZoomOut={() => void zoomOut()}
          onUndo={undo}
          onRedo={redo}
          canUndo={canUndo}
          canRedo={canRedo}
          save={save}
          saveState={saveState}
          run={run}
          runState={runState}
          minimapOpen={minimapOpen}
          onToggleMinimap={() => setMinimapOpen((v) => !v)}
          compact={narrow}
        />
        {runState === "running" && (
          <span
            className="pointer-events-auto rounded-md border px-2 py-0.5 text-[11px]"
            style={{ borderColor: "var(--node-pulse-color)", color: "var(--node-pulse-color)" }}
          >
            Eksekusi berjalan…
          </span>
        )}
        {runState === "err" && (
          <span
            className="pointer-events-auto rounded-md border px-2 py-0.5 text-[11px]"
            style={{ borderColor: "var(--node-error-glow)", color: "var(--node-error-glow)" }}
          >
            Gagal mengeksekusi ✕
          </span>
        )}
      </div>

      {nodes.length === 0 && <CanvasEmptyState onAddNode={addFirstNode} onLoadExample={onLoadExample} />}
    </div>
  );
}


