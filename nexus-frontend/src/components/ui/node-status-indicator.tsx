/**
 * NodeStatusIndicator — SALINAN RESMI dari registry React Flow UI
 * `npx shadcn@latest add https://ui.reactflow.dev/node-status-indicator`
 * (diambil langsung dari JSON registry `https://ui.reactflow.dev/node-status-indicator`,
 * MIT — webkid GmbH).
 *
 * KENAPA DI-VENDOR, BUKAN DIJALANKAN LEWAT CLI:
 * `npx shadcn@latest add <url>` menuntut `components.json` + struktur shadcn
 * standar. Repo ini TIDAK memakainya: komponen UI ditulis tangan dan helper
 * kelasnya `@/lib/cn` (bukan `@/lib/utils`). Menjalankan CLI-nya akan menulis
 * `components.json`, `lib/utils.ts`, dan menaruh file di jalur yang tidak
 * dikenali proyek ini. Jadi sumber RESMI yang sama diambil dari registry dan
 * ditempelkan apa adanya di sini.
 *
 * ADAPTASI (minimal, semua disengaja dan terlihat):
 *   1. `import { cn } from "@/lib/utils"` -> `"@/lib/cn"` (konvensi repo).
 *   2. Warna status keras (blue-700 / emerald-600 / red-400) -> token tema
 *      kanvas (`--node-pulse-color`, `--node-success-glow`, `--node-error-glow`)
 *      supaya NODE_STATUS ikut 4 tema. Struktur/perilaku komponen TIDAK diubah:
 *      status loading tetap memakai conic-gradient ring yang berputar.
 *   3. `data-testid="node-status-<status>"` ditambahkan pada elemen pembungkus
 *      supaya status bisa diukur programatik (bukti FASE 3), bukan ditebak
 *      dari screenshot.
 */
import { type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/cn";

export type NodeStatus = "loading" | "success" | "error" | "initial";

export type NodeStatusVariant = "overlay" | "border";

export type NodeStatusIndicatorProps = {
  status?: NodeStatus;
  variant?: NodeStatusVariant;
  children: ReactNode;
};

/** Warna status dari token tema (lihat globals.css `[data-canvas-theme]`). */
const PULSE = "var(--node-pulse-color, #6366f1)";
const SUCCESS = "var(--node-success-glow, #26bd73)";
const ERROR = "var(--node-error-glow, #f55c5c)";

export const SpinnerLoadingIndicator = ({ children }: { children: ReactNode }) => {
  return (
    <div className="relative" data-testid="node-status-loading">
      <StatusBorder className="border-[color:var(--node-pulse-color,#6366f1)]/40">{children}</StatusBorder>

      <div className="absolute inset-0 z-50 rounded-[14px] bg-black/45 backdrop-blur-[2px]" />
      <div className="absolute inset-0 z-50">
        <span
          className="absolute left-[calc(50%-1.25rem)] top-[calc(50%-1.25rem)] inline-block h-10 w-10 animate-ping rounded-full"
          style={{ backgroundColor: `color-mix(in srgb, ${PULSE} 25%, transparent)` }}
        />
        <LoaderCircle
          className="absolute left-[calc(50%-0.75rem)] top-[calc(50%-0.75rem)] size-6 animate-spin"
          style={{ color: PULSE }}
        />
      </div>
    </div>
  );
};

export const BorderLoadingIndicator = ({ children }: { children: ReactNode }) => {
  return (
    <div data-testid="node-status-loading" className="relative">
      <div className="absolute -left-px -top-px h-[calc(100%+2px)] w-[calc(100%+2px)]">
        <style>
          {`
        @keyframes k-node-status-spin {
          from { transform: translate(-50%, -50%) rotate(0deg); }
          to { transform: translate(-50%, -50%) rotate(360deg); }
        }
        .k-node-status-spinner {
          animation: k-node-status-spin 2s linear infinite;
          position: absolute;
          left: 50%;
          top: 50%;
          width: 140%;
          aspect-ratio: 1;
          transform-origin: center;
        }
        @media (prefers-reduced-motion: reduce) {
          .k-node-status-spinner { animation: none; }
        }
      `}
        </style>
        <div className="absolute inset-0 overflow-hidden rounded-[14px]">
          <div
            className="k-node-status-spinner rounded-full"
            style={{
              background: `conic-gradient(from 0deg at 50% 50%, ${PULSE} 0deg, rgba(0,0,0,0) 360deg)`,
            }}
          />
        </div>
      </div>
      {children}
    </div>
  );
};

const StatusBorder = ({ children, className }: { children: ReactNode; className?: string }) => {
  return (
    <>
      <div
        className={cn(
          "pointer-events-none absolute -left-px -top-px h-[calc(100%+2px)] w-[calc(100%+2px)] rounded-[14px] border-2",
          className,
        )}
      />
      {children}
    </>
  );
};

export const NodeStatusIndicator = ({ status, variant = "border", children }: NodeStatusIndicatorProps) => {
  switch (status) {
    case "loading":
      switch (variant) {
        case "overlay":
          return <SpinnerLoadingIndicator>{children}</SpinnerLoadingIndicator>;
        case "border":
          return <BorderLoadingIndicator>{children}</BorderLoadingIndicator>;
        default:
          return <>{children}</>;
      }
    case "success":
      return (
        <div className="relative" data-testid="node-status-success">
          <StatusBorder className="border-[color:var(--node-success-glow,#26bd73)]">{children}</StatusBorder>
        </div>
      );
    case "error":
      return (
        <div className="relative" data-testid="node-status-error">
          <StatusBorder className="border-[color:var(--node-error-glow,#f55c5c)]">{children}</StatusBorder>
        </div>
      );
    default:
      return <>{children}</>;
  }
};
