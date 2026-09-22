import { CanvasNode } from "./CanvasNode";

/**
 * Registry `nodeTypes` React Flow.
 *
 * Ketiga kind memakai komponen yang SAMA (`CanvasNode`) karena perbedaan
 * trigger/agent/mcp hanya pada warna + isi kartu (ditentukan oleh `data.kind`).
 * Kalau nanti tiap kind butuh layout berbeda, pecah di sini — penggantinya
 * cukup komponen baru tanpa mengubah store/Canvas.
 */
export const NODE_TYPES = {
  trigger: CanvasNode,
  agent: CanvasNode,
  mcp: CanvasNode,
};

export { CanvasNode, previewFor } from "./CanvasNode";
