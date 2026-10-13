"use client";

import Link from "next/link";
import { I18nProvider, useI18n } from "@/i18n/context";

/**
 * BUG-07 (2026-10-13): halaman 404 milik sendiri.
 *
 * SEBELUM: `src/app/` tidak punya `not-found.tsx`, jadi Next.js mengekspor
 * halaman bawaannya ke `out/404.html` — teks Inggris 33 karakter
 * ("404: This page could not be found.") tanpa navigasi. Persona pemula yang
 * salah mengetik URL langsung menemui jalan buntu (dead end) tanpa jalan
 * pulang. Bukti: docs/real-user-hard-test-2026-10-13.md §BUG-07 (4 rute uji,
 * semuanya 33 karakter, 0 jalan kembali).
 *
 * SESUDAH: halaman berbahasa Indonesia (mengikuti locale user lewat `useI18n`,
 * sama seperti `public-page.tsx`) dengan dua tautan kembali: Chat dan Beranda.
 *
 * Catatan `output: "export"`: Next.js mengekspor komponen ini sebagai
 * `out/404.html`. Karena itu komponen ini WAJIB aman dirender statis — tidak
 * membaca `useSearchParams`/`usePathname` (yang akan memaksa boundary
 * Suspense dan membuat build gagal pada static export).
 */
const TEXT = {
  id: {
    code: "404",
    title: "Halaman tidak ditemukan",
    desc: "Halaman yang Anda cari mungkin sudah dipindahkan atau dihapus.",
    toChat: "Kembali ke Chat",
    toHome: "Beranda",
  },
  en: {
    code: "404",
    title: "Page not found",
    desc: "The page you are looking for may have been moved or deleted.",
    toChat: "Back to Chat",
    toHome: "Home",
  },
} as const;

function NotFoundCopy() {
  const { locale } = useI18n();
  const t = TEXT[locale] ?? TEXT.id;
  return (
    <main
      id="main-content"
      data-testid="not-found"
      className="mx-auto flex min-h-screen max-w-lg flex-col items-center justify-center px-6 py-16 text-center"
    >
      <p
        className="text-6xl font-bold tracking-tight text-fg-subtle"
        aria-hidden="true"
      >
        {t.code}
      </p>
      <h1 className="mt-4 text-2xl font-semibold">{t.title}</h1>
      <p className="mt-2 text-fg-muted">{t.desc}</p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/chat"
          data-testid="not-found-to-chat"
          className="inline-block rounded-lg bg-accent px-5 py-2.5 font-medium text-white focus-visible:shadow-focus"
        >
          {t.toChat}
        </Link>
        <Link
          href="/"
          data-testid="not-found-to-home"
          className="inline-block rounded-lg border border-border px-5 py-2.5 font-medium focus-visible:shadow-focus"
        >
          {t.toHome}
        </Link>
      </div>
    </main>
  );
}

export default function NotFound() {
  return (
    <I18nProvider>
      <NotFoundCopy />
    </I18nProvider>
  );
}
