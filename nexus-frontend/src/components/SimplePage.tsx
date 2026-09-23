"use client";

import Link from "next/link";
import { Suspense } from "react";
import { ArrowLeft } from "lucide-react";
import { AuthProvider } from "@/context/auth";
import { QueryProvider } from "@/features/builder/provider";
import { I18nProvider, useI18n } from "@/i18n/context";
import { HydrationReady } from "@/i18n/HydrationReady";
import { CanvasThemeProvider } from "@/features/builder/themes/CanvasThemeProvider";
import { PageTransition } from "@/components/PageTransition";
import { CommandPalette } from "@/components/CommandPalette";

/**
 * Layout minimal untuk halaman akun (/settings, /billing, /help).
 *
 * SENGAJA tidak memakai Shell sidebar chat: halaman-halaman ini tidak butuh
 * daftar sesi, dan Shell mewajibkan props sessions — memaksanya masuk akan
 * menambah fetch yang tidak perlu. Navbar minimal: logo + tombol kembali.
 * AuthProvider + QueryProvider tetap dipasang agar useAuth/useMeQuery jalan
 * (pola sama seperti page.tsx root).
 *
 * Suspense DI DALAM page: useSearchParams (nuqs) dan Supabase getSession
 * butuh CSR-bailout saat prerender statis ("missing-suspense-with-csr-bailout").
 */
export function SimplePage({ title, subtitle, children, maxW = "max-w-2xl" }: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  maxW?: string;
}) {
  return (
    <Suspense fallback={null}>
      <AuthProvider>
        <QueryProvider>
          <I18nProvider>
            {/* FASE 4: halaman akun (/settings) memilih tema KANVAS juga, jadi
                provider-nya dipasang di sini. Hanya menulis `data-canvas-theme`
                pada <html> + token kanvas; halaman non-kanvas tidak memakai
                kelas `.k-*`, sehingga tidak ada efek visual tak diinginkan. */}
            <CanvasThemeProvider>
              <SimplePageInner title={title} subtitle={subtitle} maxW={maxW}>
                {children}
              </SimplePageInner>
            </CanvasThemeProvider>
          </I18nProvider>
        </QueryProvider>
      </AuthProvider>
    </Suspense>
  );
}

/** Kerangka di DALAM provider — judul ikut diterjemahkan bila berupa key i18n. */
function SimplePageInner({
  title,
  subtitle,
  children,
  maxW,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  maxW: string;
}) {
  const { t } = useI18n();
  const tr = (s: string) => (s.includes(".") && !s.includes(" ") ? t(s) : s);
  return (
          <div className="min-h-screen bg-bg text-fg">
            {/* FASE 4 (Lighthouse `skip-link`): lompatan ke konten untuk pengguna
                keyboard/screen reader — terlihat saat fokus, tersembunyi
                sebaliknya (pola `sr-only focus:not-sr-only`). */}
            <a
              href="#main-content"
              className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[200] focus:rounded-md focus:border focus:border-border focus:bg-surface focus:px-3 focus:py-2 focus:text-subhead focus:text-fg"
            >
              {t("common.skipToContent")}
            </a>
            {/* Penanda hidrasi rute statis (settings/billing/help): locale
                diganti hanya setelah subtree ini selesai dihidrasi. */}
            <HydrationReady />
            <nav className="flex items-center justify-between border-b border-border px-5 py-3">
              <Link href="/" className="text-xl font-bold tracking-tight text-fg">
                Katalir
              </Link>
              <Link
                href="/"
                className="flex h-9 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition hover:bg-bg-subtle"
              >
                <ArrowLeft size={15} strokeWidth={2} aria-hidden />
                {t("common.back")}
              </Link>
            </nav>
            <main id="main-content" tabIndex={-1} className={`mx-auto ${maxW} px-5 py-8 outline-none`}>
              <PageTransition>
                <h1 className="text-title2 font-bold tracking-tight">{tr(title)}</h1>
                {subtitle && <p className="mt-1 text-callout text-fg-muted">{tr(subtitle)}</p>}
                <div className="mt-6 flex flex-col gap-4">{children}</div>
              </PageTransition>
            </main>
            {/* FASE 4: command palette juga tersedia di halaman akun.
                Sebelumnya hanya Shell (dipakai / dan /builder) yang memasangnya,
                sehingga Ctrl+K tidak melakukan apa pun di /settings, /billing,
                /help — padahal pintasan itu didokumentasikan di cheat sheet.
                from="/" -> halaman akun ini tidak punya aksi "chat baru"
                khusus, jadi keduanya mengarah ke beranda/builder. */}
            <CommandPalette
              onNewChat={() => { window.location.href = "/"; }}
              onNewWorkflow={() => { window.location.href = "/builder"; }}
            />
          </div>
  );
}
