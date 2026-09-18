"use client";

import { useEffect, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useTheme } from "next-themes";
import {
  ChevronUp,
  CreditCard,
  HelpCircle,
  LogOut,
  Moon,
  Settings,
  Sun,
  Zap,
} from "lucide-react";
import { useAuth } from "@/context/auth";
import { cn } from "@/lib/cn";

/**
 * Link checkout Dodo Payments (Plus: $299 / TAHUN — produk "Katalir").
 * NEXT_PUBLIC_* di-INLINE saat build → perubahan URL = build ulang.
 */
const CHECKOUT_URL = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

interface UserMenuProps {
  /** tier efektif user ("free" | "plus") — diteruskan dari parent agar konsisten. */
  userTier?: "free" | "plus";
}

/**
 * Menu akun di footer sidebar (pattern DeepSeek/ChatGPT/Claude):
 * avatar + email diklik → popover dengan Upgrade (paling atas), tema, logout.
 *
 * Aksesibilitas: Radix DropdownMenu menangani role="menu", aria-expanded,
 * Escape-menutup, dan navigasi panah/Tab secara native — tidak perlu
 * implementasi keyboard manual.
 */
export function UserMenu({ userTier = "free" }: UserMenuProps) {
  const { email, signOut } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  // HYDRATION: resolvedTheme undefined di server → label tema dibuat netral
  // sampai mount (pola sama seperti ThemeToggle).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = mounted && resolvedTheme === "dark";
  const isPlus = userTier === "plus";

  const initial = (email?.trim()?.[0] ?? "?").toUpperCase();
  const itemCls =
    "flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-[13px] leading-tight outline-none transition-colors focus:bg-bg-subtle data-[highlighted]:bg-bg-subtle";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`Menu akun ${email}`}
          aria-haspopup="menu"
          className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-bg-subtle"
        >
          <span
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[13px] font-bold text-accent"
          >
            {initial}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-fg">{email}</span>
            <span className="block text-[11px] text-fg-subtle">{isPlus ? "Plus" : "Free"}</span>
          </span>
          <ChevronUp size={14} strokeWidth={2} className="shrink-0 text-fg-subtle" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="top"
          align="start"
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
                  Upgrade ke Plus — $299 / tahun
                </a>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
            </>
          )}
          {/* Belum ada route-nya → disabled jujur (bukan link mati). */}
          <DropdownMenu.Item
            disabled
            title="Segera hadir"
            className={cn(itemCls, "cursor-not-allowed text-fg-subtle")}
          >
            <Settings size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            Pengaturan Akun
          </DropdownMenu.Item>
          <DropdownMenu.Item
            disabled
            title="Segera hadir"
            className={cn(itemCls, "cursor-not-allowed text-fg-subtle")}
          >
            <CreditCard size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            Billing
          </DropdownMenu.Item>
          <DropdownMenu.Item
            onSelect={() => setTheme(isDark ? "light" : "dark")}
            className={itemCls}
          >
            {isDark ? (
              <Sun size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            ) : (
              <Moon size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            )}
            {mounted ? (isDark ? "Tema terang" : "Tema gelap") : "Tema"}
          </DropdownMenu.Item>
          <DropdownMenu.Item
            disabled
            title="Segera hadir"
            className={cn(itemCls, "cursor-not-allowed text-fg-subtle")}
          >
            <HelpCircle size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            Bantuan
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item onSelect={() => void signOut()} className={cn(itemCls, "text-red-500")}>
            <LogOut size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
            Logout
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
