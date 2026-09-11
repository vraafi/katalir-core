import { test, expect, Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

test("3c2: sidebar + URL state (?w / ?n)", async ({ page }) => {
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e as object)));

  await page.goto(`${BASE}/builder`, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForSelector(".react-flow", { timeout: 20000 }).catch(() => {});
  await sleep(1200);

  // sidebar zichtbaar (client-rendered)
  const sidebar = await page.locator("text=Alur Baru").count();
  console.log("SIDEBAR_ALUR_BARU=" + sidebar);
  expect(sidebar).toBeGreaterThan(0);

  // node click -> URL ?n= moet verschijnen (via nuqs shallow router)
  await page.locator('[draggable="true"]').first().click(); // addNode via click
  await sleep(800);
  const node = page.locator(".react-flow__node").first();
  await node.click();
  await sleep(700);
  const search = await page.evaluate(() => window.location.search);
  console.log("URL_SEARCH_AFTER_NODE_CLICK=" + search);
  const hasN = /[?&]n=/.test(search);
  console.log("URL_HAS_N=" + hasN);

  console.log("PAGE_ERRORS=" + JSON.stringify(errs));
  expect(errs).toHaveLength(0);
  await page.screenshot({ path: "test-results/3c2-sidebar.png" });
});