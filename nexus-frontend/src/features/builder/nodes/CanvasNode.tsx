"use client";

import { useEffect, useRef, useState } from "react";
import { Handle, NodeToolbar, Position } from "@xyflow/react";
import { Copy, Trash2 } from "lucide-react";
import { NodeStatusIndicator, type NodeStatus } from "@/components/ui/node-status-indicator";
import { useCanvasStore } from "../store/canvas-store";
import { META, type FlowNodeData, type Kind } from "../types";

/**
 * Kartu node kanvas (FASE 3).
 *
 * Struktur (kontrak misi):
 *   ┌──────────────────────────────┐
 *   │ [icon] nama node    [status] │
 *   │        subtitle              │
 *   ├──────────────────────────────┤
 *   │ body: preview konfigurasi    │
 *   └──────────────────────────────┘
 *
 * Kenapa tidak memakai `BaseNode` dari React Flow UI: BaseNode membawa gaya
 * shadcn sendiri, sedangkan di sini SEMUA warna harus berasal dari token tema
 * kanvas (`--node-bg`, `--node-kind-color`, …) supaya 4 tema benar-benar
 * mengganti tampilan tanpa menyentuh komponen.
 *
 * MOBILE (kontrak misi: "pan default = satu jari geser canvas, BUKAN drag node"):
 * - Di perangkat sentuh node TIDAK langsung bisa digeser: `draggable` dimatikan
 *   di Canvas, jadi gesture satu jari = pan kanvas.
 * - Long-press 500 ms di kartu -> getar (`navigator.vibrate` bila tersedia)
 *   -> node DIARMING (drag mode) + menu konteks muncul.
 *
 * CATATAN JUJUR soal "long-press -> drag mode": arming terjadi di `pointerdown`
 * yang sudah berjalan, sedangkan React Flow mengambil alih gesture dari
 * `pointerdown`. Karena itu pengguna mengangkat jari lalu menggeser node pada
 * gesture BERIKUTNYA. Menyalakan drag di tengah gesture yang sama menuntut
 * penanganan pointer manual (bypass React Flow) — risiko regresi besar tanpa
 * diminta misi. Perilaku yang diuji: 500 ms -> haptic -> drag mode
 * (`data-armed="true"`) -> node bisa digeser.
 */
const LONG_PRESS_MS = 500;

function subtitleFor(kind: Kind, data: FlowNodeData): string {
  const cfg = data.config ?? {};
  if (kind === "trigger") return cfg.event ? String(cfg.event) : META.trigger.desc;
  if (kind === "mcp") return cfg.tool ? String(cfg.tool) : META.mcp.desc;
  return META.agent.desc;
}

/** Ringkasan konfigurasi yang tampil di bagian body kartu. */
export function previewFor(kind: Kind, data: FlowNodeData): string {
  const cfg = data.config ?? {};
  if (kind === "trigger") {
    return cfg.event ? String(cfg.event) : "Belum ada event — buka konfigurasi untuk mengisi.";
  }
  if (kind === "mcp") {
    const t = cfg.tool ? String(cfg.tool) : "pilih tool";
    return cfg.param ? `${t} · ${String(cfg.param).slice(0, 60)}` : `Tool: ${t}`;
  }
  const model = cfg.model === "deepseek-flash" ? "DeepSeek V4 Flash" : "Universal AI";
  const prompt = cfg.prompt ? String(cfg.prompt).replace(/\s+/g, " ").slice(0, 90) : "prompt belum diisi";
  return `${model} · ${prompt}`;
}

const STATUS_LABEL: Record<NodeStatus, string> = {
  initial: "Siap",
  loading: "Berjalan",
  success: "Berhasil",
  error: "Gagal",
};

