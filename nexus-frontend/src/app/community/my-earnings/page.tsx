"use client";

import { useCallback, useEffect, useState } from "react";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

/**
 * F7.4 - "My earnings" for community integration developers.
 *
 * Backed by GET /community/my-earnings, which returns
 * `{ items: [{ integration_id, amount_usd, period_start, period_end, paid_at }], total_usd }`.
 *
 * The endpoint requires a bearer token (401 without one) and raises 503 when
 * the community tables are not deployed, so BOTH the signed-out case and the
 * "tables not deployed" case are handled as first-class states rather than
 * being rendered as a bare empty list. Collapsing them would tell a developer
 * with a broken backend that they have simply earned nothing.
 */

type Earning = {
  integration_id: string;
  amount_usd: number | null;
  period_start: string | null;
  period_end: string | null;
  paid_at: string | null;
};

type LoadState =
  | "loading"
  | "ready"
  | "unauthenticated"
  | "unavailable"
  | "error";

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

/** `2026-01-31` -> `31 Jan 2026`. Returns null for missing/garbage input. */
function formatPeriod(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export default function MyEarningsPage() {
  const [items, setItems] = useState<Earning[]>([]);
  const [totalUsd, setTotalUsd] = useState(0);
  const [state, setState] = useState<LoadState>("loading");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const res = await apiFetch("/community/my-earnings", { timeoutMs: 8000 });
      // 401/403 -> not signed in. 503 -> community tables not deployed.
      // Both are distinct from "you have earned nothing".
      if (res.status === 401 || res.status === 403) {
        setState("unauthenticated");
        return;
      }
      if (res.status === 503) {
        setState("unavailable");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as {
        items?: Earning[];
        total_usd?: number;
      };
      setItems(data.items ?? []);
      setTotalUsd(Number(data.total_usd ?? 0));
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SimplePage
      title="Pendapatan saya"
      subtitle="Pembagian pendapatan dari integrasi komunitas Anda."
    >
      {/* Live region so screen readers hear the state change after load. */}
      <div role="status" aria-live="polite" className="text-sm text-fg-muted">
        {state === "loading" && "Memuat\u2026"}
        {state === "ready" && `${items.length} transaksi`}
        {state === "error" && "Gagal memuat pendapatan."}
      </div>

      {state === "unauthenticated" && (
        <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-fg-muted">
          Masuk untuk melihat pendapatan Anda.
        </p>
      )}

      {state === "unavailable" && (
        <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-fg-muted">
          Tabel komunitas belum diterapkan. Jalankan
          <code className="mx-1">docs/architecture/community-platform.sql</code>
          terlebih dahulu.
        </p>
      )}

      {state === "error" && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border p-8">
          <p className="text-sm text-fg-muted">
            Tidak dapat memuat pendapatan dari server.
          </p>
          <Button variant="ghost" onClick={() => void load()}>
            Coba lagi
          </Button>
        </div>
      )}

      {state === "ready" && (
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Total pendapatan</CardTitle>
            </CardHeader>
            <CardContent>
              <p
                className="text-2xl font-semibold"
                data-testid="earnings-total"
              >
                {usd.format(totalUsd)}
              </p>
            </CardContent>
          </Card>

          {items.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-fg-muted">
              Belum ada pendapatan. Integrasi yang Anda terbitkan akan muncul
              di sini setelah periode pertama ditutup.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {items.map((row, idx) => {
                const from = formatPeriod(row.period_start);
                const to = formatPeriod(row.period_end);
                const period =
                  from && to
                    ? `${from} \u2014 ${to}`
                    : (from ?? to ?? "Periode tidak diketahui");
                return (
                  <Card
                    key={`${row.integration_id}-${row.period_start}-${idx}`}
                  >
                    <CardHeader>
                      <CardTitle>{row.integration_id}</CardTitle>
                    </CardHeader>
                    <CardContent className="flex flex-wrap items-center justify-between gap-2 text-sm">
                      <span className="text-fg-muted">{period}</span>
                      <span className="font-medium">
                        {usd.format(Number(row.amount_usd ?? 0))}
                      </span>
                      <span className="w-full text-fg-muted">
                        {row.paid_at
                          ? `Dibayar ${formatPeriod(row.paid_at)}`
                          : "Belum dibayar"}
                      </span>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      )}
    </SimplePage>
  );
}
