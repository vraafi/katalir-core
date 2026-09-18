import { test, expect, Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

test("3c3: chat page load — no page error + URL ?s state", async ({ page }) => {
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e as object)));

  await page.goto(`${BASE}/?s=sess-123`, { waitUntil: "networkidle" }).catch(() => {});
  await sleep(1500);

  const search = await page.evaluate(() => window.location.search);
  console.log("URL_SEARCH=" + search);
  const hasShell = await page.locator("text=Katalir").count();
  console.log("SHELL_KATALIR=" + hasShell);

  console.log("PAGE_ERRORS=" + JSON.stringify(errs));
  // 0 errors = nuqs+Suspense intact + geen crash (backend 401 is ok voor leeg).
  expect(errs).toHaveLength(0);
  expect(hasShell).toBeGreaterThan(0);
  await page.screenshot({ path: "test-results/3c3-chat.png" });
});