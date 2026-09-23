"use client";

import { useCallback, useRef, useState } from "react";
import { ChevronUp, Plus, Trash2 } from "lucide-react";
import { META, type Kind } from "./types";
import { useI18n } from "@/i18n/context";
import { StaggerItem, StaggerList } from "@/components/motion";

/**
 * Node Palette (FASE 3).
 *
 * Dua bentuk dari daftar yang SAMA (`PaletteList`), jadi tidak ada risiko
 * "item di sidebar berbeda dengan item di bottom sheet":
 *   - `Palette`      : sidebar 256px (desktop, seperti sebelumnya).
 *   - `PaletteSheet` : bottom sheet yang ditarik ke atas (mobile). Kontrak misi:
 *     "Node palette: bottom sheet drag-up".
 *
 * Warna item memakai token tema kanvas (`--node-trigger-color`,
 * `--node-action-color`, `--node-mcp-color`), bukan warna keras: palette ikut
 * berubah saat user mengganti tema.
 */

function kindColorVar(kind: Kind): string {
  return `var(--node-${kind === "agent" ? "action" : kind}-color)`;
}

function PaletteList({
  onAddNode,
  onClear,
  compact = false,
}: {
  onAddNode: (kind: Kind) => void;
  onClear: () => void;
  compact?: boolean;
}) {
  return (
    <>
      <p className="text-[11px] leading-snug" style={{ color: "var(--canvas-text-secondary)" }}>
        Tarik node ke kanvas, atau klik untuk menaruhnya. Di ponsel: tekan lama node untuk
        mengaktifkan mode geser.
      </p>
      <StaggerList className="flex flex-col gap-3">
        {Object.keys(META).map((k) => {
          const kind: Kind = k as Kind;
          const meta = META[kind];
          const Icon = meta.Icon;
          return (
            <StaggerItem key={kind}>
              <div
                draggable
                data-testid={`palette-item-${kind}`}
                onDragStart={(e) => {
                  e.dataTransfer?.setData("application/reactflow", kind);
                  if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
                }}
                onClick={() => onAddNode(kind)}
                className="flex w-full cursor-grab items-center gap-3 rounded-xl border px-3 py-3 text-left transition-colors"
                style={{
                  borderColor: "var(--node-border)",
                  background: "var(--canvas-panel-bg)",
                  color: "var(--canvas-text-primary)",
                }}
              >
                <span
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-white"
                  style={{ background: kindColorVar(kind), flex: "0 0 32px" }}
                  aria-hidden="true"
                >
                  <Icon size={15} strokeWidth={1.75} />
                </span>
                <span className="flex-1 text-left">
                  <span className="block text-[13px] font-semibold">{meta.label}</span>
                  <span className="block text-[11px]" style={{ color: "var(--canvas-text-secondary)" }}>
                    {meta.desc}
                  </span>
                </span>
                <Plus size={14} strokeWidth={1.75} aria-hidden="true" />
              </div>
            </StaggerItem>
          );
        })}
      </StaggerList>
      <button
        type="button"
        data-testid="palette-clear"
        onClick={onClear}
        className={
          "flex items-center justify-center gap-2 rounded-md border px-3 text-[12px] font-semibold " +
          (compact ? "h-9" : "h-9 w-full")
        }
        style={{ borderColor: "var(--node-error-glow)", color: "var(--node-error-glow)" }}
      >
        <Trash2 size={14} strokeWidth={1.5} aria-hidden="true" />
        Bersihkan alur
      </button>
    </>
  );
}

/** Sidebar desktop. */
export function Palette({
  onAddNode,
  onClear,
}: {
  onAddNode: (kind: Kind) => void;
  onClear: () => void;
}) {
  // FASE 5: nama landmark ikut bahasa pengguna (Palette selalu dirender di
  // dalam I18nProvider — /builder memasangnya di page.tsx).
  const { t } = useI18n();
  return (
    <aside
      data-testid="palette"
      aria-label={t("builder.paletteLabel")}
      className="hidden w-64 flex-col gap-4 border-r p-4 md:flex"
      style={{
        borderColor: "var(--node-border)",
        background: "var(--canvas-panel-bg)",
        color: "var(--canvas-text-primary)",
      }}
    >
      <div className="text-[11px] font-bold uppercase tracking-wide">Node Palette</div>
      <PaletteList onAddNode={onAddNode} onClear={onClear} />
    </aside>
  );
}

/** Jarak tarik (px) yang dianggap "membuka" bottom sheet. */
export const SHEET_DRAG_OPEN_PX = 40;

/**
 * Bottom sheet mobile: bar kecil di bawah yang bisa DITARIK KE ATAS (drag-up)
 * atau cukup di-tap. Tarikan mengikuti jari (`translateY`), dan sheet hanya
 * dibuka bila melewati ambang 40px supaya sentuhan tak sengaja tidak membuka.
 */
export function PaletteSheet({

  onAddNode,
  onClear,
}: {
  onAddNode: (kind: Kind) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dragY, setDragY] = useState(0);
  const dragging = useRef(false);
  const startY = useRef(0);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragging.current = true;
    startY.current = e.clientY;
    setDragY(0);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const dy = e.clientY - startY.current;
    // hanya tarikan KE ATAS yang diikuti (dy negatif)
    setDragY(Math.min(0, dy));
  }, []);

  const onPointerUp = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    if (dragY <= -SHEET_DRAG_OPEN_PX) setOpen(true);
    setDragY(0);
  }, [dragY]);

  return (
    <>
      {!open && (
        <button
          type="button"
          data-testid="palette-sheet-trigger"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onClick={() => setOpen(true)}
          aria-label="Buka node palette"
          aria-expanded={open}
          className="fixed inset-x-0 bottom-0 z-30 flex h-12 touch-none items-center justify-center gap-2 border-t md:hidden"
          style={{
            borderColor: "var(--node-border)",
            background: "var(--canvas-panel-bg)",
            color: "var(--canvas-text-primary)",
            transform: `translateY(${dragY}px)`,
          }}
        >
          <span
            aria-hidden="true"
            className="absolute left-1/2 top-1.5 h-1 w-10 -translate-x-1/2 rounded-full"
            style={{ background: "var(--node-border)" }}
          />
          <ChevronUp size={15} strokeWidth={1.75} aria-hidden="true" />
          <span className="text-[12px] font-semibold">Node Palette</span>
        </button>
      )}

      {open && (
        <div
          data-testid="palette-sheet"
          role="dialog"
          aria-modal="true"
          aria-label="Node Palette"
          className="fixed inset-x-0 bottom-0 z-40 max-h-[80vh] overflow-y-auto rounded-t-2xl border-t p-4 md:hidden"
          style={{
            borderColor: "var(--node-border)",
            background: "var(--canvas-panel-bg)",
            color: "var(--canvas-text-primary)",
          }}
        >
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wide">Node Palette</span>
            <button
              type="button"
              data-testid="palette-sheet-close"
              onClick={() => setOpen(false)}
              aria-label="Tutup node palette"
              className="rounded-md border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--node-border)" }}
            >
              Tutup ✕
            </button>
          </div>
          <div className="flex flex-col gap-3">
            <PaletteList onAddNode={onAddNode} onClear={onClear} compact />
          </div>
        </div>
      )}
    </>
  );
}
