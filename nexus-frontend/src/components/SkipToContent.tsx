"use client";

import { useI18n } from "@/i18n/context";

/**
 * FASE 5 — tautan "lewati ke konten".
 *
 * Sebelumnya tautan ini hidup di `app/layout.tsx` dan menunjuk `#main`, padahal
 * TIDAK ADA elemen ber-`id="main"` di seluruh aplikasi. Akibatnya audit
 * Lighthouse/axe `skip-link` merah ("Skip links are not focusable / No skip link
 * target", bobot 3 poin di kategori Accessibility) sementara pengguna keyboard
 * yang menekan Tab lalu Enter benar-benar tidak dibawa ke mana pun.
 *
 * Kenapa dipindah ke Shell/SimplePage (bukan layout):
 * `useI18n()` melempar error di luar `<I18nProvider>`, dan provider dipasang di
 * level halaman, bukan di root layout. Menaruh tautan di root layout berarti
 * melewati provider (harus menduplikasi deteksi locale) ATAU menampilkan teks
 * yang tidak ikut bahasa pengguna. Karena itu tautan ini dirender oleh kedua
 * kerangka halaman (Shell untuk `/`, `/chat`, `/builder`; SimplePage untuk
 * `/settings`, `/billing`, `/help`), dan tes `fase5-a11y.spec.ts` memastikan
 * setiap rute punya TEPAT satu tautan yang targetnya benar-benar ada.
 */
export function SkipToContent() {
  const { t } = useI18n();
  return (
    <a
      data-testid="skip-link"
      href="#main-content"
      className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[200] focus:rounded-md focus:border focus:border-border focus:bg-surface focus:px-3 focus:py-2 focus:text-subhead focus:text-fg"
    >
      {t("common.skipToContent")}
    </a>
  );
}
