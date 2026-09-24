import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Regresi: posisi node setelah DROP harus sama dengan titik drop.
 *
 * Bug nyata 2026-09-21: node muncul tapi menumpuk di pojok kiri-atas kanvas.
 * Sebabnya bukan state -- `node.position` BENAR (dan minimap ikut benar karena
 * dihitung dari state) -- melainkan CSS: `globals.css` memasang
 * `animation: node-spring-in ... both` pada `.react-flow__node`, sedangkan
 * keyframe-nya menganimasikan `transform`. Deklarasi animasi mengalahkan
 * inline style, jadi `transform: translate(x,y)` milik React Flow ditimpa
 * permanen oleh `transform: scale(1)` dari keyframe terakhir.
 *
 * Spec ini karena itu mengukur HAL YANG DILIHAT USER (pusat node di layar vs
 * titik drop), bukan angka di store -- store sudah benar sejak awal, sehingga
 * tes yang hanya membaca store tidak akan pernah menangkap bug ini.
 */

const BASE = "http://localhost:3000";
const CANVAS = ".react-flow";
const TOLERANCE_PX = 15;

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

/** Login sebagai user uji supaya tidak ada 401 dari /workflows atau /models. */
async function seedSession(page: Page) {
  const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: LS_KEY, value: sess }
  );
}

type NodeBox = { id: string; center: [number, number]; transform: string };


async function readNodes(page: Page): Promise<NodeBox[]> {
  return page.$$eval(".react-flow__node", (els) =>
    els.map((el) => {
      const b = el.getBoundingClientRect();
      return {
        id: el.getAttribute("data-id") ?? "",
        center: [Math.round(b.x + b.width / 2), Math.round(b.y + b.height / 2)] as [number, number],
        transform: getComputedStyle(el).transform,
      };
    })
  );
}

/** Drop node pada titik client tertentu (DragEvent nyata dengan dataTransfer). */
async function dropAt(page: Page, x: number, y: number, kind: string) {
  await page.evaluate(
    ({ x, y, kind }) => {
      const rf = document.querySelector(".react-flow");
      if (!rf) throw new Error("canvas tidak ditemukan");
      const dt = new DataTransfer();
      dt.setData("application/reactflow", kind);
      const mk = (type: string) =>
        new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y });
      rf.dispatchEvent(mk("dragover"));
      rf.dispatchEvent(mk("drop"));
    },
    { x, y, kind }
  );
  await page.waitForTimeout(700);
}

// ---------------------------------------------------------------------------
// 1. GUARD CSS (tanpa browser) -- mencegah akar masalah kembali
// ---------------------------------------------------------------------------
test("unit: animasi transform TIDAK boleh dipasang pada .react-flow__node", () => {
  const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf-8");
  const nodes = readFileSync(join(process.cwd(), "src/features/builder/nodes.tsx"), "utf-8");

  // Semua blok `selector { ... }` + isinya.
  const blocks = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selector: m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim(),
    body: m[2],
  }));

  const animOnNodeWrapper = blocks.filter(
    (b) =>
      b.selector.split(",").some((s) => s.trim().endsWith(".react-flow__node")) &&
      /(^|[;\s])animation\s*:/.test(b.body)
  );
  expect(
    animOnNodeWrapper.map((b) => b.selector),
    "animasi pada .react-flow__node menimpa transform inline React Flow (node menumpuk di pojok)"
  ).toEqual([]);

  // Animasi spring tetap ada, tetapi pada KARTU DI DALAM node.
  const card = blocks.find((b) => /\.node-card-enter/.test(b.selector));
  expect(card, "animasi spring kartu node hilang").toBeTruthy();
  expect(card!.selector).toContain(".react-flow__node");
  expect(/(^|[;\s])animation\s*:/.test(card!.body)).toBe(true);

  // Kelas itu harus benar-benar dipakai oleh node, kalau tidak animasinya mati.
  expect(nodes, "node tidak memakai kelas node-card-enter").toContain("node-card-enter");
});

// ---------------------------------------------------------------------------
// 2. BROWSER: 5 titik drop -> pusat node = titik drop
// ---------------------------------------------------------------------------
test("regresi: node muncul PERSIS di titik drop (5 titik + minimap konsisten)", async ({ page }) => {
  test.setTimeout(180000);
  const errs: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 200)); });
  page.on("pageerror", (e) => errs.push("PAGEERROR " + String(e).slice(0, 160)));

  await seedSession(page);
  await page.goto(`${BASE}/builder`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(CANVAS, { timeout: 40000 });
  await page.waitForTimeout(5000);

  const box = await page.locator(CANVAS).first().boundingBox();
  expect(box, "canvas tidak punya ukuran").toBeTruthy();

  const frac: Array<[string, number, number, string]> = [
    ["tengah", 0.5, 0.5, "trigger"],
    ["kiri-atas", 0.15, 0.15, "agent"],
    ["kanan-bawah", 0.85, 0.85, "mcp"],
    ["kanan-atas", 0.85, 0.15, "trigger"],
    ["kiri-bawah", 0.15, 0.85, "agent"],
  ];

  const measured: Array<{ label: string; drop: [number, number]; center: [number, number] }> = [];
  for (const [label, fx, fy, kind] of frac) {
    const x = Math.round(box!.x + box!.width * fx);
    const y = Math.round(box!.y + box!.height * fy);
    const before = (await readNodes(page)).length;
    await dropAt(page, x, y, kind);
    const nodes = await readNodes(page);
    expect(nodes.length, `drop ${label} tidak menambah node`).toBe(before + 1);
    const last = nodes[nodes.length - 1];
    console.log(`DROP ${label} client=[${x},${y}] center=${JSON.stringify(last.center)} transform=${last.transform}`);
    measured.push({ label, drop: [x, y], center: last.center });
  }

  // (a) setiap node muncul DI titik drop
  for (const m of measured) {
    const dx = Math.abs(m.center[0] - m.drop[0]);
    const dy = Math.abs(m.center[1] - m.drop[1]);
    expect(
      Math.max(dx, dy),
      `node "${m.label}" tidak di titik drop: drop=${JSON.stringify(m.drop)} center=${JSON.stringify(m.center)}`
    ).toBeLessThanOrEqual(TOLERANCE_PX);
  }

  // (b) node TIDAK menumpuk: semua pusat berbeda
  const keys = measured.map((m) => m.center.join(","));
  expect(new Set(keys).size, `node menumpuk di posisi sama: ${JSON.stringify(keys)}`).toBe(keys.length);

  // (c) transform inline React Flow tidak dinolkan oleh CSS
  const all = await readNodes(page);
  const zeroed = all.filter((n) => n.transform === "none" || n.transform === "matrix(1, 0, 0, 1, 0, 0)");
  expect(zeroed.map((n) => n.id), "transform node dinolkan (animasi/CSS menimpa posisi)").toEqual([]);

  // (d) minimap ikut menunjukkan node yang tersebar (bukan satu titik)
  const mm = await page.$$eval(".react-flow__minimap-node", (els) =>
    els.map((el) => {
      const b = el.getBoundingClientRect();
      return [Math.round(b.x), Math.round(b.y)].join(",");
    })
  );
  console.log("MINIMAP_POSITIONS=" + JSON.stringify(mm));
  expect(new Set(mm).size, "minimap menumpuk node di satu titik").toBeGreaterThan(3);

  console.log("ERRS=" + JSON.stringify(errs.slice(0, 3)));
  expect(errs).toHaveLength(0);
});

