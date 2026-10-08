"use client";

import { ArrowDown } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/cn";
import { categoryLabel, categoryStyle } from "./TemplateCard";
import type { FlowDataNode, Template } from "./types";

/** Warna titik node per `kind` — sinkron dengan konvensi kanvas builder. */
const KIND_STYLE: Record<string, string> = {
  trigger: "bg-amber-500",
  agent: "bg-violet-500",
  mcp: "bg-cyan-500",
};

const KIND_LABEL: Record<string, string> = {
  trigger: "Trigger",
  agent: "Agent",
  mcp: "MCP Tool",
};

/**
 * Urutkan node mengikuti alur graf (topological sederhana).
 *
 * Template nyata adalah rantai linear (trigger → … → tool), jadi cukup menelusuri
 * dari node tanpa predecessor. Bila graf bercabang / ada siklus, sisa node
 * ditambahkan apa adanya agar tidak ada yang hilang dari pratinjau.
 */
function orderNodes(tpl: Template): FlowDataNode[] {
  const nodes = tpl.flow_data?.nodes ?? [];
  const edges = tpl.flow_data?.edges ?? [];
  if (nodes.length <= 1 || edges.length === 0) return nodes;

  const indeg = new Map<string, number>();
  const next = new Map<string, string>();
  for (const n of nodes) indeg.set(n.id, 0);
  for (const e of edges) {
    if (indeg.has(e.target)) indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    if (!next.has(e.source)) next.set(e.source, e.target);
  }
  const start = nodes.find((n) => (indeg.get(n.id) ?? 0) === 0) ?? nodes[0];
  const ordered: FlowDataNode[] = [];
  const seen = new Set<string>();
  let cur: FlowDataNode | undefined = start;
  while (cur && !seen.has(cur.id)) {
    ordered.push(cur);
    seen.add(cur.id);
    const nid: string | undefined = next.get(cur.id);
    cur = nid ? nodes.find((n) => n.id === nid) : undefined;
  }
  for (const n of nodes) if (!seen.has(n.id)) ordered.push(n);
  return ordered;
}

/**
 * Modal pratinjau template: metadata + rantai node yang akan dibuat.
 *
 * Menampilkan alur sebagai daftar vertikal (bukan kanvas React Flow penuh)
 * supaya modal tetap ringan dan tidak perlu memasang `ReactFlowProvider` di
 * halaman galeri. Tujuannya memberi gambaran struktur, bukan editor.
 */
export function TemplatePreview({
  template,
  open,
  onOpenChange,
  onUse,
}: {
  template: Template | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUse: (t: Template) => void;
}) {
  if (!template) return null;
  const nodes = orderNodes(template);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={template.name}
      description={template.description || "Tanpa deskripsi."}
      closeLabel="Tutup pratinjau"
      className="max-w-lg"
    >
      <div data-testid="template-preview">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-caption font-medium",
              categoryStyle(template.category),
            )}
          >
            {categoryLabel(template.category)}
          </span>
          <span className="rounded-full bg-bg-subtle px-2 py-0.5 text-caption font-medium text-fg-muted">
            {template.source === "builtin" ? "Bawaan" : "Kustom"}
          </span>
          <span className="text-caption text-fg-muted" data-testid="preview-node-count">
            {nodes.length} node
          </span>
        </div>

        {template.tags?.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {template.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-md bg-bg-subtle px-2 py-0.5 text-caption text-fg-muted"
              >
                {tag}
              </span>
            ))}
          </div>
        ) : null}

        <div className="mt-4" data-testid="preview-flow">
          <h3 className="mb-2 text-footnote font-semibold text-fg-muted">Alur</h3>
          <ol className="flex flex-col items-stretch gap-1">
            {nodes.map((node, i) => {
              const kind = node.data?.kind ?? node.type ?? "mcp";
              return (
                <li key={node.id} className="flex flex-col items-stretch">
                  {i > 0 && (
                    <div className="flex justify-center py-0.5 text-fg-muted" aria-hidden="true">
                      <ArrowDown className="h-3.5 w-3.5" strokeWidth={1.75} />
                    </div>
                  )}
                  <div
                    className="flex items-center gap-2.5 rounded-md border border-border/60 bg-bg-subtle/50 px-3 py-2"
                    data-testid="preview-node"
                  >
                    <span
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        KIND_STYLE[kind] ?? "bg-fg-muted",
                      )}
                      aria-hidden="true"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-footnote font-medium text-fg">
                        {node.data?.label ?? node.id}
                      </p>
                      <p className="text-caption text-fg-muted">
                        {KIND_LABEL[kind] ?? kind}
                      </p>
                    </div>
                  </div>
                </li>
              );
            })}
            {nodes.length === 0 && (
              <li className="rounded-md border border-dashed border-border px-3 py-6 text-center text-footnote text-fg-muted">
                Template ini belum memiliki node.
              </li>
            )}
          </ol>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="flex h-9 items-center rounded-md border border-border px-4 text-footnote font-medium text-fg transition hover:bg-bg-subtle"
            data-testid="preview-close-btn"
          >
            Tutup
          </button>
          <button
            type="button"
            onClick={() => onUse(template)}
            className="flex h-9 items-center rounded-md bg-fg px-4 text-footnote font-medium text-bg transition hover:opacity-90"
            data-testid="preview-use-btn"
          >
            Pakai template ini
          </button>
        </div>
      </div>
    </Dialog>
  );
}
