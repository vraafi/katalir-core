import { FlowEdge } from "./FlowEdge";

/**
 * Registry `edgeTypes` React Flow. Satu tipe (`flow`) untuk semua koneksi:
 * perbedaan "diam" vs "mengalir" adalah STATE (`edge.animated`), bukan tipe.
 */
export const EDGE_TYPES = { flow: FlowEdge };

export { FlowEdge };
