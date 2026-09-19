"use client";

import { CircleDollarSign } from "lucide-react";
import { useMeSimple } from "@/components/useMeSimple";
import { useI18n } from "@/i18n/context";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

/**
 * Link checkout Dodo Payments (Plus: $299 / TAHUN).
 * NEXT_PUBLIC_* di-INLINE saat build → perubahan URL = build ulang.
 */
const CHECKOUT_URL = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

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

      <Card>
        <CardHeader>
          <CardTitle>{t("billing.invoices")}</CardTitle>
          <CardDescription>{t("billing.invoicesDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {/* SENGAJA tanpa data dummy: invoice hanya dari pembayaran nyata. */}
          <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-4 py-8 text-center">
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
