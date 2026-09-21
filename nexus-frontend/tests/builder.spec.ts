import { test, expect, Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const BASE = "http://localhost:3000";

/**
 * Sesi login disuntikkan SEBELUM navigasi.
 *
 * Dulu spec ini berjalan TANPA sesi, sehingga "Simpan Alur" dibalas 401 oleh
 * backend -- dan tes tetap hijau karena assertion-nya hanya `not.toBe(500)`
 * (terbukti: log lama mencetak `SAVE: POST /workflows status = 0`). Tes yang
 * tidak memverifikasi status sukses = tes kosong; itu juga sebabnya
 * penumpukan baris "Draft Workflow" di DB tidak pernah terlihat.
 */
function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

async function seedSession(page: Page) {
  const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: `sb-${supabaseRef()}-auth-token`, value: sess }
  );
}

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

async function gotoBuilder(page: Page) {
  await seedSession(page);
  await page.goto(`${BASE}/builder`, { waitUntil: "networkidle" }).catch(() => {});
  // ReactFlow renderi; wait canvas + palette visible
  await page.waitForSelector(".react-flow", { timeout: 20000 }).catch(() => {});
  await page.waitForSelector('[draggable="true"]', { timeout: 20000 }).catch(() => {});
  await sleep(1200);
}

async function countNodes(page: Page): Promise<number> {
  const els = await page.locator(".react-flow__node, [data-id]").count().catch(() => 0);
  return els;
}

async function canvasRect(page: Page) {
  return await page.locator(".react-flow").first().boundingBox();
}

test("a) DRAG: palette Trigger -> canvas pas posisi", async ({ page }) => {
  await gotoBuilder(page);
  const palette = page.locator('[draggable="true"]').first();
  const pb = await palette.boundingBox();
  expect(pb).toBeTruthy();
  const canvas = await canvasRect(page);
  expect(canvas).toBeTruthy();

  const before = await countNodes(page);
  const cx = canvas!.x + canvas!.width * 0.5;
  const cy = canvas!.y + canvas!.height * 0.5;

  // simulasikan drag: from palette center to canvas center
  await page.mouse.move(pb!.x + pb!.width / 2, pb!.y + pb!.height / 2);
  await page.mouse.down();
  await sleep(150);
  await page.mouse.move(cx, cy, { steps: 8 });
  await sleep(150);
  await page.mouse.up();
  await sleep(1200);

  const after = await countNodes(page);
  expect(after).toBeGreaterThan(before);

  // posisi node baru
  const nodes = await page.locator(".react-flow__node").all();
  const last = nodes[nodes.length - 1];
  const nb = await last.boundingBox();
  expect(nb).toBeTruthy();
  const dx = Math.abs(nb!.x + nb!.width / 2 - cx);
  const dy = Math.abs(nb!.y + nb!.height / 2 - cy);
  console.log(`DRAG: canvas(${cx},${cy}) node(${nb!.x + nb!.width / 2},${nb!.y + nb!.height / 2}) dx=${Math.round(dx)} dy=${Math.round(dy)}`);
  // tolerance ±150 (zoom/offset)
  expect(dx).toBeLessThan(150);
  expect(dy).toBeLessThan(150);
  await page.screenshot({ path: "test-results/drag.png" });
});

test("b) PAN: drag empty canvas moves node", async ({ page }) => {
  await gotoBuilder(page);
  // pastikan punya node (drag create one via palette click)
  await page.locator('[draggable="true"]').first().click();
  await sleep(800);
  const node0 = await page.locator(".react-flow__node").first().boundingBox().catch(() => null);
  expect(node0).toBeTruthy();

  const canvas = await canvasRect(page);
  // drag from empty area (top area of canvas, left offset behind minimap)
  const sx = canvas!.x + 60;
  const sy = canvas!.y + 40;
  const ex = sx + 120;
  const ey = sy + 80;
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await sleep(200);
  await page.mouse.move(ex, ey, { steps: 10 });
  await sleep(200);
  await page.mouse.up();
  await sleep(1000);

  const node1 = await page.locator(".react-flow__node").first().boundingBox().catch(() => null);
  console.log(`PAN: node0(${node0!.x},${node0!.y}) node1(${node1!.x},${node1!.y})`);
  const moved = Math.abs((node1?.x ?? node0!.x) - node0!.x) + Math.abs((node1?.y ?? node0!.y) - node0!.y);
  console.log(`PAN moved(total px)=${Math.round(moved)}`);
  expect(moved).toBeGreaterThan(5);
  await page.screenshot({ path: "test-results/pan.png" });
});

test("c) SAVE: klik Simpan Alur -> 201 dan TIDAK menumpuk baris", async ({ page }) => {
  test.setTimeout(120000);
  await gotoBuilder(page);
  // buat node dulu agar workflow tidak kosong
  await page.locator('[draggable="true"]').first().click();
  await sleep(600);

  // Rekam respons POST /workflows beserta body-nya. Sebelumnya tes ini hanya
  // mencetak `status = 0` (listener tidak pernah menangkap) dan
  // `expect(0).not.toBe(500)` selalu lulus -> tes kosong. Padahal setiap
  // eksekusi menyisakan SATU baris "Draft Workflow" di DB, dan penumpukan
  // itulah yang dulu dibersihkan dengan cara berbahaya (DELETE by name).
  const saves: Array<{ status: number; id?: string; updated?: boolean }> = [];
  page.on("response", async (resp) => {
    try {
      if (!resp.url().includes("/workflows")) return;
      if (resp.request().method() !== "POST") return;
      const body = await resp.json().catch(() => null);
      saves.push({
        status: resp.status(),
        id: body?.workflow?.id,
        updated: body?.updated,
      });
    } catch { /* abaikan */ }
  });

  await page.locator("text=Simpan Alur").first().click().catch(() => {});
  await sleep(3000);
  const first = saves[0];
  console.log(`SAVE: status=${first?.status} updated=${first?.updated} id=${(first?.id ?? "").slice(0, 8)}`);
  expect(first?.status, "POST /workflows tidak pernah tertangkap").toBe(201);
  expect(first?.updated).toBe(false);

  // Simpan lagi: harus UPDATE (bukan baris baru).
  await page.locator("text=Simpan Alur").first().click().catch(() => {});
  await sleep(2500);
  const second = saves[1];
  console.log(`SAVE2: status=${second?.status} updated=${second?.updated}`);
  expect(second?.status).toBe(201);
  expect(second?.updated, "simpan ulang membuat baris baru").toBe(true);
  expect(second?.id).toBe(first?.id);

  // BERSIHKAN: hapus baris yang dibuat tes ini (owner-scoped, lewat API dengan
  // token sesi yang sama) supaya tes tidak menumpuk data lagi.
  if (first?.id) {
    const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
    const api = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8123";
    const del = await page.request.delete(`${api}/workflows/${first.id}`, {
      headers: { Authorization: "Bearer " + sess.access_token },
    });
    console.log("CLEANUP_DELETE=" + del.status());
    expect(del.status(), "gagal membersihkan workflow uji").toBe(200);
  }
  await page.screenshot({ path: "test-results/save.png" });
});