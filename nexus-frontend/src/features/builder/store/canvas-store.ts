import { create } from "zustand";
import {
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import { type FlowNode, type Kind } from "../types";
import { dedupeGraph, nextNodeId } from "../node-graph";

/**
 * Genereert een unieke edge-id gebaseerd op de 4-tuple
 * (source, sourceHandle, target, targetHandle).
 * JSON-encode (i.p.v. plain concatenatie) omdat eenvoudige concatenatie
 * kan colliden (bijv. node "a-b" + handle "c" vs node "a" + handle "b-c").
 * Zie PR #5292 (July 2026) / @xyflow/utils addEdge.
 */
export function connectionEdgeId(c: {
  source: string;
  sourceHandle?: string | null;
  target: string;
  targetHandle?: string | null;
}): string {
  return `rf-${JSON.stringify([
    c.source,
    c.sourceHandle ?? null,
    c.target,
    c.targetHandle ?? null,
  ])}`;
}

/**
 * Zustand store voor het canvas (React Flow v12).
 * Volgt officieel state-management-patroon:
 * https://reactflow.dev/learn/advanced-use/state-management
 *
 * React Flow gebruikt Zustand intern — deze externe store is de
 * single-source-of-truth voor nodes/edges. onNodesChange/onEdgesChange
 * worden via applyNodeChanges/applyEdgeChanges in de store bijgewerkt
 * (zo reageert de canvas correct op drag/sélectie/verwijdering).
 */
interface CanvasState {
  nodes: FlowNode[];
  edges: Edge[];

  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void;
  onConnect: (connection: { source: string; sourceHandle?: string | null; target: string; targetHandle?: string | null }) => void;
  setNodes: (nodes: FlowNode[]) => void;
  setEdges: (edges: Edge[]) => void;
  /** Ganti seluruh isi kanvas dengan draf dari AI (FASE 2.2). Sengaja BUKAN
   *  `addNode` berulang: draf harus menggantikan, bukan menumpuk di atas
   *  workflow lama yang sedang terbuka. */
  replaceWork: (nodes: FlowNode[], edges: Edge[]) => void;
  addNode: (kind: Kind, position?: { x: number; y: number }) => void;
  clearWork: () => void;
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],

  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes) });
  },

  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges) });
  },

  onConnect: (connection) => {
    // Deterministic unieke id uit de 4-tuple (source/sourceHandle/target/
    // targetHandle) — voorkomt edge-id-collisie (PR #5292).
    const id = connectionEdgeId(connection);
    const existing = get().edges;
    // Dedupe: sla over als er al een edge met dezelfde 4-tuple bestaat.
    if (existing.some((e) => e.id === id)) return;
    set({
      edges: addEdge(
        {
          id,
          source: connection.source,
          sourceHandle: connection.sourceHandle ?? undefined,
          target: connection.target,
          targetHandle: connection.targetHandle ?? undefined,
          animated: true,
          style: { stroke: "rgb(var(--accent))", strokeWidth: 2 },
        },
        existing
      ),
    });
  },

  setNodes: (nodes) => {
    // Jalur RESTORE (workflow tersimpan / draf). Wajib dinormalisasi: draf lama
    // bisa punya id ganda, dan tanpa dedup React Flow mencetak
    // "two children with the same key" lalu membuang satu node.
    const g = dedupeGraph({ nodes, edges: get().edges });
    set({ nodes: g.nodes, edges: g.edges });
  },
  setEdges: (edges) => set({ edges: dedupeGraph({ nodes: get().nodes, edges }).edges }),

  replaceWork: (nodes, edges) => {
    // Draf AI / workflow tersimpan MENGGANTIKAN isi kanvas (bukan menumpuk),
    // jadi id-nya dinormalisasi di sini juga -- bukan hanya mengandalkan
    // counter, karena draf bisa memuat id arbitrer dari model.
    const g = dedupeGraph({ nodes, edges });
    set({ nodes: g.nodes, edges: g.edges });
  },

  addNode: (kind, position) => {
    const pos = position ?? {
      x: 80 + Math.random() * 120,
      y: 80 + Math.random() * 200,
    };
    const current = get().nodes;
    // Id diambil dari daftar id yang BENAR-BENAR ada di kanvas. Ini yang
    // sebelumnya hilang: store memakai counter yang tidak ikut naik saat
    // workflow di-restore, sehingga node baru bisa memakai id node lama.
    const id = nextNodeId(kind, current.map((n) => n.id));
    set({
      nodes: [
        ...current,
        {
          id,
          type: kind,
          position: pos,
          data: { kind, label: kind },
        },
      ],
    });
  },

  clearWork: () => set({ nodes: [], edges: [] }),
}));