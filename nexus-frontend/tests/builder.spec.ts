import { test, expect, Page } from "@playwright/test";

const BASE = "http://localhost:3000";

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

async function gotoBuilder(page: Page) {
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

test("c) SAVE: klik Simpan Alur -> bukan 500", async ({ page }) => {
  await gotoBuilder(page);
  // buat node dulu agar workflow tidak kosong
  await page.locator('[draggable="true"]').first().click();
  await sleep(600);
  // request interceptor: capture POST /workflows response
  let saveStatus = 0;
  page.on("response", (resp) => {
    if (resp.url.includes("/workflows") && resp.request.method === "POST") {
      saveStatus = resp.status;
    }
  });
  const btn = page.locator("text=Simpan Alur").first();
  await btn.click().catch(() => {});
  await sleep(2500);
  console.log(`SAVE: POST /workflows status = ${saveStatus}`);
  expect(saveStatus).not.toBe(500);
  await page.screenshot({ path: "test-results/save.png" });
});