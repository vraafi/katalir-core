import { Zap, Bot, Wrench } from "lucide-react";

export const META = {
  trigger: { label: "Trigger", color: "rgb(var(--accent))", Icon: Zap, desc: "Titik inisyalisasi alur" },
  agent: { label: "Agent", color: "rgb(var(--success))", Icon: Bot, desc: "Proses via Gemini LLM" },
  mcp: { label: "MCP Tool", color: "rgb(var(--warning))", Icon: Wrench, desc: "Aksi eksternal (MCP)" },
} as const;

export type Kind = keyof typeof META;

export type FlowNodeData = {
  kind: Kind;
  label?: string;
  config?: Record<string, string>;
};

export type FlowNode = {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: FlowNodeData;
};