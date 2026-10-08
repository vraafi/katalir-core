"use client";

import {
  Activity,
  Calendar,
  Mail,
  MessageCircle,
  Rss,
  Send,
  Sparkles,
  Table,
  Webhook,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";
import type { Template } from "./types";

/**
 * Peta ikon dari `icon` string backend -> komponen lucide.
 * Fallback `Workflow` bila backend menambah ikon yang belum dikenal: lebih baik
 * menampilkan ikon generik daripada kotak kosong.
 */
const ICONS: Record<string, LucideIcon> = {
  mail: Mail,
  rss: Rss,
  send: Send,
  webhook: Webhook,
  sparkles: Sparkles,
  table: Table,
  calendar: Calendar,
  activity: Activity,
  "message-circle": MessageCircle,
};

/** Label kategori ramah-pengguna (Indonesia). */
const CATEGORY_LABEL: Record<string, string> = {
  notification: "Notifikasi",
  marketing: "Marketing",
  data: "Data",
  ops: "Operasional",
  ai: "AI",
  integration: "Integrasi",
};

/** Warna chip per kategori — dipakai konsisten di kartu & preview. */
const CATEGORY_STYLE: Record<string, string> = {
  notification: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  marketing: "bg-pink-500/15 text-pink-600 dark:text-pink-400",
  data: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  ops: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  ai: "bg-violet-500/15 text-violet-600 dark:text-violet-400",
  integration: "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400",
};

export function categoryLabel(cat: string): string {
  return CATEGORY_LABEL[cat] ?? cat;
}

export function categoryStyle(cat: string): string {
  return CATEGORY_STYLE[cat] ?? "bg-bg-subtle text-fg-muted";
}

/**
 * Kartu satu template di galeri.
 *
 * Kartu ini murni presentasional — semua aksi (preview, use, delete) diangkat
 * lewat callback supaya induk (`TemplateGallery`) yang mengendalikan modal dan
 * state loading, dan kartu tetap mudah diuji.
 */
export function TemplateCard({
  template,
  onPreview,
  onUse,
  onDelete,
  using,
}: {
  template: Template;
  onPreview: (t: Template) => void;
  onUse: (t: Template) => void;
  onDelete?: (t: Template) => void;
  using?: boolean;
}) {
  const Icon = ICONS[template.icon ?? ""] ?? Workflow;
  const isBuiltin = template.source === "builtin";

  return (
    <div
      className={cn(
        "group flex flex-col rounded-md border border-border/60 bg-surface p-5",
        "shadow-xs transition-shadow duration-200 hover:shadow-sm",
      )}
      data-testid="template-card"
      data-template-id={template.id}
      data-template-source={template.source}
      data-template-category={template.category}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-bg-subtle text-fg">
          <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-subhead font-semibold text-fg" title={template.name}>
            {template.name}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-caption font-medium",
                categoryStyle(template.category),
              )}
              data-testid="template-category"
            >
              {categoryLabel(template.category)}
            </span>
            {!isBuiltin && (
              <span
                className="rounded-full bg-bg-subtle px-2 py-0.5 text-caption font-medium text-fg-muted"
                data-testid="template-badge-custom"
              >
                Kustom
              </span>
            )}
          </div>
        </div>
      </div>

      <p className="mt-3 line-clamp-2 flex-1 text-footnote text-fg-muted">
        {template.description || "Tanpa deskripsi."}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-caption text-fg-muted">
        <span data-testid="template-node-count">
          {template.node_count} node
        </span>
        {template.tags?.length ? (
          <>
            <span aria-hidden="true">·</span>
            <span className="truncate">{template.tags.join(", ")}</span>
          </>
        ) : null}
      </div>

      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onPreview(template)}
          className="flex h-8 flex-1 items-center justify-center rounded-md border border-border bg-transparent px-3 text-footnote font-medium text-fg transition hover:bg-bg-subtle"
          data-testid="template-preview-btn"
        >
          Pratinjau
        </button>
        <button
          type="button"
          onClick={() => onUse(template)}
          disabled={using}
          className={cn(
            "flex h-8 flex-1 items-center justify-center rounded-md px-3 text-footnote font-medium transition",
            "bg-fg text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50",
          )}
          data-testid="template-use-btn"
        >
          {using ? "Membuat…" : "Pakai"}
        </button>
        {!isBuiltin && onDelete && (
          <button
            type="button"
            onClick={() => onDelete(template)}
            aria-label={`Hapus template ${template.name}`}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-fg-muted transition hover:bg-red-500/10 hover:text-red-600"
            data-testid="template-delete-btn"
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
