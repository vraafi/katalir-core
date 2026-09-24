// auto-run.ts — FASE 2.5: jalankan workflow hasil AI lalu ambil laporannya.
//
// KEPUTUSAN PENTING: laporan TIDAK dirangkai di sini, melainkan dibaca dari
// `report` yang dikirim backend (`execution_report.py`). Satu tempat menyusun
// bahasa = semua klien konsisten + bisa diuji tanpa browser.
//
// Alur: simpan workflow -> mulai eksekusi (202) -> poll status -> laporan.
// Semua jalur gagal mengembalikan `report` yang JUJUR (tidak pernah "sukses"
// palsu) supaya chat tidak menampilkan laporan kosong tanpa penjelasan.
import { apiFetch } from "@/lib/api";
import type { AgentWorkflow } from "./workflow-spec";

const TERMINAL = new Set(["completed", "error", "failed", "canceled"]);

export type AutoRunResult = {
  ok: boolean;
  report: string;
  workflowId?: string;
  executionId?: string;
  /** FASE 5: data TERSTRUKTUR untuk kartu laporan di chat. `logs` = baris mentah
   *  `execution_logs` (sumber paling kuat); `durationMs` diukur di sini karena
   *  backend tidak mengirim durasi eksekusi. Keduanya opsional: kalau tidak ada,
   *  UI jatuh ke `report` (teks) — tidak pernah mengarang langkah. */
  status?: string;
  logs?: unknown[];
  durationMs?: number;
};

type Options = { timeoutMs?: number; intervalMs?: number };

async function readJson(res: Response): Promise<Record<string, unknown>> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export async function autoRunWorkflow(
  wf: AgentWorkflow,
  opts: Options = {}
): Promise<AutoRunResult> {
  const t0 = Date.now();
  const timeoutMs = opts.timeoutMs ?? 45_000;
  const intervalMs = opts.intervalMs ?? 1_500;

  if (!wf.nodes.length) {
    return { ok: false, report: "Workflow kosong — tidak ada yang dijalankan.", durationMs: 0 };
  }

  // 1) Simpan dulu: eksekusi selalu bekerja pada workflow yang punya id.
  let workflowId = "";
  try {
    const res = await apiFetch("/workflows", {
      method: "POST",
      body: JSON.stringify({
        name: wf.name,
        description: "Dibuat otomatis oleh Discovery Agent (Level 3).",
        flow_data: { nodes: wf.nodes, edges: wf.edges },
      }),
    });
    const data = await readJson(res);
    const row = (data.workflow ?? data) as Record<string, unknown>;
    workflowId = String(row?.id ?? "");
    if (!res.ok || !workflowId) {
      return { ok: false, report: `Gagal menyimpan workflow (HTTP ${res.status}).` };
    }
  } catch {
    return { ok: false, report: "Gagal menyimpan workflow (koneksi)." };
  }

  // 2) Mulai eksekusi.
  let executionId = "";
  try {
    const res = await apiFetch(`/workflows/${workflowId}/execute`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    const data = await readJson(res);
    const payload = (data.data ?? data) as Record<string, unknown>;
    executionId = String(data.execution_id ?? payload?.execution_id ?? "");
    if (!res.ok) {
      return { ok: false, workflowId, report: `Gagal memulai eksekusi (HTTP ${res.status}).` };
    }
  } catch {
    return { ok: false, workflowId, report: "Gagal memulai eksekusi (koneksi)." };
  }

  if (!executionId) {
    // 202 terkirim tetapi id tidak terbaca: jangan mengarang laporan sukses.
    return {
      ok: false,
      workflowId,
      report: "Eksekusi dimulai tetapi id eksekusi tidak diterima; buka kanvas untuk melihat log.",
    };
  }

  // 3) Poll sampai status final (atau batas waktu).
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const res = await apiFetch(`/executions/${executionId}`, { method: "GET" });
      const data = await readJson(res);
      const status = String(
        ((data.execution ?? {}) as Record<string, unknown>)?.status ?? ""
      );
      const report = String(data.report ?? "");
      if (TERMINAL.has(status)) {
        return {
          ok: status === "completed",
          report: report || `Workflow selesai dengan status '${status}'.`,
          workflowId,
          executionId,
          status,
          logs: Array.isArray(data.logs) ? (data.logs as unknown[]) : [],
          durationMs: Date.now() - t0,
        };
      }
    } catch {
      // Satu kegagalan jaringan bukan akhir: putaran berikutnya bisa berhasil.
    }
  }
  return {
    ok: false,
    workflowId,
    executionId,
    status: "timeout",
    durationMs: Date.now() - t0,
    report:
      "Eksekusi masih berjalan setelah batas tunggu. Buka kanvas untuk melihat log terbaru.",
  };
}
