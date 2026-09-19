"use client";

import { useI18n } from "@/i18n/context";
import { cn } from "@/lib/cn";

/** Pilihan bahasa di /settings: auto-detect default, override via localStorage. */
export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();
  const base =
    "flex-1 rounded-md px-4 py-2 text-callout transition-colors sm:flex-none sm:px-5";
  return (
    <div>
      <div className="flex gap-2" role="radiogroup" aria-label={t("settings.language")}>
        <button
          type="button"
          role="radio"
          aria-checked={locale === "id"}
          onClick={() => setLocale("id")}
          className={cn(
            base,
            locale === "id"
              ? "bg-accent font-medium text-white"
              : "bg-bg-subtle text-fg-muted hover:text-fg"
          )}
        >
          {t("settings.languageId")}
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={locale === "en"}
          onClick={() => setLocale("en")}
          className={cn(
            base,
            locale === "en"
              ? "bg-accent font-medium text-white"
              : "bg-bg-subtle text-fg-muted hover:text-fg"
          )}
        >
          {t("settings.languageEn")}
        </button>
      </div>
      <p className="mt-2 text-footnote text-fg-muted">{t("settings.languageNote")}</p>
    </div>
  );
}
