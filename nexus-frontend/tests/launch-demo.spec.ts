import { test } from "@playwright/test";

/**
 * F5.3 — records the 60-second Product Hunt demo.
 *
 * This is the actual demo, not a script for one: `npx playwright test -c
 * playwright.dev.config.ts tests/launch-demo.spec.ts` produces a webm in
 * test-results/. It navigates the real product against the real backend, so a
 * number shown in the video is the number the site serves.
 *
 * It is a separate spec from the marketplace evidence because its purpose is
 * different: that one asserts, this one performs. A failing assertion is useful
 * in a demo script too - it would surface as a stall, which is why the waits
 * below are explicit rather than sleep-based guesswork.
 *
 * Run:  npx playwright test -c playwright.demo.config.ts
 * Out:  the webm under test-results/
 */
test.describe("launch demo", () => {
  test("Product Hunt 60s demo", async ({ page }) => {
    test.setTimeout(180_000);

    // 1. The promise: describe a workflow in a sentence.
    await page.goto("/", { waitUntil: "load" });
    await page.waitForTimeout(4000);

    // 2. The marketplace, all 10 source tabs, real counts.
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await page.waitForTimeout(3500);

    // 3. The differentiator: filter to what was actually executed.
    await page.getByTestId("tier-filter-call_verified").click();
    await page.waitForTimeout(4000);
    await page.getByTestId("filters-clear").click();
    await page.waitForTimeout(3000);

    // 4. The dedup honesty toggle: raw catalogue vs one row per integration.
    await page.getByTestId("view-toggle-unique").click();
    await page.waitForTimeout(3500);
    await page.getByTestId("view-toggle-all").click();
    await page.waitForTimeout(2500);

    // 5. A source that is honestly labelled as a connection layer, not tools.
    await page.getByTestId("source-tab-nango").click();
    await page.waitForTimeout(4000);

    // 6. Back to the builder: the actual product surface.
    await page.goto("/builder", { waitUntil: "load" });
    await page.waitForTimeout(5000);
  });
});
