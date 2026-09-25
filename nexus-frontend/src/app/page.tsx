"use client";

/**
 * `/` — LANDING (FASE 6 final, Opsi 2).
 *
 * KENAPA HALAMAN INI DIPISAH DARI APLIKASI CHAT:
 * Lighthouse mobile `/` terukur 57→70 dengan `mainthread` 4,0-8,0 detik dan
 * 373-1382 KB script. Penyebab dominannya bukan halaman ini, melainkan fakta
 * bahwa `/` dulu MEMUAT SELURUH APLIKASI CHAT: bundle chat, TanStack Query,
 * `motion/framer` (2 chunk ~180 KB), React Flow lewat komponen bersama, dan
 * Shell (Radix dropdown/dialog). Semua itu tidak dibutuhkan untuk sekadar
 * menyambut pengunjung.
 *
 * Aturan yang dipegang halaman ini (dijaga oleh tes):
 *   * TIDAK mengimpor: fitur chat, TanStack Query, zustand canvas, React Flow,
 *     `motion/react`, Shell. Animasi masuk memakai CSS (`prefers-reduced-motion`
 *     dihormati) — lihat `.k-fade-up` di globals.css.
 *   * HERO TIDAK DIANIMASIKAN dari opacity 0. Temuan FASE 6: elemen LCP baru
 *     tercatat saat TERLIHAT, jadi fade-in pada hero menunda LCP.
 *   * Tetap memenuhi a11y: tautan lewati-ke-konten, satu `<h1>`, landmark
 *     `<main>`, target sentuh >= 44 px, dan teks kontras AA.
 */
import Link from "next/link";
import { Bot, ArrowRight, BookOpen, Plug, Workflow } from "lucide-react";
import { I18nProvider, useI18n } from "@/i18n/context";
import { HydrationReady } from "@/i18n/HydrationReady";
import { SkipToContent } from "@/components/SkipToContent";
import { BrandMark } from "@/components/BrandMark";

function Landing() {
  const { t } = useI18n();
  return (
    <>
      <SkipToContent />
      <div className="flex min-h-dvh flex-col bg-bg text-fg">
        <header className="flex items-center justify-between px-5 py-4 sm:px-8">
          <Link href="/chat" aria-label="Katalir" className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <BrandMark data-testid="landing-logo" />
          </Link>
          <Link
            href="/chat"
            className="rounded-md border border-border px-3 py-2 text-footnote text-fg-muted transition-colors hover:text-fg"
          >
            {t("landing.openApp")}
          </Link>
        </header>

        <main id="main-content" tabIndex={-1} className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-5 py-8 sm:px-8">
          <h1 className="text-title1 font-bold leading-tight tracking-tight sm:text-title1">
            {t("landing.title")}
          </h1>
          <p className="mt-4 max-w-xl text-callout leading-relaxed text-fg-muted">
            {t("landing.subtitle")}
          </p>
          <p className="mt-3 max-w-xl text-footnote leading-relaxed text-fg-subtle" data-testid="landing-integrations-note">
            {t("landing.integrationsNote")}
          </p>

          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link
              href="/chat"
              data-testid="landing-cta"
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-5 py-3 text-subhead font-semibold text-accent-fg shadow-sm transition-transform duration-150 ease-out hover:-translate-y-0.5"
            >
              {t("landing.cta")}
              <ArrowRight size={16} strokeWidth={2} aria-hidden />
            </Link>
            <Link
              href="/help"
              data-testid="landing-cta-secondary"
              className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border px-5 py-3 text-subhead font-medium text-fg transition-colors hover:bg-bg-subtle"
            >
              {t("landing.ctaSecondary")}
            </Link>
          </div>

          {/* Di bawah lipatan: animasi CSS dipakai di sini (bukan di hero) supaya
              tidak menunda LCP, dan tetap dihormati saat reduced-motion. */}
          <ul className="k-fade-up mt-10 grid gap-4 sm:grid-cols-3">
            <li className="rounded-xl border border-border bg-surface p-4">
              <Bot size={18} strokeWidth={1.75} aria-hidden className="text-accent" />
              <p className="mt-2 text-[13.5px] font-semibold text-fg">{t("landing.feature1Title")}</p>
              <p className="mt-1 text-footnote leading-relaxed text-fg-muted">{t("landing.feature1Desc")}</p>
            </li>
            <li className="rounded-xl border border-border bg-surface p-4">
              <Workflow size={18} strokeWidth={1.75} aria-hidden className="text-accent" />
              <p className="mt-2 text-[13.5px] font-semibold text-fg">{t("landing.feature2Title")}</p>
              <p className="mt-1 text-footnote leading-relaxed text-fg-muted">{t("landing.feature2Desc")}</p>
            </li>
            <li className="rounded-xl border border-border bg-surface p-4">
              <Plug size={18} strokeWidth={1.75} aria-hidden className="text-accent" />
              <p className="mt-2 text-[13.5px] font-semibold text-fg">{t("landing.feature3Title")}</p>
              <p className="mt-1 text-footnote leading-relaxed text-fg-muted">{t("landing.feature3Desc")}</p>
            </li>
          </ul>
        </main>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 px-5 py-4 text-footnote text-fg-muted sm:px-8">
          <span>{t("landing.footer")}</span>
          <div className="flex flex-wrap items-center gap-4">
            {/* Kredit Glama WAJIB (API Data License). Link TIDAK boleh memakai
                rel nofollow/sponsored/ugc. Jangan dihapus. */}
            <span data-testid="landing-glama-credit">
              {t("landing.glamaCredit")}{" "}
              <a href="https://glama.ai/mcp/servers" target="_blank" rel="noopener noreferrer" className="hover:text-fg">Glama</a>
            </span>
            <Link href="/help" className="inline-flex items-center gap-1.5 hover:text-fg">
              <BookOpen size={13} strokeWidth={1.75} aria-hidden />
              {t("landing.ctaSecondary")}
            </Link>
          </div>
        </footer>
      </div>
    </>
  );
}

/** Provider yang dibutuhkan halaman ini HANYA i18n — tanpa AuthProvider,
 *  QueryProvider, atau Shell. Itulah inti pemisahan ini. */
export default function Page() {
  return (
    <I18nProvider>
      {/* Penanda hidrasi: spec a11y/E2E menunggu `html[data-hydrated='true']`
          sebelum mengukur, jadi landing wajib punya komponen ini (kelas bug yang
          sama pernah terjadi pada rute baru). */}
      <HydrationReady />
      <Landing />
    </I18nProvider>
  );
}
