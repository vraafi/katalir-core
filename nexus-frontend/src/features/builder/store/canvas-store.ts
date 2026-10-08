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
import type { NodeStatus } from "@/components/ui/node-status-indicator";
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

  // --- FASE 3 -----------------------------------------------------------------
  /** Hapus satu node + edge yang menempel padanya (dipakai kartu node). */
  removeNode: (id: string) => void;
  /** Salin node (offset 32px) dengan id baru yang dijamin unik. */
  duplicateNode: (id: string) => void;
  /** Node yang sedang dalam mode geser (hasil long-press di perangkat sentuh). */
  armedNodeId: string | null;
  armNodeDrag: (id: string) => void;
  disarmNodeDrag: () => void;
  /** Tulis status eksekusi ke node (dari polling /executions/{id}). */
  setNodeStatuses: (byNodeId: Record<string, NodeStatus>) => void;
  /** Tandai edge yang sedang mengalirkan data (animated). */
  setFlowingEdges: (sourceIds: string[]) => void;

  // --- Undo/redo (toolbar) ----------------------------------------------------
  past: CanvasSnapshot[];
  future: CanvasSnapshot[];
  /** Simpan keadaan SEKARANG ke tumpukan undo (dipanggil SEBELUM mutasi). */
  commitHistory: () => void;
  undo: () => void;
  redo: () => void;
}

interface CanvasSnapshot {
  nodes: FlowNode[];
  edges: Edge[];
}

/**
 * Batas tumpukan undo. 50 langkah: cukup untuk "salah klik" yang realistis,
 * dan tiap snapshot hanya menyimpan referensi ke array node/edge (tidak
 * menyalin isinya), jadi memori tetap kecil meski kanvas punya 100+ node.
 */
const HISTORY_LIMIT = 50;


export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],

  onNodesChange: (changes) => {
    // Hapus lewat keyboard (Delete/Backspace) TIDAK melewati removeNode, jadi
    // riwayat undo dicatat di sini juga supaya undo konsisten untuk kedua jalur.
    if (changes.some((c) => c.type === "remove")) get().commitHistory();
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
          // FASE 3: edge baru memakai tipe kustom `flow` (BaseEdge +
          // getSmoothStepPath) dan TIDAK langsung beranimasi — animasi hanya
          // saat data benar-benar mengalir (lihat setFlowingEdges).
          // Warna TIDAK di-set di sini: berasal dari token tema via CSS.
          type: "flow",
          animated: false,
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
    get().commitHistory();
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
          data: {
            kind,
            label: kind,
            // Node Code TANPA `config.code` langsung gagal saat dijalankan dan
            // juga ditolak validasi draf — jadi node baru akan terasa "rusak"
            // padahal cuma belum diisi. Contoh dua baris ini membuat node baru
            // langsung bisa di-Run, sekaligus memperagakan kontraknya
            // (tetapkan `result`).
            ...(kind === "code"
              ? {
                  config: {
                    language: "python",
                    timeout_s: "30",
                    code: 'result = 1 + 1',
                  },
                }
              : {}),
          },
        },
      ],
    });
  },

  clearWork: () => set({ nodes: [], edges: [] }),

  // --- FASE 3 -----------------------------------------------------------------

  removeNode: (id) => {
    get().commitHistory();
    set({
      nodes: get().nodes.filter((n) => n.id !== id),
      // Edge yang menunjuk node terhapus WAJIB ikut dibuang: React Flow
      // mencetak error dan edge itu tidak akan pernah bisa dilihat lagi.
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      armedNodeId: null,
    });
  },

  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id);
    if (!src) return;
    get().commitHistory();
    const current = get().nodes;
    const newId = nextNodeId(src.data?.kind ?? "agent", current.map((n) => n.id));
    set({
      nodes: [
        ...current,
        {
          ...src,
          id: newId,
          selected: false,
          position: { x: src.position.x + 32, y: src.position.y + 32 },
          data: { ...src.data, label: `${src.data?.label ?? src.data?.kind ?? "node"} copy` },
        },
      ],
    });
  },

  armedNodeId: null,
  armNodeDrag: (id) => set({ armedNodeId: id }),
  disarmNodeDrag: () => set({ armedNodeId: null }),

  setNodeStatuses: (byNodeId) => {
    // PENTING: hanya tulis bila ADA yang berubah. `map()` selalu membuat array
    // baru, dan pemanggil (efek di builder-inner) bergantung pada identitas
    // `nodes` — tanpa penjagaan ini efek <-> setter akan berputar tanpa henti.
    let changed = false;
    const next = get().nodes.map((n) => {
      const want = byNodeId[n.id];
      if (want && want !== n.data?.status) {
        changed = true;
        return { ...n, data: { ...n.data, status: want } };
      }
      return n;
    });
    if (changed) set({ nodes: next });
  },

  setFlowingEdges: (sourceIds) => {
    const set$ = new Set(sourceIds);
    let changed = false;
    const next = get().edges.map((e) => {
      const shouldFlow = set$.has(e.source);
      if (Boolean(e.animated) === shouldFlow) return e;
      changed = true;
      return { ...e, animated: shouldFlow };
    });
    if (changed) set({ edges: next });
  },

  past: [],
  future: [],
  commitHistory: () =>
    set((s) => ({
      past: [...s.past, { nodes: s.nodes, edges: s.edges }].slice(-HISTORY_LIMIT),
      future: [],
    })),
  undo: () => {
    const { past, future, nodes, edges } = get();
    if (past.length === 0) return;
    const prev = past[past.length - 1];
    set({
      past: past.slice(0, -1),
      future: [...future, { nodes, edges }].slice(-HISTORY_LIMIT),
      nodes: prev.nodes,
      edges: prev.edges,
      armedNodeId: null,
    });
  },
  redo: () => {
    const { past, future, nodes, edges } = get();
    if (future.length === 0) return;
    const next = future[future.length - 1];
    set({
      future: future.slice(0, -1),
      past: [...past, { nodes, edges }].slice(-HISTORY_LIMIT),
      nodes: next.nodes,
      edges: next.edges,
      armedNodeId: null,
    });
  },
}));