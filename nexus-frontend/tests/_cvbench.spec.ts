import { test } from "@playwright/test";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

// Deterministic benchmark of the freeze mechanism: 400 message-rows layout cost
// WITH content-visibility (the fix) vs WITHOUT (baseline). No app/backend/auth
// needed — isolated layout cost (OpenHands #12707 / llama.cpp #26083).
const N = process.env.BENCH_N || 400;
test("layout cost 400 rows: CV vs plain", async ({ page }) => {
  const url = pathToFileURL(resolve("./_cv-bench.html")).href;
  const runs: any[] = [];
  for (let r = 0; r < 5; r++) {
    await page.goto(url);
    const res = await page.evaluate((n: number) => (window as any).__run(n), Number(N));
    runs.push(res);
  }
  const avg = (k: string) => Math.round(runs.reduce((a, b) => a + b[k].tLayout, 0) / runs.length);
  const avgBuild = (k: string) => Math.round(runs.reduce((a, b) => a + b[k].tBuild, 0) / runs.length);
  console.log("N=" + N);
  console.log("LAYOUT_MS withCV=" + avg("withCV") + " withoutCV=" + avg("withoutCV"));
  console.log("BUILD_MS   withCV=" + avgBuild("withCV") + " withoutCV=" + avgBuild("withoutCV"));
  console.log("RATIO=" + (avg("withoutCV") / Math.max(1, avg("withCV"))).toFixed(1) + "x faster (CV)");
});