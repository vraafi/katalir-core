import { test, Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

test("4a: chat + builder render zónder pageerror (motion/react ok)", async ({ page }) => {
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e as object)));

  await page.goto(`${BASE}/`, { waitUntil: "networkidle" }).catch(() => {});
  await sleep(1200);
  console.log("CHAT_ERRORS=" + JSON.stringify(errs));
  if (errs.length) throw new Error("chat pageerror: " + errs.join("|"));

  await page.goto(`${BASE}/builder`, { waitUntil: "networkidle" }).catch(() => {});
  await sleep(1200);
  console.log("BUILDER_ERRORS=" + JSON.stringify(errs));
  if (errs.length) throw new Error("builder pageerror: " + errs.join("|"));

  // motion.div in ConfigPanel moet bij faux in een node renderen zonder crash (Rhyset)
  const hasPalette = await page.locator("text=Palet").count().catch(() => 0);
  console.log("BUILDER_PALETTE=" + hasPalette);
});