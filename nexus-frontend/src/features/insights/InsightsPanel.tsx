"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";

/**
 * Panel /insights (Fitur #5) — success rate, latensi, error rate, time saved,
 * ROI, deret waktu 7/30/365 hari, filter workflow, ekspor CSV.
 *
 * Grafik digambar sebagai SVG inline (tanpa dependensi chart) supaya bundle
 * tetap kecil dan warna mengikuti token tema.
 */

type Series = { date: string; total: number; success: number; error: number; pending: number };
type Metrics = {
  total?: number; success?: number; error?: number; pending?: number;
  success_rate?: number; error_rate?: number;
  latency_mean_ms?: number | null; latency_p50_ms?: number | null;
  latency_p95_ms?: number | null; latency_sample_size?: number;
};
type Report = {
  range_days?: number;
  metrics?: Metrics;
  time_saved?: { automated_runs?: number; minutes_saved?: number; hours_saved?: number };
  roi?: { money_saved?: number; hourly_rate?: number; currency?: string };
  series?: Series[];
  by_workflow?: { workflow_id: string; total: number; success: number; error: number; success_rate: number }[];
};

const CARD = "rounded-xl border p-3";
const CARD_STYLE = { borderColor: "var(--node-border)", background: "var(--canvas-panel-bg)" } as const;
const LABEL = { color: "var(--canvas-text-secondary)", fontSize: 11 } as const;
const HINT = { color: "var(--canvas-text-secondary)", opacity: 0.8, fontSize: 10 } as const;

function Chart({ series }: { series: Series[] }) {
  const W = 640, H = 140, PAD = 4;
  const max = Math.max(1, ...series.map((s) => s.total));
  const bw = series.length ? (W - PAD * 2) / series.length : 0;
  const y = (v: number) => H - (v / max) * (H - 16) - 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
      aria-label="Deret waktu eksekusi" data-testid="insights-chart">
      {series.map((s, i) => {
        const x = PAD + i * bw;
        const okH = H - 2 - y(s.success);
        const errH = H - 2 - y(s.error);
        return (
          <g key={s.date}>
            <title>{`${s.date}: ${s.total} total, ${s.success} sukses, ${s.error} gagal`}</title>
            <rect x={x + bw * 0.15} y={y(s.success)} width={bw * 0.7}
              height={Math.max(0, okH)} rx={2} fill="var(--node-success-glow, #16a34a)" />
            <rect x={x + bw * 0.15} y={y(s.error)} width={bw * 0.7}
              height={Math.max(0, errH)} rx={2} fill="var(--node-error-glow, #dc2626)" />
          </g>
        );
      })}
    </svg>
  );
}