export function CanvasNode({
  id,
  data,
  selected,
}: {
  id: string;
  data: FlowNodeData;
  selected?: boolean;
}) {
  const kind: Kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;
  const status: NodeStatus = (data?.status as NodeStatus) ?? "initial";

  const removeNode = useCanvasStore((s) => s.removeNode);
  const duplicateNode = useCanvasStore((s) => s.duplicateNode);
  const armNodeDrag = useCanvasStore((s) => s.armNodeDrag);
  const armed = useCanvasStore((s) => s.armedNodeId === id);

  const timer = useRef<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  // Menu konteks harus bisa ditutup tanpa memilih aksi: klik/tap di luar node
  // atau Escape. Tanpa ini menu menggantung di atas kanvas dan menghalangi
  // node lain (ditemukan saat menjalankan skrip bukti mobile).
  useEffect(() => {
    if (!menuOpen) return;
    function onDown(e: PointerEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  function clearTimer() {
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }

  function onPointerDown(e: React.PointerEvent) {
    if (e.pointerType !== "touch") return;
    clearTimer();
    timer.current = window.setTimeout(() => {
      // Haptic (opsional; tidak semua perangkat/browser mendukung).
      try {
        navigator.vibrate?.(20);
      } catch {
        /* abaikan */
      }
      armNodeDrag(id);
      setMenuOpen(true);
    }, LONG_PRESS_MS);
  }

  const badge = (
    <span className="flex items-center gap-1.5" title={STATUS_LABEL[status]}>
      <span
        className="k-status-dot"
        data-state={status}
        data-pulse={status === "loading" ? "true" : "false"}
        aria-hidden="true"
      />
      <span className="k-node__badge" style={{ color: "var(--canvas-text-secondary)" }}>
        {STATUS_LABEL[status]}
      </span>
    </span>
  );

  const card = (
    <div
      ref={rootRef}
      data-testid="node-card"
      data-kind={kind}
      data-status={status}
      data-armed={armed ? "true" : "false"}
      onPointerDown={onPointerDown}
      onPointerUp={clearTimer}
      onPointerLeave={clearTimer}
      onPointerCancel={clearTimer}
      className={
        "k-node relative" +
        (selected ? " k-node--selected" : "") +
        (status === "loading" ? " k-node--executing" : "") +
        (armed ? " k-node--armed" : "")
      }
      style={{ ["--node-kind-color" as string]: `var(--node-${kind === "agent" ? "action" : kind}-color)` }}
    >
      <NodeToolbar position={Position.Bottom}>
        <div className="flex gap-1">
          <button
            aria-label="Duplikat node"
            onClick={() => duplicateNode(id)}
            className="flex h-7 w-7 items-center justify-center rounded-md border bg-[color:var(--canvas-panel-bg)]"
            style={{ borderColor: "var(--node-border)", color: "var(--canvas-text-primary)" }}
          >
            <Copy size={14} strokeWidth={1.5} />
          </button>
          <button
            aria-label="Hapus node"
            onClick={() => removeNode(id)}
            className="flex h-7 w-7 items-center justify-center rounded-md border bg-transparent"
            style={{ borderColor: "var(--node-error-glow)", color: "var(--node-error-glow)" }}
          >
            <Trash2 size={14} strokeWidth={1.5} />
          </button>
        </div>
      </NodeToolbar>

      {kind !== "trigger" && <Handle type="target" position={Position.Left} className="k-handle k-handle--in" />}

      <div className="k-node__header">
        <span className="k-node__icon" aria-hidden="true">
          <Icon size={15} strokeWidth={1.75} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="k-node__title">{data?.label || meta.label}</span>
          <span className="k-node__subtitle">{subtitleFor(kind, data)}</span>
        </span>
        {badge}
      </div>

      <div className="k-node__body">
        <span className="k-node__preview">{previewFor(kind, data)}</span>
      </div>

      {menuOpen && (
        <div
          role="menu"
          data-testid="node-context-menu"
          className="absolute left-0 top-full z-50 mt-2 w-44 overflow-hidden rounded-xl border p-1 text-[12px] shadow-lg"
          style={{ background: "var(--canvas-panel-bg)", borderColor: "var(--node-border)" }}
        >
          <button
            role="menuitem"
            onClick={() => { duplicateNode(id); setMenuOpen(false); }}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left"
          >
            <Copy size={13} strokeWidth={1.5} /> Duplikat node
          </button>
          <button
            role="menuitem"
            onClick={() => { removeNode(id); setMenuOpen(false); }}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left"
            style={{ color: "var(--node-error-glow)" }}
          >
            <Trash2 size={13} strokeWidth={1.5} /> Hapus node
          </button>
        </div>
      )}

      <Handle type="source" position={Position.Right} className="k-handle k-handle--out" />
    </div>
  );

  return (
    <NodeStatusIndicator status={status} variant={status === "error" ? "overlay" : "border"}>
      {card}
    </NodeStatusIndicator>
  );
}

