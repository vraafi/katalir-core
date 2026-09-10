import { useMutation, useQuery } from "@tanstack/react-query";
import type { Edge } from "@xyflow/react";
import { type FlowNode } from "../types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  animated?: boolean;
  style?: Record<string, string>;
}

export interface WorkflowListItem {
  id?: string;
  name?: string;
  description?: string;
  flow_data?: {
    nodes?: FlowNode[];
    edges?: FlowEdge[];
  };
}

// Query key factory (TanStack v5)
export const workflowKeys = {
  all: ["workflows"] as const,
  list: () => [...workflowKeys.all, "list"] as const,
  detail: (id: string) => [...workflowKeys.all, "detail", id] as const,
};

async function fetchWorkflows(): Promise<WorkflowListItem[]> {
  const res = await fetch(`${API_URL}/workflows`);
  if (!res.ok) return [];
  const data = await res.json();
  return (data?.workflows as WorkflowListItem[]) ?? [];
}

/** GET /workflows list (server-state, cached via gcTime). */
export function useWorkflowsQuery() {
  return useQuery({
    queryKey: workflowKeys.list(),
    queryFn: fetchWorkflows,
    gcTime: 60_000, // v5: gcTime (bukan cacheTime)
    placeholderData: (prev) => prev, // v5: keepPreviousData via placeholderData
    refetchOnWindowFocus: false,
  });
}

/** POST /workflows — save (or re-save) the canvas, returns the workflow id. */
export function useSaveWorkflowMutation() {
  return useMutation<{ id: string }, Error, { nodes: FlowNode[]; edges: Edge[] }>({
    mutationFn: async ({ nodes, edges }) => {
      const res = await fetch(`${API_URL}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Draft Workflow", description: "Workflow creato in Builder", flow_data: { nodes, edges } }),
      });
      if (res.status !== 201) throw new Error("HTTP " + res.status);
      const data = await res.json();
      return { id: data.workflow?.id };
    },
  });
}

/** Restore latest workflow into the canvas (helper, not a hook). */
export function applyWorkflowToCanvas(list: WorkflowListItem[], setNodes: (n: FlowNode[]) => void, setEdges: (e: any[]) => void) {
  if (!Array.isArray(list) || list.length === 0) return;
  const flow = list[0]?.flow_data ?? {};
  if (Array.isArray(flow.nodes) && flow.nodes.length > 0) {
    setNodes(flow.nodes);
    setEdges(Array.isArray(flow.edges) ? flow.edges : []);
  }
}