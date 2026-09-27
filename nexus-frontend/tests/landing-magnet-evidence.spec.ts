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
    // Worst single-tile overshoot past the cursor, in px. Bounded, not zero:
    // a soft spring always overshoots a little, and that is the requested feel.
    let worstOvershoot = 0;
    // Closest centre-to-centre distance seen between two neighbouring cards
    // across the whole sweep. This is the collision solver's real output and
    // is what proves the tiles BOUNCE (stay at contact distance) rather than
    // merge (collapse toward zero).
    let minContact = Infinity;
    for (const p of probes) {
      await page.mouse.move(p.x, p.y);
      await page.waitForTimeout(900);
      const moved = await centres();
      const disp = moved.map((m, i) => Math.hypot(m.x - settled[i].x, m.y - settled[i].y));
      report[p.name] = Number(Math.max(...disp).toFixed(1));

      // Overshoot measurement. The ORIGINAL check here asserted zero tiles ever
      // end up further from the cursor than they started, because the old force
      // was clamped to `Math.min(1, ...)` and a tile could not travel past the
      // cursor. That clamp is now deliberately GONE: the brief asks for a soft
      // spring, and an underdamped spring overshoots its target by definition.
      // So "zero overshoot" is no longer the right invariant.
      //
      // The invariant that IS right: overshoot must be BOUNDED. A few px past
      // the cursor is the flowing bounce. Overshooting far past it is the
      // vibration artefact the old comment warned about (a dozen tiles buzzing
      // rather than a shoal). So measure the worst overshoot in px and bound
      // that, rather than counting events and demanding none.
      for (let i = 0; i < moved.length; i++) {
        const d0 = Math.hypot(settled[i].x - p.x, settled[i].y - p.y);
        const d1 = Math.hypot(moved[i].x - p.x, moved[i].y - p.y);
        if (d1 > d0 + 1.5) {
          overshoots++;
          worstOvershoot = Math.max(worstOvershoot, d1 - d0);
        }
      }

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
        // The old test asserted `maxD <= gap/2` (a ~10.75px ceiling) and
        // `overlaps === 0`. Both are gone: the brief now asks for a DRAMATIC
        // field where tiles travel 30-50px and visibly BOUNCE off each other.
        // A zero-overlap assertion would forbid the exact effect that was
        // requested, and the old travel ceiling is what made the field look
        // inert in the first place.
        //
        // What is still a real defect, and is asserted instead:
        //   - every probe must move the field (no dead zones), and
        //   - travel must actually be dramatic, not merely non-zero.
        let maxD = 0;
        let minNeighbour = Infinity;
        let fused = 0;
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
            // Centre-to-centre distance of the two cards, which is the
            // quantity the collision solver actually maintains.
            const d = Math.hypot(
              a.cx + a.dx - (c.cx + c.dx),
              a.cy + a.dy - (c.cy + c.dy),
            );
            if (d < minNeighbour) minNeighbour = d;
            // FUSING is the failure mode to forbid: two cards collapsing into
            // one indistinguishable blob. The solver's contact distance is
            // cardWidth * 0.86, so a pair materially closer than the card
            // width means the glyphs are on top of each other, not touching.
            if (d < rest[0].w * 0.7) fused++;
          }
        }
        return {
          maxD: +maxD.toFixed(2),
          minNeighbour: minNeighbour === Infinity ? null : +minNeighbour.toFixed(2),
          fused,
        };
      });
      maxDisplacement = Math.max(maxDisplacement, geom.maxD);
      totalOverlaps += geom.fused;
      if (geom.minNeighbour !== null) {
        minContact = Math.min(minContact, geom.minNeighbour);
      }

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

    console.log("MAGNETIC", JSON.stringify({ ...report, overshoots, worstOvershoot: +worstOvershoot.toFixed(1), maxDisplacement, fusedPairs: totalOverlaps, minContact, ...reach }));

    // The old assertion here was `some probe > 80px`, then a `gap/2` ceiling and
    // `overlaps === 0`. That encoded a deliberately COOL field, and it is the
    // opposite of what was asked for. The brief now wants a dramatic pull where
    // tiles travel 30-50px and visibly bounce off one another.
    //
    // So the invariants are inverted, not deleted:
    //   - every probe must move the field (no dead zones), AND
    //   - the peak travel must be DRAMATIC, not merely non-zero, AND
    //   - tiles must not FUSE (collapse into one blob).
    //
    // "Every probe" rather than "some probe" stays load-bearing: with a stale
    // centre cache two of three probes read 0.0px and the suite still passed,
    // because only one probe had to exceed the threshold.
    const dead = Object.entries(report)
      .filter(([, v]) => v <= 0.5)
      .map(([k]) => k);
    expect(
      dead,
      `magnet dead at ${dead.length}/${Object.keys(report).length} probes: ${JSON.stringify(report)}`,
    ).toEqual([]);
    // The drama floor. The previous bar was 3px, which any drift cleared; 25px
    // is the brief's stated minimum and is an order of magnitude above the old
    // ~10.75px ceiling, so this fails loudly if the field regresses to a drift.
    expect(
      maxDisplacement,
      `field is not dramatic: peak travel was only ${maxDisplacement}px`,
    ).toBeGreaterThan(25);
    // FUSING is the one thing that must never happen: cards collapsing into a
    // single unreadable blob. Contact at ~0.86x the card width is the intended
    // look; anything under 0.7x means glyphs are on top of each other.
    expect(totalOverlaps, `${totalOverlaps} neighbouring card pairs fused into a blob`).toBe(0);
    // The bounce itself: some pair must have been pushed to real contact. If the
    // field never actually collides, the physics is decorative, not dramatic.
    expect(
      minContact,
      `no collision ever occurred - closest neighbour pair stayed ${minContact}px apart`,
    ).toBeLessThan(48);
    // Bounded overshoot, not zero. A soft underdamped spring always travels a
    // little past its target; that IS the requested "flowing" feel. What must
    // not happen is a tile flying far past the cursor and out the other side,
    // which is the vibration artefact rather than a bounce. The bound is
    // generous (well above a normal spring's ~10% overshoot) but far below the
    // distance a tile can actually travel, so a runaway spring still fails.
    expect(
      worstOvershoot,
      `a tile overshot the cursor by ${worstOvershoot.toFixed(1)}px - the spring is ringing, not bouncing`,
    ).toBeLessThan(25);
  });
});
