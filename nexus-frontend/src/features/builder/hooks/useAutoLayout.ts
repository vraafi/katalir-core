"use client";

import { useCallback, useState } from "react";
import dagre from "@dagrejs/dagre";
import { useReactFlow, type Edge } from "@xyflow/react";
import { useCanvasStore } from "../store/canvas-store";
import type { FlowNode } from "../types";

/**
 * Auto Layout (FASE 3) — WAJIB untuk pengguna awam: node yang baru dibuat
 * mendarat di posisi acak, dan tanpa satu klik "rapikan" alur terlihat berantakan.
 *
 * Mesin: `@dagrejs/dagre` (MIT) — pilihan default yang direkomendasikan
 * dokumentasi React Flow v12 untuk DAG. `elkjs` (EPL-2.0) sengaja TIDAK
 * dipakai: lisensinya copyleft-weak dan menambah ~7 MB worker; kebutuhan di
 * sini (graf kecil, arah TB/LR) sudah tercakup dagre.
 *
 * PENTING soal koordinat: Canvas memakai `nodeOrigin={[0.5, 0.5]}`, artinya
 * React Flow memperlakukan `node.position` sebagai TITIK TENGAH node (bukan
 * sudut kiri-atas). Dagre juga mengembalikan titik tengah, jadi hasilnya
 * dipakai LANGSUNG tanpa koreksi setengah lebar/tinggi — kalau Canvas nanti
 * mengubah nodeOrigin, konversi di bawah harus ikut diubah.
 */
export const NODE_W = 224;
export const NODE_H = 104;
export const NODE_SEP = 80;
export const RANK_SEP = 100;

export type LayoutDirection = "TB" | "LR";

/** Jarak antar-rank yang diharapkan (dipakai juga oleh spec sebagai ekspektasi). */
export function expectedRankGap(): number {
  return NODE_H + RANK_SEP;
}

/**
 * Hitung posisi node dengan dagre. Fungsi MURNI (tanpa React/DOM) supaya bisa
 * diuji langsung dan dipakai ulang di tempat lain.
 */
export function getLayoutedElements(
  nodes: FlowNode[],
  edges: Edge[],
  direction: LayoutDirection = "TB"
): { nodes: FlowNode[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes, edges };

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: NODE_SEP, ranksep: RANK_SEP });

  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) {
    // Dagre melempar bila edge menunjuk node yang tidak ada; graf dari kanvas
    // bisa mengandung sisa seperti itu (mis. setelah undo parsial).
    if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const p = g.node(n.id) as { x: number; y: number } | undefined;
      if (!p) return n;
      return { ...n, position: { x: Math.round(p.x), y: Math.round(p.y) } };
    }),
    edges,
  };
}

/**
 * Hook auto layout: jalankan dagre + animasi spring 320ms.
 *
 * Animasi TIDAK dihitung manual per-frame: kelas `react-flow--layout-anim`
 * dipasang sesaat sehingga CSS mentransisikan `transform` node ke posisi baru
 * (lihat globals.css). Pendekatan ini menghindari animasi keyframe pada
 * `.react-flow__node` yang pernah menimpa inline transform React Flow dan
 * membuat semua node menumpuk di pojok (bug nyata 2026-09-21).
 */
export function useAutoLayout() {
  const { fitView } = useReactFlow<FlowNode>();
  const [animating, setAnimating] = useState(false);

  const run = useCallback(
    (direction: LayoutDirection = "TB") => {
      const { nodes, edges, commitHistory, setNodes, setEdges } = useCanvasStore.getState();
      if (nodes.length === 0) return { nodes: 0, edges: 0 };

      commitHistory();
      const out = getLayoutedElements(nodes, edges, direction);

      const canvas = document.querySelector(".react-flow");
      canvas?.classList.add("react-flow--layout-anim");
      setAnimating(true);

      setNodes(out.nodes);
      setEdges(out.edges);

      window.setTimeout(() => {
        document.querySelector(".react-flow")?.classList.remove("react-flow--layout-anim");
        setAnimating(false);
      }, 400);

      void fitView({ padding: 0.2, duration: 300 });
      return { nodes: out.nodes.length, edges: out.edges.length };
    },
    [fitView]
  );

  return { run, animating };
}
