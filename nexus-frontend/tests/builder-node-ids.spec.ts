import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { dedupeGraph, nextNodeId, kindOf } from "../src/features/builder/node-graph";
import type { FlowNode } from "../src/features/builder/types";

/**
 * Regresi bug "node tidak muncul setelah drag" (duplicate React key).
 *
 * Bagian 1 = unit murni (tanpa browser) untuk `node-graph.ts`.
 * Bagian 2 = skenario browser nyata: workflow tersimpan BER-ID GANDA di-restore
 *            lalu node ditambahkan dari palette; sebelum perbaikan, node baru
 *            memakai id node lama sehingga React membuangnya.
 */

const BASE = "http://localhost:3000";

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
    );
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;


function node(id: string, kind = "agent"): FlowNode {
  return { id, type: kind, position: { x: 0, y: 0 }, data: { kind: kind as never } };
}

// ---------------------------------------------------------------------------
// 1. UNIT
// ---------------------------------------------------------------------------
test("unit: nextNodeId tidak pernah mengembalikan id yang sudah dipakai", () => {
  const taken = new Set<string>();
  for (let i = 0; i < 50; i++) {
    const id = nextNodeId("agent", taken);
    expect(taken.has(id), `id terulang: ${id}`).toBe(false);
    taken.add(id);
  }
  expect(taken.size).toBe(50);
});

test("unit: nextNodeId melewati id yang sudah ada (kasus restore agent-100)", () => {
  // Ini bentuk bug aslinya: kanvas sudah berisi id dari workflow tersimpan.
  const taken = new Set(["agent-100", "agent-101", "agent-102"]);
  for (let i = 0; i < 5; i++) {
    const id = nextNodeId("agent", taken);
    expect(["agent-100", "agent-101", "agent-102"]).not.toContain(id);
    taken.add(id);
  }
});

test("unit: dedupeGraph mempertahankan node tapi mengganti id ganda", () => {
  const g = dedupeGraph({
    nodes: [node("agent-100"), node("agent-100"), node("agent-100", "mcp")],
    edges: [],
  });
  const ids = g.nodes.map((n) => n.id);
  expect(g.nodes).toHaveLength(3);                       // TIDAK ada yang dibuang
  expect(new Set(ids).size).toBe(3);                     // id unik semua
  expect(ids[0]).toBe("agent-100");                      // kemunculan pertama utuh
  expect(g.renamedNodes).toBe(2);
});

test("unit: dedupeGraph menutup celah id kosong dan melengkapi type", () => {
  const g = dedupeGraph({ nodes: [{ id: "", position: { x: 0, y: 0 }, data: { kind: "trigger" } } as FlowNode], edges: [] });
  expect(g.nodes).toHaveLength(1);
  expect(g.nodes[0].id).toBeTruthy();
  expect(g.nodes[0].type).toBe("trigger");
  expect(g.renamedNodes).toBe(1);
});

test("unit: dedupeGraph membuang edge ganda dan edge yatim", () => {
  const nodes = [node("agent-1"), node("agent-2")];
  const edges = [
    { id: "e1", source: "agent-1", target: "agent-2" },
    { id: "e1", source: "agent-1", target: "agent-2" },   // id ganda
    { id: "e2", source: "agent-1", target: "hantu" },     // node tidak ada
    { id: "e3", source: "agent-1", target: "agent-2" },
  ] as never[];
  const g = dedupeGraph({ nodes, edges });
  expect(g.edges.map((e) => e.id)).toEqual(["e1", "e3"]);
  expect(g.droppedEdges).toBe(2);
});

test("unit: kindOf membaca data.kind lalu prefix id lalu type", () => {
  expect(kindOf(node("agent-9"))).toBe("agent");
  expect(kindOf({ id: "x-1", type: "trigger", data: { kind: "trigger" } } as FlowNode)).toBe("trigger");
  expect(kindOf({ id: "agent-7", type: "mcp", data: {} } as unknown as FlowNode)).toBe("mcp");
  expect(kindOf({ id: "n1", type: "trigger", data: { kind: "trigger" } } as FlowNode)).toBe("trigger");
});

test("unit: dedupeGraph tidak mengubah objek input", () => {
  const input = [node("dup"), node("dup")];
  const snapshot = JSON.stringify(input);
  dedupeGraph({ nodes: input, edges: [] });
  expect(JSON.stringify(input)).toBe(snapshot);
});

