"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import {
  MessageSquare,
  Workflow,
  Plus,
  Play,
  Sun,
  Moon,
  Languages,
  LogOut,
  Settings,
  CreditCard,
  HelpCircle,
  Search,
  Plug,
  Boxes,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useAuth } from "@/context/auth";
import { useI18n } from "@/i18n/context";

interface PaletteProps {
  onNewChat: () => void;
  onNewWorkflow: () => void;
}

/**
 * FASE 1: Command palette (Cmd/Ctrl+K) — pola Linear/Vercel.
 * Navigasi (chat/builder/settings/billing/help), aksi (chat baru, workflow
 * baru, jalankan, tema, bahasa, logout), recent (2 sesi terakhir).
 * Nol route baru; semua navigasi via next/navigation.
 */
export function CommandPalette({ onNewChat, onNewWorkflow }: PaletteProps) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { t, locale, setLocale } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const { email, signOut } = useAuth();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router]
  );

  const isDark = mounted && resolvedTheme === "dark";

  const items = useMemo(
    () => [
      { id: "chat", icon: MessageSquare, label: t("nav.chat"), run: () => go("/") },
      { id: "builder", icon: Workflow, label: t("nav.builder"), run: () => go("/builder") },
      { id: "new-chat", icon: Plus, label: t("nav.newChat"), run: () => { setOpen(false); onNewChat(); } },
      { id: "new-wf", icon: Plus, label: t("palette.newWorkflow"), run: () => { setOpen(false); onNewWorkflow(); } },
      { id: "settings", icon: Settings, label: t("userMenu.settings"), run: () => go("/settings") },
      // Integrasi dipisah dari Settings pada 2026-09: /settings = akun &
      // preferensi, /integrations = semua koneksi. Tanpa entri ini, Cmd+K
      // tetap menjadi jalan ke halaman yang salah untuk "connect apa saja".
      { id: "integrations", icon: Plug, label: t("palette.integrations"), keywords: ["integration", "connect", "oauth", "api", "slack", "sheets"], run: () => go("/integrations") },
      { id: "my-integrations", icon: Boxes, label: t("palette.myIntegrations"), keywords: ["installed", "instance", "installed mcp"], run: () => go("/my-integrations") },
      { id: "billing", icon: CreditCard, label: t("userMenu.billing"), run: () => go("/billing") },
      { id: "help", icon: HelpCircle, label: t("userMenu.help"), run: () => go("/help") },
      {
        id: "theme", icon: isDark ? Sun : Moon,
        label: mounted ? (isDark ? t("userMenu.themeLight") : t("userMenu.themeDark")) : t("userMenu.theme"),
        run: () => { setTheme(isDark ? "light" : "dark"); setOpen(false); },
      },
      {
        id: "lang", icon: Languages,
        label: locale === "id" ? "English" : "Bahasa Indonesia",
        run: () => { setLocale(locale === "id" ? "en" : "id"); setOpen(false); },
      },
      ...(email
        ? [{ id: "logout", icon: LogOut, label: t("userMenu.logout"), run: () => { setOpen(false); void signOut(); } }]
        : []),
    ],
    [t, go, onNewChat, onNewWorkflow, isDark, mounted, setTheme, locale, setLocale, email, signOut]
  );

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label={t("palette.label")}
      className="fixed left-1/2 top-[18vh] z-[100] w-[92vw] max-w-lg -translate-x-1/2 overflow-hidden rounded-md border border-border bg-surface-elevated shadow-lg"
    >
      <div className="flex items-center gap-2 border-b border-border px-3">
        <Search size={15} strokeWidth={1.75} className="shrink-0 text-fg-subtle" aria-hidden />
        <Command.Input
          placeholder={t("palette.placeholder")}
          className="h-11 w-full bg-transparent text-callout text-fg outline-none placeholder:text-fg-subtle"
        />
      </div>
      <Command.List className="max-h-[50vh] overflow-y-auto p-1.5">
        <Command.Empty className="px-3 py-6 text-center text-footnote text-fg-subtle">
          {t("palette.empty")}
        </Command.Empty>
        <Command.Group heading={t("palette.group")}>
          {items.map((it) => (
            <Command.Item
              key={it.id}
              onSelect={() => it.run()}
              className="flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-callout normal-case text-fg outline-none data-[selected=true]:bg-bg-subtle aria-selected:bg-bg-subtle"
            >
              <it.icon size={15} strokeWidth={1.75} className="shrink-0 text-fg-subtle" aria-hidden />
              {it.label}
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
      <div className="flex items-center gap-3 border-t border-border px-3 py-2 text-footnote text-fg-subtle">
        <span><kbd className="rounded border border-border bg-bg-subtle px-1">↑↓</kbd> {t("palette.navHint")}</span>
        <span><kbd className="rounded border border-border bg-bg-subtle px-1">↵</kbd> {t("palette.runHint")}</span>
        <span><kbd className="rounded border border-border bg-bg-subtle px-1">esc</kbd> {t("palette.closeHint")}</span>
      </div>
    </Command.Dialog>
  );
}

// Re-export agar Playwright/spec bisa assert ikon Play tanpa import lucide.
export const PaletteRunIcon = Play;
