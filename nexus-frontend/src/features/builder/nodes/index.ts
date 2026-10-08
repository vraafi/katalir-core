import { CanvasNode } from "./CanvasNode";

/**
 * Registry `nodeTypes` React Flow.
 *
 * Semua kind memakai komponen yang SAMA (`CanvasNode`) karena perbedaan
 * trigger/agent/mcp/code hanya pada warna + isi kartu (ditentukan oleh
 * `data.kind`). Kalau nanti tiap kind butuh layout berbeda, pecah di sini —
 * penggantinya cukup komponen baru tanpa mengubah store/Canvas.
 *
 * PENTING: kunci di sini WAJIB ada untuk SETIAP kunci `META` (types.ts).
 * React Flow TIDAK melempar error kalau `nodeTypes[kind]` tidak ada — ia
 * diam-diam memakai node bawaan (kotak abu-abu tanpa `data-testid="node-card"`).
 * Bug nyata: node `code` ditambahkan ke store dengan benar tetapi tampil sebagai
 * kotak bawaan karena kunci ini belum ada; satu-satunya gejala adalah tes UI
 * "node tidak muncul" sementara store sudah benar. Dijaga oleh
 * `tests/builder-code-node.spec.ts` (E2) dan `tests/node-types.unit.spec.ts`.
 */
export const NODE_TYPES = {
  trigger: CanvasNode,
  cron_trigger: CanvasNode,
  agent: CanvasNode,
  mcp: CanvasNode,
  code: CanvasNode,
};

export { CanvasNode, previewFor } from "./CanvasNode";
