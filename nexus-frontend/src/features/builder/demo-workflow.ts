import type { Edge } from "@xyflow/react";
import type { FlowNode } from "./types";

/**
 * Contoh workflow (FASE 3) — dipakai oleh:
 *   1. Empty state: tombol "Muat contoh workflow" supaya pengguna awam melihat
 *      alur yang BEKERJA, bukan kanvas kosong tanpa contoh.
 *   2. `?demo=1` pada /builder: mengisi kanvas dengan contoh ini, supaya
 *      screenshot/E2E bisa mengukur 4 state status node tanpa harus menjalankan
 *      eksekusi nyata (yang butuh kuota LLM).
 *
 * Empat status disengaja hadir sekaligus (`initial`, `loading`, `success`,
 * `error`) karena itulah kombinasi yang WAJIB dibuktikan secara visual.
 *
 * Posisi memakai titik TENGAH node (Canvas `nodeOrigin={[0.5, 0.5]}`).
 * Jarak antar-ranking = NODE_H + RANK_SEP = 104 + 100 = 204 px agar contoh ini
 * sudah "rapi" walau user belum menekan Auto Layout.
 *
 * KOORDINAT contoh ditata agar TIDAK berada di bawah toolbar kanvas (overlay
 * di kanan-atas). Toolbar adalah elemen `pointer-events-auto`; node yang berada
 * di bawahnya tidak bisa diklik/digeser (ditemukan spec C3/C4: klik pada kartu
 * pertama mendarat di tombol toolbar, bukan di node). Contoh dimulai di bawah
 * dan di kiri area toolbar; pengguna yang menaruh node di bawah toolbar tetap
 * bisa menggeser kanvas untuk memindahkannya.
 */
const X_MAIN = 120;
const X_BRANCH = 440;
const Y_TOP = 280;

export function demoNodes(): FlowNode[] {
  return [
    {
      id: "demo-trigger",
      type: "trigger",
      position: { x: X_MAIN, y: Y_TOP },
      data: { kind: "trigger", label: "Mulai", config: { event: "Setiap jam 9 pagi" }, status: "initial" },
    },
    {
      id: "demo-agent",
      type: "agent",
      position: { x: X_MAIN, y: Y_TOP + 204 },
      data: {
        kind: "agent",
        label: "Rangkum Email",
        config: { model: "universal", prompt: "Rangkum email masuk hari ini jadi 3 poin." },
        status: "loading",
      },
    },
    {
      id: "demo-mcp",
      type: "mcp",
      position: { x: X_MAIN, y: Y_TOP + 408 },
      data: { kind: "mcp", label: "Kirim Telegram", config: { tool: "http_request" }, status: "success" },
    },
    {
      id: "demo-agent-2",
      type: "agent",
      position: { x: X_BRANCH, y: Y_TOP + 204 },
      data: {
        kind: "agent",
        label: "Balas Otomatis",
        config: { model: "deepseek-flash", prompt: "Balas email penting dengan nada sopan." },
        status: "error",
      },
    },
  ];
}

export function demoEdges(): Edge[] {
  return [
    { id: "demo-e1", source: "demo-trigger", target: "demo-agent", type: "flow", animated: true },
    { id: "demo-e2", source: "demo-agent", target: "demo-mcp", type: "flow", animated: false },
    { id: "demo-e3", source: "demo-agent", target: "demo-agent-2", type: "flow", animated: false },
  ];
}

export function demoWorkflow(): { nodes: FlowNode[]; edges: Edge[] } {
  return { nodes: demoNodes(), edges: demoEdges() };
}
