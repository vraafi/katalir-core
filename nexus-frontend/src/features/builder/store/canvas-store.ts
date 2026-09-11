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
  onConnect: (connection: { source: string; target: string }) => void;
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
    // Guard tegen duplicate edge id (bv. wanneer een geladen workflow edges
    // bevat die overlappen met de doorlopende seq). Zoek een uniek id dat
    // niet in de huidige edges zit.
    const existing = get().edges;
    let id = `e_${get().seq++}`;
    while (existing.some((e) => e.id === id)) {
      id = `e_${get().seq++}`;
    }
    set({
      edges: addEdge(
        {
          id,
          source: connection.source,
          target: connection.target,
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