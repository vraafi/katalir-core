import { test } from "@playwright/test";

/** Diagnostic: which element is wider than the viewport, and by how much. */
test("find mobile overflow culprit", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/integrations", { waitUntil: "load" });
  await page.waitForSelector('[data-testid^="source-tab-"]');
  await page.waitForTimeout(2500);

  const culprits = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const out: Array<{ tag: string; cls: string; testid: string; w: number; right: number }> = [];
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const r = el.getBoundingClientRect();
      if (r.width > vw + 1 || r.right > vw + 1) {
        out.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.getAttribute("class") || "").slice(0, 70),
          testid: el.getAttribute("data-testid") || "",
          w: Math.round(r.width),
          right: Math.round(r.right),
        });
      }
    }
    return { vw, scrollWidth: document.documentElement.scrollWidth, out: out.slice(0, 12) };
  });
  console.log("VIEWPORT", culprits.vw, "SCROLLWIDTH", culprits.scrollWidth);
  for (const c of culprits.out) console.log(`  ${c.tag} w=${c.w} right=${c.right} testid=${c.testid} cls=${c.cls}`);
});
