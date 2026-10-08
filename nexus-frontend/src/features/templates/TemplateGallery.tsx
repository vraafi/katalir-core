"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, LayoutTemplate, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { templateKeys } from "@/lib/query-keys";
import { SearchBar } from "@/components/search-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { TemplateCard, categoryLabel } from "./TemplateCard";
import { TemplatePreview } from "./TemplatePreview";
import {
  deleteTemplate,
  listTemplates,
  useTemplate,
  TemplateApiError,
} from "./api";
import { TEMPLATE_CATEGORIES, type Template } from "./types";

/** Notifikasi ringan (inline, bukan toast library) untuk hasil aksi. */
type Notice = { kind: "ok" | "err"; text: string; workflowId?: string };

/**
 * Galeri template: kisi kartu + pencarian + filter kategori + pratinjau.
 *
 * Sumber data = backend `GET /templates` (bawaan + kustom milik user). Filter
 * kategori & pencarian dikirim ke server (bukan difilter di klien) supaya
 * template kustom yang jumlahnya bisa banyak tetap tercakup dan hasilnya
 * konsisten dengan apa yang dipakai endpoint `use`.
 */
export function TemplateGallery() {
  const qc = useQueryClient();
  const [category, setCategory] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const [preview, setPreview] = useState<Template | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const listQuery = useQuery({
    queryKey: templateKeys.list(category, query),
    queryFn: () => listTemplates({ category: category || undefined, q: query || undefined }),
    staleTime: 30_000,
  });

  const useMut = useMutation({
    mutationFn: (t: Template) => useTemplate(t.id),
    onSuccess: (res) => {
      setNotice({
        kind: "ok",
        text: `Workflow "${res.workflow?.name ?? "baru"}" dibuat dari template.`,
        workflowId: res.workflow?.id,
      });
      setPreview(null);
      // Daftar tidak berubah (workflow baru, bukan template), tapi info bisa
      // berubah bila template kustom ikut ter-instantiate — aman di-invalidate.
      qc.invalidateQueries({ queryKey: templateKeys.all });
    },
    onError: (err: unknown) => {
      const msg = err instanceof TemplateApiError ? err.message : "Gagal membuat workflow.";
      setNotice({ kind: "err", text: msg });
    },
  });

  const delMut = useMutation({
    mutationFn: (t: Template) => deleteTemplate(t.id),
    onSuccess: () => {
      setNotice({ kind: "ok", text: "Template kustom dihapus." });
      qc.invalidateQueries({ queryKey: templateKeys.all });
    },
    onError: (err: unknown) => {
      const msg = err instanceof TemplateApiError ? err.message : "Gagal menghapus template.";
      setNotice({ kind: "err", text: msg });
    },
  });

  const templates = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  const usingId = useMut.isPending ? useMut.variables?.id : undefined;

  // Kategori yang benar-benar muncul di data + kategori standar, agar chip
  // "Semua" tidak menampilkan kategori kosong.
  const categories = useMemo(() => {
    const present = new Set(templates.map((t) => t.category));
    const ordered = TEMPLATE_CATEGORIES.filter((c) => present.has(c));
    return ordered.length ? ordered : [...TEMPLATE_CATEGORIES];
  }, [templates]);

  return (
    <div data-testid="template-gallery">
      {/* Toolbar: pencarian + filter kategori */}
      <div className="flex flex-col gap-3">
        <SearchBar
          onSearch={(q) => setQuery(q)}
          minChars={1}
          placeholder="Cari template…"
          label="Cari template"
        />

        <div className="flex flex-wrap items-center gap-1.5" data-testid="template-filters">
          <button
            type="button"
            onClick={() => setCategory("")}
            aria-pressed={category === ""}
            className={cn(
              "rounded-full px-3 py-1 text-footnote font-medium transition",
              category === ""
                ? "bg-fg text-bg"
                : "bg-bg-subtle text-fg-muted hover:text-fg",
            )}
            data-testid="filter-all"
          >
            Semua
          </button>
          {categories.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCategory(c)}
              aria-pressed={category === c}
              className={cn(
                "rounded-full px-3 py-1 text-footnote font-medium transition",
                category === c
                  ? "bg-fg text-bg"
                  : "bg-bg-subtle text-fg-muted hover:text-fg",
              )}
              data-testid={`filter-${c}`}
            >
              {categoryLabel(c)}
            </button>
          ))}
          {listQuery.isFetching && (
            <RefreshCw
              className="ml-1 h-3.5 w-3.5 animate-spin text-fg-muted"
              aria-label="Memuat"
            />
          )}
        </div>
      </div>

      {/* Notifikasi hasil aksi */}
      {notice && (
        <div
          role="status"
          data-testid="template-notice"
          className={cn(
            "mt-4 flex items-start gap-2 rounded-md border px-3 py-2 text-footnote",
            notice.kind === "ok"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-400",
          )}
        >
          {notice.kind === "ok" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <span className="flex-1">
            {notice.text}{" "}
            {notice.workflowId && (
              <Link href="/builder" className="font-medium underline underline-offset-2">
                Buka Builder
              </Link>
            )}
          </span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Tutup notifikasi"
            className="opacity-70 transition hover:opacity-100"
          >
            ×
          </button>
        </div>
      )}

      {/* Konten */}
      <div className="mt-6">
        {listQuery.isLoading ? (
          <div
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
            data-testid="template-loading"
          >
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-48 w-full" />
            ))}
          </div>
        ) : listQuery.isError ? (
          <div
            className="flex flex-col items-center gap-3 rounded-md border border-red-500/30 bg-red-500/5 px-6 py-10 text-center"
            data-testid="template-error"
          >
            <AlertCircle className="h-6 w-6 text-red-600 dark:text-red-400" />
            <p className="text-footnote text-fg-muted">
              {listQuery.error instanceof TemplateApiError
                ? listQuery.error.message
                : "Gagal memuat template."}
            </p>
            <button
              type="button"
              onClick={() => listQuery.refetch()}
              className="rounded-md bg-fg px-4 py-2 text-footnote font-medium text-bg transition hover:opacity-90"
              data-testid="template-retry-btn"
            >
              Coba lagi
            </button>
          </div>
        ) : templates.length === 0 ? (
          <div
            className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-6 py-14 text-center"
            data-testid="template-empty"
          >
            <LayoutTemplate className="h-7 w-7 text-fg-muted" />
            <p className="text-subhead font-medium text-fg">Tidak ada template cocok</p>
            <p className="text-footnote text-fg-muted">
              Coba ubah kata kunci pencarian atau pilih kategori lain.
            </p>
          </div>
        ) : (
          <div
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
            data-testid="template-grid"
          >
            {templates.map((t) => (
              <TemplateCard
                key={t.id}
                template={t}
                using={usingId === t.id}
                onPreview={(tpl) => setPreview(tpl)}
                onUse={(tpl) => useMut.mutate(tpl)}
                onDelete={(tpl) => delMut.mutate(tpl)}
              />
            ))}
          </div>
        )}
      </div>

      <TemplatePreview
        template={preview}
        open={preview !== null}
        onOpenChange={(o) => !o && setPreview(null)}
        onUse={(t) => useMut.mutate(t)}
      />
    </div>
  );
}
