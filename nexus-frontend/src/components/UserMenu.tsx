"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ChevronDown,
  CreditCard,
  HelpCircle,
  LogOut,
  MoreHorizontal,
  Moon,
  Settings,
  Sun,
  Zap,
} from "lucide-react";
import { useAuth } from "@/context/auth";
import { useI18n } from "@/i18n/context";
import { cn } from "@/lib/cn";
import { applyAppTheme, THEME_KEY } from "@/components/ThemeToggle";

/**
 * Link checkout Dodo Payments (Plus: $299 / TAHUN — produk "Katalir").
 * NEXT_PUBLIC_* di-INLINE saat build → perubahan URL = build ulang.
 */
const CHECKOUT_URL = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

interface UserMenuProps {
  /** tier efektif user ("free" | "plus") — diteruskan dari parent agar konsisten. */
  userTier?: "free" | "plus";
  /** Header memakai avatar 32px saja; sidebar mempertahankan email+tier. */
  compact?: boolean;
}

/**
 * Menu akun di footer sidebar (pattern DeepSeek/ChatGPT/Claude):
 * avatar + email diklik → popover dengan Upgrade (paling atas), tema, logout.
 *
 * Aksesibilitas: Radix DropdownMenu menangani role="menu", aria-expanded,
 * Escape-menutup, dan navigasi panah/Tab secara native — tidak perlu
 * implementasi keyboard manual.
 */
export function UserMenu({ userTier = "free", compact = false }: UserMenuProps) {
  const { email, avatarUrl, displayName, signOut } = useAuth();
  const { t } = useI18n();
  const [appTheme, setAppTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    const saved = window.localStorage.getItem(THEME_KEY);
    setAppTheme(saved === "dark" ? "dark" : "light");
  }, []);
  // HYDRATION: resolvedTheme undefined di server → label tema dibuat netral
  // sampai mount (pola sama seperti ThemeToggle).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = appTheme === "dark";
  const isPlus = userTier === "plus";

  const initial = (email?.trim()?.[0] ?? "?").toUpperCase();
  const itemCls =
    "flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-[13px] leading-tight outline-none transition-colors focus:bg-bg-subtle data-[highlighted]:bg-bg-subtle";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`${t("userMenu.accountMenu")} ${email}`}
          aria-haspopup="menu"
          className={compact
            ? "flex h-11 w-11 items-center justify-center rounded-full transition-colors hover:bg-bg-subtle md:hidden"
            : "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-bg-subtle"}
          data-testid="profile-avatar"
        >
          <span
            aria-hidden
            data-testid="profile-avatar-visual"
            style={{ borderRadius: "9999px", aspectRatio: "1 / 1" }}
            className={compact
              ? "flex h-8 w-8 items-center justify-center overflow-hidden !rounded-full border border-border bg-accent/15 text-xs font-bold text-accent"
              : "flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden !rounded-full bg-accent/15 text-[13px] font-bold text-accent"}
          >
            {avatarUrl ? (
              // URL profil berasal dari Google OAuth; next/image static export
              // memakai unoptimized config sehingga host eksternal tetap aman.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={avatarUrl} alt="" className="h-full w-full object-cover" referrerPolicy="no-referrer" />
            ) : initial}
          </span>
          {!compact && (
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium text-fg">{displayName || email}</span>
            </span>
          )}
          {compact ? (
            <ChevronDown size={14} strokeWidth={2} className="shrink-0 text-fg-subtle" aria-hidden />
          ) : (
            <MoreHorizontal size={16} strokeWidth={2} className="shrink-0 text-fg-subtle" aria-hidden />
          )}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side={compact ? "bottom" : "top"}
          align={compact ? "end" : "start"}
          sideOffset={8}
          className="z-[90] w-64 rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
        >
          {!isPlus && CHECKOUT_URL && (
            <>
              <DropdownMenu.Item asChild>
                <a
                  href={CHECKOUT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={cn(itemCls, "font-semibold text-accent")}
                >
                  <Zap size={14} strokeWidth={2} className="shrink-0" aria-hidden />
                  {t("userMenu.upgrade")}
                </a>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
            </>
          )}
          {/* Halaman /settings, /billing, /help sudah live — menu aktif (bukan disabled). */}
          <DropdownMenu.Item asChild>
            <Link href="/settings" className={itemCls}>
              <Settings size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
              {t("userMenu.settings")}
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link href="/billing" className={itemCls}>
              <CreditCard size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
              {t("userMenu.billing")}
            </Link>
          </DropdownMenu.Item>
          {!compact && (
            <DropdownMenu.Item onSelect={() => { const next = isDark ? "light" : "dark"; setAppTheme(next); applyAppTheme(next); }} className={itemCls}>
              {isDark ? <Sun size={14} strokeWidth={1.75} className="shrink-0" aria-hidden /> : <Moon size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />}
              {mounted ? (isDark ? t("userMenu.themeLight") : t("userMenu.themeDark")) : t("userMenu.theme")}
            </DropdownMenu.Item>
          )}
          <DropdownMenu.Item asChild>
            <Link href="/help" className={itemCls}>
              <HelpCircle size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
              {t("userMenu.help")}
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item onSelect={() => void signOut()} className={cn(itemCls, "text-red-500")}>
            <LogOut size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            {t("userMenu.logout")}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
