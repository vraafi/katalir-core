import { test, expect } from "@playwright/test";

/**
 * Evidence capture for the magnetic effect.
 *
 * The brief is explicit: "do not claim magnetic works without a video or
 * screenshot". A test that asserts a transform string changed proves the code
 * ran, not that the effect reads as a shoal gathering around the cursor. So
 * this captures a grid of before/after frames with the mouse in a known place,
 * and measures how far the surrounding tiles actually travelled.
 *
 * Not part of the pass/fail gate - it writes PNGs to f6-shots/magnet/.
 */
test.describe("magnetic evidence", () => {
  test.setTimeout(180_000);

  test("capture the fish-gathering effect around the cursor", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1500);

    const tile = page.getByTestId("mcp-logo").nth(0);
    const tb = (await tile.boundingBox())!;
    const cx = tb.x + tb.width / 2;
    const cy = tb.y + tb.height / 2;

    // Park the cursor somewhere empty in the hero and let the field settle.
    await page.mouse.move(200, 200);
    await page.waitForTimeout(900);
    const rest = await page.getByTestId("mcp-logo").evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      }),
    );
    await page.screenshot({ path: "f6-shots/magnet/00-at-rest.png" });

    // Move to the tile and capture the approach frame by frame.
    for (const [i, delay] of [80, 200, 500, 900].entries()) {
      await page.mouse.move(cx, cy);
      await page.waitForTimeout(delay);
      await page.screenshot({ path: `f6-shots/magnet/0${i + 1}-t+${delay}ms.png` });
    }

    const moved = await page.getByTestId("mcp-logo").evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      }),
    );

    // How far did each tile travel, and is the near one further out than the
    // far ones? That gradient IS the effect - a uniform shift would be the
    // whole grid translating, not tiles converging on the cursor.
    const disp = moved.map((p, i) => Math.hypot(p.x - rest[i].x, p.y - rest[i].y));
    const d = (p: number) => Math.hypot(p.x - cx, p.y - cy);
    const near = disp.filter((_, i) => d(moved[i]) < 100);
    const far = disp.filter((_, i) => d(moved[i]) > 250);

    console.log(
      "MAGNETIC",
      JSON.stringify({
        tiles: disp.length,
        maxDisplacementPx: Math.max(...disp).toFixed(1),
        meanNearPx: (near.reduce((a, b) => a + b, 0) / Math.max(near.length, 1)).toFixed(1),
        meanFarPx: (far.reduce((a, b) => a + b, 0) / Math.max(far.length, 1)).toFixed(1),
      }),
    );
    expect(Math.max(...disp), "no tile moved at all").toBeGreaterThan(5);
  });
});
