// execution-report.ts — FASE 5: ubah hasil eksekusi menjadi laporan TERSTRUKTUR.
//
// KENAPA TERPISAH DARI UI: aturan "langkah mana yang gagal" sudah diputuskan
// backend di `execution_report.py` (node MCP bisa ber-`status=completed` tetapi
// payload-nya `status=error` — laporan yang hanya melihat `status` akan
// melaporkan "berhasil" untuk workflow yang gagal). Modul ini REPLIKASI aturan
// itu untuk jalur terstruktur, dan sengaja TIDAK menyusun kalimat baru: teks
// laporan dari backend tetap dibawa (`text`) supaya chat menampilkan bahasa yang
// sama dengan yang sudah diuji (`tests/test_execution_report.py`).
//
// Sumber data, berurutan menurut kepercayaan:
//   1. `logs` dari GET /executions/{id} — data mentah per node (paling kuat).
//   2. teks `report` backend — di-parse baris demi baris (cadangan).
//   3. tidak ada keduanya — status "error" dengan pesan jujur (bukan "sukses").
import type { AgentWorkflow } from "./workflow-spec";

export type StepStatus = "success" | "error" | "running" | "pending";

export type ReportStep = {
  id: string;
  label: string;
  status: StepStatus;
  detail: string;
};

export type ExecutionReport = {
  /** True hanya bila SELURUH langkah sukses (dipakai badge header). */
  ok: boolean;
  /** success | partial (ada yang gagal) | error (gagal total/tak terbaca). */
  status: "success" | "partial" | "error";
  okCount: number;
  failCount: number;
  durationMs: number;
  steps: ReportStep[];
  /** Laporan bahasa-manusia dari backend, apa adanya (back-compat + salin). */
  text: string;
  workflowId?: string;
  executionId?: string;
  /** Draf terkait, agar tombol "Lihat di Kanvas"/"Jalankan Ulang" di kartu
   *  laporan tetap bekerja tanpa mencari state di tempat lain. */
  workflowRef?: AgentWorkflow | null;
};

const MAX_DETAIL = 160;

/** Ringkasan satu baris dari payload apa pun (mirror `_snippet` backend). */
export function snippet(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    const rec = value as Record<string, unknown>;
    for (const key of ["summary", "message", "result", "output", "text", "error"]) {
      if (rec[key]) return snippet(rec[key]);
    }
    const parts = Object.entries(rec)
      .slice(0, 3)
      .map(([k, v]) => `${k}=${snippet(v)}`)
      .filter((p) => p && !p.endsWith("="));
    return truncate(parts.join(", "));
  }
  return truncate(String(value));
}

function truncate(text: string): string {
  const one = text.replace(/\s+/g, " ").trim();
  return one.length > MAX_DETAIL ? one.slice(0, MAX_DETAIL - 1).trimEnd() + "…" : one;
}

/** True bila langkah GAGAL walau `status`-nya 'completed' (lihat catatan modul). */
export function stepFailed(step: Record<string, unknown>): boolean {
  if (String(step.status ?? "") === "error") return true;
  const payload = step.payload;
  if (payload && typeof payload === "object") {
    const p = payload as Record<string, unknown>;
    if (p.error) return true;
    const inner = p.result;
    if (inner && typeof inner === "object") {
      const s = String((inner as Record<string, unknown>).status ?? "").toLowerCase();
      if (s === "error" || s === "failed" || s === "failure") return true;
    }
  }
  return false;
}

/** Entri TERAKHIR per node (satu node menulis baris `running` + baris akhir). */
function collapse(logs: unknown[]): Record<string, unknown>[] {
  const byNode = new Map<string, Record<string, unknown>>();
  const order: string[] = [];
  for (const row of logs) {
    if (!row || typeof row !== "object") continue; // entri kotor dari jaringan: dilewati, bukan crash
    const rec = row as Record<string, unknown>;
    const node = String(rec.node_id ?? "?");
    if (!byNode.has(node)) order.push(node);
    byNode.set(node, rec);
  }
  return order.map((n) => byNode.get(n) as Record<string, unknown>);
}

function statusOf(step: Record<string, unknown>): StepStatus {
  if (stepFailed(step)) return "error";
  const s = String(step.status ?? "");
  if (s === "completed" || s === "success") return "success";
  if (s === "running" || s === "pending") return s as StepStatus;
  return s === "" ? "pending" : "error";
}

/** Cadangan: parse teks laporan backend ("1. node — OK: detail"). */
function stepsFromText(text: string): ReportStep[] {
  const out: ReportStep[] = [];
  for (const line of text.split("\n")) {
    const m = /^\s*(\d+)\.\s+(.+?)\s+—\s+([A-Z]+)\s*(?::\s*(.*))?$/.exec(line);
    if (!m) continue;
    const [, idx, node, verdict, detail] = m;
    out.push({
      id: `${idx}-${node}`,
      label: node.trim(),
      status: verdict === "GAGAL" ? "error" : verdict === "OK" ? "success" : "pending",
      detail: (detail ?? "").trim(),
    });
  }
  return out;
}

/**
 * Susun laporan terstruktur. Tidak pernah melempar; selalu mengembalikan objek
 * yang aman dirender (UI tidak boleh blank hanya karena bentuk data berubah).
 */
export function buildExecutionReport(input: {
  text: string;
  logs?: unknown[];
  status?: string;
  durationMs?: number;
  workflowId?: string;
  executionId?: string;
  workflowRef?: AgentWorkflow | null;
}): ExecutionReport {
  const raw = Array.isArray(input.logs) ? collapse(input.logs) : [];
  let steps: ReportStep[] = raw.map((s) => ({
    id: String(s.node_id ?? "?"),
    label: String(s.node_id ?? "?"),
    status: statusOf(s),
    detail: snippet(s.payload),
  }));
  if (!steps.length) steps = stepsFromText(input.text);

  const failCount = steps.filter((s) => s.status === "error").length;
  const running = steps.filter((s) => s.status === "running" || s.status === "pending").length;
  const okCount = steps.length - failCount - running;
  const execStatus = String(input.status ?? "");
  const ok = execStatus === "completed" && failCount === 0 && running === 0 && steps.length > 0;
  // Tanpa langkah sama sekali => "error", BUKAN sukses: laporan kosong tidak boleh
  // terbaca sebagai keberhasilan (kelas kebohongan yang sama dengan §catatan modul).
  const status: ExecutionReport["status"] =
    steps.length === 0 ? "error" : failCount > 0 ? "partial" : ok ? "success" : "error";

  return {
    ok,
    status,
    okCount,
    failCount,
    durationMs: Math.max(0, input.durationMs ?? 0),
    steps,
    text: input.text,
    workflowId: input.workflowId,
    executionId: input.executionId,
    workflowRef: input.workflowRef ?? null,
  };
}
