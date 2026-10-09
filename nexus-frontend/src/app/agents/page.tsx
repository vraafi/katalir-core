"use client";

import { SimplePage } from "@/components/SimplePage";
import { AgentList } from "@/features/agents";

/**
 * Halaman /agents — entitas kelas satu untuk AI Agent (TASK 5 / Fitur #1).
 *
 * Di n8n, agent hanyalah node di dalam workflow. Di sini agent punya halaman
 * sendiri dengan siklus hidup (draf → aktif → dijeda → diarsip), kanal, dan
 * eksposur MCP. Memakai `SimplePage` (pola sama dengan /templates) supaya
 * navbar minimal + provider (Auth, Query, I18n, CanvasTheme) konsisten.
 */
export default function AgentsPage() {
  return (
    <SimplePage
      title="Agents"
      subtitle="Kelola AI Agent sebagai entitas tersendiri — siklus hidup, kanal, dan eksposur MCP."
      maxW="max-w-5xl"
    >
      <AgentList />
    </SimplePage>
  );
}
