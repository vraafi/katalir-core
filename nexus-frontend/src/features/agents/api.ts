/**
 * Klien API untuk fitur Agents (TASK 5 / Fitur #1).
 *
 * Semua fungsi memakai `apiFetch` (src/lib/api.ts) sehingga Authorization
 * Bearer JWT disuntikkan otomatis dari sesi Supabase — endpoint agent
 * owner-scoped, jadi tanpa token akan 401.
 */
import { apiFetch } from "@/lib/api";
import type {
  Agent,
  AgentChannel,
  AgentListResponse,
  AgentMcpDescriptor,
  AgentResponse,
  AgentStatus,
} from "./types";

export class AgentApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "AgentApiError";
    this.status = status;
  }
}

async function readError(res: Response, fallback: string): Promise<AgentApiError> {
  let detail = "";
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") detail = body.detail;
    else if (body && typeof body.message === "string") detail = body.message;
  } catch {
    /* body bukan JSON — pakai fallback */
  }
  return new AgentApiError(detail || `${fallback} (${res.status})`, res.status);
}

/** GET /agents — daftar agent milik user, filter status opsional. */
export async function listAgents(status?: AgentStatus): Promise<Agent[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await apiFetch(`/agents${qs}`);
  if (!res.ok) throw await readError(res, "Gagal memuat agent");
  const data = (await res.json()) as AgentListResponse;
  return data.agents ?? [];
}

/** GET /agents/{id} — detail satu agent. */
export async function getAgent(id: string): Promise<Agent> {
  const res = await apiFetch(`/agents/${encodeURIComponent(id)}`);
  if (!res.ok) throw await readError(res, "Agent tidak ditemukan");
  const data = (await res.json()) as AgentResponse;
  return data.agent;
}

/** POST /agents — buat agent baru (selalu mulai sebagai `draft`). */
export async function createAgent(input: {
  name: string;
  instruction?: string;
  model?: string;
  tools?: string[];
  channels?: AgentChannel[];
  memory_enabled?: boolean;
  description?: string;
}): Promise<Agent> {
  const res = await apiFetch("/agents", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!res.ok) throw await readError(res, "Gagal membuat agent");
  const data = (await res.json()) as AgentResponse;
  return data.agent;
}

/** PATCH /agents/{id} — perbarui agent (partial). */
export async function updateAgent(
  id: string,
  patch: Partial<{
    name: string;
    instruction: string;
    model: string;
    tools: string[];
    channels: AgentChannel[];
    memory_enabled: boolean;
    description: string;
  }>,
): Promise<Agent> {
  const res = await apiFetch(`/agents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw await readError(res, "Gagal memperbarui agent");
  const data = (await res.json()) as AgentResponse;
  return data.agent;
}

/** POST /agents/{id}/status — ubah status lewat siklus hidup yang divalidasi. */
export async function setAgentStatus(
  id: string,
  status: AgentStatus,
): Promise<Agent> {
  const res = await apiFetch(`/agents/${encodeURIComponent(id)}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw await readError(res, "Transisi status tidak diizinkan");
  const data = (await res.json()) as AgentResponse;
  return data.agent;
}

/** DELETE /agents/{id} — hapus agent (agent aktif harus dijeda/diarsip dulu). */
export async function deleteAgent(id: string): Promise<void> {
  const res = await apiFetch(`/agents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await readError(res, "Gagal menghapus agent");
}

/** GET /agents/{id}/mcp — deskripsi MCP agent (hanya `active` yang diekspos). */
export async function getAgentMcp(id: string): Promise<AgentMcpDescriptor> {
  const res = await apiFetch(`/agents/${encodeURIComponent(id)}/mcp`);
  if (!res.ok) throw await readError(res, "Gagal memuat deskripsi MCP");
  return (await res.json()) as AgentMcpDescriptor;
}
