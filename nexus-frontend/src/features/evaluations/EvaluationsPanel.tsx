"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Play, Upload, RefreshCw, CheckCircle2, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api";

/**
 * Panel /evaluations (Fitur #4) — dataset uji + metrik + LLM-as-judge.
 *
 * Semua warna memakai token kanvas (`--canvas-*`, `--node-*`) sehingga
 * terbaca di 4 tema. Data diambil lewat `apiFetch` (Authorization otomatis).
 */

type Summary = {
  name?: string;
  total?: number;
  passed?: number;
  failed?: number;
  accuracy?: number;
  threshold?: number;
  compare_mode?: string;
  latency_mean_ms?: number;
  latency_p50_ms?: number;
  latency_p95_ms?: number;
  cost_total_usd?: number;
  regression?: string;
  regression_delta?: number;
};

type CaseResult = {
  id?: string;
  input?: string;
  expected?: string;
  actual?: string;
  score?: number;
  passed?: boolean;
  latency_ms?: number;
  cost_usd?: number;
  error?: string;
};

type RunRow = {
  run_id?: string;
  name?: string;
  dataset_name?: string;
  accuracy?: number;
  passed?: number;
  total?: number;
  latency_mean_ms?: number;
  cost_total_usd?: number;
  created_at?: string;
};

const CARD = "rounded-xl border p-3";
const CARD_STYLE = { borderColor: "var(--node-border)", background: "var(--canvas-panel-bg)" } as const;
const FIELD = "mt-1 w-full rounded-md border px-2.5 py-1.5 text-[13px] outline-none";
const FIELD_STYLE = { borderColor: "var(--node-border)", background: "var(--canvas-bg)", color: "var(--canvas-text-primary)" } as const;
const LABEL = { color: "var(--canvas-text-secondary)", fontSize: 11 } as const;
const HINT = { color: "var(--canvas-text-secondary)", opacity: 0.8, fontSize: 10 } as const;

const SAMPLE = `input,expected
2+2,4
ibukota indonesia,jakarta
ibukota jepang,tokyo`;

