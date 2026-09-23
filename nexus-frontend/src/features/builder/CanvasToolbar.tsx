"use client";

import {
  LayoutGrid,
  Map as MapIcon,
  Maximize2,
  Minus,
  Play,
  Plus,
  Redo2,
  Save,
  Undo2,
} from "lucide-react";
import { ThemeSwitcherCanvas } from "@/components/theme-switcher-canvas";

/**
 * Toolbar kanvas (FASE 3).
 *
 * Berisi (kontrak misi): Auto Layout (dagre), Fit View, Zoom in/out, Undo/Redo,
 * Tema Kanvas, dan Save/Run yang sudah ada sejak sebelumnya.
 *
 * Ditempatkan DI LUAR `<ReactFlow>` (bukan `<Panel>`): tombol di dalam Panel
 * ikut terkena transform viewport saat kanvas di-pan/zoom, dan posisinya
 * relatif terhadap aliran — toolbar harus tetap menempel di layar.
 *
 * Kenapa tombol teks berubah jadi ikon di layar sempit: di 390px, tujuh tombol
 * berlabel akan memakan seluruh lebar kanvas. Yang dipertahankan selalu terlihat
 * adalah Save/Run (aksi utama pengguna awam); sisanya ikon dengan `aria-label`
 * + `title` sehingga tetap terbaca asisten dan tooltip.
 */
export function CanvasToolbar({
  onAutoLayout,
  onFitView,
  onZoomIn,
  onZoomOut,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  save,
  saveState,
  run,
  runState,
  minimapOpen,
  onToggleMinimap,
  compact,
}: {
  onAutoLayout: () => void;
  onFitView: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  save: () => void;
  saveState: "idle" | "saving" | "ok" | "err";
  run: () => void;
  runState: "idle" | "running" | "ok" | "err";
  minimapOpen: boolean;
  onToggleMinimap: () => void;
  compact: boolean;
}) {
  const iconBtn =
    "flex h-8 w-8 items-center justify-center rounded-md border transition-colors disabled:opacity-35";
  const iconStyle = {
    borderColor: "var(--node-border)",
    background: "var(--canvas-panel-bg)",
    color: "var(--canvas-text-primary)",
  } as const;

  return (
    <div
      data-testid="canvas-toolbar"
      className="pointer-events-auto flex flex-nowrap items-center justify-end gap-1.5 rounded-xl border p-1.5 shadow-lg"
      style={{ ...iconStyle, borderColor: "var(--node-border)" }}
    >
      <button
        type="button"
        data-testid="btn-auto-layout"
        onClick={onAutoLayout}
        aria-label="Auto Layout"
        title="Auto Layout (dagre)"
        className="flex h-8 items-center gap-1.5 rounded-md border px-2 text-[12px] font-medium"
        style={iconStyle}
      >
        <LayoutGrid size={14} strokeWidth={1.75} aria-hidden="true" />
        <span className="hidden xl:inline">Auto Layout</span>
      </button>

      <button type="button" data-testid="btn-fit-view" onClick={onFitView} aria-label="Fit View" title="Fit View" className={iconBtn} style={iconStyle}>
        <Maximize2 size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>
      <button type="button" data-testid="btn-zoom-in" onClick={onZoomIn} aria-label="Zoom In" title="Zoom In" className={iconBtn} style={iconStyle}>
        <Plus size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>
      <button type="button" data-testid="btn-zoom-out" onClick={onZoomOut} aria-label="Zoom Out" title="Zoom Out" className={iconBtn} style={iconStyle}>
        <Minus size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>

      <button
        type="button"
        data-testid="btn-undo"
        onClick={onUndo}
        disabled={!canUndo}
        aria-label="Undo"
        title="Undo (Ctrl/Cmd+Z)"
        className={iconBtn}
        style={iconStyle}
      >
        <Undo2 size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>
      <button
        type="button"
        data-testid="btn-redo"
        onClick={onRedo}
        disabled={!canRedo}
        aria-label="Redo"
        title="Redo (Ctrl/Cmd+Shift+Z)"
        className={iconBtn}
        style={iconStyle}
      >
        <Redo2 size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>

      <button
        type="button"
        data-testid="btn-toggle-minimap"
        onClick={onToggleMinimap}
        aria-pressed={minimapOpen}
        aria-label="Tampilkan minimap"
        title="Minimap"
        className={iconBtn}
        style={iconStyle}
      >
        <MapIcon size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>

      <ThemeSwitcherCanvas compact={compact} />

      <button
        type="button"
        data-testid="btn-save"
        onClick={save}
        disabled={saveState === "saving"}
        className="flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-[color:var(--canvas-accent-fg)] disabled:opacity-50"
        style={{ background: "var(--canvas-accent-solid)" }}
      >
        <Save size={14} strokeWidth={1.75} aria-hidden="true" />
        <span>{saveState === "saving" ? "Menyimpan…" : compact ? "Simpan" : "Simpan Alur"}</span>
      </button>
      <button
        type="button"
        data-testid="btn-run"
        onClick={run}
        disabled={runState === "running"}
        className="flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-[color:var(--node-success-fg)] disabled:opacity-50"
        style={{ background: "var(--node-success-solid)" }}
      >
        <Play size={14} strokeWidth={1.75} aria-hidden="true" />
        <span>{runState === "running" ? "Menjalankan…" : compact ? "Jalankan" : "Jalankan Alur"}</span>
      </button>
    </div>
  );
}
