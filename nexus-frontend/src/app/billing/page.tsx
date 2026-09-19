"use client";

import { CircleDollarSign } from "lucide-react";
import { useMeSimple } from "@/components/useMeSimple";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

/**
 * Link checkout Dodo Payments (Plus: $299 / TAHUN).
 * NEXT_PUBLIC_* di-INLINE saat build → perubahan URL = build ulang.
 */
const CHECKOUT_URL = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

/** Halaman Billing — konten di DALAM SimplePage (SimplePage yang memegang provider). */
function BillingContent() {
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
          <CardTitle>Status Langganan</CardTitle>
          <CardDescription>Paket aktif untuk akun {me?.email || "Anda"}.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-title3 font-bold text-fg">{isPlus ? "Plus" : "Free"}</p>
          {isPlus ? (
            <p className="mt-1 text-footnote text-fg-muted">
              Terima kasih! Anda menikmati kuota 600 request / hari.
            </p>
          ) : (
            <>
              <p className="mt-1 text-footnote text-fg-muted">
                Buka kuota 600 request / hari + DeepSeek V4.1 Flash.
              </p>
              {CHECKOUT_URL ? (
                <a
                  href={CHECKOUT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md bg-accent px-4 py-2 text-subhead font-medium text-white transition-all duration-200 hover:bg-accent/90"
                >
                  Upgrade ke Plus — $299 / tahun
                </a>
              ) : (
                <p className="mt-3 text-footnote text-fg-subtle">
                  Link checkout belum tersedia — hubungi kami untuk upgrade manual.
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Riwayat Invoice</CardTitle>
          <CardDescription>Pembayaran yang pernah dilakukan.</CardDescription>
        </CardHeader>
        <CardContent>
          {/* SENGAJA tanpa data dummy: invoice hanya dari pembayaran nyata. */}
          <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-4 py-8 text-center">
            <CircleDollarSign size={28} strokeWidth={1.5} className="text-fg-subtle" aria-hidden />
            <p className="text-callout font-medium text-fg">Belum ada invoice</p>
            <p className="text-footnote text-fg-muted">Invoice muncul setelah pembayaran pertama.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Kelola Langganan</CardTitle>
          <CardDescription>Batal atau ubah metode pembayaran.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-footnote text-fg-muted">
            Anda dapat mengelola langganan via portal Dodo Payments. Tautan portal akan
            tersedia setelah pembayaran pertama.
          </p>
        </CardContent>
      </Card>
    </>
  );
}

/** Route /billing: SimplePage (provider) + konten. */
export default function BillingPage() {
  return (
    <SimplePage title="Billing & Langganan" subtitle="Kelola paket dan pembayaran Anda" maxW="max-w-3xl">
      <BillingContent />
    </SimplePage>
  );
}
