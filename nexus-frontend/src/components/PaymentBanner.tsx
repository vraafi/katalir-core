"use client";

import { useEffect, useState } from "react";
import { Info, X } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { PAYMENT_COMING_SOON } from "@/lib/payment";

/** Kunci localStorage untuk "sudah ditutup user". Naikkan versi bila teksnya berubah. */
const DISMISS_KEY = "katalir.paymentBanner.dismissed.v1";

/**
 * Spanduk "pembayaran belum dibuka" (FASE 7).
 *
 * KENAPA ADA: menutup pembayaran tanpa memberi tahu user menciptakan teka-teki
 * — mereka mencari tombol upgrade, tidak menemukannya, dan menyimpulkan
 * aplikasinya rusak. Spanduk ini menjawab pertanyaan itu di tempat user
 * bertanya, sekali, lalu bisa ditutup permanen supaya tidak jadi gangguan.
 *
 * Tiga aturan yang dijaga komponen ini:
 *  1. Tidak dirender sama sekali saat pembayaran AKTIF — bukan disembunyikan
 *     dengan CSS, tetapi tidak ada di pohon React.
 *  2. Tidak berkedip saat hidrasi: state `mounted` mencegah render pertama
 *     menampilkan spanduk yang langsung hilang (user sudah menutupnya di
 *     sesi sebelumnya) — pola yang sama dipakai UserMenu untuk tema.
 *  3. `role="status"` + `aria-live="polite"`: diumumkan pembaca layar, tapi
 *     tidak memotong apa yang sedang dibacakan.
 */
export function PaymentBanner() {
  const { t } = useI18n();
  const [mounted, setMounted] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setMounted(true);
    try {
      setDismissed(window.localStorage.getItem(DISMISS_KEY) === "1");
    } catch {
      /* localStorage bisa dilarang (mode privat) — spanduk tetap tampil. */
    }
  }, []);

  if (!PAYMENT_COMING_SOON) return null;
  // Sebelum mount, DOM harus identik dengan HTML statis (yang tidak bisa tahu
  // localStorage) — kalau tidak, React melaporkan hydration mismatch.
  if (!mounted || dismissed) return null;

  const close = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* diabaikan: penutupan tetap berlaku untuk sesi ini */
    }
  };

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="payment-banner"
      className="flex items-start gap-2 border-b border-border bg-accent/5 px-5 py-2.5 text-footnote"
    >
      <Info size={15} strokeWidth={1.75} className="mt-0.5 shrink-0 text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <span className="font-medium text-fg">{t("payment.bannerTitle")}</span>{" "}
        <span className="text-fg-muted">{t("payment.bannerBody")}</span>
      </div>
      <button
        type="button"
        onClick={close}
        aria-label={t("payment.comingSoon") + " — tutup"}
        data-testid="payment-banner-close"
        className="shrink-0 rounded-sm p-1 text-fg-muted transition hover:bg-bg-subtle hover:text-fg"
      >
        <X size={14} strokeWidth={2} aria-hidden />
      </button>
    </div>
  );
}
