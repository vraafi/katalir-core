"use client";

import Link from "next/link";
import { Suspense } from "react";
import { ArrowLeft } from "lucide-react";
import { AuthProvider } from "@/context/auth";
import { QueryProvider } from "@/features/builder/provider";

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
          <div className="min-h-screen bg-bg text-fg">
            <nav className="flex items-center justify-between border-b border-border px-5 py-3">
              <Link href="/" className="text-xl font-bold tracking-tight text-fg">
                Katalir
              </Link>
              <Link
                href="/"
                className="flex h-9 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition hover:bg-bg-subtle"
              >
                <ArrowLeft size={15} strokeWidth={2} aria-hidden />
                Kembali
              </Link>
            </nav>
            <main className={`mx-auto ${maxW} px-5 py-8`}>
              <h1 className="text-title2 font-bold tracking-tight">{title}</h1>
              {subtitle && <p className="mt-1 text-callout text-fg-muted">{subtitle}</p>}
              <div className="mt-6 flex flex-col gap-4">{children}</div>
            </main>
          </div>
        </QueryProvider>
      </AuthProvider>
    </Suspense>
  );
}
