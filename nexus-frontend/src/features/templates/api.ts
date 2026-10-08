/**
 * Klien API untuk Template Gallery.
 *
 * Semua fungsi memakai `apiFetch` (src/lib/api.ts) sehingga Authorization
 * Bearer JWT disuntikkan otomatis dari sesi Supabase — endpoint template
 * owner-scoped, jadi tanpa token akan 401.
 */
import { apiFetch } from "@/lib/api";
import type {
  Template,
  TemplateInfoResponse,
  TemplateListResponse,
  TemplateUseResponse,
} from "./types";

/** Error yang membawa status HTTP + pesan `detail` dari FastAPI. */
export class TemplateApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "TemplateApiError";
    this.status = status;
  }
}

/** Baca `detail` dari body error FastAPI, fallback ke pesan generik. */
async function readError(res: Response, fallback: string): Promise<TemplateApiError> {
  let detail = "";
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") detail = body.detail;
    else if (body && typeof body.message === "string") detail = body.message;
  } catch {
    /* body bukan JSON — pakai fallback */
  }
  return new TemplateApiError(detail || `${fallback} (${res.status})`, res.status);
}

/** GET /templates — daftar bawaan + kustom milik user, dengan filter opsional. */
export async function listTemplates(opts?: {
  category?: string;
  q?: string;
}): Promise<Template[]> {
  const params = new URLSearchParams();
  if (opts?.category) params.set("category", opts.category);
  if (opts?.q) params.set("q", opts.q);
  const qs = params.toString();
  const res = await apiFetch(`/templates${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw await readError(res, "Gagal memuat template");
  const data = (await res.json()) as TemplateListResponse;
  return data.templates ?? [];
}

/** GET /templates/info — metadata (jumlah bawaan, kategori, batas). */
export async function getTemplateInfo(): Promise<TemplateInfoResponse> {
  const res = await apiFetch("/templates/info");
  if (!res.ok) throw await readError(res, "Gagal memuat info template");
  return (await res.json()) as TemplateInfoResponse;
}

/** GET /templates/{id} — detail satu template. */
export async function getTemplate(id: string): Promise<Template> {
  const res = await apiFetch(`/templates/${encodeURIComponent(id)}`);
  if (!res.ok) throw await readError(res, "Template tidak ditemukan");
  const data = (await res.json()) as { template: Template };
  return data.template;
}

/** POST /templates/{id}/use — buat workflow NYATA dari template. */
export async function useTemplate(
  id: string,
  opts?: { name?: string; description?: string },
): Promise<TemplateUseResponse> {
  const res = await apiFetch(`/templates/${encodeURIComponent(id)}/use`, {
    method: "POST",
    body: JSON.stringify({ name: opts?.name, description: opts?.description }),
  });
  if (!res.ok) throw await readError(res, "Gagal membuat workflow dari template");
  return (await res.json()) as TemplateUseResponse;
}

/** POST /templates — simpan template kustom. */
export async function createTemplate(input: {
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  workflow_id?: string;
}): Promise<Template> {
  const res = await apiFetch("/templates", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (!res.ok) throw await readError(res, "Gagal menyimpan template");
  const data = (await res.json()) as { template: Template };
  return data.template;
}

/** DELETE /templates/{id} — hapus template kustom milik user. */
export async function deleteTemplate(id: string): Promise<void> {
  const res = await apiFetch(`/templates/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await readError(res, "Gagal menghapus template");
}
