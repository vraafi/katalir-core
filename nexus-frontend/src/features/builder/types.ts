import { Zap, Bot, Wrench, CalendarClock, Code2 } from "lucide-react";
import type { NodeStatus } from "@/components/ui/node-status-indicator";

export const META = {
  trigger: { label: "Trigger", color: "rgb(99, 102, 241)", Icon: Zap, desc: "Titik inisyalisasi alur" },
  cron_trigger: { label: "Jadwal (Cron)", color: "rgb(168, 85, 247)", Icon: CalendarClock, desc: "Jalankan otomatis sesuai jadwal cron" },
  agent: { label: "Agent", color: "rgb(34, 197, 94)", Icon: Bot, desc: "Proses via Gemini LLM" },
  mcp: { label: "MCP Tool", color: "rgb(245, 158, 11)", Icon: Wrench, desc: "Aksi eksternal (MCP)" },
  // Fitur #6 disambungkan ke produksi (2026-10-08). Node ini menjalankan kode
  // di SANDBOX: tanpa impor, tanpa jaringan, tanpa filesystem, batas 30s/128MB.
  // Warna visualnya diambil dari `--node-code-color` (lihat `cssKind`).
  code: { label: "Kode", color: "rgb(16, 185, 129)", Icon: Code2, desc: "Jalankan Python/JavaScript di sandbox" },
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