"use client";

import { useMemo, useRef, useState } from "react";
import { Mail, Search } from "lucide-react";
import { useI18n } from "@/i18n/context";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

/**
 * Halaman Bantuan (FASE 4.3 — rebuild).
 *
 * YANG DITAMBAH dibanding versi sebelumnya (7 FAQ + kontak, satu kolom):
 *   1. PENCARIAN yang benar-benar menyaring FAQ (judul + isi) — sebelumnya user
 *      harus membaca 7 akordeon manual. `aria-live` mengumumkan jumlah hasil.
 *   2. NAVIGASI SIDEBAR (sticky di desktop, daftar ringkas di mobile) menuju
 *      Bagian: FAQ / Pintasan / Kontak.
 *   3. CHEAT SHEET pintasan keyboard. Isinya HANYA pintasan yang punya binding
 *      nyata: command palette (FASE 1), undo/redo & hapus di kanvas, serta
 *      zoom/fit kanvas yang BARU dipasang di FASE 4 (sebelumnya tombol hanya
 *      menampilkan hint "Fit View (0)" tanpa binding — janji tanpa bukti).
 *
 * Kata kunci pencarian dicocokkan tanpa membedakan huruf besar/kecil dan
 * menembus judul maupun jawaban.
 */

/** Pintasan yang benar-benar terpasang di aplikasi (bukan aspirasi). */
const SHORTCUTS: { keys: string; labelKey: string }[] = [
  { keys: "Cmd/Ctrl + K", labelKey: "help.scPalette" },
  { keys: "Enter", labelKey: "help.scEnter" },
  { keys: "Esc", labelKey: "help.scEsc" },
  { keys: "Cmd/Ctrl + Z", labelKey: "help.scUndo" },
  { keys: "Cmd/Ctrl + Shift + Z", labelKey: "help.scRedo" },
  { keys: "Delete / Backspace", labelKey: "help.scDelete" },
  { keys: "+", labelKey: "help.scZoomIn" },
  { keys: "-", labelKey: "help.scZoomOut" },
  { keys: "0", labelKey: "help.scFit" },
  { keys: "1", labelKey: "help.scReset" },
];

/** Konten Bantuan (tanpa hook auth — aman dipakai di dalam SimplePage). */
function HelpContent() {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const faqRef = useRef<HTMLDivElement | null>(null);
  const scRef = useRef<HTMLDivElement | null>(null);
  const contactRef = useRef<HTMLDivElement | null>(null);

  const faqs = useMemo(
    () =>
      [1, 2, 3, 4, 5, 6, 7].map((n) => ({
        q: t(`help.faq${n}q`),
        a: t(`help.faq${n}a`),
      })),
    [t]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return faqs;
    return faqs.filter((f) => f.q.toLowerCase().includes(q) || f.a.toLowerCase().includes(q));
  }, [faqs, query]);

  const jump = (ref: React.RefObject<HTMLDivElement | null>) =>
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-6">
      {/* NAVIGASI SIDEBAR (sticky di desktop) */}
      <nav
        aria-label={t("help.sections")}
        data-testid="help-nav"
        className="flex shrink-0 gap-2 overflow-x-auto lg:w-48 lg:flex-col lg:overflow-visible"
      >
        <p className="hidden text-caption font-semibold uppercase tracking-wide text-fg-subtle lg:block">
          {t("help.sections")}
        </p>
        {(
          [
            { id: "help-faq", label: t("help.sectionFaq"), ref: faqRef },
            { id: "help-shortcuts", label: t("help.sectionShortcuts"), ref: scRef },
            { id: "help-contact", label: t("help.sectionContact"), ref: contactRef },
          ] as const
        ).map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => jump(s.ref)}
            className="shrink-0 rounded-md border border-border px-2.5 py-1.5 text-left text-footnote text-fg-muted transition-colors hover:bg-bg-subtle hover:text-fg focus-visible:shadow-focus lg:border-transparent"
          >
            {s.label}
          </button>
        ))}
      </nav>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div>
          <label htmlFor="help-search" className="text-footnote font-medium text-fg">
            {t("help.searchLabel")}
          </label>
          <div className="relative mt-1">
            <Search
              size={15}
              strokeWidth={1.75}
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle"
            />
            <Input
              id="help-search"
              data-testid="help-search"
              type="search"
              className="pl-9"
              placeholder={t("help.searchPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <p aria-live="polite" className="mt-1 text-caption text-fg-subtle" data-testid="help-count">
            {query.trim() ? t("help.resultsCount", { n: filtered.length }) : ""}
          </p>
        </div>

        <Card data-testid="help-faq">
          <CardHeader>
            <CardTitle>{t("help.sectionFaq")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div ref={faqRef} className="scroll-mt-20" />
            {filtered.length === 0 ? (
              <p className="text-footnote text-fg-muted" data-testid="help-no-results">
                {t("help.noResults", { q: query.trim() })}
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {filtered.map((f) => (
                  <details
                    key={f.q}
                    data-testid="help-faq-item"
                    className="group rounded-md border border-border px-3.5 py-2.5 transition-colors open:bg-bg-subtle/50"
                  >
                    <summary className="cursor-pointer list-none text-[13px] font-medium text-fg outline-none focus-visible:underline [&::-webkit-details-marker]:hidden">
                      {f.q}
                    </summary>
                    <p className="mt-1.5 text-footnote leading-relaxed text-fg-muted">{f.a}</p>
                  </details>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* CHEAT SHEET — hanya pintasan yang punya binding nyata */}
        <Card data-testid="help-shortcuts">
          <CardHeader>
            <CardTitle>{t("help.sectionShortcuts")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div ref={scRef} className="scroll-mt-20" />
            <p className="mb-3 text-footnote text-fg-muted">{t("help.shortcutsDesc")}</p>
            <dl className="grid gap-1.5 sm:grid-cols-2" data-testid="shortcut-list">
              {SHORTCUTS.map((s) => (
                <div
                  key={s.keys}
                  className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-1.5"
                >
                  <dt className="text-footnote text-fg-muted">{t(s.labelKey)}</dt>
                  <dd>
                    <kbd className="rounded-sm border border-border bg-bg-subtle px-1.5 py-0.5 font-mono text-caption text-fg">
                      {s.keys}
                    </kbd>
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        {/* KONTAK */}
        <Card data-testid="help-contact">
          <CardHeader>
            <CardTitle>{t("help.contact")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div ref={contactRef} className="scroll-mt-20" />
            <div className="flex items-center gap-2.5 text-[13px]">
              <Mail size={15} strokeWidth={1.75} className="shrink-0 text-fg-subtle" aria-hidden />
              <a href={`mailto:${t("help.contactEmail")}`} className="font-medium text-accent hover:underline">
                {t("help.contactEmail")}
              </a>
              <span className="text-fg-subtle">{t("help.contactResponse")}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/** Route /help: SimplePage (provider) + konten. */
export default function HelpPage() {
  return (
    <SimplePage title="help.title" subtitle="help.subtitle" maxW="max-w-5xl">
      <HelpContent />
    </SimplePage>
  );
}


