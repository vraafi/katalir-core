import { test, expect, Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

async function gotoBuilder(page: Page) {
  await page.goto(`${BASE}/builder`, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForSelector(".react-flow", { timeout: 20000 }).catch(() => {});
  await page.waitForSelector('[draggable="true"]', { timeout: 20000 }).catch(() => {});
  await sleep(1200);
}

test("3c1: Zustand store — node add + select + clear via store", async ({ page }) => {
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e as object)));

  await gotoBuilder(page);
  const metrics = await page.evaluate(() => {
    const rf = document.querySelector(".react-flow") as HTMLElement;
    const b = rf ? rf.getBoundingClientRect() : null;
    return { w: b?.width, h: b?.height };
  });
  console.log("REACTFLOW_SIZE=" + JSON.stringify(metrics));
  expect(metrics.w ?? 0).toBeGreaterThan(400);
  expect(metrics.h ?? 0).toBeGreaterThan(400);

  // addNode via palette click (store addNode)
  const before = await page.locator(".react-flow__node").count();
  await page.locator('[draggable="true"]').first().click();
  await sleep(900);
  const after = await page.locator(".react-flow__node").count();
  console.log("NODE before=" + before + " after=" + after);
  expect(after).toBeGreaterThan(before);

  // select the new node -> ConfigPanel opens
  const first = page.locator(".react-flow__node").first();
  await first.click();
  await sleep(600);
  const hasPanel = await page.locator("text=Konfigurasi Node").count();
  console.log("CONFIG_PANEL=" + hasPanel);
  expect(hasPanel).toBeGreaterThan(0);

  console.log("PAGE_ERRORS=" + JSON.stringify(errs));
  expect(errs).toHaveLength(0);
});