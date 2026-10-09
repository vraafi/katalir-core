"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  HelpCircle,
  KeyRound,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { connectorHealthKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getHealthSchema, getHealthSummary, listByVerdict } from "./api";
import type { ConnectorVerdict } from "./types";

const VERDICT_META: Record<
  ConnectorVerdict,
  { label: string; hint: string; className: string; icon: typeof CheckCircle2 }
> = {
  ALIVE: {
    label: "ALIVE",
    hint: "Menerima tools/list — benar-benar mengirim data",
    className: "bg-success/15 text-success",
    icon: CheckCircle2,
  },
  AUTH: {
    label: "AUTH",
    hint: "Server hidup, tapi butuh kredensial",
    className: "bg-warning/15 text-warning",
    icon: KeyRound,
  },
  DEAD: {
    label: "DEAD",
    hint: "Tidak dapat dijangkau (5xx / timeout)",
    className: "bg-danger/15 text-danger",
    icon: XCircle,
  },
  UNKNOWN: {
    label: "UNKNOWN",
    hint: "Hasil belum konklusif",
    className: "bg-bg-subtle text-fg-muted",
    icon: HelpCircle,
  },
};

const ORDER: ConnectorVerdict[] = ["ALIVE", "AUTH", "DEAD", "UNKNOWN"];

export function ConnectorHealthDashboard() {
  const [selected, setSelected] = useState<ConnectorVerdict>("ALIVE");

  const summary = useQuery({
    queryKey: connectorHealthKeys.summary(),
    queryFn: getHealthSummary,
    refetchInterval: 60_000,
  });

  const schema = useQuery({
    queryKey: connectorHealthKeys.schema(),
    queryFn: getHealthSchema,
    staleTime: 5 * 60_000,
  });

  const list = useQuery({
    queryKey: connectorHealthKeys.byVerdict(selected, 50),
    queryFn: () => listByVerdict(selected, 50),
    enabled: Boolean(summary.data),
  });

  if (summary.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (summary.isError || !summary.data) {
    return (
      <div className="rounded-lg border border-border bg-danger/10 p-4 text-sm text-danger">
        <AlertCircle className="mr-2 inline h-4 w-4" />
        Gagal memuat kesehatan konektor. Pastikan backend aktif.
      </div>
    );
  }

  const { health, catalog } = summary.data;
  const pct = (n: number) => (health.total ? Math.round((n / health.total) * 100) : 0);

  return (
    <div className="space-y-6">
      {/* Ringkasan */}
      <div className="rounded-lg border border-border bg-surface p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-fg">
              Hasil probe live
            </h2>
            <p className="text-sm text-fg-muted">
              {health.total.toLocaleString()} konektor ber-URL diuji langsung
              dengan protokol MCP.
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              void summary.refetch();
              void list.refetch();
            }}
            disabled={summary.isFetching}
          >
            <RefreshCw
              className={cn("mr-2 h-4 w-4", summary.isFetching && "animate-spin")}
            />
            Muat ulang
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {ORDER.map((v) => {
            const meta = VERDICT_META[v];
            const Icon = meta.icon;
            const count = health[v];
            return (
              <button
                key={v}
                type="button"
                onClick={() => setSelected(v)}
                className={cn(
                  "rounded-lg border p-3 text-left transition",
                  selected === v
                    ? "border-accent bg-bg-subtle"
                    : "border-border bg-bg-subtle/40 hover:bg-bg-subtle",
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
                      meta.className,
                    )}
                  >
                    <Icon className="mr-1 h-3 w-3" />
                    {meta.label}
                  </span>
                </div>
                <div className="mt-2 text-2xl font-semibold text-fg">
                  {count.toLocaleString()}
                </div>
                <div className="text-xs text-fg-muted">{pct(count)}% dari total</div>
              </button>
            );
          })}
        </div>

        {/* Perbandingan dengan katalog — mencegah klaim berlebihan */}
        <div className="mt-4 rounded border border-border bg-bg-subtle/50 p-3 text-xs text-fg-muted">
          <strong className="text-fg">Pembanding katalog:</strong>{" "}
          {catalog.total?.toLocaleString() ?? "—"} entri total,{" "}
          {catalog.executable?.toLocaleString() ?? "—"} executable,{" "}
          {catalog.metadata_only?.toLocaleString() ?? "—"} metadata-only.{" "}
          <span className="text-warning">
            Angka katalog ≠ terhubung. Hanya verdict ALIVE yang berarti
            benar-benar mengirim data.
          </span>
        </div>
      </div>

      {/* Daftar per verdict */}
      <div className="rounded-lg border border-border bg-surface p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-fg">
            {VERDICT_META[selected].label} — {VERDICT_META[selected].hint}
          </h3>
          {list.data ? (
            <span className="text-xs text-fg-muted">
              menampilkan {list.data.connectors.length} dari {list.data.count}
            </span>
          ) : null}
        </div>

        {list.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : list.isError ? (
          <div className="text-sm text-danger">Gagal memuat daftar.</div>
        ) : (list.data?.connectors.length ?? 0) === 0 ? (
          <div className="text-sm text-fg-muted">
            Tidak ada konektor dengan verdict ini.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-fg-muted">
                  <th className="py-2 pr-3 font-medium">Connector</th>
                  <th className="py-2 pr-3 font-medium">HTTP</th>
                  <th className="py-2 pr-3 font-medium">Tools</th>
                  <th className="py-2 pr-3 font-medium">Latensi</th>
                  <th className="py-2 font-medium">Catatan</th>
                </tr>
              </thead>
              <tbody>
                {list.data?.connectors.map((c) => (
                  <tr key={c.connector_id} className="border-b border-border/50">
                    <td className="py-2 pr-3 font-mono text-xs text-fg">
                      {c.connector_id}
                    </td>
                    <td className="py-2 pr-3 text-fg">
                      {c.http_status ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-fg">
                      {c.tools_count ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-fg-muted">
                      {c.latency_ms != null ? `${c.latency_ms} ms` : "—"}
                    </td>
                    <td className="py-2 text-xs text-fg-muted">
                      {c.error ? c.error.slice(0, 60) : "ok"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Kontrak prober */}
      {schema.data ? (
        <div className="rounded-lg border border-border bg-surface p-5 text-xs text-fg-muted">
          <h3 className="mb-2 text-sm font-semibold text-fg">Metode pengujian</h3>
          <div className="grid gap-1 sm:grid-cols-2">
            <div>
              Protokol MCP <code className="text-fg">{schema.data.prober.protocol_version}</code>
            </div>
            <div>
              Timeout {schema.data.prober.timeout_s}s · {schema.data.prober.workers} worker
            </div>
            <div>
              Perbaikan otomatis maks {schema.data.repair.max_rounds} putaran
            </div>
            <div>
              Hard stop: {schema.data.repair.hard_stops.join(", ")}
            </div>
          </div>
          <p className="mt-2">
            Metodologi perbaikan diadaptasi dari{" "}
            <code className="text-fg">{schema.data.repair.methodology_from}</code>
          </p>
        </div>
      ) : null}
    </div>
  );
}
