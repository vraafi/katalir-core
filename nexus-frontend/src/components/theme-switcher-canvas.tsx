"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, Palette } from "lucide-react";
import { useCanvasTheme } from "@/features/builder/themes/CanvasThemeProvider";
import { THEMES, type CanvasTheme, type CanvasThemeId } from "@/features/builder/themes/canvas-themes";

/**
 * Pemilih tema kanvas (FASE 3).
 *
 * Terpisah dari mode gelap/terang aplikasi (`next-themes`, di ThemeToggle):
 * tema kanvas HANYA mengubah kanvas Builder (4 pilihan: Midnight, Daylight,
 * Cyberpunk, Minimal) dan tidak menyentuh shell/chat.
 *
 * Setiap item menampilkan PREVIEW MINI-KANVAS yang dirender dari token tema
 * yang sama dengan kanvas asli — bukan gambar statis. Konsekuensinya preview
 * tidak bisa "bohong": kalau token berubah, preview ikut berubah.
 *
 * Aksesibilitas: Radix DropdownMenu membawa role="menu", aria-expanded,
 * Escape-menutup, dan navigasi panah tanpa implementasi manual. Setiap item
 * memakai `aria-checked` (pola radio) sehingga status pilihan terbaca asisten.
 */
function MiniPreview({ theme }: { theme: CanvasTheme }) {
  return (
    <span
      aria-hidden="true"
      data-testid={`theme-preview-${theme.id}`}
      style={{
        display: "block",
        width: 56,
        height: 36,
        borderRadius: 8,
        background: theme.canvasBg,
        border: `1px solid ${theme.nodeBorder}`,
        backgroundImage: `radial-gradient(${theme.gridColor} 1px, transparent 1px)`,
        backgroundSize: "6px 6px",
        overflow: "hidden",
        position: "relative",
        flex: "0 0 56px",
      }}
    >
      <span
        style={{
          position: "absolute",
          left: 6,
          top: 7,
          width: 18,
          height: 10,
          borderRadius: 3,
          background: theme.nodeBg,
          border: `1px solid ${theme.nodeBorder}`,
        }}
      />
      <span
        style={{
          position: "absolute",
          left: 30,
          top: 19,
          width: 20,
          height: 10,
          borderRadius: 3,
          background: theme.kindColor.agent,
        }}
      />
      <span
        style={{
          position: "absolute",
          left: 24,
          top: 12,
          width: 7,
          height: 2,
          background: theme.edge,
        }}
      />
    </span>
  );
}

export function ThemeSwitcherCanvas({ compact = false }: { compact?: boolean }) {
  const { themeId, setTheme, mounted } = useCanvasTheme();
  const active = THEMES[themeId];

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label="Tema Kanvas"
          data-testid="canvas-theme-trigger"
          className={
            "flex items-center gap-2 rounded-md border px-2 text-[12px] font-medium transition-colors " +
            (compact ? "h-8" : "h-8 px-2.5")
          }
          style={{
            borderColor: "var(--node-border)",
            background: "var(--canvas-panel-bg)",
            color: "var(--canvas-text-primary)",
          }}
        >
          <Palette size={14} strokeWidth={1.75} aria-hidden="true" />
          <span className="hidden sm:inline">{mounted ? active.name : "Tema Kanvas"}</span>
          <span className="sm:hidden">Tema</span>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          data-testid="canvas-theme-menu"
          className="z-[90] w-72 rounded-xl border p-1.5 shadow-lg"
          style={{
            background: "var(--canvas-panel-bg)",
            borderColor: "var(--node-border)",
            color: "var(--canvas-text-primary)",
          }}
        >
          <DropdownMenu.Label className="px-2 py-1.5 text-[10px] font-bold uppercase tracking-wide opacity-60">
            Tema Kanvas
          </DropdownMenu.Label>

          <DropdownMenu.RadioGroup value={themeId} onValueChange={(v) => setTheme(v as CanvasThemeId)}>
            {Object.values(THEMES).map((t) => {
              const checked = t.id === themeId;
              return (
                <DropdownMenu.RadioItem
                  key={t.id}
                  value={t.id}
                  aria-checked={checked}
                  data-testid={`canvas-theme-option-${t.id}`}
                  className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 outline-none data-[highlighted]:bg-[color:var(--node-hover-bg)]"
                >
                  <MiniPreview theme={t} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold">{t.name}</span>
                    <span className="block text-[11px] opacity-60">{t.description}</span>
                  </span>
                  {checked && <Check size={14} strokeWidth={2} aria-hidden="true" />}
                </DropdownMenu.RadioItem>
              );
            })}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
