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

  test("measure the magnetic effect across the whole hero", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1500);

    const centres = () =>
      page.getByTestId("mcp-logo").evaluateAll((els) =>
        els.map((el) => {
          const r = el.getBoundingClientRect();
          return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }),
      );

    // Park the cursor far from any logo and let the field settle to rest.
    await page.mouse.move(5, 895);
    await page.waitForTimeout(1000);
    const rest = await centres();
    await page.screenshot({ path: "f6-shots/magnet/00-at-rest.png" });

    // Sweep the cursor across a grid of positions and record the peak travel at
    // each one. Sweeping matters: the layout puts logos in 3 widely spaced rows,
    // so the peak depends heavily on WHERE the cursor is. Sampling a single
    // convenient spot produced a number that was true and meaningless.
    const probes = [
      { name: "on-a-tile", x: rest[10].x, y: rest[10].y },
      { name: "between-rows", x: rest[10].x + 300, y: (rest[10].y + rest[31].y) / 2 },
      { name: "mid-hero", x: 700, y: 450 },
    ];

    const report: Record<string, number> = {};
    let overshoots = 0;
    let frame = 0;
    for (const p of probes) {
      await page.mouse.move(p.x, p.y);
      await page.waitForTimeout(900);
      const moved = await centres();
      const disp = moved.map((m, i) => Math.hypot(m.x - rest[i].x, m.y - rest[i].y));
      report[p.name] = Number(Math.max(...disp).toFixed(1));

      // A tile must never end up further from the cursor than it started. An
      // unclamped force above 1.0 sends it past the cursor and out the far side.
      // Measured per probe, against THIS probe's cursor - comparing every probe
      // against one shared snapshot of the field is meaningless.
      overshoots += moved.filter((m, i) => {
        const d0 = Math.hypot(rest[i].x - p.x, rest[i].y - p.y);
        return Math.hypot(m.x - p.x, m.y - p.y) > d0 + 1.5;
      }).length;

      await page.screenshot({ path: `f6-shots/magnet/0${++frame}-${p.name}.png` });
    }

    // How much of the hero actually reacts? With rows spread across the full
    // height, the cursor is often further than `radius` from every logo, and
    // then nothing moves at all. Reporting this number is the point: it is the
    // honest cost of combining small tiles with a full-height field.
    const reach = await page.evaluate(() => {
      const hero = document.querySelector('[data-testid="hero-section"]')!.getBoundingClientRect();
      const els = Array.from(document.querySelectorAll('[data-testid="mcp-logo"]'));
      let dead = 0;
      let total = 0;
      for (let y = hero.top + 20; y < hero.bottom - 20; y += 40) {
        for (let x = hero.left + 20; x < hero.right - 20; x += 40) {
          total++;
          const near = els.some((el) => {
            const r = el.getBoundingClientRect();
            return Math.hypot(r.left + r.width / 2 - x, r.top + r.height / 2 - y) < 250;
          });
          if (!near) dead++;
        }
      }
      return { deadPct: +((dead / total) * 100).toFixed(1), samples: total };
    });

    console.log("MAGNETIC", JSON.stringify({ ...report, overshoots, ...reach }));
    expect(Object.values(report).some((v) => v > 80), `no probe exceeded 80px: ${JSON.stringify(report)}`).toBe(true);
    expect(overshoots, `${overshoots} tiles passed through the cursor`).toBe(0);
  });
});
