"use client";

import { ArrowLeft } from "lucide-react";
import { useBack } from "@/hooks/useBack";
import { useI18n } from "@/i18n/context";

/**
 * Tombol Back untuk halaman akun.
 *
 * Dulu ini `<Link href="/">`, yang mengirim user ke marketing. Sekarang
 * balik ke dalam app: ke halaman sebelumnya kalau navigasi internal
 * terdeteksi, kalau tidak ke fallback (`/chat` untuk user login).
 */
export function BackButton({ fallback = "/chat", className = "" }: { fallback?: string; className?: string }) {
  const goBack = useBack(fallback);
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={goBack}
      data-testid="back-button"
      aria-label={t("common.back")}
      className={`flex h-9 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition hover:bg-bg-subtle ${className}`}
    >
      <ArrowLeft size={15} strokeWidth={2} aria-hidden />
      {t("common.back")}
    </button>
  );
}
