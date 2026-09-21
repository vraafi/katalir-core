import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Edge } from "@xyflow/react";
import { apiFetch } from "@/lib/api";
import { type FlowNode } from "../types";
import { dedupeGraph } from "../node-graph";

/**
 * Layer data workflow.
 *
 * Perubahan penting (FASE B, 2026-09-21):
 *  - LIST hanya metadata (`id,name,description,created_at`) — tanpa `flow_data`.
 *    Isi graf diambil per-workflow lewat GET /workflows/{id}.
 *  - SAVE mengirim `id` bila workflow sedang terbuka supaya POST = UPDATE,
 *    bukan INSERT baru (dulu setiap klik "Simpan Alur" menumpuk baris).
 *  - Ada DELETE dan RENAME (owner-scoped di backend).
 */

export interface WorkflowListItem {
  id?: string;
  name?: string;
  description?: string;
  created_at?: string;
}

export interface WorkflowDetail extends WorkflowListItem {
  flow_data?: {
    nodes?: FlowNode[];
    edges?: Edge[];
  };
}

// Query key factory (TanStack v5)
export const workflowKeys = {
  all: ["workflows"] as const,
  list: () => [...workflowKeys.all, "list"] as const,
  detail: (id: string) => [...workflowKeys.all, "detail", id] as const,
};

async function fetchWorkflows(): Promise<WorkflowListItem[]> {
  const res = await apiFetch("/workflows");
  if (!res.ok) return [];
  const data = await res.json();
  return (data?.workflows as WorkflowListItem[]) ?? [];
}

async function fetchWorkflowDetail(id: string): Promise<WorkflowDetail | null> {
  const res = await apiFetch(`/workflows/${encodeURIComponent(id)}`);
  if (!res.ok) return null;
  const data = await res.json();
  return (data?.workflow as WorkflowDetail) ?? null;
}

/** GET /workflows (metadata, cached). */
export function useWorkflowsQuery() {
  return useQuery({
    queryKey: workflowKeys.list(),
    queryFn: fetchWorkflows,
    gcTime: 60_000,
    placeholderData: (prev) => prev,
    refetchOnWindowFocus: false,
  });
}

/**
 * POST /workflows — `id` diisi -> UPDATE (idempoten), kosong -> INSERT baru.
 * Mengembalikan { id, updated } supaya pemanggil tahu apakah baris baru dibuat.
 */
export function useSaveWorkflowMutation() {
  return useMutation<
    { id: string; updated: boolean },
    Error,
    { id?: string | null; name?: string; nodes: FlowNode[]; edges: Edge[] }
  >({
    mutationFn: async ({ id, name, nodes, edges }) => {
      const res = await apiFetch("/workflows", {
        method: "POST",
        body: JSON.stringify({
          id: id || undefined,
          name: name || "Draft Workflow",
          description: "Workflow dibuat di Builder",
          flow_data: { nodes, edges },
        }),
      });
      if (res.status !== 201) throw new Error("HTTP " + res.status);
      const data = await res.json();
      return { id: data.workflow?.id, updated: Boolean(data.updated) };
    },
  });
}

/** DELETE /workflows/{id} — owner-scoped (bukan pemilik -> 403). */
export function useDeleteWorkflowMutation() {
  return useMutation<void, Error, string>({
    mutationFn: async (id: string) => {
      const res = await apiFetch(`/workflows/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok) throw new Error("HTTP " + res.status);
    },
  });
}

/** PATCH /workflows/{id} — rename (owner-scoped). */
export function useRenameWorkflowMutation() {
  return useMutation<void, Error, { id: string; name: string }>({
    mutationFn: async ({ id, name }) => {
      const res = await apiFetch(`/workflows/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
    },
  });
}

/** Ambil detail lalu pasang ke kanvas (dipakai builder-inner). */
export async function loadWorkflowIntoCanvas(
  id: string,
  setNodes: (n: FlowNode[]) => void,
  setEdges: (e: Edge[]) => void
): Promise<boolean> {
  const detail = await fetchWorkflowDetail(id);
  if (!detail) return false;
  applyWorkflowToCanvas(detail, setNodes, setEdges);
  return true;
}

/**
 * Pasang SATU workflow (hasil GET detail) ke kanvas.
 * Dedup penuh (node + edge) supaya draf lama ber-id ganda tidak merusak render.
 */
export function applyWorkflowToCanvas(
  wf: WorkflowDetail | null | undefined,
  setNodes: (n: FlowNode[]) => void,
  setEdges: (e: Edge[]) => void
) {
  const flow = wf?.flow_data ?? {};
  if (!Array.isArray(flow.nodes) || flow.nodes.length === 0) return;
  const g = dedupeGraph({ nodes: flow.nodes, edges: (flow.edges ?? []) as Edge[] });
  setNodes(g.nodes);
  setEdges(g.edges);
}

/** Query client dipakai builder-inner untuk memuat detail saat memilih workflow. */
export function useWorkflowClient() {
  return useQueryClient();
}

