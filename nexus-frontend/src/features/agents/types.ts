/**
 * Tipe untuk fitur Agents (TASK 5 / Fitur #1).
 *
 * Agent adalah entitas kelas satu: punya siklus hidup (draft/active/paused/
 * archived), kanal, dan bisa diekspos sebagai MCP server.
 */

export type AgentStatus = "draft" | "active" | "paused" | "archived";

export type ChannelType =
  | "web"
  | "api"
  | "webhook"
  | "slack"
  | "schedule"
  | "mcp"
  | "embed";

export interface AgentChannel {
  type: ChannelType;
  config?: Record<string, unknown>;
  enabled?: boolean;
}

export interface Agent {
  id: string;
  name: string;
  description?: string;
  instruction?: string;
  model?: string;
  tools?: string[];
  channels?: AgentChannel[];
  memory_enabled?: boolean;
  workflow_id?: string | null;
  status: AgentStatus;
  version?: number;
  created_at?: string;
  updated_at?: string;
  /** Transisi status yang diizinkan dari status saat ini (dari server). */
  can_transition?: AgentStatus[];
}

export interface AgentListResponse {
  status: string;
  agents: Agent[];
}

export interface AgentResponse {
  status: string;
  agent: Agent;
}

export interface AgentMcpDescriptor {
  status: string;
  agent_id: string;
  name: string;
  exposed: boolean;
  reason: string | null;
  tools: string[];
  transport: string;
  endpoint: string;
  memory_enabled: boolean;
}
