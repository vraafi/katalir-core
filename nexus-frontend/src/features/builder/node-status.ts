import type { NodeStatus } from "@/components/ui/node-status-indicator";
import type { FlowNode } from "./types";

/**
 * Jembatan status eksekusi backend -> status visual node (FASE 3).
 *
 * SUMBER: log eksekusi yang sudah ada (`GET /executions/{id}`, dipoll
 * `useExecutionPolling` setiap 2 detik). Misi mengizinkan "WebSocket ATAU
 * polling"; polling dipilih karena backend memang sudah menyediakannya, jadi
 * tidak ada endpoint/kontrak baru yang perlu ditambah (dan tidak ada risiko
 * memutus jalur eksekusi yang sudah lulus Level 3).
 *
 * Fungsi ini MURNI (tanpa React, tanpa fetch) supaya aturannya bisa diuji
 * langsung — inilah satu-satunya tempat pemetaan state di bawah ini:
 *
 *   tidak ada eksekusi                 -> semua node `initial`
 *   log node: ok                       -> `success`
 *   log node: error/failed             -> `error`
 *   eksekusi pending/running, tanpa log-> `loading`
 *   sudah terminal tapi node tanpa log -> `initial` (tidak diklaim berhasil)
 *
 * `flowing` = id node yang selesai/berjalan; dipakai untuk menandai edge
 * "sedang mengalirkan data" (`animated`).
 */
export interface ExecutionLogLike {
  node_id?: string;
  status?: string;
}

const OK = new Set(["ok", "success", "completed", "done"]);
const ERR = new Set(["error", "failed", "failure", "timeout"]);
const LIVE = new Set(["pending", "running", "queued", "in_progress", "processing"]);

export function deriveNodeStatuses(
  nodes: FlowNode[],
  logs: ExecutionLogLike[],
  executionStatus: string | null | undefined
): { byNode: Record<string, NodeStatus>; flowing: string[] } {
  const byNode: Record<string, NodeStatus> = {};
  const byId = new Map(logs.map((l) => [String(l.node_id ?? ""), String(l.status ?? "").toLowerCase()]));

  const live = executionStatus ? LIVE.has(String(executionStatus).toLowerCase()) : false;

  for (const n of nodes) {
    const s = byId.get(n.id);
    if (s && OK.has(s)) byNode[n.id] = "success";
    else if (s && ERR.has(s)) byNode[n.id] = "error";
    else if (live) byNode[n.id] = "loading";
    else byNode[n.id] = "initial";
  }

  const flowing = nodes.filter((n) => byNode[n.id] === "success" || byNode[n.id] === "loading").map((n) => n.id);
  return { byNode, flowing };
}