export function EvaluationsPanel() {
  const [dataset, setDataset] = useState(SAMPLE);
  const [fmt, setFmt] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const [name, setName] = useState("eval");
  const [mode, setMode] = useState("fuzzy");
  const [threshold, setThreshold] = useState("0.8");
  const [baseline, setBaseline] = useState("");
  const [maxCases, setMaxCases] = useState("20");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [results, setResults] = useState<CaseResult[]>([]);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadRuns = useCallback(async () => {
    try {
      const res = await apiFetch("/evaluations/runs?limit=20");
      if (res.ok) {
        const data = await res.json();
        setRuns((data?.runs as RunRow[]) ?? []);
      }
    } catch {
      /* daftar run bersifat opsional */
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const onFile = useCallback(async (file: File) => {
    const text = await file.text();
    setDataset(text);
    setFmt(file.name.toLowerCase().endsWith(".csv") ? "csv" : "json");
  }, []);

  const run = useCallback(async () => {
    setBusy(true);
    setError("");
    setSummary(null);
    setResults([]);
    try {
      const body = {
        dataset,
        dataset_format: fmt,
        workflow_id: workflowId,
        name,
        compare_mode: mode,
        threshold: Number(threshold) || 0.8,
        baseline_accuracy: baseline.trim() === "" ? null : Number(baseline),
        max_cases: Number(maxCases) || 20,
      };
      const res = await apiFetch("/evaluations/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data?.detail || `Gagal menjalankan evaluasi (${res.status})`);
        return;
      }
      setSummary(data.summary as Summary);
      setResults((data.results as CaseResult[]) ?? []);
      void loadRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kesalahan jaringan");
    } finally {
      setBusy(false);
    }
  }, [dataset, fmt, workflowId, name, mode, threshold, baseline, maxCases, loadRuns]);

  const acc = summary?.accuracy ?? 0;
  const accColor = acc >= 0.8 ? "var(--node-success-glow, #16a34a)"
    : acc >= 0.5 ? "var(--node-warning-color, #f59e0b)"
    : "var(--node-error-glow, #dc2626)";

  const bars = useMemo(() => results.slice(0, 40), [results]);

  return (
    <div className="flex flex-col gap-4">
      <div className={CARD} style={CARD_STYLE}>
        <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL}>
          Dataset uji (CSV atau JSON)
        </div>
        <textarea
          className={FIELD}
          style={{ ...FIELD_STYLE, minHeight: 120, fontFamily: "monospace" }}
          value={dataset}
          onChange={(e) => { setDataset(e.target.value); setFmt(""); }}
          data-testid="eval-dataset"
          spellCheck={false}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-semibold"
            style={{ borderColor: "var(--node-border)", color: "var(--canvas-text-primary)" }}
            data-testid="eval-upload"
          >
            <Upload size={13} /> Unggah file
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f); }}
          />
          <span style={HINT}>
            Kolom dikenali: input/prompt, expected/output/answer. Format lain diabaikan.
          </span>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span style={LABEL}>Workflow ID</span>
          <input className={FIELD} style={FIELD_STYLE} value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
            placeholder="uuid workflow yang dievaluasi" data-testid="eval-workflow" />
        </label>
        <label className="block">
          <span style={LABEL}>Nama run</span>
          <input className={FIELD} style={FIELD_STYLE} value={name}
            onChange={(e) => setName(e.target.value)} data-testid="eval-name" />
        </label>
        <label className="block">
          <span style={LABEL}>Mode banding</span>
          <select className={FIELD} style={FIELD_STYLE} value={mode}
            onChange={(e) => setMode(e.target.value)} data-testid="eval-mode">
            <option value="fuzzy">Fuzzy (kemiripan teks)</option>
            <option value="exact">Exact</option>
            <option value="contains">Contains</option>
            <option value="numeric">Numeric (toleransi)</option>
            <option value="judge">LLM-as-judge</option>
          </select>
        </label>
        <label className="block">
          <span style={LABEL}>Ambang lulus (0–1)</span>
          <input type="number" min={0} max={1} step={0.05} className={FIELD}
            style={FIELD_STYLE} value={threshold}
            onChange={(e) => setThreshold(e.target.value)} data-testid="eval-threshold" />
        </label>
        <label className="block">
          <span style={LABEL}>Baseline accuracy (opsional)</span>
          <input className={FIELD} style={FIELD_STYLE} value={baseline}
            onChange={(e) => setBaseline(e.target.value)} placeholder="mis. 0.85" />
        </label>
        <label className="block">
          <span style={LABEL}>Maksimum kasus</span>
          <input type="number" min={1} max={1000} className={FIELD}
            style={FIELD_STYLE} value={maxCases}
            onChange={(e) => setMaxCases(e.target.value)} />
        </label>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy}
          className="flex items-center gap-2 rounded-md px-3 py-2 text-[13px] font-semibold text-white disabled:opacity-60"
          style={{ background: "var(--canvas-accent, #6366f1)" }}
          data-testid="eval-run"
        >
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
          {busy ? "Menjalankan…" : "Jalankan evaluasi"}
        </button>
        {error && <span className="text-[12px]" style={{ color: "var(--node-error-glow, #dc2626)" }} data-testid="eval-error">{error}</span>}
      </div>

      {summary && (
        <>
          <div className="grid gap-3 sm:grid-cols-4" data-testid="eval-summary">
            {[
              { label: "Accuracy", value: `${(acc * 100).toFixed(1)}%`, color: accColor },
              { label: "Lulus", value: `${summary.passed ?? 0}/${summary.total ?? 0}` },
              { label: "Latensi rata-rata", value: `${(summary.latency_mean_ms ?? 0).toFixed(0)} ms` },
              { label: "Biaya total", value: `$${(summary.cost_total_usd ?? 0).toFixed(4)}` },
            ].map((c) => (
              <div key={c.label} className={CARD} style={CARD_STYLE}>
                <div style={LABEL}>{c.label}</div>
                <div className="text-[18px] font-bold" style={{ color: c.color || "var(--canvas-text-primary)" }}>
                  {c.value}
                </div>
              </div>
            ))}
          </div>

          {summary.regression && (
            <div className={CARD} style={CARD_STYLE} data-testid="eval-regression">
              <span style={LABEL}>Regresi vs baseline: </span>
              <span className="text-[12px] font-semibold"
                style={{ color: summary.regression === "regressed" ? "var(--node-error-glow, #dc2626)" : "var(--node-success-glow, #16a34a)" }}>
                {summary.regression} ({(summary.regression_delta ?? 0) >= 0 ? "+" : ""}
                {((summary.regression_delta ?? 0) * 100).toFixed(1)}%)
              </span>
            </div>
          )}

          <div className={CARD} style={CARD_STYLE}>
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL}>
              Skor per kasus
            </div>
            <div className="flex items-end gap-1" style={{ height: 64 }} aria-hidden="true">
              {bars.map((r, i) => (
                <div key={i} title={`${r.id}: ${r.score}`}
                  style={{
                    flex: "1 0 auto", maxWidth: 14, height: `${Math.max(4, (r.score ?? 0) * 100)}%`,
                    background: r.passed ? "var(--node-success-glow, #16a34a)" : "var(--node-error-glow, #dc2626)",
                    borderRadius: 2,
                  }} />
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-[12px]" data-testid="eval-results">
              <thead>
                <tr style={LABEL}>
                  <th className="px-2 py-1 text-left">ID</th>
                  <th className="px-2 py-1 text-left">Input</th>
                  <th className="px-2 py-1 text-left">Expected</th>
                  <th className="px-2 py-1 text-left">Output</th>
                  <th className="px-2 py-1 text-right">Skor</th>
                  <th className="px-2 py-1 text-right">ms</th>
                </tr>
              </thead>
              <tbody>
                {results.slice(0, 100).map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--node-border)", color: "var(--canvas-text-primary)" }}>
                    <td className="px-2 py-1">{r.passed ? <CheckCircle2 size={13} color="var(--node-success-glow, #16a34a)" /> : <XCircle size={13} color="var(--node-error-glow, #dc2626)" />} {r.id}</td>
                    <td className="px-2 py-1 max-w-[220px] truncate" title={r.input}>{r.input}</td>
                    <td className="px-2 py-1 max-w-[160px] truncate" title={r.expected}>{r.expected}</td>
                    <td className="px-2 py-1 max-w-[220px] truncate" title={r.actual}>{r.error ? `⚠ ${r.error}` : r.actual}</td>
                    <td className="px-2 py-1 text-right">{r.score}</td>
                    <td className="px-2 py-1 text-right">{r.latency_ms?.toFixed?.(0) ?? r.latency_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className={CARD} style={CARD_STYLE}>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wide" style={LABEL}>
            Riwayat run
          </span>
          <button type="button" onClick={() => void loadRuns()}
            className="rounded-md border px-2 py-1 text-[11px]"
            style={{ borderColor: "var(--node-border)", color: "var(--canvas-text-primary)" }}>
            Muat ulang
          </button>
        </div>
        {runs.length === 0 ? (
          <span style={HINT}>Belum ada run.</span>
        ) : (
          <ul className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--canvas-text-primary)" }}>
            {runs.map((r) => (
              <li key={r.run_id} className="flex items-center justify-between gap-2">
                <span className="truncate">{r.name} · {r.dataset_name || "—"}</span>
                <span style={HINT}>
                  {((r.accuracy ?? 0) * 100).toFixed(1)}% · {r.passed}/{r.total} ·{" "}
                  {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