// ---------------------------------------------------------------------------
// 2. BROWSER (skenario nyata) -- TANPA menulis ke backend
// ---------------------------------------------------------------------------
// Kenapa lewat localStorage, bukan POST /workflows: /builder me-restore
// `workflows[0]` untuk SEMUA spec, jadi menaruh workflow uji di server membuat
// spec lain (builder.spec.ts) ikut me-restore node uji saya dan gagal karena
// alasan yang tidak ada hubungannya. Draf AI di localStorage melewati jalur
// store yang sama (replaceWork -> dedupeGraph) tanpa meninggalkan jejak.
const PENDING_KEY = "katalir.workflow.pending.v1";

async function gotoBuilder(page: Page) {
  await page.goto(`${BASE}/builder`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".react-flow__node", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(4000);
}

/** Seed draf AI ber-id GANDA (state "draft lama" yang korup) + sesi login. */
async function seedDuplicateDraft(page: Page) {
  const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
  const draft = {
    name: "REG-DUP-ID",
    nodes: [
      { id: "agent-100", type: "agent", position: { x: 120, y: 160 }, data: { kind: "agent", label: "Agent" } },
      { id: "agent-100", type: "agent", position: { x: 420, y: 160 }, data: { kind: "agent", label: "Agent" } },
      { id: "agent-101", type: "agent", position: { x: 720, y: 160 }, data: { kind: "agent", label: "Agent" } },
    ],
    edges: [{ id: "e-dup", source: "agent-100", target: "agent-101" }],
  };
  await page.addInitScript(
    (kv: { lsKey: string; session: unknown; pendingKey: string; draft: unknown }) => {
      try {
        window.localStorage.setItem(kv.lsKey, JSON.stringify(kv.session));
        window.localStorage.setItem(kv.pendingKey, JSON.stringify(kv.draft));
      } catch { /* abaikan */ }
    },
    { lsKey: LS_KEY, session: sess, pendingKey: PENDING_KEY, draft }
  );
}

test("regresi: draft lama ber-id ganda -> tambah node selalu muncul, 0 duplicate key", async ({ page }) => {
  // 180s: prod build + restore lewat jaringan + 3 klik; timeout default 60s
  // terbukti kurang dan menghasilkan kegagalan "timeout" tanpa info.
  test.setTimeout(180000);
  const errs: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 300)); });
  page.on("pageerror", (e) => errs.push("PAGEERROR " + String(e).slice(0, 200)));

  console.log("STEP=seed-draft");
  await seedDuplicateDraft(page);

  console.log("STEP=goto");
  await gotoBuilder(page);
  const restored = await page.$$eval(".react-flow__node", (els) => els.map((e) => e.getAttribute("data-id")));
  console.log("RESTORED_IDS=" + JSON.stringify(restored));
  // Draf berisi 3 node dengan 2 id kembar -> KETIGA node tetap ada, id unik.
  expect(restored.length, "draf ber-id ganda kehilangan node").toBe(3);
  expect(new Set(restored).size, `draft migration menyisakan id ganda: ${JSON.stringify(restored)}`).toBe(restored.length);

  // Tambah Trigger + Agent + MCP dari palette (klik = jalur addNode yang sama
  // dengan drop: drag memanggil onDropNode -> addNode).
  for (const idx of [0, 1, 2]) {
    console.log("STEP=click" + idx);
    await page.locator('[draggable="true"]').nth(idx).click({ timeout: 15000 });
    await page.waitForTimeout(900);
  }

  const ids = await page.$$eval(".react-flow__node", (els) => els.map((e) => e.getAttribute("data-id")));
  console.log("FINAL_IDS=" + JSON.stringify(ids));
  console.log("DOM_COUNT=" + ids.length + " UNIQUE=" + new Set(ids).size);

  expect(ids.length, `node baru tidak muncul: ${JSON.stringify(ids)}`).toBe(6);
  expect(new Set(ids).size, `ada id ganda: ${JSON.stringify(ids)}`).toBe(ids.length);

  const dup = errs.filter((e) => /same key|two children/i.test(e));
  console.log("DUP_KEY_ERR=" + dup.length);
  console.log("OTHER_ERR=" + JSON.stringify(errs.filter((e) => !/same key|two children/i.test(e)).slice(0, 3)));
  expect(dup).toHaveLength(0);
});


