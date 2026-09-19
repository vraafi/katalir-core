"use client";

import { useI18n } from "@/i18n/context";
import { cn } from "@/lib/cn";

/** Pilihan bahasa di /settings: auto-detect default, override via localStorage.
 *  Non-aktif sengaja bergaya tombol (border + bg-surface + hover) supaya jelas
 *  bisa diklik — sebelumnya hanya teks polos dan user ragu (review visual). */
export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();
  const base =
    "flex-1 rounded-md px-4 py-2 text-callout font-medium transition-all duration-150 ease-apple outline-none focus-visible:shadow-focus active:scale-[0.98] sm:flex-none sm:px-5";
  const active = "bg-accent text-accent-fg shadow-xs";
  const inactive =
    "bg-surface border border-border text-fg-muted hover:border-border-strong hover:bg-bg-subtle hover:text-fg";
  return (
    <div>
      <div className="flex gap-2" role="radiogroup" aria-label={t("settings.language")}>
        <button
          type="button"
          role="radio"
          aria-checked={locale === "id"}
          onClick={() => setLocale("id")}
          className={cn(base, locale === "id" ? active : inactive)}
        >
          {t("settings.languageId")}
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={locale === "en"}
          onClick={() => setLocale("en")}
          className={cn(base, locale === "en" ? active : inactive)}
        >
          {t("settings.languageEn")}
        </button>
      </div>
      <p className="mt-2 text-footnote text-fg-muted">{t("settings.languageNote")}</p>
    </div>
  );
}
