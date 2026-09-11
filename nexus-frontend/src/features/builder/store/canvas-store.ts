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
  seq: number;

  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void;
  onConnect: (connection: { source: string; sourceHandle?: string | null; target: string; targetHandle?: string | null }) => void;
  setNodes: (nodes: FlowNode[]) => void;
  setEdges: (edges: Edge[]) => void;
  addNode: (kind: Kind, position?: { x: number; y: number }) => void;
  clearWork: () => void;
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],
  seq: 100,

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

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  addNode: (kind, position) => {
    const pos = position ?? {
      x: 80 + Math.random() * 120,
      y: 80 + Math.random() * 200,
    };
    set({
      nodes: [
        ...get().nodes,
        {
          id: `${kind}-${get().seq++}`,
          type: kind,
          position: pos,
          data: { kind, label: kind },
        },
      ],
    });
  },

  clearWork: () => set({ nodes: [], edges: [] }),
}));