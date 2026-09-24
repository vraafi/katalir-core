"use client";

import { useEffect, useState } from "react";
import { CircleDollarSign } from "lucide-react";
import { useMeSimple } from "@/components/useMeSimple";
import { useI18n } from "@/i18n/context";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/cn";

/**
 * Link checkout Dodo Payments (Plus: $299 / TAHUN).
 * NEXT_PUBLIC_* di-INLINE saat build → perubahan URL = build ulang.
 */
const CHECKOUT_URL = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

interface QuotaBucket {
  used: number;
  limit: number;
}
interface QuotaPayload {
  tier?: string;
  buckets?: Record<string, QuotaBucket>;
  labels?: Record<string, string>;
  used_total?: number;
  limit_total?: number;
}

/**
 * Kartu pemakaian (FASE 4.2).
 *
 * SENGAJA tidak memakai `@tremor/react` meski misi menyebutnya sebagai acuan:
 * Tremor membawa `recharts` + perubahan konfigurasi Tailwind, sedangkan yang
 * dibutuhkan di sini hanya bar progres + angka dari token desain yang sudah ada.
 * Menambah paket grafik untuk dua bar akan menaikkan bundel dan mengunci sistem
 * tema ke palet Tremor. Keputusan ini dicatat di
 * docs/audit/fase4-verification.md.
 */
