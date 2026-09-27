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

    // Warm the field up BEFORE sampling, then re-snapshot rest. The very first
    // probe after a jump out of the parked corner read 0.0px even though a
    // tile sat ~24px away, because the field had never been activated and the
    // first sample is taken while the exponential lerp is still warming. A
    // measurement harness that reports the ramp-up as a dead region is
    // measuring itself, not the component.
    await page.mouse.move(720, 470);
    await page.waitForTimeout(1200);
    await page.mouse.move(5, 895);
    await page.waitForTimeout(1200);
    const settled = await centres();

    // Sweep a GRID across the hero, not a handful of hand-picked spots.
    //
    // The three original probes were chosen from `rest` itself - i.e. from
    // positions derived from the same measurement the code caches - and two of
    // the three measured exactly 0.0px while the third measured 10.7px. That
    // is the signature of a stale centre cache: the code was comparing the
    // cursor against centres measured against an older layout, so a whole band
    // of the hero was further than `radius` from every cached centre and the
    // magnet was dead there. Three hand-picked probes reported the field as
    // healthy because one of them happened to land on a still-valid region.
    //
    // A grid is the honest version of the same check: it samples the whole
    // field, and it is the assertion that would have caught this.
    const heroBox = await page.getByTestId("hero-section").boundingBox();
    expect(heroBox).not.toBeNull();
    const grid: { name: string; x: number; y: number }[] = [];
    for (let gy = 1; gy <= 4; gy++) {
      for (let gx = 1; gx <= 4; gx++) {
        grid.push({
          name: `g${gx}-${gy}`,
          x: Math.round(heroBox!.x + (heroBox!.width * gx) / 5),
          y: Math.round(heroBox!.y + (heroBox!.height * gy) / 5),
        });
      }
    }
    const probes = grid;

    const report: Record<string, number> = {};
    let overshoots = 0;
    let frame = 0;
    let maxDisplacement = 0;
    let totalOverlaps = 0;
    let worstOverlap = 0;
    for (const p of probes) {
      await page.mouse.move(p.x, p.y);
      await page.waitForTimeout(900);
      const moved = await centres();
      const disp = moved.map((m, i) => Math.hypot(m.x - settled[i].x, m.y - settled[i].y));
      report[p.name] = Number(Math.max(...disp).toFixed(1));

      // A tile must never end up further from the cursor than it started. An
      // unclamped force above 1.0 sends it past the cursor and out the far side.
      // Measured per probe, against THIS probe's cursor - comparing every probe
      // against one shared snapshot of the field is meaningless.
      overshoots += moved.filter((m, i) => {
        const d0 = Math.hypot(settled[i].x - p.x, settled[i].y - p.y);
        return Math.hypot(m.x - p.x, m.y - p.y) > d0 + 1.5;
      }).length;

      // Task D: the collision-free bound, measured from the laid-out grid. The
      // grid is `minmax(cell, 1fr)`, so columns stretch and the real pitch is
      // NOT cell+gap - at 1440x900 it is 74.5px across and 72px down. The bound
      // is therefore derived in the component from the measured pitch, and this
      // asserts the same invariant independently rather than a magic constant.
      const geom = await page.evaluate(() => {
        const els = Array.from(document.querySelectorAll('[data-testid="mcp-logo"]')).filter(
          (e) => (e as HTMLElement).offsetWidth > 0,
        );
        const rest = els.map((e) => {
          const r = e.getBoundingClientRect();
          const m = new DOMMatrix(getComputedStyle(e).transform);
          return {
            cx: r.left - m.m41 + r.width / 2,
            cy: r.top - m.m42 + r.height / 2,
            w: r.width,
            h: r.height,
            dx: m.m41,
            dy: m.m42,
          };
        });
        let minX = Infinity;
        let minY = Infinity;
        for (let i = 0; i < rest.length; i++) {
          for (let j = i + 1; j < rest.length; j++) {
            const dx = Math.abs(rest[i].cx - rest[j].cx);
            const dy = Math.abs(rest[i].cy - rest[j].cy);
            if (dy < 2 && dx > 2 && dx < minX) minX = dx;
            if (dx < 2 && dy > 2 && dy < minY) minY = dy;
          }
        }
        const free = Math.min(minX - rest[0].w, minY - rest[0].h);
        const limit = (free / 2) * 0.9;
        let maxD = 0;
        let overlaps = 0;
        let worst = 0;
        for (let i = 0; i < rest.length; i++) {
          maxD = Math.max(maxD, Math.hypot(rest[i].dx, rest[i].dy));
          for (let j = i + 1; j < rest.length; j++) {
            const a = rest[i];
            const c = rest[j];
            const rx = Math.abs(a.cx - c.cx);
            const ry = Math.abs(a.cy - c.cy);
            const isNeighbour =
              (Math.abs(rx - minX) < 3 && ry < 3) || (Math.abs(ry - minY) < 3 && rx < 3);
            if (!isNeighbour) continue;
            const ox = Math.min(a.cx + a.dx + a.w / 2, c.cx + c.dx + c.w / 2) -
              Math.max(a.cx + a.dx - a.w / 2, c.cx + c.dx - c.w / 2);
            const oy = Math.min(a.cy + a.dy + a.h / 2, c.cy + c.dy + c.h / 2) -
              Math.max(a.cy + a.dy - a.h / 2, c.cy + c.dy - c.h / 2);
            const o = Math.min(ox, oy);
            if (o > 0.5) {
              overlaps++;
              worst = Math.max(worst, o);
            }
          }
        }
        return { limit: +limit.toFixed(2), maxD: +maxD.toFixed(2), overlaps, worst: +worst.toFixed(2) };
      });
      maxDisplacement = Math.max(maxDisplacement, geom.maxD);
      totalOverlaps += geom.overlaps;
      worstOverlap = Math.max(worstOverlap, geom.worst);
      // 0.5px tolerance absorbs sub-pixel rounding in the matrix readback.
      expect(
        geom.maxD,
        `tile travelled ${geom.maxD}px, past the collision-free bound of ${geom.limit}px`,
      ).toBeLessThanOrEqual(geom.limit + 0.5);

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

    console.log("MAGNETIC", JSON.stringify({ ...report, overshoots, maxDisplacement, totalOverlaps, worstOverlap, ...reach }));

    // The old assertion here was `some probe > 80px`. It encoded the UNCLAMPED
    // behaviour: tiles used to travel up to 93px, which is 4x the 24px of free
    // space between two cards, so adjacent cards overlapped by ~20px. Asserting
    // a large travel figure was asserting the bug. The invariants that matter
    // are now: EVERY sampled point moves the field, no tile passes the
    // collision-free bound, no neighbour pair overlaps, and nothing overshoots
    // the cursor.
    //
    // "Every probe" rather than "some probe" is the load-bearing part. With a
    // stale centre cache two of three probes read 0.0px and the suite still
    // passed, because only one probe had to exceed the threshold.
    const dead = Object.entries(report)
      .filter(([, v]) => v <= 0.5)
      .map(([k]) => k);
    expect(
      dead,
      `magnet dead at ${dead.length}/${Object.keys(report).length} probes: ${JSON.stringify(report)}`,
    ).toEqual([]);
    expect(
      Math.max(...Object.values(report)),
      `field looks frozen: peak travel was only ${JSON.stringify(report)}px`,
    ).toBeGreaterThan(3);
    expect(totalOverlaps, `${totalOverlaps} neighbouring card pairs overlapped`).toBe(0);
    expect(worstOverlap).toBe(0);
    expect(overshoots, `${overshoots} tiles passed through the cursor`).toBe(0);
  });
});
