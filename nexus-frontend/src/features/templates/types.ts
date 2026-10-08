/**
 * Tipe untuk Template Gallery (Fitur #10 Workflow Templates).
 *
 * Bentuk ini mengikuti apa yang benar-benar dikembalikan backend
 * `GET /templates` (lihat `workflow_templates.py::_row_to_template` +
 * `list_templates`). Sengaja TIDAK memakai tipe kanvas (`FlowNode`) karena
 * `flow_data` di sini adalah JSON mentah dari server — konversi ke bentuk
 * React Flow baru dilakukan saat workflow benar-benar dibuka di /builder.
 */

/** Kategori template. Harus sinkron dengan `workflow_templates.CATEGORIES`. */
export const TEMPLATE_CATEGORIES = [
  "notification",
  "marketing",
  "data",
  "ops",
  "ai",
  "integration",
] as const;

export type TemplateCategory = (typeof TEMPLATE_CATEGORIES)[number];

/** Asal template: `builtin` (kode, tidak bisa dihapus) atau `custom` (milik user). */
export type TemplateSource = "builtin" | "custom";

/** Satu node di dalam `flow_data` — bentuk longgar karena JSON dari server. */
export interface FlowDataNode {
  id: string;
  type?: string;
  position?: { x: number; y: number };
  data?: { kind?: string; label?: string; config?: Record<string, unknown> };
}

/** Satu edge di dalam `flow_data`. */
export interface FlowDataEdge {
  id?: string;
  source: string;
  target: string;
}

/** Graf mentah template. */
export interface FlowData {
  nodes: FlowDataNode[];
  edges?: FlowDataEdge[];
}

/** Satu template seperti yang dikirim backend. */
export interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  icon?: string;
  source: TemplateSource;
  node_count: number;
  flow_data: FlowData;
  created_at?: string;
}

/** Respons `GET /templates`. */
export interface TemplateListResponse {
  status: string;
  count: number;
  templates: Template[];
}

/** Respons `GET /templates/info`. */
export interface TemplateInfoResponse {
  status: string;
  builtin_count: number;
  categories: string[];
  builtin_ids: string[];
  max_nodes: number;
  max_edges: number;
}

/** Respons `POST /templates/{id}/use`. */
export interface TemplateUseResponse {
  status: string;
  template: Pick<Template, "id" | "name" | "category" | "source" | "node_count">;
  workflow: { id: string; name: string; description?: string } & Record<string, unknown>;
}
