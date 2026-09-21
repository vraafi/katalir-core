import type { Edge, Node } from "@xyflow/react";
import { type FlowNode, type Kind } from "./types";

/**
 * Identitas node/edge untuk kanvas Builder (FASE stabilisasi).
 *
 * Kenapa modul terpisah: bug "node tidak muncul setelah ditambahkan" berasal
 * dari generator id yang tidak pernah sadar id mana yang SUDAH dipakai.
 * Store dulu menyimpan counter `seq` yang mulai dari 100 dan TIDAK disinkronkan
 * ketika workflow tersimpan di-restore (`setNodes`), sehingga menambah node
 * menghasilkan id `agent-100` yang sudah ada -> React melihat dua anak dengan
 * key sama, membuang satu, dan node baru tampak "hilang".
 *
 * Aturan di sini: satu-satunya cara membuat id node adalah `nextNodeId()` yang
 * menerima daftar id terpakai, dan setiap jalur masuk kanvas (restore workflow,
 * draf AI, set nodes langsung) melewati `dedupeGraph()`.
 */

const ID_BASE = 100;

// Monoton (naik terus, tidak pernah di-reset oleh pergantian isi kanvas).
// Dipakai sebagai titik awal pencarian, BUKAN sebagai jaminan keunikan --
// keunikan selalu diverifikasi terhadap himpunan id yang benar-benar ada.
let counter = ID_BASE;

/**
 * Kind dari sebuah node.
 *
 * Urutan prioritas (paling kuat dulu):
 *   1. `data.kind`  -- sinyal eksplisit dari pembuat node (kanvas / draf AI).
 *   2. `type`       -- yang dipakai React Flow untuk memilih komponen node,
 *                      jadi selalu ada pada node yang valid.
 *   3. prefix id    -- heuristik terlemah; id draf AI bisa berupa "n1"/"m2"
 *                      sehingga prefix tidak selalu bermakna.
 */
export function kindOf(node: Partial<FlowNode> | null | undefined): Kind {
  const fromData = (node?.data as { kind?: string } | undefined)?.kind;
  if (fromData === "trigger" || fromData === "agent" || fromData === "mcp") return fromData;
  const t = String(node?.type ?? "");
  if (t === "trigger" || t === "agent" || t === "mcp") return t as Kind;
  const prefix = typeof node?.id === "string" ? node.id.split("-")[0] : "";
  if (prefix === "trigger" || prefix === "agent" || prefix === "mcp") return prefix as Kind;
  return "agent";
}

/**
 * Id node yang dijamin belum dipakai `taken`.
 * `taken` WAJIB berisi seluruh id yang sudah ada di kanvas (termasuk hasil
 * restore dan draf AI) supaya tidak ada tabrakan di state apa pun.
 */
export function nextNodeId(kind: Kind | string, taken?: Iterable<string>): string {
  const used = taken instanceof Set ? taken : new Set(taken ?? []);
  let id: string;
  do {
    counter += 1;
    id = `${kind}-${counter}`;
  } while (used.has(id));
  return id;
}

export type GraphInput = { nodes?: FlowNode[] | null; edges?: Edge[] | null };

export type DedupeResult = {
  nodes: FlowNode[];
  edges: Edge[];
  /** Jumlah node yang id-nya diganti karena duplikat/kosong. */
  renamedNodes: number;
  /** Jumlah edge yang dibuang (id ganda atau menunjuk node yang tidak ada). */
  droppedEdges: number;
};

/**
 * Normalisasi graf dari sumber yang tidak tepercaya (workflow tersimpan, draf
 * AI, localStorage lama).
 *
 * - id node kosong/ganda -> node DIPERTAHANKAN, id-nya diganti (bukan dibuang).
 *   Kemunculan PERTAMA tetap memakai id aslinya, sehingga edge lama yang
 *   menunjuk id itu tidak perlu diubah.
 * - edge dengan id ganda -> dibuang (React Flow butuh id unik).
 * - edge yang menunjuk node tidak ada -> dibuang, karena React Flow mencetak
 *   error dan edge-nya tidak akan pernah terlihat.
 * - `type` node dilengkapi dari `kind` bila kosong, supaya React Flow tidak
 *   jatuh ke node default.
 *
 * Objek input tidak diubah (dikembalikan sebagai salinan bila perlu diubah).
 */
export function dedupeGraph({ nodes, edges }: GraphInput): DedupeResult {
  const inputNodes = Array.isArray(nodes) ? nodes.filter(Boolean) : [];
  const inputEdges = Array.isArray(edges) ? edges.filter(Boolean) : [];

  const allIds = new Set<string>();
  for (const n of inputNodes) if (n && typeof n.id === "string" && n.id) allIds.add(n.id);

  const seenNode = new Set<string>();
  const outNodes: FlowNode[] = [];
  let renamedNodes = 0;

  for (const n of inputNodes) {
    const originalId = typeof n.id === "string" ? n.id : "";
    const kind = kindOf(n);
    let id = originalId;
    if (!id || seenNode.has(id)) {
      id = nextNodeId(kind, new Set([...allIds, ...seenNode]));
      renamedNodes += 1;
    }
    seenNode.add(id);
    const type = n.type ?? kind;
    outNodes.push(id === n.id && type === n.type ? n : { ...n, id, type });
  }

  const seenEdge = new Set<string>();
  const outEdges: Edge[] = [];
  let droppedEdges = 0;
  for (const e of inputEdges) {
    const id = typeof e.id === "string" ? e.id : "";
    const src = typeof e.source === "string" ? e.source : "";
    const dst = typeof e.target === "string" ? e.target : "";
    if (!id || seenEdge.has(id)) {
      droppedEdges += 1;
      continue;
    }
    if (!seenNode.has(src) || !seenNode.has(dst)) {
      droppedEdges += 1;
      continue;
    }
    seenEdge.add(id);
    outEdges.push(e);
  }

  return { nodes: outNodes, edges: outEdges, renamedNodes, droppedEdges };
}