function UsageCard() {
  const { t } = useI18n();
  const [quota, setQuota] = useState<QuotaPayload | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty">("loading");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data: session } = await supabase.auth.getSession();
        if (!session.session?.access_token) {
          if (alive) setState("empty");
          return;
        }
        const r = await apiFetch("/quota", { timeoutMs: 20000 });
        if (!alive) return;
        if (!r.ok) {
          setState("empty");
          return;
        }
        const d = (await r.json()) as QuotaPayload;
        if (!alive) return;
        setQuota(d);
        setState(d?.buckets && Object.keys(d.buckets).length > 0 ? "ready" : "empty");
      } catch {
        if (alive) setState("empty");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Card data-testid="card-usage">
      <CardHeader>
        <CardTitle>{t("billing.usage")}</CardTitle>
        <CardDescription>{t("billing.usageDesc")}</CardDescription>
      </CardHeader>
      <CardContent>
        {state === "loading" && (
          // MOTION (FASE 4.4): loading -> skeleton, bukan ruang kosong.
          <div className="flex flex-col gap-3" data-testid="usage-skeleton">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-2 w-full" />
            <Skeleton className="h-2 w-4/5" />
            <span className="sr-only">{t("billing.usageLoading")}</span>
          </div>
        )}
        {state === "empty" && (
          <p className="text-footnote text-fg-muted" data-testid="usage-empty">
            {t("billing.usageUnavailable")}
          </p>
        )}
        {state === "ready" && quota?.buckets && (
          <div className="flex flex-col gap-3" data-testid="usage-bars">
            {Object.entries(quota.buckets).map(([key, b]) => {
              const pct = b.limit > 0 ? Math.min(100, Math.round((b.used / b.limit) * 100)) : 0;
              const label = quota.labels?.[key] ?? key;
              return (
                <div key={key}>
                  <div className="mb-1 flex items-center justify-between text-footnote">
                    <span className="font-medium text-fg">{label}</span>
                    <span className="text-fg-muted">
                      {b.used} / {b.limit} · {pct}%
                    </span>
                  </div>
                  <div
                    role="progressbar"
                    aria-valuenow={pct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={label}
                    className="h-2 w-full overflow-hidden rounded-full bg-bg-subtle"
                  >
                    <div
                      className={cn(
                        "h-full rounded-full transition-[width] duration-300",
                        pct >= 90 ? "bg-danger" : "bg-accent"
                      )}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
            <p className="text-caption text-fg-subtle">
              {t("quota.total")}: {quota.used_total ?? 0} / {quota.limit_total ?? 0} {t("quota.request")} ·{" "}
              {t("quota.reset")}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Baris tabel perbandingan paket: nilai + tanda (ya/tidak) yang aksesibel. */
function PlanRow({ label, free, plus }: { label: string; free: string; plus: string }) {
  return (
    <tr className="border-t border-border">
      <th scope="row" className="py-2 pr-3 text-left text-footnote font-medium text-fg-muted">
        {label}
      </th>
      <td className="py-2 pr-3 text-footnote text-fg">{free}</td>
      <td className="py-2 text-footnote font-medium text-fg">{plus}</td>
    </tr>
  );
}


/** Halaman Billing — konten di DALAM SimplePage (SimplePage yang memegang provider). */
function BillingContent() {
  const { t } = useI18n();
  // useMeSimple (fetch langsung, TANPA TanStack): useMeQuery butuh
  // QueryClientProvider — saat prerender statis provider itu belum ada
  // ("No QueryClient set") dan build gagal. Halaman kecil ini tidak butuh cache.
  const me = useMeSimple(true);
  const serverTier = (me?.tier ?? "free").toLowerCase();
  const isPlus = serverTier === "plus" || serverTier === "pro" || serverTier === "ultra";

  return (
    <>
      <UsageCard />

      <Card>
        <CardHeader>
          <CardTitle>{t("billing.status")}</CardTitle>
          <CardDescription>{t("billing.statusDesc", { email: me?.email || "Anda" })}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-title3 font-bold text-fg">{isPlus ? t("billing.plus") : t("billing.free")}</p>
          {isPlus ? (
            <p className="mt-1 text-footnote text-fg-muted">
              {t("billing.upgradeThanks")}
            </p>
          ) : (
            <>
              <p className="mt-1 text-footnote text-fg-muted">
                {t("billing.upgradeDesc")}
              </p>
              {CHECKOUT_URL ? (
                <a
                  href={CHECKOUT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md bg-accent px-4 py-2 text-subhead font-medium text-white transition-all duration-200 hover:bg-accent/90"
                >
                  {t("billing.upgradeCta")}
                </a>
              ) : (
                <p className="mt-3 text-footnote text-fg-subtle">
                  {t("billing.checkoutMissing")}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card data-testid="card-plan">
        <CardHeader>
          <CardTitle>{t("billing.plan")}</CardTitle>
          <CardDescription>{t("billing.planDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse" data-testid="plan-table">
              <caption className="sr-only">{t("billing.planDesc")}</caption>
              <thead>
                <tr className="text-left">
                  <th scope="col" className="pb-2 pr-3 text-caption font-semibold uppercase tracking-wide text-fg-subtle">
                    {t("billing.colFeature")}
                  </th>
                  <th scope="col" className="pb-2 pr-3 text-caption font-semibold uppercase tracking-wide text-fg-subtle">
                    {t("billing.colFree")}
                  </th>
                  <th scope="col" className="pb-2 text-caption font-semibold uppercase tracking-wide text-accent">
                    {t("billing.colPlus")}
                  </th>
                </tr>
              </thead>
              <tbody>
                <PlanRow label={t("billing.rowPrice")} free={t("billing.priceFree")} plus={t("billing.pricePlus")} />
                <PlanRow label={t("billing.rowQuota")} free={t("billing.quotaFree")} plus={t("billing.quotaPlus")} />
                <PlanRow label={t("billing.rowModels")} free={t("billing.modelsFree")} plus={t("billing.modelsPlus")} />
                <PlanRow label={t("billing.rowCanvas")} free={t("billing.canvasBoth")} plus={t("billing.canvasBoth")} />
                <PlanRow
                  label={t("billing.rowSupport")}
                  free={t("billing.supportCommunity")}
                  plus={t("billing.supportPriority")}
                />
              </tbody>
            </table>
          </div>
          <div className="mt-4">
            {isPlus ? (
              <p className="text-footnote font-medium text-success" data-testid="plan-current">
                ✓ {t("billing.currentPlan")}: {serverTier.toUpperCase()}
              </p>
            ) : CHECKOUT_URL ? (
              <a
                href={CHECKOUT_URL}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="plan-checkout"
                className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md bg-accent px-4 py-2 text-subhead font-medium text-white transition-all duration-200 hover:bg-accent/90 active:scale-[0.98]"
              >
                {t("billing.upgradeCta")}
              </a>
            ) : (
              <p className="text-footnote text-fg-subtle">{t("billing.checkoutMissing")}</p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("billing.invoices")}</CardTitle>
          <CardDescription>{t("billing.invoicesDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {/* SENGAJA tanpa data dummy: invoice hanya dari pembayaran nyata. */}
          <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-4 py-8 text-center" data-testid="invoices-empty">
            <CircleDollarSign size={28} strokeWidth={1.5} className="text-fg-subtle" aria-hidden />
            <p className="text-callout font-medium text-fg">{t("billing.noInvoices")}</p>
            <p className="text-footnote text-fg-muted">{t("billing.noInvoicesDesc")}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("billing.manage")}</CardTitle>
          <CardDescription>{t("billing.manageDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-footnote text-fg-muted">
            {t("billing.manageNote")}
          </p>
        </CardContent>
      </Card>
    </>
  );
}

/** Route /billing: SimplePage (provider) + konten. */
export default function BillingPage() {
  return (
    <SimplePage title="billing.title" subtitle="billing.subtitle" maxW="max-w-3xl">
      <BillingContent />
    </SimplePage>
  );
}
