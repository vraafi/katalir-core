import { Zap, Bot, Wrench, CalendarClock } from "lucide-react";
import type { NodeStatus } from "@/components/ui/node-status-indicator";

export const META = {
  trigger: { label: "Trigger", color: "rgb(99, 102, 241)", Icon: Zap, desc: "Titik inisyalisasi alur" },
  cron_trigger: { label: "Jadwal (Cron)", color: "rgb(168, 85, 247)", Icon: CalendarClock, desc: "Jalankan otomatis sesuai jadwal cron" },
  agent: { label: "Agent", color: "rgb(34, 197, 94)", Icon: Bot, desc: "Proses via Gemini LLM" },
  mcp: { label: "MCP Tool", color: "rgb(245, 158, 11)", Icon: Wrench, desc: "Aksi eksternal (MCP)" },
} as const;

export type Kind = keyof typeof META;

export type FlowNodeData = {
  kind: Kind;
  label?: string;
  config?: Record<string, string>;
  /**
   * Status eksekusi node (FASE 3). Diisi builder-inner dari log eksekusi
   * backend (polling `/executions/{id}`) — lihat `deriveNodeStatuses`.
   */
  status?: NodeStatus;
};

export type FlowNode = {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: FlowNodeData;
  /** React Flow: dimatikan di perangkat sentuh sampai long-press (drag mode). */
  draggable?: boolean;
  selected?: boolean;
  className?: string;
};