export function InsightsPanel() {
  const [days, setDays] = useState(30);
  const [workflowId, setWorkflowId] = useState("");
  const [latency, setLatency] = useState(true);
  const [rep, setRep] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [workflows, setWorkflows] = useState<{ id: string; name?: string }[]>([]);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const qs = new URLSearchParams({ days: String(days), latency: String(latency) });
      if (workflowId) qs.set("workflow_id", workflowId);
      const res = await apiFetch(`/insights?${qs.toString()}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data?.detail || `Gagal memuat insight (${res.status})`);
        return;
      }
      setRep(data as Report);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kesalahan jaringan");
    } finally {
      setBusy(false);
    }
  }, [days, workflowId, latency]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/workflows");
        if (res.ok) {
          const d = await res.json();
          const list = (d?.workflows ?? d ?? []) as { id: string; name?: string }[];
          setWorkflows(Array.isArray(list) ? list : []);
        }
      } catch { /* filter opsional */ }
    })();
  }, []);

  const exportCsv = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ days: String(days) });
      if (workflowId) qs.set("workflow_id", workflowId);
      const res = await apiFetch(`/insights/export?${qs.toString()}`);
      if (!res.ok) return;
      const text = await res.text();
      const blob = new Blob([text], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `insights-${days}d.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* diabaikan */ }
  }, [days, workflowId]);

  const m = rep?.metrics ?? {};
  const sr = m.success_rate ?? 0;
  const srColor = sr >= 0.9 ? "var(--node-success-glow, #16a34a)"
    : sr >= 0.7 ? "var(--node-warning-color, #f59e0b)"
    : "var(--node-error-glow, #dc2626)";

  const cards = useMemo(() => ([
    { label: "Success rate", value: `${(sr * 100).toFixed(1)}%`, color: srColor },
    { label: "Total eksekusi", value: `${m.total ?? 0}` },
    { label: "Error rate", value: `${((m.error_rate ?? 0) * 100).toFixed(1)}%` },
    { label: "Latensi rata-rata", value: m.latency_mean_ms != null ? `${m.latency_mean_ms.toFixed(0)} ms` : "—" },
    { label: "Waktu dihemat", value: `${rep?.time_saved?.hours_saved ?? 0} jam` },
    { label: "ROI", value: `$${(rep?.roi?.money_saved ?? 0).toFixed(2)}` },
  ]), [sr, srColor, m, rep]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {[7, 30, 365].map((d) => (
          <button key={d} type="button" onClick={() => setDays(d)}
            className="rounded-md border px-3 py-1.5 text-[12px] font-semibold"
            style={{
              borderColor: days === d ? "var(--canvas-accent, #6366f1)" : "var(--node-border)",
              color: days === d ? "var(--canvas-accent, #6366f1)" : "var(--canvas-text-primary)",
            }}
            data-testid={`insights-range-${d}`}>
            {d} hari
          </button>
        ))}
        <select
          className="rounded-md border px-2.5 py-1.5 text-[12px]"
          style={{ borderColor: "var(--node-border)", background: "var(--canvas-bg)", color: "var(--canvas-text-primary)" }}
          value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}
          data-testid="insights-workflow-filter">
          <option value="">Semua workflow</option>
          {workflows.map((w) => (
            <option key={w.id} value={w.id}>{w.name || w.id.slice(0, 8)}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-[12px]" style={LABEL}>
          <input type="checkbox" checked={latency} onChange={(e) => setLatency(e.target.checked)} />
          Ukur latensi
        </label>
        <button type="button" onClick={() => void load()} disabled={busy}
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-semibold"
          style={{ borderColor: "var(--node-border)", color: "var(--canvas-text-primary)" }}
          data-testid="insights-refresh">
          <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> Muat ulang
        </button>
        <button type="button" onClick={() => void exportCsv()}
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-semibold"
          style={{ borderColor: "var(--node-border)", color: "var(--canvas-text-primary)" }}
          data-testid="insights-export">
          <Download size={13} /> Ekspor CSV
        </button>
      </div>

      {error && <span className="text-[12px]" style={{ color: "var(--node-error-glow, #dc2626)" }} data-testid="insights-error">{error}</span>}

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6" data-testid="insights-cards">
        {cards.map((c) => (
          <div key={c.label} className={CARD} style={CARD_STYLE}>
            <div style={LABEL}>{c.label}</div>
            <div className="text-[17px] font-bold" style={{ color: c.color || "var(--canvas-text-primary)" }}>
              {c.value}
            </div>
          </div>
        ))}
      </div>

      <div className={CARD} style={CARD_STYLE}>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wide" style={LABEL}>
            Eksekusi {rep?.range_days ?? days} hari terakhir
          </span>
          <span style={HINT}>
            <span style={{ color: "var(--node-success-glow, #16a34a)" }}>■</span> sukses{" "}
            <span style={{ color: "var(--node-error-glow, #dc2626)" }}>■</span> gagal
          </span>
        </div>
        {rep?.series?.length ? <Chart series={rep.series} /> : <span style={HINT}>Tidak ada data.</span>}
        {m.latency_sample_size ? (
          <span style={HINT}>
            Latensi dari {m.latency_sample_size} eksekusi tersampel (p50 {m.latency_p50_ms ?? 0} ms, p95 {m.latency_p95_ms ?? 0} ms).
          </span>
        ) : null}
      </div>

      <div className={CARD} style={CARD_STYLE}>
        <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL}>
          Per workflow
        </div>
        {rep?.by_workflow?.length ? (
          <table className="w-full text-[12px]" data-testid="insights-by-workflow">
            <thead>
              <tr style={LABEL}>
                <th className="px-2 py-1 text-left">Workflow</th>
                <th className="px-2 py-1 text-right">Total</th>
                <th className="px-2 py-1 text-right">Sukses</th>
                <th className="px-2 py-1 text-right">Gagal</th>
                <th className="px-2 py-1 text-right">Rate</th>
              </tr>
            </thead>
            <tbody>
              {rep.by_workflow.slice(0, 20).map((w) => (
                <tr key={w.workflow_id} style={{ borderTop: "1px solid var(--node-border)", color: "var(--canvas-text-primary)" }}>
                  <td className="px-2 py-1">{w.workflow_id.slice(0, 8)}</td>
                  <td className="px-2 py-1 text-right">{w.total}</td>
                  <td className="px-2 py-1 text-right">{w.success}</td>
                  <td className="px-2 py-1 text-right">{w.error}</td>
                  <td className="px-2 py-1 text-right">{(w.success_rate * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <span style={HINT}>Belum ada eksekusi.</span>}
      </div>
    </div>
  );
}
