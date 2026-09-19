"use client";

import { useEffect, useState } from "react";
import { Moon, Sun, MonitorSmartphone } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { useAuth } from "@/context/auth";
import { useI18n } from "@/i18n/context";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/** Konten Pengaturan — dipakai di DALAM SimplePage (SimplePage yang memegang provider).
 *  TIDAK di-export (aturan App Router: hanya default + metadata yang boleh di-export
 *  dari page.tsx; named export lain merusak type-check route). */
function SettingsContent() {
  const { email } = useAuth();
  const { t } = useI18n();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const initial = (email?.trim()?.[0] ?? "?").toUpperCase();
  const themeVal = mounted ? (theme ?? "system") : "system";
  const themeOpt =
    "flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2.5 text-[13px] transition-colors";

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.profile")}</CardTitle>
          <CardDescription>{t("settings.profileDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[17px] font-bold text-accent"
            >
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate text-callout font-medium text-fg">{email ?? t("common.loading")}</p>
              <p className="text-footnote text-fg-muted">{t("settings.loginVia")}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.preferences")}</CardTitle>
          <CardDescription>{t("settings.preferencesDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="mb-2 text-footnote font-semibold uppercase tracking-wide text-fg-subtle">{t("settings.theme")}</p>
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label={t("settings.theme")}>
            {(
              [
                { id: "light", label: t("settings.themeLight"), Icon: Sun },
                { id: "dark", label: t("settings.themeDark"), Icon: Moon },
                { id: "system", label: t("settings.themeSystem"), Icon: MonitorSmartphone },
              ] as const
            ).map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={themeVal === id}
                onClick={() => setTheme(id)}
                className={cn(
                  themeOpt,
                  themeVal === id
                    ? "border-accent bg-accent/10 font-medium text-fg"
                    : "border-border text-fg-muted hover:bg-bg-subtle hover:text-fg"
                )}
              >
                <Icon size={15} strokeWidth={1.75} aria-hidden />
                {label}
              </button>
            ))}
          </div>
          <p className="mb-2 mt-5 text-footnote font-semibold uppercase tracking-wide text-fg-subtle">{t("settings.language")}</p>
          <LanguageSwitcher />
        </CardContent>
      </Card>

      <Card className="border-danger/40">
        <CardHeader>
          <CardTitle className="text-danger">{t("settings.dangerZone")}</CardTitle>
          <CardDescription>{t("settings.dangerDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="danger" onClick={() => toast.info(t("settings.deleteToast"))}>
            {t("settings.deleteAccount")}
          </Button>
        </CardContent>
      </Card>
    </>
  );
}

/** Route /settings: SimplePage (provider) + konten. Judul memakai KEY i18n
 *  supaya ikut bahasa aktif (SimplePageInner menerjemahkannya di dalam
 *  I18nProvider). */
export default function SettingsPage() {
  return (
    <SimplePage title="settings.title" subtitle="settings.subtitle">
      <SettingsContent />
    </SimplePage>
  );
}
