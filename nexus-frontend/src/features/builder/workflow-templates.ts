import type { Edge } from "@xyflow/react";
import type { FlowNode } from "./types";
import { demoNodes, demoEdges } from "./demo-workflow";

export type WorkflowTemplate = { id: string; name: string; description: string; nodes: FlowNode[]; edges: Edge[] };

function clean(nodes: FlowNode[], edges: Edge[]): Omit<WorkflowTemplate, "id" | "name" | "description"> {
  return { nodes: nodes.map((n) => ({ ...n, status: "initial" })), edges: edges.map((e) => ({ ...e, animated: false })) };
}

export const workflowTemplates: WorkflowTemplate[] = [
  { id: "morning-digest", name: "Daily digest", description: "Summarize the day's inputs.", ...clean(demoNodes(), demoEdges()) },
  { id: "notify", name: "Notify team", description: "Process an input and notify the team.", ...clean(demoNodes().slice(0, 3), demoEdges().slice(0, 2)) },
];
