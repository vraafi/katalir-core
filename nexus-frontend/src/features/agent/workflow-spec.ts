// workflow-spec.ts — jembatan "draf dari AI" -> canvas React Flow.
//
// KENAPA ADA VALIDASI DI SINI (padahal backend sudah memvalidasi):
// kanvas adalah UI yang tidak boleh crash. Payload `meta.workflow` datang dari
// jaringan (bisa basi, bisa beda versi, bisa diubah proxy), jadi diperlakukan
// sebagai data TIDAK terpercaya: `parseAgentWorkflow` memeriksa ulang bentuk,
// membuang item rusak, dan mengembalikan null alih-alih melempar error.
// Hasilnya: satu node cacat tidak pernah membuat halaman putih.
import type { Edge } from "@xyflow/react";
import type { FlowNode, Kind, FlowNodeData } from "@/features/builder/types";

/** Draf workflow yang dipulangkan backend di `meta.workflow`. */
export type AgentWorkflow = {
  name: string;
  nodes: FlowNode[];
  edges: Edge[];
};

/** Kunci penyimpanan draf sementara (agar pindah halaman tidak menghilangkannya). */
export const PENDING_WORKFLOW_KEY = "katalir.workflow.pending.v1";

const KINDS: Kind[] = ["trigger", "agent", "mcp"];

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function parseNode(raw: unknown): FlowNode | null {
  const n = asRecord(raw);
  if (!n) return null;
  const id = typeof n.id === "string" ? n.id.trim() : "";
  if (!id) return null;
  const data = asRecord(n.data) ?? {};
  const kindRaw = typeof data.kind === "string" ? data.kind : n.type;
  if (typeof kindRaw !== "string" || !KINDS.includes(kindRaw as Kind)) return null;
  const pos = asRecord(n.position) ?? {};
  const x = typeof pos.x === "number" && Number.isFinite(pos.x) ? pos.x : 0;
  const y = typeof pos.y === "number" && Number.isFinite(pos.y) ? pos.y : 0;
  // config dipakai ConfigPanel; hanya string/number/boolean yang aman dirender.
  const rawCfg = asRecord(data.config) ?? {};
  const config: Record<string, string> = {};
  for (const [k, v] of Object.entries(rawCfg)) {
    if (typeof v === "string") config[k] = v;
    else if (typeof v === "number" || typeof v === "boolean") config[k] = String(v);
  }
  const kind = kindRaw as Kind;
  const nodeData: FlowNodeData = {
    kind,
    label: typeof data.label === "string" && data.label ? data.label : id,
    config,
  };
  return { id, type: kind, position: { x, y }, data: nodeData };
}

function parseEdge(raw: unknown, known: Set<string>): Edge | null {
  const e = asRecord(raw);
  if (!e) return null;
  const source = typeof e.source === "string" ? e.source : "";
  const target = typeof e.target === "string" ? e.target : "";
  // Edge ke node yang tidak ada = garis menggantung di kanvas -> buang.
  if (!source || !target || !known.has(source) || !known.has(target)) return null;
  const id = typeof e.id === "string" && e.id ? e.id : `${source}->${target}`;
  return {
    id,
    source,
    target,
    animated: e.animated === true,
    style: { stroke: "rgb(99, 102, 241)", strokeWidth: 2 },
  };
}

/**
 * Validasi defensif payload `meta.workflow` -> siap dipakai canvas, atau null.
 * Tidak pernah melempar. Node/edge rusak dibuang, sisanya tetap dipakai.
 */
export function parseAgentWorkflow(raw: unknown): AgentWorkflow | null {
  const w = asRecord(raw);
  if (!w) return null;
  const nodesRaw = Array.isArray(w.nodes) ? w.nodes : [];
  const nodes = nodesRaw.map(parseNode).filter((n): n is FlowNode => n !== null);
  if (!nodes.length) return null;
  const known = new Set(nodes.map((n) => n.id));
  const edgesRaw = Array.isArray(w.edges) ? w.edges : [];
  const seen = new Set<string>();
  const edges: Edge[] = [];
  for (const item of edgesRaw) {
    const e = parseEdge(item, known);
    if (!e || seen.has(e.id)) continue;   // dedupe: id ganda bikin React warning
    seen.add(e.id);
    edges.push(e);
  }
  return {
    name: typeof w.name === "string" && w.name ? w.name : "Workflow AI",
    nodes,
    edges,
  };
}

/** Simpan draf agar tidak hilang saat user pindah ke halaman Builder. */
export function savePendingWorkflow(wf: AgentWorkflow): void {
  try {
    localStorage.setItem(PENDING_WORKFLOW_KEY, JSON.stringify(wf));
  } catch {
    // storage penuh/diblokir: kanvas tetap terisi di sesi ini, jadi bukan fatal.
  }
}

/** Baca draf tanpa menghapusnya (dipakai Builder saat mount/reload). */
export function peekPendingWorkflow(): AgentWorkflow | null {
  try {
    const raw = localStorage.getItem(PENDING_WORKFLOW_KEY);
    return raw ? parseAgentWorkflow(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

/** Hapus draf (setelah user memilih workflow tersimpan / memulai kanvas baru). */
export function clearPendingWorkflow(): void {
  try {
    localStorage.removeItem(PENDING_WORKFLOW_KEY);
  } catch {
    /* tidak fatal */
  }
}
